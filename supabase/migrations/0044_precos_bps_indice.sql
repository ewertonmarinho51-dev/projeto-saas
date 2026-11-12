-- ## 0044 — Índice do BPS (Banco de Preços em Saúde, Ministério da Saúde)
-- ## ESTADO: APLICADA EM PRODUÇÃO em 12/11/2026 como `m0044_precos_bps_indice`
-- ##   (registro 20261112120809), a pedido expresso do dono ("pode aplicar a
-- ##   0044 e importar o BPS"), depois do ensaio nos dois níveis e da revisão.
--
-- REGISTRO DA APLICAÇÃO EM PRODUÇÃO (12/11/2026):
--   * ANTES: 52 tabelas em public, as 52 com RLS; 105 políticas; 96 grants de
--     tabela a `authenticated`, 0 a `anon`; 109 grants DELETE/TRUNCATE/
--     REFERENCES/TRIGGER a `service_role`; 174 funções; nenhum objeto do BPS;
--     12.377 referências, 616 itens, 3.760 resultados do PNCP;
--   * aplicação: conferência interna aprovada;
--   * DEPOIS: 54 tabelas, as 54 com RLS; 106 políticas; 97 e 0 grants
--     (`authenticated` +1: SELECT em `precos_bps_registros`); os 109 de
--     `service_role` inalterados; 175 funções; ACL `service_role=arwm` nas
--     duas tabelas, `authenticated=r` só nos registros; EXECUTE da busca só
--     para `authenticated` e `service_role`; referências, itens e PNCP intactos;
--   * comportamento, num bloco desfeito com versões e registros sintéticos:
--     `authenticated` vê só os vigentes e busca por termo e por CATMAT; não lê
--     versões nem altera (42501); `anon` sem leitura nem busca (42501);
--     `service_role` não apaga nem trunca (42501). Nenhum resíduo depois;
--   * advisors de segurança: nada novo além do INFO "RLS sem política" em
--     `precos_bps_versoes`, por desenho (como as tabelas de controle da 0042).
--
-- REGISTRO DO ENSAIO (12/11/2026):
--   * nível 1: PostgreSQL do CI (`tests/test_migracao_0044.py`), com cada ramo
--     da conferência sob mutação;
--   * nível 2, descartável `uslaxaxomjawydqtbwkb`
--     (`m0044_precos_bps_indice_ensaio`): conferência aprovada; comportamento
--     idêntico ao de produção; o banco recusa duas versões vigentes no ano
--     (23505), vigente sem publicar (23514), esfera privada (23514) e versão
--     inexistente (23503). Com 11.000 registros sintéticos (o volume do
--     arquivo de 2026): busca por termos 59 ms, por CATMAT 7 ms; republicar
--     tudo (reapontar + os quatro passos de `publicar`) < 1 s;
--   * revisão do `revisor-de-banco-e-seguranca`: sem bloqueador. Entraram na
--     conferência os reforços que ela sugeriu: REFERENCES por coluna, grant a
--     papel não nomeado (tabela e coluna, PUBLIC incluído) e gatilho — os
--     três provados por mutação no descartável. Ficou de fora, por ser herdado
--     da 0042 e só de custo: termo começando com "-" vira negação no
--     `websearch_to_tsquery`.
--
-- O PROBLEMA (11/11/2026)
--   Medicamento é o objeto em que a pesquisa de preços mais depende de fonte
--   própria, e o BPS é o banco oficial de preços PAGOS por compras públicas
--   de saúde. A API oficial só consulta por CATMAT; item de planilha
--   municipal quase nunca traz CATMAT. Para pesquisar pela descrição é
--   preciso o arquivo anual oficial num índice local.
--
-- O QUE FAZ
--   * `precos_bps_versoes`   — cada arquivo oficial importado: ano, SHA-256,
--     endereço, contagens, estado (importando, publicado, recusado) e qual é
--     a versão VIGENTE do ano;
--   * `precos_bps_registros` — uma compra por linha: CATMAT, descrição,
--     apresentação, unidade de fornecimento, quantidade, preço pago, data,
--     instituição e esfera, fornecedor (só CNPJ), a consulta oficial do
--     CATMAT, o arquivo e o `co_seq_bps` da linha naquele arquivo;
--   * `precos_bps_buscar(...)` — por CATMAT (identidade) ou por termos da
--     descrição, só do que está vigente.
--
-- DECISÕES
--   * SEM `tenant_id`: dado público de fonte oficial, igual para todo
--     município;
--   * a chave da linha é a identidade da COMPRA (`bps.chave_estavel`), não o
--     `co_seq_bps`: medido em 11/11/2026, o Ministério refaz esse número a
--     cada publicação do arquivo (o mesmo registro saiu com 27507687 em
--     20/10 e com 33224771 em 11/11). O `co_seq_bps` fica guardado, junto do
--     SHA-256 do arquivo em que ele vale;
--   * PUBLICAÇÃO POR VERSÃO: linha nova nasce `vigente = false` e só aparece
--     na busca quando o importador publica a versão inteira; linha que saiu
--     do arquivo novo deixa de ser vigente, não é apagada;
--   * quem LÊ: `authenticated`, e só as linhas vigentes de
--     `precos_bps_registros`; `anon` não lê nada; as versões são do servidor;
--   * quem ESCREVE: só a credencial de servidor (o importador). Sem DELETE,
--     TRUNCATE, REFERENCES nem TRIGGER, nem para ela;
--   * a busca roda como quem chama (`security invoker`), `search_path` vazio,
--     com o mesmo teto de custo da 0042 (24 termos de até 60 caracteres);
--   * a tabela NÃO decide se a fonte está ligada: `fontes_externas.habilitada`
--     exige a flag `price_source_bps`, o mapeamento conferido e a licença
--     aprovada com prova — as três no código, versionadas.
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * não importa nada: índice vazio até o importador rodar;
--   * não aprova a licença de reúso do BPS — isso é decisão do dono;
--   * só medicamentos: é o que o arquivo oficial de 2026 traz (classe 6505).

