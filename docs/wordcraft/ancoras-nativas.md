# Âncoras derivadas do checkpoint nativo

Status: módulo isolado funcional, com decisão e inventário registrados antes da implementação. Ainda sem integração ao owner ou ao aplicador e sem conclusão de G2/G4.

## Evidência e decisão

O upstream auditado `533615620ef91ae57fa7aa4cd77fd98b2179e693` define `Document.body`, `Document.parts` e `Block::{Para,Table}` em `crates/doc/src/lib.rs`. `Path` contém `[bloco]` ou `[bloco, linha, célula, bloco, ...]`; `StoryRef` distingue `body` de `part(u32)`. `Part.kind` diferencia header/footer/footnote/endnote/comment/textBox. Tabelas aninhadas usam `Table.rows[].cells[].blocks`. `Paragraph.rev`, em `crates/doc/src/para.rs`, é contador de cache com `serde(skip)`, e não constitui identidade persistente.

`src/blocos.py` já concentra o SHA-256 textual e o modelo Markdown usado pelo aplicador canônico `src/patches.py`. Esse aplicador permanece a única autoridade de correção. O novo código reutiliza `hash_texto`, o validador nativo `src/wordcraft_native.validar` e os validadores de hash/UUID/revisão do protocolo. Não aplica patches, não exporta conteúdo, não reconstrói documento nem grava checkpoints.

Decisão: construir um índice lateral por revisão, derivado exclusivamente dos bytes exatos de um checkpoint aprovado pelo motor pinado. Ele contém UUID de bloco, story, path nativo, tipo e hash integral do bloco. O hash da revisão sempre cobre os bytes originais, incluindo media/passthrough; o índice não é segundo snapshot canônico. A leitura JSON serve somente para projetar os endereços, depois da validação pelo mesmo motor. Campos do modelo não são normalizados de volta nem descartados na persistência.

## Inventário autorizado deste incremento

| Arquivo | Responsabilidade | Reuso e limite |
|---|---|---|
| `src/wordcraft_blocos.py` | Projetar índice, reconciliar IDs e resolver âncora na revisão exata | `blocos.hash_texto`, `wordcraft_native.validar`, `wordcraft_protocol`; sem mutação, ACL ou aplicação |
| `tests/test_wordcraft_blocos.py` | Exercitar inserção, movimento, edição comprovada, duplicados, remoção, tabelas aninhadas e precondições stale | Unidade da reconciliação; não simula um aceite nativo como evidência de RLS ou WASM |
| `docs/wordcraft/ancoras-nativas.md` | Decisão, escopo e limitações | Documento de integração, sem alterar gates globais |

## Regras de identidade

1. Cada construção verifica UUID/revisão/hash, limite de bytes e aprovação nativa antes de projetar. O hash declarado deve corresponder exatamente aos bytes. Retries do mesmo documento/revisão/checkpoint/build geram os mesmos IDs iniciais.
2. Reconciliação exige revisão consecutiva, mesmo documento, mesmo build nativo e bytes anteriores que comprovem integralmente o índice anterior. Conteúdo idêntico tem identidade de conteúdo preservada somente quando seu hash integral/tipo/story ocorre uma única vez em ambos os índices. Inserção ou reordenação de blocos únicos pode deslocar o path sem trocar esse ID.
3. Nenhuma heurística de similaridade, posição, vizinhos, número de cláusula ou `Paragraph.rev` identifica uma edição. Duplicados recebem IDs novos quando a revisão muda, mesmo se permanecerem nos mesmos paths, exceto quando há vínculo operacional validado explicitamente.
4. Preservar ID quando o conteúdo muda exige vínculos com paths e hashes exatos de origem/destino e confirmação síncrona por um verificador confiável do backend. O verificador recebe o contexto completo da transição e todos os vínculos em conjunto. A configuração e a resposta desse verificador não podem vir do browser, da IA ou de hints de seleção. Ele deve conferir operação já validada pelo backend ou resultado do motor correlacionado à base/checkpoint, não apenas aceitar o tipo declarado. Ausência, resposta ambígua ou rejeição invalida a tentativa inteira.
5. Digitação arbitrária de canvas sem testemunho operacional correlacionado pode gerar ID novo. Isso invalida propostas antigas em vez de adivinhar o alvo. Dois snapshots isolados não provam que texto alterado foi edição, e não remoção seguida de inserção. Nem mesmo conteúdo igual prova continuidade física: a correspondência automática estabelece identidade de conteúdo, não história de autoria/gesto.
6. Resolução exige documento, revisão, hash integral da revisão e hash do bloco exatos. Um UUID preservado entre revisões não autoriza reutilizar patch antigo. ACL, cláusulas bloqueadas, escopo, orçamento, confirmação humana e aplicação transacional permanecem no backend/aplicador existentes.
7. Todas as stories em `parts`, inclusive cabeçalho/rodapé e tabelas aninhadas, são enumeradas. Separadores de notas fora de `StoryRef` são informados explicitamente como áreas não endereçáveis; não podem receber patches por este índice. O índice não promete que uma story de caixa de texto órfã esteja visível no layout.

