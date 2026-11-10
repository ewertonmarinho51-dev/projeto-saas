-- ## 0042 — Índice de resultados homologados do PNCP (piloto da busca por descrição)
-- ## ESTADO: NÃO APLICADA EM PRODUÇÃO. Aplicável; aguarda a revisão do
-- ##   `revisor-de-banco-e-seguranca` e a autorização do dono.
-- ## ENSAIO: CI (`tests/test_migracao_0042.py`, PostgreSQL) e projeto
-- ##   descartável `uslaxaxomjawydqtbwkb` em 10/11/2026 (registro
-- ##   `m0042_precos_pncp_indice`): conferência passou; com amostra REAL do
-- ##   índice paraense, `authenticated` buscou "gasolina comum" (2 vigentes,
-- ##   a invalidada fora), não escreveu nem leu o controle; `anon` sem execute.
--
-- O PROBLEMA (10/11/2026)
--   A busca de preços da prefeitura só tem UMA fonte de preço: o Compras.gov.
--   O PNCP entra em `fontes_padrao()` como evidência e devolve vazio, porque
--   a API dele não tem busca de item por descrição — só o caminho contratação
--   → itens → resultados. Medido em produção: 81 de 394 buscas automáticas em
--   21 dias terminaram sem nenhum resultado.
--
-- O QUE FAZ
--   Três tabelas que guardam, FORA do clique do usuário, o que um job
--   limitado e retomável (`scripts/indexar_pncp.py`, `src/precos/pncp_indice.py`)
--   lê dos canais oficiais do PNCP, e uma função de busca:
--   * `precos_pncp_cursores`     — onde a descoberta parou, por UF e modalidade;
--   * `precos_pncp_contratacoes` — cada contratação vista, o estado da coleta
--     e o item em que ela parou (ponto de retomada);
--   * `precos_pncp_resultados`   — um resultado HOMOLOGADO por linha: item,
--     unidade, quantidade, unitário, total, fornecedor (só CNPJ), plataforma de
--     origem e o registro bruto que permite refazer a conferência;
--   * `precos_pncp_buscar(...)`  — termos da descrição → linhas, por relevância.
--
-- DECISÕES
--   * SEM `tenant_id`: é dado PÚBLICO de portal oficial, igual para todo
--     município. O que é do município (cotação, cesta, decisão) continua em
--     `pesquisa_preco_*`, com RLS por tenant;
--   * quem LÊ: `authenticated`, e só `precos_pncp_resultados`. A política é
--     `using (true)` de propósito e só para esse papel — não há linha que um
--     usuário autenticado não possa ver; `anon` não lê nada;
--   * quem ESCREVE: só a credencial de servidor (o job de bancada). O worker
--     da API não escreve aqui: ele roda com o token do usuário;
--   * `DELETE` e `TRUNCATE` revogados inclusive de `service_role`: registro
--     coletado é substituído por versão nova (upsert), não apagado;
--   * a busca roda como quem chama (`security invoker`), com `search_path`
--     vazio. O texto de busca vem pronto do coletor (sem acento, minúsculas),
--     para não depender da extensão `unaccent`;
--   * correção ou cancelamento publicado DEPOIS da coleta não apaga nada:
--     a revisita marca a linha antiga `vigente = false`, com motivo, e a
--     busca deixa de devolvê-la (o histórico do que foi lido fica);
--   * a tabela NÃO decide se a fonte está ligada: isso é a flag
--     `price_source_pncp_indice` (`governanca.FLAG_PNCP_INDICE`), desligada.
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * não liga a fonte nem coleta nada: tabela vazia até o job rodar;
--   * não agenda o job (decisão de operação);
--   * não limita o crescimento: o piloto é o Pará; ampliar para outras UFs
--     pede medir tamanho e tempo de busca antes.

create table if not exists public.precos_pncp_cursores (
  uf char(2) not null,
  modalidade_id integer not null,
  data_inicial date not null,
  data_final date not null,
  proxima_pagina integer not null default 1 check (proxima_pagina >= 1),
  concluido boolean not null default false,
  atualizado_em timestamptz not null default now(),
  primary key (uf, modalidade_id)
);

