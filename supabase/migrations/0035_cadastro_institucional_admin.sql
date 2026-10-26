-- ## 0035 — Cadastro institucional: o ADMIN edita a prefeitura, cria e
-- ##        edita secretarias e cria/exclui identidades visuais com o
-- ##        próprio JWT (interface nova, M7b)
-- ## ESTADO: APLICADA EM PRODUÇÃO em 25/10/2026 como
-- ##   `m0035_cadastro_institucional_admin` (registro 20261025135801),
-- ##   depois do ensaio no projeto descartável `govdocs-ensaio-descartavel`
-- ##   no mesmo dia.
--
-- REGISTRO DA APLICAÇÃO EM PRODUÇÃO (25/10/2026):
--   * ANTES: 1 prefeitura, 2 secretarias, 2 identidades; 99 políticas em
--     public; 94 grants de tabela a `authenticated`, 0 a `anon`; 30
--     privilégios de coluna (só SELECT) em tenants/secretarias;
--   * aplicação: conferência interna aprovada;
--   * DEPOIS: mesmas 1/2/2 linhas; 104 políticas (+5); 96 grants de tabela
--     (+2: INSERT e DELETE em `config_orgaos`); por coluna, UPDATE dos 8
--     campos de `tenants` e INSERT/UPDATE das colunas previstas de
--     `secretarias` — nada além; 0 grants a `anon`;
--   * comportamento, num bloco desfeito, com segunda prefeitura e
--     registros temporários: admin edita a própria prefeitura (1 linha),
--     não o `slug` (negado) nem a alheia (0); cria e desativa secretaria,
--     não em outra prefeitura, não com origem alheia, não muda tenant nem
--     origem, não apaga (todos negados); cria e exclui a própria identidade,
--     não a alheia; usuário comum: 0 linhas e negado. Nada ficou gravado;
--   * advisors de segurança: nenhum aviso novo.
--
-- REGISTRO DO ENSAIO (25/10/2026):
--   * nível 1: PostgreSQL do CI, tests/test_migracao_0035.py (comportamento
--     e uma mutação por ramo da conferência);
--   * nível 2, descartável: o mesmo estado de produção nas três tabelas;
--     conferência interna aprovada; os mesmos 18 resultados do bloco acima.
--
-- O PROBLEMA (auditoria de produção, 25/10/2026, catálogo)
--   A interface nova escreve com o JWT do usuário (ADR-002); o Streamlit,
--   com a credencial de servidor. Para as três telas do cadastro
--   institucional, o banco só abre LEITURA ao `authenticated`:
--   * `tenants`: SELECT da própria prefeitura (`tenants_le`). Sem UPDATE —
--     "Salvar dados institucionais" não teria como gravar;
--   * `secretarias`: SELECT do tenant (`secretarias_le`). Sem INSERT nem
--     UPDATE — nem criar, nem desativar, nem marcar a padrão;
--   * `config_orgaos` (identidade visual): SELECT e UPDATE do admin. Sem
--     INSERT nem DELETE — editava o que existe, não criava nem excluía.
--   E salvar uma identidade ESPELHA em `secretarias`
--   (`db._espelhar_orgao_em_secretaria`), que hoje recusaria em silêncio:
--   a identidade nasceria sem a secretaria que o resolvedor do timbrado lê.
--
-- O QUE FAZ — só o admin, só a própria prefeitura
--   * `tenants_admin_edita`: UPDATE da linha `id = tenant_do_jwt()`, e o
--     grant é POR COLUNA — os oito campos institucionais da tela
--     (`nome_oficial`, `cnpj`, `sigla`, `cidade`, `endereco`, `telefone`,
--     `email`, `site`). `slug`, `nome`, `uf` e `ativo` continuam fora:
--     são identidade e estado da prefeitura no sistema, não cadastro;
--   * `secretarias_admin_cria` / `secretarias_admin_edita`: INSERT e
--     UPDATE no tenant do JWT, com grant POR COLUNA (`id` e `criado_em`
--     nunca; `tenant_id` e `origem_orgao_id` só no INSERT, e a origem só
--     de identidade do próprio tenant — ver a nota junto da política).
--     Sem DELETE: secretaria se DESATIVA (processos, usuários e portarias
--     apontam para ela);
--   * `config_orgaos_admin_cria` / `config_orgaos_admin_exclui`: INSERT e
--     DELETE no tenant do JWT (o UPDATE já existia, da 0020).
--   O `with check` com `tenant_id = tenant_do_jwt()` é o que impede mudar
--   uma linha para outra prefeitura.
--
-- AUDITORIA ANTES DE ESCREVER (produção, 25/10/2026)
--   * grants de `authenticated`: `tenants` SELECT; `secretarias` SELECT;
--     `config_orgaos` SELECT, UPDATE; `anon` sem nada nas três;
--   * políticas: `tenants_le`, `secretarias_le`, `config_orgaos_le`,
--     `config_orgaos_admin` (UPDATE);
--   * nenhum gatilho nas três; FKs de `secretarias` e `config_orgaos` para
--     `tenants`; `unique (tenant_id, nome)` em `secretarias`.
--
-- O QUE NÃO RESOLVE
--   * o vínculo usuário → secretaria e a flag de resolução automática
--     continuam no Streamlit: o vínculo vive também no `app_metadata` do
--     Auth (credencial de servidor, M7c) e a flag em `config_app`, que é
--     fechada de propósito (0018/0033);
--   * excluir uma identidade NÃO apaga a secretaria espelhada — o mesmo
--     comportamento do Streamlit;
--   * campos de imagem são texto base64 sem teto no banco; o teto é da API;
--   * nada impede duas secretarias `padrao` por PostgREST direto (não há
--     índice único parcial); o resolvedor escolhe a primeira, no próprio
--     tenant. Integridade, não isolamento;
--   * a conferência não lê o corpo das políticas além de recusar `true`;
--     quem prova a lógica é o comportamento (ensaio e bloco desfeito).
--
-- REVISÃO (revisor-de-banco-e-seguranca, 25/10/2026): sem bloqueador; o
-- grant de tabela inteira em `secretarias` da primeira versão deixava o
-- admin gravar `origem_orgao_id` de outra prefeitura — trocado por grant
-- de coluna e `with check` da origem. `db.py` passou a filtrar o tenant
-- no espelho da identidade e na edição de secretaria.

