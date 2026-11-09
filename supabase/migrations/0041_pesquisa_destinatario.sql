-- ## 0041 — Pesquisa de preços: o órgão a que o relatório se destina
-- ## ESTADO: aplicável. NÃO aplicada em produção (aplica-se só a pedido do dono).
--
-- O PROBLEMA (09/11/2026, relatado pelo dono)
--   Todo Relatório de Cotação saía com o timbrado de Paragominas. O timbrado
--   era resolvido pelo VÍNCULO de quem emite (secretaria > município >
--   primeiro órgão de `config_orgaos`), e todo usuário de produção é de
--   Paragominas. Cotação feita para outra prefeitura saía com o timbrado
--   errado. A regra do dono: o timbrado de Paragominas só vai em relatório
--   dirigido à Prefeitura de Paragominas ou a uma secretaria dela; outra
--   prefeitura, sem timbrado salvo, sai sem timbrado.
--
--   O destinatário não existia como dado: a pesquisa só guardava texto livre
--   (nome, objeto, responsável, local de referência). Daí estas colunas.
--
-- O QUE FAZ
--   * `destinatario_secretaria_id`: uma secretaria cadastrada DO MESMO
--     município (a prefeitura ou uma secretaria dela). O relatório sai com o
--     timbrado dela, herdando o do município quando ela não tem um próprio;
--   * `destinatario_externo`: o nome de outro órgão, digitado. O relatório
--     sai SEM timbrado;
--   * as duas vazias: pesquisa anterior a esta migração. Decisão do dono
--     (09/11/2026): sai como antes, pelo vínculo de quem emite;
--   * as duas preenchidas ao mesmo tempo: recusado (check);
--   * secretaria de OUTRO município: recusada pelo gatilho. A chave
--     estrangeira sozinha não basta — ela atravessa o RLS e aceitaria o id de
--     uma secretaria de outra prefeitura, que viraria sonda e, pior, timbrado
--     alheio;
--   * `revisar_pesquisa_preco` copia as duas colunas para a revisão nova.
--     Sem isso, revisar uma cotação de outra prefeitura a devolveria ao
--     timbrado de Paragominas em silêncio.
--
-- PRIVILÉGIOS
--   Nenhum grant novo. As colunas herdam o grant de TABELA da 0021
--   (`select, insert, update` a `authenticated`); `anon` segue sem nada. O
--   gatilho é `security definer` porque confere `secretarias` por cima do
--   RLS de quem grava (a pergunta é "esta secretaria é do município desta
--   pesquisa?", não "eu vejo esta secretaria?"); devolve só sim/não, tem
--   `search_path` vazio e não é executável por `anon`.
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * timbrado de OUTRA prefeitura: não há cadastro de órgão externo com
--     timbrado. Órgão externo sai sem timbrado até esse cadastro existir;
--   * as pesquisas já criadas continuam vazias: o timbrado delas segue o
--     vínculo, até alguém escolher o destinatário na tela;
--   * a escolha é de quem escreve na pesquisa (dono ou admin, 0021); errar o
--     destinatário é corrigível na tela, não há trava de conteúdo;
--   * o gatilho aceita QUALQUER secretaria do município, não só a de quem
--     grava: o timbrado é do município, e escolher a prefeitura ou outra
--     secretaria dela é o caso de uso. O que ele barra é outro município;
--   * com a chave estrangeira, apagar uma secretaria que alguma pesquisa
--     tenha como destinatária passa a ser recusado (desativá-la continua
--     possível, e o relatório segue com o timbrado dela).
--
-- ORDEM: esta migração ANTES da imagem que grava as colunas. Ao contrário, a
-- criação de pesquisa quebra: o PostgREST recusa coluna que não conhece.

alter table public.pesquisas_preco
  add column if not exists destinatario_secretaria_id uuid
    references public.secretarias (id),
  add column if not exists destinatario_externo text not null default '';

do $$
begin
  if not exists (select 1 from pg_constraint
                 where conname = 'pesquisas_preco_destinatario_coerente'
                   and conrelid = 'public.pesquisas_preco'::regclass) then
    alter table public.pesquisas_preco
      add constraint pesquisas_preco_destinatario_coerente
      check ((destinatario_secretaria_id is null or destinatario_externo = '')
             and char_length(destinatario_externo) <= 200);
  end if;
end
$$;

comment on column public.pesquisas_preco.destinatario_secretaria_id is
  'Secretaria do município a que o relatório se destina; dá o timbrado (0041).';
comment on column public.pesquisas_preco.destinatario_externo is
  'Nome de outro órgão a que o relatório se destina; sai sem timbrado (0041).';

-- ---------------------------------------------------------------
-- Gatilho: a secretaria destinatária é do município da pesquisa
-- ---------------------------------------------------------------
create or replace function public.trg_pesquisa_preco_destinatario()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.destinatario_secretaria_id is not null
     and not exists (select 1 from public.secretarias s
                     where s.id = new.destinatario_secretaria_id
                       and s.tenant_id = new.tenant_id) then
    raise exception 'secretaria destinatária fora do município da pesquisa'
      using errcode = '42501';
  end if;
  return new;
end $$;

revoke all on function public.trg_pesquisa_preco_destinatario() from public, anon;

drop trigger if exists pesquisas_preco_destinatario on public.pesquisas_preco;
create trigger pesquisas_preco_destinatario
  before insert or update of destinatario_secretaria_id, tenant_id
  on public.pesquisas_preco
  for each row execute function public.trg_pesquisa_preco_destinatario();

-- ---------------------------------------------------------------
-- Revisão copia o destinatário (corpo da 0029 + as duas colunas)
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
    versao, revisao_de, raiz_id, motivo_da_revisao,
    destinatario_secretaria_id, destinatario_externo)
  values (
    v_origem.tenant_id, v_origem.secretaria_id, v_origem.auth_user_id,
    v_origem.processo_id,
    v_origem.nome, v_origem.objeto, v_origem.responsavel,
    v_origem.local_referencia, v_origem.data_base,
    v_origem.perfil_normativo,
    'review',
    v_origem.filtros, v_origem.valor_global,
    v_origem.versao_algoritmo, v_origem.versao_regras, v_origem.modelo_ia,
    v_proxima, v_origem.id, v_raiz, coalesce(p_motivo, ''),
    v_origem.destinatario_secretaria_id, v_origem.destinatario_externo)
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

