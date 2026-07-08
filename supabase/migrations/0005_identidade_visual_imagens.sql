-- ============================================================
-- Identidade visual por imagem: cabeçalho, rodapé e marca d'água
-- capturados de um documento-modelo (PDF/DOCX) e armazenados como
-- PNG em base64. As colunas de texto (0004) permanecem como fallback.
--
-- Script idempotente. Aplicar no SQL Editor do Supabase.
-- ============================================================

alter table public.config_orgaos
  add column if not exists cabecalho_img text not null default '',
  add column if not exists rodape_img text not null default '',
  add column if not exists marca_img text not null default '',
  add column if not exists cabecalho_pct real not null default 14,
  add column if not exists rodape_pct real not null default 10;
