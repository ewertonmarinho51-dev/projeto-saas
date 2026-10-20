# QA automatizado do canvas em Chromium headless

Contrato registrado antes do código em 16/10/2026. Este incremento é teste de
software do repositório em Linux CI, com três fixtures sintéticas verificadas e
perfis determinísticos adicionais de 20 e 100 páginas.
Não é observação manual pelo conector Browser, homologação G1, prova GoTrue,
persistência de produção, aprovação institucional ou aceite visual de layout.

O script `scripts/wordcraft_browser_qa.mjs` recebe caminhos de servidor
explícitos para bundle recém-compilado, manifesto com SHA confiável, checkpoints
do mesmo build, corpus imutável, Python e pacote QA. Antes de criar saídas ou
abrir HTTP, reutiliza `wordcraft_corpus.verify_inputs`, o validador/exportador
nativo e `text_blocks` para ligar cada checkpoint à fixture DOCX sintética.
Revalida hashes ao ler os bytes que seguirão ao browser. Os três casos precisam
ser admitidos; documento alheio, ausência ou divergência recusa toda a execução.

Playwright Core é dependência exclusiva de QA em RUNNER_TEMP: versão 1.56.1,
Node >=18, pacote oficial
`https://registry.npmjs.org/playwright-core/-/playwright-core-1.56.1.tgz`, SHA-512
`hutraynyn31F+Bifme+Ps9Vq59hKuUCz7H1kDOcBs+2oGguKkWTU50bBWrtz34OUWmIwpBTWDxaRPXrIXkgvmQ==`.
O catálogo oficial dessa versão fixa Chromium/headless-shell revisão 1194,
versão 141.0.7390.37. O script confere pacote, catálogo, revisão e versão do
browser executado, registra hashes locais e não escolhe outro browser se faltar.
Instalação segue o CLI pinado, com browsers/cache QA em RUNNER_TEMP; nenhuma
dependência runtime do produto é adicionada.

O runner aceita somente Linux e Windows. Em ambos exige
`PLAYWRIGHT_BROWSERS_PATH` absoluto e resolve explicitamente o
`chromium_headless_shell-1194`; o mesmo executável cujo hash é registrado é
passado ao `launch`. O ambiente do processo admite apenas variáveis básicas de
runtime e o caminho do browser, sem encaminhar URLs, chaves ou proxies da
aplicação. Falhas preservam estágio, contagens de rede e diagnóstico limitado,
sem transformar execução incompleta em evidência positiva.

O servidor estático escuta somente 127.0.0.1 e responde a um mapa fechado de
HTML/JS/WASM de teste e host. Não serve diretórios, manifests, JSONs, checkpoints,
DOCX/PDF, traces, HAR, credenciais nem uma API de upload. Os checkpoints entram
pela chamada em memória de Node para a página, sem URL ou conteúdo em argv.
O browser também bloqueia requisições fora desse mapa/origem. Somente screenshots
sintéticos e JSON sanitizado de etapas, hashes, contagens e limites são gravados.

Cada caso usa um `GovConnectEditor` público e `EditorController` existente sobre
um canvas real, sem acesso a Session/runner privados nem motor de alteração de
JSON. Exercita edição API, dirty, checkpoint, ACK de transporte **simulado** e
rerun de props na mesma instância. Essa confirmação não é save/ACL/CAS de banco.
Um InputEvent DOM sintético deve ser observado ainda pendente antes do pedido
freeze e percorrer a captura real do eframe; a drenagem deve recusar a prova,
reter a edição e permitir checkpoint normal. Isso não representa IME manual.

Um teste separado usa `page.keyboard.type` do Playwright sobre o agente de texto
real e exige mudança de geração, bytes/hash e texto alvo. Teclado que falhar
falha o CI: não há substituição por API ou stub. Freeze limpo precisa aguardar
readiness nativa, conservar o hash, recusar APIs de edição durante frozen,
aceitar somente release correlacionado e ignorar replay terminal. Após release,
patch tipado nativo deve recusar hash stale, alterar o alvo, conservar histórico
anterior e retornar hashes exatos com undo/redo. Nenhuma Session é recarregada
para simular esse histórico. Exportações DOCX/PDF podem ser verificadas em memória.

