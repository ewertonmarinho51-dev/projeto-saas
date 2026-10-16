# Cotações — progresso da implementação

Branch `feature/cotacoes-unificadas-bp-jev`, criada de `origin/main`
(`0de2939`). Nenhum merge, migração aplicada ou deploy. Comando de prova
em todos os gates (paridade com o CI):

```bash
PYTHONUTF8=1 python -m pytest -q -p no:cacheprovider --basetemp <dir curto>
```

---

## G0 — inventário e reprodução · PASS

- **Commit:** `59dd093`.
- **Arquivos:** `docs/cotacoes/{baseline.md, gates.md, 10_BACKLOG_116_FUNCOES.csv, bench/antes-legado.json}`, `scripts/benchmark_cotacoes.py`, `tests/{cotacoes_apoio.py, test_cotacoes_g0_reproducao.py}`.
- **Resultado:** suíte do HEAD 2732 passed / 344 skipped; 5 regressões aritméticas verdes; 13 defeitos P1 vermelhos (`xfail(strict)`), cada um falhando pelo motivo do dossiê (`--runxfail`).
- **Rollback:** reverter o commit (só docs, script e provas).

---

## G1 — confiabilidade do núcleo · PASS

**Resultado:** as 13 reproduções do G0 viraram provas comuns e passam;
16 provas novas de aceite (`tests/test_cotacoes_g1_nucleo.py`) e 13 de
revisão da migração 0029 (`tests/test_migracao_0029.py`, + 1 que pula
sem Postgres de ensaio). **Suíte completa: 2779 passed, 345 skipped,
0 failed** (3 min 51 s).

### O que mudou (código real, sem tela nova ainda)

| Tema | Antes | Depois | Onde |
|---|---|---|---|
| Contagem dos 3 | 4 superfícies contavam só `selected` | `cesta.consideradas()` é a única definição; relatório, resumido, XLSX, GovBot e telas usam | `src/precos/cesta.py` |
| Menos de 3 | sem caminho: item `INCOMPLETO` para sempre | exceção formal: perfil, ≥ 1 preço, texto, fundamento, aprovador e declaração; vai a REVISÃO, revisor conclui; cesta que muda **invalida** a exceção (histórico guardado); lote com prévia | `cesta.registrar_excecao`, `prever_/aplicar_excecao_em_lote` |
| Memória | concluir **substituía** a memória | justificativa é **acrescentada** | `repositorio.confirmar_item` |
| Método do item | sem seletor; recálculo voltava ao automático | seletor com justificativa, gravado em `estatisticas.decisoes` e reaplicado | `cesta.escolher_metodo` |
| Metodologia | relatório descrevia "mediana por CV" | texto pela `versao_regras` da pesquisa | `relatorio._criterios_estatisticos` |
| Unidade | item sem unidade/unidade desconhecida desligava a normalização | referência fica fora da cesta com motivo; dicionário ganhou unidades de serviço e embalagens comuns, sem conversão nova | `unidades.normalizar` |
| Importação | linhas ruins sumiam; "abc" → 0; reordenar sobrescrevia | diagnóstico de TODAS as linhas (linha, campo, valor, motivo); tudo ou nada; plano por código/descrição; reimportar = "igual"; unidade trocada em item pesquisado volta à busca | `src/precos/importacao.py`, `planilha.ler_tabela_xlsx` |
| Hash | não cobria quantidade, total, unidade, memória, motivos | formato 2 cobre o conteúdo decisório; formato 1 preservado para conferir relatórios antigos (golden do commit `0de2939`) | `relatorio.projecao_decisoria` |
| Pendências | itens listados só por número; pendências críticas não impressas; sem aviso ao gerar | `pendencias_nominais` (item, situação, deficiência) no completo, resumido e XLSX; aviso nominal com ciência antes de gerar | `relatorio.py`, `precos_ui.render_aviso_de_pendencias` |
| Trilha de fontes | nome, tipo bruto, contagem | coleta (1ª/última, UTC), desfechos por item **inclusive INDISPONÍVEL**, consideradas, inciso de origem; links de verificação | `relatorio._trilha_de_fontes` |
| Discrepante | percentual não gravado; frase sem base | percentual gravado; frase com mediana, n e faixa IQR | `estatistica.detectar_anomalias` |
| n = 3 | não analisado | critério percentual **opcional por cotação** (média dos outros sem os elevados), só sinaliza; 9,66 → 42,56 % | `estatistica.analise_percentual` |
| Fórmula da referência | inexistente | módulo sobre propostas reais (29,99 / 31,56 / 29,00 do J08); **sem fonte que entregue propostas, nada é simulado** | `src/precos/formulas.py` |
| Formatação | `0.48`, `float` na moeda do relatório | `48,23%` e `R$ 1.234,56` a partir de `Decimal` | `estatistica.brl/pct` |