create table if not exists public.precos_pncp_contratacoes (
  numero_controle text primary key,
  uf char(2),
  modalidade_id integer,
  plataforma text,
  atualizacao_global text,
  tem_homologacao boolean not null default false,
  estado text not null default 'pendente' check (estado in
    ('pendente', 'coletada', 'sem_resultado', 'fora_do_piloto', 'falha')),
  tentativas integer not null default 0,
  itens integer,
  itens_lidos_ate integer not null default 0,
  resultados_validos integer not null default 0,
  erro text not null default '',
  resumo jsonb not null default '{}'::jsonb,
  coletada_em timestamptz,
  atualizado_em timestamptz not null default now()
);

create index if not exists precos_pncp_contratacoes_fila_idx
  on public.precos_pncp_contratacoes (tem_homologacao desc, atualizacao_global desc)
  where estado = 'pendente';

create table if not exists public.precos_pncp_resultados (
  id_externo text primary key,
  numero_controle text not null
    references public.precos_pncp_contratacoes (numero_controle),
  numero_item integer not null,
  sequencial_resultado integer not null default 1,
  descricao text not null,
  descricao_busca text not null,
  unidade text not null,
  quantidade numeric(22, 6) not null check (quantidade > 0),
  valor_unitario numeric(22, 6) not null check (valor_unitario > 0),
  valor_total numeric(24, 6),
  data_resultado date,
  uf char(2),
  municipio text,
  orgao text,
  orgao_cnpj text,
  plataforma text,
  id_compra_origem text,
  fornecedor_cnpj text,                 -- só CNPJ; pessoa física não é gravada
  codigo_catalogo text,
  bruto jsonb not null,
  hash_linha text not null,
  versao_coletor text not null,
  coletado_em timestamptz not null default now(),
  -- Correção e cancelamento TARDIOS: quando a revisita da contratação não
  -- encontra mais este resultado como homologado conferível, a linha não
  -- é apagada (DELETE é revogado de todos) — fica `vigente = false`, com o
  -- motivo, e sai da busca. Se voltar a valer, o upsert a reativa.
  vigente boolean not null default true,
  invalidado_em timestamptz,
  invalidado_motivo text not null default '',
  busca tsvector generated always as
    (to_tsvector('portuguese'::regconfig, descricao_busca)) stored
);

create index if not exists precos_pncp_resultados_busca_idx
  on public.precos_pncp_resultados using gin (busca);
create index if not exists precos_pncp_resultados_data_idx
  on public.precos_pncp_resultados (uf, data_resultado desc);
create index if not exists precos_pncp_resultados_contratacao_idx
  on public.precos_pncp_resultados (numero_controle, numero_item);

alter table public.precos_pncp_cursores     enable row level security;
alter table public.precos_pncp_contratacoes enable row level security;
alter table public.precos_pncp_resultados   enable row level security;

revoke all on public.precos_pncp_cursores     from anon, authenticated, public;
revoke all on public.precos_pncp_contratacoes from anon, authenticated, public;
revoke all on public.precos_pncp_resultados   from anon, authenticated, public;

grant select, insert, update on public.precos_pncp_cursores     to service_role;
grant select, insert, update on public.precos_pncp_contratacoes to service_role;
grant select, insert, update on public.precos_pncp_resultados   to service_role;
-- o default do Supabase dá `arwdDxtm`: além de apagar, o servidor não cria
-- gatilho nem chave estrangeira apontando para cá (revisão de 10/11/2026)
revoke delete, truncate, references, trigger on public.precos_pncp_cursores     from service_role;
revoke delete, truncate, references, trigger on public.precos_pncp_contratacoes from service_role;
revoke delete, truncate, references, trigger on public.precos_pncp_resultados   from service_role;

grant select on public.precos_pncp_resultados to authenticated;
drop policy if exists "precos_pncp_resultados_leitura" on public.precos_pncp_resultados;
create policy "precos_pncp_resultados_leitura" on public.precos_pncp_resultados
  for select to authenticated using (true);

