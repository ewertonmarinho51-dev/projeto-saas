# C05 — aplicação governada de template institucional

Data: 18/10/2026
Estado: **PASS LOCAL DO OWNER, UI E POSTGRESQL; navegador/Auth real pendentes**

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

Este aceite não prova login GoTrue, JWT real, RLS através do PostgREST nem a
interação visual no navegador com a Session WASM. Também não promove o bundle
de QA a artefato operacional, não ativa flag e não autoriza produção.
