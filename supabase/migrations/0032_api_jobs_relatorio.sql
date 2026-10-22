-- ## 0032 — Jobs da API (/api/v1, P04d): emissão de relatório de preços
-- ## ESTADO: APLICADA no projeto descartável `govdocs-ensaio-descartavel`
-- ##   em 22/10/2026 como `m0032_api_jobs_relatorio` (registro
-- ##   20261022204129). NÃO APLICADA EM PRODUÇÃO (atualizar este cabeçalho
-- ##   ao aplicar, com a medição antes/depois).
-- ##   Só a API nova e o worker usam a tabela; o Streamlit não a conhece.
--
-- REGISTRO DO ENSAIO (22/10/2026):
--   * nível 1: PostgreSQL do CI, tests/test_migracao_0032.py;
--   * nível 2, descartável: 48 -> 48 tabelas (nenhuma nova); CHECK de
--     `tipo` com os dois tipos; 3 políticas; grants iguais aos da 0031
--     (anon nenhum; service_role sem DELETE/TRUNCATE); conferência
--     interna aprovada;
--   * comportamento, num bloco desfeito (0 linhas restantes), com dois
--     usuários reais do mesmo município e claims injetadas: o dono cria
--     job `relatorio_precos` e grava `resultado` (1 linha); `resultado`
--     que não é objeto é recusado (check_violation); o colega não vê (0)
--     nem altera (0 linhas).
--
-- O QUE FAZ (aditiva, nada some):
--   * `api_jobs.tipo` passa a aceitar `relatorio_precos` além de
--     `coleta_precos` — a CHECK é trocada por uma mais larga, com o mesmo
--     nome;
--   * `api_jobs.resultado` (jsonb, objeto, até 4 KB): o que o job produziu
--     para a TELA mostrar — nome do arquivo, tamanho, SHA-256, se a
--     emissão foi registrada, até quando o arquivo fica disponível. Jobs
--     existentes ficam com `{}`.
--
-- O ARQUIVO NÃO MORA AQUI. O relatório gerado fica no Redis da rede
-- interna por 30 min, ao lado dos metadados que o WORKER gravou (ADR-003,
-- revisada no P04d). Quem baixa passa pela API, que confere o job pelo
-- RLS desta tabela (dono + município) antes de ler o Redis. A prova
-- permanente da emissão continua sendo `pesquisa_preco_emissoes` (0029):
-- hash do conteúdo decisório e hash do arquivo.
--
-- AUTORIZAÇÃO: inalterada. As três políticas da 0031 cobrem a coluna nova
-- (o dono escreve no próprio job; ninguém mais lê). O que isso permite e
-- não permite:
--   * o dono pode reescrever `resultado` do próprio job pelo PostgREST.
--     Efeito: a tela DELE mostra outro nome ou outro hash. O download não
--     lê `resultado` — usa os metadados do Redis, que só o worker grava —,
--     e o registro da 0029 não muda. Mesmo limite que a 0031 já declara
--     para `estado`;
--   * colega do município que pode LER a pesquisa pode emitir (regra da
--     0029: "emite quem lê"), e o job é dele — não do dono da pesquisa.
--
-- AUDITORIA ANTES DE ESCREVER (produção, 22/10/2026, catálogo):
--   * a CHECK de `tipo` nasceu sem nome explícito na 0031; o Postgres a
--     chamou `api_jobs_tipo_check` (conferido em pg_constraint);
--   * `api_jobs` tem 0 linhas; nenhuma coluna `resultado`.

alter table public.api_jobs drop constraint if exists api_jobs_tipo_check;
alter table public.api_jobs add constraint api_jobs_tipo_check
  check (tipo in ('coleta_precos', 'relatorio_precos'));

alter table public.api_jobs
  add column if not exists resultado jsonb not null default '{}'::jsonb;

alter table public.api_jobs drop constraint if exists api_jobs_resultado_objeto;
alter table public.api_jobs add constraint api_jobs_resultado_objeto
  check (jsonb_typeof(resultado) = 'object' and pg_column_size(resultado) <= 4096);

-- ---------------------------------------------------------------
-- Conferência que falha sozinha
-- ---------------------------------------------------------------
do $$
declare
  faltou text := '';
begin
  if not exists (select 1 from pg_constraint
                 where conrelid = 'public.api_jobs'::regclass
                   and conname = 'api_jobs_tipo_check'
                   and pg_get_constraintdef(oid) like '%relatorio_precos%'
                   and pg_get_constraintdef(oid) like '%coleta_precos%') then
    faltou := faltou || ' tipo_relatorio;';
  end if;
  if not exists (select 1 from information_schema.columns
                 where table_schema = 'public' and table_name = 'api_jobs'
                   and column_name = 'resultado' and data_type = 'jsonb'
                   and is_nullable = 'NO') then
    faltou := faltou || ' coluna_resultado;';
  end if;
  if not exists (select 1 from pg_constraint
                 where conrelid = 'public.api_jobs'::regclass
                   and conname = 'api_jobs_resultado_objeto') then
    faltou := faltou || ' limite_do_resultado;';
  end if;
  -- O que a 0031 garantiu continua garantido.
  if not (select relrowsecurity and relforcerowsecurity from pg_class
          where oid = 'public.api_jobs'::regclass) then
    faltou := faltou || ' rls_ligada_e_forcada;';
  end if;
  if (select count(*) from pg_policies
      where schemaname = 'public' and tablename = 'api_jobs') <> 3 then
    faltou := faltou || ' tres_politicas;';
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
  if faltou <> '' then
    raise exception 'A 0032 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
