# D — Cotação automática pronta para revisão (26/11/2026)

Os números abaixo foram medidos. Onde a medida não cobre algo, o texto diz.

## 1. Estado de produção antes da mudança

| O quê | Valor conferido |
|---|---|
| Imagem em produção | `sha-5ee9309a5cc5` (api, worker, web) |
| Flags da pesquisa ligadas | `cotacao_automatica_teto`, `precos_saneamento_pre_cesta`, `jev_price_research`, `price_source_pncp_indice`, `price_source_bps`, `precos_relatorio_visual`, `precos_ciencia_emissao`, `unified_quotations`, `referencia_teto_cmed` |
| Fontes que devolvem preço por item | Compras.gov (preços praticados e itens), índice do PNCP; o BPS respondeu `success_empty` em todos os itens observados |
| Importador do PNCP | pausado desde 25/11 (concorria com a coleta pelo banco) |

### Linha de base real

Dados de `api_jobs` e `pesquisa_preco_eventos` da cotação real `505b4321` (materiais de construção, 383 itens, perfil Lei 14.133):

- **Lote `f8ad2119` (26/11, código antigo):** 18 itens em 47 min, ou seja 2,6 min por item. Ficaram prontos 2 de 18 (11%) e 16 foram para "Revisar CV".
- **Seis lotes de 9 a 16/11:** todos terminaram em `SESSION_EXPIRED` com 25 a 30 itens feitos, quando o token do usuário venceu (1 h).
- **Na fila para sempre:** 3 lotes de 16/11 nunca começaram, e outro lote da mesma cotação rodou depois deles.
- **Tempo de busca:** cada item levava de 8 a 17 s, mas os eventos saíam a cada ~2 min 10 s.

## 2. Causas e correções

| Sintoma | Causa demonstrada | Correção | Prova |
|---|---|---|---|
| Lote lento e token vencendo no meio | A cada passo de um item, `_preparar_lote` consultava o índice do PNCP (`precos_pncp_buscar`, 1,43 s de média em `pg_stat_statements`) para os ~84 pendentes já buscados: cerca de 2 min por item | Com o recorte fixado pelo worker, o passo só confere se o item ainda pede trabalho. Ao fixar o recorte, as consultas correm em paralelo, com o JWT | `test_passo_com_recorte_fixo_nao_consulta_o_indice_dos_pendentes`, `test_recorte_da_largada_pergunta_ao_indice_em_paralelo_com_o_jwt` (mutação pega) |
| Lote morre em `SESSION_EXPIRED` | O token do usuário dura 1 h | A tela retoma sozinha com a sessão atual (`retomarColeta`). A chave é a do lote que parou | `RETOMAVEIS` em `components/precos.ts`, painel "Retomando a pesquisa" |
| Quem sai e volta não vê o lote | O lote só vinha de `?job=` | `GET /precos/pesquisas/{id}/coleta/atual`. A página usa o lote vivo ou o resumo das últimas 12 h | `test_lote_atual_da_cotacao_para_quem_volta_sem_job_na_url`, e2e `coleta.spec.ts` |
| Lotes duplicados na mesma cotação | Outra chave criava outro job | Lote vivo (atualizado há até 15 min) é devolvido em vez de criar outro | `test_pedir_de_novo_com_lote_vivo_devolve_o_mesmo_sem_fila`, `test_lote_parado_ha_mais_de_15_min_nao_segura_a_cotacao` |
| Planilha importada com o lote rodando ficava de fora | O pedido devolve o lote vivo, cujo recorte já está fixado | Rodada no fim do lote para os itens que chegaram | `test_itens_que_chegam_com_o_lote_rodando_entram_no_fim` |
| Itens só apareciam no fim | A página só recarregava ao terminar | A página recarrega a cada item feito | — |
| CV alto por mistura de produtos | A equivalência não lia classe nem tamanho | Atributos novos: classe AC da argamassa, tamanho da bucha, bitola em polegadas, seção em mm², recarga × vasilhame, conjunto com parafuso, produto personalizado, tipo, adição e classe do cimento, largura e comprimento da fita, cor declarada, qualificador que é o produto (água, caneta, martelo) | `tests/test_cotacao_pronta.py` (mutação pega) |
| 25% exatos passava | `cv > 25%` | `cv_aceito`: estritamente abaixo de 25%, no valor exato | `test_25_por_cento_exatos_vao_para_revisao_e_um_pouco_abaixo_passa` (mutação `<=` pega) |
| Item "pronto" que não era | Preço atípico sem decisão contava como pronto; série curta contava como "Revisar CV" | Desfecho `revisar_atipico`; série abaixo de 3 vira amostra insuficiente | `test_desfecho_do_lote_e_honesto`, `test_desfechos_distinguiveis` |

## 3. Medição antes × depois, com fontes reais

O medidor é `scripts/medir_cotacao_lote.py`. Ele roda o caminho de produção (`pesquisar_em_lote`, teto 5, barreira do CV, triagem pré-cesta) contra o Compras.gov e a busca nacional do PNCP. A primeira execução grava as respostas num recorte, e as duas versões rodam sobre as **mesmas** respostas.

