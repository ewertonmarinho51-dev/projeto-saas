# Cotações — matriz de substituição (estado em 16/10/2026)

"Descontinuado" = fora da navegação com a flag ligada; o código continua
existindo como fallback (flag desligada) até a homologação. **Nada foi
removido.** Remoção só depois de: E2E verde em homologação, consumidores
migrados, rollback exercitado e uma janela de observação.

| Existente | Situação com `unified_quotations` ligada | Consumidores | Próximo passo |
|---|---|---|---|
| `precos_ui._render_lista` (Minhas pesquisas) | descontinuado → `cotacoes_ui._render_lista` | `render_precos` | remover após homologação |
| `precos_ui._render_banco` + `cesta.salvar_consulta_como_pesquisa` (consulta avulsa que cria UMA pesquisa por consulta) | descontinuado → busca no item da cotação (`cotacoes.pesquisar_item`) | `render_precos`; `tests/test_pricebank_*` | remover após homologação; o serviço de cesta permanece |
| `precos_ui._render_nova` | descontinuado → `cotacoes_ui._render_nova` | `render_precos` | remover |
| `precos_ui._render_itens` + `_render_editor_de_itens` | descontinuado → painel de itens (incluir, editar, retirar, reordenar) | `render_precos` | remover; `render_importacao` é COMPARTILHADO e fica |
| `precos_ui._render_execucao` + `execucao.executar_lote` | descontinuado → `cotacoes.pesquisar_em_lote` | `render_precos`; `scripts/benchmark_precos.py`; `tests/test_precos_fase4.py`, `test_pricebank_lote_210.py` | **consolidar**: `executar_lote` sobrescrevia decisões humanas numa nova busca; migrar o benchmark real e as provas para `pesquisar_em_lote`, depois remover |
| `precos_ui._render_revisao` | descontinuado → painéis de busca e cesta do item | `render_precos` | remover; `_render_detalhe`, `_render_filtros`, `_render_cotacao`, `render_metodo_do_item`, `render_excecao_do_item` são COMPARTILHADOS |
| `precos_ui._render_resumo` | descontinuado → cabeçalho + painel "Relatório" | `render_precos` | remover; `_render_relatorios` e `_render_aplicacao` são COMPARTILHADOS |
| `busca.py`, `cesta.py`, `estatistica.py`, `perfil.py`, `matching.py`, `fontes.py`, `unidades.py` | **preservados** (uma coleta, uma cesta, um cálculo) | ambos | — |
| `repositorio.py` + 0021 | **preservado**, migração aditiva 0029 | ambos | aplicar 0029 com autorização |
| `relatorio.py` | **preservado e evoluído** (um gerador; formato 2 do hash; formato 1 conferível) | ambos | — |
| `decisoes.py`, `jev.py`, `ai_gateway.py` | **preservados**; `seletor.py` orquestra por cima, sem segundo gateway | seletor | calibração humana |
| `cotacao.py` (cotação direta) | **preservado** + `fornecedores_sugeridos` | ambos | — |
| `aplicacao.py` | **preservado**; evento grava o identificador aplicado | ambos | — |

Não há duas tabelas, dois caches nem dois cálculos de preço. Os dois
botões ("Pesquisar preços" e "Cotação automática") são dois comandos do
MESMO serviço sobre o MESMO item.
