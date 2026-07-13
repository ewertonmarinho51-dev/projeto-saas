-- ============================================================
-- 0006 — Fundação multi-tenant (Fase 1 da matriz de compatibilidade)
--
-- Estratégia EXPAND (nada é removido nem alterado de comportamento):
--   1. tabela `tenants` com o município atual como TENANT PADRÃO;
--   2. coluna `tenant_id` (com DEFAULT no tenant padrão) nas entidades
--      municipais + backfill dos registros existentes;
--   3. coluna `snapshot` em processos (congelamento de contexto
--      institucional na emissão — uso nas fases seguintes);
--   4. tabela `geracoes` (persistência do registro técnico de geração).
--
-- Com o app atual (flag desligada) NADA muda: o DEFAULT garante que
-- toda escrita continue caindo no tenant padrão. Rollback = ignorar as
-- colunas novas (nenhum código antigo quebra).
-- ============================================================

-- 1. Tenants (municípios). UUID FIXO para o tenant padrão: referenciável
--    em DEFAULTs de coluna (Postgres não aceita subquery em DEFAULT).
create table if not exists public.tenants (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  slug text not null unique,
  nome text not null,
  uf text not null default '',
  ativo boolean not null default true
);

insert into public.tenants (id, slug, nome, uf)
values ('11111111-1111-1111-1111-111111111111',
        'paragominas', 'Prefeitura Municipal de Paragominas', 'PA')
on conflict (slug) do nothing;

alter table public.tenants enable row level security;
create policy "anon_select_tenants" on public.tenants
  for select to anon using (true);

-- 2. tenant_id nas entidades municipais (DEFAULT = tenant padrão)
alter table public.processos
  add column if not exists tenant_id uuid not null
  default '11111111-1111-1111-1111-111111111111'
  references public.tenants (id);

alter table public.usuarios
  add column if not exists tenant_id uuid not null
  default '11111111-1111-1111-1111-111111111111'
  references public.tenants (id);

alter table public.config_orgaos
  add column if not exists tenant_id uuid not null
  default '11111111-1111-1111-1111-111111111111'
  references public.tenants (id);

alter table public.documentos_referencia
  add column if not exists tenant_id uuid not null
  default '11111111-1111-1111-1111-111111111111'
  references public.tenants (id);

-- config_app: chaves de IA passam a poder ser por tenant (a chave textual
-- vira única por par tenant+chave; registros atuais = tenant padrão)
alter table public.config_app
  add column if not exists tenant_id uuid not null
  default '11111111-1111-1111-1111-111111111111'
  references public.tenants (id);

create index if not exists processos_tenant_idx
  on public.processos (tenant_id, atualizado_em desc);
create index if not exists documentos_referencia_tenant_idx
  on public.documentos_referencia (tenant_id);

-- 3. Snapshot de contexto institucional no processo (fases 2+)
alter table public.processos
  add column if not exists snapshot jsonb not null default '{}'::jsonb;

-- 4. Registro técnico de gerações (auditoria persistente)
create table if not exists public.geracoes (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  tenant_id uuid not null
    default '11111111-1111-1111-1111-111111111111'
    references public.tenants (id),
  processo_id uuid,
  documento text not null,
  motor text not null,
  modelo text not null default '',
  duracao_s numeric,
  tokens_entrada int,
  tokens_saida int,
  request_id text not null default '',
  status text not null,
  erro text not null default '',
  fallback boolean not null default false
);

create index if not exists geracoes_tenant_criado_idx
  on public.geracoes (tenant_id, criado_em desc);

alter table public.geracoes enable row level security;
create policy "anon_insert_geracoes" on public.geracoes
  for insert to anon with check (true);
create policy "anon_select_geracoes" on public.geracoes
  for select to anon using (true);

-- OBS: as políticas continuam liberadas para `anon` (tenant único em
-- produção). O fechamento por tenant (RLS por auth.uid()/JWT claim)
-- acontece na Fase 2, junto com a migração para Supabase Auth.
