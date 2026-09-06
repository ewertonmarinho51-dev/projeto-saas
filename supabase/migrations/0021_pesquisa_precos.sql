-- ############################################################
-- ##  0021 — Pesquisa de Preços (Fase 3: persistência)
-- ##
-- ##  ESTADO: APLICADA EM PRODUÇÃO (`govdocs-wizard`) em 06/09/2026,
-- ##  pelo mecanismo oficial de migrations, em quatro partes:
-- ##  tabelas e índices; predicados, RLS, revokes, políticas e grants;
-- ##  gatilhos, a RPC de revisão e a flag; e a revogação de
-- ##  DELETE/TRUNCATE. Antes disso já estava aplicada e verificada no
-- ##  ambiente de ensaio (`govdocs-ensaio-descartavel`).
-- ##
-- ##  A FLAG NASCEU E CONTINUA `off`. Aplicar a migração não liga o
-- ##  módulo: as quatro tabelas estão vazias e sem tráfego.
-- ##
-- ##  Verificação pós-aplicação: as impressões digitais de políticas,
-- ##  colunas, grants, gatilhos e checks batem entre produção e o
-- ##  ensaio; RLS ligado nas quatro; `anon` sem privilégio nenhum;
-- ##  `service_role` sem DELETE e sem TRUNCATE; Security Advisors sem
-- ##  achado de nível ERROR.
-- ##
-- ##  A trava existia por dependência TÉCNICA, não por cautela
-- ##  decorativa: esta migração CHAMA as funções de contexto da 0020
-- ##  (`tenant_do_jwt`, `secretaria_do_jwt`, `e_admin`) nas suas
-- ##  políticas. Sem a 0020, as políticas não podem sequer ser
-- ##  criadas — e, se pudessem, as tabelas nasceriam no mundo
-- ##  pré-0019, onde `anon` ainda tem grants amplos. Seria criar
-- ##  exposição nova para hospedar preço de contratação.
-- ##
-- ##  Ordem do runbook, e ela continua obrigatória:
-- ##  0018 → 0019 → 0020 → 0021.
-- ##
-- ##  O §39 do prompt do módulo exige "não ativar este módulo em
-- ##  produção sem provar o mesmo isolamento exigido do restante da
-- ##  plataforma". O isolamento desta migração está provado e
-- ##  EXECUTADO (tests/test_precos_fase3_rls.py, 47 provas contra
-- ##  PostgreSQL real). Ligar a flag depende de outra coisa, que não é
-- ##  desta migração: hoje não existe conta no Supabase Auth, e sem
-- ##  `auth.uid()` toda política aqui nega — como deve.
-- ##
-- ##  IDEMPOTÊNCIA OPERACIONAL: tudo aqui é `if not exists`,
-- ##  `create or replace`, `drop policy if exists` antes de criar, e
-- ##  `on conflict do nothing` no insert da flag. Reaplicar não
-- ##  duplica objeto nem religa a flag que alguém desligou.
-- ############################################################

-- ===============================================================
-- POR QUE QUATRO TABELAS, E NÃO MENOS
--
-- O prompt (§41) manda auditar o schema antes de criar e proibir
-- tabela criada só porque o nome apareceu no enunciado. As 28
-- tabelas existentes foram examinadas. Nenhuma serve:
--
-- * `processos.dados` é jsonb. Uma pesquisa de 210 itens × ~30
--   referências são ~6.300 linhas; dentro de um jsonb elas não são
--   filtráveis, não são indexáveis por fonte/data, e uma exclusão
--   manual vira reescrita do documento inteiro — sem trilha do que
--   mudou;
--
-- * `geracoes` é registro técnico de geração de documento (motor,
--   tokens, duração). Não tem onde pôr preço, fonte nem score;
--
-- * `governanca_eventos` PARECE servir de trilha, e foi seriamente
--   considerada. Não serve, por um motivo verificável: a escrita
--   passa por `registrar_evento_governanca`, que autoriza pela
--   matriz `eventos_permitidos_ao_papel(papel_governanca)`. Um
--   servidor comum tem `papel_governanca` NULO e recebe
--   `array[]::text[]` — nenhum evento. Ou seja: o servidor que
--   exclui uma referência da cesta não conseguiria registrar que
--   excluiu. Trilha que recusa o ato que precisa registrar não é
--   trilha.
--
-- Restam as quatro. Cada uma existe porque tem chave, cardinalidade
-- e ciclo de vida próprios.
-- ===============================================================

