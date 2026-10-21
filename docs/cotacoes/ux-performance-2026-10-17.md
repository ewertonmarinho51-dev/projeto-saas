# Cotações: teto automático, avanço de item e UX global (17/10/2026)

Pacote `PACOTE_CLAUDE_CODE_GOVCONNECT_PERFORMANCE_UX_2026-10-17`. Branch
`claude/cotacoes-ux-performance`, a partir de `main` em `bd5803b`
(v1.9.3). Streamlit 1.64.0, Python 3.11. **Sem merge, sem deploy, sem
migração.**

Flags novas, ambas DESLIGADAS por padrão (sem linha em `config_app`):

| Flag | O que liga |
|---|---|
| `cotacao_automatica_teto` | política de teto da cotação automática (G1) |

G2 a G5 não têm flag: são apresentação, sem efeito em dado. O rollback
deles é reverter os commits.

Skill: `kylezantos/design-motion-principles`, commit `4a9ca87`, MIT,
instalada à mão em `.claude/skills/design-motion-principles` depois de
revisada (só Markdown e HTML de referência, sem scripts). Pesos usados,
como o pacote pediu: Emil Kowalski primário, Jakub Krehel secundário,
Jhey Tompkins pontual.

## Gates

| Gate | Status | Evidência | Pendência |
|---|---|---|---|
| G0 baseline | PASSOU | `bench/ux-antes-*.json`, `ux/antes/` (6 larguras + `medidas.json`) | — |
| G1 teto + desempenho | PASSOU | `tests/test_cotacoes_teto_automatico.py` (21), mutação 5/5, `bench/ux-depois-*.json` | ligar a flag é ato do operador |
| G2 autoavanço | PASSOU | `tests/test_cotacoes_autoavanco.py` (18), mutação 3/3 | — |
| G3 layout | PASSOU com ressalva | `ux/depois/` (7 capturas + `medidas.json`), `tests/test_cotacoes_ux.py` | ver "Ressalvas" |
| G4 sidebar | PASSOU | 15 alternâncias sem erro no navegador; provas de CSS | — |
| G5 loading/motion/status | PASSOU | auditoria abaixo; provas de CSS e estados | ver "Ressalvas" |
| G6 regressão | PASSOU | suíte completa (número no fim deste documento) | testes de leitor de tela e zoom 200% NÃO executados |

## G0 — diagnóstico confirmado no código e no DOM

* `estatistica.selecionar_cesta` marcava TODAS as elegíveis; a cotação
  unificada (`cotacoes.pesquisar_item`) e a legada (`execucao`) gravavam
  todas as candidatas; a consulta pedia 100 por fonte e as duas fontes
  eram sempre consultadas.
* `_form_concluir` gravava e reabria o mesmo item.
* Colunas `[1.05, 2.3, 1.35]`; "Concluir item" abaixo da dobra em TODAS as
  larguras (1003 px em 1920; 9160 px em 360).
* Sidebar: o CSS forçava 264 px nos dois estados e escondia o
  `stSidebarHeader` e o `stToolbar` — o colapso nativo existia
  (`aria-expanded`) e era anulado.