## Integração ainda necessária

Persistir o registro lateral atomicamente com a revisão no owner, manter índices históricos imutáveis e ACL por documento. Integrar uma evidência operacional real produzida pelo caminho nativo de edição para preservar IDs em texto alterado. Sem esse vínculo, o modo conservador continua seguro, mas não satisfaz a promessa de identidade permanente para toda digitação. O aplicador canônico ainda precisa de um adaptador que valide escopo e execute comandos nativos tipados e transacionais; este índice não substitui esse trabalho nem conclui G2/G4.

Os testes de unidade usam projeções do formato real e um validador nativo substituído somente para isolar o algoritmo. Uma aprovação simulada não prova compatibilidade do motor.

API para o backend: `construir_indice` valida e cria o primeiro índice; `validar_indice` confronta índice histórico e bytes originais; `reconciliar_indice` produz o índice da revisão consecutiva, informando IDs invalidados; `resolver_ancora` devolve somente `CaminhoNativo` com precondições exatas. As dataclasses são imutáveis e não guardam texto, media ou payload do checkpoint. O verificador síncrono opcional recebe `TransicaoNativa` e a tupla de `VinculoOperacional`; somente o booleano `True` aprova a relação, e indisponibilidade falha de modo fechado. Nenhum campo ou tipo desse contrato concede permissão de edição.

## Evidência deste incremento

Verificação de regressão: **35 testes do índice e 18 testes existentes de blocos/patches, totalizando 53 aprovações**. Os casos incluem inserção/reordenação, mudança de conteúdo com e sem confirmação backend, duplicados, remoção, hashes/revisões stale, integridade do índice anterior, limite de projeção, tabelas aninhadas e stories de cabeçalho/rodapé. `git diff --check` sem erros nos três arquivos deste incremento.

Execução local separada dos testes de unidade: os três `checkpoint.json` extraídos do artefato upstream/adapter aprovado `896ebbc` foram validados pelo worker Node/WASM real e depois projetados. Bundle local com `qa-manifest.json` SHA-256 `54386ff2c1f16ff0f1d0a9b2d7edbfdce4f7bc0cc1b4f4cc26e881e023b929c6`, previamente conferido com o ZIP do CI. A execução resolveu todos os IDs de cada índice com as precondições exatas, sem escrever conteúdo ou chamar Supabase.

| Checkpoint sintético | Bytes originais | Blocos projetados | Stories | SHA-256 original |
|---|---:|---:|---|---|
| `01-texto-listas-links` | 287.985 | 10 parágrafos | body: 10 | `7ca1359cef875861b385c2e98c17233af522ff1c07c65bcde9d4e494e07b2130` |
| `02-tabela-210-itens` | 828.130 | 1 tabela e 1.487 parágrafos | body: 1.488 | `cffc3fbc1233d02f5625d9fdbe14fdca08e5c03292b70336800f94ed53f63351` |
| `03-timbrado-assinaturas` | 290.927 | 1 tabela e 18 parágrafos | body: 17, header: 1, footer: 1 | `590a508bdf4926acfe8bfeb556b3a2c928f34471e16b8b1a462aca2d349f6d32` |

Nenhuma área não endereçável apareceu nesses três arquivos. Tabelas aninhadas e separadores são cobertos por testes de unidade do formato; não foram encontrados no corpus real usado nesta execução. A confirmação de linhagem operacional ainda usa verificador sintético nos testes: nenhum comando real do editor foi certificado por esse callback.
