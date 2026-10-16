-- ## 0029 — Cotações unificadas (Minhas Cotações → Elaborar Cotação)
-- ## ESTADO: APLICADA EM PRODUÇÃO em 16/10/2026, por autorização expressa
-- ##   do operador, como `m0029_cotacoes_unificadas` (projeto
-- ##   nxibohgoekphxblqtqku). Antes, ensaiada no projeto descartável
-- ##   `govdocs-ensaio-descartavel` com o mesmo nome.
-- ## Rollback: `docs/cotacoes/0029_rollback.sql`.
--
-- REGISTRO DA APLICAÇÃO (16/10/2026):
--   * ensaio: conferência aprovada; mutação (DELETE ao service_role e
--     UPDATE ao authenticated na tabela nova) REPROVADA pela conferência,
--     nomeando os dois; UPDATE na emissão recusado com 42501 até para o
--     dono; UF 'ZZ' recusada pelo CHECK. Linha de ensaio deixada no
--     projeto descartável (append-only impede apagá-la);
--   * produção, ANTES e DEPOIS: grants das quatro tabelas da 0021
--     idênticos; linhas idênticas (2 pesquisas, 215 itens, 1.610
--     referências, 2.491 eventos); 215 itens com revisao = 1 e colunas
--     novas vazias; emissões com SELECT/INSERT a authenticated e sem
--     DELETE/TRUNCATE ao service_role; advisor de segurança sem achado
--     novo;
--   * nível 1 do ensaio (PostgreSQL local) NÃO executado: não há
--     PostgreSQL nesta máquina;
--   * depois da aplicação, `flag_unified_quotations` = 'on'. A
--     `flag_jev_price_research` já estava '1' em produção.
-- ===============================================================
--
-- AUDITORIA ANTES DE ESCREVER (produção, 16/10/2026, catálogo):
--   * migração roda como `postgres`; o `pg_default_acl` dele concede a
--     `service_role` `arwdxtm` em tabela nova — DELETE incluído. A
--     tabela nova revoga `delete, truncate` de `service_role` aqui
--     mesmo, e a conferência no fim mede;
--   * eventos em uso: pesquisa_criada, busca_iniciada, busca_concluida,
--     pesquisa_arquivada (2.491 linhas) — todos no CHECK novo;
--   * CHECK atual: `pesquisa_preco_eventos_tipo_check` (nome confere).
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE: o default de `postgres` continua
-- concedendo DELETE ao `service_role` na PRÓXIMA tabela que alguém
-- criar — é a "fábrica" que a 0024 apontou. Estreitar o
-- `pg_default_acl` é decisão de schema inteiro, fora do escopo de uma
-- migração de funcionalidade; fica registrado para a próxima de
-- contenção.
--
-- ADITIVA. Nada é apagado, renomeado ou reescrito; nenhuma linha
-- existente muda de valor. O que entra:
--
--   1. `pesquisa_preco_itens`: `revisao` (controle otimista entre abas —
--      pacote U07), `lote` e `uf` (importação validada — dossiê BP J05)
--      e `removido_em` (retirar item da cotação sem apagar a evidência:
--      a 0021 não concede DELETE a ninguém, de propósito);
--   2. tipos novos de evento na trilha: exceção à regra dos três,
--      emissão de relatório, registro de busca, item editado/removido e
--      sugestão de seleção;
--   3. `pesquisa_preco_emissoes`: o REGISTRO de cada relatório emitido
--      (quem, quando, hash do conteúdo decisório e do arquivo, lista de
--      pendências impressas). Append-only como a trilha;
--   4. `revisar_pesquisa_preco` passa a copiar `lote`, `uf` e
--      `removido_em` para a revisão nova;
--   5. a flag `flag_unified_quotations`, DESLIGADA.
--
-- Mesmo modelo de segurança da 0021: só `authenticated`, RLS por
-- `pode_ler_pesquisa_preco`/`pode_escrever_pesquisa_preco`, `anon` sem
-- grant, `service_role` sem DELETE/TRUNCATE, gatilhos que valem até para
-- quem atravessa o RLS.
-- ===============================================================

