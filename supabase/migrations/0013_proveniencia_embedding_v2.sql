-- ============================================================
-- 0013 — Índice vetorial V2 com PROVENIÊNCIA (expand-only)
--
-- A auditoria de 11/08/2026 não conseguiu provar documentalmente qual
-- modelo gerou os vetores da coluna `embedding`: o banco não guardava
-- provedor, modelo, dimensão nem data. Esta migração cria o índice V2 ao
-- lado do legado, agora com identidade completa em cada chunk.
--
-- Expand-only: nada é removido ou reescrito. A coluna `embedding` e seu
-- índice permanecem intactos e continuam servindo a produção (`main`)
-- até o corte coordenado com o deploy do P1.
--
-- Padrão V2 (decisão registrada em src/config.py):
--   provedor  openai
--   modelo    text-embedding-3-small
--   dimensão  768
--   versão    v2
-- ============================================================

alter table public.chunks_referencia
  add column if not exists embedding_v2 public.vector(768),
  add column if not exists embedding_provider text,
  add column if not exists embedding_model text,
  add column if not exists embedding_dimensions int,
  add column if not exists embedding_version text,
  add column if not exists embedding_generated_at timestamptz,
  add column if not exists embedding_status text not null default 'pendente';

-- Estados possíveis: pendente (sem vetor), ok (vetorizado), falha
-- (tentativa registrada). 'pendente' é o default para que um chunk novo
-- jamais nasça "vetorizado por omissão".
do $$
begin
  if not exists (select 1 from pg_constraint
                  where conname = 'chunks_referencia_embedding_status_ck') then
    alter table public.chunks_referencia
      add constraint chunks_referencia_embedding_status_ck
      check (embedding_status in ('pendente', 'ok', 'falha'));
  end if;
end $$;

-- Coerência: vetor presente exige proveniência completa; ausente exige
-- que o status NÃO seja 'ok'. Impede o retorno do NULL silencioso.
do $$
begin
  if not exists (select 1 from pg_constraint
                  where conname = 'chunks_referencia_proveniencia_ck') then
    alter table public.chunks_referencia
      add constraint chunks_referencia_proveniencia_ck
      check (
        (embedding_v2 is null and embedding_status <> 'ok')
        or (embedding_v2 is not null
            and embedding_provider is not null
            and embedding_model is not null
            and embedding_dimensions is not null
            and embedding_version is not null
            and embedding_generated_at is not null
            and embedding_status = 'ok')
      );
  end if;
end $$;

-- Retomada do backfill em lotes: "os próximos que faltam".
create index if not exists chunks_referencia_backfill_idx
  on public.chunks_referencia (documento_id, ordem)
  where embedding_v2 is null;

comment on column public.chunks_referencia.embedding_v2 is
  'Índice vetorial V2 — openai/text-embedding-3-small/768. Um único '
  'espaço vetorial: nunca gravar vetor de outro provedor/modelo aqui.';
comment on column public.chunks_referencia.embedding_status is
  'pendente | ok | falha — chunk sem vetor fica explicitamente pendente '
  'e continua disponível para a busca textual.';
comment on column public.chunks_referencia.embedding is
  'LEGADO: origem não comprovada documentalmente (auditoria 11/08/2026). '
  'Mantido apenas para leitura da versão em produção até o corte para o '
  'embedding_v2. Não gravar novos vetores aqui.';
