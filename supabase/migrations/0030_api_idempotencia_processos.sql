-- ## 0030 — Idempotência na criação de processo pela API (/api/v1, P02)
-- ## ESTADO: APLICADA no projeto descartável `govdocs-ensaio-descartavel`
-- ##   em 22/10/2026 como `m0030_api_idempotencia_processos`.
-- ##   NÃO APLICADA EM PRODUÇÃO (atualizar este cabeçalho ao aplicar).
-- ##   Só a API nova usa a coluna; o Streamlit não a lê nem a escreve.
--
-- REGISTRO DO ENSAIO (22/10/2026):
--   * nível 1: PostgreSQL do CI, `tests/test_migracao_0030.py` verde no
--     PR #78 (unicidade por município, NULL sem colisão, formato,
--     privilégios iguais, conferência morde sem o índice);
--   * nível 2, projeto descartável, ANTES e DEPOIS: grants de
--     `processos` idênticos (authenticated INSERT/SELECT/UPDATE;
--     service_role sem TRUNCATE; anon nenhum), três políticas
--     idênticas, 1 linha antes e depois, 0 linhas com chave; índice
--     novo presente. Conferência interna aprovada;
--   * comportamento no descartável, num bloco desfeito por exceção
--     (0 tenants de ensaio restantes): chave repetida no mesmo tenant
--     recusada (unique_violation), aceita em outro tenant, NULLs sem
--     colisão, 'tem espaco' recusada (check_violation);
--   * produção: medição ANTES feita (7 linhas, mesmos grants e
--     políticas); a aplicação foi bloqueada pelo controle de permissão
--     do agente e aguarda o operador.
--
-- O QUE FAZ
--   `processos.idempotency_key` + índice único PARCIAL em
--   (tenant_id, idempotency_key). `POST /api/v1/processos` exige o
--   cabeçalho `Idempotency-Key`; repetir a mesma chave — o navegador
--   que reenvia, o usuário que clica duas vezes, o retry depois de um
--   timeout — devolve o processo já criado em vez de criar outro.
--
-- POR QUE NO BANCO, E NÃO NA API
--   A API em memória não vê a requisição concorrente da outra thread
--   nem a da réplica. Só a unicidade no Postgres decide "quem chegou
--   primeiro" sem corrida: o segundo INSERT recebe 23505 e a API
--   responde com o processo do primeiro (`apps/api/govconect_api/processos.py`).
--
-- AUDITORIA ANTES DE ESCREVER (catálogo, 22/10/2026):
--   * produção e descartável: `processos` com as mesmas 15 colunas, sem
--     `idempotency_key`; produção com 7 linhas;
--   * grants de `processos` são de TABELA (authenticated: SELECT,
--     INSERT, UPDATE; nenhum grant por coluna além dos implícitos). A
--     coluna nova herda exatamente esses — nem mais, nem menos. Nada de
--     privilégio muda aqui, e a conferência no fim mede isso;
--   * RLS de `processos` (0020) intocado: a coluna não entra em política.
--
-- ESCOLHAS
--   * nullable, sem default: as 7 linhas atuais e todo processo criado
--     pelo Streamlit ficam com NULL, e o índice PARCIAL os ignora — nada
--     de backfill, nada de chave inventada para dado antigo;
--   * única por MUNICÍPIO, não global: chave escolhida pelo cliente não
--     pode virar canal entre prefeituras (a colisão de A não revela nem
--     bloqueia nada em B);
--   * CHECK com o mesmo formato que a API aceita: quem escrever direto
--     pelo PostgREST não grava lixo que a API depois não reconheça.
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * o `authenticated` pode ALTERAR a chave do próprio processo pelo
--     PostgREST (o UPDATE da 0020 é de tabela). Efeito máximo: a pessoa
--     estraga a idempotência dos PRÓPRIOS envios; não alcança processo
--     alheio, que a política de edição já barra. Fechar isso exigiria
--     trocar o grant de UPDATE por lista de colunas — mudança de
--     contrato com o Streamlit, fora do escopo;
--   * idempotência de pesquisa de preços, relatório e exportação: cada
--     um ganha a sua quando virar job (P04, ADR-004).

alter table public.processos
  add column if not exists idempotency_key text;

alter table public.processos
  drop constraint if exists processos_idempotency_key_formato;
alter table public.processos
  add constraint processos_idempotency_key_formato
  check (idempotency_key is null
         or idempotency_key ~ '^[A-Za-z0-9._:-]{8,128}$');

create unique index if not exists processos_tenant_idempotency_uidx
  on public.processos (tenant_id, idempotency_key)
  where idempotency_key is not null;

comment on column public.processos.idempotency_key is
  'Chave de idempotência do POST /api/v1/processos; única por tenant. '
  'NULL para processos criados pelo Streamlit.';

-- ---------------------------------------------------------------
-- Conferência que falha sozinha
-- ---------------------------------------------------------------
do $$
declare
  faltou text := '';
begin
  if not exists (select 1 from information_schema.columns
                 where table_schema = 'public' and table_name = 'processos'
                   and column_name = 'idempotency_key' and is_nullable = 'YES') then
    faltou := faltou || ' coluna;';
  end if;
  if not exists (select 1 from pg_indexes
                 where schemaname = 'public'
                   and indexname = 'processos_tenant_idempotency_uidx'
                   and indexdef ilike '%unique%'
                   and indexdef ilike '%where (idempotency_key is not null)%') then
    faltou := faltou || ' indice_unico_parcial;';
  end if;
  if not exists (select 1 from pg_constraint
                 where conname = 'processos_idempotency_key_formato'
                   and conrelid = 'public.processos'::regclass) then
    faltou := faltou || ' check_formato;';
  end if;
  -- Nada de privilégio pode ter mudado: os mesmos três de rede.
  if (select string_agg(privilege_type, ',' order by privilege_type)
        from information_schema.role_table_grants
       where table_schema = 'public' and table_name = 'processos'
         and grantee = 'authenticated') is distinct from 'INSERT,SELECT,UPDATE' then
    faltou := faltou || ' grants_authenticated_alterados;';
  end if;
  if exists (select 1 from information_schema.role_table_grants
             where table_schema = 'public' and table_name = 'processos'
               and grantee = 'anon') then
    faltou := faltou || ' anon_com_grant;';
  end if;
  if faltou <> '' then
    raise exception 'A 0030 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
