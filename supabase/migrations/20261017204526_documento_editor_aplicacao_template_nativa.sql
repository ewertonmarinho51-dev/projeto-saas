-- Atomic application of one effective governed template to a native revision.
-- Local migration only; do not apply remotely without explicit authorization.
begin;

alter table public.documentos_editor_revisoes
  add column template_version_id uuid references public.governanca_versoes(id) on delete restrict,
  add column template_proof jsonb;

alter table public.documentos_editor_revisoes drop constraint documentos_editor_index_required;
alter table public.documentos_editor_revisoes add constraint documentos_editor_index_required
  check (block_index is not null and octet_length(block_index) between 1 and 8388608
    and block_index_sha256 is not null and block_index_sha256=encode(sha256(block_index),'hex')
    and index_mode is not null and index_mode in
      ('initial','reconciled','rebuilt_missing_index','rebuilt_build','operational_patch','template_application')) not valid;

alter table public.documentos_editor_revisoes add constraint documentos_editor_template_proof_required
  check (case when index_mode='template_application'
    then template_version_id is not null and template_proof is not null
      and jsonb_typeof(template_proof)='object'
      and template_proof->>'schema'='gc-wordcraft-template-application/v1'
    else template_version_id is null and template_proof is null end) not valid;

create index documentos_editor_template_version
  on public.documentos_editor_revisoes(template_version_id)
  where template_version_id is not null;

create function public.documento_editor_template_prova()
returns trigger language plpgsql security invoker set search_path='' as $$
declare
  v_raw text := pg_catalog.current_setting('app.wordcraft_template_proof',true);
  v_proof jsonb;
begin
  if v_raw is null or v_raw='' then return new; end if;
  v_proof:=v_raw::jsonb;
  if pg_catalog.jsonb_typeof(v_proof) is distinct from 'object'
     or v_proof->>'schema' is distinct from 'gc-wordcraft-template-application/v1'
     or v_proof->>'operationId' is distinct from new.operation_id::text
     or v_proof->>'documentId' is distinct from new.document_id::text
     or (v_proof->>'sourceRevision')::bigint is distinct from new.source_revision
     or v_proof->>'sourceHash' is null
     or v_proof->>'targetRevision' is distinct from new.revision::text
     or v_proof->>'targetHash' is distinct from new.content_hash
     or v_proof->>'engineManifestHash' is distinct from new.engine_build_sha256
     or v_proof->'officialEmission' is distinct from 'false'::jsonb
     or pg_catalog.jsonb_typeof(v_proof->'template') is distinct from 'object'
     or pg_catalog.jsonb_typeof(v_proof->'clausesUsed') is distinct from 'array'
     or (select count(*) from pg_catalog.jsonb_object_keys(v_proof))<>16 then
    raise exception 'invalid native template proof' using errcode='22023';
  end if;
  new.index_mode:='template_application';
  new.template_version_id:=(v_proof->'template'->>'versionId')::uuid;
  new.template_proof:=v_proof;
  return new;
end $$;
revoke all on function public.documento_editor_template_prova()
  from public,anon,authenticated,service_role;
create trigger documento_editor_template_prova
  before insert on public.documentos_editor_revisoes
  for each row execute function public.documento_editor_template_prova();

create function public.documento_editor_aplicar_template(
  p_document uuid,p_process uuid,p_tipo text,p_expected_revision bigint,
  p_operation uuid,p_payload bytea,p_content_hash text,p_engine_build_sha256 text,
  p_block_index bytea,p_block_index_sha256 text,
  p_institutional_snapshot bytea,p_institutional_snapshot_sha256 text,
  p_template_version uuid,p_template_hash text,p_provenance jsonb,p_claims jsonb)
returns table(document_id uuid,revision bigint,content_hash text,operation_id uuid,
  replayed boolean,engine_build_sha256 text,validation_provenance text,
  block_index_sha256 text,index_mode text,institutional_snapshot_sha256 text,
  template_version_id uuid,template_hash text,template_proof jsonb)
