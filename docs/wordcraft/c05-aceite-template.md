# C05 — aplicação governada de template institucional

Data: 19/10/2026
Estado: **PASS LOCAL INTEGRADO COM POSTGREST/RLS E CHROMIUM/WASM; AUTH REAL PENDENTE**

O fluxo reutiliza a biblioteca `governanca_artefatos` / `governanca_versoes`, o
`DocumentoService`, o renderer institucional, o importador/validador WordCraft,
o índice nativo e o snapshot institucional existentes. Não cria cadastro,
renderer, persistência ou fonte de identidade paralelos.

A prévia é somente leitura e fica ligada às heads nativas correntes. Somente o
template efetivo, `PUBLISHED`, vigente, visível no tenant/secretaria e sem
pendências pode ser preparado. A preparação injeta dados canônicos, recusa
marcadores não resolvidos, produz bytes e índice nativos, registra os hashes da
origem e do alvo e recebe selo do owner. Nenhuma revisão é criada nessa etapa.

Após confirmação explícita, a RPC privada
`documento_editor_aplicar_template` relê e bloqueia processo, head, versão e
artefato. Ela confere ator, CAS, vigência, escopo, unicidade do candidato, hash
da versão e contrato fechado de proveniência. Revisão, índice e linhagem do
template são inseridos na mesma transação. Retry idêntico devolve a mesma
revisão; origem stale, operação divergente ou resolução ambígua falha sem deixar
revisão parcial. `authenticated` e `anon` não executam a RPC diretamente.

Na UI operacional, o documento é relido após o recibo e o canvas só é remontado
quando revisão e hash conferem. Prévia, estrutura, auditoria, parecer, evidências
e preparações dependentes da head anterior são invalidados.

Evidência automatizada:

- owner e UI: `tests/test_documentos_editor_patches.py` e
  `tests/test_wordcraft_operacional.py`;
- PostgreSQL 16.15 descartável:
  `tests/test_documentos_editor_template_sql.py`, **3 passed em 4,67 s**;
- regressão focada de owner/UI: **59 passed em 3,32 s**; regressão integral
  `test_wordcraft*.py`: **499 passed, 1 skipped em 77,20 s**;
- contenção HTTP anônima da RPC incluída no ensaio PostgREST local de 68 testes.

Em 19/10/2026, o ensaio integrado criou um processo e um template sintéticos
no PostgreSQL descartável. O owner abriu a revisão 1 no Chromium/WASM, leu pelo
PostgREST/RLS o template efetivo, snapshot institucional e montagem Decimal,
preparou o alvo sem alterar canvas, head, histórico ou auditoria, e confirmou a
aplicação pela RPC canônica. A revisão 2 persistiu bytes, índice e proveniência
do template na mesma transação; a revisão 1 continuou relível. Um novo canvas
foi montado com os bytes da head persistida e devolveu o mesmo hash nativo.

O ensaio também revelou e corrigiu o consumidor do recibo: funções
`RETURNS TABLE` chegam pelo PostgREST como uma lista de uma linha. O mock agora
reproduz esse transporte e o owner normaliza a linha antes de validar o contrato.
O relatório conjunto passou com 37/37 checks e limpeza de browser, processos,
banco e login, SHA-256
`fab7f077c60120135bc8141f87677ef62cf875637490c55e0306a3bb9f26a899`.

Este aceite não prova login GoTrue nem JWT emitido pelo Auth real. Também não
promove o bundle de QA a artefato operacional, não ativa flag e não autoriza
produção.