Chromium roda headless com WebGL/SwiftShader para renderização de software,
prazo por etapa e prazo global. Falha de Chromium, engine, input, barreira,
timeout ou API ausente falha o job; não há skip ou PASS condicional. Screenshot
é evidência de render automatizado, sem aprovação visual humana. IME manual,
toolbar real, Streamlit completo e persistência completa permanecem pendentes
quando não exercitados por esse teste.

O mesmo runner registra desempenho sem criar um segundo cenário: tempo de
startup do processo Chromium, tempo até a API do canvas ficar pronta e tempo de
`open` para cada fixture. O primeiro caso é rotulado como contexto frio; os dois
seguintes usam nova página no mesmo contexto/processo e são rotulados como
cache quente. O relatório inclui amostras e P50/P95 pelo método nearest-rank,
declarando que os três documentos são diferentes. CDP fornece heap JavaScript
do renderer e contadores de DOM antes e depois das interações. A própria
instância wasm-bindgen fornece a capacidade corrente de sua `WebAssembly.Memory`
antes e depois das interações; o relatório registra o máximo observado em bytes.
No pico simultâneo de dois canvas, `SystemInfo.getProcessInfo` enumera o conjunto
de processos Chromium e a coleta exige uma amostra para cada PID: soma de
`WorkingSet64` no Windows e de `VmRSS` no Linux, discriminada pelo tipo CDP.
Essa soma pode contar páginas compartilhadas em mais de um processo e representa
somente uma fotografia do runner local, não memória privada nem orçamento-alvo.
Falha ou ausência das métricas esperadas falha a etapa `performance_metrics`.

O step fica depois dos roundtrips/import/export/patch puro e antes dos artifacts
de `wordcraft-build.yml`, sem build alternativo, deploy ou produção. Testes Node
offline do novo harness cobrem mapa estático, limites, confinamento e saídas
sanitizadas; não são apresentados como execução Chromium.

Em 19/10/2026, o runner Windows passou novamente os três casos e mediu, no pico
de dois canvas, cinco processos CDP e soma de working sets de **785.494.016
bytes**: browser 56.037.376, dois renderers 514.211.840, GPU 181.309.440 e rede
33.935.360. O mesmo ensaio observou máximo de 71.041.024 bytes de memória linear
WASM, 20.328.264 bytes de heap JS usado e 25 nós DOM. O relatório externo
`wordcraft-browser-qa-current-win-19/browser-qa.json` tem SHA-256
`8c46bdad227c75d93d94c402debe3f84a2a879fcf387cfc1d7a260afbd7fed42`.
São medidas locais do corpus sintético, sem afirmar capacidade da infraestrutura
de homologação ou produção.

O runner passou ainda a reutilizar o perfil determinístico de escala do benchmark:
DOCX com 100 marcadores e 99 quebras explícitas, importado e validado pelo mesmo
worker. Antes do browser, o PDF nativo é contado pelo `PdfReader` e precisa ter
exatamente 100 páginas. O checkpoint é então aberto no canvas Chromium/WASM e a
exportação PDF feita dentro da página precisa repetir byte count e SHA-256 do PDF
admitido. A passagem Windows de 19/10/2026 abriu o checkpoint de 310.397 bytes em
662,7232 ms e reproduziu o PDF de 129.678 bytes, SHA-256
`59b9d1e2e2304664c69fc8e6f6b61b735f1ca7f7bb3b50f607f651a8203c444e`.
No momento da amostra, a memória linear WASM era 41.091.072 bytes e a soma dos
working sets de quatro processos CDP era 623.947.776 bytes. O relatório externo
`wordcraft-browser-qa-current-win-21/browser-qa.json` tem SHA-256
`8e3387c2528e06b3e886eaa66cf520ebf028bd8bfdba9fe3e5daafbfc330ce6e`.
Uma nova passagem Windows em 19/10/2026 ampliou a admissão fechada para os perfis
exatos de 20 e 100 páginas. O perfil de 20 páginas abriu em 863,8332 ms, com
checkpoint de 289.677 bytes, memória linear WASM de 40.501.248 bytes e working
set agregado de 529.883.136 bytes; o PDF reproduzido tem SHA-256
`4f0d23454afc99f5d69cd218cceae01648dfd2d03bd486713329d6d8b4449241`.
O perfil de 100 páginas abriu em 973,3872 ms, com checkpoint de 310.397 bytes,
memória linear WASM de 41.091.072 bytes e working set agregado de 699.203.584
bytes; seu PDF repetiu o SHA-256 já admitido. Houve zero requisições recusadas,
erros de página ou console. Evidência externa:
`wordcraft-browser-qa-current-win-22/browser-qa.json`, SHA-256
`5fb03fd6caf36684d5486344b670111801e2a7ecebfae8227a0f5666b78fca61`.
Essa prova fecha abertura e exportação automatizadas dos perfis sintéticos de 20
e 100 páginas; não constitui inspeção visual humana nem orçamento da
infraestrutura-alvo.