* **Barra azul**: inspecionada no DOM durante uma execução — o único
  elemento no topo era o pseudo-elemento `.stApp[data-test-script-state=
  "running"]::before` (`assets/govconnect.css`, PR #54), com a animação
  `gc-rerun-faixa` oscilando de 15% a 85% em loop. O `stDecoration` do
  Streamlit estava oculto e não participava.

## Antes e depois (valores medidos)

Benchmark sintético (`scripts/benchmark_cotacoes.py`, fontes e banco
dublês, sem rede): 301 candidatas por fonte, duas fontes, 20 itens.

| Indicador | Antes | Depois | Como foi medido |
|---|---|---|---|
| Referências gravadas por item | 542 | **21,5** | linhas no banco dublê ÷ itens |
| Consideradas por item (média / máx.) | 369 / 452 | **13 / 15** | `cesta.na_cesta_do_item` |
| Chamadas a fontes por item | 2,0 | **1,15** | contador da fonte dublê |
| Tempo por item p50 / p95 | 2,01 s / 4,82 s | **0,033 s / 0,047 s** | `perf_counter` por passo |
| Itens com 3+ preços | 18 de 20 | **18 de 20** | mesma cobertura |
| Lote de 210 itens | não medido* | 22,5 s, 19 gravadas e ≤ 15 consideradas por item | `bench/ux-depois-unificado-v301-210itens.json` |
| Relatório Analítico Integral, 5 itens | 191 págs, 11 MB, 33 s | **12 págs, 561 KB, 7,6 s** | `bench/ux-relatorio-com-e-sem-teto.json` (compacto: 5 págs nos dois) |
| Chamadas de IA (Jev) | 0 | 0 | flag do Jev desligada no benchmark; o Jev passa a receber só o gravado (≤ 25 linhas) |
| Cliques para concluir e ir ao próximo item | concluir + clicar o próximo na lista (2) | concluir (1) | fluxo na tela |
| "Concluir item" visível sem rolar | 0 de 6 larguras | 1920, 1440 e 1280 (sidebar recolhida) | `ux/*/medidas.json` |
| Rolagem horizontal | nenhuma | nenhuma | `scrollWidth` |

\* com ~600 referências por item o banco dublê degrada de forma
quadrática; a medida não representaria o servidor.

Com volume normal (6 candidatas por fonte) nada muda além de não gravar
a candidata não comparável: 5 consideradas antes e depois.

## G1 — política única

`estatistica.POLITICA_AUTOMATICA` (`"2026-10-17.teto-15"`): teto 15 na
cesta automática de cada item contando as que já estavam lá; busca que
para de consultar fontes ao chegar a 6 elegíveis (`suficiente`); 50
registros pedidos por fonte; 10 de reserva para o revisor. O que não é
gravado fica CONTADO na trilha (`brutas`, `unicas`, `elegiveis`,
`nao_gravadas`, `fontes_nao_consultadas`, `politica`). Modo manual sem
teto. Desconsiderada não volta; decisão humana preservada. Mesma regra
na rota legada (`execucao.pesquisar_item/executar_lote`, parâmetro
`politica`).

**Revisão .3 (21/10/2026, `"2026-10-21.teto-15.3"`).** A parada em 6
elegíveis (`suficiente`) foi retirada: com amostra farta no primeiro
portal, os demais não eram consultados e a cesta saía de uma fonte só.
Agora toda fonte configurada é consultada (o `limite_por_fonte`
continua: limita quanto se pede, não quais fontes) e as 15 vagas são
repartidas em rodízio entre as fontes, a de maior prioridade normativa
abrindo cada rodada (`estatistica._rodizio_por_fonte`). Dois portais
fartos → 8 + 7. `fontes_nao_consultadas` só aparece em pesquisas
gravadas sob a .2.

## G2 — concluir e avançar

`cotacoes.proximo_item_para_revisao` (pura) + `_avancar_depois_de_concluir`
na tela, chamado só depois de `concluir_item` confirmar. Sem próximo,
abre o painel de conclusão da cotação.

## G3 — Elaborar Cotação

Regiões com nome (`cot_regiao_itens/busca/cesta`). CSS por **espaço
útil** (container query sobre `.stMainBlockContainer`), não pela janela:
≥ 1061 px úteis, três regiões (lista 236, busca flexível, cesta 324,
cesta sticky com rolagem própria); 721–1060, lista em faixa horizontal,
busca e cesta lado a lado; ≤ 720, uma coluna com a cesta ANTES dos
resultados. Cesta: preço, N/mínimo e o próximo passo (pendências logo
acima de "Concluir item"); estatística, método, cotação de fornecedor e
memória recolhidos. Cabeçalho do item curto com selo de situação;
especificação inteira sob demanda; filtros da busca recolhidos;
métricas encontradas/comparáveis/consideradas/descartadas + fontes
consultadas. Ações do cabeçalho sem truncar.

## G4 — sidebar

Colapso NATIVO do Streamlit. O CSS fixa a largura só com
`aria-expanded="true"`; o botão de recolher (do próprio Streamlit) fica
visível no canto, e o de reabrir aparece no canto superior; nomes
acessíveis "Recolher menu" e "Abrir menu". Aberta: recuo de 10 px,
canto de 14 px, sombra leve. Transição de 200 ms (`--gc-shell-ms`),
instantânea com reduced-motion. Topbar e atalho de teclado acompanham o
estado. Celular: começa recolhida (`initial_sidebar_state="auto"`),
abre em sobreposição. Nenhum JS mexe na sidebar.

## G5 — auditoria de movimento (skill, modo Audit) e correções

| # | Achado | Severidade | Correção |
|---|---|---|---|
| 1 | `gc-rerun-faixa`: barra de topo oscilando em loop a cada clique | Crítico | avança num sentido só (0 → 90%, 8 s, desacelerando), some quando há spinner, progresso do lote ou overlay de geração |
| 2 | `gc-generation-motion`: barra do overlay de geração oscilando | Crítico | trecho que corre da esquerda para a direita e recomeça; estático em reduced-motion |
| 3 | GovBot `float`, `confetti`, `celebrate` infinitos (ornamento) | Importante | 2 ciclos e param; estados funcionais (ouvindo, trabalhando, girando) mantidos |
| 4 | atalho de pular para o conteúdo com transição (acionado por teclado) | Importante | sem transição |
| 5 | `scroll-behavior: smooth` global | Importante | `auto` |
| 6 | sidebar sem transição de recolher (lacuna) | Lacuna | 200 ms ease-out no shell |

Estados de item: palavra + ícone Material + tom (`components.ESTADO_ITEM`),
nunca só cor; legenda com os mesmos selos. Skeleton
(`components.render_skeleton`, mesma base do de documento, `aria-busy`)
só durante a leitura real da cotação e da lista. Detalhe de cada
referência carregado sob demanda (antes, ~15 elementos por referência
eram montados mesmo fechados).

## Ressalvas

* Em 1280 px **com a sidebar aberta** e em telas menores, "Concluir
  item" fica a ~1030 px do topo: está no TOPO da cesta (não mais no fim
  de um painel longo), mas pede uma rolagem curta. Recolher a sidebar em
  1280 devolve as três regiões e o botão à primeira tela.
