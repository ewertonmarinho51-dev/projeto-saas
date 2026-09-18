-- ############################################################
-- ##  0025 — Multi-prefeituras: módulos, servidores, funções,
-- ##            portarias e assinaturas institucionais
-- ##
-- ##  ESTADO: APLICÁVEL. Cria tabelas novas, acrescenta colunas
-- ##  NULLABLE em `tenants` e não altera nenhuma linha existente.
-- ##  Não mexe em política de RLS já instalada, não remove
-- ##  coluna, não toca em `config_orgaos` nem em `secretarias`.
-- ##
-- ##  NÃO APLICADA EM PRODUÇÃO. Quando for, este cabeçalho
-- ##  registra a data, como a 0022, a 0023 e a 0024.
-- ############################################################

-- ===============================================================
-- O QUE JÁ EXISTIA — e por isso NÃO foi recriado
--
-- A auditoria do schema (18/09/2026) encontrou pronto:
--
--   `tenants`      — id, slug, nome, uf, ativo
--   `secretarias`  — tenant_id, nome, sigla, ativo, identidade visual
--                    COMPLETA (cabecalho/rodape/marca + _img + _pct,
--                    padrao) e `origem_orgao_id`, que é o espelho do
--                    legado `config_orgaos`
--   `usuarios`     — tenant_id, secretaria_id, papel, papel_governanca,
--                    auth_user_id
--   `processos`    — tenant_id, secretaria_id, auth_user_id, dados,
--                    documentos, snapshot
--
-- E, em `src/contexto.py`, o RESOLVEDOR DE IDENTIDADE já implementa a
-- herança que o escopo pede: secretaria → município → nenhuma. Ele não
-- foi duplicado. Esta migração dá a ele dados novos para resolver, não
-- um concorrente.
--
-- Os auxiliares de RLS da 0020 — `tenant_do_jwt()`, `secretaria_do_jwt()`,
-- `e_admin()`, `pode_ler_processo()` — são reusados em TODA política
-- abaixo. Nenhuma política nova inventa seu próprio jeito de descobrir
-- quem é o usuário.
--
-- A trilha de auditoria também já existe: `governanca_eventos` mais
-- `registrar_evento_governanca()`. O §48 do escopo se resolve nela, e
-- não numa tabela de log paralela.
-- ===============================================================

-- ===============================================================
-- A DESCOBERTA QUE MUDA O MODELO DO ESCOPO
--
-- O escopo lista `documentos` como se fosse tabela. NÃO É: os documentos
-- vivem em `processos.documentos`, uma coluna jsonb, e `processos.snapshot`
-- guarda o bundle de blocos versionados (`blocos.snapshot_bundle`).
--
-- Criar uma tabela `documentos` agora significaria duas verdades sobre
-- onde o documento mora, e elas divergiriam na primeira edição feita
-- pela tela de sempre — exatamente o que a 0023 recusou fazer com a
-- consolidação de demanda.
--
-- Então as duas tabelas de snapshot abaixo são chaveadas por
-- `(processo_id, doc_key)`, que é como o documento é de fato
-- identificado neste sistema.
-- ===============================================================

-- ---------------------------------------------------------------
-- A) DADOS INSTITUCIONAIS DA PREFEITURA (§8)
--
-- Todas NULLABLE. Nenhum dado é inventado: prefeitura cadastrada antes
-- desta migração continua com os campos vazios até alguém preenchê-los.
-- `add column` com default nulo não reescreve a tabela no PG 11+.
-- ---------------------------------------------------------------
alter table public.tenants add column if not exists nome_oficial text;
alter table public.tenants add column if not exists cnpj          text;
alter table public.tenants add column if not exists sigla         text;
alter table public.tenants add column if not exists cidade        text;
alter table public.tenants add column if not exists endereco      text;
alter table public.tenants add column if not exists telefone      text;
alter table public.tenants add column if not exists email         text;
alter table public.tenants add column if not exists site          text;

