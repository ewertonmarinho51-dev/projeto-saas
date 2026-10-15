# G4 — projeção e aplicador canônico nativo

Contrato registrado antes da implementação, em 2026-10-15. Este incremento
adapta o aplicador existente; não cria regras paralelas de governança, não
consulta LLM, não grava documentos e não concede autorização de acesso.

`wordcraft_blocos.projetar_documento(doc_key, checkpoint, *, indice, node,
bundle, manifest_sha256)` valida os bytes pelo motor pinado e confere o índice
autoritativo inteiro. Retorna `ProjecaoNativa` imutável, vinculada a documento,
revisão, hash dos bytes e build. Seus blocos são uma view de leitura com caminhos
`doc/clausula/n/block_uuid`, `doc/preambulo/block_uuid` ou
`doc/institucional/block_uuid`; UUID e posição vêm exclusivamente do índice do
backend. O texto dessa view jamais é importado para editar o documento.

A cláusula é reconhecida pela regex canônica `validacao._RE_CLAUSULA`, somente
em parágrafos com estilo de título comprovado. O exportador usa o style ID
`GovDocsClausula`; os IDs nativos `Heading1`, `Heading2`, `Heading3` também
representam títulos numerados. O prefixo `## ` é acrescentado apenas à view de
análise. Parágrafos do corpo e das células herdam a cláusula anterior do corpo;
um título dentro de célula nunca redefine a cláusula do documento. Títulos,
preâmbulo, stories auxiliares, estilos institucionais e assinaturas ficam
bloqueados. Uma seção de assinaturas bloqueia o restante até um próximo título
de cláusula. Estrutura numerada repetida/ambígua e perfil sem todos os títulos
FIXED reconhecíveis impedem autocorreção, inclusive numeração parcial que possa
ocultar uma região fixa sob cláusula anterior. Lacunas de texto de objetos ou áreas
não endereçáveis são explícitas e impedem alegar cobertura integral de análise.

`patches.aplicar_plano_nativo(plano, documentos, relatorio, *, node, bundle,
manifest_sha256, max_proporcao_blocos=0.25)` recebe por documento um
`DocumentoNativo(checkpoint, indice)` mantido pelo backend. Reutiliza o envelope
do corretor e exige `expectedOldHash` por operação e `sourceNative` por
documento, com `{documentId, revision, sourceHash, engineManifestSha256}`,
além de `sourceBundleVersion` e `sourceBundleHash`. O hash do bundle nativo
vincula a ordem canônica dos documentos, IDs, revisões, hashes e build.

As regras continuam sendo `corretor.validar_plano`,
`patches._validar_clausulas_fixas` e
`patches._validar_diff_por_clausula`. Neste incremento a allowlist contém
somente `replace` de um parágrafo inteiro, não vazio, sem controles, objetos,
tracking ou estilos mistos. Títulos não são editáveis. Os paths do plano são
resolvidos na view e traduzidos para posições nativas pelo backend; caminhos,
offsets, comandos, URLs e arquivos não são aceitos como autoridade da IA.
O adaptador compila essa substituição para o menor range UTF-8 com diferença,
retendo ao menos um caractere do parágrafo original fora da seleção. Inserções
pontuais incluem um caractere vizinho no range. A substituição sem contexto que
consome o parágrafo inteiro permanece explicitamente não suportada devido à
pós-condição de paragraph mark do comando nativo atual; não há fallback.

A edição efetiva ocorre exclusivamente em `wordcraft_native.aplicar_patch`,
que chama o comando nativo atômico de Session em cópia. O adaptador valida
novamente o checkpoint e prova o texto esperado, identidade/estrutura do modelo
fora dos parágrafos autorizados, propriedades de parágrafo/run e bytes de media
e passthrough. A comparação JSON é um oráculo de pós-condição de leitura, nunca
um mecanismo de aplicação. Reprojeta, preserva IDs por vínculo operacional
confirmado no próprio aplicador após essas provas e aplica o mesmo diff canônico.
Qualquer falha em qualquer documento descarta o lote inteiro em memória.

O retorno contém os novos checkpoints/índices, snapshot, diff e versão. Não há
save, CAS, ACL ou ACK de editor. O chamador deve autorizar tenant/escopo e fazer
CAS sobre os hashes/revisões de origem. O Undo da Session temporária não é Undo
de uma sessão viva do navegador; essa integração permanece posterior.

Testes de política isolam o IPC nativo explicitamente. Eles não substituem a
prova com o bundle real pinado, coletado e verificado pelo integrador.

Evidência local: 123 testes focados passaram (novo aplicador, corretor,
aplicador legado e índice). A projeção do checkpoint real sintético C01/dfd
(`bc0d7d897914dbf31a73a23e6a1fd3cffe39031eb88f1c5c9b6ef6bb05da8163`)
foi validada pelo bundle 240, manifesto pinado
`e26defdab3c8d4835cea5b5f8a69250af16a7c472a7104f8eae2893def60a75f`:
79 blocos nativos, 78 views de parágrafos, 10 títulos, cláusulas 1 a 9,
52 parágrafos editáveis, cobertura textual completa e sem impedimentos.
Tabelas mantêm geometria no modelo
e índice nativos; a view textual enumera os parágrafos das células em ordem,
sem reconstruir uma tabela Markdown ou alegar auditoria visual da geometria.

Prova real de aplicação em 2026-10-15, sem stubs: bundle GovConnect
`39fec20fc5e94590a95cfd9af8d0ce34d07c3e54`, mesmo upstream pinado,
manifesto `bd306cdb4709a43314366375da91ca1d00b2dd6db3c7683fff44eb15eb087548`.
O corpus completo passou `wordcraft_corpus.verify_full_inputs`; o checkpoint
de origem reexportado apresentou os mesmos textos, links, headers e footers da
fixture DOCX C01 pinada antes da aplicação.

`aplicar_plano_nativo` executou o IPC e `apply_patch` WASM reais: revisão 1 para
2, uma palavra substituída em um parágrafo da cláusula 2, diff de exatamente um
bloco e todos os 79 IDs preservados. Os 27 parágrafos protegidos/fixos/bloqueados,
stories auxiliares, media e passthrough ficaram idênticos; arquivo e bytes de
origem em memória permaneceram intactos. Resultado de checkpoint:
`3ca52cad7d0142c4b7fbf94c260ab85562452ca1316d0e9ecceae266c73a94bc`.

Oito negativas reais recusaram hash/revisão de origem, hash do parágrafo,
blockedPath, escopo de finding, FIXED_LOCKED, mudança de prosa PARAMETERIZED e
região de assinatura, mesmo quando o finding a permitia. Cada caso executou
zero IPC de aplicação e uma validação nativa obrigatória, contados separadamente.
Não se alega ausência de todo IPC na fase de validação.

Exportação nativa real gerou DOCX de 19.773 bytes e PDF de 45.364 bytes com
quatro páginas parseáveis. O DOCX passou preflight, mostrou somente a mudança
textual esperada e preservou links, headers e footers. Reimportação e nova
exportação DOCX mantiveram a mesma projeção textual. Não houve revisão visual
de layout nesta prova nem gravação, banco, CAS ou integração de Undo/browser.

Evidência da sessão em `outputs/WORDCRAFT_G4_APLICADOR_NATIVO_REAL.json`, SHA-256
`ba6925a7985cad8b46c0d161cd517bab5fc67a01bc23f65b2e8d605794f03f29`, acompanhada
de `WORDCRAFT_G4_C01_DFD_APLICADO.docx` e `.pdf`. O JSON contém hashes,
contagens, bindings e resultados; não inclui o texto do plano/documento.
