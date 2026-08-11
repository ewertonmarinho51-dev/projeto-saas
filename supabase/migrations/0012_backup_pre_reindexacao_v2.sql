-- ============================================================
-- 0012 — Backup ANTES da reconstrução do índice vetorial (V2)
--
-- Cópia integral e imutável do estado atual: ids, documento_id, ordem,
-- conteúdo, embedding LEGADO e tsv, mais o catálogo de documentos (que
-- carrega o tenant). É a rede de rollback da reindexação — nenhuma linha
-- da tabela viva é tocada aqui.
--
-- Impressão digital do estado copiado (11/08/2026), conferida após a
-- cópia (backup e tabela viva com o mesmo hash):
--   chunks ................................. 4.539 em 40 documentos
--   estrutural (id|doc|ordem|md5(conteudo)) . 90c41e57140a984909bbd86547d72d50
--   conteúdo (md5 dos textos) ............... 226d8ce165b98cacf00b995756fe5956
--   com embedding legado ................... 2.978
-- ============================================================

create table if not exists public.chunks_referencia_bkp_20260811 as
  select * from public.chunks_referencia;

create table if not exists public.documentos_referencia_bkp_20260811 as
  select * from public.documentos_referencia;

comment on table public.chunks_referencia_bkp_20260811 is
  'Backup pré-reindexação V2 (11/08/2026). Somente leitura: base do '
  'rollback. Não excluir antes do smoke test + merge + estabilização.';
comment on table public.documentos_referencia_bkp_20260811 is
  'Backup pré-reindexação V2 (11/08/2026) — catálogo e tenant.';
