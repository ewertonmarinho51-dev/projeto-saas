-- ## 0045 — Fila durável do importador nacional do PNCP (tarefas com lease)
-- ## ESTADO: aplicável; NÃO aplicada em produção (13/11/2026).
-- ## ENSAIO: CI (`tests/test_migracao_0045.py`, PostgreSQL).
--
-- O PROBLEMA (13/11/2026)
--   O índice da 0042 é alimentado por um laço que lê PA, pregões (6/7) e
--   120 dias, e pega "pendentes" por SELECT … ORDER BY … LIMIT. Isso não
--   escala para o Brasil (medido: ~118 mil contratações publicadas só em
--   outubro de 2026) e não prova reserva exclusiva: dois processos podem
--   pegar a mesma contratação, e uma queda no meio não deixa rastro do que
--   faltou. O pedido é carga nacional contínua, com o recente primeiro e o
--   histórico atrás, sem a tarefa depender da aba do Terminal.
--
-- O QUE FAZ
--   * `precos_pncp_tarefas` — uma linha por PARTIÇÃO de trabalho (um dia de
--     resultados do Compras.gov em lote; uma janela de publicação do PNCP;
--     uma contratação a ler item a item), com faixa (recente, atualização,
--     histórico, urgente), prioridade, estado, tentativas, próxima tentativa,
--     checkpoint (página/item onde parou) e totais medidos;
--   * lease com token de posse: `precos_pncp_reservar` entrega tarefas com
--     FOR UPDATE SKIP LOCKED (dois processos nunca recebem a mesma), e só
--     quem tem o token confirma (`precos_pncp_concluir`) ou renova
--     (`precos_pncp_renovar`). Lease vencido volta à fila sozinho;
--   * `precos_pncp_controle` — linha única: pausa global (com motivo),
--     orçamento de requisições por segundo e o LÍDER (`precos_pncp_liderar`):
--     um processo só escreve de cada vez, e o indexador antigo não convive
--     com o novo sem coordenação.
--
-- DECISÕES
--   * só a credencial de servidor: RLS ligado, nenhuma política, nada para
--     `anon`/`authenticated`; as RPCs têm EXECUTE revogado de PUBLIC (o
--     padrão do PostgreSQL concede a todos) e concedido só a `service_role`;
--   * as RPCs são SECURITY INVOKER: rodam com os privilégios de quem chama;
--   * sem DELETE nas duas tabelas: a fila é também a contabilidade da
--     cobertura (o que foi lido, o que falhou, o que ficou em quarentena).
--     Tarefa errada se corrige por UPDATE de estado, nunca some;
--   * pausa vale para a reserva: com `pausado`, `reservar` não entrega nada
--     e o trabalho em curso termina a transação em que está;
--   * `concluida` é FINAL e não volta à fila. O que precisa ser relido
--     (resultado tardio, cancelamento) é confirmado como `pendente` com
--     `proxima_em` futuro e `checkpoint.lido_em` — a leitura feita fica
--     registrada e a revisita entra pela mesma reserva (revisão do
--     `revisor-de-banco-e-seguranca`, 13/11/2026).
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * não importa nada: o serviço (`pncp_integral`) precisa rodar;
--   * o limite de requisições é aplicado pelo processo líder; um processo
--     que ignore a liderança e chame o PNCP por conta própria não é contido
--     pelo banco;
--   * a política `using (true)` dos resultados da 0042 segue como está.

create table if not exists public.precos_pncp_tarefas (
  id bigint generated always as identity primary key,
  campanha text not null check (char_length(campanha) between 3 and 80),
  fonte text not null check (fonte in
    ('comprasgov_lote', 'pncp_descoberta', 'pncp_contratacao')),
  particao text not null check (char_length(particao) between 1 and 200),
  faixa text not null default 'recente' check (faixa in
    ('recente', 'atualizacao', 'historico', 'urgente')),
  prioridade integer not null default 100,
  estado text not null default 'pendente' check (estado in
    ('pendente', 'em_execucao', 'concluida', 'parcial', 'falha', 'quarentena')),
  tentativas integer not null default 0,
  proxima_em timestamptz not null default now(),
  dono text,
  token uuid,
  lease_ate timestamptz,
  checkpoint jsonb not null default '{}'::jsonb,
  totais jsonb not null default '{}'::jsonb,
  erro text not null default '',
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  unique (campanha, fonte, particao)
);

create index if not exists precos_pncp_tarefas_fila_idx
  on public.precos_pncp_tarefas (prioridade, proxima_em, id)
  where estado in ('pendente', 'parcial', 'em_execucao');
create index if not exists precos_pncp_tarefas_resumo_idx
  on public.precos_pncp_tarefas (campanha, fonte, estado);

