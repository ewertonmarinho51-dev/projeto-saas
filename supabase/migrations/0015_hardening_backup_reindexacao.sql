-- ============================================================
-- 0015 — Blindagem das tabelas de backup da reindexação V2
--
-- A 0012 criou os backups com CREATE TABLE AS. O comentário dizia
-- "somente leitura", mas isso não era garantido pelo banco: as tabelas
-- nasceram SEM RLS e com os privilégios padrão do schema `public`, ou
-- seja, `anon` e `authenticated` tinham SELECT, INSERT, UPDATE, DELETE e
-- TRUNCATE — pela API do PostgREST, qualquer portador da chave anônima
-- poderia LER ou APAGAR a rede de rollback.
--
-- Esta migração revoga esses privilégios e habilita RLS sem políticas
-- (defesa em profundidade: mesmo que um GRANT reapareça, nenhuma linha
-- fica visível para os papéis da aplicação). O acesso administrativo
-- para o rollback permanece com `service_role` e com o owner `postgres`.
--
-- Os DADOS não são tocados: nenhuma linha é lida, alterada ou removida.
-- ============================================================

revoke all privileges on table public.chunks_referencia_bkp_20260811
  from anon, authenticated, public;
revoke all privileges on table public.documentos_referencia_bkp_20260811
  from anon, authenticated, public;

alter table public.chunks_referencia_bkp_20260811 enable row level security;
alter table public.documentos_referencia_bkp_20260811 enable row level security;

grant select on table public.chunks_referencia_bkp_20260811 to service_role;
grant select on table public.documentos_referencia_bkp_20260811 to service_role;

comment on table public.chunks_referencia_bkp_20260811 is
  'Backup pré-reindexação V2 (11/08/2026). SOMENTE LEITURA e SOMENTE '
  'administrativo: RLS habilitada sem políticas; anon/authenticated sem '
  'qualquer privilégio (0015). Base do rollback — não excluir antes do '
  'smoke test + merge + estabilização.';
comment on table public.documentos_referencia_bkp_20260811 is
  'Backup pré-reindexação V2 (11/08/2026) — catálogo e tenant. Mesmo '
  'regime de proteção do backup de chunks (0015).';