* NÃO executados aqui: leitor de tela real, zoom de 200% e Edge (só o
  motor Chromium da prévia). Navegação por teclado verificada só nos
  controles da sidebar (nomes acessíveis).
* Capturas e medidas são da prévia LOCAL com banco dublê (latência de
  60 ms por consulta), não de produção.

## Rollback

* G1: desligar `cotacao_automatica_teto` (ou não ligá-la). Nada gravado
  é apagado ou reescrito ao desligar.
* G2–G5: reverter os commits da branch; nenhum dado depende deles.

## Testes

* Novos: `test_cotacoes_teto_automatico.py` (21), `test_cotacoes_autoavanco.py`
  (18), `test_cotacoes_ux.py` (18). Mutação: G1 5/5, G2 3/3.
* Suíte completa local, com LibreOffice: **2995 passaram, 1 falhou, 306
  puladas** (PostgreSQL de ensaio ausente). A falha,
  `test_contexto.py::test_tela_final_aplica_identidade_automaticamente`,
  não se repete: passa isolada e com o arquivo inteiro (25/25), com e sem
  estas mudanças — a rodada levou 23 min com o LibreOffice convertendo em
  paralelo. Registrada como intermitente; o CI confirma.

## Veredito

**APTO PARA HOMOLOGAÇÃO**, com a flag `cotacao_automatica_teto`
desligada até o operador ligá-la e as ressalvas acima (botão a uma
rolagem curta em 1280 px com a sidebar aberta; leitor de tela e zoom de
200% não testados).