-- ---------------------------------------------------------------
-- 1. Itens
-- ---------------------------------------------------------------
alter table public.pesquisa_preco_itens
  add column if not exists revisao integer not null default 1;
alter table public.pesquisa_preco_itens
  add column if not exists lote text;
alter table public.pesquisa_preco_itens
  add column if not exists uf text;
alter table public.pesquisa_preco_itens
  add column if not exists removido_em timestamptz;

do $$
begin
  if not exists (select 1 from pg_constraint
                 where conname = 'pesquisa_preco_itens_revisao_positiva') then
    alter table public.pesquisa_preco_itens
      add constraint pesquisa_preco_itens_revisao_positiva
      check (revisao >= 1);
  end if;
  -- UF: as 27 siglas, e nada mais (o BP aceitou "ZZ" — J05).
  if not exists (select 1 from pg_constraint
                 where conname = 'pesquisa_preco_itens_uf_valida') then
    alter table public.pesquisa_preco_itens
      add constraint pesquisa_preco_itens_uf_valida
      check (uf is null or uf in (
        'AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG',
        'PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE',
        'TO'));
  end if;
end $$;

-- ---------------------------------------------------------------
-- 2. Tipos de evento
--
-- O CHECK da 0021 foi declarado na coluna; o nome gerado pelo
-- PostgreSQL é `<tabela>_<coluna>_check`. Recriado com os tipos
-- antigos INTACTOS mais os novos — nenhum evento existente fica
-- inválido.
-- ---------------------------------------------------------------
alter table public.pesquisa_preco_eventos
  drop constraint if exists pesquisa_preco_eventos_tipo_check;
alter table public.pesquisa_preco_eventos
  add constraint pesquisa_preco_eventos_tipo_check
  check (tipo in ('pesquisa_criada', 'pesquisa_revisada',
                  'busca_iniciada', 'busca_concluida', 'busca_falhou',
                  'referencia_incluida', 'referencia_excluida',
                  'metodo_alterado', 'preco_arbitrado',
                  'item_concluido', 'item_incompleto',
                  'pesquisa_concluida', 'pesquisa_aplicada',
                  'pesquisa_arquivada',
                  -- 0029
                  'excecao_registrada', 'relatorio_emitido',
                  'busca_registrada', 'item_editado', 'item_removido',
                  'selecao_sugerida'));

-- ---------------------------------------------------------------
-- 3. Registro de emissão
-- ---------------------------------------------------------------
create table if not exists public.pesquisa_preco_emissoes (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  pesquisa_id uuid not null
    references public.pesquisas_preco (id) on delete cascade,
  tenant_id uuid not null references public.tenants (id),
  emitido_por uuid,
  versao_pesquisa integer not null default 1,
  tipo text not null
    check (tipo in ('completo', 'resumido', 'analitico', 'pacote')),
  formato text not null check (formato in ('pdf', 'docx', 'xlsx', 'zip')),
  formato_hash text not null default '2',
  hash_decisorio text not null check (hash_decisorio ~ '^[0-9a-f]{64}$'),
  hash_arquivo text not null check (hash_arquivo ~ '^[0-9a-f]{64}$'),
  tamanho_bytes integer not null check (tamanho_bytes >= 0),
  nome_arquivo text not null default '',
  pendencias jsonb not null default '[]'::jsonb,
  idempotency_key text not null default ''
);

create index if not exists pesquisa_preco_emissoes_pesquisa_idx
  on public.pesquisa_preco_emissoes (pesquisa_id, criado_em desc);
create index if not exists pesquisa_preco_emissoes_hash_idx
  on public.pesquisa_preco_emissoes (hash_decisorio);