-- ---------------------------------------------------------------
-- 1. Cabeçalho da pesquisa
--
-- `processo_id` é NULLABLE de propósito: o §17 prevê a pesquisa
-- AUTÔNOMA, iniciada pelo dashboard e vinculada a um processo
-- depois — ou nunca.
--
-- Sobre o VERSIONAMENTO (§44), três colunas e nenhuma a mais:
--   `versao`     — número da revisão dentro da mesma pesquisa lógica;
--   `revisao_de` — a revisão imediatamente anterior;
--   `raiz_id`    — a primeira revisão. NULO significa "esta é a raiz".
--
-- Com as três, "todo o histórico desta pesquisa" é
-- `coalesce(raiz_id, id) = X`, e a revisão vigente é a de maior
-- `versao`. Nada é apagado ao revisar: cria-se linha nova.
-- ---------------------------------------------------------------
create table if not exists public.pesquisas_preco (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),

  -- Escopo institucional. `tenant_id` é NOT NULL e SEM DEFAULT: o
  -- default do tenant padrão existe nas tabelas de 2026 porque elas
  -- foram criadas antes do multi-tenant e precisavam de backfill.
  -- Tabela nova não herda esse débito — quem insere declara o tenant,
  -- e a política confere contra o JWT.
  tenant_id uuid not null references public.tenants (id),
  secretaria_id uuid references public.secretarias (id),
  auth_user_id uuid not null references auth.users (id),

  processo_id uuid references public.processos (id),

  -- Identificação (§18, Etapa 1)
  nome text not null,
  objeto text not null default '',
  responsavel text not null default '',
  local_referencia text not null default '',
  data_base date,

  -- Regime normativo sob o qual a pesquisa correu (§3). Fica na
  -- linha, não na interface: o relatório precisa dizer meses depois
  -- sob qual regra o valor foi formado.
  perfil_normativo text not null default 'lei_14133',

  estado text not null default 'draft'
    check (estado in ('draft', 'queued', 'running', 'partial', 'review',
                      'completed', 'applied', 'archived', 'failed')),

  -- Filtros da pesquisa (janela temporal, UF, fontes, piso de
  -- comparabilidade). Alterá-los cria revisão nova — ver §44.
  filtros jsonb not null default '{}'::jsonb,

  valor_global numeric(18, 4),

  -- Reprodutibilidade (§34). O relatório precisa poder ser refeito a
  -- partir do que foi salvo, mesmo que a API externa mude depois.
  versao_algoritmo text not null default '',
  versao_regras text not null default '',
  modelo_ia text not null default '',

  -- Versionamento lógico
  versao integer not null default 1 check (versao >= 1),
  revisao_de uuid references public.pesquisas_preco (id),
  raiz_id uuid references public.pesquisas_preco (id),
  motivo_da_revisao text not null default '',

  -- Idempotência (§43): reexecutar a criação com a mesma chave
  -- devolve a mesma pesquisa em vez de criar a segunda.
  idempotency_key text not null default '',

  aplicada_em timestamptz,

  -- A raiz não pode apontar para si mesma por engano, e uma revisão
  -- não é a própria anterior.
  constraint pesquisas_preco_raiz_coerente
    check (raiz_id is null or raiz_id <> id),
  constraint pesquisas_preco_revisao_coerente
    check (revisao_de is null or revisao_de <> id)
);

create index if not exists pesquisas_preco_tenant_idx
  on public.pesquisas_preco (tenant_id, atualizado_em desc);
create index if not exists pesquisas_preco_processo_idx
  on public.pesquisas_preco (processo_id)
  where processo_id is not null;
create index if not exists pesquisas_preco_dono_idx
  on public.pesquisas_preco (auth_user_id, atualizado_em desc);
-- Histórico de uma pesquisa lógica, da raiz à revisão vigente.
create index if not exists pesquisas_preco_historico_idx
  on public.pesquisas_preco (coalesce(raiz_id, id), versao desc);
-- Duas revisões nunca dividem o mesmo número dentro da mesma raiz.
create unique index if not exists pesquisas_preco_versao_unica
  on public.pesquisas_preco (coalesce(raiz_id, id), versao);
-- Idempotência por tenant. Índice PARCIAL: a chave vazia é o caso
-- normal (criação interativa) e não deve colidir com nada.
create unique index if not exists pesquisas_preco_idempotencia
  on public.pesquisas_preco (tenant_id, idempotency_key)
  where idempotency_key <> '';

-- ---------------------------------------------------------------
-- 2. Itens da pesquisa
--
-- O item tem estado PRÓPRIO. Um item `incomplete` no meio de 209
-- concluídos é a informação mais importante da tela de resumo, e ela
-- não existe se o estado for só da pesquisa.
--
-- `codigo`/`tipo_catalogo` são NULLABLE: a decisão de produto é que
-- CATMAT/CATSER é aceito e usado quando pertinente, nunca exigido.
-- ---------------------------------------------------------------
create table if not exists public.pesquisa_preco_itens (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),

  pesquisa_id uuid not null
    references public.pesquisas_preco (id) on delete cascade,
  tenant_id uuid not null references public.tenants (id),

  numero integer not null check (numero >= 1),
  codigo text,
  tipo_catalogo text check (tipo_catalogo in ('CATMAT', 'CATSER')),
  descricao text not null,
  unidade text not null default '',
  quantidade numeric(18, 4),

  estado text not null default 'pending'
    check (estado in ('pending', 'searching', 'matching', 'review',
                      'complete', 'incomplete', 'error')),

  -- Como o preço foi formado. 'manual' é o preço arbitrado pelo
  -- revisor, e existe como método NOMEADO justamente para não se
  -- disfarçar de média.
  metodo text check (metodo in ('media', 'mediana', 'menor', 'manual')),
  preco_estimado numeric(18, 4),
  preco_total numeric(18, 4),

  -- Memória de cálculo: n, média, mediana, desvio, CV, IQR, limites.
  estatisticas jsonb not null default '{}'::jsonb,
  -- Por que este método, por que esta cesta, por que estas exclusões.
  justificativa text not null default '',
  -- Ocorrências das fontes (§37): "PNCP indisponível" vive aqui.
  ocorrencias jsonb not null default '[]'::jsonb,

  -- DESFECHO POR FONTE — `{"compras_gov_precos": "failure", "pncp":
  -- "success_empty"}`.
  --
  -- Existe porque `ocorrencias` é texto para humano e não sustenta
  -- decisão: relendo o item do banco, ninguém distinguia "a fonte de
  -- preço caiu" de "o mercado não tinha o item". Os dois viravam
  -- `incomplete`, e só o primeiro justifica repetir a busca.
  --
  -- Os valores são os de `precos.fontes.Desfecho`.
  desfechos jsonb not null default '{}'::jsonb,

  -- Diagnóstico da falha técnica, quando houve. Fica ao lado de
  -- `estado='error'` e é o que a tela mostra ao oferecer o retry.
  erro text not null default '',

  unique (pesquisa_id, numero)
);

