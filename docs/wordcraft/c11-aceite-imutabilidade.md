# C11 — aceite de imutabilidade de aprovado e emitido

Data: 19/10/2026

Escopo: PostgreSQL/PostgREST/JWT/RLS local, RPC canônica e Chromium/WASM coevo

Estado: **PASS LOCAL INTEGRADO PARA APROVADO; emitido/GoTrue-alvo ainda parciais**

O manifesto offline continua `NOT_TESTED`: seus dois arquivos são sementes e
não podem declarar que o banco executou o fluxo. A prova funcional está no teste
`test_c11_approved_and_emitted_head_never_rewrites_historical_revision`.

| Campo | Evidência |
|---|---|
| ID | C11-SQL-01 |
| Fixture | revisão 1 com `C11-LEGACY-ORIGINAL`; tentativa posterior com `C11-REVISION-NEW` |
| Ambiente | PostgreSQL 16 local descartável; schema integral; papel `service_role` com claims sintéticos autenticados; sem remoto ou produção |
| Ações | criar revisão 1; aprovar pelo ato canônico; tentar checkpoint da revisão nova; conferir histórico; marcar o mesmo head como emitido; repetir tentativa; conferir revisão, hash e vínculo da aprovação |
| Esperado | aprovado e emitido recusam escrita; revisão 1 permanece byte-idêntica; head não avança; aprovação continua vinculada à revisão/hash originais |
| Observado | ambas as tentativas retornam `InsufficientPrivilege`; existe somente a revisão 1; bytes e SHA-256 originais permanecem; head continua na revisão 1; vínculo aprovado aponta a revisão/hash originais |
| Resultado | PASS SQL LOCAL |
| Regressão | `tests/test_documentos_editor_aprovacao_sql.py` |

O teste não cria uma “revisão 2” dentro de um ato aprovado. O contrato atual
fecha o head aprovado/emitido; uma futura edição institucional deve iniciar um
novo fluxo explicitamente autorizado, sem alterar a revisão ou aprovação
históricas. Inventar esse fluxo dentro do teste esconderia uma lacuna de produto.

Em 19/10/2026, uma segunda prova criou um DFD sintético derivado do checkpoint
C01 já renderizável, com fatos confirmados e identidade segregada de revisão
`admin_municipal`. O preflight canônico resultou em zero achados, zero
pendências, score `90,5` e gate não bloqueante. O Chromium/WASM abriu a revisão
1, drenou a fila e confirmou a barreira `freeze` para a revisão/hash exatos.
Somente então a RPC canônica registrou a aprovação via PostgREST, JWT sintético
e RLS.

Após a aprovação, o owner recusou um novo checkpoint sem alterar head,
histórico ou auditoria. No mesmo canvas congelado, `insert_text`, negrito, Undo,
Redo, seleção e `apply_text_patch` foram recusados; token da instância, geração
e hash permaneceram idênticos. A revisão 1 continuou byte-idêntica. Evidência:
`outputs/WORDCRAFT_G4_OWNER_REAL_PERSISTENCE.json`, SHA-256
`993c4416f473c8b51cb4b8860eb15aa2c6fe8cdc6e11a575561eb4f5dce8011e`,
34/34 checks verdadeiros e cleanup completo.

O estado `emitido` continua provado no SQL local, mas ainda não atravessa essa
mesma UI congelada. O JWT é cunhado pelo harness; GoTrue real e homologação na
infraestrutura-alvo permanecem necessários para G7.

O preflight da sequência completa também encontrou e fechou um defeito de
projeção no C05: bookmarks DOCX delimitavam os títulos de 32 cláusulas com
`U+FFFC`, fazendo o Edital aparecer sem estrutura e fora da cobertura. A
projeção agora reconhece somente o par estrito `bookmarkStart`/`bookmarkEnd`,
com mesmo nome, nas duas bordas de um título tipado de primeiro nível. O título
continua bloqueado para edição pelo motor nativo. Objeto opaco, marcador interno
ou não pareado continua falhando fechado. No checkpoint real de 329.216 bytes,
o resultado passou de zero para 32 cláusulas, com 141 blocos, zero lacunas e
aptidão de análise/autocorreção. Isso remove o bloqueio estrutural do Edital,
mas não declara a emissão completa, que ainda exige aprovar os quatro heads e
atravessar a RPC canônica em uma única prova integrada.