### Migração

`supabase/migrations/0029_cotacoes_unificadas.sql.NAO_APLICAR` — aditiva:
`revisao`, `lote`, `uf` (CHECK das 27), `removido_em` nos itens; tipos de
evento novos (os da 0021 intactos); tabela `pesquisa_preco_emissoes`
(RLS ligada e forçada, só `select/insert` a `authenticated`,
append-only por gatilho, emissor carimbado); revisão copiando as colunas
novas; flag `flag_unified_quotations` = `off`. **Não aplicada.** Rollback:
`docs/cotacoes/0029_rollback.sql`.

Compatibilidade sem a 0029: a tela atual não escreve nenhuma coluna nova
(UF e lote são validados e não gravados; `revisao` só é usada quando o
item a traz). Os eventos novos (`excecao_registrada`) dependem do CHECK
da 0029: antes dela, a gravação do evento falha e vira **incidente
registrado** (`db.registrar_incidente`), sem perder a exceção, que fica no
item (`estatisticas.decisoes` e memória).

### Provas antigas ajustadas (e por quê)

- `test_precos_fase7`: a fixture não tinha `natureza_valor`; linha sem
  natureza não é preço e não conta (a natureza vem sempre do adapter).
- `test_pricebank_nucleo`: memória agora em pt-BR (`soma R$ 66,00 ÷ 3`);
  dublê do repositório aceita `decisoes`/`revisao_esperada`.
- `test_precos_fase4` (texto "cesta" na revisão) segue igual — o texto da
  tela foi ajustado para manter a palavra.

### Riscos e pendências

- Sem Postgres de ensaio nesta máquina: a 0029 foi revisada por leitura
  e por provas estáticas; a aplicação real e a prova de catálogo pulam.
- Exceção "aprovada" é REGISTRO da aprovação (nome + declaração), não um
  fluxo de aprovação no sistema — não existe esse fluxo no GovConnect.
- `salvar_itens` deixou de reescrever `estado` em itens existentes
  (reimportação devolvia itens pesquisados a PENDENTE por fora da máquina
  de estados).

**Custo de IA:** 0 chamadas. **Rollback:** reverter o commit do G1; a
0029 não foi aplicada, então não há schema a desfazer.

**Próximo gate:** G2 — serviço `cotacoes.py` e telas Minhas Cotações /
Elaborar Cotação com manual e automático no mesmo item.

---

## G2 — ambiente unificado · PASS (parcial: suíte completa não rerodada)

- **Commit:** G1 = `eb9bbab`; G2 = este commit.
- **Serviço único** `src/precos/cotacoes.py`: criar/listar/duplicar/arquivar, itens validados (incluir, editar, retirar sem apagar, reordenar), `pesquisar_item` com modo `manual` e `automatico` no MESMO caminho (`busca.coletar` → `cesta.recalcular_e_gravar`), decisões de cesta preservadas em nova busca, diagnóstico (fonte indisponível / zero / sem comparáveis / amostra insuficiente), busca registrada na trilha, lote reentrante, controle otimista com compensação, estado da cotação derivado por transições declaradas.
- **Telas** `src/ui/cotacoes_ui.py` (flag `unified_quotations`, OFF): Minhas Cotações → Nova cotação → Elaborar Cotação (itens | busca e resultados | cesta), Cotação automática no cabeçalho e por item, relatório e aplicação pelos serviços existentes. Com a flag ligada, o menu mostra só "Cotações".
- **Concorrência real no Streamlit:** a revisão VISTA pela aba é guardada; a aba velha recebe conflito e reaplica (provado no AppTest).
- **Provas:** `tests/test_cotacoes_g2_servico.py` (13) e `tests/test_cotacoes_g2_ui.py` (5); recorte cotações/preços/navegação: 580 passed, 88 skipped, 0 failed.
- **Demo sintética:** `scripts/demo_cotacoes.py` (banco em memória, fontes sintéticas, acesso ao banco real bloqueado) — conferida no navegador: Cotação automática do item 1 → 6/3 considerados, R$ 24,27, valor provisório com discrepante sinalizado.

**Pendente:** G3 (filtros/fontes adicionais e prova adversarial dedicada), G4 (seletor Jev barato com calibração), G5 (registro de emissão com hash do arquivo, prévia), G6 (E2E 50/210 no serviço novo, benchmark "depois", screenshots, matriz de substituição e consolidação de `execucao.executar_lote`), suíte completa após o G2.

---

## G3 — busca completa · PASS

