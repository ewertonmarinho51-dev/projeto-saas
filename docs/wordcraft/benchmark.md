# Benchmark local do formato canônico e IPC nativo

Registro anterior à implementação. `scripts/wordcraft_benchmark.py` reutilizará
`wordcraft_corpus.verify_inputs`, `wordcraft_corpus.text_blocks` e as APIs existentes
`wordcraft_native.validar/exportar`. Não haverá novo motor, banco, rede ou chamada IA.

O ensaio aceita caminhos locais explícitos de Node, bundle, corpus e checkpoints,
mais o SHA-256 confiável do manifesto configurado pelo servidor. Nenhum parâmetro
vem do navegador. Antes de medir ou escrever resultado, verifica os hashes dos três
DOCX sintéticos versionados, valida os três checkpoints no motor real e compara o
texto ordenado, links, cabeçalhos e rodapés reexportados com suas respectivas
fixtures. A tabela também deve conter os 210 códigos esperados. Falha em qualquer
caso encerra o ensaio sem gerar relatório parcial ou gravar documentos.

Cada amostra de validar ou exportar DOCX/PDF inicia um processo Node independente
pelas APIs reais de produção. O tempo observado inclui criação do processo,
verificação de assets/manifesto, inicialização WASM, operação e IPC. Não chamar
essas amostras de startup de browser, warm start ou tempo isolado do motor. Não
medir nem inferir memória do navegador. Repetições limitadas de 1 a 10 por operação
e caso; registrar todas, mediana e percentil 95 empírico por nearest-rank
(`ceil(0.95*n)`, portanto o maior valor quando `n <= 10`).

O JSON registra somente ambiente/runtime/commits, contagens, hashes, bytes,
relações de tamanho e latências. Checkpoints e exportações permanecem em memória;
nenhum texto documental, token, segredo ou conteúdo de erro nativo entra na saída.
O modo inicial não é aceite de fidelidade visual, não mede o corpus de 20/100
páginas e não certifica desempenho de produção. A ampliação v2 e a passagem no
browser estão registradas abaixo. A comparação semântica valida os elementos
que `text_blocks` inspeciona; não substitui inspeção de metadados ou dados reais.

Execução pelo integrador com o runtime e bundle locais já aprovados:

```powershell
python scripts/wordcraft_benchmark.py `
  --node 'CAMINHO_ABSOLUTO_NODE' `
  --bundle 'CAMINHO_ABSOLUTO_BUNDLE' `
  --manifest-sha256 'SHA256_CONFIAVEL_DO_MANIFESTO' `
  --inputs tests/fixtures/wordcraft `
  --checkpoints '../wordcraft-896-evidence/corpus-roundtrip' `
  --repetitions 3 `
  --out '../../outputs/WORDCRAFT_BENCHMARK_LOCAL.json'
```

O destino deve ser novo e seu diretório deve existir. O script não sobrescreve
relatórios existentes nem publica qualquer artefato.

## Medição integral v2 executada em 18/10/2026

O mesmo medidor passou a aceitar `--full-roundtrip`, sempre de forma exclusiva a
`--checkpoints`. Nesse modo ele exige o recibo canônico
`gc-wordcraft-full-roundtrip/v1`, exatamente 16 casos, o mesmo manifesto do motor,
todas as etapas `PASS` e os hashes/tamanhos de checkpoint, DOCX e PDF. A admissão
estrutural e criptográfica de todos os casos termina antes da primeira chamada ao
motor. Depois, o motor atual precisa reproduzir os hashes DOCX/PDF admitidos antes
que qualquer amostra seja registrada.

A execução local real usou três repetições por operação e produziu
`WORDCRAFT_BENCHMARK_FULL_16_20261018.json`, SHA-256
`b9f52f09376c7b573be58f4f7187943cbe141a2757d66adcff446f41029aadd4`.
Foram medidos 16 casos. C02 gerou 29 páginas: validação P50/P95 443,52/492,10 ms,
DOCX 502,77/630,43 ms e PDF 836,03/1.072,51 ms. C08 gerou 16 páginas e preservou
210 itens: validação 409,42/417,84 ms, DOCX 501,63/516,41 ms e PDF
1.258,44/1.288,37 ms. Cada amostra inclui novo processo Node, conferência dos
assets, inicialização WASM, operação nativa e IPC.

Esses números são observações locais sintéticas. O relatório declara como falsos
`browser_startup_measured`, `browser_memory_measured` e
`visual_fidelity_approved`. Portanto fecha a medição atual de
checkpoint/exportação para o corpus de 16 casos, incluindo 20+ páginas e 210
itens, mas não fecha o orçamento G7 de navegador.

O mesmo modo gera ainda um DOCX sintético determinístico somente em memória,
com 100 marcadores e 99 quebras explícitas. O arquivo passa pelo preflight e
importador nativo existentes; o checkpoint é validado e o PDF exportado precisa
conter exatamente 100 páginas pelo `PdfReader`. Três repetições produziram:
importação P50/P95 472,39/478,16 ms, validação 285,91/293,75 ms e PDF
1.104,71/1.113,60 ms. O relatório atualizado é
`WORDCRAFT_BENCHMARK_FULL_16_PLUS_100P_20261018.json`, 47.188 bytes, SHA-256
`66302123a324a8be1f4ac8be9bf9148dd7bf8600def571588239cf3e83d28f06`.
O campo `hundred_page_measurement_kind` registra
`native_import_validate_export_not_browser_open`: esta prova mede o motor/IPC,
sem reclassificá-la como abertura ou memória de navegador.
