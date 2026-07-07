-- Já aplicada no projeto Supabase govdocs-wizard (via MCP em 2026-07-06).
-- Versionada aqui para reprodutibilidade em novos ambientes.

create table public.processos (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  orgao text not null default '',
  objeto text not null default '',
  etapa int not null default 0,
  dados jsonb not null default '{}'::jsonb,
  documentos jsonb not null default '{}'::jsonb,
  aprovados text[] not null default '{}'
);

comment on table public.processos is
  'Processos de contratação: formulário matriz, documentos gerados (DFD/ETP/TR/Edital), aprovações e etapa do wizard.';

create index processos_atualizado_em_idx on public.processos (atualizado_em desc);

create or replace function public.set_atualizado_em()
returns trigger
language plpgsql
security invoker set search_path = ''
as $$
begin
  new.atualizado_em = now();
  return new;
end;
$$;

revoke execute on function public.set_atualizado_em() from public, anon, authenticated;

create trigger trg_processos_atualizado
before update on public.processos
for each row execute function public.set_atualizado_em();

alter table public.processos enable row level security;

create policy "anon_select" on public.processos for select to anon using (true);
create policy "anon_insert" on public.processos for insert to anon with check (true);
create policy "anon_update" on public.processos for update to anon using (true) with check (true);
create policy "anon_delete" on public.processos for delete to anon using (true);