create unique index if not exists pesquisa_preco_emissoes_idempotencia
  on public.pesquisa_preco_emissoes (pesquisa_id, idempotency_key)
  where idempotency_key <> '';

alter table public.pesquisa_preco_emissoes enable row level security;
alter table public.pesquisa_preco_emissoes force row level security;
revoke all on public.pesquisa_preco_emissoes from anon, authenticated, public;
revoke delete, truncate on public.pesquisa_preco_emissoes from service_role;

drop policy if exists "pesquisa_preco_emissoes_le"
  on public.pesquisa_preco_emissoes;
create policy "pesquisa_preco_emissoes_le" on public.pesquisa_preco_emissoes
  for select to authenticated
  using (exists (select 1 from public.pesquisas_preco s
                 where s.id = pesquisa_preco_emissoes.pesquisa_id
                   and public.pode_ler_pesquisa_preco(
                         s.tenant_id, s.secretaria_id, s.auth_user_id)));

-- Emite quem LÊ a pesquisa (o colega da pasta pode imprimir), mas o
-- registro sai com o tenant da pesquisa e o emissor carimbado.
drop policy if exists "pesquisa_preco_emissoes_insere"
  on public.pesquisa_preco_emissoes;
create policy "pesquisa_preco_emissoes_insere" on public.pesquisa_preco_emissoes
  for insert to authenticated
  with check (
    tenant_id = public.tenant_do_jwt()
    and exists (select 1 from public.pesquisas_preco s
                where s.id = pesquisa_preco_emissoes.pesquisa_id
                  and s.tenant_id = pesquisa_preco_emissoes.tenant_id
                  and public.pode_ler_pesquisa_preco(
                        s.tenant_id, s.secretaria_id, s.auth_user_id)));

grant select, insert on public.pesquisa_preco_emissoes to authenticated;

create or replace function public.trg_pesquisa_preco_emissor()
returns trigger language plpgsql
set search_path = ''
as $$
begin
  if auth.uid() is not null then
    if new.emitido_por is null then
      new.emitido_por := auth.uid();
    elsif new.emitido_por <> auth.uid() then
      raise exception 'emissor não confere com o usuário autenticado'
        using errcode = '42501';
    end if;
  end if;
  return new;
end $$;

revoke all on function public.trg_pesquisa_preco_emissor() from public, anon;

drop trigger if exists pesquisa_preco_emissor on public.pesquisa_preco_emissoes;
create trigger pesquisa_preco_emissor
  before insert on public.pesquisa_preco_emissoes
  for each row execute function public.trg_pesquisa_preco_emissor();

-- Append-only até para quem atravessa o RLS (mesma função da trilha).
drop trigger if exists pesquisa_preco_emissoes_imutavel
  on public.pesquisa_preco_emissoes;
create trigger pesquisa_preco_emissoes_imutavel
  before update or delete on public.pesquisa_preco_emissoes
  for each row execute function public.trg_pesquisa_preco_trilha_imutavel();

-- ---------------------------------------------------------------
-- 4. Revisão copia as colunas novas
-- ---------------------------------------------------------------
create or replace function public.revisar_pesquisa_preco(
  p_pesquisa uuid, p_motivo text default '')
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_origem public.pesquisas_preco%rowtype;
  v_raiz uuid;
  v_proxima integer;
  v_nova uuid;
