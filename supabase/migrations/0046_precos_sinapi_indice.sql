-- ## 0046 — Índice do SINAPI (CAIXA/IBGE): custos de referência de engenharia
-- ## ESTADO: NÃO APLICADA EM PRODUÇÃO. Aplicável; aguarda o ensaio nos dois
-- ##   níveis (o do CI roda em `tests/test_migracao_0046.py`), a revisão do
-- ##   `revisor-de-banco-e-seguranca` e a autorização do dono.
--
-- O PROBLEMA (23/11/2026)
--   Obra e serviço de engenharia têm referência própria (Lei 14.133, art. 23,
--   § 2º, I; Decreto 7.983/2013): o SINAPI. A CAIXA publica UM arquivo mensal
--   nacional (`SINAPI-AAAA-MM-formato-xlsx.zip`, ~16 MB) com seis abas de
--   preço e uma coluna por UF. Ninguém consulta isso no clique: o arquivo é
--   importado fora dele, por competência e UF, e a tela lê o índice.
--
-- O QUE FAZ
--   * `precos_sinapi_versoes`   — cada arquivo oficial importado por
--     competência e UF: SHA-256, endereço, emissão, encargos sociais da UF,
--     contagens e recusas por motivo, estado (importando, publicado,
--     recusado) e qual é a versão VIGENTE;
--   * `precos_sinapi_registros` — uma linha de aba para uma UF: tipo
--     (insumo ou composição), regime (sem desoneração, com desoneração, sem
--     encargos), código, descrição, unidade, valor, origem do preço (C/CR)
--     ou %AS, a aba e a LINHA da planilha oficial, e o arquivo de onde veio;
--   * `precos_sinapi_buscar(...)` — por código ou termos, só do vigente.
--
-- DECISÕES
--   * NÃO é preço de compra e não alimenta a cesta: a tabela é separada das
--     de preço (0042, 0044) e a consulta tem tela própria;
--   * SEM `tenant_id`: dado público de publicação oficial;
--   * VERSÃO = (competência, UF, SHA-256). A CAIXA retifica arquivos (já
--     publicou preços zerados e corrigiu depois): arquivo novo da mesma
--     competência é versão nova, com as próprias linhas; a anterior fica
--     guardada e só deixa de ser vigente quando a nova é publicada inteira.
--     A chave da linha (`chave_linha`) é a mesma nas duas versões;
--   * preço em branco ou zero NÃO é gravado (check `valor > 0`);
--   * quem LÊ: `authenticated`, só as linhas vigentes; as versões são do
--     servidor; `anon` não lê nada;
--   * quem ESCREVE: só a credencial de servidor (o importador). Sem DELETE,
--     TRUNCATE, REFERENCES nem TRIGGER, nem para ela;
--   * a busca roda como quem chama, `search_path` vazio, mesmo teto de custo
--     da 0042/0044. Sem competência pedida, vale a MAIS RECENTE vigente da UF;
--   * a tabela NÃO decide se a consulta está aberta: isso é
--     `fontes_externas.habilitada("sinapi")` (flag, mapeamento e licença).
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * não importa nada: índice vazio até o importador rodar;
--   * não aprova a licença de reúso — decisão do dono;
--   * não guarda o analítico das composições (coeficientes): só o custo
--     unitário publicado, que é o que a consulta mostra.

create table if not exists public.precos_sinapi_versoes (
  competencia text not null check (competencia ~ '^\d{4}-(0[1-9]|1[0-2])$'),
  uf char(2) not null check (uf ~ '^[A-Z]{2}$'),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  estado text not null default 'importando' check (estado in
    ('importando', 'publicado', 'recusado')),
  vigente boolean not null default false,
  url text not null check (url like 'https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/%'),
  last_modified text,
  emissao text not null default '',
  encargos jsonb not null default '{}'::jsonb,
  linhas integer not null default 0,
  validos integer not null default 0,
  recusas jsonb not null default '{}'::jsonb,
  motivo text not null default '',
  versao_parser text not null default '',
  publicado_em timestamptz,
  criado_em timestamptz not null default now(),
  primary key (competencia, uf, sha256),
  check (not vigente or estado = 'publicado')
);

-- uma versão vigente por competência e UF, no máximo
create unique index if not exists precos_sinapi_versoes_vigente_idx
  on public.precos_sinapi_versoes (competencia, uf) where vigente;