## Emulação móvel

O host de QA passou a declarar viewport e dimensionar o canvas por `100vw` e
`100vh`. Uma passagem Chromium com emulação explícita de 390×844 CSS pixels,
device scale factor 2, touch e `isMobile` abriu o perfil de 20 páginas em
906,4664 ms, inicializou o canvas em 229,9367 ms, reproduziu o PDF admitido de
36.406 bytes e registrou 72.155.136 bytes de memória linear WASM. Não houve
requisição externa recusada, erro de página ou console. O relatório
`wordcraft-browser-qa-current-win-24/browser-qa.json` tem SHA-256
`54dbefe7c5d2b925452c03033df1e933747b7cbc5caa488737e943e2460e14e7`.

A captura `mobile-390x844.png`, SHA-256
`7fdbc8d6e3770147d48748ad4203b027ea0c84825be27d762ff06e473f40ab2f`,
confirma que o canvas renderizou, mas mostra a faixa de opções e o conteúdo
horizontalmente recortados na largura móvel. Por isso o recibo registra
`emulation_only_not_physical_device=true` e `mobile_usability_approved=false`.
Esta prova verifica execução, memória, contenção e exportação sob emulação; a
usabilidade móvel e um aparelho físico continuam pendentes, sem falso PASS.

## Tamanho dos assets admitidos

O runner mede os bytes exatos dos arquivos do manifesto do motor, excluindo o
host de QA, e calcula gzip nível 9 e Brotli qualidade 11 sobre esses mesmos
bytes. Na passagem Windows seguinte, os dois arquivos admitidos totalizaram
41.860.573 bytes brutos, 15.492.381 bytes em gzip (37,01% do bruto) e 9.804.706
bytes em Brotli (23,42% do bruto). O JavaScript corresponde a 162.289 / 24.458 /
20.463 bytes; o WASM, a 41.698.284 / 15.467.923 / 9.784.243 bytes, na ordem
bruto/gzip/Brotli. A execução funcional completa permaneceu PASS, com zero
requisições recusadas ou erros. Evidência:
`wordcraft-browser-qa-current-win-25/browser-qa.json`, 21.921 bytes, SHA-256
`cefd4dc4692fa9bf51d55ca7ff0e1db110ae3687818cade695f15f8bbdb6e9d3`.
Esses números medem compressibilidade; não afirmam que o host de homologação já
negocie ou sirva `Content-Encoding`.

Em 18/10/2026, a execução local Windows confirmou o Chromium pinado
`141.0.7390.37`, SHA-256 do executável
`ed19d88b4486c39c0265b0c07cbf1d6835d06069e600bede1adb09db0df46c8e`,
servidor loopback e ausência de requisições bloqueadas/erros de página. O bundle
histórico produtor `39fec20`, manifesto
`bd306cdb4709a43314366375da91ca1d00b2dd6db3c7683fff44eb15eb087548`, foi
corretamente recusado ao abrir o primeiro caso porque ainda não exportava
`interaction_lock_ready`, `set_interaction_locked` e `apply_text_patch`. Portanto
essa tentativa prova o fail-closed e a portabilidade da inicialização, mas não é
uma nova passagem positiva do canvas atual. Uma repetição local completa exige
bundle reconstruído do adapter atual; o fluxo CI já registra a passagem dos três
casos com bundle coevo.

