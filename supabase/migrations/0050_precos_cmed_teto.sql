-- ## 0050 — Teto CMED de medicamentos (Anvisa), em consulta própria
-- ## ESTADO: NÃO APLICADA EM PRODUÇÃO. Aplicável; aguarda o ensaio nos dois
-- ##   níveis (o do CI roda em `tests/test_migracao_0050.py`), a revisão do
-- ##   `revisor-de-banco-e-seguranca` e a autorização do dono.
-- ##   Numerada depois da 0047 (SEOP-PA, #229), 0048 (SIGTAP, #230) e 0049
-- ##   (SICRO, #231), que não dependem dela nem ela delas.
--
-- O PROBLEMA (24/11/2026)
--   Medicamento tem preço máximo regulado: a CMED fixa o Preço Fábrica (PF)
--   e o Preço Máximo de Venda ao Governo (PMVG) de cada apresentação, por
--   alíquota de ICMS. A compra pública não pode pagar acima do teto. O BPS dá
--   o preço PRATICADO; faltava o TETO, em categoria separada. A CMED publica
--   a lista como XLSX na página de preços; não há API.
--
-- O QUE FAZ
--   * `precos_cmed_versoes`   — cada lista PMVG importada: SHA-256, data e
--     hora de publicação (do cabeçalho), nome e endereço, contagens, estado,
--     e qual é a VIGENTE — uma só no total: a lista nova substitui a antiga;
--   * `precos_cmed_registros` — uma apresentação: GGREM (15 dígitos), registro,
--     EANs, substância, laboratório, produto, apresentação, o PF e o PMVG nas
--     26 colunas (sem impostos, ICMS 0% e 12% a 23%, com e sem ALC), CAP,
--     CONFAZ 87, ICMS 0%, restrição hospitalar, análise recursal, tarja e a
--     linha da planilha;
--   * `precos_cmed_buscar(...)` — por código (GGREM, registro ou EAN) ou por
--     termos, só da lista vigente.
--
-- DECISÕES
--   * CATEGORIA PRÓPRIA, como a 0046: fora da cesta, sem `tenant_id`, leitura
--     só do vigente por `authenticated`, escrita só do servidor, sem DELETE/
--     TRUNCATE/REFERENCES/TRIGGER nem para ele, busca `security invoker` com
--     o mesmo teto (24 termos × 60 caracteres, 200 linhas);
--   * o banco guarda as DUAS colunas (PF e PMVG); quem decide qual é o teto
--     é a regra do cabeçalho da CMED, no código (`cmed.TetoCmed`): CAP "Sim"
--     → PMVG; sem CAP → PF. A coluna PMVG vem preenchida para todos;
--   * PF e PMVG em `jsonb` com as 26 chaves exigidas por `check` (`?&`);
--   * a consulta é aberta pela flag `referencia_teto_cmed`, desligada.
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * não importa nada: índice vazio até o importador rodar;
--   * não escolhe a alíquota de ICMS do estado de destino nem aplica a
--     isenção do CONFAZ 87/ICMS 0%: o gestor escolhe, a tela mostra as duas;
--   * RETENÇÃO: cada lista (~26,7 mil apresentações) fica gravada, e a CMED
--     republica com frequência; como ninguém apaga (nem o servidor), o
--     espaço cresce a cada importação — importar quando a lista muda, não
--     por agenda cega;
--   * a publicação de versão nova são quatro UPDATEs pela API REST, não uma
--     transação: entre o 1º e o 2º, a lista velha e a nova aparecem juntas;
--     se o importador cair ali, reimportar o mesmo arquivo refaz tudo. Se
--     cair entre o 3º e o 4º, fica SEM lista vigente (a consulta volta vazia)
--     e a próxima importação não tem com quem comparar data nem tamanho:
--     reimportar o MESMO arquivo antes de qualquer outro.

