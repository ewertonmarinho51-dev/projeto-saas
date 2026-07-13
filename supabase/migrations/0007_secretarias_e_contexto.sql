-- ============================================================
-- 0007 — Secretarias, vínculos e RAG por tenant (Fase 2 da matriz
--         de compatibilidade; exige a 0006 aplicada)
--
-- Estratégia EXPAND (nada é removido; comportamento antigo intacto):
--   1. tabela `secretarias`: evolução de `config_orgaos` — nome/sigla
--      da unidade + identidade visual própria (quando vazia, herda a
--      identidade padrão do município). `config_orgaos` permanece como
--      legado até a fase de contração;
--   2. backfill: cada identidade de `config_orgaos` vira uma secretaria
--      (rastreada por `origem_orgao_id`; reexecução não duplica);
--   3. vínculo institucional: `usuarios.secretaria_id` e
--      `processos.secretaria_id` (nullable — sem vínculo, nada muda);
--   4. RPCs do RAG ganham filtro de tenant. O parâmetro novo tem
--      DEFAULT no tenant padrão, então chamadas antigas (sem ele)
--      continuam funcionando com o mesmo resultado de hoje.
--
-- Com a flag `flag_secretarias` DESLIGADA (config_app) NADA muda no
-- app. Ordem de ativação: aplicar esta migração → cadastrar/vincular
-- no painel Administração → ligar a flag. Rollback = desligar a flag.
-- ============================================================

-- 1. Secretarias do município (tenant)
create table if not exists public.secretarias (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  tenant_id uuid not null
    default '11111111-1111-1111-1111-111111111111'
    references public.tenants (id),
  nome text not null,
  sigla text not null default '',
  ativo boolean not null default true,
  -- identidade visual própria (vazia = herda a identidade padrão do município)
  cabecalho text not null default '',
  rodape text not null default '',
  marca_dagua text not null default '',
  cabecalho_img text not null default '',
  rodape_img text not null default '',
  marca_img text not null default '',
  cabecalho_pct real not null default 14,
  rodape_pct real not null default 10,
  -- padrao=true marca a identidade PADRÃO do município (base da herança)
  padrao boolean not null default false,
  -- rastreio do backfill/espelhamento a partir de config_orgaos (legado)
  origem_orgao_id uuid,
  unique (tenant_id, nome)
);

create index if not exists secretarias_tenant_idx
  on public.secretarias (tenant_id, ativo);

-- 2. Backfill: identidades já cadastradas viram secretarias
insert into public.secretarias
  (tenant_id, nome, cabecalho, rodape, marca_dagua, cabecalho_img,
   rodape_img, marca_img, cabecalho_pct, rodape_pct, padrao, origem_orgao_id)
select o.tenant_id, o.orgao, o.cabecalho, o.rodape, o.marca_dagua,
       o.cabecalho_img, o.rodape_img, o.marca_img, o.cabecalho_pct,
       o.rodape_pct, o.padrao, o.id
from public.config_orgaos o
where not exists (
  select 1 from public.secretarias s where s.origem_orgao_id = o.id
)
on conflict (tenant_id, nome) do nothing;

-- 3. Vínculos institucionais (nullable: expand sem quebrar o legado)
alter table public.usuarios
  add column if not exists secretaria_id uuid references public.secretarias (id);

alter table public.processos
  add column if not exists secretaria_id uuid references public.secretarias (id);

create index if not exists processos_secretaria_idx
  on public.processos (secretaria_id);

-- 4. RLS: mesmo modelo do restante (papel anon, tenant único em produção).
--    O fechamento por tenant via auth.uid()/JWT acontece com a migração
--    para Supabase Auth (decisão pendente do proprietário — ver matriz).
alter table public.secretarias enable row level security;

drop policy if exists "anon_select" on public.secretarias;
drop policy if exists "anon_insert" on public.secretarias;
drop policy if exists "anon_update" on public.secretarias;
drop policy if exists "anon_delete" on public.secretarias;

create policy "anon_select" on public.secretarias for select to anon using (true);
create policy "anon_insert" on public.secretarias for insert to anon with check (true);
create policy "anon_update" on public.secretarias for update to anon using (true) with check (true);
create policy "anon_delete" on public.secretarias for delete to anon using (true);

-- 5. RAG restrito ao tenant. DROP + CREATE com parâmetro novo (com
--    DEFAULT) em vez de sobrecarga: duas assinaturas coexistindo tornam
--    a chamada de 2 argumentos ambígua para o PostgREST.
drop function if exists public.buscar_chunks_vetorial(public.vector, int);

create or replace function public.buscar_chunks_vetorial(
  query_embedding public.vector(768),
  qtd int default 6,
  tenant uuid default '11111111-1111-1111-1111-111111111111'
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
    and d.tenant_id = tenant
  order by c.embedding operator(public.<=>) query_embedding
  limit qtd;
$$;

drop function if exists public.buscar_chunks_textual(text, int);

create or replace function public.buscar_chunks_textual(
  consulta text,
  qtd int default 6,
  tenant uuid default '11111111-1111-1111-1111-111111111111'
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
    and d.tenant_id = tenant
  order by similaridade desc
  limit qtd;
$$;