drop policy if exists "tenants_admin_edita" on public.tenants;
create policy "tenants_admin_edita" on public.tenants
  for update to authenticated
  using (public.e_admin() and id = public.tenant_do_jwt())
  with check (public.e_admin() and id = public.tenant_do_jwt());
grant update (nome_oficial, cnpj, sigla, cidade, endereco, telefone, email, site)
  on public.tenants to authenticated;

-- `origem_orgao_id` não tem FK (0007) e o espelho do Streamlit busca a
-- secretaria por ele SEM filtro de tenant, com a credencial de servidor.
-- Aceitar ali o id de uma identidade de OUTRA prefeitura faria o próximo
-- "salvar identidade" daquela prefeitura sobrescrever esta secretaria. Por
-- isso: no INSERT, só identidade do próprio tenant (a subconsulta roda sob
-- `config_orgaos_le`); no UPDATE, a coluna fica fora do grant.
drop policy if exists "secretarias_admin_cria" on public.secretarias;
create policy "secretarias_admin_cria" on public.secretarias
  for insert to authenticated
  with check (public.e_admin() and tenant_id = public.tenant_do_jwt()
              and (origem_orgao_id is null
                   or exists (select 1 from public.config_orgaos o
                               where o.id = secretarias.origem_orgao_id
                                 and o.tenant_id = public.tenant_do_jwt())));
drop policy if exists "secretarias_admin_edita" on public.secretarias;
create policy "secretarias_admin_edita" on public.secretarias
  for update to authenticated
  using (public.e_admin() and tenant_id = public.tenant_do_jwt())
  with check (public.e_admin() and tenant_id = public.tenant_do_jwt());
-- Por coluna: `id` e `criado_em` são do banco; `tenant_id` e
-- `origem_orgao_id` não mudam depois de criados.
grant insert (tenant_id, nome, sigla, ativo, padrao, origem_orgao_id,
              cabecalho, rodape, marca_dagua, cabecalho_img, rodape_img, marca_img,
              cabecalho_pct, rodape_pct)
  on public.secretarias to authenticated;
grant update (nome, sigla, ativo, padrao,
              cabecalho, rodape, marca_dagua, cabecalho_img, rodape_img, marca_img,
              cabecalho_pct, rodape_pct)
  on public.secretarias to authenticated;

drop policy if exists "config_orgaos_admin_cria" on public.config_orgaos;
create policy "config_orgaos_admin_cria" on public.config_orgaos
  for insert to authenticated
  with check (public.e_admin() and tenant_id = public.tenant_do_jwt());
drop policy if exists "config_orgaos_admin_exclui" on public.config_orgaos;
create policy "config_orgaos_admin_exclui" on public.config_orgaos
  for delete to authenticated
  using (public.e_admin() and tenant_id = public.tenant_do_jwt());
