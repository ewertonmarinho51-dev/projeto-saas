-- Revision validation provenance. Local/disposable rehearsal first; no remote
-- application is authorized by this file. Never retroattribute an engine build.
begin;

alter table public.documentos_editor_revisoes
  add column engine_build_sha256 text,
  add column validation_provenance text generated always as (
    case when engine_build_sha256 is null then 'legacy_unrecorded'::text
         else 'server_manifest_sha256'::text end
  ) stored;

-- Existing rows retain NULL and explicit legacy provenance. NOT VALID skips
-- scanning historical rows but enforces the constraint on every NEW insertion.
alter table public.documentos_editor_revisoes
  add constraint documentos_editor_revisoes_build_required
  check (engine_build_sha256 is not null and engine_build_sha256 ~ '^[0-9a-f]{64}$') not valid;

comment on column public.documentos_editor_revisoes.engine_build_sha256 is
  'SHA256 of the trusted server manifest verified by the native validator before commit; NULL means historical validation build was not recorded';
comment on column public.documentos_editor_revisoes.validation_provenance is
  'Generated provenance; reopening an old revision never retroattributes a validation build';

-- Remove the former service-only API atomically: no overload may omit build.
drop function public.documento_editor_checkpoint(uuid,uuid,text,bigint,uuid,bytea,text,jsonb);

-- Native validation remains outside this short CAS transaction. Build is supplied
-- only by DocumentoService configuration, never the browser or user JWT claims.
create function public.documento_editor_checkpoint(
  p_document uuid, p_process uuid, p_tipo text, p_expected_revision bigint,
  p_operation uuid, p_payload bytea, p_content_hash text, p_claims jsonb, p_engine_build_sha256 text)
returns table(document_id uuid, revision bigint, content_hash text, operation_id uuid, replayed boolean,
  engine_build_sha256 text, validation_provenance text)
language plpgsql security invoker set search_path = ''
as $$
declare
  v_process public.processos%rowtype;
  v_document public.documentos_editor%rowtype;
  v_previous public.documentos_editor_revisoes%rowtype;
  v_actor uuid;
  v_old_claims text;
  v_next bigint;
begin
  if p_engine_build_sha256 is null or p_engine_build_sha256 !~ '^[0-9a-f]{64}$'
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
       or v_previous.engine_build_sha256 is distinct from p_engine_build_sha256 then
      raise exception 'operation identity conflict' using errcode = '40001';
    end if;
    perform pg_catalog.set_config('request.jwt.claims', coalesce(v_old_claims,''), true);
    return query select p_document, v_previous.revision, v_previous.content_hash, p_operation, true,
      v_previous.engine_build_sha256, v_previous.validation_provenance;
    return;
  end if;
  if v_document.revision <> p_expected_revision then
    raise exception 'document revision conflict' using errcode = '40001';
  end if;
  v_next := v_document.revision + 1;
  insert into public.documentos_editor_revisoes
    (document_id, revision, source_revision, operation_id, payload, content_hash, created_by, engine_build_sha256)
    values (p_document, v_next, p_expected_revision, p_operation, p_payload, p_content_hash, v_actor, p_engine_build_sha256);
  update public.documentos_editor d set revision = v_next,
    content_hash = p_content_hash, modified_at = pg_catalog.now() where d.id = p_document;
  perform pg_catalog.set_config('request.jwt.claims', coalesce(v_old_claims,''), true);
  return query select p_document, v_next, p_content_hash, p_operation, false, p_engine_build_sha256, 'server_manifest_sha256'::text;
end;
$$;
revoke all on function public.documento_editor_checkpoint(uuid,uuid,text,bigint,uuid,bytea,text,jsonb,text)
  from public, anon, authenticated;
grant execute on function public.documento_editor_checkpoint(uuid,uuid,text,bigint,uuid,bytea,text,jsonb,text)
  to service_role;


commit;
