# Dataset de calibração Jev

`dataset_candidatos.json` contém cinco pares de candidatos extraídos da fixture oficial de preços praticados. Cada lado registra o arquivo de origem, seu SHA-256 com quebras de linha normalizadas para LF, o índice do registro e o `raw_hash` canônico. A leitura do dataset confere esses valores antes de qualquer benchmark.

Os cinco pares são candidatos, não exemplos rotulados: todos começam com `human_label: null`. Não há rótulos humanos nas fixtures existentes, portanto não é possível declarar positivos, negativos, casos difíceis, thresholds, precision ou recall.

Para rotular, um revisor deve conferir as duas evidências na fonte e substituir somente `human_label` por `true` ou `false`, mantendo a proveniência intacta. A coleta atual é homogênea: todos os registros são alicates wattímetro com o mesmo código de catálogo. Ela serve para validar a trilha, mas não cobre negativos ou especificações/unidades/embalagens divergentes. Antes de homologar, é necessário capturar referências reais adicionais com esses cenários e submetê-las à mesma revisão humana.

O runner offline é:

```powershell
python scripts/jev_benchmark.py --dataset docs/jev/dataset_candidatos.json --baseline baseline.jsonl --jev jev_respostas.jsonl
```

Ele aceita JSON, `{ "results": [...] }` ou JSONL. Cada resultado gravado informa `candidate_id` e, quando efetivamente observado, `decision`, `calls`, `input_tokens`, `output_tokens`, `cost` e `latency_ms`. Campos ausentes permanecem ausentes no relatório; o runner não estima custo ou latência. Sem todos os rótulos humanos do recorte, `metrics` fica `null`.