create index if not exists pesquisa_preco_itens_pesquisa_idx
  on public.pesquisa_preco_itens (pesquisa_id, numero);
create index if not exists pesquisa_preco_itens_estado_idx
  on public.pesquisa_preco_itens (pesquisa_id, estado);

-- ---------------------------------------------------------------
-- 3. Referências coletadas
--
-- É AQUI que mora o volume, e é por isso que esta tabela existe.
--
-- Sobre o SNAPSHOT (§35): guardamos os campos normalizados, o
-- identificador oficial, o hash do payload e o payload bruto em
-- `bruto`. O bruto é mantido porque a evidência de que o preço
-- existiu não pode depender de URL viva — o §34 é explícito. São
-- dados públicos de contratação (Lei de Acesso à Informação), sem
-- dado pessoal além da razão social e do NI do fornecedor, que são
-- justamente o que identifica a contratação no ato administrativo.
--
-- REJEIÇÃO NÃO É EXCLUSÃO. Não há grant de DELETE nesta tabela para
-- ninguém. Tirar uma referência da cesta é mudar `status` para
-- 'rejected' e registrar o motivo — uma pesquisa em que preços
-- coletados somem sem rastro é o oposto de auditável.
-- ---------------------------------------------------------------
create table if not exists public.pesquisa_preco_referencias (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  coletado_em timestamptz not null default now(),

  item_id uuid not null
    references public.pesquisa_preco_itens (id) on delete cascade,
  tenant_id uuid not null references public.tenants (id),

  fonte_id text not null,
  fonte_nome text not null default '',
  fonte_tipo text not null default 'outro'
    check (fonte_tipo in ('sistema_oficial', 'contratacao_similar', 'outro')),
  id_externo text not null,
  referencia_externa text,
  raw_hash text not null,

  -- O que a fonte disse
  descricao_original text not null default '',
  unidade_original text,
  quantidade_original numeric(18, 4),
  valor_unitario_original numeric(18, 4),
  capacidade_embalagem numeric(18, 4),

  -- O que o motor derivou COM PROVA. NULO quando não houve prova —
  -- e nunca zero, que mentiria dizendo que a conversão deu zero.
  unidade_normalizada text,
  valor_unitario_normalizado numeric(18, 4),

  -- NATUREZA DO VALOR — o que o número É, não só quanto ele vale.
  --
  -- Sem esta coluna a regra viveria só em memória: recarregando a
  -- pesquisa do banco, o `valorUnitarioEstimado` de uma contratação de
  -- terceiro voltaria indistinguível de preço praticado, e a primeira
  -- releitura perderia a proteção.
  --
  -- O CHECK enumera de propósito, com a mesma lista de
  -- `precos.modelo.NaturezaValor`: natureza que o app não conhece não
  -- entra no banco, e natureza que o banco não conhece não sai do app.
  natureza_valor text not null default 'outro'
    check (natureza_valor in ('praticado', 'homologado', 'contratado',
                              'adjudicado', 'estimado_origem', 'proposta',
                              'outro')),

  codigo_catalogo text,
  tipo_catalogo text,
  orgao text,
  uf text,
  municipio text,
  fornecedor text,
  ni_fornecedor text,
  marca text,
  data_compra date,
  data_resultado date,

  -- Comparabilidade explicada (§14): o total, os dois componentes e
  -- os fatores um a um. É o que a tela de revisão mostra ao servidor.
  score numeric(6, 5),
  identidade numeric(6, 5),
  circunstancias numeric(6, 5),
  fatores jsonb not null default '[]'::jsonb,

  status text not null default 'candidate'
    check (status in ('candidate', 'selected', 'rejected',
                      'warning', 'manual_review')),
  motivos jsonb not null default '[]'::jsonb,

  -- Payload como a fonte entregou (§35).
  bruto jsonb not null default '{}'::jsonb,

  -- IDEMPOTÊNCIA (§43), e esta é a garantia central do módulo:
  -- reexecutar a pesquisa do item NÃO duplica referência. A fonte
  -- promete unicidade do par (fonte, id externo); nós a amarramos ao
  -- item.
  unique (item_id, fonte_id, id_externo)
);

create index if not exists pesquisa_preco_referencias_item_idx
  on public.pesquisa_preco_referencias (item_id, status);
