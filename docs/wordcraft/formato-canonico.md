# Representação escolhida para a fatia G1

Escolha: `gc-wordcraft-snapshot/v1`, bytes UTF-8 produzidos pelo adaptador pinado,
armazenados privadamente em `documentos_editor_revisoes.payload`. DOCX/PDF são
artefatos derivados, não o buffer autoritativo. Não há migração automática do acervo.

O JSON nativo isolado foi recusado: Document ignora media e passthrough no serde.
O contêiner conserva esses campos, limita bytes/profundidade/objetos, rejeita campos
de modelo descartados pelo parser e permite somente as três chaves de bookkeeping
identificadas no DOCX upstream. OLE e gráficos opacos sem representação segura são
recusados; continuam no caminho legado, sem conversão silenciosa.

## Evidência e limites

- Upstream: 533615620ef91ae57fa7aa4cd77fd98b2179e693, versão 0.7.0.
- Build integrado 896ebbc: 12 testes nativos, 401 testes UI + 6 doctests passaram;
  três DOCX sintéticos importados, serializados, reabertos e exportados pelo motor.
- O comparador confirmou texto ordenado, headers/footers/links e os 210 códigos;
  geometria fracionária e bytes preservados são cobertos nos testes do adaptador.
- No navegador local, texto e descrição de célula foram editados, validados no
  servidor, commitados no PostgreSQL e reabertos após reload com o mesmo SHA-256.
- Isso ainda não certifica toda fidelidade visual, imagens institucionais,
  comentários/revisões ou performance de 100 páginas. As revisões editadas dos três casos sintéticos foram exportadas em DOCX/PDF; detalhes em g1-evidencias.md.

O DOCX como fonte única exigiria repetir importação/exportação a cada checkpoint
e vincular patches a posições reconstruídas. O contêiner evita esse ciclo para a
edição e permite igualdade do modelo na reabertura. DOCX original permanece fonte
de importação e referência de fidelidade, preservada na migração futura.

## Medição local de admissão e exportação

O benchmark `scripts/wordcraft_benchmark.py` executou três amostras por operação
com o bundle 240233c, manifesto `e26defdab3c8d4835cea5b5f8a69250af16a7c472a7104f8eae2893def60a75f`.
Cada amostra abre um processo Node, confere assets e inicializa WASM; não mede
sessão aquecida nem o navegador. Os checkpoints validados tinham 287.985 bytes
(texto), 828.130 (tabela) e 290.927 (timbrado), frente a 37.434, 45.991 e 38.856
bytes de DOCX original. A troca maior conserva o modelo em memória do motor,
sem converter DOCX novamente a cada checkpoint.

| Caso | Validar P50 / P95 observado (ms) | DOCX P50 / P95 (ms) | PDF P50 / P95 (ms) |
|---|---|---|---|
| Texto | 957,69 / 988,26 | 975,65 / 1.060,80 | 1.266,83 / 1.306,95 |
| 210 itens | 1.106,35 / 1.163,95 | 967,35 / 1.406,53 | 3.020,77 / 4.427,12 |
| Timbrado | 434,54 / 591,76 | 413,07 / 440,94 | 736,43 / 833,54 |

P95 empírico com N=3 é o máximo observado. O download Cargo concorrente pode ter
afetado recursos da máquina; estes números não são orçamento de produção nem
uma comparação controlada de motores. Evidência bruta externa ao repositório:
`outputs/WORDCRAFT_BENCHMARK_LOCAL_240.json`. A escolha do contêiner permanece
provisória para homologação G2: os resultados sustentam a implementação funcional,
mas faltam memória/startup do navegador, 20/100 páginas e comparação completa.

## IDs, patches e migração

Posições nativas usam story/path/offset e são vinculadas à revisão. O índice
derivado `gc-wordcraft-block-index/v1` preserva IDs apenas quando há conteúdo
exato único na mesma história, inclusive após inserção/reordenação; duplicatas e
edições sem vínculo operacional confiável invalidam o ID anterior. Mudança do
build exige reconstrução explícita. O índice acompanha atomicamente a revisão,
mas o checkpoint continua autoritativo. G4 ainda precisa da tradução para o
aplicador canônico de patches, com hash e revisão, preservando cláusulas fixas.

As tabelas novas não substituem processos, usuários, tenants ou assinaturas.
Cabeça e revisões referenciam processos existentes; permissões reutilizam as funções
de contexto SQL e o perfil atual de usuarios. Revision/operação são transacionais;
revisões anteriores não recebem UPDATE/DELETE nem pelo papel de servidor do app.
O serviço valida pelo motor antes da RPC interna; usuários têm somente leitura RLS.

G1 fornece o mínimo de commit autoritativo que o próprio contrato 02 exige. G2
continua pendente da homologação completa: migração Markdown/DOCX com relatório de
perdas, referências aos originais, snapshots institucionais/aprovações, trilha
canônica, identificação exata do build por revisão e rollback de documentos.
As flags permanecem desligadas e nenhum consumidor operacional foi migrado.
