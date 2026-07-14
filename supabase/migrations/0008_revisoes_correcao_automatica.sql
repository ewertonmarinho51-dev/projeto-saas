-- ============================================================
-- 0008 — Revisões: ciclo de correção automática de documentos
--        (Etapa 2 do pacote_correcao_automatica_documentos_v1;
--         exige a 0006 aplicada)
--
-- Estratégia EXPAND (nada é removido; comportamento antigo intacto):
--   tabela `revisoes` = job de revisão/correção de um processo, com o
--   histórico completo do ciclo em JSONB:
--     - snapshots : versões IMUTÁVEIS do bundle (uma por ciclo);
--     - relatorios: audit-reports (findings estruturados) por ciclo;
--     - planos    : patch-plans propostos pelo corretor por ciclo;
--     - diffs     : diffs estruturais entre versões;
--     - eventos   : transições da máquina de estados (ator, motivo,
--                   versão origem/destino, timestamp).
--   `idempotency_key` única (parcial) garante que reexecuções técnicas
--   não criem novo ciclo (T11/T12 do pacote).
--
-- Com as flags de correção automática DESLIGADAS (config_app) NADA
-- muda no app — a tabela fica vazia. Rollback = desligar as flags.
-- ============================================================

create table if not exists public.revisoes (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  tenant_id uuid not null
    default '11111111-1111-1111-1111-111111111111'
    references public.tenants (id),
  processo_id uuid references public.processos (id),
  -- máquina de estados (02_maquina_de_estados.md); texto livre para não
  -- exigir migração a cada estado novo
  status text not null default 'REVIEW_QUEUED',
  ciclo int not null default 0,
  etapa_ui text not null default '',
  versao_atual int not null default 1,
  bundle_hash text not null default '',
  snapshots jsonb not null default '[]'::jsonb,
  relatorios jsonb not null default '[]'::jsonb,
  planos jsonb not null default '[]'::jsonb,
  diffs jsonb not null default '[]'::jsonb,
  eventos jsonb not null default '[]'::jsonb,
  idempotency_key text not null default '',
  bloqueio text not null default ''
);

create index if not exists revisoes_processo_idx
  on public.revisoes (processo_id, criado_em desc);

create index if not exists revisoes_tenant_idx
  on public.revisoes (tenant_id, atualizado_em desc);

-- reexecução com a mesma chave não cria novo job (idempotência)
create unique index if not exists revisoes_idempotencia_idx
  on public.revisoes (idempotency_key)
  where idempotency_key <> '';

-- RLS: mesmo modelo do restante (papel anon, tenant único em produção).
-- O fechamento por tenant via auth.uid()/JWT acontece com a migração
-- para Supabase Auth (decisão pendente do proprietário).
alter table public.revisoes enable row level security;

drop policy if exists "anon_select" on public.revisoes;
drop policy if exists "anon_insert" on public.revisoes;
drop policy if exists "anon_update" on public.revisoes;

create policy "anon_select" on public.revisoes for select to anon using (true);
create policy "anon_insert" on public.revisoes for insert to anon with check (true);
create policy "anon_update" on public.revisoes for update to anon using (true) with check (true);