- **Ampliação semântica explícita:** só quando o servidor desmarca "apenas o termo digitado" (manual ou automático); só acrescenta PALAVRAS à consulta, a descrição do item continua sendo a régua de comparação; termos acrescentados ficam na trilha e na tela.
- **Filtros antes da busca:** fontes (a fonte desmarcada não é chamada), janela, UF, termo, literal. **Depois:** os anteriores + natureza do valor, faixa de preço normalizado e "só as consideradas no cálculo" (a mesma definição do N/3). Filtro esconde, nunca apaga.
- **Detalhe da referência:** link de verificação oficial; propostas e fórmulas (`formulas.py`) **só quando a fonte as publica** — nenhuma fonte integrada as entrega hoje, então nada é simulado.
- **Provas** `tests/test_cotacoes_g3_busca.py` (9): item fictício com 11 vizinhos → **0 elegíveis, 0 considerados, sem preço** nos dois modos (mutação: piso de comparabilidade 0 → a prova reprova); ampliação só fora do literal e registrada; mesma compra Compras.gov × PNCP conta uma vez; estimado de origem fora da cesta inclusive por clique; os quatro diagnósticos distintos; uma fonte fora ≠ falha do item; fonte desmarcada não é consultada; busca reaberta com horário e contagens.
- **Cache/índice:** NÃO implementado, por decisão medida. No benchmark sintético o processamento do GovConnect custa ~1–4 ms/item; no real, a rede domina (p50 ≈ 2 s/item, `docs/pricebank-baseline.md`). Cache de resposta de fonte só faria sentido com TTL e escopo por tenant e mudaria a data de coleta registrada; sem medição de reconsulta repetida em produção, ele seria complexidade sem ganho provado. Reavaliar com telemetria real.
- **Não entregue (dado ausente):** filtro por modalidade/ARP — as fontes integradas não gravam modalidade na referência nem trazem ARP (F078 bloqueado).
- **Rollback:** reverter o commit; sem schema.

---

## G4 — Jev como seletor barato · PASS (aceite automático BLOQUEADO por desenho)

- **`src/precos/seletor.py`:** cada referência ainda não decidida pelo revisor passa primeiro pelas barreiras existentes (`decisoes.impedimento`: fonte registrada, evidência íntegra, preço, natureza, unidade comprovada, janela, código) e pela comparabilidade determinística: **≥ 75 % → comparável sem IA**, **< 25 % → incompatível sem IA**, código+descrição idênticos → comparável sem IA. **Só a faixa cinzenta** vai ao Jev, pelo caminho que já existe (`decisoes.revisar_referencia` → `ai_gateway.decision`: cache por hash, reserva, timeout, registro de custo).
- **Abstenção por padrão:** sem calibração aprovada, a saída do Jev é RECOMENDAÇÃO e a decisão fica `REVIEW_REQUIRED`. Nada entra ou sai da cesta, nenhum item é concluído pela IA. `aceite_automatico_permitido()` só seria True com `docs/jev/calibracao_aprovada.json` (aprovador, meta definida antes, ≥ 200 rótulos humanos, meta atingida) — **o arquivo não existe**, e mesmo com ele o seletor não executa o aceite: só o marca.
- **Custo:** tetos por item (5), por cotação (60 consultas) e de custo (US$ 1,00) — configuráveis em `filtros.jev`; o gasto anterior é somado das propostas gravadas; cache não conta como chamada; IA fora do ar → revisão humana, cotação segue.
- **Trilha:** cada proposta vira evento `selecao_sugerida` (tipo da 0029) com contagem, chamadas, cache, custo e a análise de cada referência; a tela mostra chips "regra: comparável / revisão humana / Jev sugere …".
- **Provas:** `tests/test_cotacoes_g4_seletor.py` (10) com dublê do Jev — nenhuma chamada paga.
- **Benchmark sintético** (`scripts/seletor_benchmark.py`, `docs/jev/seletor-benchmark-sintetico.json`), cadeia real `busca.coletar` → matching → triagem, 15 casos rotulados POR CONSTRUÇÃO: 3/3 comparáveis corretos, 9/9 incompatíveis corretos, **0 falso positivo**, 20 % de abstenção (1 paráfrase do mesmo produto e 2 vizinhos), 0 chamadas de IA. **Não é calibração do Jev**: o dataset humano (`docs/jev/dataset_candidatos.json`) segue com 5 pares sem rótulo, e a meta de falso positivo precisa ser definida pela equipe responsável antes de qualquer promoção.
- **Flag:** `jev_price_research` continua OFF; com ela OFF o seletor faz só a parte determinística (custo 0).
- **Rollback:** reverter o commit; sem schema novo além do tipo de evento já previsto na 0029.

---

## G5 — relatórios, emissão, cotação direta e aplicação · PASS