create table if not exists public.precos_pncp_controle (
  id smallint primary key default 1 check (id = 1),
  pausado boolean not null default false,
  motivo_pausa text not null default '',
  req_por_s numeric(6, 2) not null default 1 check (req_por_s > 0 and req_por_s <= 20),
  lider text,
  lider_ate timestamptz,
  atualizado_em timestamptz not null default now()
);
insert into public.precos_pncp_controle (id) values (1) on conflict (id) do nothing;

alter table public.precos_pncp_tarefas enable row level security;
alter table public.precos_pncp_controle enable row level security;
revoke all on public.precos_pncp_tarefas from anon, authenticated, public;
revoke all on public.precos_pncp_controle from anon, authenticated, public;
-- a sequência da identidade herdaria o default ACL de sequências
revoke all on sequence public.precos_pncp_tarefas_id_seq from anon, authenticated, public;
grant select, insert, update on public.precos_pncp_tarefas to service_role;
grant select, update on public.precos_pncp_controle to service_role;
revoke delete, truncate, references, trigger on public.precos_pncp_tarefas from service_role;
revoke insert, delete, truncate, references, trigger on public.precos_pncp_controle from service_role;
do $$
begin
  if current_setting('server_version_num')::int >= 170000 then
    execute 'revoke maintain on public.precos_pncp_tarefas from service_role';
    execute 'revoke maintain on public.precos_pncp_controle from service_role';
  end if;
end
$$;

-- Reserva atômica: SKIP LOCKED garante que duas chamadas simultâneas nunca
-- recebem a mesma tarefa; lease vencido é reentregue (outro token).
create or replace function public.precos_pncp_reservar(
  p_dono text, p_fontes text[], p_limite integer, p_lease_s integer)
returns setof public.precos_pncp_tarefas
language sql volatile security invoker set search_path = public
as $$
  with escolhidas as materialized (
    select f.id from public.precos_pncp_tarefas f
     where f.fonte = any (p_fontes)
       and f.proxima_em <= now()
       and (f.estado in ('pendente', 'parcial')
            or (f.estado = 'em_execucao' and f.lease_ate < now()))
       and not coalesce((select c.pausado from public.precos_pncp_controle c where c.id = 1), false)
     order by f.prioridade, f.proxima_em, f.id
     limit greatest(1, least(coalesce(p_limite, 1), 100))
     for update skip locked)
  update public.precos_pncp_tarefas t
     set estado = 'em_execucao', dono = p_dono, token = gen_random_uuid(),
         lease_ate = now() + make_interval(secs => greatest(30, least(coalesce(p_lease_s, 600), 3600))),
         tentativas = t.tentativas + 1, atualizado_em = now()
    from escolhidas e
   where t.id = e.id
  returning t.*;
$$;

create or replace function public.precos_pncp_renovar(
  p_id bigint, p_token uuid, p_lease_s integer)
returns boolean
language sql volatile security invoker set search_path = public
as $$
  with r as (
    update public.precos_pncp_tarefas
       set lease_ate = now() + make_interval(secs => greatest(30, least(p_lease_s, 3600))),
           atualizado_em = now()
     where id = p_id and token = p_token and estado = 'em_execucao'
     returning 1)
  select exists (select 1 from r);
$$;

-- Só o dono do token confirma. Estado final ou volta à fila com checkpoint.
create or replace function public.precos_pncp_concluir(
  p_id bigint, p_token uuid, p_estado text, p_checkpoint jsonb,
  p_totais jsonb, p_erro text, p_proxima_em timestamptz)
returns boolean
language sql volatile security invoker set search_path = public
as $$
  with r as (
    update public.precos_pncp_tarefas
       set estado = p_estado,
           checkpoint = coalesce(p_checkpoint, checkpoint),
           totais = coalesce(p_totais, totais),
           erro = left(coalesce(p_erro, ''), 2000),
           proxima_em = coalesce(p_proxima_em, now()),
           dono = null, token = null, lease_ate = null, atualizado_em = now()
     where id = p_id and token = p_token and estado = 'em_execucao'
       and p_estado in ('pendente', 'concluida', 'parcial', 'falha', 'quarentena')
     returning 1)
  select exists (select 1 from r);
$$;

-- Um líder por vez: quem tem a liderança vigente renova; vencida, outro assume.
create or replace function public.precos_pncp_liderar(p_dono text, p_lease_s integer)
returns boolean
language sql volatile security invoker set search_path = public
as $$
  with r as (
    update public.precos_pncp_controle
       set lider = p_dono,
           lider_ate = now() + make_interval(secs => greatest(30, least(p_lease_s, 3600))),
           atualizado_em = now()
     where id = 1 and (lider is null or lider = p_dono or lider_ate < now())
     returning 1)
  select exists (select 1 from r);
