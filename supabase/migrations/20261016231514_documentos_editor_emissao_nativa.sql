-- Official native document emission. The publication vocabulary, actor
-- competence and append-only audit trail remain owned by the existing
-- governance subsystem. No production migration is applied by this file.
begin;

create table public.documentos_editor_emissoes (
  id uuid primary key references public.governanca_publicacoes(id) on delete restrict,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  processo_id uuid not null references public.processos(id) on delete restrict,
  operation_id uuid not null unique,
  emitido_por uuid not null,
  engine_manifest_sha256 text not null check (engine_manifest_sha256 ~ '^[0-9a-f]{64}$'),
  documentos jsonb not null check (jsonb_typeof(documentos)='array' and jsonb_array_length(documentos) between 1 and 32),
  manifest jsonb not null check (jsonb_typeof(manifest)='object'
    and manifest->>'schema'='gc-wordcraft-official-emission/v1'
    and manifest->'official_emission'='true'::jsonb),
  docx_package bytea not null check (octet_length(docx_package) between 1 and 67108864),
  docx_sha256 text not null check (docx_sha256=encode(sha256(docx_package),'hex')),
  pdf_package bytea not null check (octet_length(pdf_package) between 1 and 67108864),
  pdf_sha256 text not null check (pdf_sha256=encode(sha256(pdf_package),'hex')),
  criado_em timestamptz not null default now()
);

alter table public.documentos_editor_emissoes enable row level security;
revoke all on public.documentos_editor_emissoes from public,anon,authenticated,service_role;
grant select on public.documentos_editor_emissoes to authenticated;
grant select,insert on public.documentos_editor_emissoes to service_role;
create policy documentos_editor_emissoes_le on public.documentos_editor_emissoes
  for select to authenticated using (
    (select public.documento_editor_sessao_valida()) and exists (
      select 1 from public.processos p where p.id=processo_id and p.tenant_id=tenant_id
        and public.pode_ler_processo(p.tenant_id,p.secretaria_id)));

create function public.documento_editor_emissao_immutable()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
  raise exception 'native emission is immutable' using errcode='42501';
end $$;
revoke all on function public.documento_editor_emissao_immutable() from public,anon,authenticated,service_role;
create trigger documento_editor_emissao_immutable before update or delete
  on public.documentos_editor_emissoes for each row
  execute function public.documento_editor_emissao_immutable();

create function public.documento_editor_emitir(
  p_process uuid,p_operation uuid,p_engine_manifest_sha256 text,
  p_documents jsonb,p_manifest jsonb,p_docx bytea,p_docx_sha256 text,
  p_pdf bytea,p_pdf_sha256 text,p_claims jsonb)
returns table(emission_id uuid,processo_id uuid,operation_id uuid,
  docx_sha256 text,pdf_sha256 text,event_id uuid,replayed boolean)
language plpgsql security invoker set search_path='' set lock_timeout='2s' set statement_timeout='8s' as $$
declare
  v_claims text := current_setting('request.jwt.claims',true);
  v_actor uuid; v_role text; v_profile public.usuarios%rowtype;
  v_process public.processos%rowtype; v_previous public.documentos_editor_emissoes%rowtype;
  v_emission uuid; v_event uuid; v_count integer; v_item jsonb;
