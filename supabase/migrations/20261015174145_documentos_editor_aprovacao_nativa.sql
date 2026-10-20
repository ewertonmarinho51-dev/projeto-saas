-- Experimental individual native approval; no legacy wizard/emission mutation.
begin;

alter table public.governanca_aprovacoes
  add column native_revision bigint,
  add column native_content_hash text,
  add column native_operation_id uuid,
  add column native_snapshot bytea,
  add column native_snapshot_sha256 text,
  add column native_evidence jsonb,
  add column native_sources jsonb,
  add constraint aprovacao_native_revision_fk foreign key (entidade_id,native_revision)
    references public.documentos_editor_revisoes(document_id,revision) on delete restrict,
  add constraint aprovacao_native_contract check (
    case when entidade_tipo = 'documento_editor' then
      native_revision is not null and native_revision > 0 and decisao = 'APROVADO'
      and native_content_hash is not null and native_content_hash ~ '^[0-9a-f]{64}$'
      and native_operation_id is not null and native_snapshot is not null
      and octet_length(native_snapshot) between 1 and 8388608
      and native_snapshot_sha256 is not null
      and native_snapshot_sha256 = encode(sha256(native_snapshot),'hex')
      and native_evidence is not null and jsonb_typeof(native_evidence) = 'object'
      and native_sources is not null and jsonb_typeof(native_sources) = 'object'
    else native_revision is null and native_content_hash is null
      and native_operation_id is null and native_snapshot is null
      and native_snapshot_sha256 is null and native_evidence is null and native_sources is null
    end) not valid; -- Unknown historical rows stay explicit; new writes must prove the contract.
create unique index aprovacao_native_operation on public.governanca_aprovacoes(native_operation_id)
  where native_operation_id is not null;
-- NULL revisions retain arbitrary legacy rows; the full index also serves
-- the composite FK lookup without depending on an entity-type predicate.
create unique index aprovacao_native_revision on public.governanca_aprovacoes(entidade_id,native_revision);

-- Extend the existing resolver, keeping the original role/scope rules.
create or replace function public.aprovacao_no_escopo(
  p_aprovacao uuid,p_tenant uuid,p_secretaria uuid,p_papel text)
returns boolean language plpgsql stable security definer set search_path = '' as $$
declare v_tipo text; v_alvo uuid; v_tenant uuid; v_sec uuid;
begin
  select ap.entidade_tipo,ap.entidade_id into v_tipo,v_alvo
    from public.governanca_aprovacoes ap where ap.id=p_aprovacao and ap.tenant_id=p_tenant;
  if not found then return false; end if;
  if v_tipo='versao' then
    select a.tenant_id,a.secretaria_id into v_tenant,v_sec from public.governanca_versoes v
      join public.governanca_artefatos a on a.id=v.artefato_id where v.id=v_alvo;
  elsif v_tipo='artefato' then
    select a.tenant_id,a.secretaria_id into v_tenant,v_sec from public.governanca_artefatos a where a.id=v_alvo;
  elsif v_tipo='documento_editor' then
    select d.tenant_id,p.secretaria_id into v_tenant,v_sec from public.documentos_editor d
      join public.processos p on p.id=d.processo_id where d.id=v_alvo;
  else return false;
  end if;
  if not found or v_tenant is distinct from p_tenant then return false; end if;
  return public.papel_alcanca_o_tenant(p_papel) or (v_sec is not null and v_sec=p_secretaria);
end $$;

create policy aprovacoes_native_insert_owner on public.governanca_aprovacoes
  as restrictive for insert to authenticated with check (entidade_tipo <> 'documento_editor');
create policy aprovacoes_native_select_scope on public.governanca_aprovacoes
  as restrictive for select to authenticated using (entidade_tipo <> 'documento_editor' or (
    (select public.documento_editor_sessao_valida()) and exists (
      select 1 from public.documentos_editor d where d.id=entidade_id)));

create function public.aprovacao_native_immutable()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  if old.entidade_tipo='documento_editor' or (tg_op='UPDATE' and new.entidade_tipo='documento_editor') then
    raise exception 'native approval is immutable' using errcode='42501';
  end if;
  if tg_op='DELETE' then return old; end if;
  return new;
