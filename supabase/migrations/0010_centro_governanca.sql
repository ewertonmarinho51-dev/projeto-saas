-- ============================================================
-- 0010 — Centro de Governança e Catálogo Documental (Fase 1 do
--        pacote_centro_governanca_catalogo_v1 / prompt V6;
--        exige 0006 e 0009 aplicadas)
--
-- Estratégia EXPAND (nada é removido; comportamento V5 intacto —
-- as 12 flags do V6 nascem DESLIGADAS e nenhuma tela muda):
--   1. governanca_artefatos  registro de cláusulas, políticas, famílias
--      de modelos e templates (tenant NULL = escopo da PLATAFORMA);
--   2. governanca_versoes    versões IMUTÁVEIS após publicação
--      (payload JSONB + hash + vigência + autor/revisor/aprovador);
--   3. governanca_publicacoes releases com vigência e rollback;
--   4. simulacoes            impacto ANTES de publicar;
--   5. pareceres + parecer_achados  ingestão individual/lote;
--   6. melhoria_clusters + melhoria_propostas  laboratório;
--   7. governanca_aprovacoes segregação autor/revisor/publicador;
--   8. governanca_eventos    trilha APPEND-ONLY (sem update/delete).
--   + usuarios.papel_governanca (proprietario | admin_global |
--     admin_municipal | revisor_juridico | publicador | auditor).
--
-- RLS no modelo vigente (papel anon, tenant único em produção; o
-- fechamento por auth.uid()/JWT vem com a migração para Supabase Auth
-- — o escopo por papel é aplicado na camada de aplicação até lá).
-- ============================================================

-- 0. Papel de governança do usuário (NULL = servidor comum, sem acesso)
alter table public.usuarios
  add column if not exists papel_governanca text;

-- 1. Artefatos de governança
create table if not exists public.governanca_artefatos (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  tenant_id uuid references public.tenants (id),  -- NULL = plataforma
  secretaria_id uuid references public.secretarias (id),
  tipo_artefato text not null,
  -- clausula | politica | familia | template
  chave_estavel text not null,
  descricao text not null default ''
);

-- unicidade por escopo (plataforma/município/secretaria)
create unique index if not exists governanca_artefatos_chave_idx
  on public.governanca_artefatos (
    tipo_artefato, chave_estavel,
    coalesce(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid),
    coalesce(secretaria_id, '00000000-0000-0000-0000-000000000000'::uuid)
  );

create index if not exists governanca_artefatos_tenant_idx
  on public.governanca_artefatos (tenant_id, tipo_artefato);

alter table public.governanca_artefatos enable row level security;
drop policy if exists "anon_select" on public.governanca_artefatos;
drop policy if exists "anon_insert" on public.governanca_artefatos;
create policy "anon_select" on public.governanca_artefatos for select to anon using (true);
create policy "anon_insert" on public.governanca_artefatos for insert to anon with check (true);

-- 2. Versões (imutáveis após publicação — imutabilidade garantida na
--    aplicação: update permitido apenas em DRAFT/UNDER_REVIEW)
create table if not exists public.governanca_versoes (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  artefato_id uuid not null references public.governanca_artefatos (id),
  versao int not null default 1,
  status text not null default 'DRAFT',
  -- DRAFT | UNDER_REVIEW | APPROVED_FOR_SIMULATION | SHADOW |
  -- SCHEDULED | PUBLISHED | SUPERSEDED | REVOKED
  vigencia_inicio timestamptz,
  vigencia_fim timestamptz,
  payload jsonb not null default '{}'::jsonb,
  hash text not null default '',
  autor uuid,
  revisor uuid,
  aprovador uuid,
  unique (artefato_id, versao)
);

create index if not exists governanca_versoes_status_idx
  on public.governanca_versoes (artefato_id, status);

alter table public.governanca_versoes enable row level security;
drop policy if exists "anon_select" on public.governanca_versoes;
drop policy if exists "anon_insert" on public.governanca_versoes;
drop policy if exists "anon_update" on public.governanca_versoes;
create policy "anon_select" on public.governanca_versoes for select to anon using (true);
create policy "anon_insert" on public.governanca_versoes for insert to anon with check (true);
create policy "anon_update" on public.governanca_versoes for update to anon using (true) with check (true);

-- 3. Publicações (releases; rollback = release restaurador)
create table if not exists public.governanca_publicacoes (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  tenant_id uuid references public.tenants (id),
  numero serial,
  status text not null default 'ATIVA',   -- ATIVA | REVERTIDA
  itens jsonb not null default '[]'::jsonb,  -- [{artefato, versao, hash}]
  motivo text not null default '',
  publicado_por uuid,
  reverte uuid                                -- release restaurador
);

alter table public.governanca_publicacoes enable row level security;
drop policy if exists "anon_select" on public.governanca_publicacoes;
drop policy if exists "anon_insert" on public.governanca_publicacoes;
drop policy if exists "anon_update" on public.governanca_publicacoes;
create policy "anon_select" on public.governanca_publicacoes for select to anon using (true);
create policy "anon_insert" on public.governanca_publicacoes for insert to anon with check (true);
create policy "anon_update" on public.governanca_publicacoes for update to anon using (true) with check (true);

-- 4. Simulações (impacto antes da publicação)
create table if not exists public.simulacoes (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  tenant_id uuid references public.tenants (id),
  alvo jsonb not null default '{}'::jsonb,     -- artefato/versão simulada
  contexto jsonb not null default '{}'::jsonb, -- processo de teste
  resultado jsonb not null default '{}'::jsonb,
  status text not null default 'CONCLUIDA'
);

