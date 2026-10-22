-- ## 0033 — As FLAGS do painel para a API (/api/v1), e só elas
-- ## ESTADO: APLICADA EM PRODUÇÃO em 22/10/2026 como `m0033_flags_do_app`
-- ##   (registro 20261022222239), depois do ensaio no projeto descartável
-- ##   `govdocs-ensaio-descartavel` no mesmo dia.
--
-- REGISTRO DA APLICAÇÃO EM PRODUÇÃO (22/10/2026):
--   * ANTES: `config_app` com 57 linhas, 0 grants a anon/authenticated, 0
--     políticas; sem a função;
--   * aplicação: conferência interna aprovada;
--   * DEPOIS: a função existe, SECURITY DEFINER; `anon` sem EXECUTE,
--     `authenticated` com; `config_app` igual (57 linhas, 0 grants, 0
--     políticas); 0 grants ao anon em public;
--   * comportamento, num bloco desfeito (nada gravado), com um usuário
--     real e claims injetadas: lê 50 flags e 0 não-flags pela função;
--     `flag_precos_ciencia_emissao` = on (a ciência VALE pela API); a
--     tabela continua negada (insufficient_privilege);
--   * advisors de segurança: o aviso NOVO é o esperado —
--     `authenticated_security_definer_function_executable` para
--     `flags_do_app`. É a intenção (ver "O QUE NÃO RESOLVE"); os demais
--     avisos são anteriores.
--
-- REGISTRO DO ENSAIO (22/10/2026):
--   * nível 1: PostgreSQL do CI, tests/test_migracao_0033.py;
--   * nível 2, descartável: antes, `config_app` com 6 linhas (5 flags),
--     sem função, 0 grants e 0 políticas na tabela; depois, a função
--     existe, conferência interna aprovada, tabela igual (0 grants, 0
--     políticas);
--   * comportamento, num bloco desfeito, com um usuário real e claims
--     injetadas: `authenticated` lê 5 flags e 0 não-flags pela função; a
--     tabela continua negada (insufficient_privilege); `anon` sem EXECUTE.
--
-- O PROBLEMA (achado no P04d, 22/10/2026)
--   O domínio lê as feature flags de `config_app` (`db.flag_ativa`) com a
--   credencial de SERVIDOR. A API não tem essa credencial (ADR-002), e a
--   0018 fechou `config_app` para `anon` e `authenticated` — a tabela
--   guarda segredos. Resultado medido: no processo da API toda flag lia
--   DESLIGADA. Na coleta (P04c), teto automático e triagem pré-cesta não
--   valiam pela API; na emissão (P04d), a ciência dos alertas (RF-03)
--   seria pulada.
--
-- O QUE FAZ
--   `public.flags_do_app()`: SECURITY DEFINER, `search_path` vazio,
--   devolve (chave, valor) só das linhas `flag_%` cujo valor é um booleano
--   reconhecido — o mesmo vocabulário de `db.flag_ativa`. Uma chave mal
--   nomeada que guarde segredo (`flag_x` = 'sk-...') NÃO sai. Executável
--   só por `authenticated`; `anon` e `public` sem EXECUTE.
--
--   A TABELA continua fechada: nenhum grant, nenhuma política nova em
--   `config_app` (a matriz da 0018/0020 e suas provas valem inteiras).
--
-- AUDITORIA ANTES DE ESCREVER (produção, 22/10/2026, catálogo + contagem):
--   * `config_app`: 57 linhas, 50 `flag_%`, um tenant; nenhuma linha
--     `flag_%` com valor fora do vocabulário booleano;
--   * não existe função `flags_do_app`;
--   * as flags são do APP, não do município (`db.flag_ativa` não filtra
--     tenant), e a função preserva isso.
--
-- O QUE NÃO RESOLVE
--   * qualquer usuário autenticado passa a saber quais flags estão
--     ligadas. É comportamento do produto, não dado de município nem
--     segredo, e a tela já o revela pelo que mostra.

create or replace function public.flags_do_app()
returns table (chave text, valor text)
language sql
stable
security definer
set search_path = ''
as $$
  select c.chave, c.valor
    from public.config_app c
   where c.chave like 'flag\_%' escape '\'
     and c.valor ~* '^(1|true|on|sim|0|false|off|nao|não)?$'
   order by c.chave
$$;

comment on function public.flags_do_app() is
  'Só as feature flags (flag_*) com valor booleano, para a API sem credencial '
  'de servidor (0033). A tabela config_app continua fechada.';

revoke all on function public.flags_do_app() from public, anon;
grant execute on function public.flags_do_app() to authenticated;

-- ---------------------------------------------------------------
-- Conferência que falha sozinha
-- ---------------------------------------------------------------
do $$
declare
  faltou text := '';
begin
  if not exists (select 1 from pg_proc p
                 where p.oid = 'public.flags_do_app()'::regprocedure
                   and p.prosecdef
                   and coalesce(array_to_string(p.proconfig, ','), '') like '%search_path=%') then
    faltou := faltou || ' definer_com_search_path;';
  end if;
  if has_function_privilege('anon', 'public.flags_do_app()', 'execute') then
    faltou := faltou || ' anon_executa;';
  end if;
  if not has_function_privilege('authenticated', 'public.flags_do_app()', 'execute') then
    faltou := faltou || ' authenticated_sem_execute;';
  end if;
  -- A tabela continua fechada.
  if exists (select 1 from information_schema.role_table_grants
             where table_schema = 'public' and table_name = 'config_app'
               and grantee in ('anon', 'authenticated')) then
    faltou := faltou || ' config_app_com_grant;';
  end if;
  if exists (select 1 from pg_policies
             where schemaname = 'public' and tablename = 'config_app') then
    faltou := faltou || ' config_app_com_politica;';
  end if;
  -- Nada que não seja flag sai pela função.
  if exists (select 1 from public.flags_do_app() f where f.chave not like 'flag\_%' escape '\') then
    faltou := faltou || ' vaza_nao_flag;';
  end if;
  if faltou <> '' then
    raise exception 'A 0033 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