create index if not exists pesquisa_preco_referencias_score_idx
  on public.pesquisa_preco_referencias (item_id, score desc nulls last);
create index if not exists pesquisa_preco_referencias_tenant_idx
  on public.pesquisa_preco_referencias (tenant_id, coletado_em desc);

-- ---------------------------------------------------------------
-- 4. Trilha da pesquisa — APPEND-ONLY
--
-- "alterações humanas" é item do §34. Inclusão manual, exclusão
-- manual, troca de método, preço arbitrado, aplicação ao processo:
-- tudo vira linha aqui, com o ator e o payload.
-- ---------------------------------------------------------------
create table if not exists public.pesquisa_preco_eventos (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),

  pesquisa_id uuid not null
    references public.pesquisas_preco (id) on delete cascade,
  item_id uuid references public.pesquisa_preco_itens (id) on delete cascade,
  tenant_id uuid not null references public.tenants (id),

  -- Quem praticou o ato. NULO só quando o ato é do motor.
  ator uuid,
  automatico boolean not null default false,

  tipo text not null
    check (tipo in ('pesquisa_criada', 'pesquisa_revisada',
                    'busca_iniciada', 'busca_concluida', 'busca_falhou',
                    'referencia_incluida', 'referencia_excluida',
                    'metodo_alterado', 'preco_arbitrado',
                    'item_concluido', 'item_incompleto',
                    'pesquisa_concluida', 'pesquisa_aplicada',
                    'pesquisa_arquivada')),
  descricao text not null default '',
  payload jsonb not null default '{}'::jsonb,

  idempotency_key text not null default ''
);

create index if not exists pesquisa_preco_eventos_pesquisa_idx
  on public.pesquisa_preco_eventos (pesquisa_id, criado_em desc);
create index if not exists pesquisa_preco_eventos_item_idx
  on public.pesquisa_preco_eventos (item_id, criado_em desc)
  where item_id is not null;
create unique index if not exists pesquisa_preco_eventos_idempotencia
  on public.pesquisa_preco_eventos (pesquisa_id, idempotency_key)
  where idempotency_key <> '';

-- ===============================================================
-- PREDICADO DE LEITURA
--
-- A 0020 tem `pode_ler_processo(tenant, secretaria)` e diz, com
-- razão, que repetir o predicado em cada tabela abre espaço para
-- divergirem. Aqui ele NÃO é reusado tal e qual, e a diferença é
-- deliberada — está escrita para ser contestada, não escondida.
--
-- `pode_ler_processo` exige, para o não-admin, que a secretaria da
-- linha seja a do JWT. Aplicado a esta tabela, isso trancaria o
-- autor para fora da própria pesquisa em dois casos REAIS:
--
--   1. pesquisa AUTÔNOMA (§17, opção B), que nasce sem processo e
--      pode nascer sem secretaria;
--   2. servidor sem vínculo de secretaria — `usuarios.secretaria_id`
--      é NULLABLE desde a 0007, e a 0020 já registrou que o legado
--      sem secretaria fica invisível.
--
-- Numa tabela que existe desde hoje dá para evitar o problema em vez
-- de herdá-lo: soma-se o DONO ao predicado. O resultado é mais
-- estreito, não mais largo, do que "todo autenticado do tenant": lê
-- quem é admin do município, quem é da mesma secretaria, ou quem
-- fez a pesquisa.
-- ===============================================================
create or replace function public.pode_ler_pesquisa_preco(
  p_tenant uuid, p_secretaria uuid, p_dono uuid)
returns boolean language sql stable
set search_path = ''
as $$
  select p_tenant is not null
     and p_tenant = public.tenant_do_jwt()
     and (public.e_admin()
          or (p_dono is not null and p_dono = auth.uid())
          or (p_secretaria is not null
              and p_secretaria = public.secretaria_do_jwt()))
$$;

-- ESCRITA é mais estreita que LEITURA, pela mesma razão que a 0020
-- separou as duas: poder ler a pesquisa do colega da pasta não dá
-- direito de mexer na cesta dela — e o registro sairia com a
-- aparência de ter vindo do titular.
create or replace function public.pode_escrever_pesquisa_preco(
  p_tenant uuid, p_dono uuid)
returns boolean language sql stable
set search_path = ''
as $$
  select p_tenant is not null
     and p_tenant = public.tenant_do_jwt()
     and (public.e_admin() or (p_dono is not null and p_dono = auth.uid()))
$$;

-- EXECUTE explícito, função por função.
--
-- Não é simetria: o ensaio local da 0020 provou em PG 16 que
-- `alter default privileges ... revoke execute on functions from
-- public` NÃO suprime o EXECUTE que o PostgreSQL concede a PUBLIC em
-- toda função nova. Para funções, a única garantia é o revoke
-- explícito. Sem estas quatro linhas, `anon` executaria os
-- predicados desta migração.
revoke all on function
  public.pode_ler_pesquisa_preco(uuid, uuid, uuid) from public, anon;
grant execute on function
  public.pode_ler_pesquisa_preco(uuid, uuid, uuid)
  to authenticated, service_role;

revoke all on function
  public.pode_escrever_pesquisa_preco(uuid, uuid) from public, anon;
