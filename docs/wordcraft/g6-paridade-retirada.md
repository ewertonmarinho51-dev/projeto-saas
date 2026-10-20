# G6 — paridade, transição e retirada do legado

Data da revisão: 19/10/2026

Estado: **PENDENTE PARA RETIRADA; FRONTEIRA LOCAL DE TRANSIÇÃO COMPROVADA**.

## Caminhos atuais

`steps._render_documento` possui uma única decisão de superfície. Quando
`wordcraft_runtime.ativo()` é verdadeiro, chama `wordcraft_operacional.render`
e retorna imediatamente; TipTap e `text_area` não são montados em paralelo.
Falha de runtime, admissão, importação ou persistência permanece visível dentro
do host WordCraft e não aciona fallback silencioso.

Quando a flag está desligada, o caminho legado continua operacional e constitui
o rollback da transição. Isso ainda é necessário porque Auth real, execução Linux
de fidelidade, homologação na infraestrutura-alvo e canário operacional não foram
concluídos. Remover `rich_editor.py`, `assets/rich_editor/`, o editor Markdown ou
seus exportadores agora eliminaria o único rollback comprovado.

## Proteção de rascunho durante a troca

Antes de carregar runtime, criar owner ou importar documento, o host verifica
`edicoes_pendentes[doc_key]` e `editor_<doc_key>`. Texto divergente do documento
canônico bloqueia a montagem WordCraft, permanece intacto na sessão e orienta o
operador a salvar ou descartar no fluxo antigo. A troca de identidade também
revoga owner, bridges, checkpoints, preparações, widgets e caches documentais.

Essas proteções demonstram exclusividade de superfície e preservação da volta.
Elas não demonstram que todos os usuários e documentos reais passaram pelo
canário, nem autorizam apagar o código legado.

## Paridade comprovada localmente

| Capacidade | Evidência atual | Limite para retirada |
|---|---|---|
| abrir, editar, salvar, recarregar e exportar | G1 local e owner persistido | Auth/infraestrutura-alvo |
| undo/redo e patches | canvas real, ACK persistido, CAS e auditoria G4 | canário operacional |
| histórico e restauração | revisão histórica vira nova head e remonta canvas | canário operacional |
| aprovação e emissão | quatro heads aprovadas/emitidas e reabertas byte a byte | Auth real e homologação |
| painel contextual G5 | trilhas A–D passam pelos owners existentes | artefato operacional homologado |
| isolamento | dois tenants, dois owners e dois Chromium/WASM; leituras cruzadas recusadas | sessões emitidas pelo GoTrue |
| escala | perfil de 100 páginas abre e reproduz o PDF admitido | orçamento na infraestrutura-alvo |
| fidelidade | 16/16 roundtrips e testes Rust de IO/layout | raster Linux e revisão visual |

## Revisão regressiva

Em 19/10/2026, a dependência de QA `PyYAML 6.0.3` foi instalada em diretório
isolado do workspace, sem alterar o Python do sistema. O contrato específico de
`.github/workflows/wordcraft-fidelity.yml` passou com **9 passed e 1 skipped em
0,66 s**; o skip é a verificação `bash -n`, indisponível neste Windows. Em
seguida, a execução agregada de todos os arquivos `test_wordcraft*.py`, agora
incluindo o analisador YAML do workflow e o benchmark de escopo de IA, encerrou
em sua rodada mais recente com **502 passed e 1 skipped em 42,37 s**. Os 21
contratos Node específicos do browser e a execução conjunta de host, validador e
browser com **66/66 testes** passaram na sequência mais recente.

## Decisão de retirada

Nenhum arquivo ou consumidor legado é retirado neste estado. A retirada exige,
na ordem: fechar Auth real e fidelidade Linux, homologar o bundle operacional,
medir a infraestrutura-alvo, executar canário com rollback e obter autorização
específica para remover os caminhos que o canário demonstrar substituídos.
Até lá, G6 permanece pendente e a ausência de remoção é uma salvaguarda material,
não escopo esquecido.