Na continuação da mesma prova, o overlay atual foi reaplicado ao upstream
`5336156` com conferência de Cargo, lock, UI e patch de IO, e compilado para WASM
com Rust GNU 1.99.1 e Trunk 0.21.14 checksum-verificado. O bundle produtor
`ba120b8`, manifesto
`f5aabf8a7923dd7cc941f855072f9c8967bf380870e852730ccd502957e4143c`,
gerou pelo importador WASM três checkpoints coevos, todos revalidados antes do
browser. A execução Windows passou os três casos com status
`PASS_HEADLESS_NATIVE_CANVAS_TRANSPORT_QA_NOT_MANUAL_ACCEPTANCE`: zero requisições
externas, erros de página ou console; startup 282,4142 ms; canvas P50/P95
182,8896/235,03 ms; abertura P50/P95 712,9428/1053,0555 ms; pico observado de
heap JS do renderer 19.980.144 bytes e 25 nós DOM. O JSON de evidência tem
SHA-256 `502ed68d538eff94e88a85c96c0c321a26fd8788d572f22a22b95f4754d454f6`.
As três capturas foram inspecionadas e mostram canvas renderizado, mas continuam
marcadas sem aprovação humana de fidelidade. IME, toolbar, Streamlit completo,
persistência de banco e memória total do processo continuam fora do escopo dessa
passagem. A memória linear WASM passou a ser medida na repetição posterior.

Em 19/10/2026, a repetição Windows com o mesmo bundle e os três checkpoints
coevos passou novamente. O retorno real de inicialização wasm-bindgen expôs a
`WebAssembly.Memory`; seis leituras (abertura e pós-interações de cada caso)
foram aceitas, com máximo observado de 71.041.024 bytes. O pico do heap JS do
renderer foi 19.169.296 bytes e o DOM chegou a 25 nós. O JSON em
`work/wordcraft-browser-qa-current-win-17/browser-qa.json` tem SHA-256
`7773441e25c3a711f484cd17e46f0a689c1646d1541fa5a5e126f13806685f5d`.
Isso fecha a medida local da memória linear WASM; memória total do processo,
naquela repetição, permaneceu sem amostra. A passagem posterior descrita acima
mede a soma de working sets; orçamento na infraestrutura-alvo e Auth real
continuam pendentes.

O runner foi ampliado na sequência para abrir simultaneamente os dois primeiros
documentos em páginas separadas do mesmo contexto. A prova exige tokens de
instância distintos, edita o primeiro sem alterar hash ou geração do segundo,
fecha o primeiro e ainda edita o segundo. A repetição passou com fechamento
independente, zero erros/requisições externas e JSON SHA-256
`782d186811b7797454fa015b27835d32a6612e5882041b93b7d198ae5ba386a3`.
Isso fecha o risco local de colisão entre dois canvas no mesmo processo; não
substitui concorrência entre usuários nem CAS/persistência backend.

O primeiro caso também seleciona no `GovConnectEditor` o parágrafo integral e
exige que o evento `document.selection` permaneça ligado ao hash limpo. Um
subprocesso Python com ambiente reduzido chama o
`wordcraft_capacidades.propositor_govbot_selecao`; a resposta da IA é mockada,
como exige o plano de testes inicial, mas atravessa o parser do gateway e o
compilador G4 reais. O runner admite somente uma substituição TR fechada, sem
fontes, aplica o novo texto no canvas, confirma por ACK simulado o hash alterado,
executa o Undo somente depois desse ACK e confirma o hash restaurado por um
segundo ACK simulado. A execução passou com hash de origem/restauração
`2457749e8fa58bc338d9baff291843006f66e68073370707cde4eb87ee454d40`,
hash transitório aplicado
`50bd11340abc83a6121eeb88449e5bc57ef8d50677f4a0489ff71c58a94fec63`
e ACKs de transporte consecutivos nas revisões 5 e 6. JSON SHA-256
`ea0765f1ffbe9c5eacd5cb659b3fadce6d0bba79644bb2f77aea13639ec09270`.
Não houve chamada paga, rede externa, persistência ou elevação de autoridade.

Uma segunda prova confinada mantém a mesma instância Chromium/WASM viva enquanto
o backend descartável executa o commit. O canvas recebe o `ComandoPatch` selado
do owner pela ação `patch` real, emite checkpoint com o mesmo `operation_id`, e
`DocumentoService.confirmar_patches(..., checkpoints=...)` persiste a revisão 2
somente após comparar operação, revisão, hash e bytes. O recibo real é entregue
ao `EditorController`; só então a mesma instância executa Undo, emite outro
checkpoint e o owner persiste a restauração como revisão 3. O segundo recibo
deixa controller e WASM em `saved`, com o hash nativo igual ao head reaberto.
PostgreSQL 16, PostgREST 12, adaptador, JWT/RLS e Chromium são locais e
descartáveis; zero requisições externas, erros de página ou console. Evidência
`outputs/WORDCRAFT_G4_OWNER_REAL_PERSISTENCE.json`, SHA-256
`993c4416f473c8b51cb4b8860eb15aa2c6fe8cdc6e11a575561eb4f5dce8011e`,
status `PASS_REAL_CANVAS_BACKEND_ACK_UNDO_LOCAL`. GoTrue e homologação na
infraestrutura-alvo não fazem parte dessa prova.

