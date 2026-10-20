-- Atomic native patches through the existing checkpoint and cycle ledger.
begin;
alter table public.revisoes
  add column native_patch_operation uuid,
  add column native_patch_actor uuid,
  add column native_patch_sha256 text,
  add column native_patch_manifest jsonb,
  add constraint revisoes_native_patch_contract check (
    case when native_patch_operation is null then native_patch_actor is null
      and native_patch_sha256 is null and native_patch_manifest is null
    else native_patch_actor is not null and native_patch_sha256 is not null
      and native_patch_sha256 ~ '^[0-9a-f]{64}$' and native_patch_manifest is not null
      and jsonb_typeof(native_patch_manifest)='object' and status='REVIEW_COMPLETED' end) not valid;
create unique index revisoes_native_patch_operation on public.revisoes(native_patch_operation)
  where native_patch_operation is not null;
create policy revisoes_native_patch_owner on public.revisoes as restrictive for insert to authenticated
  with check (native_patch_operation is null);
create policy revisoes_native_patch_le on public.revisoes as restrictive for select to authenticated
  using (native_patch_operation is null or (select public.documento_editor_sessao_valida()));
create function public.revisao_patch_imutavel() returns trigger language plpgsql security invoker set search_path='' as $$
begin
  if old.native_patch_operation is not null or (tg_op='UPDATE' and new.native_patch_operation is not null) then
    raise exception 'native patch audit is immutable' using errcode='42501';
  end if;
  if tg_op='DELETE' then return old; end if;
  return new;
end $$;
revoke all on function public.revisao_patch_imutavel() from public,anon,authenticated,service_role;
create trigger revisao_patch_imutavel before update or delete on public.revisoes
  for each row execute function public.revisao_patch_imutavel();

alter table public.documentos_editor_revisoes
  add column patch_audit_id uuid references public.revisoes(id) on delete restrict,
  add column patch_proof jsonb;
create index documentos_editor_patch_audit on public.documentos_editor_revisoes(patch_audit_id);
alter table public.documentos_editor_revisoes drop constraint documentos_editor_index_required;
alter table public.documentos_editor_revisoes add constraint documentos_editor_index_required
  check (block_index is not null and octet_length(block_index) between 1 and 8388608
    and block_index_sha256 is not null and block_index_sha256=encode(sha256(block_index),'hex')
    and index_mode is not null and index_mode in ('initial','reconciled','rebuilt_missing_index','rebuilt_build','operational_patch')) not valid;
alter table public.documentos_editor_revisoes add constraint documentos_editor_patch_proof_required
  check (case when index_mode='operational_patch' then patch_audit_id is not null and patch_proof is not null
    else patch_audit_id is null and patch_proof is null end) not valid;

-- Canonical checkpoint18 still receives reconciled. Only a matching immutable
-- cycle manifest may stamp operational lineage BEFORE INSERT; no history UPDATE.
create function public.documento_editor_patch_prova() returns trigger
language plpgsql security invoker set search_path='' as $$
declare v_audit public.revisoes%rowtype; v_target jsonb; v_base public.documentos_editor_revisoes%rowtype;
  v_old jsonb; v_new jsonb;