-- ---------------------------------------------------------------
-- B) MÓDULOS POR PREFEITURA (§9)
--
-- A relação com a flag global é de CONJUNÇÃO, não de substituição:
--
--   flag global (config_app)  = o módulo existe tecnicamente
--   tenant_modulos            = esta prefeitura contratou/habilitou
--
-- Dois sistemas de flag seriam o "não criar dois sistemas concorrentes"
-- que o escopo proíbe. Este é o segundo NÍVEL do mesmo sistema, e a
-- resolução (`src/modulos.py`) exige os dois ligados.
-- ---------------------------------------------------------------
create table if not exists public.tenant_modulos (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants(id),
  modulo        text not null,
  habilitado    boolean not null default false,
  configuracao  jsonb   not null default '{}'::jsonb,
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  unique (tenant_id, modulo)
);

create index if not exists idx_tenant_modulos_tenant
  on public.tenant_modulos (tenant_id, modulo) where habilitado;

-- ---------------------------------------------------------------
-- C) MÓDULOS POR SECRETARIA (§10)
--
-- Três estados, e o default é HERDAR: secretaria criada depois de um
-- módulo ser ligado no tenant já nasce com ele, sem cadastro manual.
--
-- A regra que o CHECK não consegue expressar — "secretaria nunca habilita
-- módulo proibido no tenant" — mora em `src/modulos.py` e tem prova. Um
-- CHECK aqui precisaria consultar outra tabela, o que em PostgreSQL
-- exigiria gatilho; e gatilho que valida hierarquia de configuração
-- transforma erro de tela em erro de banco, sem ganho de contenção:
-- quem escreve aqui é `e_admin()` do próprio tenant, não o público.
-- ---------------------------------------------------------------
create table if not exists public.secretaria_modulos (
  id             uuid primary key default gen_random_uuid(),
  secretaria_id  uuid not null references public.secretarias(id),
  tenant_id      uuid not null references public.tenants(id),
  modulo         text not null,
  estado         text not null default 'HERDAR'
                 check (estado in ('HERDAR', 'HABILITADO', 'DESABILITADO')),
  criado_em      timestamptz not null default now(),
  atualizado_em  timestamptz not null default now(),
  unique (secretaria_id, modulo)
);

create index if not exists idx_secretaria_modulos_sec
  on public.secretaria_modulos (secretaria_id, modulo);

-- ---------------------------------------------------------------
-- D) SERVIDORES (§15)
--
-- SEM CPF, e isso é decisão registrada: o escopo diz "não exigir CPF se
-- não houver necessidade funcional", e não há. O que o documento precisa
-- é nome, cargo, matrícula e função — nenhum deles é dado sensível. Um
-- CPF guardado "por via das dúvidas" é uma obrigação de LGPD adquirida
-- sem contrapartida.
-- ---------------------------------------------------------------
create table if not exists public.servidores (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants(id),
  nome          text not null,
  matricula     text,
  cargo         text,
  email         text,
  telefone      text,
  ativo         boolean not null default true,
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

create index if not exists idx_servidores_tenant
  on public.servidores (tenant_id, ativo);
create index if not exists idx_servidores_nome
  on public.servidores (tenant_id, lower(nome));

-- ---------------------------------------------------------------
-- E) VÍNCULO SERVIDOR × SECRETARIA, COM HISTÓRICO (§16)
--
-- Tabela própria em vez de `servidores.secretaria_id` porque servidor
-- muda de secretaria, e um documento de 2025 precisa dizer onde ele
-- estava em 2025 — não onde está hoje. Guardar só o vínculo corrente
-- faria o histórico mentir na primeira transferência.
-- ---------------------------------------------------------------
create table if not exists public.servidor_vinculos (
  id            uuid primary key default gen_random_uuid(),
  servidor_id   uuid not null references public.servidores(id),
  secretaria_id uuid not null references public.secretarias(id),
  tenant_id     uuid not null references public.tenants(id),
  cargo         text,
  data_inicio   date not null default current_date,
  data_fim      date,
  ativo         boolean not null default true,
  criado_em     timestamptz not null default now(),
  check (data_fim is null or data_fim >= data_inicio)
);

create index if not exists idx_vinculos_servidor
  on public.servidor_vinculos (servidor_id, data_inicio desc);
create index if not exists idx_vinculos_secretaria
  on public.servidor_vinculos (secretaria_id, ativo);

