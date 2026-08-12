-- ============================================================
-- 0011 — Rastro do RAG na geração (P1)
--
-- Responde "por que o sistema citou este artigo?": guarda, por geração,
-- as consultas/temas enviados à base de conhecimento e as fontes
-- efetivamente recuperadas (título, categoria, score, documento/ordem e
-- um trecho curto). NÃO guarda chave de API nem o documento gerado.
--
-- Expand-only e idempotente: apenas acrescenta uma coluna opcional à
-- tabela `geracoes` (migração 0006). Nenhuma coluna é removida ou
-- alterada e nenhum dado existente é tocado — versões anteriores da
-- aplicação continuam gravando normalmente (o campo fica '{}').
-- ============================================================

alter table public.geracoes
  add column if not exists rag_trace jsonb not null default '{}'::jsonb;

comment on column public.geracoes.rag_trace is
  'Rastro do RAG: {modo, piso, consultas[], referencias[]} — '
  'identificação das fontes recuperadas para auditoria da fundamentação. '
  'Nunca contém segredos nem o conteúdo integral dos documentos.';

-- Consulta típica da auditoria: gerações COM rastro, por tenant/data.
create index if not exists geracoes_rag_trace_idx
  on public.geracoes (tenant_id, criado_em desc)
  where rag_trace <> '{}'::jsonb;
