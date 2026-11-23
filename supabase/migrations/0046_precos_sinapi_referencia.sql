-- ## 0046 — Referência de custos SINAPI (CAIXA/IBGE), em consulta própria
-- ## ESTADO: NÃO APLICADA EM PRODUÇÃO. Aplicável; aguarda o ensaio nos dois
-- ##   níveis (o do CI roda em `tests/test_migracao_0046.py`), a revisão do
-- ##   `revisor-de-banco-e-seguranca` e a autorização do dono.
--
-- O PROBLEMA (23/11/2026)
--   Obra e serviço de engenharia não se orçam com preço de compra: a Lei
--   14.133 (art. 23, § 2º, I) manda usar o SINAPI como parâmetro de custo. O
--   Gov Conect só tinha fontes de compra. O SINAPI é publicado pela CAIXA
--   como arquivo mensal (XLSX dentro de ZIP), por competência, com as 27 UFs
--   e três regimes de encargos; não há API.
--
-- O QUE FAZ
--   * `precos_sinapi_versoes`   — cada arquivo mensal importado: competência
--     (AAAA-MM), SHA-256, endereço, data de emissão, UFs, contagens, estado
--     (importando, publicado, recusado) e qual é a versão VIGENTE da
--     competência. Retificação da CAIXA é outro arquivo, outro SHA: versão
--     nova da mesma competência;
--   * `precos_sinapi_registros` — uma referência por linha: competência, UF,
--     tipo (insumo ou composição), regime (sem desoneração, com desoneração,
--     sem encargos), código, descrição, unidade, valor, origem do preço
--     (insumo: C/CR) ou %AS (composição), e a aba e a linha da planilha
--     oficial de onde ela saiu;
--   * `precos_sinapi_buscar(...)` — por código ou por termos da descrição,
--     só do que está vigente, na competência pedida ou na mais recente.
--
-- DECISÕES
--   * CATEGORIA PRÓPRIA: estas tabelas não alimentam a cesta da pesquisa de
--     preços. O valor é "custo referencial" de engenharia, não preço de
--     compra; quem consulta é a rota `/precos/referencias/sinapi`;
--   * SEM `tenant_id`: dado público oficial, igual para todo município;
--   * a chave da linha é a identidade da referência — competência, tipo,
--     código, UF e regime —, a mesma em qualquer versão do arquivo;
--   * valor sempre > 0: preço em branco (sem coleta mínima) e custo zerado
--     (composição com item sem custo) são recusados no importador e o banco
--     recusa de novo (check);
--   * PUBLICAÇÃO POR VERSÃO: linha nova nasce `vigente = false` e só aparece
--     quando o importador publica a versão inteira; linha que saiu do arquivo
--     novo deixa de ser vigente, não é apagada;
--   * quem LÊ: `authenticated`, só as linhas vigentes dos registros; `anon`
--     não lê nada; as versões são da credencial de servidor;
--   * quem ESCREVE: só a credencial de servidor (o importador). Sem DELETE,
--     TRUNCATE, REFERENCES nem TRIGGER, nem para ela;
--   * a busca roda como quem chama (`security invoker`), `search_path` vazio,
--     com o mesmo teto de custo da 0042 e da 0044 (24 termos de até 60
--     caracteres, 200 linhas);
--   * a tabela NÃO decide se a consulta está ligada: é a flag
--     `referencia_custos_sinapi` (`governanca.FLAG_REFERENCIA_SINAPI`).
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * não importa nada: índice vazio até o importador rodar;
--   * só o que a CAIXA publica no XLSX de referência (insumos e custos de
--     composições). Composição analítica, famílias e manutenções ficam fora;
--   * o piloto é o Pará: o importador grava só as UFs pedidas;
--   * não aplica BDI nem decide o regime de desoneração da obra — são
--     escolhas do orçamentista, registradas no processo.

