-- ## 0049 — Referência de custos SICRO (DNIT), em consulta própria
-- ## ESTADO: NÃO APLICADA EM PRODUÇÃO. Aplicável; aguarda o ensaio nos dois
-- ##   níveis (o do CI roda em `tests/test_migracao_0049.py`), a revisão do
-- ##   `revisor-de-banco-e-seguranca` e a autorização do dono.
-- ##   Numerada depois da 0047 (SEOP-PA, #229) e da 0048 (SIGTAP, #230), que
-- ##   não dependem dela nem ela delas: só a ordem do ensaio.
--
-- O PROBLEMA (24/11/2026)
--   Obra de infraestrutura de transportes (estrada, ponte, drenagem, obra
--   hidroviária) se orça pelo SICRO, o sistema de custos do DNIT — mesmo
--   fundamento do SINAPI (Lei 14.133, art. 23, § 2º, I, e § 3º para sistema
--   adotado pelo ente). O DNIT publica, por UF e trimestre, UM 7-Zip com os
--   relatórios em PDF e XLSX; não há API.
--
-- O QUE FAZ
--   * `precos_sicro_versoes`   — cada 7-Zip importado: competência, UF,
--     SHA-256, nome e endereço do arquivo, contagens, recusas, estado
--     (importando, publicado, recusado) e qual é a VIGENTE da (competência,
--     UF). A edição "revisado" é outro arquivo, outro SHA: versão nova;
--   * `precos_sicro_registros` — uma referência por linha dos relatórios
--     sintéticos: tipo (composição, material, mão de obra, equipamento),
--     regime de encargos, código, descrição, unidade, custo (equipamento:
--     produtivo, e o improdutivo ao lado), a sigla da origem do preço na UF,
--     a planilha de dentro do 7-Zip e a linha;
--   * `precos_sicro_buscar(...)` — por código ou termos, só do vigente, na
--     competência pedida ou na mais recente da UF.
--
-- DECISÕES
--   * CATEGORIA PRÓPRIA, como a 0046: fora da cesta, sem `tenant_id`, leitura
--     só do vigente por `authenticated`, escrita só do servidor, sem DELETE/
--     TRUNCATE/REFERENCES/TRIGGER nem para ele, busca `security invoker` com
--     o mesmo teto (24 termos × 60 caracteres, 200 linhas);
--   * o regime é amarrado ao tipo: composição só SEM desoneração (é o que o
--     DNIT publica — o analítico precifica a mão de obra sem desoneração),
--     material sem encargos (`nao_se_aplica`), mão de obra e equipamento nos
--     dois. A busca por um regime traz também os materiais;
--   * valor sempre > 0: "-" (sem preço na UF) e "preço referencial zerado"
--     são recusados no importador e o banco recusa de novo;
--   * a chave da linha (competência, UF, tipo, regime, código) é a mesma em
--     qualquer versão; o `registro_id` inclui o SHA, então versões convivem
--     e a publicação troca qual é vigente;
--   * a consulta é aberta pela flag `referencia_custos_sicro`, desligada.
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * não importa nada: índice vazio até o importador rodar (piloto: Pará);
--   * só os relatórios SINTÉTICOS. Analítico de composições, encargos,
--     produção de equipes e DMT ficam no 7-Zip oficial, linkado em cada linha;
--   * não aplica BDI nem escolhe o regime da obra: escolhas do orçamentista;
--   * a publicação de versão nova são quatro UPDATEs pela API REST, não uma
--     transação (como no SINAPI): entre o 1º e o 2º, a versão velha e a nova
--     aparecem juntas; se o importador cair ali, a nova fica em `importando`
--     e reimportar o mesmo arquivo refaz a publicação inteira.