create table if not exists public.precos_sinapi_registros (
  registro_id text primary key,
  chave_linha text not null,
  competencia text not null,
  uf char(2) not null,
  arquivo_sha256 text not null,
  vigente boolean not null default false,
  tipo text not null check (tipo in ('insumo', 'composicao')),
  regime text not null check (regime in
    ('sem_desoneracao', 'com_desoneracao', 'sem_encargos')),
  codigo text not null check (codigo ~ '^\d+$'),
  descricao text not null,
  descricao_busca text not null,
  unidade text not null,
  valor numeric(22, 6) not null check (valor > 0),
  classificacao text,
  origem_preco text,
  percentual_sp numeric(12, 6),
  aba text not null check (aba in ('ISD', 'ICD', 'ISE', 'CSD', 'CCD', 'CSE')),
  linha_planilha integer not null check (linha_planilha >= 11),
  url_arquivo text not null check (url_arquivo like 'https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/%'),
  hash_linha text not null,
  versao_parser text not null,
  importado_em timestamptz not null default now(),
  busca tsvector generated always as
    (to_tsvector('portuguese'::regconfig, descricao_busca)) stored,
  unique (arquivo_sha256, chave_linha),
  foreign key (competencia, uf, arquivo_sha256)
    references public.precos_sinapi_versoes (competencia, uf, sha256)
);

create index if not exists precos_sinapi_registros_busca_idx
  on public.precos_sinapi_registros using gin (busca) where vigente;
create index if not exists precos_sinapi_registros_codigo_idx
  on public.precos_sinapi_registros (codigo, uf, competencia desc) where vigente;
create index if not exists precos_sinapi_registros_versao_idx
  on public.precos_sinapi_registros (competencia, uf, arquivo_sha256);

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
  p_uf text default 'PA',
  p_competencia text default null,
  p_tipo text default null,
  p_regime text default null,
  p_limite integer default 50)
returns setof public.precos_sinapi_registros
language sql
stable
security invoker
set search_path = ''
as $$
  with consulta as (
    -- mesmo teto de custo da 0042/0044: 24 termos, 60 caracteres cada
    select websearch_to_tsquery('portuguese'::regconfig,
             coalesce((select string_agg(left(t, 60), ' or ')
                         from unnest(coalesce(p_termos, '{}'::text[]))
                              with ordinality as u(t, n)
                        where n <= 24), '')) as q
  ), alvo as (
    -- sem competência pedida: a mais recente vigente da UF
    select coalesce(nullif(p_competencia, ''),
                    (select max(r.competencia)
                       from public.precos_sinapi_registros r
                      where r.vigente and r.uf = upper(coalesce(p_uf, 'PA'))))
           as competencia
  )
  select r.*
    from public.precos_sinapi_registros r, consulta c, alvo a
   where r.vigente
     and r.uf = upper(coalesce(p_uf, 'PA'))
     and r.competencia = a.competencia
     and (p_tipo is null or r.tipo = p_tipo)
     and (p_regime is null or r.regime = p_regime)
     -- com código, só o código: é a identidade do insumo/composição
     and case when nullif(p_codigo, '') is not null
              then r.codigo = p_codigo
              else r.busca @@ c.q end
   order by case when nullif(p_codigo, '') is not null then 0
                 else ts_rank(r.busca, c.q) end desc,
            r.tipo, r.codigo, r.regime
   limit least(greatest(coalesce(p_limite, 50), 1), 200)
$$;

comment on function public.precos_sinapi_buscar(text[], text, text, text, text, text, integer) is
  'Custos de referência do SINAPI no índice, por código ou termos (0046).';

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
    -- um a um: com lista, `has_table_privilege` responde "algum"
    if has_table_privilege('service_role', 'public.' || tabela, 'delete')
       or has_table_privilege('service_role', 'public.' || tabela, 'truncate') then
      faltou := faltou || ' service_role_apaga:' || tabela;
    end if;
    -- REFERENCES por coluna não aparece em `has_table_privilege`
    if has_table_privilege('service_role', 'public.' || tabela, 'trigger')
       or has_any_column_privilege('service_role', 'public.' || tabela,
                                   'references') then
      faltou := faltou || ' service_role_gatilho_ou_fk:' || tabela;
    end if;
    -- A conferência por papel NOMEADO não vê o papel que ninguém nomeou
    -- (reforço da revisão da 0044): fora o dono, só `service_role` e
    -- `authenticated` podem aparecer no ACL da tabela ou de qualquer coluna
    -- (PUBLIC é o grantee 0 e também cai).
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
