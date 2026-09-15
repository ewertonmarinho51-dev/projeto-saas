-- ############################################################
-- ##  0022 — Nome do processo
-- ##
-- ##  ESTADO: APLICÁVEL. Uma coluna, aditiva, com default que
-- ##  preenche todas as linhas existentes sem reescrita de dados.
-- ############################################################

-- ===============================================================
-- POR QUE SÓ UMA COLUNA
--
-- O painel de processos mostra nome, datas, STATUS, ETAPA ATUAL e
-- PROGRESSO. Só o nome vira coluna. Os outros três são DERIVADOS de
-- `etapa`, `documentos` e `aprovados`, que já existem desde a 0001.
--
-- Guardar status e progresso em colunas próprias criaria um segundo
-- lugar onde a verdade mora — e os dois divergem na primeira vez que
-- alguém aprova um documento por um caminho que esqueceu de atualizar o
-- carimbo. O painel passaria a exibir "concluído" para um processo com
-- três documentos pendentes, e ninguém saberia qual dos dois acreditar.
--
-- Derivar custa uma função pura (`src/processos.py`) e não pode
-- divergir: a fonte é a mesma que o wizard usa para navegar.
--
-- O nome é diferente: ele é uma DECISÃO do servidor, não um resumo do
-- estado. Não existe de onde derivá-lo.
-- ===============================================================
alter table public.processos
  add column if not exists nome text not null default '';

comment on column public.processos.nome is
  'Nome livre dado pelo servidor. Vazio significa "sem nome": a '
  'interface exibe órgão e objeto no lugar, e nunca um rótulo '
  'inventado que o servidor não escreveu.';

-- Busca por nome na listagem. `text_pattern_ops` serve ao `ilike
-- 'termo%'`; a busca do painel é por prefixo e por trecho, e para o
-- volume de uma prefeitura (dezenas a centenas de processos) isto
-- basta. Um índice trigram exigiria a extensão `pg_trgm` e não se
-- justifica nesta escala.
create index if not exists processos_nome_idx
  on public.processos (nome text_pattern_ops);

-- ===============================================================
-- RLS: NADA A FAZER, E ISSO É VERIFICÁVEL
--
-- `processos` já tem RLS desde a 0018, e a 0020 reescreveu as políticas
-- sobre `auth.uid()`. Coluna nova entra sob as políticas existentes:
-- quem já podia ler a linha lê o nome, quem não podia continua sem ver.
--
-- Não há grant novo a conceder. O `authenticated` já tem select/update
-- na tabela; o privilégio é por TABELA, não por coluna.
-- ===============================================================