create table if not exists public.precos_sicro_versoes (
  competencia text not null check (competencia ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  uf char(2) not null check (uf ~ '^[A-Z]{2}$'),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  estado text not null default 'importando' check (estado in
    ('importando', 'publicado', 'recusado')),
  vigente boolean not null default false,
  arquivo text not null check (arquivo ~ '^[a-z]{2}-[0-9]{2}-[0-9]{4}([-_][a-z0-9]+)*\.7z$'),
  url text not null check (url like 'https://www.gov.br/dnit/pt-br/assuntos/planejamento-e-pesquisa/custos-referenciais/sistemas-de-custos/sicro/relatorios/relatorios-sicro/%'
                           and url not like '%..%' and url not like '%?%'
                           and url not like '%\%%'),
  linhas integer not null default 0,
  validas integer not null default 0,
  recusas jsonb not null default '{}'::jsonb,
  recusadas jsonb not null default '[]'::jsonb,
  motivo text not null default '',
  versao_parser text not null default '',
  publicado_em timestamptz,
  criado_em timestamptz not null default now(),
  primary key (competencia, uf, sha256),
  check (not vigente or estado = 'publicado')
);

-- uma versão vigente por (competência, UF), no máximo
create unique index if not exists precos_sicro_versoes_vigente_idx
  on public.precos_sicro_versoes (competencia, uf) where vigente;

create table if not exists public.precos_sicro_registros (
  registro_id text primary key,
  chave_linha text not null,
  competencia text not null,
  uf char(2) not null,
  arquivo_sha256 text not null,
  vigente boolean not null default false,
  tipo text not null check (tipo in ('composicao', 'material', 'mao_de_obra', 'equipamento')),
  regime text not null check (regime in ('sem_desoneracao', 'com_desoneracao', 'nao_se_aplica')),
  codigo text not null,
  descricao text not null,
  descricao_busca text not null,
  unidade text,
  valor numeric(16, 4) not null check (valor > 0),
  valor_improdutivo numeric(16, 4) check (valor_improdutivo is null or valor_improdutivo >= 0),
  origem_preco text check (origem_preco is null or origem_preco ~ '^[A-Z]{1,4}$'),
  planilha text not null check (planilha ~ '^[A-Z]{2} [0-9]{2}-[0-9]{4} Relatório Sintético de .+\.xlsx$'),
  linha_planilha integer not null check (linha_planilha > 1),
  url_arquivo text not null check (url_arquivo like 'https://www.gov.br/dnit/pt-br/assuntos/planejamento-e-pesquisa/custos-referenciais/sistemas-de-custos/sicro/relatorios/relatorios-sicro/%'
                                   and url_arquivo not like '%..%' and url_arquivo not like '%?%'
                                   and url_arquivo not like '%\%%'),
  arquivo text not null check (arquivo ~ '^[a-z]{2}-[0-9]{2}-[0-9]{4}([-_][a-z0-9]+)*\.7z$'),
  hash_linha text not null,
  versao_parser text not null,
  importado_em timestamptz not null default now(),
  busca tsvector generated always as
    (to_tsvector('portuguese'::regconfig, descricao_busca)) stored,
  unique (arquivo_sha256, chave_linha),
  -- o código tem a forma do tipo; o regime, a que o DNIT publica para ele
  check (case tipo
           when 'composicao'  then codigo ~ '^[0-9]{7}$' and regime = 'sem_desoneracao'
           when 'material'    then codigo ~ '^M[0-9]{4}$' and regime = 'nao_se_aplica'
           when 'mao_de_obra' then codigo ~ '^P[0-9]{4}$' and regime <> 'nao_se_aplica'
           else codigo ~ '^[EA][0-9]{4}$' and regime <> 'nao_se_aplica'
         end),
  check (valor_improdutivo is null or tipo = 'equipamento'),
  foreign key (competencia, uf, arquivo_sha256)
    references public.precos_sicro_versoes (competencia, uf, sha256)
);

create index if not exists precos_sicro_registros_busca_idx
  on public.precos_sicro_registros using gin (busca) where vigente;
create index if not exists precos_sicro_registros_codigo_idx
  on public.precos_sicro_registros (codigo, uf, competencia) where vigente;
create index if not exists precos_sicro_registros_versao_idx
  on public.precos_sicro_registros (competencia, uf, arquivo_sha256);

alter table public.precos_sicro_versoes   enable row level security;
alter table public.precos_sicro_registros enable row level security;

revoke all on public.precos_sicro_versoes   from anon, authenticated, public;
revoke all on public.precos_sicro_registros from anon, authenticated, public;

grant select, insert, update on public.precos_sicro_versoes   to service_role;
grant select, insert, update on public.precos_sicro_registros to service_role;
revoke delete, truncate, references, trigger on public.precos_sicro_versoes   from service_role;
revoke delete, truncate, references, trigger on public.precos_sicro_registros from service_role;

grant select on public.precos_sicro_registros to authenticated;
drop policy if exists "precos_sicro_registros_leitura" on public.precos_sicro_registros;
create policy "precos_sicro_registros_leitura" on public.precos_sicro_registros
  for select to authenticated using (vigente);

create or replace function public.precos_sicro_buscar(
  p_termos text[],
  p_codigo text default null,
  p_uf text default null,
  p_competencia text default null,
  p_regime text default null,
  p_tipo text default null,
  p_limite integer default 50)
returns setof public.precos_sicro_registros
language sql
stable
security invoker
set search_path = ''
as $$
  with consulta as (
    -- mesmo teto de custo da 0042/0044/0046: 24 termos, 60 caracteres cada
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
                       from public.precos_sicro_registros r
                      where r.vigente
                        and (p_uf is null or r.uf = upper(p_uf)))) as competencia
  )
  select r.*
    from public.precos_sicro_registros r, consulta c, alvo a
   where r.vigente
     and r.competencia = a.competencia
     and case when nullif(p_codigo, '') is not null
              then r.codigo = upper(p_codigo)
              else r.busca @@ c.q end
     and (p_uf is null or r.uf = upper(p_uf))
     -- material não tem encargos: aparece em qualquer regime pedido
     and (nullif(p_regime, '') is null or r.regime in (p_regime, 'nao_se_aplica'))
     and (nullif(p_tipo, '') is null or r.tipo = p_tipo)
   order by case when nullif(p_codigo, '') is not null then 0
                 else ts_rank(r.busca, c.q) end desc,
            r.tipo, r.codigo
   limit least(greatest(coalesce(p_limite, 50), 1), 200)