A mesma execução agora observa a negativa stale com um `probe` estritamente de
leitura antes e depois da tentativa. O owner recusa a preparação antiga sem
criar revisão ou auditoria, e o canvas conserva `instance_token`, geração e
hash. Nenhum comando que o backend recusou é enviado ao editor.

O mesmo stack cria um segundo tenant e entrega ao owner um JWT sintético B.
PostgREST/RLS recusam tanto a abertura quanto o checkpoint contra o documento A;
o canvas A permanece vivo e byte-identical, e a leitura administrativa mínima
confirma que head, revisões e auditoria não mudaram. O harness cunha os JWTs;
esta evidência não substitui login ou revogação pelo GoTrue.

Na expansão seguinte, cada tenant recebeu documento próprio, owner separado e
um processo Chromium/WASM simultâneo. Os canvas apresentaram tokens de instância
e hashes distintos; leituras cruzadas A→B e B→A foram recusadas, e o commit no
documento A conservou integralmente o probe do canvas B. O relatório conjunto
passou 40/40 checks, SHA-256
`167bb5080ea1e71304a478873890b2565c0ccdc01f1954e4b7ed08c519a19ea0`.
Os JWTs ainda são sintéticos e não provam emissão, refresh ou revogação GoTrue.

Ainda com o canvas A vivo, os owners existentes carregam pelo PostgREST/RLS o
snapshot institucional ligado à revisão, a montagem determinística de dois
itens (`30.02` por `Decimal`), uma fonte RAG vigente e a conferência literal de
citação. Os probes e a leitura persistida mínima provam que essas projeções não
alteram canvas, head, revisões ou auditoria.

Uma execução posterior acrescentou a aplicação governada de template à mesma
prova. Um canvas abriu a revisão-fonte; seleção, prévia e preparação do template
efetivo permaneceram somente leitura. A RPC canônica persistiu revisão, índice
e linhagem, e um novo canvas abriu exatamente os bytes e o hash da revisão 2,
mantendo a revisão 1 intacta. O relatório conjunto passou 37/37 checks, SHA-256
`fab7f077c60120135bc8141f87677ef62cf875637490c55e0306a3bb9f26a899`.

Na mesma execução, C09 lê um parecer normalizado e três achados pelo
PostgREST/JWT/RLS. Somente a recomendação objetiva recebe âncora e comando; o
Chromium/WASM em revisão 3 emite o checkpoint exato, o owner persiste a revisão
4 e o ACK deixa o controller em `saved`. A trilha marca o item aplicado como
pendente de revisão humana e mantém os dois demais pendentes. As revisões
anteriores permanecem relíveis e byte-idênticas.

Um segundo canvas coevo executa C11 com DFD sintético apto aos gates. A
identidade de governança `admin_municipal` é separada do operador G4; o
preflight resulta em score `90,5`, sem achados ou pendências. O canvas confirma
o `freeze` da revisão 1 e a RPC registra a aprovação sob PostgREST/JWT/RLS. Um
checkpoint posterior é recusado sem nova revisão; seis APIs editáveis permanecem
bloqueadas no mesmo token de instância, geração e hash. A prova não promove JWT
sintético a GoTrue e ainda não cobre o estado `emitido` no canvas.

Fontes primárias verificadas:
[release Playwright 1.56.1](https://github.com/microsoft/playwright/releases/tag/v1.56.1),
[catálogo de browsers pinado](https://raw.githubusercontent.com/microsoft/playwright/v1.56.1/packages/playwright-core/browsers.json),
[package.json pinado](https://raw.githubusercontent.com/microsoft/playwright/v1.56.1/packages/playwright-core/package.json),
[metadata NPM oficial](https://registry.npmjs.org/playwright-core/1.56.1),
[instalação oficial de browsers](https://playwright.dev/docs/browsers),
[API oficial de teclado](https://playwright.dev/docs/api/class-keyboard).