grant execute on function
  public.pode_escrever_pesquisa_preco(uuid, uuid)
  to authenticated, service_role;

-- ===============================================================
-- RLS — habilitado antes de qualquer grant
-- ===============================================================
alter table public.pesquisas_preco             enable row level security;
alter table public.pesquisa_preco_itens        enable row level security;
alter table public.pesquisa_preco_referencias  enable row level security;
alter table public.pesquisa_preco_eventos      enable row level security;

-- `anon` não tem nada aqui. A linha é explícita — e não confiada ao
-- default — porque é a afirmação central desta migração.
--
-- `authenticated` entra no revoke e recebe de volta, logo abaixo,
-- exatamente select/insert/update por tabela. Parece redundante e não
-- é: o `pg_default_acl` do schema `public` tem DUAS entradas, e qual
-- delas vale depende de QUEM cria a tabela. A entrada do dono
-- `supabase_admin` concede `arwdDxtm` a anon, authenticated e
-- service_role; a do dono `postgres` — que é quem executa estas
-- migrações — concede só a postgres e service_role. Amarrar a
-- ausência de DELETE de `authenticated` ao fato de a migração ter
-- rodado como `postgres` é depender de uma circunstância que nenhuma
-- linha deste arquivo declara. Com o revoke explícito, o resultado é
-- o mesmo nos dois caminhos.
revoke all on public.pesquisas_preco            from anon, authenticated, public;
revoke all on public.pesquisa_preco_itens       from anon, authenticated, public;
revoke all on public.pesquisa_preco_referencias from anon, authenticated, public;
revoke all on public.pesquisa_preco_eventos     from anon, authenticated, public;

-- DELETE FORA, INCLUSIVE PARA A CREDENCIAL DE SERVIDOR.
--
-- Estas quatro linhas nasceram de um achado ao APLICAR a migração no
-- ambiente de ensaio, e valem o registro porque a migração afirmava o
-- contrário do que acontecia. O Supabase configura o schema `public`
-- com `alter default privileges ... grant all on tables to postgres,
-- anon, authenticated, service_role` — então cada tabela criada aqui
-- nascia com DELETE para `service_role` sem uma linha de SQL nossa
-- pedindo por isso.
--
-- O ensaio local não pegou porque ele NÃO reproduzia esses defaults:
-- era mais frouxo que a realidade e, por isso, mais complacente com a
-- migração. Corrigido no mesmo commit (`ensaio_local.PREAMBULO`).
--
-- E o revoke tem dente: o `BYPASSRLS` do `service_role` ignora
-- POLÍTICAS de linha, não GRANTs de tabela. Sem o privilégio, a
-- credencial de servidor não apaga — e é ela que operaria estas
-- tabelas se alguém voltasse atrás na decisão de usar o JWT do
-- usuário.
--
-- TRUNCATE vai junto, e a razão é a que torna o achado grave: ele
-- apaga TODAS as linhas sem passar pelo gatilho de linha. O
-- `trg_pesquisa_preco_trilha_imutavel` é `before update or delete` —
-- TRUNCATE não é nenhum dos dois. Revogar só DELETE deixaria esta
-- migração afirmando, por escrito, que a trilha é append-only "até
-- para a credencial de servidor" enquanto um único comando a
-- esvaziava. Foi exatamente o que a primeira versão fez.
revoke delete, truncate on public.pesquisas_preco            from service_role;
revoke delete, truncate on public.pesquisa_preco_itens       from service_role;
revoke delete, truncate on public.pesquisa_preco_referencias from service_role;
revoke delete, truncate on public.pesquisa_preco_eventos     from service_role;

-- ---------------------------------------------------------------
-- Políticas — cabeçalho
-- ---------------------------------------------------------------
drop policy if exists "pesquisas_preco_le" on public.pesquisas_preco;
create policy "pesquisas_preco_le" on public.pesquisas_preco
  for select to authenticated
  using (public.pode_ler_pesquisa_preco(
           tenant_id, secretaria_id, auth_user_id));

drop policy if exists "pesquisas_preco_insere" on public.pesquisas_preco;
create policy "pesquisas_preco_insere" on public.pesquisas_preco
  for insert to authenticated
  with check (
    tenant_id = public.tenant_do_jwt()
    -- O dono é quem está autenticado. Sem isto, uma pesquisa poderia
    -- nascer com o nome de outro servidor.
    and auth_user_id = auth.uid()
    and (secretaria_id is null
         or secretaria_id = public.secretaria_do_jwt()
         or public.e_admin())
    -- Vínculo com processo só para processo que o autor alcança —
    -- senão o `processo_id` viraria sonda de existência de processos
    -- de outras pastas.
    and (processo_id is null
         or exists (select 1 from public.processos p
                    where p.id = processo_id
                      and public.pode_ler_processo(p.tenant_id,
                                                   p.secretaria_id))));

drop policy if exists "pesquisas_preco_edita" on public.pesquisas_preco;
create policy "pesquisas_preco_edita" on public.pesquisas_preco
  for update to authenticated
  using      (public.pode_escrever_pesquisa_preco(tenant_id, auth_user_id))
  with check (public.pode_escrever_pesquisa_preco(tenant_id, auth_user_id));

grant select, insert, update on public.pesquisas_preco to authenticated;