$$;

comment on function public.precos_sicro_buscar(text[], text, text, text, text, text, integer) is
  'Custo referencial do SICRO no índice, por código ou termos (0049).';

revoke all on function public.precos_sicro_buscar(text[], text, text, text, text, text, integer)
  from public, anon;
grant execute on function public.precos_sicro_buscar(text[], text, text, text, text, text, integer)
  to authenticated;
grant execute on function public.precos_sicro_buscar(text[], text, text, text, text, text, integer)
  to service_role;

notify pgrst, 'reload schema';

do $$
declare
  faltou text := '';
  tabela text;
  funcao constant regprocedure :=
    'public.precos_sicro_buscar(text[], text, text, text, text, text, integer)'::regprocedure;
begin
  foreach tabela in array array['precos_sicro_versoes', 'precos_sicro_registros'] loop
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

  if has_any_column_privilege('authenticated', 'public.precos_sicro_versoes', 'select') then
    faltou := faltou || ' authenticated_le_controle_da_importacao';
  end if;
  if not has_table_privilege('authenticated', 'public.precos_sicro_registros', 'select') then
    faltou := faltou || ' authenticated_sem_leitura';
  end if;
  if (select count(*) from pg_policies
       where schemaname = 'public' and tablename like 'precos\_sicro\_%' escape '\') <> 1
     or not exists (
       select 1 from pg_policies
        where schemaname = 'public' and tablename = 'precos_sicro_registros'
          and policyname = 'precos_sicro_registros_leitura'
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
    raise exception 'A 0049 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