begin
  select * into v_audit from public.revisoes where native_patch_operation=new.operation_id;
  if not found then
    if new.index_mode='operational_patch' or new.patch_audit_id is not null or new.patch_proof is not null then
      raise exception 'operational patch has no canonical audit' using errcode='22023';
    end if;
    return new;
  end if;
  select value into v_target from jsonb_array_elements(v_audit.native_patch_manifest->'targets')
    where value->>'document_id'=new.document_id::text;
  if v_target is null or v_audit.native_patch_actor is distinct from new.created_by
     or (v_target->>'revision')::bigint is distinct from new.revision
     or v_target->>'content_hash' is distinct from new.content_hash
     or v_target->>'index_hash' is distinct from new.block_index_sha256
     or v_target->>'institutional_hash' is distinct from new.institutional_snapshot_sha256
     or v_target->>'engine_build' is distinct from new.engine_build_sha256
     or new.index_mode<>'reconciled' or new.original_format is not null or new.restored_from_revision is not null then
    raise exception 'operational patch proof differs' using errcode='22023';
  end if;
  if not exists(select 1 from public.documentos_editor d where d.id=new.document_id
      and d.processo_id=v_audit.processo_id and d.tenant_id=v_audit.tenant_id) then
    raise exception 'operational audit scope differs' using errcode='42501';
  end if;
  select * into v_base from public.documentos_editor_revisoes
    where document_id=new.document_id and revision=new.source_revision;
  if not found or v_base.engine_build_sha256 is distinct from new.engine_build_sha256
     or v_base.institutional_snapshot is distinct from new.institutional_snapshot
     or v_target->'native_commands'->>'source_hash' is distinct from v_base.content_hash
     or v_target->'native_commands'->>'source_revision' is distinct from v_base.revision::text then
    raise exception 'operational source differs' using errcode='40001';
  end if;
  select jsonb_agg(value-'content_hash' order by value->>'block_id') into v_old
    from jsonb_array_elements(convert_from(v_base.block_index,'UTF8')::jsonb->'blocos');
  select jsonb_agg(value-'content_hash' order by value->>'block_id') into v_new
    from jsonb_array_elements(convert_from(new.block_index,'UTF8')::jsonb->'blocos');
  if v_old is distinct from v_new or convert_from(new.block_index,'UTF8')::jsonb->'invalidacoes' <> '[]'::jsonb then
    raise exception 'operational index identity differs' using errcode='22023';
  end if;
  new.index_mode:='operational_patch';
  new.patch_audit_id:=v_audit.id;
  new.patch_proof:=v_target;
  return new;
end $$;
revoke all on function public.documento_editor_patch_prova() from public,anon,authenticated,service_role;
create trigger documento_editor_patch_prova before insert on public.documentos_editor_revisoes
  for each row execute function public.documento_editor_patch_prova();

create function public.documento_editor_fontes_patch(p_process uuid,p_claims jsonb)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare v_process public.processos%rowtype; v_result jsonb;
  v_old text:=current_setting('request.jwt.claims',true);
begin
  if p_claims->>'role' is distinct from 'authenticated' then
    raise exception 'native patch session required' using errcode='42501';
  end if;
  perform set_config('request.jwt.claims',p_claims::text,true);
  select * into v_process from public.processos where id=p_process;
  if not coalesce(public.documento_editor_sessao_valida(),false) or not found
     or not coalesce(public.pode_ler_processo(v_process.tenant_id,v_process.secretaria_id),false)
     or not coalesce(v_process.auth_user_id=auth.uid() or public.e_admin(),false) then
    raise exception 'native patch process denied' using errcode='42501';
  end if;
  select jsonb_build_object('processo',jsonb_build_object('id',v_process.id,'tenant_id',v_process.tenant_id,
    'secretaria_id',v_process.secretaria_id,'dados',v_process.dados,'aprovados',v_process.aprovados),
    'fatos',(select coalesce(jsonb_agg(to_jsonb(f) order by f.id),'[]'::jsonb) from
      (select * from public.fatos_canonicos where processo_id=p_process and tenant_id=v_process.tenant_id
        order by id limit 10001) f)) into v_result;
  perform set_config('request.jwt.claims',coalesce(v_old,''),true);
  return v_result;
end $$;
revoke all on function public.documento_editor_fontes_patch(uuid,jsonb) from public,anon,authenticated;
grant execute on function public.documento_editor_fontes_patch(uuid,jsonb) to service_role;

create function public.documento_editor_patch_lote(p_process uuid,p_operation uuid,p_batch bytea,p_batch_sha256 text,p_claims jsonb)
returns jsonb language plpgsql security invoker set search_path='' set lock_timeout='2s' set statement_timeout='5s' as $$
declare
  v_old text:=current_setting('request.jwt.claims',true); v_actor uuid; v_body jsonb; v_source jsonb; v_target jsonb;
  v_process public.processos%rowtype; v_head public.documentos_editor%rowtype; v_rev public.documentos_editor_revisoes%rowtype;
  v_audit public.revisoes%rowtype; v_audit_id uuid; v_replay boolean:=false; v_targets jsonb; v_events jsonb; v_receipts jsonb;
