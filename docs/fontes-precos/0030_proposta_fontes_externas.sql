-- =====================================================================
-- PROPOSTA — NÃO APLICADA. Fica em docs/ de propósito, fora de
-- supabase/migrations/, para que ninguém a aplique por engano.
--
-- Pacote de expansão das fontes de preço (20/10/2026). Índice LOCAL das
-- evidências de fontes novas (TCE-RS, BPS…): a busca da pesquisa lê
-- daqui; nunca baixa arquivo nem chama a internet no clique.
--
-- Antes de mover para supabase/migrations/0030_*.sql:
--   1. ritual do skill `revisar-migracao` (ensaio em dois níveis, medida
--      antes/depois, conferência que falha sozinha);
--   2. revisão do agente `revisor-de-banco-e-seguranca`;
--   3. aprovação explícita do usuário.
--
-- Decisões:
-- * SEM tenant_id: é dado PÚBLICO de fonte oficial, igual para todo
--   tenant. O que é do tenant (cotação, cesta, decisão) continua em
--   pesquisa_preco_* com RLS por tenant;
-- * leitura para `authenticated` só do que estiver VALIDADO; escrita só
--   pela credencial de servidor (o ETL de bancada); DELETE e TRUNCATE
--   revogados de todos, inclusive service_role — evidência coletada não
--   some, é substituída por versão nova do snapshot;
-- * dinheiro em NUMERIC com folga de escala: o parser preserva a escala
--   da fonte (até 4 casas no BPS e no TCE-RS);
-- * a tabela NÃO decide se a fonte está habilitada: isso mora no código
--   (src/precos/fontes_externas.py), versionado.
-- =====================================================================

create table if not exists public.precos_fontes_snapshot (
  id bigint generated always as identity primary key,
  fonte_id text not null,
  url text not null check (url like 'https://%'),
  sha256 char(64) not null,
  bytes bigint not null check (bytes >= 0),
  last_modified text,
  etag text,
  versao_parser text not null,
  coletado_em timestamptz not null default now(),
  unique (fonte_id, sha256)
);

create table if not exists public.precos_evidencias (
  id bigint generated always as identity primary key,
  fonte_id text not null,
  registro_id text not null,
  snapshot_id bigint not null references public.precos_fontes_snapshot (id),
  descricao text not null,
  unidade text,
  quantidade numeric(22, 6),
  valor_unitario numeric(22, 6),
  valor_total numeric(24, 6),
  tipo_preco text not null check (tipo_preco in
    ('HOMOLOGADO', 'ADJUDICADO', 'CONTRATADO', 'ESTIMADO', 'PROPOSTA',
     'DESCONHECIDO')),
  orgao text,
  orgao_cnpj char(14),
  uf char(2),
  municipio text,
  fornecedor_cnpj char(14),           -- só CNPJ; CPF não é gravado
  processo text,
  item text,
  codigo_catalogo text,
  data_resultado date,
  resultado text,                      -- código cru da fonte
  url_evidencia text check (url_evidencia is null or url_evidencia like 'https://%'),
  atributos jsonb not null default '{}'::jsonb,
  motivos jsonb not null default '[]'::jsonb,   -- quarentena: vazio = validada
  validada boolean generated always as (motivos = '[]'::jsonb) stored,
  hash_linha char(64) not null,
  versao_parser text not null,
  atualizado_em timestamptz not null default now(),
  unique (fonte_id, registro_id)
);

create index if not exists precos_evidencias_busca_idx
  on public.precos_evidencias
  using gin (to_tsvector('portuguese', descricao))
  where validada;
create index if not exists precos_evidencias_catalogo_idx
  on public.precos_evidencias (codigo_catalogo, unidade) where validada;
create index if not exists precos_evidencias_fornecedor_idx
  on public.precos_evidencias (fornecedor_cnpj, valor_unitario, data_resultado);

create table if not exists public.precos_fontes_execucoes (
  id bigint generated always as identity primary key,
  fonte_id text not null,
  snapshot_id bigint references public.precos_fontes_snapshot (id),
  iniciada_em timestamptz not null default now(),
  terminada_em timestamptz,
  etapa text not null check (etapa in ('baixar', 'ler', 'normalizar', 'deduplicar', 'indexar')),
  desfecho text check (desfecho in ('ok', 'falha', 'recusado')),
  contagens jsonb not null default '{}'::jsonb,
  erro text                            -- classe do erro; nunca segredo, nunca URL com credencial
);

alter table public.precos_fontes_snapshot  enable row level security;
alter table public.precos_evidencias       enable row level security;
alter table public.precos_fontes_execucoes enable row level security;

revoke all on public.precos_fontes_snapshot  from anon, authenticated, public;
revoke all on public.precos_evidencias       from anon, authenticated, public;
revoke all on public.precos_fontes_execucoes from anon, authenticated, public;
revoke delete, truncate on public.precos_fontes_snapshot  from service_role;
revoke delete, truncate on public.precos_evidencias       from service_role;
revoke delete, truncate on public.precos_fontes_execucoes from service_role;

drop policy if exists "precos_evidencias_le_validadas" on public.precos_evidencias;
create policy "precos_evidencias_le_validadas" on public.precos_evidencias
  for select to authenticated using (validada);
grant select on public.precos_evidencias to authenticated;
-- snapshot e execuções: só a credencial de servidor (o painel de saúde
-- lê pelo app, que já usa service_role).