create table if not exists public.precos_sinapi_versoes (
  competencia text not null check (competencia ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  estado text not null default 'importando' check (estado in
    ('importando', 'publicado', 'recusado')),
  vigente boolean not null default false,
  url text not null check (url like 'https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/%'),
  data_emissao date,
  ufs text[] not null default '{}',
  linhas integer not null default 0,
  validas integer not null default 0,
  recusadas jsonb not null default '{}'::jsonb,
  motivo text not null default '',
  versao_parser text not null default '',
  publicado_em timestamptz,
  criado_em timestamptz not null default now(),
  primary key (competencia, sha256),
  check (not vigente or estado = 'publicado')
);

-- uma versão vigente por competência, no máximo
create unique index if not exists precos_sinapi_versoes_vigente_idx
  on public.precos_sinapi_versoes (competencia) where vigente;

create table if not exists public.precos_sinapi_registros (
  registro_id text primary key,
  competencia text not null,
  arquivo_sha256 text not null,
  vigente boolean not null default false,
  tipo text not null check (tipo in ('insumo', 'composicao')),
  regime text not null check (regime in
    ('sem_desoneracao', 'com_desoneracao', 'sem_encargos')),
  codigo text not null check (codigo ~ '^[0-9]{1,9}$'),
  descricao text not null,
  descricao_busca text not null,
  unidade text,
  uf char(2) not null,
  valor numeric(22, 6) not null check (valor > 0),
  classificacao text,
  origem_preco text check (origem_preco is null or origem_preco in ('C', 'CR')),
  percentual_sp numeric(9, 6),
  aba text not null check (aba in ('ISD', 'ICD', 'ISE', 'CSD', 'CCD', 'CSE')),
  linha_planilha integer not null check (linha_planilha > 0),
  url_arquivo text not null check (url_arquivo like 'https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/%'),
  hash_linha text not null,
  versao_parser text not null,
  importado_em timestamptz not null default now(),
  busca tsvector generated always as
    (to_tsvector('portuguese'::regconfig, descricao_busca)) stored,
  foreign key (competencia, arquivo_sha256)
    references public.precos_sinapi_versoes (competencia, sha256)
);

create index if not exists precos_sinapi_registros_busca_idx
  on public.precos_sinapi_registros using gin (busca) where vigente;
create index if not exists precos_sinapi_registros_codigo_idx
  on public.precos_sinapi_registros (codigo, uf, competencia) where vigente;
create index if not exists precos_sinapi_registros_versao_idx
  on public.precos_sinapi_registros (competencia, arquivo_sha256);

alter table public.precos_sinapi_versoes   enable row level security;
alter table public.precos_sinapi_registros enable row level security;

revoke all on public.precos_sinapi_versoes   from anon, authenticated, public;
revoke all on public.precos_sinapi_registros from anon, authenticated, public;

grant select, insert, update on public.precos_sinapi_versoes   to service_role;
grant select, insert, update on public.precos_sinapi_registros to service_role;
revoke delete, truncate, references, trigger on public.precos_sinapi_versoes   from service_role;
revoke delete, truncate, references, trigger on public.precos_sinapi_registros from service_role;

grant select on public.precos_sinapi_registros to authenticated;
drop policy if exists "precos_sinapi_registros_leitura" on public.precos_sinapi_registros;
create policy "precos_sinapi_registros_leitura" on public.precos_sinapi_registros
  for select to authenticated using (vigente);

create or replace function public.precos_sinapi_buscar(
  p_termos text[],
  p_codigo text default null,
  p_uf text default null,
  p_competencia text default null,
  p_regime text default null,
  p_tipo text default null,
  p_limite integer default 50)
returns setof public.precos_sinapi_registros
language sql
stable
security invoker
set search_path = ''
as $$
  with consulta as (
    -- mesmo teto de custo da 0042/0044: 24 termos, 60 caracteres cada. Sem
    -- termo a consulta é vazia e não casa com nada.
    select websearch_to_tsquery('portuguese'::regconfig,
             coalesce((select string_agg(left(t, 60), ' or ')
                         from unnest(coalesce(p_termos, '{}'::text[]))
                              with ordinality as u(t, n)
                        where n <= 24), '')) as q
  ),
  -- sem competência pedida: a mais recente com referência vigente na UF
  alvo as (
    select coalesce(nullif(p_competencia, ''),
                    (select max(r.competencia)
                       from public.precos_sinapi_registros r
                      where r.vigente
                        and (p_uf is null or r.uf = upper(p_uf)))) as competencia
  )
  select r.*
    from public.precos_sinapi_registros r, consulta c, alvo a
   where r.vigente
     and r.competencia = a.competencia
     and case when nullif(p_codigo, '') is not null
              then r.codigo = p_codigo
              else r.busca @@ c.q end
     and (p_uf is null or r.uf = upper(p_uf))
     and (nullif(p_regime, '') is null or r.regime = p_regime)
     and (nullif(p_tipo, '') is null or r.tipo = p_tipo)
   order by case when nullif(p_codigo, '') is not null then 0
                 else ts_rank(r.busca, c.q) end desc,
            r.tipo, r.codigo, r.regime
   limit least(greatest(coalesce(p_limite, 50), 1), 200)
$$;

comment on function public.precos_sinapi_buscar(text[], text, text, text, text, text, integer) is
  'Custos referenciais do SINAPI no índice, por código ou por termos (0046).';

revoke all on function public.precos_sinapi_buscar(text[], text, text, text, text, text, integer)
  from public, anon;
grant execute on function public.precos_sinapi_buscar(text[], text, text, text, text, text, integer)
  to authenticated;
grant execute on function public.precos_sinapi_buscar(text[], text, text, text, text, text, integer)
  to service_role;

notify pgrst, 'reload schema';

do $$
declare
  faltou text := '';
  tabela text;
  funcao constant regprocedure :=
    'public.precos_sinapi_buscar(text[], text, text, text, text, text, integer)'::regprocedure;
begin
  foreach tabela in array array['precos_sinapi_versoes', 'precos_sinapi_registros'] loop
    if not (select relrowsecurity from pg_class
             where oid = ('public.' || tabela)::regclass) then
      faltou := faltou || ' rls_desligado:' || tabela;
    end if;
    if has_any_column_privilege('anon', 'public.' || tabela,
                                'select, insert, update, references') then
      faltou := faltou || ' anon_alcanca:' || tabela;
    end if;
    if has_table_privilege('anon', 'public.' || tabela, 'delete, truncate') then
      faltou := faltou || ' anon_apaga:' || tabela;
    end if;
    if has_any_column_privilege('authenticated', 'public.' || tabela,
                                'insert, update, references') then
      faltou := faltou || ' authenticated_escreve:' || tabela;
    end if;
    if has_table_privilege('authenticated', 'public.' || tabela,
                           'delete, truncate') then
      faltou := faltou || ' authenticated_apaga:' || tabela;
    end if;
    if has_table_privilege('service_role', 'public.' || tabela,
                           'delete, truncate') then
      faltou := faltou || ' service_role_apaga:' || tabela;
    end if;
    -- REFERENCES por coluna não aparece em `has_table_privilege`
    if has_table_privilege('service_role', 'public.' || tabela, 'trigger')
       or has_any_column_privilege('service_role', 'public.' || tabela,
                                   'references') then
      faltou := faltou || ' service_role_gatilho_ou_fk:' || tabela;
    end if;
    -- fora o dono, só `service_role` e `authenticated` podem aparecer no ACL
    -- da tabela ou de qualquer coluna (PUBLIC é o grantee 0 e também cai)
    if exists (
         select 1 from pg_class c,
                aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
          where c.oid = ('public.' || tabela)::regclass
            and a.grantee not in (c.relowner, 'service_role'::regrole::oid,
                                  'authenticated'::regrole::oid))
       or exists (
         select 1 from pg_attribute at, pg_class c, aclexplode(at.attacl) a
          where at.attrelid = ('public.' || tabela)::regclass
            and c.oid = at.attrelid and at.attacl is not null
            and a.grantee not in (c.relowner, 'service_role'::regrole::oid,
                                  'authenticated'::regrole::oid)) then
      faltou := faltou || ' grant_a_papel_inesperado:' || tabela;
    end if;
    -- a migração não cria gatilho; um que apareça mudaria o que é gravado
    if exists (select 1 from pg_trigger
                where tgrelid = ('public.' || tabela)::regclass
                  and not tgisinternal) then
      faltou := faltou || ' gatilho:' || tabela;
    end if;
    -- com lista, `has_table_privilege` responde "algum": cada um é conferido
    if not (has_table_privilege('service_role', 'public.' || tabela, 'select')
            and has_table_privilege('service_role', 'public.' || tabela, 'insert')
            and has_table_privilege('service_role', 'public.' || tabela, 'update')) then
      faltou := faltou || ' service_role_sem_escrita:' || tabela;
    end if;
  end loop;

  if has_any_column_privilege('authenticated', 'public.precos_sinapi_versoes', 'select') then
    faltou := faltou || ' authenticated_le_controle_da_importacao';
  end if;
  if not has_table_privilege('authenticated', 'public.precos_sinapi_registros', 'select') then
    faltou := faltou || ' authenticated_sem_leitura';
  end if;
  if (select count(*) from pg_policies
       where schemaname = 'public' and tablename like 'precos\_sinapi\_%' escape '\') <> 1
     or not exists (
       select 1 from pg_policies
        where schemaname = 'public' and tablename = 'precos_sinapi_registros'
          and policyname = 'precos_sinapi_registros_leitura'
          and cmd = 'SELECT' and roles = '{authenticated}'
          and qual = 'vigente') then
    faltou := faltou || ' politica_fora_do_previsto';
  end if;

  if (select prosecdef from pg_proc where oid = funcao) then
    faltou := faltou || ' security_definer';
  end if;
  if (select provolatile from pg_proc where oid = funcao) <> 's' then
    faltou := faltou || ' nao_estavel';
  end if;
  if not coalesce((select proconfig from pg_proc where oid = funcao)
                  @> array['search_path=""'], false) then
    faltou := faltou || ' sem_search_path_vazio';
  end if;
  if not has_function_privilege('authenticated', funcao, 'execute') then
    faltou := faltou || ' authenticated_sem_execute';
  end if;
  if has_function_privilege('anon', funcao, 'execute') then
    faltou := faltou || ' anon_executa';
  end if;

  if faltou <> '' then
    raise exception 'A 0046 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
