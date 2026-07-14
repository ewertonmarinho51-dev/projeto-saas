-- ============================================================
-- 0009 — Governança e qualidade documental (Fase 1 do
--        pacote_governanca_qualidade_documental_v1 / prompt V5;
--        exige a 0006 aplicada)
--
-- Estratégia EXPAND (nada é removido; comportamento v4 intacto —
-- todas as flags nascem DESLIGADAS e nenhuma tela muda):
--   1. fatos_canonicos    fonte da verdade do processo (versionada);
--   2. fontes_conhecimento governança de vigência das fontes do RAG;
--   3. regras_conhecimento regras estruturadas por camada/precedência;
--   4. decisoes           registro APPEND-ONLY e reproduzível (hashes)
--                         — base da explicabilidade;
--   5. qualidade_scores   índice de confiança (shadow primeiro);
--   6. aprendizado_feedback captura → curadoria → publicação.
--
-- RLS no modelo vigente (papel anon, tenant único em produção; o
-- fechamento por auth.uid()/JWT vem com a migração para Supabase
-- Auth). `decisoes` NÃO recebe policies de UPDATE/DELETE: append-only.
-- ============================================================

-- 1. Fatos canônicos do processo (versionados; nova versão substitui)
create table if not exists public.fatos_canonicos (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  tenant_id uuid not null
    default '11111111-1111-1111-1111-111111111111'
    references public.tenants (id),
  processo_id uuid,
  path text not null,                 -- ex.: objeto.natureza, itens[0].quantidade
  tipo text not null default 'texto', -- texto|numero|booleano|lista|objeto
  valor jsonb not null default 'null'::jsonb,
  fonte text not null default '',     -- ex.: formulario:objeto, memorando
  status text not null default 'extraido',
  -- extraido | confirmado | disputado | substituido
  confirmado_por uuid,
  confianca real not null default 0.5,
  versao int not null default 1,
  substitui uuid,                     -- versão anterior deste fato
  hash text not null default ''
);

create index if not exists fatos_processo_idx
  on public.fatos_canonicos (processo_id, path, versao desc);
create index if not exists fatos_tenant_idx
  on public.fatos_canonicos (tenant_id, criado_em desc);

alter table public.fatos_canonicos enable row level security;
drop policy if exists "anon_select" on public.fatos_canonicos;
drop policy if exists "anon_insert" on public.fatos_canonicos;
drop policy if exists "anon_update" on public.fatos_canonicos;
create policy "anon_select" on public.fatos_canonicos for select to anon using (true);
create policy "anon_insert" on public.fatos_canonicos for insert to anon with check (true);
create policy "anon_update" on public.fatos_canonicos for update to anon using (true) with check (true);

-- 2. Governança de fontes de conhecimento (vigência/revogação; liga
--    a Base de Conhecimento do RAG às decisões — KQ-003)
create table if not exists public.fontes_conhecimento (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  tenant_id uuid
    references public.tenants (id),  -- NULL = camada nacional/plataforma
  documento_referencia_id uuid,       -- link opcional ao RAG
  rotulo text not null,
  camada text not null default 'municipio',
  -- nacional | controle | plataforma | municipio | secretaria | processo
  vigente boolean not null default true,
  revogada_em timestamptz,
  versao int not null default 1,
  hash text not null default ''
);

create index if not exists fontes_tenant_idx
  on public.fontes_conhecimento (tenant_id, vigente);

alter table public.fontes_conhecimento enable row level security;
drop policy if exists "anon_select" on public.fontes_conhecimento;
drop policy if exists "anon_insert" on public.fontes_conhecimento;
drop policy if exists "anon_update" on public.fontes_conhecimento;
create policy "anon_select" on public.fontes_conhecimento for select to anon using (true);
create policy "anon_insert" on public.fontes_conhecimento for insert to anon with check (true);
create policy "anon_update" on public.fontes_conhecimento for update to anon using (true) with check (true);

-- 3. Regras de conhecimento (estruturadas, versionadas, por camada)
create table if not exists public.regras_conhecimento (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  tenant_id uuid
    references public.tenants (id),  -- NULL = plataforma/nacional
  chave_estavel text not null,        -- ex.: regra.me-epp.srp-bens
  versao int not null default 1,
  status text not null default 'DRAFT',
  -- DRAFT | UNDER_REVIEW | PUBLISHED | REVOKED | SUPERSEDED
  camada text not null default 'municipio',
  prioridade int not null default 100,
  condicao jsonb not null default '{}'::jsonb,  -- ALL/ANY/NOT + folhas
  acoes jsonb not null default '[]'::jsonb,
  vigencia_inicio timestamptz,
  vigencia_fim timestamptz,
  fontes jsonb not null default '[]'::jsonb,
  justificativa text not null default '',
  autor uuid,
  revisor uuid,
  aprovador uuid,
  hash text not null default '',
  unique (chave_estavel, versao)
);

