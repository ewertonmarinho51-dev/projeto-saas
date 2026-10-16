# Cotações — ativação e rollback

Nada disto foi executado em produção. Cada passo depende de autorização
expressa do operador.

## Ordem de ativação

Estado em 16/10/2026: passos 1 a 3 FEITOS com autorização do operador (merge do PR #51, v1.9.0 na VPS, 0029 aplicada, `flag_unified_quotations` = on). O Jev (passo 4) já estava ligado em produção (`flag_jev_price_research` = 1) antes desta entrega; com ele ligado, o seletor consulta a IA só no caso ambíguo, dentro dos tetos, e só recomenda.

1. **Merge** da branch `feature/cotacoes-unificadas-bp-jev` (PR, CI verde).
   Com as flags desligadas, o produto se comporta como antes: a entrada
   continua "Pesquisa de Preços" e as correções do G1 valem para ela.
2. **Migração 0029** (`supabase/migrations/0029_cotacoes_unificadas.sql`) — **FEITO em 16/10/2026** (`m0029_cotacoes_unificadas`, ensaiada antes no projeto descartável; registro no cabeçalho do arquivo):
   seguir o ritual `revisar-migracao` — ensaio em PostgreSQL descartável
   (`GOVDOCS_ENSAIO_PG_DSN` + `tests/test_migracao_0029.py`), revisão do
   agente `revisor-de-banco-e-seguranca`, remover o sufixo no commit que
   aplica, aplicar, conferir catálogo.
3. **Flag `flag_unified_quotations` = on** em homologação; só depois em
   produção. Exige `flag_price_research` ligada.
4. **Jev** (`flag_jev_price_research`) continua OFF até: credencial e
   orçamento aprovados, dataset humano rotulado, meta de falso positivo
   definida pela equipe ANTES do benchmark e
   `docs/jev/calibracao_aprovada.json` assinado. Mesmo ligado, o Jev só
   recomenda.

## Rollback

| Situação | Ação | Efeito |
|---|---|---|
| Tela nova com problema | `flag_unified_quotations` = off | menu volta a "Pesquisa de Preços"; cotações criadas pela tela nova continuam legíveis lá (mesma entidade); itens retirados (`removido_em`) aparecem de novo na tela antiga |
| Jev com problema | `flag_jev_price_research` = off | seletor segue só determinístico, custo 0 |
| Schema 0029 | `docs/cotacoes/0029_rollback.sql` (exportar antes `lote`, `uf`, `removido_em`, `revisao` e as emissões) | eventos com tipos novos ficam na trilha (CHECK recriado `not valid`) |
| Código | reverter os commits G5→G1 na ordem inversa | G1 muda formatos de memória/relatório; relatórios já emitidos continuam conferíveis (formato 1 preservado) |

## O que a tela antiga lê do que a nova grava

- `estatisticas.decisoes` (método e exceção): a tela antiga mostra a
  memória com a exceção e reaplica as decisões no recálculo (código G1 é
  compartilhado).
- `removido_em`, `lote`, `uf`, `revisao`: a tela antiga ignora; o
  relatório gerado por ela exclui itens com `removido_em`.
- Eventos `selecao_sugerida`, `relatorio_emitido`, `excecao_registrada`,
  `item_editado`, `item_removido`: só leitura na trilha.