$$;

revoke all on function public.precos_pncp_reservar(text, text[], integer, integer) from public, anon, authenticated;
revoke all on function public.precos_pncp_renovar(bigint, uuid, integer) from public, anon, authenticated;
revoke all on function public.precos_pncp_concluir(bigint, uuid, text, jsonb, jsonb, text, timestamptz) from public, anon, authenticated;
revoke all on function public.precos_pncp_liderar(text, integer) from public, anon, authenticated;
grant execute on function public.precos_pncp_reservar(text, text[], integer, integer) to service_role;
grant execute on function public.precos_pncp_renovar(bigint, uuid, integer) to service_role;
grant execute on function public.precos_pncp_concluir(bigint, uuid, text, jsonb, jsonb, text, timestamptz) to service_role;
grant execute on function public.precos_pncp_liderar(text, integer) to service_role;

notify pgrst, 'reload schema';

do $$
declare
  faltou text := '';
  tabela text;
  funcao text;
begin
  foreach tabela in array array['public.precos_pncp_tarefas', 'public.precos_pncp_controle'] loop
    if not (select relrowsecurity from pg_class where oid = tabela::regclass) then
      faltou := faltou || ' rls_desligado:' || tabela;
    end if;
    if has_any_column_privilege('anon', tabela, 'select, insert, update, references')
       or has_table_privilege('anon', tabela, 'delete, truncate')
       or has_any_column_privilege('authenticated', tabela, 'select, insert, update, references')
       or has_table_privilege('authenticated', tabela, 'delete, truncate') then
      faltou := faltou || ' usuario_alcanca:' || tabela;
    end if;
    if has_table_privilege('service_role', tabela, 'delete, truncate, references, trigger') then
      faltou := faltou || ' service_role_apaga_ou_amarra:' || tabela;
    end if;
    if current_setting('server_version_num')::int >= 170000 then
      if has_table_privilege('service_role', tabela, 'maintain') then
        faltou := faltou || ' service_role_maintain:' || tabela;
      end if;
    end if;
    if exists (select 1 from pg_policies where schemaname = 'public'
                and tablename = split_part(tabela, '.', 2)) then
      faltou := faltou || ' politica_inesperada:' || tabela;
    end if;
  end loop;
  -- um a um: com lista, has_table_privilege é verdadeiro se QUALQUER um
  -- existir (a mutação "revoke update" passava calada — pega no CI)
  if not (has_table_privilege('service_role', 'public.precos_pncp_tarefas', 'select')
          and has_table_privilege('service_role', 'public.precos_pncp_tarefas', 'insert')
          and has_table_privilege('service_role', 'public.precos_pncp_tarefas', 'update')
          and has_table_privilege('service_role', 'public.precos_pncp_controle', 'select')
          and has_table_privilege('service_role', 'public.precos_pncp_controle', 'update')) then
    faltou := faltou || ' service_role_sem_o_necessario';
  end if;
  foreach funcao in array array[
      'public.precos_pncp_reservar(text, text[], integer, integer)',
      'public.precos_pncp_renovar(bigint, uuid, integer)',
      'public.precos_pncp_concluir(bigint, uuid, text, jsonb, jsonb, text, timestamptz)',
      'public.precos_pncp_liderar(text, integer)'] loop
    if has_function_privilege('anon', funcao, 'execute')
       or has_function_privilege('authenticated', funcao, 'execute') then
      faltou := faltou || ' usuario_executa:' || funcao;
    end if;
    if not has_function_privilege('service_role', funcao, 'execute') then
      faltou := faltou || ' servidor_nao_executa:' || funcao;
    end if;
    if (select prosecdef from pg_proc where oid = funcao::regprocedure) then
      faltou := faltou || ' security_definer:' || funcao;
    end if;
    if not exists (select 1 from pg_proc where oid = funcao::regprocedure
                    and 'search_path=public' = any (coalesce(proconfig, '{}'))) then
      faltou := faltou || ' search_path_solto:' || funcao;
    end if;
  end loop;
  if has_sequence_privilege('anon', 'public.precos_pncp_tarefas_id_seq', 'usage, select, update')
     or has_sequence_privilege('authenticated', 'public.precos_pncp_tarefas_id_seq',
                               'usage, select, update') then
    faltou := faltou || ' usuario_alcanca_sequencia';
  end if;
  if (select count(*) from public.precos_pncp_controle) <> 1 then
    faltou := faltou || ' controle_sem_linha_unica';
  end if;
  if faltou <> '' then
    raise exception 'A 0045 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