create index if not exists regras_tenant_status_idx
  on public.regras_conhecimento (tenant_id, status, camada);

alter table public.regras_conhecimento enable row level security;
drop policy if exists "anon_select" on public.regras_conhecimento;
drop policy if exists "anon_insert" on public.regras_conhecimento;
drop policy if exists "anon_update" on public.regras_conhecimento;
create policy "anon_select" on public.regras_conhecimento for select to anon using (true);
create policy "anon_insert" on public.regras_conhecimento for insert to anon with check (true);
create policy "anon_update" on public.regras_conhecimento for update to anon using (true) with check (true);

-- 4. Decisões (APPEND-ONLY: sem policy de update/delete — a trilha
--    fonte → fato → regra → decisão é imutável e reproduzível)
create table if not exists public.decisoes (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  tenant_id uuid not null
    default '11111111-1111-1111-1111-111111111111'
    references public.tenants (id),
  processo_id uuid,
  documento text not null default '',
  tipo_decisao text not null,
  -- ex.: clausulas_aplicaveis | bloqueio | familia_modelo | consistencia
  resultado jsonb not null default '{}'::jsonb,
  regras_versoes jsonb not null default '[]'::jsonb,
  fatos_versoes jsonb not null default '[]'::jsonb,
  fontes jsonb not null default '[]'::jsonb,
  explicacao jsonb not null default '{}'::jsonb,
  input_hash text not null default '',
  output_hash text not null default '',
  ator_tipo text not null default 'sistema',  -- sistema | usuario | ia
  ator_id uuid
);

create index if not exists decisoes_processo_idx
  on public.decisoes (processo_id, criado_em desc);
create index if not exists decisoes_tenant_idx
  on public.decisoes (tenant_id, criado_em desc);

alter table public.decisoes enable row level security;
drop policy if exists "anon_select" on public.decisoes;
drop policy if exists "anon_insert" on public.decisoes;
create policy "anon_select" on public.decisoes for select to anon using (true);
create policy "anon_insert" on public.decisoes for insert to anon with check (true);

-- 5. Índice de confiança (config versionada; shadow antes de gate)
create table if not exists public.qualidade_scores (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  tenant_id uuid not null
    default '11111111-1111-1111-1111-111111111111'
    references public.tenants (id),
  processo_id uuid,
  versao_bundle int not null default 1,
  config_versao text not null default 'quality-config@1',
  score numeric not null default 0,
  dimensoes jsonb not null default '{}'::jsonb,
  criticos jsonb not null default '[]'::jsonb,
  shadow boolean not null default true
);

create index if not exists scores_processo_idx
  on public.qualidade_scores (processo_id, criado_em desc);

alter table public.qualidade_scores enable row level security;
drop policy if exists "anon_select" on public.qualidade_scores;
drop policy if exists "anon_insert" on public.qualidade_scores;
create policy "anon_select" on public.qualidade_scores for select to anon using (true);
create policy "anon_insert" on public.qualidade_scores for insert to anon with check (true);

-- 6. Aprendizado institucional controlado (nada publica sozinho)
create table if not exists public.aprendizado_feedback (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  tenant_id uuid not null
    default '11111111-1111-1111-1111-111111111111'
    references public.tenants (id),
  processo_id uuid,
  origem text not null default '',    -- ex.: edicao_documento, parecer
  status text not null default 'CAPTURED',
  -- CAPTURED | NORMALIZED | UNDER_REVIEW | APPROVED_FOR_SHADOW |
  -- SHADOW_VALIDATED | PUBLISHED | DEPRECATED | REJECTED
  conteudo jsonb not null default '{}'::jsonb,   -- SEMPRE anonimizado
  evidencias jsonb not null default '[]'::jsonb,
  curador uuid,
  versao_publicada text not null default ''
);

create index if not exists feedback_tenant_status_idx
  on public.aprendizado_feedback (tenant_id, status, criado_em desc);

alter table public.aprendizado_feedback enable row level security;
drop policy if exists "anon_select" on public.aprendizado_feedback;
drop policy if exists "anon_insert" on public.aprendizado_feedback;
drop policy if exists "anon_update" on public.aprendizado_feedback;
create policy "anon_select" on public.aprendizado_feedback for select to anon using (true);
create policy "anon_insert" on public.aprendizado_feedback for insert to anon with check (true);
create policy "anon_update" on public.aprendizado_feedback for update to anon using (true) with check (true);
