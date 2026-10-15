-- Reference context only, not an approval, signature or official emission.
-- Reuses institutional registries; no new identity or signatory tables.
begin;
alter table public.documentos_editor_revisoes
  add column institutional_snapshot bytea,
  add column institutional_snapshot_sha256 text;
-- Historical absence remains NULL. New rows must record an exact reference.
alter table public.documentos_editor_revisoes add constraint documentos_editor_institutional_required
  check (institutional_snapshot is not null and octet_length(institutional_snapshot) between 1 and 8388608
    and institutional_snapshot_sha256 is not null
    and institutional_snapshot_sha256=encode(sha256(institutional_snapshot),'hex')) not valid;
comment on column public.documentos_editor_revisoes.institutional_snapshot is
  'Server-derived immutable draft reference from existing canonical registries. Not proof of native approval. NULL means history not recorded.';
drop function public.documento_editor_checkpoint(uuid,uuid,text,bigint,uuid,bytea,text,jsonb,text,bytea,text,text,text,bytea,jsonb,bigint);
create function public.documento_editor_checkpoint(
  p_document uuid, p_process uuid, p_tipo text, p_expected_revision bigint,
  p_operation uuid, p_payload bytea, p_content_hash text, p_claims jsonb, p_engine_build_sha256 text,
  p_block_index bytea, p_block_index_sha256 text, p_index_mode text,
  p_original_format text, p_original_payload bytea, p_conversion_report jsonb, p_restored_from_revision bigint,
  p_institutional_snapshot bytea, p_institutional_snapshot_sha256 text)
returns table(document_id uuid, revision bigint, content_hash text, operation_id uuid, replayed boolean,
  engine_build_sha256 text, validation_provenance text, block_index_sha256 text,
  index_mode text, restored_from_revision bigint, original_hash text, institutional_snapshot_sha256 text)
language plpgsql security invoker set search_path = ''
as $$
declare
  v_process public.processos%rowtype;
  v_document public.documentos_editor%rowtype;
  v_previous public.documentos_editor_revisoes%rowtype;
  v_actor uuid;
  v_old_claims text;
  v_next bigint;
  v_index jsonb;
  v_base public.documentos_editor_revisoes%rowtype;
  v_original_hash text;
  v_institutional jsonb;
  v_snapshot_source bytea;