language plpgsql security invoker set search_path=''
set lock_timeout='2s' set statement_timeout='8s' as $$
declare
  v_old text:=pg_catalog.current_setting('request.jwt.claims',true);
  v_actor uuid;
  v_process public.processos%rowtype;
  v_head public.documentos_editor%rowtype;
  v_prior public.documentos_editor_revisoes%rowtype;
  v_version public.governanca_versoes%rowtype;
  v_artifact public.governanca_artefatos%rowtype;
  v_receipt record;
  v_revision public.documentos_editor_revisoes%rowtype;
  v_rank integer;
  v_count integer;
begin
  if p_document is null or p_process is null or p_operation is null
     or p_template_version is null or p_expected_revision is null or p_expected_revision<1
     or p_tipo is null or p_tipo!~'^[a-z][a-z0-9_]{0,63}$'
     or p_template_hash is null or p_template_hash!~'^[0-9a-f]{64}$'
     or p_provenance is null or pg_catalog.jsonb_typeof(p_provenance)<>'object'
     or p_provenance->>'schema' is distinct from 'gc-wordcraft-template-application/v1'
     or p_provenance->>'operationId' is distinct from p_operation::text
     or p_provenance->>'processId' is distinct from p_process::text
     or p_provenance->>'documentId' is distinct from p_document::text
     or p_provenance->>'docKey' is distinct from p_tipo
     or p_provenance->>'sourceRevision' is distinct from p_expected_revision::text
     or p_provenance->>'targetRevision' is distinct from (p_expected_revision+1)::text
     or p_provenance->>'targetHash' is distinct from p_content_hash
     or p_provenance->>'engineManifestHash' is distinct from p_engine_build_sha256
     or p_provenance->'officialEmission' is distinct from 'false'::jsonb
     or p_provenance->'template'->>'versionId' is distinct from p_template_version::text
     or p_provenance->'template'->>'hash' is distinct from p_template_hash
     or pg_catalog.jsonb_typeof(p_provenance->'clausesUsed') is distinct from 'array'
     or (select count(*) from pg_catalog.jsonb_object_keys(p_provenance))<>16
     or p_claims is null or pg_catalog.jsonb_typeof(p_claims)<>'object'
     or p_claims->>'role' is distinct from 'authenticated'
     or pg_catalog.jsonb_typeof(p_claims->'app_metadata') is distinct from 'object' then
    raise exception 'invalid native template application contract' using errcode='22023';
  end if;
  perform pg_catalog.set_config('request.jwt.claims',p_claims::text,true);
  v_actor:=auth.uid();
  if v_actor is null or p_provenance->>'actorId' is distinct from v_actor::text
     or not coalesce(public.documento_editor_sessao_valida(),false) then
    raise exception 'native template actor denied' using errcode='42501';
  end if;
  perform 1 from public.usuarios u where u.auth_user_id=v_actor for share;
  if not coalesce(public.documento_editor_sessao_valida(),false) then
    raise exception 'native template actor revoked' using errcode='42501';
  end if;
  select * into v_process from public.processos p where p.id=p_process for share;
  if not found or not coalesce(public.pode_ler_processo(v_process.tenant_id,v_process.secretaria_id),false)
     or not coalesce(v_process.auth_user_id=v_actor or public.e_admin(),false) then
    raise exception 'native template process denied' using errcode='42501';
  end if;
  select * into v_head from public.documentos_editor d
    where d.id=p_document and d.processo_id=p_process and d.tipo=p_tipo for update;
  if not found or v_head.tenant_id<>v_process.tenant_id
     or v_head.status not in ('rascunho','em_revisao') then
    raise exception 'native template document denied' using errcode='42501';
  end if;
  select * into v_prior from public.documentos_editor_revisoes r
    where r.document_id=p_document and r.operation_id=p_operation;
  if found then
    if v_prior.index_mode is distinct from 'template_application'
       or v_prior.source_revision is distinct from p_expected_revision
       or v_prior.content_hash is distinct from p_content_hash
       or v_prior.template_version_id is distinct from p_template_version
       or v_prior.template_proof is distinct from p_provenance
       or v_prior.created_by is distinct from v_actor then
      raise exception 'native template operation differs' using errcode='PT409';
    end if;
    perform pg_catalog.set_config('request.jwt.claims',coalesce(v_old,''),true);
    return query select v_prior.document_id,v_prior.revision,v_prior.content_hash,p_operation,true,
      v_prior.engine_build_sha256,v_prior.validation_provenance,v_prior.block_index_sha256,
      v_prior.index_mode,v_prior.institutional_snapshot_sha256,v_prior.template_version_id,
      p_template_hash,v_prior.template_proof;
    return;
  end if;
  if v_head.revision<>p_expected_revision or v_head.content_hash is distinct from p_provenance->>'sourceHash' then
    raise exception 'native template source changed' using errcode='PT409';
  end if;
  select v.* into v_version from public.governanca_versoes v
    where v.id=p_template_version for share;
  if not found then raise exception 'native template version missing' using errcode='42501'; end if;
  select a.* into v_artifact from public.governanca_artefatos a
    where a.id=v_version.artefato_id for share;
  if not found or v_artifact.tipo_artefato<>'template'
     or v_artifact.tenant_id is distinct from v_process.tenant_id
     or not (v_artifact.secretaria_id is null
        or v_artifact.secretaria_id is not distinct from v_process.secretaria_id)
     or v_version.status<>'PUBLISHED'
     or (v_version.vigencia_inicio is not null and pg_catalog.now()<v_version.vigencia_inicio)
     or (v_version.vigencia_fim is not null and pg_catalog.now()>=v_version.vigencia_fim)
     or v_version.hash is distinct from p_template_hash
     or v_artifact.id::text is distinct from p_provenance->'template'->>'artifactId'
     or v_artifact.chave_estavel is distinct from p_provenance->'template'->>'key'
     or v_version.versao::text is distinct from p_provenance->'template'->>'version'
     or not (v_version.payload->'documentos_suportados' ? p_tipo) then
    raise exception 'native template is not effective' using errcode='42501';
  end if;
  v_rank:=case when v_artifact.secretaria_id is null then 0 else 1 end;
  select count(*) into v_count
    from public.governanca_versoes v join public.governanca_artefatos a on a.id=v.artefato_id
    where a.tipo_artefato='template' and a.tenant_id=v_process.tenant_id
      and (a.secretaria_id is null or a.secretaria_id is not distinct from v_process.secretaria_id)
      and v.status='PUBLISHED'
      and (v.vigencia_inicio is null or pg_catalog.now()>=v.vigencia_inicio)
      and (v.vigencia_fim is null or pg_catalog.now()<v.vigencia_fim)
      and v.payload->'documentos_suportados' ? p_tipo
      and (case when a.secretaria_id is null then 0 else 1 end)>=v_rank;
  if v_count<>1 then
    raise exception 'native template resolution is ambiguous' using errcode='PT409';
  end if;
  perform pg_catalog.set_config('app.wordcraft_template_proof',p_provenance::text,true);
  select * into v_receipt from public.documento_editor_checkpoint(
    p_document,p_process,p_tipo,p_expected_revision,p_operation,p_payload,p_content_hash,p_claims,
    p_engine_build_sha256,p_block_index,p_block_index_sha256,'reconciled',
    null,null,null,null,p_institutional_snapshot,p_institutional_snapshot_sha256);
  select * into v_revision from public.documentos_editor_revisoes r
    where r.document_id=p_document and r.revision=v_receipt.revision;
  if not found or v_revision.index_mode<>'template_application'
     or v_revision.template_version_id<>p_template_version
     or v_revision.template_proof is distinct from p_provenance then
    raise exception 'native template lineage missing' using errcode='40001';
  end if;
  perform pg_catalog.set_config('request.jwt.claims',coalesce(v_old,''),true);
  return query select v_revision.document_id,v_revision.revision,v_revision.content_hash,p_operation,false,
    v_revision.engine_build_sha256,v_revision.validation_provenance,v_revision.block_index_sha256,
    v_revision.index_mode,v_revision.institutional_snapshot_sha256,v_revision.template_version_id,
    p_template_hash,v_revision.template_proof;
end $$;

revoke all on function public.documento_editor_aplicar_template(
  uuid,uuid,text,bigint,uuid,bytea,text,text,bytea,text,bytea,text,uuid,text,jsonb,jsonb)
  from public,anon,authenticated;
grant execute on function public.documento_editor_aplicar_template(
  uuid,uuid,text,bigint,uuid,bytea,text,text,bytea,text,bytea,text,uuid,text,jsonb,jsonb)
  to service_role;

revoke update,delete,truncate on public.documentos_editor_revisoes
  from service_role,authenticated,anon,public;

commit;
