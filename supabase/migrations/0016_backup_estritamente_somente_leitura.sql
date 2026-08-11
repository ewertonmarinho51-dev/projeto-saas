-- ============================================================
-- 0016 — Backup estritamente SOMENTE LEITURA
--
-- A 0015 tirou anon/authenticated do caminho, mas `service_role` seguia
-- com INSERT/UPDATE/DELETE/TRUNCATE herdados do padrão do schema. Para
-- o rollback basta LER o backup (a escrita ocorre na tabela viva), e um
-- TRUNCATE acidental com a chave de serviço destruiria a rede de
-- segurança. Deixa-se apenas SELECT.
--
-- O owner (`postgres`) mantém controle total — é ele quem removerá os
-- backups na limpeza do legado, depois da estabilização.
-- ============================================================

revoke insert, update, delete, truncate, references, trigger
  on table public.chunks_referencia_bkp_20260811 from service_role;
revoke insert, update, delete, truncate, references, trigger
  on table public.documentos_referencia_bkp_20260811 from service_role;