create table if not exists public.precos_bps_versoes (
  ano integer not null check (ano between 2000 and 2100),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  estado text not null default 'importando' check (estado in
    ('importando', 'publicado', 'recusado')),
  vigente boolean not null default false,
  url text not null check (url like 'https://%'),
  last_modified text,
  linhas integer not null default 0,
  validas integer not null default 0,
  quarentena jsonb not null default '{}'::jsonb,
  motivo text not null default '',
  versao_parser text not null default '',
  versao_importador text not null default '',
  publicado_em timestamptz,
  criado_em timestamptz not null default now(),
  primary key (ano, sha256),
  check (not vigente or estado = 'publicado')
);

-- uma versão vigente por ano, no máximo
create unique index if not exists precos_bps_versoes_vigente_idx
  on public.precos_bps_versoes (ano) where vigente;

create table if not exists public.precos_bps_registros (
  registro_id text primary key,
  co_seq_bps text not null,
  ano integer not null,
  arquivo_sha256 text not null,
  vigente boolean not null default false,
  catmat text not null,
  descricao text not null,
  descricao_busca text not null,
  unidade text not null,
  apresentacao text,
  quantidade numeric(22, 6) not null check (quantidade > 0),
  valor_unitario numeric(22, 6) not null check (valor_unitario > 0),
  valor_total numeric(24, 6),
  data_compra date not null,
  uf char(2),
  municipio text,
  orgao text,
  orgao_cnpj text,
  esfera text not null check (esfera in
    ('FEDERAL', 'ESTADUAL', 'MUNICIPAL', 'DISTRITAL')),
  fornecedor_cnpj text,                -- só CNPJ; pessoa física não é gravada
  modalidade text,
  tipo_compra text,
  generico text,
  registro_anvisa text,
  processo text,
  url_evidencia text not null check (url_evidencia like 'https://%'),
  url_arquivo text not null check (url_arquivo like 'https://%'),
  hash_linha text not null,
  versao_parser text not null,
  importado_em timestamptz not null default now(),
  busca tsvector generated always as
    (to_tsvector('portuguese'::regconfig, descricao_busca)) stored,
  foreign key (ano, arquivo_sha256)
    references public.precos_bps_versoes (ano, sha256)
);

create index if not exists precos_bps_registros_busca_idx
  on public.precos_bps_registros using gin (busca) where vigente;