begin
  if p_institutional_snapshot is null or pg_catalog.octet_length(p_institutional_snapshot) not between 1 and 8388608
     or p_institutional_snapshot_sha256 is null
     or p_institutional_snapshot_sha256 <> pg_catalog.encode(pg_catalog.sha256(p_institutional_snapshot),'hex')
     or p_block_index is null or pg_catalog.octet_length(p_block_index) not between 1 and 8388608
     or p_block_index_sha256 is null or p_block_index_sha256 <> pg_catalog.encode(pg_catalog.sha256(p_block_index),'hex')
     or p_index_mode is null or p_index_mode not in ('initial','reconciled','rebuilt_missing_index','rebuilt_build')
     or p_engine_build_sha256 is null or p_engine_build_sha256 !~ '^[0-9a-f]{64}$'
     or p_document is null or p_process is null or p_operation is null
     or p_tipo is null or p_tipo !~ '^[a-z][a-z0-9_]{0,63}$'
     or p_expected_revision is null or p_expected_revision < 0
     or p_payload is null or pg_catalog.octet_length(p_payload) not between 1 and 8388608
     or p_content_hash is null or p_content_hash <> pg_catalog.encode(pg_catalog.sha256(p_payload),'hex')
     or p_claims is null or pg_catalog.jsonb_typeof(p_claims) <> 'object'
     or coalesce(p_claims->>'role','') <> 'authenticated'
     or pg_catalog.jsonb_typeof(p_claims->'app_metadata') is distinct from 'object'
     or (select count(*) from pg_catalog.jsonb_object_keys(p_claims)) <> 3 then
    raise exception 'invalid checkpoint contract' using errcode = '22023';
  end if;
  v_institutional := pg_catalog.convert_from(p_institutional_snapshot,'UTF8')::jsonb;
  if pg_catalog.jsonb_typeof(v_institutional) is distinct from 'object'
     or v_institutional->>'schema' is distinct from 'gc-wordcraft-institutional/v1'
     or v_institutional->>'phase' is distinct from 'draft_reference'
     or v_institutional->>'application' not in ('reference_only','applied_by_govconnect_docx')
     or v_institutional->>'application' is null
     or v_institutional->>'document_id' is distinct from p_document::text
     or v_institutional->>'processo_id' is distinct from p_process::text
     or v_institutional->>'doc_key' is distinct from p_tipo
     or pg_catalog.jsonb_typeof(v_institutional->'identity') is distinct from 'object'
     or pg_catalog.jsonb_typeof(v_institutional->'signatories') is distinct from 'array'
     or pg_catalog.jsonb_typeof(v_institutional->'captured_for_revision') is distinct from 'number'
     or (v_institutional->>'captured_for_revision')::bigint not between 1 and p_expected_revision+1
     or (select count(*) from pg_catalog.jsonb_object_keys(v_institutional)) <> 14 then
    raise exception 'invalid institutional reference' using errcode='22023';
  end if;
  v_index := pg_catalog.convert_from(p_block_index,'UTF8')::jsonb;
  if pg_catalog.jsonb_typeof(v_index) is distinct from 'object'
     or v_index->>'schema' is distinct from 'gc-wordcraft-block-index/v1'
     or v_index->>'document_id' is distinct from p_document::text
     or v_index->>'revision' is distinct from (p_expected_revision + 1)::text
     or v_index->>'content_hash' is distinct from p_content_hash
     or v_index->>'engine_manifest_sha256' is distinct from p_engine_build_sha256
     or pg_catalog.jsonb_typeof(v_index->'blocos') is distinct from 'array'
     or pg_catalog.jsonb_typeof(v_index->'invalidacoes') is distinct from 'array'
     or pg_catalog.jsonb_typeof(v_index->'areas_nao_enderecaveis') is distinct from 'array'
     or (select count(*) from pg_catalog.jsonb_object_keys(v_index)) <> 8 then
    raise exception 'invalid block index contract' using errcode = '22023';
  end if;
  if p_original_format is null then
    if p_original_payload is not null or p_conversion_report is not null then
      raise exception 'incomplete original source' using errcode = '22023';
    end if;
  else
    if p_expected_revision <> 0 or p_original_format not in ('markdown','docx')
       or p_original_payload is null or pg_catalog.octet_length(p_original_payload) not between 1 and 8388608
       or pg_catalog.jsonb_typeof(p_conversion_report) is distinct from 'object' then
      raise exception 'invalid original source' using errcode = '22023';
    end if;
    v_original_hash := pg_catalog.encode(pg_catalog.sha256(p_original_payload),'hex');
    if p_conversion_report->>'schema' is distinct from 'gc-wordcraft-import/v1'
       or p_conversion_report->>'source_sha256' is distinct from v_original_hash
       or p_conversion_report->>'source_format' is distinct from p_original_format
       or p_conversion_report->>'fidelity' is distinct from 'pending_manual_review' then
      raise exception 'invalid conversion report' using errcode = '22023';
    end if;
  end if;
  if p_restored_from_revision is not null then
    if p_original_format is not null or p_restored_from_revision < 1 or p_restored_from_revision > p_expected_revision then
      raise exception 'invalid restoration reference' using errcode = '22023';
    end if;
  end if;
  v_old_claims := pg_catalog.current_setting('request.jwt.claims', true);
  perform pg_catalog.set_config('request.jwt.claims', p_claims::text, true);
  v_actor := auth.uid();
  -- Hold the canonical profile stable while checking scope and committing.
  perform 1 from public.usuarios u where u.auth_user_id = v_actor for share;
  if not coalesce(public.documento_editor_sessao_valida(),false) then
    raise exception 'document access denied' using errcode = '42501';
  end if;
  select p.* into v_process from public.processos p where p.id = p_process for share;
  if not found or not coalesce(public.pode_ler_processo(v_process.tenant_id, v_process.secretaria_id),false)
     or not coalesce(v_process.auth_user_id = v_actor or public.e_admin(),false) then
    raise exception 'document access denied' using errcode = '42501';
  end if;
  if v_institutional->>'tenant_id' is distinct from v_process.tenant_id::text
     or v_institutional->>'secretaria_id' is distinct from v_process.secretaria_id::text then
    raise exception 'institutional scope differs' using errcode='42501';
  end if;
  if coalesce(p_tipo = any(v_process.aprovados), false) then
    raise exception 'approved document is immutable' using errcode = '42501';
  end if;
  insert into public.documentos_editor (id, processo_id, tenant_id, tipo, created_by)
    values (p_document, p_process, v_process.tenant_id, p_tipo, v_actor)
    on conflict (id) do nothing;
  select d.* into v_document from public.documentos_editor d where d.id = p_document for update;
  if v_document.processo_id <> p_process or v_document.tenant_id <> v_process.tenant_id
     or v_document.tipo <> p_tipo or v_document.status not in ('rascunho','em_revisao') then
    raise exception 'document access denied' using errcode = '42501';
  end if;
  select r.* into v_previous from public.documentos_editor_revisoes r
    where r.document_id = p_document and r.operation_id = p_operation;
  if found then
    if v_previous.content_hash <> p_content_hash or v_previous.payload <> p_payload
       or v_previous.source_revision <> p_expected_revision or v_previous.created_by <> v_actor
       or v_previous.engine_build_sha256 is distinct from p_engine_build_sha256
       or v_previous.block_index is distinct from p_block_index
       or v_previous.index_mode is distinct from p_index_mode
       or v_previous.original_format is distinct from p_original_format
       or v_previous.original_payload is distinct from p_original_payload
       or v_previous.conversion_report is distinct from p_conversion_report
       or v_previous.restored_from_revision is distinct from p_restored_from_revision
       or v_previous.institutional_snapshot is distinct from p_institutional_snapshot then
      raise exception 'operation identity conflict' using errcode = '40001';
    end if;
    perform pg_catalog.set_config('request.jwt.claims', coalesce(v_old_claims,''), true);
    return query select p_document, v_previous.revision, v_previous.content_hash, p_operation, true,
      v_previous.engine_build_sha256, v_previous.validation_provenance, v_previous.block_index_sha256,
      v_previous.index_mode, v_previous.restored_from_revision, v_previous.original_hash, v_previous.institutional_snapshot_sha256;
    return;
  end if;
  if v_document.revision <> p_expected_revision then
    raise exception 'document revision conflict' using errcode = '40001';
  end if;
  if p_expected_revision = 0 then
    if p_index_mode <> 'initial' then
      raise exception 'invalid initial index mode' using errcode = '22023';
    end if;
  else
    select r.* into v_base from public.documentos_editor_revisoes r
      where r.document_id=p_document and r.revision=p_expected_revision;
    if not found or p_index_mode <> (case when v_base.block_index is null then 'rebuilt_missing_index'
      when v_base.engine_build_sha256 <> p_engine_build_sha256 then 'rebuilt_build' else 'reconciled' end) then
      raise exception 'invalid index transition mode' using errcode = '22023';
    end if;
  end if;
  if p_restored_from_revision is not null and not exists (
    select 1 from public.documentos_editor_revisoes r where r.document_id=p_document
      and r.revision=p_restored_from_revision and r.payload=p_payload and r.content_hash=p_content_hash) then
    raise exception 'restoration source differs' using errcode = '22023';
  end if;
  if p_restored_from_revision is not null then
    select r.institutional_snapshot into v_snapshot_source from public.documentos_editor_revisoes r
      where r.document_id=p_document and r.revision=p_restored_from_revision;
  else
    v_snapshot_source := v_base.institutional_snapshot;
  end if;
  if v_snapshot_source is not null and v_snapshot_source <> p_institutional_snapshot then
    raise exception 'institutional history differs' using errcode='40001';
  end if;
  if p_expected_revision > 0 and v_snapshot_source is null and
       ((v_institutional->>'captured_for_revision')::bigint <> p_expected_revision+1
        or v_institutional->>'application' <> 'reference_only') then
    raise exception 'legacy institutional history unrecorded' using errcode='22023';
  end if;
  v_next := v_document.revision + 1;
  insert into public.documentos_editor_revisoes
    (document_id, revision, source_revision, operation_id, payload, content_hash, created_by, engine_build_sha256, block_index, block_index_sha256, index_mode,
     original_format, original_payload, original_hash, conversion_report, restored_from_revision,
     institutional_snapshot, institutional_snapshot_sha256)
    values (p_document, v_next, p_expected_revision, p_operation, p_payload, p_content_hash, v_actor, p_engine_build_sha256, p_block_index, p_block_index_sha256, p_index_mode,
      p_original_format, p_original_payload, v_original_hash, p_conversion_report, p_restored_from_revision,
      p_institutional_snapshot, p_institutional_snapshot_sha256);
  update public.documentos_editor d set revision = v_next,
    content_hash = p_content_hash, modified_at = pg_catalog.now() where d.id = p_document;
  perform pg_catalog.set_config('request.jwt.claims', coalesce(v_old_claims,''), true);
  return query select p_document, v_next, p_content_hash, p_operation, false, p_engine_build_sha256, 'server_manifest_sha256'::text, p_block_index_sha256,
    p_index_mode, p_restored_from_revision, v_original_hash, p_institutional_snapshot_sha256;
end;
$$;
revoke all on function public.documento_editor_checkpoint(uuid,uuid,text,bigint,uuid,bytea,text,jsonb,text,bytea,text,text,text,bytea,jsonb,bigint,bytea,text)
  from public, anon, authenticated;
grant execute on function public.documento_editor_checkpoint(uuid,uuid,text,bigint,uuid,bytea,text,jsonb,text,bytea,text,text,text,bytea,jsonb,bigint,bytea,text)
  to service_role;




commit;
