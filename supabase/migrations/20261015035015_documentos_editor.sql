-- Experimental document owner for the G1 slice. Never apply remotely without
-- authorization. Process/auth/tenant rules remain owned by existing tables.
begin;

create table public.documentos_editor (
  id uuid primary key,
  processo_id uuid not null references public.processos(id) on delete restrict,
  tenant_id uuid not null references public.tenants(id) on delete restrict,
  tipo text not null check (tipo ~ '^[a-z][a-z0-9_]{0,63}$'),
  revision bigint not null default 0 check (revision >= 0),
  content_hash text not null default repeat('0',64) check (content_hash ~ '^[0-9a-f]{64}$'),
  status text not null default 'rascunho'
    check (status in ('rascunho','em_revisao','aprovado','emitido','substituido')),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  modified_at timestamptz not null default now(),
  unique (processo_id, tipo)
);

create table public.documentos_editor_revisoes (
  document_id uuid not null references public.documentos_editor(id) on delete restrict,
  revision bigint not null check (revision > 0),
  source_revision bigint not null check (source_revision = revision - 1),
  operation_id uuid not null,
  payload bytea not null check (octet_length(payload) between 1 and 8388608),
  content_hash text not null check (content_hash = encode(sha256(payload), 'hex')),
  editor_schema_version text not null default 'gc-wordcraft-snapshot/v1'
    check (editor_schema_version = 'gc-wordcraft-snapshot/v1'),
  engine_version text not null default '0.7.0',
  wordcraft_commit text not null default '533615620ef91ae57fa7aa4cd77fd98b2179e693',
  created_by uuid not null,
  created_at timestamptz not null default now(),
  primary key (document_id, revision),
  unique (document_id, operation_id)
);

alter table public.documentos_editor enable row level security;
alter table public.documentos_editor_revisoes enable row level security;
revoke all on public.documentos_editor, public.documentos_editor_revisoes
  from public, anon, authenticated, service_role;
grant select on public.documentos_editor, public.documentos_editor_revisoes to authenticated;
grant select, insert, update on public.documentos_editor to service_role;
grant select, insert on public.documentos_editor_revisoes to service_role;

-- Reconcile the verified JWT with the current canonical profile. A revoked or
-- moved account must not retain document access until its old JWT expires.
create function public.documento_editor_sessao_valida()
returns boolean language sql stable security invoker set search_path = ''
as $$
  select coalesce(auth.jwt()->>'role','') = 'authenticated' and exists (
    select 1 from public.usuarios u where u.auth_user_id = auth.uid() and u.ativo
      and u.tenant_id = public.tenant_do_jwt()
      and u.secretaria_id is not distinct from public.secretaria_do_jwt()
      and u.papel = public.papel_do_jwt()
  )
$$;
revoke all on function public.documento_editor_sessao_valida() from public, anon;
grant execute on function public.documento_editor_sessao_valida() to authenticated, service_role;

create policy documentos_editor_le on public.documentos_editor for select to authenticated
using ((select public.documento_editor_sessao_valida()) and exists (
  select 1 from public.processos p
  where p.id = processo_id and p.tenant_id = documentos_editor.tenant_id
    and public.pode_ler_processo(p.tenant_id, p.secretaria_id)
));
create policy documentos_editor_revisoes_le on public.documentos_editor_revisoes for select to authenticated
using (exists (
  select 1 from public.documentos_editor d where d.id = document_id
));

-- This returns only the caller's JWT-verified identity. It neither accepts claims
-- from a browser payload nor creates a second authentication mechanism.
create function public.documento_editor_contexto()
returns jsonb language plpgsql stable security invoker set search_path = ''
as $$
begin
  if not coalesce(public.documento_editor_sessao_valida(),false) then
    raise exception 'authenticated document session required' using errcode = '42501';
  end if;
  return pg_catalog.jsonb_build_object('sub', auth.uid(), 'role', 'authenticated',
    'app_metadata', auth.jwt()->'app_metadata');
end;
$$;
revoke all on function public.documento_editor_contexto() from public, anon, service_role;
grant execute on function public.documento_editor_contexto() to authenticated;

-- Only the trusted backend may call this RPC, AFTER native model validation.
-- p_claims comes from documento_editor_contexto via the user's JWT client, never
-- from component events. Native bytes remain in private DB rows, not public URLs.
create function public.documento_editor_checkpoint(
  p_document uuid, p_process uuid, p_tipo text, p_expected_revision bigint,
  p_operation uuid, p_payload bytea, p_content_hash text, p_claims jsonb)
returns table(document_id uuid, revision bigint, content_hash text, operation_id uuid, replayed boolean)
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
  if p_document is null or p_process is null or p_operation is null
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
       or v_previous.source_revision <> p_expected_revision or v_previous.created_by <> v_actor then
      raise exception 'operation identity conflict' using errcode = '40001';
    end if;
    perform pg_catalog.set_config('request.jwt.claims', coalesce(v_old_claims,''), true);
    return query select p_document, v_previous.revision, v_previous.content_hash, p_operation, true;
    return;
  end if;
  if v_document.revision <> p_expected_revision then
    raise exception 'document revision conflict' using errcode = '40001';
  end if;
  v_next := v_document.revision + 1;
  insert into public.documentos_editor_revisoes
    (document_id, revision, source_revision, operation_id, payload, content_hash, created_by)
    values (p_document, v_next, p_expected_revision, p_operation, p_payload, p_content_hash, v_actor);
  update public.documentos_editor d set revision = v_next,
    content_hash = p_content_hash, modified_at = pg_catalog.now() where d.id = p_document;
  perform pg_catalog.set_config('request.jwt.claims', coalesce(v_old_claims,''), true);
  return query select p_document, v_next, p_content_hash, p_operation, false;
end;
$$;
revoke all on function public.documento_editor_checkpoint(uuid,uuid,text,bigint,uuid,bytea,text,jsonb)
  from public, anon, authenticated;
grant execute on function public.documento_editor_checkpoint(uuid,uuid,text,bigint,uuid,bytea,text,jsonb)
  to service_role;

commit;