- **Registro de emissão** (F140/F162): cada relatório gerado (completo, resumido, DOCX, XLSX, pacote ZIP) grava `pesquisa_preco_emissoes` (0029) com hash do conteúdo decisório (formato 2, reprodutível), **hash SHA-256 do arquivo entregue**, tamanho, nome, versão da cotação e a lista nominal de pendências impressas; mais o evento `relatorio_emitido`. **Sem IP** (dado pessoal desnecessário). Sem a 0029, o documento é entregue e a tela diz "registro de emissão indisponível" — falha registrada como incidente, não silenciosa.
- **Conferência por terceiro** dentro do sistema: `relatorio.conferir_identificador` recalcula o resultado atual nos formatos 2 e 1 e diz se confere. Não há página pública (não existe endpoint autorizado para isso).
- **Prévia fiel** (F132): o mesmo Markdown que vira PDF/DOCX, na tela, antes de emitir (completo até 30 itens; resumido sempre). Aviso nominal de pendências com ciência continua obrigatório (G1).
- **Fornecedores sugeridos** (F151): quem já vendeu o item à Administração, a partir das referências reais coletadas, ordenado por presença na cesta — nunca por preço. **Nenhum envio** (F154/F155 bloqueados: sem provedor e sem consentimento).
- **Aplicação ao processo:** continua por `aplicacao.py`, com diff, documentos a descartar nominais e confirmação; o evento `pesquisa_aplicada` passa a gravar o **identificador decisório** aplicado.
- **Provas:** `tests/test_cotacoes_g5_emissao.py` (7), inclusive na tela (AppTest): gerar o quadro registra a emissão com o hash do arquivo; item pendente impede emitir até a ciência.
- **Suíte completa:** **2824 passed, 345 skipped, 0 failed** (4 min 55 s).
- **Não entregue, com motivo:** assinatura no relatório de preços (F137) — o mecanismo do GovConnect (`src/assinaturas.py`) exige signatário do cadastro de servidores/portarias do processo; ligar exige decisão de quem assina a pesquisa autônoma. % de preço máximo (F042) — sem regra normativa definida pelo ente. Índices de correção (F104/F093) — sem série oficial integrada. Geração assíncrona (F136) — P3.

---

## G6 — homologação local e consolidação · PASS com limites

- **E2E** `tests/test_cotacoes_g6_e2e.py` (9): lote automático com 1/10/50/210 itens sobre a fixture do caso real (todos preservados, códigos intactos, nada de preço para zero/vizinhos/fonte fora, reexecução sem duplicar); 50 itens cancelados em 15 e retomados só nos 35 restantes por outra sessão; 10 itens manual + automático na mesma cotação; 3 preços com 1 excluído → 2/3 e R$ 25,85; cotação fora do alcance recusada mesmo com ID conhecido; sem sessão, nada de credencial de servidor.
- **Benchmark antes/depois** (`docs/cotacoes/bench/`): mesma cobertura (157/210) e mesmos estados; requisições ao banco por item caíram de 11,8 para **8,2** com a otimização deste gate (sincronizar estado por passo e com consulta leve; não reler referências nem item depois do upsert; cotação lida uma vez por passo). Fluxo antigo: 3,9 — a diferença é deliberada (preservar decisões humanas; trilha de cada busca).
- **Defeito de tela corrigido:** frases com dois "R$" eram renderizadas como fórmula LaTeX pelo Streamlit (discrepante, GovBot, motivos) — visto no navegador, corrigido nas duas telas.
- **Navegador:** demo sintética conferida (lote automático, chips, indisponibilidade de fonte, item fictício 0/3).
- **Documentos:** `RELATORIO_ENTREGA.md`, `rollback.md`, `matriz_substituicao.md`, backlog final.
- **Suíte completa:** **2833 passed, 345 skipped, 0 failed**.
- **Limites:** RLS não exercida (sem Postgres de ensaio); nada ativado nem aplicado; telas antigas mantidas como fallback.

---

## Ativação em produção (16/10/2026, autorizada pelo operador)

- PR #51 mergeado (`17d5307`); tag `v1.9.0` promovida na VPS (health 200, logs limpos).
- Migração 0029 completada com a conferência que falha sozinha, ensaiada no projeto descartável (com prova de mutação e de comportamento) e aplicada em produção como `m0029_cotacoes_unificadas`. Antes/depois medidos: nada do que existia mudou. Registro no cabeçalho do arquivo, que perdeu o sufixo `.NAO_APLICAR`.
- `flag_unified_quotations` = on. `flag_jev_price_research` já estava 1 em produção (correção: os relatórios anteriores disseram que estava off — era o padrão do código, não a configuração de produção).
- Rollback: `docs/cotacoes/rollback.md`.