-- ---------------------------------------------------------------
-- Políticas — itens e referências herdam o escopo do PAI
--
-- O predicado não é repetido: é consultado na pesquisa. Se o escopo
-- mudar, muda em `pode_ler_pesquisa_preco` e nada mais.
--
-- O `tenant_id` da filha é amarrado ao do PAI **e** ao do JWT. Sem a
-- amarração ao pai, a coluna aceitaria um tenant qualquer vindo do
-- cliente e a linha ficaria pendurada numa pesquisa de um município
-- declarando pertencer a outro.
-- ---------------------------------------------------------------
drop policy if exists "pesquisa_preco_itens_le"
  on public.pesquisa_preco_itens;
create policy "pesquisa_preco_itens_le" on public.pesquisa_preco_itens
  for select to authenticated
  using (exists (select 1 from public.pesquisas_preco s
                 where s.id = pesquisa_preco_itens.pesquisa_id
                   and public.pode_ler_pesquisa_preco(
                         s.tenant_id, s.secretaria_id, s.auth_user_id)));

drop policy if exists "pesquisa_preco_itens_insere"
  on public.pesquisa_preco_itens;
create policy "pesquisa_preco_itens_insere" on public.pesquisa_preco_itens
  for insert to authenticated
  with check (
    tenant_id = public.tenant_do_jwt()
    and exists (select 1 from public.pesquisas_preco s
                where s.id = pesquisa_preco_itens.pesquisa_id
                  and s.tenant_id = pesquisa_preco_itens.tenant_id
                  and public.pode_escrever_pesquisa_preco(
                        s.tenant_id, s.auth_user_id)));

drop policy if exists "pesquisa_preco_itens_edita"
  on public.pesquisa_preco_itens;
create policy "pesquisa_preco_itens_edita" on public.pesquisa_preco_itens
  for update to authenticated
  using (exists (select 1 from public.pesquisas_preco s
                 where s.id = pesquisa_preco_itens.pesquisa_id
                   and public.pode_escrever_pesquisa_preco(
                         s.tenant_id, s.auth_user_id)))
  with check (
    tenant_id = public.tenant_do_jwt()
    and exists (select 1 from public.pesquisas_preco s
                where s.id = pesquisa_preco_itens.pesquisa_id
                  and s.tenant_id = pesquisa_preco_itens.tenant_id
                  and public.pode_escrever_pesquisa_preco(
                        s.tenant_id, s.auth_user_id)));

grant select, insert, update on public.pesquisa_preco_itens to authenticated;

-- Referências pendem do ITEM, que pende da pesquisa: dois saltos.
drop policy if exists "pesquisa_preco_referencias_le"
  on public.pesquisa_preco_referencias;
create policy "pesquisa_preco_referencias_le"
  on public.pesquisa_preco_referencias
  for select to authenticated
  using (exists (
    select 1 from public.pesquisa_preco_itens i
      join public.pesquisas_preco s on s.id = i.pesquisa_id
     where i.id = pesquisa_preco_referencias.item_id
       and public.pode_ler_pesquisa_preco(
             s.tenant_id, s.secretaria_id, s.auth_user_id)));

drop policy if exists "pesquisa_preco_referencias_insere"
  on public.pesquisa_preco_referencias;
create policy "pesquisa_preco_referencias_insere"
  on public.pesquisa_preco_referencias
  for insert to authenticated
  with check (
    tenant_id = public.tenant_do_jwt()
    and exists (
      select 1 from public.pesquisa_preco_itens i
        join public.pesquisas_preco s on s.id = i.pesquisa_id
       where i.id = pesquisa_preco_referencias.item_id
         and i.tenant_id = pesquisa_preco_referencias.tenant_id
         and public.pode_escrever_pesquisa_preco(
               s.tenant_id, s.auth_user_id)));

-- UPDATE existe para mudar STATUS e motivo (incluir/excluir da
-- cesta). Não existe DELETE — ver o comentário da tabela.
drop policy if exists "pesquisa_preco_referencias_edita"
  on public.pesquisa_preco_referencias;
create policy "pesquisa_preco_referencias_edita"
  on public.pesquisa_preco_referencias
  for update to authenticated
  using (exists (
    select 1 from public.pesquisa_preco_itens i
      join public.pesquisas_preco s on s.id = i.pesquisa_id
     where i.id = pesquisa_preco_referencias.item_id
       and public.pode_escrever_pesquisa_preco(s.tenant_id, s.auth_user_id)))
  with check (
    tenant_id = public.tenant_do_jwt()
    and exists (
      select 1 from public.pesquisa_preco_itens i
        join public.pesquisas_preco s on s.id = i.pesquisa_id
       where i.id = pesquisa_preco_referencias.item_id
         and i.tenant_id = pesquisa_preco_referencias.tenant_id
         and public.pode_escrever_pesquisa_preco(
               s.tenant_id, s.auth_user_id)));

grant select, insert, update
  on public.pesquisa_preco_referencias to authenticated;

-- ---------------------------------------------------------------
-- Políticas — trilha
--
-- SELECT e INSERT, nada mais. Sem UPDATE e sem DELETE: é o que
-- "append-only" significa quando é para valer.
-- ---------------------------------------------------------------
drop policy if exists "pesquisa_preco_eventos_le"
  on public.pesquisa_preco_eventos;