-- ---------------------------------------------------------------
-- F) FUNÇÕES ADMINISTRATIVAS (§17)
--
-- Tabela de domínio, e não `text` livre: o escopo pede "evitar strings
-- livres espalhadas pelo código", e uma FK é o único jeito de o banco
-- recusar `EQUIPE_PLANEJAMENTO ` com espaço no fim.
--
-- Cargo e função são coisas diferentes: `servidores.cargo` é o vínculo
-- funcional (Agente Administrativo); `funcao` é o papel no processo
-- (Integrante da Equipe de Planejamento). Um secretário municipal tem um
-- cargo e três funções.
-- ---------------------------------------------------------------
create table if not exists public.funcoes_administrativas (
  codigo    text primary key,
  rotulo    text not null,
  descricao text,
  ordem     int  not null default 100
);

insert into public.funcoes_administrativas (codigo, rotulo, ordem) values
  ('RESPONSAVEL_DEMANDA',            'Responsável pela Demanda',              10),
  ('EQUIPE_PLANEJAMENTO',            'Integrante da Equipe de Planejamento',  20),
  ('COORDENADOR_EQUIPE_PLANEJAMENTO','Coordenador da Equipe de Planejamento', 21),
  ('SECRETARIO',                     'Secretário Municipal',                  30),
  ('AUTORIDADE_COMPETENTE',          'Autoridade Competente',                 31),
  ('ORDENADOR_DESPESAS',             'Ordenador de Despesas',                 32),
  ('PREGOEIRO',                      'Pregoeiro',                             40),
  ('AGENTE_CONTRATACAO',             'Agente de Contratação',                 41),
  ('FISCAL_CONTRATO',                'Fiscal do Contrato',                    50),
  ('GESTOR_CONTRATO',                'Gestor do Contrato',                    51)
on conflict (codigo) do nothing;

-- ---------------------------------------------------------------
-- G) SERVIDOR × FUNÇÃO (§18)
--
-- `origem_designacao` registra DE ONDE a função veio — cargo, portaria,
-- designação avulsa ou cadastro. Sem isso, o sistema saberia que alguém
-- é pregoeiro e não saberia dizer por qual ato, que é justamente o que
-- um documento administrativo precisa citar.
-- ---------------------------------------------------------------
create table if not exists public.servidor_funcoes (
  id                uuid primary key default gen_random_uuid(),
  servidor_id       uuid not null references public.servidores(id),
  secretaria_id     uuid references public.secretarias(id),
  tenant_id         uuid not null references public.tenants(id),
  funcao            text not null references public.funcoes_administrativas(codigo),
  origem_designacao text not null default 'CADASTRO'
                    check (origem_designacao in
                           ('CARGO', 'PORTARIA', 'DESIGNACAO', 'CADASTRO')),
  portaria_id       uuid,
  data_inicio       date not null default current_date,
  data_fim          date,
  ativo             boolean not null default true,
  criado_em         timestamptz not null default now(),
  check (data_fim is null or data_fim >= data_inicio)
);

create index if not exists idx_servidor_funcoes_busca
  on public.servidor_funcoes (tenant_id, secretaria_id, funcao, ativo);

-- ---------------------------------------------------------------
-- H) PORTARIAS (§19, §20)
--
-- `tipo` é aberto a mais do que Equipe de Planejamento desde o primeiro
-- dia, porque o escopo avisa: "não codificar tudo exclusivamente para
-- equipe de planejamento".
--
-- `status` é DECLARADO e não derivado da data. Parece redundante com a
-- vigência e não é: uma portaria pode ser REVOGADA antes do fim da
-- vigência, e nenhuma conta de data descobre isso. O resolvedor usa os
-- dois — status e janela — e a regra está em `src/portarias.py`.
-- ---------------------------------------------------------------
create table if not exists public.portarias (
  id                    uuid primary key default gen_random_uuid(),
  tenant_id             uuid not null references public.tenants(id),
  secretaria_id         uuid references public.secretarias(id),
  numero                text not null,
  ano                   int  not null,
  tipo                  text not null default 'EQUIPE_PLANEJAMENTO'
                        check (tipo in ('EQUIPE_PLANEJAMENTO', 'PREGOEIRO',
                                        'AGENTE_CONTRATACAO', 'FISCAL',
                                        'GESTOR', 'COMISSAO', 'OUTRO')),
  descricao             text,
  data_publicacao       date,
  data_inicio_vigencia  date not null,
  data_fim_vigencia     date,
  status                text not null default 'RASCUNHO'
                        check (status in ('RASCUNHO', 'ATIVA', 'REVOGADA',
                                          'EXPIRADA', 'FUTURA')),
  arquivo               text,
  hash_arquivo          text,
  observacao            text,
  criado_em             timestamptz not null default now(),
  atualizado_em         timestamptz not null default now(),
  check (data_fim_vigencia is null
         or data_fim_vigencia >= data_inicio_vigencia)
);

