-- ============================================================
-- Base de Conhecimento (RAG) — GovDocs Wizard
--
-- Armazena documentos de referência (leis, acórdãos, entendimentos
-- dos Tribunais de Contas, processos anteriores, modelos) divididos
-- em trechos (chunks) com embeddings vetoriais (pgvector) e índice
-- de busca textual em português (fallback sem embeddings).
--
-- Script idempotente: pode ser executado mais de uma vez sem erro.
-- Obs.: dentro das funções o search_path é vazio (hardening), por isso
-- o operador de distância do pgvector é qualificado: operator(public.<=>).
-- ============================================================

create extension if not exists vector;

-- Documentos de referência enviados pelo usuário
create table if not exists public.documentos_referencia (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  titulo text not null,
  categoria text not null check (categoria in
    ('lei', 'acordao', 'entendimento', 'processo_anterior', 'modelo', 'outro')),
  nome_arquivo text not null default '',
  total_chunks int not null default 0
);

comment on table public.documentos_referencia is
  'Biblioteca RAG: leis, acórdãos, entendimentos de TCs, processos anteriores e modelos usados para fundamentar a geração dos documentos.';

-- Trechos (chunks) com embedding (Gemini, 768 dims) e tsvector português
create table if not exists public.chunks_referencia (
  id bigint generated always as identity primary key,
  documento_id uuid not null references public.documentos_referencia (id) on delete cascade,
  ordem int not null default 0,
  conteudo text not null,
  embedding public.vector(768),
  tsv tsvector generated always as (to_tsvector('portuguese', conteudo)) stored
);

create index if not exists chunks_referencia_documento_idx
  on public.chunks_referencia (documento_id);
create index if not exists chunks_referencia_tsv_idx
  on public.chunks_referencia using gin (tsv);
create index if not exists chunks_referencia_embedding_idx
  on public.chunks_referencia using hnsw (embedding public.vector_cosine_ops);

-- Busca vetorial (chamada via RPC pela aplicação)
create or replace function public.buscar_chunks_vetorial(
  query_embedding public.vector(768),
  qtd int default 6
)
returns table (
  conteudo text,
  titulo text,
  categoria text,
  similaridade float
)
language sql
stable
security invoker
set search_path = ''
as $$
  select c.conteudo, d.titulo, d.categoria,
         1 - (c.embedding operator(public.<=>) query_embedding) as similaridade
  from public.chunks_referencia c
  join public.documentos_referencia d on d.id = c.documento_id
  where c.embedding is not null
  order by c.embedding operator(public.<=>) query_embedding
  limit qtd;
$$;

-- Busca textual em português (fallback quando não há embeddings)
create or replace function public.buscar_chunks_textual(
  consulta text,
  qtd int default 6
)
returns table (
  conteudo text,
  titulo text,
  categoria text,
  similaridade float
)
language sql
stable
security invoker
set search_path = ''
as $$
  select c.conteudo, d.titulo, d.categoria,
         ts_rank(c.tsv, websearch_to_tsquery('portuguese', consulta))::float as similaridade
  from public.chunks_referencia c
  join public.documentos_referencia d on d.id = c.documento_id
  where c.tsv @@ websearch_to_tsquery('portuguese', consulta)
  order by similaridade desc
  limit qtd;
$$;

-- RLS: mesmo modelo da tabela processos (ferramenta interna de tenant
-- único usando a chave publishable/anon; ver observação no README)
alter table public.documentos_referencia enable row level security;
alter table public.chunks_referencia enable row level security;

drop policy if exists "anon_select" on public.documentos_referencia;
drop policy if exists "anon_insert" on public.documentos_referencia;
drop policy if exists "anon_update" on public.documentos_referencia;
drop policy if exists "anon_delete" on public.documentos_referencia;

create policy "anon_select" on public.documentos_referencia for select to anon using (true);
create policy "anon_insert" on public.documentos_referencia for insert to anon with check (true);
create policy "anon_update" on public.documentos_referencia for update to anon using (true) with check (true);
create policy "anon_delete" on public.documentos_referencia for delete to anon using (true);

drop policy if exists "anon_select" on public.chunks_referencia;
drop policy if exists "anon_insert" on public.chunks_referencia;
drop policy if exists "anon_delete" on public.chunks_referencia;

create policy "anon_select" on public.chunks_referencia for select to anon using (true);
create policy "anon_insert" on public.chunks_referencia for insert to anon with check (true);
create policy "anon_delete" on public.chunks_referencia for delete to anon using (true);
