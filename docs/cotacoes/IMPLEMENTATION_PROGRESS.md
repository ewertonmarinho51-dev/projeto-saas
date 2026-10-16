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