end $$;
revoke all on function public.aprovacao_native_immutable() from public,anon,authenticated,service_role;
create trigger aprovacao_native_immutable before update or delete on public.governanca_aprovacoes
  for each row execute function public.aprovacao_native_immutable();

-- One SQL statement snapshot. The same function is rerun under short SHARE
-- locks by the private act; LIMIT is detected, never accepted as a full set.
create function public.documento_editor_fontes_aprovacao(p_document uuid,p_claims jsonb)
returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare v_process public.processos%rowtype; v_result jsonb;
  v_claims text := pg_catalog.current_setting('request.jwt.claims',true);
  v_visual boolean;
begin
  if p_claims->>'role' is distinct from 'authenticated' then
    raise exception 'document session required' using errcode='42501';
  end if;
  perform pg_catalog.set_config('request.jwt.claims',p_claims::text,true);
  if not coalesce(public.documento_editor_sessao_valida(),false) then
    raise exception 'document session required' using errcode='42501';
  end if;
  select p.* into v_process from public.documentos_editor d join public.processos p on p.id=d.processo_id
    where d.id=p_document and d.tenant_id=p.tenant_id;
  if not found or not coalesce(public.pode_ler_processo(v_process.tenant_id,v_process.secretaria_id),false) then
    raise exception 'document access denied' using errcode='42501';
  end if;
  select exists(select 1 from public.config_app where chave='flag_visual_policy_builder'
    and lower(btrim(valor)) in ('1','true','on','sim')) into v_visual;
  select pg_catalog.jsonb_build_object(
    'processo',pg_catalog.jsonb_build_object('id',v_process.id,'tenant_id',v_process.tenant_id,
      'secretaria_id',v_process.secretaria_id,'criado_em',v_process.criado_em,'dados',v_process.dados),
    'secretarias',(select coalesce(jsonb_agg(to_jsonb(t) order by t.id),'[]') from
      (select * from public.secretarias where tenant_id=v_process.tenant_id order by id limit 10001) t),
    'servidores',(select coalesce(jsonb_agg(to_jsonb(t) order by t.id),'[]') from
      (select * from public.servidores where tenant_id=v_process.tenant_id order by id limit 10001) t),
    'servidor_funcoes',(select coalesce(jsonb_agg(to_jsonb(t) order by t.id),'[]') from
      (select * from public.servidor_funcoes where tenant_id=v_process.tenant_id order by id limit 10001) t),
    'portarias',(select coalesce(jsonb_agg(to_jsonb(t) order by t.id),'[]') from
      (select * from public.portarias where tenant_id=v_process.tenant_id order by id limit 10001) t),
    'portaria_membros',(select coalesce(jsonb_agg(to_jsonb(t) order by t.id),'[]') from
      (select * from public.portaria_membros where tenant_id=v_process.tenant_id order by id limit 10001) t),
    'fatos_canonicos',(select coalesce(jsonb_agg(to_jsonb(t) order by t.id),'[]') from
      (select * from public.fatos_canonicos where tenant_id=v_process.tenant_id and processo_id=v_process.id
        order by id limit 10001) t),
    'regras_conhecimento',(select coalesce(jsonb_agg(to_jsonb(t) order by t.id),'[]') from
      (select * from public.regras_conhecimento where tenant_id is null or tenant_id=v_process.tenant_id
        order by id limit 10001) t),
    'fontes_conhecimento',(select coalesce(jsonb_agg(to_jsonb(t) order by t.id),'[]') from
      (select * from public.fontes_conhecimento where tenant_id is null or tenant_id=v_process.tenant_id
        order by id limit 10001) t),
    'config_app',(select coalesce(jsonb_agg(to_jsonb(t) order by t.chave),'[]') from
      (select chave,valor from public.config_app where chave='flag_visual_policy_builder') t),
    'governanca_artefatos',case when v_visual then
      (select coalesce(jsonb_agg(to_jsonb(t) order by t.id),'[]') from
        (select * from public.governanca_artefatos where tipo_artefato='politica'
          and (tenant_id is null or tenant_id=v_process.tenant_id)
          and (secretaria_id is null or secretaria_id=v_process.secretaria_id) order by id limit 10001) t)
      else '[]'::jsonb end,
    'governanca_versoes',case when v_visual then
      (select coalesce(jsonb_agg(to_jsonb(t) order by t.id),'[]') from
        (select v.* from public.governanca_versoes v join public.governanca_artefatos a on a.id=v.artefato_id
          where a.tipo_artefato='politica' and (a.tenant_id is null or a.tenant_id=v_process.tenant_id)
            and (a.secretaria_id is null or a.secretaria_id=v_process.secretaria_id)
            and v.status='PUBLISHED' order by v.id limit 10001) t)
      else '[]'::jsonb end) into v_result;
  perform pg_catalog.set_config('request.jwt.claims',coalesce(v_claims,''),true);
  return v_result;