create index if not exists idx_portarias_vigencia
  on public.portarias (tenant_id, secretaria_id, tipo,
                       data_inicio_vigencia, data_fim_vigencia);
create unique index if not exists idx_portarias_numero_ano
  on public.portarias (tenant_id, numero, ano, tipo);

alter table public.servidor_funcoes
  drop constraint if exists servidor_funcoes_portaria_fk;
alter table public.servidor_funcoes
  add constraint servidor_funcoes_portaria_fk
  foreign key (portaria_id) references public.portarias(id);

-- ---------------------------------------------------------------
-- I) MEMBROS DA PORTARIA (§22)
--
-- FK para `servidores`, nunca nome em texto. O escopo é explícito:
-- "nunca gravar o nome como única referência". Nome solto impede saber
-- que o Antonio da portaria 003 é o mesmo Antonio que saiu da prefeitura.
-- ---------------------------------------------------------------
create table if not exists public.portaria_membros (
  id           uuid primary key default gen_random_uuid(),
  portaria_id  uuid not null references public.portarias(id) on delete cascade,
  servidor_id  uuid not null references public.servidores(id),
  tenant_id    uuid not null references public.tenants(id),
  funcao       text not null references public.funcoes_administrativas(codigo),
  ordem        int  not null default 100,
  ativo        boolean not null default true,
  criado_em    timestamptz not null default now(),
  unique (portaria_id, servidor_id, funcao)
);

create index if not exists idx_portaria_membros
  on public.portaria_membros (portaria_id, ordem) where ativo;

-- ---------------------------------------------------------------
-- J) SNAPSHOT DA IDENTIDADE VISUAL DO DOCUMENTO (§14)
--
-- CRÍTICO, e a razão cabe numa frase: se a prefeitura trocar a logo
-- amanhã, o edital publicado ontem não pode mudar. O timbrado faz parte
-- do documento, não da tela.
--
-- Chaveado por `(processo_id, doc_key)` porque não existe tabela
-- `documentos` — ver o bloco no topo.
-- ---------------------------------------------------------------
create table if not exists public.documento_identidades (
  id            uuid primary key default gen_random_uuid(),
  processo_id   uuid not null references public.processos(id) on delete cascade,
  doc_key       text not null,
  tenant_id     uuid not null references public.tenants(id),
  secretaria_id uuid references public.secretarias(id),
  origem        text not null check (origem in ('secretaria', 'municipio', 'nenhuma')),
  identidade    jsonb not null,
  hash_identidade text not null,
  versao        int  not null default 1,
  criado_em     timestamptz not null default now(),
  unique (processo_id, doc_key, versao)
);

create index if not exists idx_doc_identidades
  on public.documento_identidades (processo_id, doc_key);

-- ---------------------------------------------------------------
-- K) SIGNATÁRIOS DO DOCUMENTO, COM SNAPSHOT (§33)
--
-- As colunas `*_snapshot` são cópias deliberadas, e duplicação aqui é o
-- objetivo, não o defeito: se o servidor sair da prefeitura, se mudar de
-- cargo, se a portaria for revogada, o documento assinado continua
-- dizendo o que dizia no dia. `servidor_id` fica para auditoria — quem
-- era essa pessoa no cadastro —, mas a EXPORTAÇÃO lê só o snapshot.
-- ---------------------------------------------------------------
create table if not exists public.documento_signatarios (
  id                      uuid primary key default gen_random_uuid(),
  processo_id             uuid not null references public.processos(id) on delete cascade,
  doc_key                 text not null,
  tenant_id               uuid not null references public.tenants(id),
  servidor_id             uuid references public.servidores(id),
  nome_snapshot           text not null,
  matricula_snapshot      text,
  cargo_snapshot          text,
  funcao_snapshot         text not null,
  secretaria_snapshot     text,
  portaria_numero_snapshot text,
  portaria_data_snapshot  date,
  ordem                   int  not null default 1,
  criado_em               timestamptz not null default now(),
  unique (processo_id, doc_key, ordem)
);

create index if not exists idx_doc_signatarios
  on public.documento_signatarios (processo_id, doc_key, ordem);