alter table public.simulacoes enable row level security;
drop policy if exists "anon_select" on public.simulacoes;
drop policy if exists "anon_insert" on public.simulacoes;
create policy "anon_select" on public.simulacoes for select to anon using (true);
create policy "anon_insert" on public.simulacoes for insert to anon with check (true);

-- 5. Pareceres jurídicos (ingestão individual e em lote)
create table if not exists public.pareceres (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  tenant_id uuid not null
    default '11111111-1111-1111-1111-111111111111'
    references public.tenants (id),
  processo_id uuid,
  lote_id text not null default '',
  nome_arquivo text not null default '',
  texto text not null default '',       -- extraído; tratado como DADO
  hash_origem text not null default '',
  status text not null default 'UPLOADED',
  -- UPLOADED | EXTRACTED | NORMALIZED | GROUPED | UNDER_REVIEW |
  -- ACCEPTED | REJECTED | FAILED
  erro text not null default ''
);

create index if not exists pareceres_lote_idx
  on public.pareceres (tenant_id, lote_id, status);

alter table public.pareceres enable row level security;
drop policy if exists "anon_select" on public.pareceres;
drop policy if exists "anon_insert" on public.pareceres;
drop policy if exists "anon_update" on public.pareceres;
create policy "anon_select" on public.pareceres for select to anon using (true);
create policy "anon_insert" on public.pareceres for insert to anon with check (true);
create policy "anon_update" on public.pareceres for update to anon using (true) with check (true);

create table if not exists public.parecer_achados (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  parecer_id uuid not null references public.pareceres (id),
  categoria text not null default '',
  gravidade text not null default 'MEDIUM',
  problema text not null default '',    -- normalizado e anonimizado
  documento_afetado text not null default '',
  clausula_afetada text not null default '',
  fundamento text not null default '',
  correcao_solicitada text not null default '',
  causa text not null default '',
  sistemico boolean not null default false,
  confianca real not null default 0.5,
  evidencias jsonb not null default '[]'::jsonb
);

create index if not exists parecer_achados_parecer_idx
  on public.parecer_achados (parecer_id);

alter table public.parecer_achados enable row level security;
drop policy if exists "anon_select" on public.parecer_achados;
drop policy if exists "anon_insert" on public.parecer_achados;
create policy "anon_select" on public.parecer_achados for select to anon using (true);
create policy "anon_insert" on public.parecer_achados for insert to anon with check (true);

-- 6. Laboratório de melhorias
create table if not exists public.melhoria_clusters (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  tenant_id uuid not null
    default '11111111-1111-1111-1111-111111111111'
    references public.tenants (id),
  rotulo text not null default '',
  problema text not null default '',
  achado_ids jsonb not null default '[]'::jsonb,  -- vínculo preservado
  status text not null default 'ABERTO'
);

alter table public.melhoria_clusters enable row level security;
drop policy if exists "anon_select" on public.melhoria_clusters;
drop policy if exists "anon_insert" on public.melhoria_clusters;
drop policy if exists "anon_update" on public.melhoria_clusters;
create policy "anon_select" on public.melhoria_clusters for select to anon using (true);
create policy "anon_insert" on public.melhoria_clusters for insert to anon with check (true);
create policy "anon_update" on public.melhoria_clusters for update to anon using (true) with check (true);

create table if not exists public.melhoria_propostas (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  tenant_id uuid not null
    default '11111111-1111-1111-1111-111111111111'
    references public.tenants (id),
  cluster_id uuid references public.melhoria_clusters (id),
  tipo_alvo text not null,
  -- formulario | fato_obrigatorio | validacao | politica | clausula |
  -- modelo | prompt | auditor | operacional
  status text not null default 'DRAFT',
  proposta jsonb not null default '{}'::jsonb,  -- SEM dados específicos
  criado_por uuid
);

alter table public.melhoria_propostas enable row level security;
drop policy if exists "anon_select" on public.melhoria_propostas;
drop policy if exists "anon_insert" on public.melhoria_propostas;
drop policy if exists "anon_update" on public.melhoria_propostas;
create policy "anon_select" on public.melhoria_propostas for select to anon using (true);
create policy "anon_insert" on public.melhoria_propostas for insert to anon with check (true);
create policy "anon_update" on public.melhoria_propostas for update to anon using (true) with check (true);

-- 7. Aprovações (segregação autor/revisor/publicador)
create table if not exists public.governanca_aprovacoes (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  tenant_id uuid references public.tenants (id),
  entidade_tipo text not null,
  entidade_id uuid not null,
  papel_exigido text not null default '',
  aprovador uuid,
  decisao text not null default '',   -- APROVADO | REJEITADO
  motivo text not null default ''
);

alter table public.governanca_aprovacoes enable row level security;
drop policy if exists "anon_select" on public.governanca_aprovacoes;
drop policy if exists "anon_insert" on public.governanca_aprovacoes;
create policy "anon_select" on public.governanca_aprovacoes for select to anon using (true);
create policy "anon_insert" on public.governanca_aprovacoes for insert to anon with check (true);

-- 8. Trilha de auditoria (APPEND-ONLY: sem policy de update/delete)
create table if not exists public.governanca_eventos (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  tenant_id uuid references public.tenants (id),
  ator uuid,
  tipo_evento text not null,
  entidade_tipo text not null default '',
  entidade_id uuid,
  payload jsonb not null default '{}'::jsonb
);

create index if not exists governanca_eventos_tenant_idx
  on public.governanca_eventos (tenant_id, criado_em desc);

alter table public.governanca_eventos enable row level security;
drop policy if exists "anon_select" on public.governanca_eventos;
drop policy if exists "anon_insert" on public.governanca_eventos;
create policy "anon_select" on public.governanca_eventos for select to anon using (true);
create policy "anon_insert" on public.governanca_eventos for insert to anon with check (true);
