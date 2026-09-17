-- ############################################################
-- ##  0023 — Flag da consolidação de demandas
-- ##
-- ##  ESTADO: APLICÁVEL. Uma linha em `config_app`, com valor
-- ##  'off'. Não cria tabela, não altera coluna, não toca RLS.
-- ##
-- ##  NÃO APLICADA EM PRODUÇÃO nesta entrega, conforme o escopo.
-- ############################################################

-- ===============================================================
-- POR QUE NÃO HÁ TABELA NOVA AQUI
--
-- O escopo previa quatro tabelas — `solicitacoes_despesa`,
-- `solicitacao_despesa_itens`, `consolidacoes_demanda`,
-- `consolidacao_item_origens` — e mandava, antes disso, verificar se o
-- schema atual já suporta o necessário. Ele suporta.
--
-- O resultado da consolidação é a PLANILHA DO PROCESSO. Ela já mora em
-- `processos.dados->'itens'`, que é jsonb, e é de lá que o DFD, o ETP, o
-- Termo de Referência e o edital leem. A alocação por secretaria e a
-- rastreabilidade até cada arquivo entram em
-- `processos.dados->'consolidacao_demanda'`, exatamente como a pesquisa
-- de preços já grava a proveniência dela em `dados->'pesquisa_preco'`
-- (ver `src/precos/aplicacao.py`).
--
-- Quatro tabelas novas criariam um segundo lugar onde a demanda mora —
-- e os dois divergiriam na primeira vez que alguém editasse a planilha
-- à mão pela tela de sempre. Também exigiriam quatro conjuntos de
-- políticas de RLS para proteger dados que as políticas de `processos`
-- já protegem, porque são dados DO processo.
--
-- O que muda essa conclusão: guardar os PDFs originais no banco, ou
-- consolidar fora de um processo. Nenhum dos dois está no escopo desta
-- entrega. Se entrarem, as tabelas voltam à mesa — com FK, índice,
-- tenant e RLS, como o §35 pede.
-- ===============================================================

-- ===============================================================
-- A FLAG NASCE DESLIGADA
--
-- `do nothing` no conflito para que reaplicar a migração nunca reative
-- uma flag que alguém desligou de propósito — mesma regra da 0021.
--
-- Desligada porque esta etapa muda a ORIGEM da planilha orçamentária do
-- processo. Ligada sem auditoria, colocaria uma quantidade consolidada
-- dentro de um edital antes de alguém conferir a conta.
-- ===============================================================
insert into public.config_app (chave, valor)
values ('flag_demand_consolidation', 'off')
on conflict (chave) do nothing;

comment on table public.config_app is
  'Configuração e feature flags do aplicativo. Flags usam a chave '
  'flag_<nome_em_ingles> e nascem desligadas.';