Condições fixas:
- data de corte 26/11/2026, perfil Lei 14.133, Brasil inteiro, janela de 365 dias;
- lote A, `tests/fixtures/lote_cotacao_a.json`, para medir;
- lote B, `tests/fixtures/lote_cotacao_b.json`, reservado com descrições diferentes.

O medidor não usa o índice regional do PNCP de produção nem o JEV; produção usa os dois.

| | Lote A antes | Lote A depois | Lote B antes | Lote B depois |
|---|---|---|---|---|
| Itens importados | 20 | 20 | 20 | 20 |
| Marcados prontos sem edição | 2 (10%) | 3 (15%) | 6 (30%) | 4 (20%) |
| **Prontos válidos na auditoria** | **1 (5%)** | **3 (15%)** | **4 (20%)** | **4 (20%)** |
| Prontos inválidos | 1: bucha S6 com cesta só de S10 | 0 | 2: bucha com e sem parafuso; martelo de unha com martelo de bola | 0 |
| Revisar CV | 12 | 5 | 10 | 8 |
| Revisar preço atípico | — | 2 | — | 1 |
| Revisar similaridade / amostra curta | 2 | 9 | 3 | 6 |
| Sem referência compatível | 1 | 1 | 1 | 1 |
| Duração do lote, rede ao vivo | 610 s | ver nota | 596 s | ver nota |
| Primeira proposta, rede ao vivo | 97 s | ver nota | 66 s | ver nota |
| Chamadas à rede | 52 | 0 (recorte) | 52 | 0 (recorte) |

**A medida principal**, prontos válidos sem edição sobre itens importados, foi de **1/20 para 3/20 no lote A** e de **4/20 para 4/20 no lote B**. Os prontos falsos foram a zero nos dois lotes.

**Lote A ao vivo, código novo, sem recorte** (`medicao/a-depois-vivo.json`; as fontes mudam entre consultas):
- 4/20 prontos (20%), os quatro válidos na auditoria: argamassa AC 2, caneta esferográfica azul com CV de 10,44% e cinco esferográficas azuis, copo 200 ml e água em recarga;
- primeira proposta em **32 s**, contra 97 s antes;
- lote em 589 s, contra 610 s antes, limitado pela rede das fontes;
- 58 chamadas, contra 52, por causa da expansão de termos nas amostras curtas.

**Nota sobre tempo.** No medidor, a busca ao vivo leva de 9 a 75 s por item, e esse tempo é das fontes, não do código. O ganho de tempo que muda a experiência do servidor está em produção: ~2 min por item gastos fora da busca, que a correção elimina. A conferência pós-deploy está na seção 5.

### Item antes perdido que passou a chegar pronto

**Argamassa colante AC 2, saco de 20 kg.**
- **Antes:** "Revisar CV", 29,29%, porque a série misturava AC-I e AC-III.
- **Depois:** pronta com 5 referências que declaram "tipo: AC II", CV de 16,65%.
- **Referência que comprova:** PNCP `46223715000104-1-000097/2026` (ARGAMASSA COLANTE AC-II, SACO COM 20KG, R$ 27,40), com o link do edital no relatório.

**Água mineral, garrafão de 20 L, recarga.**
- **Antes:** CV de 53%, mistura de recarga com garrafão.
- **Depois:** pronta com 3 recargas ou retornáveis, CV de 12,50% (PNCP `83211391000110-1-000032/2026`, R$ 11,91).

### Casos que ficaram corretamente em revisão

- **Caneta esferográfica azul.** A cesta agora tem só esferográficas, de R$ 0,46 a R$ 0,71, com CV de 18,68%. A análise crítica sinalizou um preço atípico e quem decide é o servidor.
  - Antes, a série tinha caneta de metal, caneta personalizada e indicador laser, com CV de 42%.
- **Vassoura de piaçava, grampeador 26/6, alicate de corte 6" e saco de lixo 100 L.** O CV continua entre 31% e 38% entre referências comparáveis. A descrição do item não fixa o que explica a diferença: capacidade em folhas, espessura em micras, material. A série vai inteira para o servidor.
- **Colher de pedreiro 8".** Há 19 elegíveis, de R$ 6,80 a R$ 22,97, e a cesta proposta fica com CV de 32,06%. Antes, outra ordenação dava 17,63%. Não se escolhe o subconjunto de menor CV.

### Ainda pendentes, com a causa

| Item | Causa | O que destrava |
|---|---|---|
| Tinta látex 18 L, cabo 4 mm², água sanitária 1 L, detergente 500 ml | Recuperação: as fontes devolveram outro produto (tinta de pincel marcador) ou converteram o volume como se fosse quantidade (frasco de 1000 ml virou 1000 unidades) | Termos e conversão de volume por item; fica para a próxima rodada |
| Papel A4 75 g, resma | A busca nacional devolveu papel colorido, com 2 elegíveis | Índice regional do PNCP ou o catálogo (CATMAT) |
| Serviço de recarga de extintor e de limpeza de caixa d'água | Sem referência de serviço nas fontes medidas | Cotação direta |

## 4. Fora do escopo desta entrega

- **Conversão de volume em "embalagem":** a fonte informa a capacidade em ml, e o sistema a usa como fator de quantidade. Essas linhas não entram na cesta (ficam "para conferência"), mas tiram elegíveis.
- **Importador do PNCP:** continua pausado. Religá-lo volta a disputar o banco com a coleta.