begin
  select * into v_origem
    from public.pesquisas_preco where id = p_pesquisa;

  if v_origem.id is null
     or not public.pode_escrever_pesquisa_preco(
              v_origem.tenant_id, v_origem.auth_user_id) then
    raise exception 'pesquisa de preços não encontrada ou fora do escopo'
      using errcode = '42501';
  end if;

  if v_origem.estado = 'archived' then
    raise exception 'pesquisa arquivada não admite revisão'
      using errcode = '42501';
  end if;

  v_raiz := coalesce(v_origem.raiz_id, v_origem.id);

  select coalesce(max(versao), 0) + 1 into v_proxima
    from public.pesquisas_preco where coalesce(raiz_id, id) = v_raiz;

  insert into public.pesquisas_preco (
    tenant_id, secretaria_id, auth_user_id, processo_id,
    nome, objeto, responsavel, local_referencia, data_base,
    perfil_normativo, estado, filtros, valor_global,
    versao_algoritmo, versao_regras, modelo_ia,
    versao, revisao_de, raiz_id, motivo_da_revisao)
  values (
    v_origem.tenant_id, v_origem.secretaria_id, v_origem.auth_user_id,
    v_origem.processo_id,
    v_origem.nome, v_origem.objeto, v_origem.responsavel,
    v_origem.local_referencia, v_origem.data_base,
    v_origem.perfil_normativo,
    'review',
    v_origem.filtros, v_origem.valor_global,
    v_origem.versao_algoritmo, v_origem.versao_regras, v_origem.modelo_ia,
    v_proxima, v_origem.id, v_raiz, coalesce(p_motivo, ''))
  returning id into v_nova;

  insert into public.pesquisa_preco_itens (
    pesquisa_id, tenant_id, numero, codigo, tipo_catalogo, descricao,
    unidade, quantidade, estado, metodo, preco_estimado, preco_total,
    estatisticas, justificativa, ocorrencias, desfechos, erro,
    lote, uf, removido_em)
  select v_nova, i.tenant_id, i.numero, i.codigo, i.tipo_catalogo,
         i.descricao, i.unidade, i.quantidade, i.estado, i.metodo,
         i.preco_estimado, i.preco_total, i.estatisticas, i.justificativa,
         i.ocorrencias, i.desfechos, i.erro,
         i.lote, i.uf, i.removido_em
    from public.pesquisa_preco_itens i
   where i.pesquisa_id = p_pesquisa;

  insert into public.pesquisa_preco_referencias (
    item_id, tenant_id, fonte_id, fonte_nome, fonte_tipo, id_externo,
    referencia_externa, raw_hash, descricao_original, unidade_original,
    quantidade_original, valor_unitario_original, capacidade_embalagem,
    unidade_normalizada, valor_unitario_normalizado, natureza_valor,
    codigo_catalogo,
    tipo_catalogo, orgao, uf, municipio, fornecedor, ni_fornecedor,
    marca, data_compra, data_resultado, score, identidade, circunstancias,
    fatores, status, motivos, bruto, coletado_em)
  select novo.id, r.tenant_id, r.fonte_id, r.fonte_nome, r.fonte_tipo,
         r.id_externo, r.referencia_externa, r.raw_hash,
         r.descricao_original, r.unidade_original, r.quantidade_original,
         r.valor_unitario_original, r.capacidade_embalagem,
         r.unidade_normalizada, r.valor_unitario_normalizado,
         r.natureza_valor,
         r.codigo_catalogo, r.tipo_catalogo, r.orgao, r.uf, r.municipio,
         r.fornecedor, r.ni_fornecedor, r.marca, r.data_compra,
         r.data_resultado, r.score, r.identidade, r.circunstancias,
         r.fatores, r.status, r.motivos, r.bruto, r.coletado_em
    from public.pesquisa_preco_referencias r
    join public.pesquisa_preco_itens antigo on antigo.id = r.item_id
    join public.pesquisa_preco_itens novo
      on novo.pesquisa_id = v_nova and novo.numero = antigo.numero
   where antigo.pesquisa_id = p_pesquisa;

  insert into public.pesquisa_preco_eventos (
    pesquisa_id, tenant_id, ator, tipo, descricao, payload)
  values (v_nova, v_origem.tenant_id, auth.uid(), 'pesquisa_revisada',
          coalesce(p_motivo, ''),
          jsonb_build_object('origem', p_pesquisa,
                             'versao', v_proxima,
                             'raiz', v_raiz));

  return v_nova;
end $$;

revoke all on function public.revisar_pesquisa_preco(uuid, text)
  from public, anon;
