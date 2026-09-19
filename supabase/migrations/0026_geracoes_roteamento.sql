-- ############################################################
-- ##  0026 — Sob qual política o documento foi gerado
-- ##
-- ##  ESTADO: APLICÁVEL. Acrescenta UMA coluna jsonb NULLABLE a
-- ##  `geracoes`. Não altera nenhuma linha existente, não cria
-- ##  tabela, não toca em política de RLS nem em grant.
-- ##
-- ##  APLICADA EM PRODUÇÃO em 19/09/2026. Medição depois:
-- ##  coluna jsonb e NULLABLE; 168 linhas preservadas; nenhuma
-- ##  delas com política registrada, que é o correto — as
-- ##  gerações anteriores correram sob política desconhecida e
-- ##  NULO diz exatamente isso; índice parcial no lugar.
-- ############################################################

-- ===============================================================
-- O BURACO QUE ESTA MIGRAÇÃO FECHA
--
-- Em 19/09/2026 o operador ligou `OMNIROUTE_ROUTING_ENABLED` em
-- produção e pediu confirmação do efeito. Não havia como dar: a tabela
-- `geracoes` guardava motor, modelo, duração, tokens, status e
-- fallback — e NADA sobre a política de roteamento em vigor.
--
-- A pergunta "este edital foi gerado sob a política?" só podia ser
-- respondida por dedução: olhar o motor e supor. Dedução não é trilha
-- de auditoria, e um edital vira ato administrativo.
--
-- Pior: `ai_gateway.telemetria()` já devolvia exatamente esses campos
-- —  `task_type`, `routing_policy`, `critica`, `provider`, `gateway` e
-- `routing_enabled` — e não era chamada em lugar nenhum do sistema.
-- Estava escrita e nunca ligada. Esta migração é o destino dela.
--
-- POR QUE UMA COLUNA jsonb E NÃO SEIS COLUNAS
--
-- Porque `telemetria()` é a fonte única desses campos, e espalhá-los em
-- colunas escalares criaria uma segunda definição do que é telemetria
-- de roteamento — que divergiria na primeira vez que alguém
-- acrescentasse um campo lá e esquecesse aqui. É a mesma decisão que
-- `rag_trace` (0011) tomou, pela mesma razão, e reusar o padrão é
-- melhor que inventar o segundo.
--
-- O QUE NÃO ENTRA AQUI
--
-- Nada de prompt, nada de resposta, nada de chave de API. A telemetria
-- é metadado de roteamento e só — `tests/test_ai_gateway.py` mede isso,
-- e a prova nova mede de novo no caminho do registro.
-- ===============================================================

alter table public.geracoes
  add column if not exists roteamento jsonb;

-- Índice só sobre a pergunta que se faz de verdade: "quais gerações
-- correram SEM a política?". Parcial, porque o caso interessante é o
-- minoritário — e um índice sobre toda a coluna pagaria por linhas que
-- ninguém consulta.
create index if not exists idx_geracoes_sem_politica
  on public.geracoes ((roteamento->>'routing_enabled'))
  where roteamento is not null;

-- ===============================================================
-- CONFERÊNCIA — a migração falha se não cumpriu o que afirma
--
-- Mesmo padrão da 0024 e da 0025: `add column if not exists` que não
-- acrescenta não levanta erro. Um arquivo que declara uma coluna
-- precisa MEDIR que ela existe.
-- ===============================================================
do $$
begin
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'geracoes'
      and column_name = 'roteamento' and data_type = 'jsonb'
  ) then
    raise exception
      'A 0026 não criou `geracoes.roteamento` como jsonb';
  end if;

  -- A coluna nasce NULA em toda linha antiga, e tem que ser assim: as
  -- gerações anteriores a esta migração correram sob política
  -- desconhecida, e inventar `false` para elas seria afirmar o que
  -- ninguém mediu. NULO quer dizer "não registrado", e é a verdade.
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'geracoes'
      and column_name = 'roteamento'
      and (is_nullable = 'NO' or column_default is not null)
  ) then
    raise exception
      'A 0026 deixou `roteamento` com NOT NULL ou default — linha '
      'antiga passaria a afirmar uma política que ninguém mediu';
  end if;
end
$$;
