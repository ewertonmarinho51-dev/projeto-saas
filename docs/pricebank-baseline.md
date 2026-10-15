# Banco de Preços — baseline e medição antes/depois

Medido em 15/10/2026 contra as APIs **públicas** do Compras.gov (leitura,
sem custo). Nada de IA paga. Arquivos brutos em `docs/pricebank/`.

## Como foi medido

`scripts/benchmark_precos.py` roda o `execucao.pesquisar_item` REAL sobre
`tests/fixtures/caso_210_itens.json` — a planilha real de 210 itens de
material de expediente (códigos internos de 6 dígitos, sem CATMAT) — e
conta as chamadas por fonte embrulhando `fonte._abrir`.

```bash
python scripts/benchmark_precos.py --itens 210 --saida docs/pricebank/<arquivo>.json
```

* **antes** = `main` original (0167c5f, v1.7.2), em worktree separada;
* **depois** = esta branch. A rodada `depois-210.json` foi feita com o
  código dos Gates 0–2; `depois-210-critica.json` com a análise crítica
  (Gate 6) — é a que vale para o relatório.

Cada linha de `itens` traz tempo, encontradas, na cesta, status, método,
valor, mediana, pendências e o valor da planilha do município.

## Resultado

| Indicador | Antes (13:57 UTC) | Depois (14:50 UTC) |
|---|---:|---:|
| Itens com 3+ preços comparáveis na cesta | 3 / 210 | 92 / 210 |
| … dos quais sem pendência de análise crítica | — (regra não existia) | 5 |
| … com média PROVISÓRIA (discrepante ou CV > 0,25) | — | 87 |
| Itens com alguma referência | 187 | 188 |
| Cobertura bruta média (referências/item) | 341,0 | 341,9 |
| p50 / p95 por item (210) | 2,20 s / 7,77 s | 1,98 s / 6,98 s |
| Lote 10 / 50 / 210 (soma dos tempos por item) | 26,0 / 124,6 / 639,5 s | 30,1 / 146,0 / 568,9 s |
| Itens por minuto (210) | 19,7 | 22,1 |
| Chamadas Compras.gov por item | 2,88 | 2,88 |
| Chamadas PNCP por item | 0 | 0 |
| Erros de fonte | 0 | 0 |
| Chamadas de IA | 0 | 0 |

**O que explica o salto de 3 para 92:** o código interno do município
(6 dígitos) era tratado como CATMAT e ZERAVA a identidade de todas as
referências. Agora o código só conta se o catálogo o confirmou
(`codigo_confirmado`) ou se o tipo foi declarado. Não foi a troca de
método.

**Por que só 5 sem pendência:** preço público real é disperso. Em 87 dos
92 itens, ou há discrepante sinalizado, ou o CV passa de 0,25. Antes isso
era resolvido trocando, em silêncio, a média pela mediana; agora a média
fica PROVISÓRIA até o revisor excluir (com motivo) ou manter (com
justificativa). Casos reais que motivaram a regra:

| Item | Média sem análise | Planilha do município | Causa |
|---|---:|---:|---|
| Almofada para carimbo (consulta manual) | R$ 4.955,86 | R$ 15,75 | 1 registro de R$ 698.000,00 na fonte |
| Divisória para fichário (nº 208) | R$ 30.002,33 | R$ 14,90 | 3 preços, 1 grosseiro; detector exige 4+ |
| Borracha ponteira (nº 210) | R$ 191,80 | R$ 0,40 | idem |

Na almofada, a ação humana "tirar os 12 discrepantes" levou a média a
**R$ 4,72** (mediana R$ 4,45) — verificado no navegador.

## p95 e rede

A rodada `depois-210.json` (14:21 UTC) teve p95 de 14,74 s. Medido em
seguida: o item mais lento (37,4 s) refeito a frio levou 4,3 s, dos quais
**0,2 s de CPU**; com as respostas em cache, 0,19 s. O p95 é dominado pela
latência da API; a rodada seguinte (14:50) deu p95 de 6,98 s com o mesmo
número de chamadas. Não há regressão de CPU.

## NÃO MEDIDO

* Falso positivo de comparabilidade — exige dataset rotulado por humano,
  que não existe no repositório.
* Custo de IA real — nenhuma chamada paga foi feita (regra do pacote).
* Cold × warm cache separados por fonte em escala.