-- O PostgREST guarda o esquema em cache: sem isto, as colunas novas não
-- existem para ele até o próximo recarregamento.
notify pgrst, 'reload schema';

-- ---------------------------------------------------------------
-- Conferência que falha sozinha
-- ---------------------------------------------------------------
do $$
declare
  faltou text := '';
  gatilho constant regprocedure :=
    'public.trg_pesquisa_preco_destinatario()'::regprocedure;
  revisao constant regprocedure :=
    'public.revisar_pesquisa_preco(uuid, text)'::regprocedure;
  corpo text;
begin
  if not exists (select 1 from information_schema.columns
                 where table_schema = 'public' and table_name = 'pesquisas_preco'
                   and column_name = 'destinatario_secretaria_id'
                   and data_type = 'uuid') then
    faltou := faltou || ' sem_coluna_secretaria';
  end if;
  if not exists (select 1 from information_schema.columns
                 where table_schema = 'public' and table_name = 'pesquisas_preco'
                   and column_name = 'destinatario_externo'
                   and is_nullable = 'NO' and column_default like '''''%') then
    faltou := faltou || ' sem_coluna_externo';
  end if;
  if not exists (select 1 from pg_constraint
                 where conname = 'pesquisas_preco_destinatario_coerente'
                   and conrelid = 'public.pesquisas_preco'::regclass
                   and contype = 'c' and convalidated) then
    faltou := faltou || ' sem_check';
  end if;
  -- BEFORE (2), por linha (1), em INSERT (4) e UPDATE (16), com colunas-alvo:
  -- um gatilho recriado como `after update` não recusaria nada a tempo.
  if not exists (select 1 from pg_trigger
                 where tgname = 'pesquisas_preco_destinatario'
                   and tgrelid = 'public.pesquisas_preco'::regclass
                   and tgfoid = gatilho and tgenabled <> 'D'
                   and tgtype & 23 = 23 and array_length(tgattr::int2[], 1) = 2) then
    faltou := faltou || ' sem_gatilho';
  end if;
  if not coalesce((select proconfig from pg_proc where oid = gatilho)
                  @> array['search_path=""'], false) then
    faltou := faltou || ' gatilho_sem_search_path';
  end if;
  -- O corpo: um `create or replace` que reduza o gatilho a `return new`
  -- passaria por todas as outras perguntas.
  if not (select prosecdef and prosrc like '%s.tenant_id = new.tenant_id%'
          from pg_proc where oid = gatilho) then
    faltou := faltou || ' gatilho_nao_confere_municipio';
  end if;
  if has_function_privilege('anon', gatilho, 'execute') then
    faltou := faltou || ' anon_executa_gatilho';
  end if;
  select prosrc into corpo from pg_proc where oid = revisao;
  if corpo not like '%v_origem.destinatario_secretaria_id%'
     or corpo not like '%v_origem.destinatario_externo%' then
    faltou := faltou || ' revisao_nao_copia';
  end if;
  if has_function_privilege('anon', revisao, 'execute') then
    faltou := faltou || ' anon_revisa';
  end if;
  if not has_function_privilege('authenticated', revisao, 'execute') then
    faltou := faltou || ' authenticated_nao_revisa';
  end if;
  if not has_function_privilege('service_role', revisao, 'execute') then
    faltou := faltou || ' service_role_nao_revisa';
  end if;
  if not coalesce((select prosecdef and proconfig @> array['search_path=""']
                   from pg_proc where oid = revisao), false) then
    faltou := faltou || ' revisao_sem_search_path';
  end if;
  if not has_column_privilege('authenticated', 'public.pesquisas_preco',
                              'destinatario_externo', 'update')
     or not has_column_privilege('authenticated', 'public.pesquisas_preco',
                                 'destinatario_secretaria_id', 'update')
     or not has_column_privilege('authenticated', 'public.pesquisas_preco',
                                 'destinatario_externo', 'insert')
     or not has_column_privilege('authenticated', 'public.pesquisas_preco',
                                 'destinatario_secretaria_id', 'insert') then
    faltou := faltou || ' authenticated_nao_grava';
  end if;
  -- Por coluna também: um grant de coluna a `anon` não aparece em
  -- `has_table_privilege`.
  if has_any_column_privilege('anon', 'public.pesquisas_preco', 'select') then
    faltou := faltou || ' anon_le_tabela';
  end if;
  if not (select relrowsecurity from pg_class
          where oid = 'public.pesquisas_preco'::regclass) then
    faltou := faltou || ' rls_desligado';
  end if;
  if faltou <> '' then
    raise exception 'A 0041 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