begin
  if p_process is null or p_operation is null
     or p_engine_manifest_sha256 is null or p_engine_manifest_sha256 !~ '^[0-9a-f]{64}$'
     or p_documents is null or jsonb_typeof(p_documents)<>'array'
     or jsonb_array_length(p_documents) not between 1 and 32
     or p_manifest is null or jsonb_typeof(p_manifest)<>'object'
     or p_manifest->>'schema' is distinct from 'gc-wordcraft-official-emission/v1'
     or p_manifest->'official_emission' is distinct from 'true'::jsonb
     or p_manifest->>'processo_id' is distinct from p_process::text
     or p_manifest->>'engine_manifest_sha256' is distinct from p_engine_manifest_sha256
     or p_manifest->'documents' is distinct from p_documents
     or p_docx is null or octet_length(p_docx) not between 1 and 67108864
     or p_docx_sha256 is distinct from encode(sha256(p_docx),'hex')
     or p_pdf is null or octet_length(p_pdf) not between 1 and 67108864
     or p_pdf_sha256 is distinct from encode(sha256(p_pdf),'hex')
     or p_manifest->'packages' is distinct from jsonb_build_object(
       'docx',jsonb_build_object('sha256',p_docx_sha256,'bytes',octet_length(p_docx)),
       'pdf',jsonb_build_object('sha256',p_pdf_sha256,'bytes',octet_length(p_pdf)))
     or p_claims is null or jsonb_typeof(p_claims)<>'object'
     or p_claims->>'role' is distinct from 'authenticated'
     or jsonb_typeof(p_claims->'app_metadata') is distinct from 'object' then
    raise exception 'invalid native emission contract' using errcode='22023';
  end if;
  perform set_config('request.jwt.claims',p_claims::text,true);
  v_actor:=auth.uid();
  select * into v_profile from public.usuarios u where u.auth_user_id=v_actor;
  v_role:=coalesce(nullif(v_profile.papel_governanca,''),
    case when v_profile.papel='admin' then 'admin_municipal' end);
  if not coalesce(public.documento_editor_sessao_valida(),false) or v_role is null
     or v_role is distinct from coalesce(nullif(p_claims->'app_metadata'->>'papel_governanca',''),
       case when p_claims->'app_metadata'->>'papel'='admin' then 'admin_municipal' end)
     or not ('publicacao_registrada'=any(public.eventos_permitidos_ao_papel(v_role))) then
    raise exception 'publication competence required' using errcode='42501';
  end if;
  select * into v_profile from public.usuarios u where u.auth_user_id=v_actor for share;
  if not v_profile.ativo or not coalesce(public.documento_editor_sessao_valida(),false) then
    raise exception 'publication competence revoked' using errcode='42501';
  end if;
  perform set_config('request.jwt.claims',jsonb_set(p_claims,
    '{app_metadata,papel_governanca}',to_jsonb(v_role))::text,true);
  select * into v_process from public.processos p where p.id=p_process for share;
  if not found or v_process.tenant_id is distinct from public.tenant_do_jwt()
     or not (public.papel_alcanca_o_tenant(v_role) or
       (v_process.secretaria_id is not null and v_process.secretaria_id=public.secretaria_do_jwt()))
     or not coalesce(public.pode_ler_processo(v_process.tenant_id,v_process.secretaria_id),false) then
    raise exception 'publication scope denied' using errcode='42501';
  end if;
  select * into v_previous from public.documentos_editor_emissoes e
    where e.operation_id=p_operation;
  if found then
    if (v_previous.processo_id,v_previous.emitido_por,v_previous.engine_manifest_sha256,
        v_previous.documentos,v_previous.manifest,v_previous.docx_sha256,v_previous.pdf_sha256,
        v_previous.docx_package,v_previous.pdf_package)
       is distinct from (p_process,v_actor,p_engine_manifest_sha256,p_documents,p_manifest,
        p_docx_sha256,p_pdf_sha256,p_docx,p_pdf) then
      raise exception 'emission operation differs' using errcode='PT409';
    end if;
    select e.id into v_event from public.governanca_eventos e
      where e.tipo_evento='publicacao_registrada' and e.entidade_tipo='publicacao'
        and e.entidade_id=v_previous.id and e.ator=v_actor;
    if v_event is null then raise exception 'incomplete emission history' using errcode='PT409'; end if;
    perform set_config('request.jwt.claims',coalesce(v_claims,''),true);
    return query select v_previous.id,p_process,p_operation,p_docx_sha256,p_pdf_sha256,v_event,true;
    return;
  end if;
  select count(*) into v_count from public.documentos_editor d where d.processo_id=p_process;
  if v_count<>jsonb_array_length(p_documents) then
    raise exception 'native emission set differs' using errcode='PT409';
  end if;
  if (select count(distinct value->>'document_id') from jsonb_array_elements(p_documents))
       <>jsonb_array_length(p_documents)
     or (select count(distinct value->>'tipo') from jsonb_array_elements(p_documents))
       <>jsonb_array_length(p_documents) then
    raise exception 'native emission set is ambiguous' using errcode='22023';
  end if;
  for v_item in select value from jsonb_array_elements(p_documents) loop
    if (select count(*) from jsonb_object_keys(v_item))<>9
       or v_item->>'tipo' is null or v_item->>'document_id' is null
       or v_item->>'revision' is null or v_item->>'source_sha256' !~ '^[0-9a-f]{64}$'
       or v_item->>'approval_id' is null or v_item->>'approval_snapshot_sha256' !~ '^[0-9a-f]{64}$'
       or v_item->>'engine_manifest_sha256' is distinct from p_engine_manifest_sha256
       or v_item->>'docx_sha256' !~ '^[0-9a-f]{64}$' or v_item->>'pdf_sha256' !~ '^[0-9a-f]{64}$'
       or not exists (
         select 1 from public.documentos_editor d
         join public.documentos_editor_revisoes r on r.document_id=d.id and r.revision=d.revision
         join public.governanca_aprovacoes a on a.entidade_tipo='documento_editor'
           and a.entidade_id=d.id and a.native_revision=d.revision
         where d.id=(v_item->>'document_id')::uuid and d.processo_id=p_process
           and d.tipo=v_item->>'tipo' and d.status='aprovado'
           and d.revision=(v_item->>'revision')::bigint
           and d.content_hash=v_item->>'source_sha256'
           and r.engine_build_sha256=p_engine_manifest_sha256
           and d.tenant_id=v_process.tenant_id and a.id=(v_item->>'approval_id')::uuid
           and a.native_content_hash=d.content_hash
           and a.native_snapshot_sha256=v_item->>'approval_snapshot_sha256') then
      raise exception 'approved native source differs' using errcode='PT409';
    end if;
  end loop;
  -- Hold every head stable only after all expensive native exports completed.
  perform 1 from public.documentos_editor d where d.processo_id=p_process
    order by d.id for update;
  -- Recheck under locks; no source may cross the approval/emission boundary.
  for v_item in select value from jsonb_array_elements(p_documents) loop
    if not exists(select 1 from public.documentos_editor d
      where d.id=(v_item->>'document_id')::uuid and d.processo_id=p_process
        and d.status='aprovado' and d.revision=(v_item->>'revision')::bigint
        and d.content_hash=v_item->>'source_sha256') then
      raise exception 'native source changed during emission' using errcode='PT409';
    end if;
  end loop;
  insert into public.governanca_publicacoes(tenant_id,status,itens,motivo,publicado_por)
    values(v_process.tenant_id,'ATIVA',p_documents,
      'Emissão documental nativa WordCraft',v_actor) returning id into v_emission;
  insert into public.documentos_editor_emissoes(id,tenant_id,processo_id,operation_id,
    emitido_por,engine_manifest_sha256,documentos,manifest,docx_package,docx_sha256,
    pdf_package,pdf_sha256)
    values(v_emission,v_process.tenant_id,p_process,p_operation,v_actor,
      p_engine_manifest_sha256,p_documents,p_manifest,p_docx,p_docx_sha256,p_pdf,p_pdf_sha256);
  v_event:=public.registrar_evento_governanca('publicacao_registrada','publicacao',v_emission,
    jsonb_build_object('processo_id',p_process,'operation_id',p_operation,
      'engine_manifest_sha256',p_engine_manifest_sha256,'docx_sha256',p_docx_sha256,
      'pdf_sha256',p_pdf_sha256,'documents',p_documents,'official_emission',true));
  if v_event is null then raise exception 'emission event missing' using errcode='PT409'; end if;
  update public.documentos_editor d set status='emitido',modified_at=now()
    where d.processo_id=p_process and d.status='aprovado';
  perform set_config('request.jwt.claims',coalesce(v_claims,''),true);
  return query select v_emission,p_process,p_operation,p_docx_sha256,p_pdf_sha256,v_event,false;
end $$;
revoke all on function public.documento_editor_emitir(uuid,uuid,text,jsonb,jsonb,bytea,text,bytea,text,jsonb)
  from public,anon,authenticated;
grant execute on function public.documento_editor_emitir(uuid,uuid,text,jsonb,jsonb,bytea,text,bytea,text,jsonb)
  to service_role;

commit;
