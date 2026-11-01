-- ## 0039 — Jobs da API: elaboração automática de documentos
-- ## ESTADO: APLICADA EM PRODUÇÃO em 01/11/2026 como
-- ##   `m0039_api_jobs_elaboracao` (registro 20261101152437), depois do ensaio
-- ##   no projeto descartável `govdocs-ensaio-descartavel` no mesmo dia.
-- ##   Só a API nova e o worker usam a tabela; o Streamlit não a conhece.
--
-- REGISTRO DA APLICAÇÃO EM PRODUÇÃO (01/11/2026, catálogo, só SELECT):
--   * ANTES: 48 tabelas; `api_jobs` com 2 linhas, nenhuma ativa; tipos
--     `coleta_precos` e `relatorio_precos`; processos 8; última migração
--     20261031142917;
--   * aplicação: conferência interna aprovada (nenhuma exceção);
--   * DEPOIS: 48 tabelas; `api_jobs` com 2 linhas e processos 8 (inalterados);
--     tipo novo no check; índice único parcial criado; RLS ligada e forçada,
--     3 políticas; grants iguais aos de antes (authenticated INSERT/SELECT/
--     UPDATE, service_role sem DELETE e TRUNCATE, anon nenhum);
--   * comportamento NÃO exercido em produção: foi provado no PostgreSQL do
--     CI (tests/test_migracao_0039.py) e na pilha real do E2E.
--
-- REGISTRO DO ENSAIO (01/11/2026):
--   * nível 1: PostgreSQL do CI, tests/test_migracao_0039.py verde;
--   * nível 2, descartável: 48 tabelas, índice criado, RLS forçada, 3
--     políticas, grants iguais aos de produção; conferência interna aprovada.
--
-- O QUE FAZ
--   * `api_jobs.tipo` passa a aceitar `elaboracao_documento`, além de
--     `coleta_precos` e `relatorio_precos`;
--   * índice único parcial `api_jobs_elaboracao_ativa`: a mesma pessoa não
--     tem dois jobs ativos (`queued`/`running`) de elaboração no mesmo
--     processo. É o banco que impede a geração duplicada por clique
--     repetido ou por duas abas; a tela só desabilita o botão.
--
-- POR QUE POR PESSOA, E NÃO SÓ POR PROCESSO
--   O RLS de `api_jobs` mostra o job só ao dono. Com um índice só por
--   processo, o job abandonado de um administrador travaria o titular para
--   sempre, sem que ele pudesse ver ou encerrar o que o trava. Duas pessoas
--   ao mesmo tempo no mesmo processo são contidas na gravação: o worker
--   substitui o documento com CAS em `processos.atualizado_em`.
--
-- AUDITORIA ANTES DE ESCREVER (produção, 01/11/2026, catálogo):
--   * `api_jobs_tipo_check` aceita `coleta_precos` e `relatorio_precos`;
--   * `api_jobs` tem 2 linhas, nenhuma ativa: o índice nasce sem conflito;
--   * nenhum grant muda aqui, e nenhuma tabela nova nasce.
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * o dono continua podendo escrever no próprio job pelo PostgREST (ver
--     a 0031). Efeito: a tela dele mente para ele mesmo; o documento mora
--     em `processos` e no editor nativo, não no job;
--   * job preso em `queued`/`running` porque o worker morreu: quem encerra
--     é a API, ao ler ou pedir de novo depois de 30 min sem atualização;
--   * retenção de jobs antigos: `parametros` da elaboração guarda o contexto
--     herdado da cadeia aprovada, sob o mesmo RLS. Limpeza continua no P06.

alter table public.api_jobs drop constraint if exists api_jobs_tipo_check;
alter table public.api_jobs add constraint api_jobs_tipo_check
  check (tipo in ('coleta_precos', 'relatorio_precos', 'elaboracao_documento'));

create unique index if not exists api_jobs_elaboracao_ativa
  on public.api_jobs (tenant_id, auth_user_id, recurso_id)
  where tipo = 'elaboracao_documento' and estado in ('queued', 'running');

-- ---------------------------------------------------------------
-- Conferência que falha sozinha
-- ---------------------------------------------------------------
do $$
declare
  definicao text;
begin
  select pg_get_constraintdef(oid) into definicao
    from pg_constraint
   where conrelid = 'public.api_jobs'::regclass and conname = 'api_jobs_tipo_check';
  if definicao is null or definicao not like '%coleta_precos%'
     or definicao not like '%relatorio_precos%' or definicao not like '%elaboracao_documento%' then
    raise exception 'A 0039 não cumpriu o que afirma: tipos de job';
  end if;

  if not exists (
    select 1 from pg_indexes
     where schemaname = 'public' and tablename = 'api_jobs'
       and indexname = 'api_jobs_elaboracao_ativa'
       and indexdef like 'CREATE UNIQUE INDEX%'
       and indexdef like '%elaboracao_documento%') then
    raise exception 'A 0039 não cumpriu o que afirma: índice de job ativo';
  end if;

  if not (select relrowsecurity and relforcerowsecurity from pg_class
           where oid = 'public.api_jobs'::regclass) then
    raise exception 'A 0039 não cumpriu o que afirma: RLS de api_jobs';
  end if;

  if (select count(*) from pg_policies
       where schemaname = 'public' and tablename = 'api_jobs') <> 3 then
    raise exception 'A 0039 não cumpriu o que afirma: políticas de api_jobs';
  end if;

  if exists (select 1 from information_schema.role_table_grants
              where table_schema = 'public' and table_name = 'api_jobs'
                and grantee = 'anon') then
    raise exception 'A 0039 não cumpriu o que afirma: anon com acesso a api_jobs';
  end if;
end
$$;