-- ===============================================================
-- RLS — reusando os auxiliares da 0020, sem inventar outro jeito
--
-- Leitura: todo mundo do tenant. Servidor precisa ver a lista de
-- servidores e portarias para escolher signatário; esconder isso
-- quebraria a funcionalidade sem proteger nada (são dados institucionais
-- da própria prefeitura, não dado pessoal sensível).
--
-- Escrita: `e_admin()` do PRÓPRIO tenant. Admin municipal administra a
-- casa dele e nada além (§46).
--
-- Os snapshots de documento seguem `pode_ler_processo()`, que é a regra
-- do processo a que pertencem — não uma segunda regra que poderia
-- divergir dela.
-- ===============================================================
do $$
declare
  t text;
begin
  -- Tabelas institucionais do tenant: leitura por tenant, escrita por admin.
  foreach t in array array['tenant_modulos', 'secretaria_modulos',
                           'servidores', 'servidor_vinculos',
                           'servidor_funcoes', 'portarias',
                           'portaria_membros']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, public', t);
    execute format('grant select, insert, update on public.%I to authenticated', t);

    execute format('drop policy if exists "%s_le" on public.%I', t, t);
    execute format(
      'create policy "%s_le" on public.%I for select to authenticated '
      'using (tenant_id = public.tenant_do_jwt())', t, t);

    execute format('drop policy if exists "%s_admin_escreve" on public.%I', t, t);
    execute format(
      'create policy "%s_admin_escreve" on public.%I for insert to authenticated '
      'with check (tenant_id = public.tenant_do_jwt() and public.e_admin())',
      t, t);

    execute format('drop policy if exists "%s_admin_altera" on public.%I', t, t);
    execute format(
      'create policy "%s_admin_altera" on public.%I for update to authenticated '
      'using (tenant_id = public.tenant_do_jwt() and public.e_admin()) '
      'with check (tenant_id = public.tenant_do_jwt() and public.e_admin())',
      t, t);
  end loop;

  -- Domínio de funções: leitura para todos os autenticados, escrita para
  -- ninguém pela rede. A lista é do PRODUTO, não de cada prefeitura —
  -- deixar uma delas renomear `EQUIPE_PLANEJAMENTO` quebraria o código
  -- que casa por esse código.
  execute 'alter table public.funcoes_administrativas enable row level security';
  execute 'revoke all on public.funcoes_administrativas from anon, public';
  execute 'grant select on public.funcoes_administrativas to authenticated';
  execute 'drop policy if exists "funcoes_le" on public.funcoes_administrativas';
  execute 'create policy "funcoes_le" on public.funcoes_administrativas '
          'for select to authenticated using (true)';

  -- Snapshots do documento: seguem a regra do processo.
  foreach t in array array['documento_identidades', 'documento_signatarios']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, public', t);
    execute format('grant select, insert on public.%I to authenticated', t);

    execute format('drop policy if exists "%s_le" on public.%I', t, t);
    execute format(
      'create policy "%s_le" on public.%I for select to authenticated '
      'using (exists (select 1 from public.processos p '
      '               where p.id = processo_id '
      '                 and public.pode_ler_processo(p.tenant_id, p.secretaria_id)))',
      t, t);

    execute format('drop policy if exists "%s_grava" on public.%I', t, t);
    execute format(
      'create policy "%s_grava" on public.%I for insert to authenticated '
      'with check (tenant_id = public.tenant_do_jwt() and exists ('
      '  select 1 from public.processos p where p.id = processo_id '
      '    and public.pode_ler_processo(p.tenant_id, p.secretaria_id)))',
      t, t);
  end loop;
end
$$;

-- ===============================================================
-- SNAPSHOT É IMUTÁVEL — e o banco é quem garante
--
-- Sem UPDATE e sem DELETE para `authenticated` nas duas tabelas de
-- snapshot: um documento assinado não muda de signatário nem de timbrado
-- depois de emitido. A correção de um erro é uma emissão NOVA, com
-- `versao` maior, não a reescrita da anterior.
--
-- É a mesma decisão da 0020 para `governanca_eventos`: sem política de
-- escrita, nem o admin altera.
--
-- `service_role` ENTRA no revoke, e a primeira versão deste arquivo o
-- esquecera — a conferência do fim pegou, com o nome das quatro
-- concessões que sobravam. É a mesma lição da 0021: o default do
-- Supabase concede `arwdDxtm` à credencial de servidor, então NÃO
-- ESCREVER a linha não significa não conceder o privilégio.
--
-- E a credencial de servidor apagar o que o admin não pode apagar é a
-- contradição que a 0024 documentou. Apagar processo continua
-- funcionando: as FK são `on delete cascade`, e ação referencial roda
-- por dentro da constraint, sem exigir DELETE de quem disparou.
-- ===============================================================
revoke update, delete, truncate on public.documento_identidades
  from service_role, authenticated, anon, public;
