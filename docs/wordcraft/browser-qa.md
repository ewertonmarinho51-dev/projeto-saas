# QA automatizado do canvas em Chromium headless

Contrato registrado antes do código em 16/10/2026. Este incremento é teste de
software do repositório em Linux CI, com três fixtures sintéticas verificadas.
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
do renderer e contadores de DOM antes e depois das interações. Esses números
**não** incluem memória total do processo/browser nem memória linear do WASM;
ambas permanecem `false` no contrato para impedir promoção indevida da medida.
Falha ou ausência das métricas esperadas falha a etapa `performance_metrics`.

O step fica depois dos roundtrips/import/export/patch puro e antes dos artifacts
de `wordcraft-build.yml`, sem build alternativo, deploy ou produção. Testes Node
offline do novo harness cobrem mapa estático, limites, confinamento e saídas
sanitizadas; não são apresentados como execução Chromium.

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

Fontes primárias verificadas:
[release Playwright 1.56.1](https://github.com/microsoft/playwright/releases/tag/v1.56.1),
[catálogo de browsers pinado](https://raw.githubusercontent.com/microsoft/playwright/v1.56.1/packages/playwright-core/browsers.json),
[package.json pinado](https://raw.githubusercontent.com/microsoft/playwright/v1.56.1/packages/playwright-core/package.json),
[metadata NPM oficial](https://registry.npmjs.org/playwright-core/1.56.1),
[instalação oficial de browsers](https://playwright.dev/docs/browsers),
[API oficial de teclado](https://playwright.dev/docs/api/class-keyboard).
