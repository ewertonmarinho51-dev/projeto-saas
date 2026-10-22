-- ## 0031 — Jobs da API (/api/v1, P04c): coleta de preços assíncrona
-- ## ESTADO: aplicável. NÃO APLICADA em produção nem no descartável
-- ##   (atualizar este cabeçalho ao aplicar: data e nome).
-- ##   Só a API nova e o worker usam a tabela; o Streamlit não a conhece.
--
-- O QUE FAZ
--   `public.api_jobs`: o registro de NEGÓCIO de cada tarefa longa — quem
--   pediu, de que município, sobre qual recurso, em que estado, quanto
--   andou, quantas tentativas, e o código seguro da falha. O broker
--   (Redis) só transporta o aviso "processe o job X"; a verdade sobre o
--   job mora aqui (ADR-004: a fila não é fonte de verdade).
--
-- O progresso REAL da coleta continua sendo o estado de cada item em
-- `pesquisa_preco_itens` (o domínio retoma de onde parou). Este registro
-- é o que a tela consulta — `feitos/total` — e o que sobra quando o
-- worker cai no meio.
--
-- AUDITORIA ANTES DE ESCREVER (produção, 22/10/2026, catálogo):
--   * `pg_default_acl` de `postgres` (quem roda a migração): tabela nova
--     nasce com `service_role` = arwdxtm (sem TRUNCATE, com DELETE) e
--     NADA para `anon`/`authenticated`. Os grants abaixo são explícitos;
--   * não existe tabela de jobs; `public.set_atualizado_em()` existe (0001).
--
-- AUTORIZAÇÃO
--   Dono E município: lê, cria e atualiza só o job que é seu, no tenant
--   do seu JWT. O worker atualiza o job COM O TOKEN DO DONO — as tabelas
--   de preços (0021) não dão escrita a mais ninguém, e o worker não tem
--   credencial de servidor. Sem política de DELETE: job encerrado fica
--   como registro.
--
-- IDEMPOTÊNCIA
--   `(tenant_id, idempotency_key)` única: o segundo POST com a mesma
--   chave recebe 23505 e a API devolve o job do primeiro, em vez de pôr
--   duas coletas da mesma pesquisa na fila.
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * o dono pode escrever no próprio job pelo PostgREST (marcar como
--     concluído, por exemplo). Efeito: a tela dele mente para ele mesmo;
--     os preços continuam onde o domínio os gravou. Fechar exigiria um
--     papel de worker com credencial própria — decisão para o P06;
--   * retenção: nada apaga jobs antigos. Rotina de limpeza é P06.

create table if not exists public.api_jobs (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  iniciado_em timestamptz,
  concluido_em timestamptz,

  tenant_id uuid not null references public.tenants (id),
  auth_user_id uuid not null references auth.users (id),

  tipo text not null check (tipo in ('coleta_precos')),
  recurso_id uuid not null,
  parametros jsonb not null default '{}'::jsonb,

  estado text not null default 'queued'
    check (estado in ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  feitos integer not null default 0 check (feitos >= 0),
  total integer not null default 0 check (total >= 0),
  tentativas integer not null default 0 check (tentativas >= 0),
  erro_codigo text not null default ''
    check (erro_codigo ~ '^[A-Z_]{0,40}$'),

  idempotency_key text not null
    check (idempotency_key ~ '^[A-Za-z0-9._:-]{8,128}$'),

  constraint api_jobs_feitos_ate_total check (feitos <= total or total = 0),
  constraint api_jobs_idempotencia unique (tenant_id, idempotency_key)
);

create index if not exists api_jobs_dono_idx
  on public.api_jobs (auth_user_id, criado_em desc);
create index if not exists api_jobs_recurso_idx
  on public.api_jobs (recurso_id, criado_em desc);

drop trigger if exists api_jobs_carimbo on public.api_jobs;
create trigger api_jobs_carimbo
  before update on public.api_jobs
  for each row execute function public.set_atualizado_em();

alter table public.api_jobs enable row level security;
alter table public.api_jobs force row level security;

drop policy if exists "api_jobs_le" on public.api_jobs;
create policy "api_jobs_le" on public.api_jobs
  for select to authenticated
  using (auth_user_id = auth.uid() and tenant_id = public.tenant_do_jwt());

drop policy if exists "api_jobs_insere" on public.api_jobs;
create policy "api_jobs_insere" on public.api_jobs
  for insert to authenticated
  with check (auth_user_id = auth.uid() and tenant_id = public.tenant_do_jwt()
              and estado = 'queued');

drop policy if exists "api_jobs_edita" on public.api_jobs;
create policy "api_jobs_edita" on public.api_jobs
  for update to authenticated
  using      (auth_user_id = auth.uid() and tenant_id = public.tenant_do_jwt())
  with check (auth_user_id = auth.uid() and tenant_id = public.tenant_do_jwt());

revoke all on public.api_jobs from anon, authenticated;
grant select, insert, update on public.api_jobs to authenticated;
-- Servidor sem DELETE/TRUNCATE: o registro do job não some por engano.
revoke delete, truncate on public.api_jobs from service_role;

-- ---------------------------------------------------------------
-- Conferência que falha sozinha
-- ---------------------------------------------------------------
do $$
declare
  faltou text := '';
begin
  if not (select relrowsecurity and relforcerowsecurity from pg_class
          where oid = 'public.api_jobs'::regclass) then
    faltou := faltou || ' rls_ligada_e_forcada;';
  end if;
  if (select count(*) from pg_policies
      where schemaname = 'public' and tablename = 'api_jobs') <> 3 then
    faltou := faltou || ' tres_politicas;';
  end if;
  if exists (select 1 from pg_policies
             where schemaname = 'public' and tablename = 'api_jobs'
               and (coalesce(qual, '') ilike '%true%'
                    or coalesce(with_check, '') ilike '%true%')) then
    faltou := faltou || ' politica_irrestrita;';
  end if;
  if exists (select 1 from information_schema.role_table_grants
             where table_schema = 'public' and table_name = 'api_jobs'
               and grantee = 'anon') then
    faltou := faltou || ' anon_com_grant;';
  end if;
  if (select string_agg(privilege_type, ',' order by privilege_type)
        from information_schema.role_table_grants
       where table_schema = 'public' and table_name = 'api_jobs'
         and grantee = 'authenticated') is distinct from 'INSERT,SELECT,UPDATE' then
    faltou := faltou || ' grants_authenticated;';
  end if;
  if exists (select 1 from information_schema.role_table_grants
             where table_schema = 'public' and table_name = 'api_jobs'
               and grantee = 'service_role'
               and privilege_type in ('DELETE', 'TRUNCATE')) then
    faltou := faltou || ' service_role_apaga;';
  end if;
  if faltou <> '' then
    raise exception 'A 0031 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
