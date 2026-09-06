-- ############################################################
-- ##  APLICADA EM PRODUÇÃO em 06/09/2026, com autorização
-- ##  expressa. O sufixo `.NAO_APLICAR` saiu junto.
-- ##
-- ##  A trava existia por uma razão que deixou de valer: em
-- ##  14/08 o app acessava o Supabase SÓ pela chave publicável,
-- ##  e esta migração o teria deixado sem `config_app` — sem
-- ##  chaves de IA e com TODAS as feature flags em OFF, em
-- ##  silêncio. Desde então `db._cliente()` passou a usar
-- ##  SUPABASE_SECRET_KEY, e isso foi CONFERIDO no código antes
-- ##  de aplicar: `db.obter_config()` lê pelo cliente de
-- ##  servidor, que contorna RLS por definição.
-- ##
-- ##  Verificado depois de aplicar, em produção: `service_role`
-- ##  enxerga usuarios=2, config_app=27, processos=6; `anon` é
-- ##  recusado por privilégio.
-- ##
-- ##  O QUE ESTA MIGRAÇÃO NÃO FEZ, e continua pendente: rotacionar
-- ##  OPENAI_API_KEY e GOOGLE_API_KEY. Elas seguem em `config_app`
-- ##  e estiveram legíveis por quem tivesse a chave publicável.
-- ##  Fechar o acesso não desfaz exposição passada — a rotação é
-- ##  decisão do responsável e não foi feita aqui.
-- ############################################################

-- ============================================================
-- 0018 — Fecha a leitura pública de segredos e de processos
--
-- ACHADO (14/08/2026, durante a auditoria do padrão ouro documental):
-- a tabela `config_app` é LEGÍVEL PELA CHAVE PUBLICÁVEL do projeto, e
-- guarda OPENAI_API_KEY e GOOGLE_API_KEY EM TEXTO PURO. As tabelas
-- `processos` e `revisoes` também são legíveis por essa chave e contêm
-- o conteúdo integral dos documentos, os dados do formulário e os nomes
-- dos servidores envolvidos.
--
-- CORREÇÃO DE UMA AFIRMAÇÃO ANTERIOR desta migração: dizia-se aqui que
-- a chave publicável "vai no navegador de qualquer visitante do app".
-- Isso está ERRADO para esta arquitetura. O GovDocs é Streamlit e roda
-- INTEIRO no servidor: o navegador recebe a interface já renderizada,
-- por websocket. `st.secrets` e o cliente Supabase ficam no processo do
-- servidor, e a aplicação NÃO envia a chave ao cliente.
--
-- O que continua verdadeiro, e é o que sustenta esta migração: a chave
-- publicável DEVE ser tratada como pública — é a premissa do modelo do
-- Supabase, que assume a autorização no RLS. Quem obtiver essa chave
-- por qualquer via (painel, backup de configuração, log de plataforma,
-- API de gestão) faz um GET no endpoint REST e recebe as credenciais de
-- IA e os processos do município.
--
-- E o que NÃO está provado: não há evidência de que a chave tenha
-- vazado, nem de que as credenciais de IA tenham sido usadas por
-- terceiros. A prioridade é P0 PREVENTIVA — corrigir com urgência
-- máxima, sem declarar incidente consumado.
--
-- ORDEM DE EXECUÇÃO — a migração NÃO é o primeiro passo:
--
--   1. ROTACIONAR as duas chaves nos provedores (OpenAI e Google) e
--      gravar as novas nos Secrets do servidor. A rotação é medida
--      PRECAUCIONAL: as chaves estiveram acessíveis a quem tivesse a
--      chave publicável, e não há trilha que permita afirmar se isso
--      ocorreu — nem que não ocorreu.
--   2. Conferir se a aplicação continua funcionando com as novas chaves.
--   3. SÓ ENTÃO aplicar esta migração.
--
-- Depois dela, a leitura de `config_app` passa a exigir `service_role`.
-- Verifique antes se o app usa a chave de serviço no servidor; se ele
-- ainda ler a configuração com a chave anônima, a leitura vai falhar —
-- e o correto é migrar a leitura para o servidor, não reabrir o acesso.
--
-- Os DADOS não são tocados: nenhuma linha é lida, alterada ou removida.
-- Idempotente: pode ser reexecutada sem efeito adicional.
-- ============================================================

-- 1. Segredos: nenhum papel da aplicação enxerga a tabela ------------
revoke all privileges on table public.config_app
  from anon, authenticated, public;

alter table public.config_app enable row level security;
alter table public.config_app force row level security;

-- Sem POLÍTICA nenhuma: com RLS ativo e nenhuma policy, todo papel
-- sujeito a RLS lê zero linhas. `service_role` contorna o RLS por
-- definição e continua atendendo o servidor da aplicação.

-- 2. Conteúdo dos processos: escrita fechada para a chave anônima ----
-- A leitura permanece como está para não derrubar o app em produção;
-- o que se elimina agora é a possibilidade de QUALQUER visitante
-- alterar ou apagar processos e jobs de revisão alheios.
revoke insert, update, delete, truncate on table public.processos
  from anon, public;
revoke insert, update, delete, truncate on table public.revisoes
  from anon, public;

-- 3. Registro do que ficou pendente ----------------------------------
comment on table public.config_app is
  'Configuração e segredos da aplicação. Acesso restrito a service_role '
  '(migração 0018). NÃO conceder grants a anon/authenticated.';
comment on table public.processos is
  'PENDENTE (0018): a LEITURA ainda é pública. Fechar exige RLS por '
  'tenant/usuário — ver docs/seguranca-config-app.md, etapa 4.';