create policy "pesquisa_preco_eventos_le" on public.pesquisa_preco_eventos
  for select to authenticated
  using (exists (select 1 from public.pesquisas_preco s
                 where s.id = pesquisa_preco_eventos.pesquisa_id
                   and public.pode_ler_pesquisa_preco(
                         s.tenant_id, s.secretaria_id, s.auth_user_id)));

drop policy if exists "pesquisa_preco_eventos_insere"
  on public.pesquisa_preco_eventos;
create policy "pesquisa_preco_eventos_insere" on public.pesquisa_preco_eventos
  for insert to authenticated
  with check (
    tenant_id = public.tenant_do_jwt()
    and exists (select 1 from public.pesquisas_preco s
                where s.id = pesquisa_preco_eventos.pesquisa_id
                  and s.tenant_id = pesquisa_preco_eventos.tenant_id
                  and public.pode_escrever_pesquisa_preco(
                        s.tenant_id, s.auth_user_id)));

grant select, insert on public.pesquisa_preco_eventos to authenticated;

-- ---------------------------------------------------------------
-- Gatilhos: as duas coisas que política de RLS não alcança
-- ---------------------------------------------------------------
-- 1. O ator do evento é quem está autenticado.
--
-- Mesmo modelo do `trg_evento_ator_confiavel` da 0020, e pela mesma
-- razão: se uma política de INSERT voltar mais frouxa numa migração
-- futura, o gatilho ainda recusa evento assinado com o nome alheio.
-- O gatilho CARIMBA quando o ator vem vazio, e só RECUSA quando vem
-- outro. A distinção importa e a primeira versão não a fazia:
-- `is distinct from` tratava NULL como divergência, e todo evento
-- automático do motor — que roda dentro da sessão do usuário e não
-- assina nada — seria recusado com 42501.
--
-- Carimbar é melhor do que aceitar o nulo: um evento sem ator é uma
-- trilha que não diz quem estava operando, e "alterações humanas" é
-- item do §34. Quem dispara a busca responde por ela; `automatico`
-- registra que a DECISÃO foi do motor, não que não houve ninguém.
create or replace function public.trg_pesquisa_preco_ator()
returns trigger language plpgsql
set search_path = ''
as $$
begin
  if auth.uid() is not null then
    if new.ator is null then
      new.ator := auth.uid();
    elsif new.ator <> auth.uid() then
      raise exception 'ator do evento não confere com o usuário autenticado'
        using errcode = '42501';
    end if;
  end if;
  return new;
end $$;

revoke all on function public.trg_pesquisa_preco_ator() from public, anon;

drop trigger if exists pesquisa_preco_ator on public.pesquisa_preco_eventos;
create trigger pesquisa_preco_ator
  before insert on public.pesquisa_preco_eventos
  for each row execute function public.trg_pesquisa_preco_ator();

-- 2. A trilha é imutável até para a credencial de servidor.
--
-- Grants e políticas param `authenticated`. `service_role` tem
-- BYPASSRLS por definição — e é justamente com ele que o app opera
-- hoje. Um gatilho é o único ponto em que "append-only" continua
-- valendo para quem atravessa o RLS.
create or replace function public.trg_pesquisa_preco_trilha_imutavel()
returns trigger language plpgsql
set search_path = ''
as $$
begin
  raise exception
    'trilha da pesquisa de preços é append-only: % recusado', tg_op
    using errcode = '42501';
end $$;

revoke all on function public.trg_pesquisa_preco_trilha_imutavel()
  from public, anon;

drop trigger if exists pesquisa_preco_trilha_imutavel
  on public.pesquisa_preco_eventos;
create trigger pesquisa_preco_trilha_imutavel
  before update or delete on public.pesquisa_preco_eventos
  for each row execute function public.trg_pesquisa_preco_trilha_imutavel();

-- 3. `atualizado_em` é do banco, não do cliente.
create or replace function public.trg_pesquisa_preco_carimbo()
returns trigger language plpgsql
set search_path = ''
as $$
begin
  new.atualizado_em := now();
  return new;
end $$;

revoke all on function public.trg_pesquisa_preco_carimbo() from public, anon;

drop trigger if exists pesquisas_preco_carimbo on public.pesquisas_preco;
create trigger pesquisas_preco_carimbo
  before update on public.pesquisas_preco
  for each row execute function public.trg_pesquisa_preco_carimbo();

drop trigger if exists pesquisa_preco_itens_carimbo
  on public.pesquisa_preco_itens;
create trigger pesquisa_preco_itens_carimbo
  before update on public.pesquisa_preco_itens
  for each row execute function public.trg_pesquisa_preco_carimbo();