grant execute on function public.revisar_pesquisa_preco(uuid, text)
  to authenticated, service_role;

-- ---------------------------------------------------------------
-- 5. Flag — DESLIGADA
-- ---------------------------------------------------------------
insert into public.config_app (chave, valor)
values ('flag_unified_quotations', 'off')
on conflict (chave) do nothing;

-- ---------------------------------------------------------------
-- 6. Conferência que falha sozinha
--
-- Um `revoke` que não pega não levanta erro. Cada afirmação acima é
-- medida aqui no catálogo; qualquer divergência aborta a migração
-- inteira (a transação desfaz tudo).
-- ---------------------------------------------------------------
do $$
declare
  faltou text := '';
  n integer;
begin
  select count(*) into n from information_schema.columns
   where table_schema = 'public' and table_name = 'pesquisa_preco_itens'
     and column_name in ('revisao', 'lote', 'uf', 'removido_em');
  if n <> 4 then faltou := faltou || ' colunas_do_item=' || n; end if;

  if not exists (select 1 from pg_class
                  where oid = 'public.pesquisa_preco_emissoes'::regclass
                    and relrowsecurity and relforcerowsecurity) then
    faltou := faltou || ' rls_emissoes';
  end if;

  select count(*) into n from information_schema.role_table_grants
   where table_schema = 'public' and table_name = 'pesquisa_preco_emissoes'
     and grantee in ('anon', 'PUBLIC', 'public');
  if n > 0 then faltou := faltou || ' grant_anon_ou_public=' || n; end if;

  select count(*) into n from information_schema.role_table_grants
   where table_schema = 'public' and table_name = 'pesquisa_preco_emissoes'
     and grantee = 'authenticated'
     and privilege_type not in ('SELECT', 'INSERT');
  if n > 0 then faltou := faltou || ' authenticated_alem_de_select_insert=' || n; end if;

  select count(*) into n from information_schema.role_table_grants
   where table_schema = 'public' and table_name = 'pesquisa_preco_emissoes'
     and grantee = 'service_role' and privilege_type in ('DELETE', 'TRUNCATE');
  if n > 0 then faltou := faltou || ' service_role_delete_truncate=' || n; end if;

  select count(*) into n from pg_trigger
   where tgrelid = 'public.pesquisa_preco_emissoes'::regclass
     and tgname in ('pesquisa_preco_emissor', 'pesquisa_preco_emissoes_imutavel')
     and not tgisinternal;
  if n <> 2 then faltou := faltou || ' gatilhos_emissoes=' || n; end if;

  select count(*) into n from pg_policies
   where schemaname = 'public' and tablename = 'pesquisa_preco_emissoes'
     and (coalesce(qual, '') ilike '%true%' and length(coalesce(qual, '')) < 10);
  if n > 0 then faltou := faltou || ' politica_irrestrita=' || n; end if;

  -- nenhum evento existente ficou fora do CHECK novo (o add constraint
  -- já validaria, mas a afirmação vai escrita)
  select count(*) into n from public.pesquisa_preco_eventos e
   where e.tipo not in ('pesquisa_criada', 'pesquisa_revisada',
                        'busca_iniciada', 'busca_concluida', 'busca_falhou',
                        'referencia_incluida', 'referencia_excluida',
                        'metodo_alterado', 'preco_arbitrado',
                        'item_concluido', 'item_incompleto',
                        'pesquisa_concluida', 'pesquisa_aplicada',
                        'pesquisa_arquivada', 'excecao_registrada',
                        'relatorio_emitido', 'busca_registrada',
                        'item_editado', 'item_removido', 'selecao_sugerida');
  if n > 0 then faltou := faltou || ' eventos_fora_do_check=' || n; end if;

  if not exists (select 1 from public.config_app
                  where chave = 'flag_unified_quotations') then
    faltou := faltou || ' flag_ausente';
  end if;

  if faltou <> '' then
    raise exception 'A 0029 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