begin
  if p_process is null or p_operation is null or p_batch is null or octet_length(p_batch) not between 1 and 67108864
     or p_batch_sha256 is distinct from encode(sha256(p_batch),'hex') or p_claims->>'role' is distinct from 'authenticated' then
    raise exception 'invalid native patch batch' using errcode='22023';
  end if;
  v_body:=convert_from(p_batch,'UTF8')::jsonb;
  if v_body->>'schema' is distinct from 'gc-wordcraft-patch-batch/v1'
     or (select count(*) from jsonb_object_keys(v_body))<>12
     or v_body->>'processo_id' is distinct from p_process::text or v_body->>'operation_id' is distinct from p_operation::text
     or jsonb_typeof(v_body->'sources') is distinct from 'array' or jsonb_typeof(v_body->'targets') is distinct from 'array'
     or jsonb_array_length(v_body->'sources') not between 1 and 32
     or jsonb_array_length(v_body->'targets') not between 1 and jsonb_array_length(v_body->'sources')
     or v_body->'audit'->>'schema' is distinct from 'gc-wordcraft-patch-batch/v1'
     or v_body->'audit'->>'operation_id' is distinct from p_operation::text
     or v_body->'audit'->>'status' is distinct from 'REVIEW_COMPLETED'
     or v_body->'audit'->'official_emission' is distinct from 'false'::jsonb
     or v_body->>'plan_hash' is null or v_body->>'plan_hash' !~ '^[0-9a-f]{64}$'
     or v_body->>'source_bundle_hash' is null or v_body->>'source_bundle_hash' !~ '^[0-9a-f]{64}$'
     or v_body->>'target_bundle_hash' is null or v_body->>'target_bundle_hash' !~ '^[0-9a-f]{64}$'
     or jsonb_typeof(v_body->'audit'->'reports') is distinct from 'array'
     or jsonb_array_length(v_body->'audit'->'reports')<>2
     or v_body->'audit'->'reports'->0->>'status' is distinct from 'REVIEW_COMPLETED'
     or v_body->'audit'->'reports'->1->>'status' is distinct from 'REVIEW_COMPLETED'
     or v_body->'audit'->'plan'->>'patchPlanId' is distinct from p_operation::text
     or v_body->'audit'->'plan'->>'bundleId' is distinct from p_process::text
     or v_body->'audit'->'plan'->>'sourceBundleHash' is distinct from v_body->>'source_bundle_hash'
     or v_body->>'plan_payload' is null
     or encode(sha256((v_body->>'plan_payload')::bytea),'hex') is distinct from v_body->>'plan_hash'
     or convert_from((v_body->>'plan_payload')::bytea,'UTF8')::jsonb is distinct from v_body->'audit'->'plan'
     or v_body->>'source_bundle_hash' is distinct from v_body->'audit'->'snapshots'->0->>'hash'
     or v_body->>'target_bundle_hash' is distinct from v_body->'audit'->'snapshots'->1->>'hash' then
    raise exception 'invalid native patch evidence' using errcode='22023';
  end if;
  perform set_config('request.jwt.claims',p_claims::text,true);
  v_actor:=auth.uid();
  if not coalesce(public.documento_editor_sessao_valida(),false) or v_body->>'actor_id' is distinct from v_actor::text then
    raise exception 'native patch actor denied' using errcode='42501';
  end if;
  select * into v_process from public.processos where id=p_process;
  if not found or not coalesce(public.pode_ler_processo(v_process.tenant_id,v_process.secretaria_id),false)
     or not coalesce(v_process.auth_user_id=v_actor or public.e_admin(),false) then
    raise exception 'native patch process denied before locks' using errcode='42501';
  end if;
  perform 1 from public.usuarios where auth_user_id=v_actor for share;
  if not coalesce(public.documento_editor_sessao_valida(),false) then
    raise exception 'native patch actor revoked' using errcode='42501';
  end if;
  -- Existing checkpoint takes FOR SHARE on this process before creating or
  -- changing a head. FOR UPDATE fences the canonical source set, including new
  -- documents, and serializes only this process, not all native documents.
  select * into v_process from public.processos where id=p_process for update;
  if not found or not coalesce(public.pode_ler_processo(v_process.tenant_id,v_process.secretaria_id),false)
     or not coalesce(v_process.auth_user_id=v_actor or public.e_admin(),false) then
    raise exception 'native patch process denied' using errcode='42501';
  end if;
  if (select count(distinct value->>'document_id') from jsonb_array_elements(v_body->'sources')) <> jsonb_array_length(v_body->'sources')
     or (select count(distinct value->>'document_id') from jsonb_array_elements(v_body->'targets')) <> jsonb_array_length(v_body->'targets') then
    raise exception 'duplicate native patch document' using errcode='22023';
  end if;
  for v_source in select value from jsonb_array_elements(v_body->'sources') order by value->>'document_id' loop
    select * into v_head from public.documentos_editor d where d.id=(v_source->>'document_id')::uuid
      and d.processo_id=p_process and d.tenant_id=v_process.tenant_id for update;
    if not found then raise exception 'native patch source scope denied' using errcode='42501'; end if;
  end loop;
  select * into v_audit from public.revisoes where native_patch_operation=p_operation;
  if found then
    if v_audit.processo_id is distinct from p_process or v_audit.tenant_id is distinct from v_process.tenant_id
       or v_audit.native_patch_actor is distinct from v_actor or v_audit.native_patch_sha256 is distinct from p_batch_sha256 then
      raise exception 'native patch operation differs' using errcode='PT409';
    end if;
    v_audit_id:=v_audit.id; v_replay:=true;
  else
    if (select count(*) from public.documentos_editor where processo_id=p_process) <> jsonb_array_length(v_body->'sources') then
      raise exception 'native patch source set changed' using errcode='PT409';
    end if;
    for v_source in select value from jsonb_array_elements(v_body->'sources') loop
      select * into v_head from public.documentos_editor where id=(v_source->>'document_id')::uuid;
      select * into v_rev from public.documentos_editor_revisoes where document_id=v_head.id and revision=v_head.revision;
      if not found or v_head.tipo is distinct from v_source->>'doc_key'
         or v_head.revision is distinct from (v_source->>'revision')::bigint
         or v_head.content_hash is distinct from v_source->>'content_hash' or v_rev.content_hash is distinct from v_head.content_hash
         or v_rev.engine_build_sha256 is distinct from v_source->>'engine_build'
         or v_rev.block_index_sha256 is distinct from v_source->>'index_hash'
         or v_rev.institutional_snapshot_sha256 is distinct from v_source->>'institutional_hash' then
        raise exception 'native patch source changed' using errcode='PT409';
      end if;
    end loop;
    -- Facts have non-versioned status updates and can gain new rows. Only this
    -- table requires a global SHARE lock; no external work occurs in the TX.
    lock table public.fatos_canonicos in share mode;
    if public.documento_editor_fontes_patch(p_process,p_claims) is distinct from v_body->'context' then
      raise exception 'native patch facts or process changed' using errcode='PT409';
    end if;
    for v_target in select value from jsonb_array_elements(v_body->'targets') loop
      select value into v_source from jsonb_array_elements(v_body->'sources') where value->>'document_id'=v_target->>'document_id';
      if not found or (select count(*) from jsonb_object_keys(v_target))<>12
         or v_target->>'doc_key' is distinct from v_source->>'doc_key'
         or (v_target->>'source_revision')::bigint is distinct from (v_source->>'revision')::bigint
         or (v_target->>'revision')::bigint is distinct from (v_source->>'revision')::bigint+1
         or v_target->>'engine_build' is distinct from v_source->>'engine_build'
         or v_target->>'institutional_hash' is distinct from v_source->>'institutional_hash'
         or v_target->'native_commands'->>'schema' is distinct from 'gc-wordcraft-native-patch/v1'
         or v_target->'native_commands'->>'source_hash' is distinct from v_source->>'content_hash'
         or v_target->'native_commands'->>'source_revision' is distinct from v_source->>'revision'
         or jsonb_typeof(v_target->'native_commands'->'operations') is distinct from 'array'
         or jsonb_array_length(v_target->'native_commands'->'operations') not between 1 and 200
         or exists(select 1 from jsonb_array_elements(v_target->'native_commands'->'operations') op
           where op->>'op' is distinct from 'replace_text') then
        raise exception 'native patch target binding differs' using errcode='22023';
      end if;
    end loop;
    select jsonb_agg(value-array['payload','block_index','institutional_snapshot'] order by value->>'document_id') into v_targets
      from jsonb_array_elements(v_body->'targets');
    v_events:=jsonb_build_array(
      jsonb_build_object('de','CORRECTING','para','CORRECTION_APPLIED','motivo','patch nativo persistido','versao',2,'quando',now(),'ator',v_actor,'operation_id',p_operation),
      jsonb_build_object('de','CORRECTION_APPLIED','para','REVALIDATING','motivo','auditoria posterior registrada','versao',2,'quando',now(),'ator',v_actor,'operation_id',p_operation),
      jsonb_build_object('de','REVALIDATING','para','REVIEW_COMPLETED','motivo','emissao e aprovacao permanecem gates separados','versao',2,'quando',now(),'ator',v_actor,'operation_id',p_operation));
    insert into public.revisoes(tenant_id,processo_id,status,ciclo,etapa_ui,versao_atual,bundle_hash,snapshots,relatorios,planos,diffs,eventos,
      native_patch_operation,native_patch_actor,native_patch_sha256,native_patch_manifest)
      values(v_process.tenant_id,p_process,'REVIEW_COMPLETED',1,'validando',2,v_body->>'target_bundle_hash',
        v_body->'audit'->'snapshots',v_body->'audit'->'reports',jsonb_build_array(v_body->'audit'->'plan'),
        jsonb_build_array(v_body->'audit'->'diff'),v_events,p_operation,v_actor,p_batch_sha256,
        jsonb_build_object('schema','gc-wordcraft-patch-batch/v1','plan_hash',v_body->>'plan_hash',
          'sources',v_body->'sources','targets',v_targets,'context',v_body->'context')) returning id into v_audit_id;
    for v_target in select value from jsonb_array_elements(v_body->'targets') order by value->>'document_id' loop
      perform public.documento_editor_checkpoint((v_target->>'document_id')::uuid,p_process,v_target->>'doc_key',
        (v_target->>'source_revision')::bigint,p_operation,(v_target->>'payload')::bytea,v_target->>'content_hash',p_claims,
        v_target->>'engine_build',(v_target->>'block_index')::bytea,v_target->>'index_hash','reconciled',
        null,null,null,null,(v_target->>'institutional_snapshot')::bytea,v_target->>'institutional_hash');
    end loop;
  end if;
  select jsonb_agg(jsonb_build_object('document_id',r.document_id,'revision',r.revision,'content_hash',r.content_hash,
    'engine_build_sha256',r.engine_build_sha256,'block_index_sha256',r.block_index_sha256,
    'index_mode',r.index_mode,'institutional_snapshot_sha256',r.institutional_snapshot_sha256) order by r.document_id) into v_receipts
    from public.documentos_editor_revisoes r where r.patch_audit_id=v_audit_id;
  if jsonb_array_length(coalesce(v_receipts,'[]')) <> jsonb_array_length(v_body->'targets') then
    raise exception 'native patch history incomplete' using errcode='40001';
  end if;
  perform set_config('request.jwt.claims',coalesce(v_old,''),true);
  return jsonb_build_object('operation_id',p_operation,'processo_id',p_process,'audit_id',v_audit_id,
    'plan_hash',v_body->>'plan_hash','batch_sha256',p_batch_sha256,'replayed',v_replay,'documentos',v_receipts);
end $$;
revoke all on function public.documento_editor_patch_lote(uuid,uuid,bytea,text,jsonb) from public,anon,authenticated;
grant execute on function public.documento_editor_patch_lote(uuid,uuid,bytea,text,jsonb) to service_role;
commit;