create index if not exists precos_bps_registros_catmat_idx
  on public.precos_bps_registros (catmat, data_compra desc) where vigente;
create index if not exists precos_bps_registros_versao_idx
  on public.precos_bps_registros (ano, arquivo_sha256);

alter table public.precos_bps_versoes   enable row level security;
alter table public.precos_bps_registros enable row level security;

revoke all on public.precos_bps_versoes   from anon, authenticated, public;
revoke all on public.precos_bps_registros from anon, authenticated, public;

grant select, insert, update on public.precos_bps_versoes   to service_role;
grant select, insert, update on public.precos_bps_registros to service_role;
revoke delete, truncate, references, trigger on public.precos_bps_versoes   from service_role;
revoke delete, truncate, references, trigger on public.precos_bps_registros from service_role;

grant select on public.precos_bps_registros to authenticated;
drop policy if exists "precos_bps_registros_leitura" on public.precos_bps_registros;
create policy "precos_bps_registros_leitura" on public.precos_bps_registros
  for select to authenticated using (vigente);

create or replace function public.precos_bps_buscar(
  p_termos text[],
  p_catmat text default null,
  p_uf text default null,
  p_desde date default null,
  p_ate date default null,
  p_limite integer default 50)
returns setof public.precos_bps_registros
language sql
stable
security invoker
set search_path = ''
as $$
  with consulta as (
    -- mesmo teto de custo da 0042: 24 termos, 60 caracteres cada. Sem termo
    -- a consulta é vazia e não casa com nada.
    select websearch_to_tsquery('portuguese'::regconfig,
             coalesce((select string_agg(left(t, 60), ' or ')
                         from unnest(coalesce(p_termos, '{}'::text[]))
                              with ordinality as u(t, n)
                        where n <= 24), '')) as q
  )
  select r.*
    from public.precos_bps_registros r, consulta c
   where r.vigente
     -- com CATMAT, só o código: é a identidade do medicamento
     and case when nullif(p_catmat, '') is not null
              then r.catmat = p_catmat
              else r.busca @@ c.q end
     and (p_uf is null or r.uf = upper(p_uf))
     and (p_desde is null or r.data_compra >= p_desde)
     and (p_ate is null or r.data_compra <= p_ate)
   order by case when nullif(p_catmat, '') is not null then 0
                 else ts_rank(r.busca, c.q) end desc,
            r.data_compra desc, r.registro_id
   limit least(greatest(coalesce(p_limite, 50), 1), 200)
$$;

comment on function public.precos_bps_buscar(text[], text, text, date, date, integer) is
  'Preços pagos do BPS no índice, por CATMAT ou por termos da descrição (0044).';

revoke all on function public.precos_bps_buscar(text[], text, text, date, date, integer)
  from public, anon;
grant execute on function public.precos_bps_buscar(text[], text, text, date, date, integer)
  to authenticated;
grant execute on function public.precos_bps_buscar(text[], text, text, date, date, integer)
  to service_role;

notify pgrst, 'reload schema';

do $$
declare
  faltou text := '';
  tabela text;
  funcao constant regprocedure :=
    'public.precos_bps_buscar(text[], text, text, date, date, integer)'::regprocedure;
begin
  foreach tabela in array array['precos_bps_versoes', 'precos_bps_registros'] loop
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
    -- A conferência por papel NOMEADO não vê o papel que ninguém nomeou:
    -- fora o dono, só `service_role` e `authenticated` podem aparecer no ACL
    -- da tabela ou de qualquer coluna (PUBLIC é o grantee 0 e também cai).
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

  if has_any_column_privilege('authenticated', 'public.precos_bps_versoes', 'select') then
    faltou := faltou || ' authenticated_le_controle_da_importacao';
  end if;
  if not has_table_privilege('authenticated', 'public.precos_bps_registros', 'select') then
    faltou := faltou || ' authenticated_sem_leitura';
  end if;
  if (select count(*) from pg_policies
       where schemaname = 'public' and tablename like 'precos\_bps\_%' escape '\') <> 1
     or not exists (
       select 1 from pg_policies
        where schemaname = 'public' and tablename = 'precos_bps_registros'
          and policyname = 'precos_bps_registros_leitura'
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
    raise exception 'A 0044 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