grant insert, delete on public.config_orgaos to authenticated;

-- Conferência que falha sozinha: um grant ou uma política que não pegou
-- não levanta erro; este bloco levanta.
do $$
declare faltou text;
begin
  select string_agg(item, ', ') into faltou from (
    -- o que precisa existir
    select 'politica_' || p.nome as item
      from (values ('tenants', 'tenants_admin_edita', 'UPDATE'),
                   ('secretarias', 'secretarias_admin_cria', 'INSERT'),
                   ('secretarias', 'secretarias_admin_edita', 'UPDATE'),
                   ('config_orgaos', 'config_orgaos_admin_cria', 'INSERT'),
                   ('config_orgaos', 'config_orgaos_admin_exclui', 'DELETE'))
           as p(tabela, nome, cmd)
     where not exists (select 1 from pg_policies x
                        where x.schemaname = 'public' and x.tablename = p.tabela
                          and x.policyname = p.nome and x.cmd = p.cmd
                          and x.roles = '{authenticated}'::name[])
    union all
    select 'grant_coluna_tenants_' || c
      from unnest(array['nome_oficial', 'cnpj', 'sigla', 'cidade', 'endereco',
                        'telefone', 'email', 'site']) c
     where not has_column_privilege('authenticated', 'public.tenants', c, 'UPDATE')
    union all
    select 'grant_' || g.priv || '_' || g.tabela
      from (values ('config_orgaos', 'INSERT'), ('config_orgaos', 'DELETE'))
           as g(tabela, priv)
     where not has_table_privilege('authenticated', 'public.' || g.tabela, g.priv)
    union all
    select 'grant_coluna_secretarias_' || lower(g.priv) || '_' || g.coluna
      from (values ('INSERT', 'tenant_id'), ('INSERT', 'nome'), ('INSERT', 'origem_orgao_id'),
                   ('UPDATE', 'nome'), ('UPDATE', 'ativo'), ('UPDATE', 'padrao'),
                   ('UPDATE', 'cabecalho_img')) as g(priv, coluna)
     where not has_column_privilege('authenticated', 'public.secretarias', g.coluna, g.priv)
    union all
    -- secretarias: o que não pode ser escrito por quem não é o banco
    select 'secretarias_coluna_aberta_' || lower(g.priv) || '_' || g.coluna
      from (values ('INSERT', 'id'), ('INSERT', 'criado_em'),
                   ('UPDATE', 'id'), ('UPDATE', 'criado_em'), ('UPDATE', 'tenant_id'),
                   ('UPDATE', 'origem_orgao_id')) as g(priv, coluna)
     where has_column_privilege('authenticated', 'public.secretarias', g.coluna, g.priv)
    union all
    -- política com corpo `true` nas três tabelas: contenção de enfeite
    select 'politica_aberta_' || p.tablename || '_' || p.policyname
      from pg_policies p
     where p.schemaname = 'public'
       and p.tablename in ('tenants', 'secretarias', 'config_orgaos')
       and (coalesce(p.qual, '') = 'true' or coalesce(p.with_check, '') = 'true')
    union all
    -- o que NÃO pode ter vindo junto
    select 'tenants_coluna_aberta_' || c
      from unnest(array['id', 'slug', 'nome', 'uf', 'ativo', 'criado_em']) c
     where has_column_privilege('authenticated', 'public.tenants', c, 'UPDATE')
    union all
    select 'tenants_' || lower(p)
      from unnest(array['INSERT', 'DELETE']) p
     where has_table_privilege('authenticated', 'public.tenants', p)
    union all
    select 'delete_em_secretarias'
     where has_table_privilege('authenticated', 'public.secretarias', 'DELETE')
    union all
    select 'privilegio_largo_em_' || t
      from unnest(array['tenants', 'secretarias', 'config_orgaos']) t
     where has_table_privilege('authenticated', 'public.' || t, 'TRUNCATE,REFERENCES,TRIGGER')
    union all
    select 'anon_em_' || t
      from unnest(array['tenants', 'secretarias', 'config_orgaos']) t
     where has_table_privilege('anon', 'public.' || t, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
        or has_any_column_privilege('anon', 'public.' || t, 'SELECT,INSERT,UPDATE')
    union all
    select 'rls_desligado_em_' || c.relname
      from pg_class c
     where c.oid in ('public.tenants'::regclass, 'public.secretarias'::regclass,
                     'public.config_orgaos'::regclass)
       and not c.relrowsecurity
  ) achados;
  if faltou is not null then
    raise exception 'A 0035 não cumpriu o que afirma: %', faltou;
  end if;
end
$$;
