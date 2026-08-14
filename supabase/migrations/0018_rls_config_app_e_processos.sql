-- ============================================================
-- 0018 — Fecha a leitura pública de segredos e de processos
--
-- ACHADO (14/08/2026, durante a auditoria do padrão ouro documental):
-- a tabela `config_app` é LEGÍVEL PELA CHAVE ANÔNIMA PÚBLICA do projeto
-- — a mesma chave que vai no navegador de qualquer visitante do app.
-- Ela guarda OPENAI_API_KEY e GOOGLE_API_KEY EM TEXTO PURO. As tabelas
-- `processos` e `revisoes` também são legíveis pela chave anônima e
-- contêm o conteúdo integral dos documentos, os dados do formulário e
-- os nomes dos servidores envolvidos.
--
-- Ou seja: hoje, um GET no endpoint REST com a chave publicável devolve
-- as credenciais dos provedores de IA e todos os processos do município.
--
-- ORDEM DE EXECUÇÃO — a migração NÃO é o primeiro passo:
--
--   1. ROTACIONAR as duas chaves nos provedores (OpenAI e Google) e
--      gravar as novas no painel administrativo. Fechar o acesso sem
--      rotacionar não resolve: as chaves atuais já estiveram expostas e
--      devem ser consideradas comprometidas.
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