create or replace function public.precos_pncp_buscar(
  p_termos text[],
  p_uf text default null,
  p_desde date default null,
  p_ate date default null,
  p_limite integer default 50)
returns setof public.precos_pncp_resultados
language sql
stable
security invoker
set search_path = ''
as $$
  with consulta as (
    -- `websearch_to_tsquery` não levanta erro de sintaxe com texto livre; o
    -- "or" entre os termos é o OU dele. Sem termo, a consulta é vazia e não
    -- casa com nada.
    -- Teto de custo (revisão de 10/11/2026): a RPC é alcançável direto pelo
    -- PostgREST por qualquer conta autenticada. Só os 24 primeiros termos,
    -- cada um cortado em 60 caracteres — o coletor manda no máximo 12 por
    -- variante; o resto seria só OU a mais sobre o GIN e o `ts_rank`.
    select websearch_to_tsquery('portuguese'::regconfig,
             coalesce((select string_agg(left(t, 60), ' or ')
                         from unnest(coalesce(p_termos, '{}'::text[]))
                              with ordinality as u(t, n)
                        where n <= 24), '')) as q
  )
  select r.*
    from public.precos_pncp_resultados r, consulta c
   where r.busca @@ c.q
     and r.vigente
     and (p_uf is null or r.uf = upper(p_uf))
     and (p_desde is null or r.data_resultado >= p_desde)
     and (p_ate is null or r.data_resultado <= p_ate)
   order by ts_rank(r.busca, c.q) desc, r.data_resultado desc nulls last,
            r.id_externo
   limit least(greatest(coalesce(p_limite, 50), 1), 200)
$$;

comment on function public.precos_pncp_buscar(text[], text, date, date, integer) is
  'Resultados homologados do PNCP no índice, por termos da descrição (0042).';

revoke all on function public.precos_pncp_buscar(text[], text, date, date, integer)
  from public, anon;
grant execute on function public.precos_pncp_buscar(text[], text, date, date, integer)
  to authenticated;
grant execute on function public.precos_pncp_buscar(text[], text, date, date, integer)
  to service_role;

notify pgrst, 'reload schema';

do $$
declare
  faltou text := '';
  tabela text;
  funcao constant regprocedure :=
    'public.precos_pncp_buscar(text[], text, date, date, integer)'::regprocedure;
begin
  foreach tabela in array array['precos_pncp_cursores', 'precos_pncp_contratacoes',
                                'precos_pncp_resultados'] loop
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
    if has_table_privilege('service_role', 'public.' || tabela,
                           'references, trigger') then
      faltou := faltou || ' service_role_gatilho_ou_fk:' || tabela;
    end if;
    -- com lista, `has_table_privilege` responde "algum": cada um é conferido
    if not (has_table_privilege('service_role', 'public.' || tabela, 'select')
            and has_table_privilege('service_role', 'public.' || tabela, 'insert')
            and has_table_privilege('service_role', 'public.' || tabela, 'update')) then
      faltou := faltou || ' service_role_sem_escrita:' || tabela;
    end if;
  end loop;

  if has_any_column_privilege('authenticated', 'public.precos_pncp_cursores', 'select')
     or has_any_column_privilege('authenticated', 'public.precos_pncp_contratacoes', 'select') then
    faltou := faltou || ' authenticated_le_controle_da_coleta';
  end if;
  if not has_table_privilege('authenticated', 'public.precos_pncp_resultados', 'select') then
    faltou := faltou || ' authenticated_sem_leitura';
  end if;
  if (select count(*) from pg_policies
       where schemaname = 'public' and tablename like 'precos\_pncp\_%' escape '\') <> 1
     or not exists (
       select 1 from pg_policies
        where schemaname = 'public' and tablename = 'precos_pncp_resultados'
          and policyname = 'precos_pncp_resultados_leitura'
          and cmd = 'SELECT' and roles = '{authenticated}') then
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
    raise exception 'A 0042 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
