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
O resultado não é aceite de fidelidade visual, não mede o corpus de 20/100 páginas
e não certifica desempenho de produção. A comparação semântica valida os elementos
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