-- ===============================================================
-- REVISÃO LÓGICA (§44) — uma RPC, e não um laço no aplicativo
--
-- "Alterar cesta, metodologia, filtros ou preço estimado cria uma nova
-- revisão. O histórico anterior não desaparece."
--
-- A revisão é uma CÓPIA completa: cabeçalho, itens e referências. Meia
-- cópia não serviria — se as referências ficassem na revisão antiga, a
-- cesta anterior sumiria assim que alguém mudasse um status, que é
-- exatamente o histórico que o §44 manda preservar.
--
-- Por que no banco, e não em Python: uma pesquisa de 210 itens tem
-- ~6.300 referências. Copiá-las pelo PostgREST seria ler 6.300 linhas,
-- trazê-las pela rede e reescrevê-las — lento, e sobretudo NÃO
-- ATÔMICO: uma queda no meio deixaria uma revisão pela metade, que é
-- pior do que revisão nenhuma. Aqui são três `insert … select` numa
-- transação só.
--
-- SECURITY DEFINER, e a razão é a mesma do
-- `registrar_evento_governanca` da 0020: a política de INSERT exige
-- `auth_user_id = auth.uid()`, e a revisão precisa PRESERVAR o autor
-- original. Sem isso, revisar a pesquisa de um colega a transferiria
-- para o nome de quem revisou — e, numa pesquisa autônoma (sem
-- secretaria), trancaria o autor para fora do próprio trabalho.
--
-- Definer sem checagem seria um buraco. A autorização está explícita
-- na primeira coisa que a função faz, com o MESMO predicado das
-- políticas: quem não pode escrever na pesquisa não pode revisá-la.
-- ===============================================================
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

  -- Pesquisa inexistente e pesquisa inalcançável dão a MESMA resposta.
  -- Distingui-las transformaria a função em sonda de existência de
  -- pesquisas de outras secretarias e de outros municípios.
  if v_origem.id is null
     or not public.pode_escrever_pesquisa_preco(
              v_origem.tenant_id, v_origem.auth_user_id) then
    raise exception 'pesquisa de preços não encontrada ou fora do escopo'
      using errcode = '42501';
  end if;

  -- Arquivada é terminal na máquina de estados. Revisar a partir dela
  -- desfaria a decisão de arquivar sem que ninguém a revogasse.
  if v_origem.estado = 'archived' then
    raise exception 'pesquisa arquivada não admite revisão'
      using errcode = '42501';
  end if;

  v_raiz := coalesce(v_origem.raiz_id, v_origem.id);

  -- Duas revisões simultâneas disputam este número. Quem perder leva
  -- 23505 do índice único `pesquisas_preco_versao_unica` — que existe
  -- para isso: a corrida termina numa recusa, não em duas revisões
  -- com o mesmo número.
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
    -- A revisão nasce EM REVISÃO, qualquer que fosse o estado de
    -- origem: ela existe porque alguém está mudando o resultado, e o
    -- resultado mudado precisa ser reconfirmado antes de valer.
    'review',
    v_origem.filtros, v_origem.valor_global,
    v_origem.versao_algoritmo, v_origem.versao_regras, v_origem.modelo_ia,
    v_proxima, v_origem.id, v_raiz, coalesce(p_motivo, ''))
  returning id into v_nova;

  -- `desfechos` e `erro` vêm junto: sem eles a revisão nasceria sem
  -- saber POR QUE um item ficou em erro, e o servidor perderia a
  -- distinção entre falha de fonte e ausência de preço logo na primeira
  -- revisão — que é justamente quando ele está reexaminando o caso.
  insert into public.pesquisa_preco_itens (
    pesquisa_id, tenant_id, numero, codigo, tipo_catalogo, descricao,
    unidade, quantidade, estado, metodo, preco_estimado, preco_total,
    estatisticas, justificativa, ocorrencias, desfechos, erro)
  select v_nova, i.tenant_id, i.numero, i.codigo, i.tipo_catalogo,
         i.descricao, i.unidade, i.quantidade, i.estado, i.metodo,
         i.preco_estimado, i.preco_total, i.estatisticas, i.justificativa,
         i.ocorrencias, i.desfechos, i.erro
    from public.pesquisa_preco_itens i
   where i.pesquisa_id = p_pesquisa;

  -- O par (pesquisa, numero) é único, então ele é a correspondência
  -- exata entre o item antigo e a cópia.
  --
  -- `coletado_em` é COPIADO, e `criado_em` não: a data em que o preço
  -- foi colhido da fonte é um fato e não muda ao ser copiado; a data
  -- em que esta linha passou a existir é outra coisa.
  --
  -- `natureza_valor` é COPIADA, e esquecê-la seria estrago silencioso:
  -- a coluna tem default `'outro'`, e `outro` não é natureza
  -- comparável. Uma revisão que não a copiasse nasceria com TODAS as
  -- referências fora da cesta — cada item viraria `incomplete` sem que
  -- nada tivesse mudado no mérito, e o motivo estaria num default de
  -- schema, invisível para quem olhasse a tela.
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

  -- A trilha registra a revisão na linha NOVA, com o motivo e a
  -- origem. `ator` é quem chamou — o gatilho confere.
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

-- ===============================================================
-- FEATURE FLAG (§40) — nasce DESLIGADA
--
-- Aplicar a migração não liga o módulo.
-- `db.flag_ativa(governanca.FLAG_PESQUISA_PRECOS)` lê esta chave —
-- `flag_price_research`, no padrão inglês das demais flags — e ela
-- entra como 'off'. `do nothing` no conflito
-- para que reaplicar a migração nunca reative uma flag que alguém
-- desligou de propósito.
-- ===============================================================
insert into public.config_app (chave, valor)
values ('flag_price_research', 'off')
on conflict (chave) do nothing;