create table if not exists public.precos_cmed_versoes (
  sha256 text primary key check (sha256 ~ '^[0-9a-f]{64}$'),
  estado text not null default 'importando' check (estado in
    ('importando', 'publicado', 'recusado')),
  vigente boolean not null default false,
  publicada_em timestamptz,
  arquivo text not null check (arquivo ~* '^lista_pmvg_[0-9]{8}_[0-9]{9}\.xlsx$'),
  url text not null check (url like 'https://www.gov.br/anvisa/pt-br/assuntos/medicamentos/cmed/precos/arquivos/%'
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
  check (not vigente or (estado = 'publicado' and publicada_em is not null))
);

-- uma lista vigente no total, no máximo
create unique index if not exists precos_cmed_versoes_vigente_idx
  on public.precos_cmed_versoes ((true)) where vigente;

create table if not exists public.precos_cmed_registros (
  registro_id text primary key,
  chave_linha text not null,
  publicada_em timestamptz not null,
  arquivo_sha256 text not null references public.precos_cmed_versoes (sha256),
  vigente boolean not null default false,
  ggrem text not null check (ggrem ~ '^[0-9]{15}$'),
  registro text check (registro is null or registro ~ '^[0-9]{9,13}$'),
  eans text[] not null default '{}',
  substancia text not null,
  cnpj text,
  laboratorio text not null,
  produto text not null,
  apresentacao text not null,
  classe_terapeutica text,
  tipo_produto text,
  regime_preco text,
  pf jsonb not null,
  pmvg jsonb not null,
  restricao_hospitalar boolean not null,
  cap boolean not null,
  confaz87 boolean not null,
  icms_0 boolean not null,
  analise_recursal text,
  lista_credito text,
  comercializado boolean not null,
  tarja text,
  linha_planilha integer not null check (linha_planilha > 1),
  descricao_busca text not null,
  url_arquivo text not null check (url_arquivo like 'https://www.gov.br/anvisa/pt-br/assuntos/medicamentos/cmed/precos/arquivos/%'
                                   and url_arquivo not like '%..%' and url_arquivo not like '%?%'
                                   and url_arquivo not like '%\%%'),
  arquivo text not null check (arquivo ~* '^lista_pmvg_[0-9]{8}_[0-9]{9}\.xlsx$'),
  hash_linha text not null,
  versao_parser text not null,
  importado_em timestamptz not null default now(),
  busca tsvector generated always as
    (to_tsvector('portuguese'::regconfig, descricao_busca)) stored,
  unique (arquivo_sha256, ggrem),
  -- as 26 colunas de valor da lista, em PF e em PMVG
  check (jsonb_typeof(pf) = 'object' and pf ?& array[
    'sem_impostos', '0', '12', '12_alc', '17', '17_alc', '17.5', '17.5_alc', '18',
    '18_alc', '19', '19_alc', '19.5', '19.5_alc', '20', '20_alc', '20.5', '20.5_alc',
    '21', '21_alc', '22', '22_alc', '22.5', '22.5_alc', '23', '23_alc']),
  check (jsonb_typeof(pmvg) = 'object' and pmvg ?& array[
    'sem_impostos', '0', '12', '12_alc', '17', '17_alc', '17.5', '17.5_alc', '18',
    '18_alc', '19', '19_alc', '19.5', '19.5_alc', '20', '20_alc', '20.5', '20.5_alc',
    '21', '21_alc', '22', '22_alc', '22.5', '22.5_alc', '23', '23_alc'])
);

create index if not exists precos_cmed_registros_busca_idx
  on public.precos_cmed_registros using gin (busca) where vigente;
create index if not exists precos_cmed_registros_ggrem_idx
  on public.precos_cmed_registros (ggrem) where vigente;
create index if not exists precos_cmed_registros_registro_idx
  on public.precos_cmed_registros (registro) where vigente;
create index if not exists precos_cmed_registros_eans_idx
  on public.precos_cmed_registros using gin (eans) where vigente;
create index if not exists precos_cmed_registros_versao_idx
  on public.precos_cmed_registros (arquivo_sha256);

alter table public.precos_cmed_versoes   enable row level security;
alter table public.precos_cmed_registros enable row level security;

revoke all on public.precos_cmed_versoes   from anon, authenticated, public;
revoke all on public.precos_cmed_registros from anon, authenticated, public;

grant select, insert, update on public.precos_cmed_versoes   to service_role;
grant select, insert, update on public.precos_cmed_registros to service_role;
revoke delete, truncate, references, trigger on public.precos_cmed_versoes   from service_role;
revoke delete, truncate, references, trigger on public.precos_cmed_registros from service_role;

grant select on public.precos_cmed_registros to authenticated;
drop policy if exists "precos_cmed_registros_leitura" on public.precos_cmed_registros;
create policy "precos_cmed_registros_leitura" on public.precos_cmed_registros
  for select to authenticated using (vigente);

create or replace function public.precos_cmed_buscar(
  p_termos text[],
  p_codigo text default null,
  p_limite integer default 50)
returns setof public.precos_cmed_registros
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
  )
  select r.*
    from public.precos_cmed_registros r, consulta c
   where r.vigente
     and case when nullif(p_codigo, '') is not null
              then r.ggrem = p_codigo or r.registro = p_codigo
                   or r.eans @> array[p_codigo]
              else r.busca @@ c.q end
   order by case when nullif(p_codigo, '') is not null then 0
                 else ts_rank(r.busca, c.q) end desc,
            r.substancia, r.produto, r.ggrem
   limit least(greatest(coalesce(p_limite, 50), 1), 200)
$$;

comment on function public.precos_cmed_buscar(text[], text, integer) is
  'Teto CMED (PF e PMVG) da lista vigente, por código ou termos (0050).';

revoke all on function public.precos_cmed_buscar(text[], text, integer) from public, anon;
grant execute on function public.precos_cmed_buscar(text[], text, integer) to authenticated;
grant execute on function public.precos_cmed_buscar(text[], text, integer) to service_role;

notify pgrst, 'reload schema';

do $$
declare
  faltou text := '';
  tabela text;
  funcao constant regprocedure :=
    'public.precos_cmed_buscar(text[], text, integer)'::regprocedure;
begin
  foreach tabela in array array['precos_cmed_versoes', 'precos_cmed_registros'] loop
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

  if has_any_column_privilege('authenticated', 'public.precos_cmed_versoes', 'select') then
    faltou := faltou || ' authenticated_le_controle_da_importacao';
  end if;
  if not has_table_privilege('authenticated', 'public.precos_cmed_registros', 'select') then
    faltou := faltou || ' authenticated_sem_leitura';
  end if;
  if (select count(*) from pg_policies
       where schemaname = 'public' and tablename like 'precos\_cmed\_%' escape '\') <> 1
     or not exists (
       select 1 from pg_policies
        where schemaname = 'public' and tablename = 'precos_cmed_registros'
          and policyname = 'precos_cmed_registros_leitura'
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
    raise exception 'A 0050 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