revoke update, delete, truncate on public.documento_signatarios
  from service_role, authenticated, anon, public;

-- TRUNCATE fora do alcance da credencial de servidor, como a 0024
-- estabeleceu. O `alter default privileges` dela já cobre tabela nova,
-- mas o revoke explícito aqui torna o arquivo verdadeiro por si —
-- ele afirma o estado final, não um delta.
revoke truncate on public.tenant_modulos, public.secretaria_modulos,
                   public.servidores, public.servidor_vinculos,
                   public.servidor_funcoes, public.portarias,
                   public.portaria_membros, public.funcoes_administrativas,
                   public.documento_identidades, public.documento_signatarios
  from service_role, authenticated, anon, public;

-- ===============================================================
-- CARIMBO DE ATUALIZAÇÃO — reusando `set_atualizado_em()` da 0009
-- ===============================================================
do $$
declare
  t text;
begin
  foreach t in array array['tenant_modulos', 'secretaria_modulos',
                           'servidores', 'portarias']
  loop
    execute format('drop trigger if exists trg_%s_atualizado on public.%I', t, t);
    execute format(
      'create trigger trg_%s_atualizado before update on public.%I '
      'for each row execute function public.set_atualizado_em()', t, t);
  end loop;
end
$$;

-- ===============================================================
-- CONFERÊNCIA — a migração falha se não cumpriu o que afirma
--
-- Mesmo padrão da 0024, pela mesma razão: `create table if not exists`
-- que não cria, `revoke` que não pega e `create policy` que não instala
-- não levantam erro. Um arquivo que declara isolamento precisa MEDIR.
-- ===============================================================
do $$
declare
  faltou text;
  novas text[] := array['tenant_modulos', 'secretaria_modulos', 'servidores',
                        'servidor_vinculos', 'funcoes_administrativas',
                        'servidor_funcoes', 'portarias', 'portaria_membros',
                        'documento_identidades', 'documento_signatarios'];
begin
  -- 1) as dez tabelas existem
  select string_agg(t, ', ') into faltou
  from unnest(novas) t
  where to_regclass('public.' || t) is null;
  if faltou is not null then
    raise exception 'A 0025 não criou: %', faltou;
  end if;

  -- 2) todas com RLS ligado
  select string_agg(c.relname, ', ') into faltou
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public' and c.relname = any(novas)
    and not c.relrowsecurity;
  if faltou is not null then
    raise exception 'A 0025 deixou tabela sem RLS: %', faltou;
  end if;

  -- 3) `anon` não alcança nada
  select string_agg(distinct table_name, ', ') into faltou
  from information_schema.role_table_grants
  where table_schema = 'public' and table_name = any(novas)
    and grantee in ('anon', 'PUBLIC');
  if faltou is not null then
    raise exception 'A 0025 deixou grant para anon em: %', faltou;
  end if;

  -- 4) snapshot é imutável: nenhum UPDATE/DELETE de rede
  select string_agg(distinct table_name || '→' || privilege_type, ', ')
    into faltou
  from information_schema.role_table_grants
  where table_schema = 'public'
    and table_name in ('documento_identidades', 'documento_signatarios')
    and privilege_type in ('UPDATE', 'DELETE', 'TRUNCATE')
    and grantee in ('authenticated', 'anon', 'PUBLIC', 'service_role');
  if faltou is not null then
    raise exception
      'A 0025 afirma snapshot imutável e deixou escrita: %', faltou;
  end if;

  -- 5) o domínio de funções foi semeado
  if (select count(*) from public.funcoes_administrativas) < 10 then
    raise exception
      'A 0025 não semeou as funções administrativas — o FK de '
      'servidor_funcoes e portaria_membros ficaria sem destino';
  end if;
end
$$;
