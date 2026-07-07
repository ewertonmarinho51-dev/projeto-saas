-- ============================================================
-- Login/papéis, configurações do app e identidade visual por órgão
--
-- usuarios       : contas com hash PBKDF2 e papel (admin | usuario)
-- config_app     : pares chave/valor definidos pelo administrador
--                  (ex.: OPENAI_API_KEY, OPENAI_MODEL, GOOGLE_API_KEY)
-- config_orgaos  : cabeçalho, rodapé e marca d'água por órgão para os
--                  documentos exportados (PDF/DOCX)
-- processos      : ganha usuario_id (dono do processo)
--
-- Script idempotente. Aplicar no SQL Editor do Supabase.
-- ============================================================

create table if not exists public.usuarios (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  nome text not null,
  login text not null unique,
  senha_hash text not null,          -- pbkdf2_sha256$iteracoes$salt$hash
  papel text not null default 'usuario' check (papel in ('admin', 'usuario')),
  ativo boolean not null default true
);

create table if not exists public.config_app (
  chave text primary key,
  valor text not null default '',
  atualizado_em timestamptz not null default now()
);

create table if not exists public.config_orgaos (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  orgao text not null,
  cabecalho text not null default '',
  rodape text not null default '',
  marca_dagua text not null default '',
  padrao boolean not null default false
);

alter table public.processos add column if not exists usuario_id uuid;
create index if not exists processos_usuario_idx on public.processos (usuario_id);

-- RLS: mesmo modelo do restante (papel anon, ferramenta interna).
-- Observação de segurança: qualquer detentor da chave publishable pode
-- ler estas tabelas; os hashes PBKDF2 (200k iterações, salt por usuário)
-- mitigam exposição de senhas. Para endurecer: Supabase Auth + RLS por
-- auth.uid() (documentado no README).
alter table public.usuarios enable row level security;
alter table public.config_app enable row level security;
alter table public.config_orgaos enable row level security;

do $$
declare t text;
begin
  foreach t in array array['usuarios', 'config_app', 'config_orgaos'] loop
    execute format('drop policy if exists "anon_select" on public.%I', t);
    execute format('drop policy if exists "anon_insert" on public.%I', t);
    execute format('drop policy if exists "anon_update" on public.%I', t);
    execute format('drop policy if exists "anon_delete" on public.%I', t);
    execute format('create policy "anon_select" on public.%I for select to anon using (true)', t);
    execute format('create policy "anon_insert" on public.%I for insert to anon with check (true)', t);
    execute format('create policy "anon_update" on public.%I for update to anon using (true) with check (true)', t);
    execute format('create policy "anon_delete" on public.%I for delete to anon using (true)', t);
  end loop;
end $$;