end $$;
revoke all on function public.documento_editor_fontes_aprovacao(uuid,jsonb) from public,anon,authenticated;
grant execute on function public.documento_editor_fontes_aprovacao(uuid,jsonb) to service_role;

create function public.documento_editor_aprovar(
  p_document uuid,p_revision bigint,p_content_hash text,p_operation uuid,p_claims jsonb,
  p_sources jsonb,p_snapshot bytea,p_snapshot_sha256 text,p_evidence jsonb)
returns table(approval_id uuid,document_id uuid,revision bigint,content_hash text,operation_id uuid,
  snapshot_sha256 text,event_id uuid,replayed boolean)
language plpgsql security invoker set search_path = '' set lock_timeout='2s' set statement_timeout='5s' as $$
declare
  v_claims text := pg_catalog.current_setting('request.jwt.claims',true);
  v_actor uuid; v_role text; v_profile public.usuarios%rowtype; v_head public.documentos_editor%rowtype;
  v_process public.processos%rowtype; v_revision public.documentos_editor_revisoes%rowtype;
  v_previous public.governanca_aprovacoes%rowtype; v_approval uuid; v_event uuid; v_snapshot jsonb;
begin
  if p_document is null or p_operation is null or p_revision is null or p_revision<1
     or p_content_hash is null or p_content_hash !~ '^[0-9a-f]{64}$'
     or p_claims->>'role' is distinct from 'authenticated' then
    raise exception 'invalid approval binding' using errcode='22023';
  end if;
  perform pg_catalog.set_config('request.jwt.claims',p_claims::text,true);
  v_actor := auth.uid();
  -- Competence is checked before acquiring any lock, then rechecked while the
  -- canonical profile is held stable. JWT role revocation takes effect now.
  select * into v_profile from public.usuarios u where u.auth_user_id=v_actor;
  v_role := coalesce(nullif(v_profile.papel_governanca,''),case when v_profile.papel='admin' then 'admin_municipal' end);
  if not coalesce(public.documento_editor_sessao_valida(),false) or v_role is null
     or v_role is distinct from coalesce(nullif(p_claims->'app_metadata'->>'papel_governanca',''),
       case when p_claims->'app_metadata'->>'papel'='admin' then 'admin_municipal' end)
     or not ('aprovacao_registrada'=any(public.eventos_permitidos_ao_papel(v_role))) then
    raise exception 'review competence required' using errcode='42501';
  end if;
  select * into v_profile from public.usuarios u where u.auth_user_id=v_actor for share;
  if not v_profile.ativo or v_role is distinct from coalesce(nullif(v_profile.papel_governanca,''),
       case when v_profile.papel='admin' then 'admin_municipal' end)
     or not coalesce(public.documento_editor_sessao_valida(),false) then
    raise exception 'review competence revoked' using errcode='42501';
  end if;
  -- Match the existing auth admin fallback using the reconciled backend role;
  -- the canonical trail still receives an explicit controlled governance role.
  perform pg_catalog.set_config('request.jwt.claims',pg_catalog.jsonb_set(p_claims,
    '{app_metadata,papel_governanca}',to_jsonb(v_role))::text,true);
  select p.* into v_process from public.documentos_editor d join public.processos p on p.id=d.processo_id
    where d.id=p_document for share of p;
  if not found or v_process.tenant_id is distinct from public.tenant_do_jwt()
     or not (public.papel_alcanca_o_tenant(v_role) or
       (v_process.secretaria_id is not null and v_process.secretaria_id=public.secretaria_do_jwt()))
     or not coalesce(public.pode_ler_processo(v_process.tenant_id,v_process.secretaria_id),false) then
    raise exception 'review scope denied' using errcode='42501';
  end if;
  select * into v_head from public.documentos_editor d where d.id=p_document for update;
  if v_head.revision is distinct from p_revision or v_head.content_hash is distinct from p_content_hash then
    raise exception 'stale review revision' using errcode='40001';
  end if;
  select * into v_previous from public.governanca_aprovacoes a where a.native_operation_id=p_operation;
  if found then
    if (v_previous.entidade_id,v_previous.native_revision,v_previous.native_content_hash,v_previous.aprovador)
        is distinct from (p_document,p_revision,p_content_hash,v_actor)
       or (p_snapshot is not null and (v_previous.native_snapshot,v_previous.native_evidence,v_previous.native_sources)
         is distinct from (p_snapshot,p_evidence,p_sources)) then
      raise exception 'review operation differs' using errcode='40001';
    end if;
    select e.id into v_event from public.governanca_eventos e where e.entidade_tipo='aprovacao'
      and e.entidade_id=v_previous.id and e.tipo_evento='aprovacao_registrada' and e.ator=v_actor;
    if v_event is null or v_head.status<>'aprovado' then
      raise exception 'incomplete approval history' using errcode='40001';
    end if;
    perform pg_catalog.set_config('request.jwt.claims',coalesce(v_claims,''),true);
    return query select v_previous.id,p_document,p_revision,p_content_hash,p_operation,
      v_previous.native_snapshot_sha256,v_event,true;
    return;
  end if;
  if v_head.status not in ('rascunho','em_revisao') or coalesce(v_head.tipo=any(v_process.aprovados),false) then
    raise exception 'document already governed' using errcode='42501';
  end if;
  select * into v_revision from public.documentos_editor_revisoes r
    where r.document_id=p_document and r.revision=p_revision;
  if v_revision.block_index is null or v_revision.institutional_snapshot is null
     or v_revision.engine_build_sha256 is null or p_snapshot is null
     or octet_length(p_snapshot) not between 1 and 8388608
     or p_snapshot_sha256 is distinct from encode(sha256(p_snapshot),'hex') then
    raise exception 'native proof missing' using errcode='22023';
  end if;
  v_snapshot := convert_from(p_snapshot,'UTF8')::jsonb;
  if v_snapshot->>'phase' is distinct from 'approved'
     or v_snapshot->>'approved_revision' is distinct from p_revision::text
     or v_snapshot->>'approved_content_hash' is distinct from p_content_hash
     or v_snapshot->>'approved_engine_manifest_sha256' is distinct from v_revision.engine_build_sha256
     or v_snapshot->>'draft_reference_sha256' is distinct from v_revision.institutional_snapshot_sha256
     or ((v_snapshot - array['approved_revision','approved_content_hash','approved_engine_manifest_sha256',
       'draft_reference_sha256']) || '{"phase":"draft_reference"}'::jsonb)
       is distinct from convert_from(v_revision.institutional_snapshot,'UTF8')::jsonb
     or p_evidence->>'schema' is distinct from 'gc-wordcraft-approval/v1'
     or p_evidence->>'document_id' is distinct from p_document::text
     or p_evidence->>'revision' is distinct from p_revision::text
     or p_evidence->>'content_hash' is distinct from p_content_hash
     or p_evidence->>'engine_manifest_sha256' is distinct from v_revision.engine_build_sha256
     or p_evidence->>'coverage' is distinct from 'complete_textual_projection'
     or p_evidence->>'scope' is distinct from 'individual_revision_review'
     or p_evidence->'official_emission' is distinct from 'false'::jsonb
     or p_evidence->'gate'->'bloqueia' is distinct from 'false'::jsonb
     or p_evidence->'quality'->'criticos' is distinct from '[]'::jsonb
     or not coalesce((p_evidence->'quality'->>'score')::numeric between 75 and 100,false)
     or p_evidence->>'evaluated_at' is null
     or (p_evidence->>'evaluated_at')::timestamptz not between clock_timestamp()-interval '30 seconds'
       and clock_timestamp() then
    raise exception 'approval evidence differs' using errcode='22023';
  end if;
  -- Fixed order, all in one bounded lock acquisition. Includes exactly every
  -- non-versioned table in the source envelope, preventing update AND phantoms.
  -- No Node/LLM/network operation is performed while any lock is held.
  lock table public.secretarias,public.servidores,public.servidor_funcoes,public.portarias,
    public.portaria_membros,public.fatos_canonicos,public.regras_conhecimento,public.fontes_conhecimento,public.config_app in share mode;
  if exists(select 1 from public.config_app where chave='flag_visual_policy_builder'
      and lower(btrim(valor)) in ('1','true','on','sim')) then
    lock table public.governanca_artefatos,public.governanca_versoes in share mode;
  end if;
  if p_sources is null or octet_length(p_sources::text)>8388608
     or public.documento_editor_fontes_aprovacao(p_document,p_claims) is distinct from p_sources then
    raise exception 'review sources changed' using errcode='40001';
  end if;
  -- A rule may cross a validity boundary without any row changing. Reanalysis
  -- is required when time changed which rules the canonical resolver considers.
  if exists (select 1 from public.regras_conhecimento r where
      (r.tenant_id is null or r.tenant_id=v_head.tenant_id) and r.status='PUBLISHED' and
      ((r.vigencia_inicio > (p_evidence->>'evaluated_at')::timestamptz and r.vigencia_inicio<=clock_timestamp())
       or (r.vigencia_fim > (p_evidence->>'evaluated_at')::timestamptz and r.vigencia_fim<=clock_timestamp())))
     or exists (select 1 from public.governanca_versoes v
       where v.id::text in (select value->>'id' from jsonb_array_elements(p_sources->'governanca_versoes'))
         and ((v.vigencia_inicio > (p_evidence->>'evaluated_at')::timestamptz and v.vigencia_inicio<=clock_timestamp())
          or (v.vigencia_fim > (p_evidence->>'evaluated_at')::timestamptz and v.vigencia_fim<=clock_timestamp()))) then
    raise exception 'rule validity changed during review' using errcode='40001';
  end if;
  insert into public.governanca_aprovacoes(tenant_id,entidade_tipo,entidade_id,papel_exigido,aprovador,decisao,
      native_revision,native_content_hash,native_operation_id,native_snapshot,native_snapshot_sha256,native_evidence,native_sources)
    values(v_head.tenant_id,'documento_editor',p_document,v_role,v_actor,'APROVADO',p_revision,p_content_hash,
      p_operation,p_snapshot,p_snapshot_sha256,p_evidence,p_sources) returning id into v_approval;
  v_event := public.registrar_evento_governanca('aprovacao_registrada','aprovacao',v_approval,
    pg_catalog.jsonb_build_object('document_id',p_document,'revision',p_revision,'content_hash',p_content_hash,
      'operation_id',p_operation,'institutional_snapshot_sha256',p_snapshot_sha256,'scope','individual_revision_review',
      'official_emission',false));
  if v_event is null then raise exception 'approval event missing' using errcode='40001'; end if;
  update public.documentos_editor set status='aprovado',modified_at=now() where id=p_document;
  perform pg_catalog.set_config('request.jwt.claims',coalesce(v_claims,''),true);
  return query select v_approval,p_document,p_revision,p_content_hash,p_operation,p_snapshot_sha256,v_event,false;
end $$;
revoke all on function public.documento_editor_aprovar(uuid,bigint,text,uuid,jsonb,jsonb,bytea,text,jsonb)
  from public,anon,authenticated;
grant execute on function public.documento_editor_aprovar(uuid,bigint,text,uuid,jsonb,jsonb,bytea,text,jsonb) to service_role;
commit;
