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

O mesmo modo gera ainda DOCX sintéticos determinísticos somente em memória para
20 e 100 páginas, com respectivamente 19 e 99 quebras explícitas. Cada arquivo
passa pelo preflight e importador nativo existentes; o checkpoint é validado e o
PDF exportado precisa conter exatamente a contagem declarada pelo `PdfReader`.
Na execução histórica do perfil de 100 páginas, três repetições produziram:
importação P50/P95 472,39/478,16 ms, validação 285,91/293,75 ms e PDF
1.104,71/1.113,60 ms. O relatório atualizado é
`WORDCRAFT_BENCHMARK_FULL_16_PLUS_100P_20261018.json`, 47.188 bytes, SHA-256
`66302123a324a8be1f4ac8be9bf9148dd7bf8600def571588239cf3e83d28f06`.
O campo `scale_measurement_kind` registra
`native_import_validate_export_not_browser_open`: esta prova mede o motor/IPC,
sem reclassificá-la como abertura ou memória de navegador.

A implementação ampliada foi executada novamente com o bundle corrente e o
round-trip integral regenerado: **16/16 casos, zero diferenças**, `comparison.json`
SHA-256 `b41ca4f7c11d323ffc5148e4c6c17e95e2294a536f78d057cc0f44cf70706db4`.
Com três repetições por operação, o perfil de 20 páginas obteve importação
P50/P95 503,0097/635,4754 ms, validação 310,348/350,49 ms e PDF
679,732/731,3025 ms. O perfil de 100 páginas obteve respectivamente
490,1563/492,2653 ms, 323,9769/331,5153 ms e 1.145,978/1.149,4995 ms. O relatório
`WORDCRAFT_BENCHMARK_FULL_16_PLUS_20P_100P_20261019.json` tem 49.837 bytes e
SHA-256 `b04aa3f4215b093eecf8cb5b4e2db3f1030c6cb9856a49442ee695aedc1a9c00`.

## Escopo de IA por seleção

`scripts/wordcraft_ai_scope_benchmark.py` reutiliza `GovBotContext`,
`govbot.montar_prompt`, o extrator semântico do corpus e o tokenizador canônico
`o200k_base` já usado pela medição de custos. Ele compara o prompt fechado da
edição de um bloco com a regeneração hipotética do documento inteiro, sem chamar
modelo, sem persistir texto e sem criar telemetria paralela.

No ETP sintético C02 de 29 páginas, 117 blocos e 61.059 caracteres, o maior bloco
individual tinha 705 caracteres. O prompt da edição por seleção mediu 608 tokens;
o prompt equivalente com o documento inteiro, 12.634 tokens. O recorte evitou
12.026 tokens de entrada, ou 95,1876%, mantendo uma chamada hipotética em ambos
os cenários. Chamadas reais ao provedor: zero. O custo em USD permanece nulo no
relatório porque nenhum modelo/preço foi escolhido; a ferramenta só calcula esse
valor quando recebe explicitamente `--input-usd-per-million`.

Evidência externa: `WORDCRAFT_AI_SCOPE_BENCHMARK_20261019.json`, 762 bytes,
SHA-256 `fa790e1006264383307bb76df793d878a33fc25f70c43a02c3c1ac68584aff79`.
