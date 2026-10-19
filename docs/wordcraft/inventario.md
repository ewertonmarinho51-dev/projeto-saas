# Inventário anterior à implementação — 14/10/2026

Base GovConnect: `770f969882f9c6c2fb55d23b68385bf601e87012`.
WordCraft inspecionado e fixado: `533615620ef91ae57fa7aa4cd77fd98b2179e693`.
Branch: `feature/wordcraft-wasm-govconnect`. Produção não alterada.

| Funcionalidade / código | Equivalente WordCraft | Dono / consumidores | Estratégia | Paridade / risco |
|---|---|---|---|---|
| `src/ui/rich_editor.py`, `assets/rich_editor/` | `apps/wordcraft-web`, `WordApp` | state; steps e revisão | SUBSTITUIR após G1/G6 | rerun, caret, undo, ACK; alto |
| `src/state.py`, `src/operacao_documento.py` | Session é buffer, não persistência | processo/autosave/geração | PRESERVAR e INTEGRAR | conflito, restart, aprovações; alto |
| `src/db.py::salvar_processo` | inexistente | Supabase; state | PRESERVAR processos; commit documental mínimo para G1, homologação definitiva em G2 | update geral atual não é CAS; alto |
| `src/blocos.py`, `src/patches.py`, `src/corretor.py` | registry/Session::run | GovBot, ciclo, parecer | PRESERVAR regras, INTEGRAR âncoras | hash, cláusulas fixas, atomicidade; alto |
| `src/govbot.py`, `src/ui/revisao.py` | seleção e comentários | mesmo gateway, mesmo aplicador | INTEGRAR | seleção autorizada, stale, undo; alto |
| validacao/consistencia/achados/ciclo/fatos/conhecimento | não é regra jurídica do editor | auditoria canônica | PRESERVAR | achados revalidados; alto |
| pareceres/parecer_correcao | revisão e diff no motor | parecer e corretor canônicos | INTEGRAR | objetivo/ambíguo/conflitante; alto |
| perfis/contexto/templates_gov/instituicional_bridge/signatarios | estilos, headers, tables | administração existente | PRESERVAR e INTEGRAR | snapshot institucional; alto |
| rag/conhecimento/precos | links e fontes no documento | proveniência existente | PRESERVAR | ausência de resultado não é inexistência; alto |
| ai_gateway/roteamento/politica_ia | nenhuma chave deve chegar ao WASM | único gateway | PRESERVAR | mocks, zero chamada paga; alto |
| `src/export.py` | engine::io, docx, pdf | emissão histórica | SUBSTITUIR condicionado ao G3 | 210 itens, timbrado, PDF selecionável; alto |
| auth/contexto/db/trilha | sem segundo cadastro | backend autenticado | PRESERVAR | JWT/RLS A/B real; crítico |

## Novos módulos autorizados neste inventário

| Módulo | Responsabilidade exclusiva / consumidores | Teste | Risco / gate |
|---|---|---|---|
| `src/documentos_editor.py` | proprietário único de abertura/checkpoint, aprovação, exportação e emissão nativa; reutiliza clientes/contexto SQL existentes e valida pelo motor antes do commit | CAS/idempotência/ACL, PostgREST/RLS, Chromium/WASM, pacote persistido e emissão local integrada | consumidor operacional sob flag OFF; Auth/infraestrutura-alvo pendentes |
| `supabase/migrations/20261015035015_documentos_editor.sql` | armazenamento privado de cabeça/revisões imutáveis vinculado a processos existentes; RPC interna de commit e contexto verificado pelo JWT | PostgreSQL/PostgREST local, RLS A/B, retry e conflito | gerada CLI 2.121.0; não aplicar remoto; fundação G2 preservada por migrations aditivas |
| `tests/test_documentos_editor_sql.py`, `tests/test_documentos_editor.py` | provar restrições SQL e contrato do proprietário backend com falhas negativas | PostgreSQL real e protocolo; caminho positivo com motor real no G1 | mocks não provam native/RLS; sem produção |
| `scripts/ensaio_http_local.py` | orquestrar schema/harness PostgREST existentes e provas HTTP em banco local descartável; nenhum backend documental novo | executar os testes reais de catálogo/anon/servidor, limpar processos e banco | somente loopback; sem GoTrue/Storage; CI e laboratório Windows |
| `src/wordcraft_protocol.py` | validar envelopes e respostas da ponte; futura UI; sem gravar, autorizar ou aplicar patches | schema fechado, nonce, escopo, replay, ACK | alto; fundação independente, não prova G1 |
| `src/wordcraft_native.py` | executar validador do mesmo motor em processo isolado, sem documento em arquivo ou credenciais no ambiente filho | rejeição/timeout/erro de runtime e resultado fechado | valida modelo, não concede ACL nem confirma save |
| `assets/wordcraft_editor/validate.mjs` | worker Node para validar bytes pelo WASM pinado, sem WordApp/canvas | hashes do manifesto/assets, input limitado e rejeição de modelo | depende de artefato compilado; não é segundo parser do documento |
| `assets/wordcraft_editor/validate.test.mjs`, `tests/test_wordcraft_native.py` | provar fail-closed do worker/IPC e não vazamento do payload/credenciais | Node/pytest offline | aprovação positiva real depende do WASM do CI |
| `src/ui/wordcraft_editor.py` | registrar/montar host v2 com instância estável e callback obrigatório do proprietário backend | contrato de abertura, chave estável e renderer simulado | não grava nem concede ACL; sem consumidor operacional até G1 |
| `tests/test_wordcraft_renderer.py` | recusar abertura divergente e preservar montagem/callback entre reruns | pytest offline | não equivale a navegador com WASM real |
| `scripts/wordcraft_preflight.py` | verificar fontes/ferramentas e prova criptográfica do baseline upstream imutável; não aprova o adaptador | SHA/ZIP/run/lockfile exatos e falhas negativas | somente baseline pode ser reutilizado; integração sempre recompilada/testada |
| `tests/test_wordcraft_protocol.py` | regressões negativas e lifecycle do contrato | pytest offline | sem dependência de LLM |
| `tests/test_wordcraft_preflight.py` | impedir aprovação falsa com source/toolchain ausentes ou divergentes | pytest offline | pré-requisitos não certificam G1 |
| `docs/wordcraft/upstream.lock.json` | manifesto de origem e versão auditada | preflight | hash Git não prova build |
| `.github/workflows/wordcraft-build.yml` | build pinado e artefato JS/WASM para ensaio local após checks, sem deploy ou segredos | cargo xtask ci, testes do adaptador/UI, Trunk, hashes e avisos | artefato interno com revisão de distribuição e G1 pendentes |
| `vercel.json` | impedir auto-deploy da branch isolada por integração externa preexistente | configuração oficial git.deploymentEnabled por branch | controle de execução, não altera produção |
| `integrations/wordcraft/govconnect.rs` | codec de checkpoint sem perda de media/passthrough e operações tipadas sobre a própria Session upstream | testes Rust de roundtrip, bytes inválidos e atomicidade | candidato experimental; não substitui patch/ACL/CAS |
| `integrations/wordcraft/govconnect_fixture.rs` | executável exclusivamente de QA para DOCX sintético → checkpoint → DOCX/PDF pelo mesmo motor | corpus verificado por hash, igualdade do modelo e comparação de conteúdo | sem consumidor operacional; não é serviço de persistência |
| `tests/fixtures/wordcraft/` | três DOCX de entrada inteiramente sintéticos e manifesto de origem/hash | fixture produzida no CI canônico e cópia byte-idêntica | inspeção visual ainda pendente; não é modelo institucional aprovado |
| `scripts/wordcraft_overlay.py` | aplicar biblioteca de integração ao SHA exato upstream sem reimplementar engine | hashes de entrada, caminhos confinados e aplicação idempotente | build isolado, sem produção |
| `tests/test_wordcraft_overlay.py` | validar recusa de SHA/arquivos divergentes e confinamento do overlay | pytest sem rede | não substitui compilação Rust |
| `integrations/wordcraft/govconnect_browser.rs` | API WASM explícita sobre o mesmo WordApp/Session, sem picker/download e sem reinicialização por rerun | compilação WASM, smoke test de browser e ACK/checkpoint | G1 candidato; transporte/backend ainda necessários |
| `integrations/wordcraft/main.rs` | entrada WASM controlada: inicialização explícita pelo host; sem shell de arquivos original | build do binário e export da classe GovConnectEditor | não distribui marcas nem ativa editor |
| `integrations/wordcraft/rustfmt.toml` | formato Rust igual ao upstream pinado, em Windows e CI | rustfmt --check com configuração explícita | reprodutibilidade do overlay |
| `integrations/wordcraft/ui-patches.json` | mudanças mínimas de identidade do fork, preservando copyright e origem | hashes antes/depois, recusa de drift e verificação do overlay real | requisito de marca/licença antes do bundle |
| `integrations/wordcraft/licenses/epaint_default_fonts/` | textos de licença das fontes do epaint 0.36.2, sem copiar fontes novas ou marcas | comparação canônica com arquivos do pacote efetivamente resolvido | fonte/proveniência em PROVENANCE.json |
| `scripts/wordcraft_notices.py` | reunir avisos upstream e de fontes a partir dos inputs pinados do build | falha se versão/texto da licença mudar; hashes no manifesto | não declara concluída toda auditoria de dependências |
| `scripts/wordcraft_local_assets.py` | instalar artefato verificado somente em laboratório local marcado; copiar JS/WASM/avisos sem documentos | SHA de ZIP/arquivos, pin/commit, traversal e recusa de destino alheio | sem rede ou deploy; não instala checkpoints em static |
| `tests/test_wordcraft_local_assets.py` | rejeitar bundle alterado, escopo divergente e instalação fora do laboratório antes de escrita | pytest com artefato sintético | não certifica compilação nem MIME do servidor |
| `scripts/wordcraft_corpus.py` | gerar entradas sintéticas de fidelidade pelo exportador e planilha canônicos | 210 códigos, totais Decimal independentes, XML A4/links/headers e hashes | referência de comparação; não aprova o novo motor |
| `tests/test_wordcraft_corpus.py` | verificar conteúdo do corpus e cálculo independente sem dados de tenant | pytest offline | render e roundtrip do WASM continuam obrigatórios |
| `tests/test_wordcraft_notices.py` | verificar inclusão de fontes, rejeição de alteração e confinamento de saída | pytest offline | não substitui revisão de todas as licenças |
| `assets/wordcraft_editor/host.mjs` | host v2: instância estável, eventos tipados, debounce, retry e ACK correlacionado | testes Node de lifecycle e futuro browser com WASM real | sem persistência/ACL própria |
| `assets/wordcraft_editor/host.test.mjs` | rejeição de ACK divergente, conflito, retry e preservação de instância | node --test, sem LLM/rede | não equivale a teste de interface |
| `.github/workflows/ci.yml` (existente) | executar as provas do novo host no CI canônico do produto | Node existente, sem novas dependências | preserva testes/bundle/export/RLS atuais |

O container gc-wordcraft-snapshot/v1 foi escolhido para G1 em formato-canonico.md, preservando media/passthrough. IDs estáveis e fidelidade institucional ainda precisam de homologação. Não se grava novo documento como Markdown.
Nenhum backend novo de patches, tenants, IA, processos ou assinaturas será criado.
Nenhuma remoção de legado antes da prova de substituição e do aceite correspondente.

## Laboratório reproduzível após G1 — inventário antes do código

| Componente planejado | Responsabilidade | Reuso e prova |
|---|---|---|
| `scripts/wordcraft_lab.py` | preparar banco sintético próprio e servir laboratório somente em loopback; reabrir o mesmo banco em restart | `homologacao_local`, `homologacao_stack`, marcador do instalador e owner existente; DSN/paths/portas validados antes de mutações |
| `integrations/wordcraft/lab/app.py`, `server.py` | página de ensaio do componente real, commit/ACK, download e preparação/aplicação G4 condicionada a finding autocorrigível corrente | `auth.entrar`, `DocumentoService`, `Ponte`, renderer e aplicador atômico; o corpus aprovado atual não possui finding G4 elegível e o laboratório não entra nos consumidores operacionais |
| `tests/test_wordcraft_lab.py` | recusar configuração remota, namespaces alheios, alteração do manifesto e corpus não verificado | sem banco nos testes de contrato; execução real local separada |

O runner substitui os roteiros avulsos de `work/` na reprodução da prova; não cria
outro sistema de processos, autenticação ou persistência. Segredos sintéticos ficam
somente em memória dos processos; o estado de retomada contém apenas nomes/UUIDs/hashes.

## Ampliação G2/G3/G4 — 15/10/2026

| Componente | Responsabilidade exclusiva e reuso | Prova e limite |
|---|---|---|
| `src/wordcraft_blocos.py` | índice derivado do checkpoint validado pelo motor, identidade conservadora e resolução por revisão/hash; não armazena documento alternativo | unicidade, duplicatas, histórias/células aninhadas e invalidação explícita; sem seleção confiável fornecida pelo browser |
| `scripts/wordcraft_benchmark.py` | medir admissão e exportação nos três inputs pinados ou nos 16 artefatos de um round-trip integral canônico, usando o worker existente; gera ainda perfis determinísticos de 20 e 100 páginas somente em memória | v2 mede P50/P95 locais, 29 páginas, 210 itens e importação/validação/PDF de 20 e 100 páginas; o runner Chromium reutiliza os perfis para abertura/exportação e memória locais; não mede orçamento G7 na infraestrutura-alvo |
| `scripts/wordcraft_distribution_notices.py` | reunir textos reais da closure Cargo filtrada para WASM e registrar ausência/expressões de licença | hashes, paths confinados e revisão explícita; metadata não é link map nem aprovação legal |
| `scripts/wordcraft_corpus.py --full-corpus` | ampliar o gerador existente aos doze cenários C01–C12, sem trocar fixtures G1 | oráculos Decimal por célula e QA estrutural; sementes de governança não aprovam owner/patch/RLS |
| `DocumentoService` + migrations aditivas G2 | preservar originais, índices e restauração na revisão imutável existente; snapshot institucional vem das fontes canônicas | CAS atômico, histórico privado, aprovação e emissão local integradas; ausência histórica não é preenchida artificialmente |
| `scripts/wordcraft_libreoffice_qa.py` (planejado) | comparar DOCX sintéticos com distribuição oficial extraída em workspace e perfil exclusivo | execução real headless, sem instalação global ou alteração no exportador do produto |
| `scripts/wordcraft_full_roundtrip.py` (planejado) | exercer as dezesseis entradas do gerador completo no importador/validador/exportador pinado e conferir os oráculos existentes | relatório por etapa e retenção de recusas; nunca transforma um teste de governança em aprovação documental |
| `src/patches.py` (adaptação planejada) | manter uma entrada de regras/escopo/FIXED e traduzir âncoras nativas verificadas para comandos limitados do mesmo motor | cópia, hash/revisão, escopo, diff e pós-condições; nunca editar JSON como motor alternativo |
| `GovConnect apply_patch` (adaptador Rust planejado) | comando puro tipado sobre Session upstream, sem save/ACL próprios | lote atômico de substituição textual, stale/UTF-8/estrutura/formato recusados; undo no documento vivo exige prova separada |

A decisão pré-código específica está em `persistencia-g2.md`,
`snapshot-institucional.md`, `corpus-g3.md`, `benchmark.md`,
`licencas-distribuicao.md` e `patches-nativos.md`. Este inventário consolidado
não retrodata a execução dessas provas nem encerra os gates correspondentes.

## Consolidação dos contratos registrados antes do código — 16/10/2026

As decisões específicas abaixo foram registradas nos respectivos documentos
antes de sua implementação. Esta tabela consolida o inventário; não retrodata
provas nem transforma implementado em homologado.

| Componente | Responsabilidade e reuso | Prova e limite |
|---|---|---|
| Aprovação nativa em `DocumentoService`/`state` e migration aditiva | mesma aprovação/trilha canônica sobre revisão/hash/fontes, sem rotular Markdown ou avançar consumidor antigo | `ato-unico-aprovacao.md` e `c11-aceite-imutabilidade.md`; aprovação e emissão local integrada passaram |
| Preparação e lote em `DocumentoService` e migration aditiva | aplicador canônico, checkpoint e auditoria `revisoes` na mesma transação; fontes obtidas no backend | `patches-persistencia.md`; SQL, canvas Chromium/WASM, commit/ACK real e Undo posterior passaram no mesmo ensaio descartável; GoTrue/infraestrutura-alvo permanecem em G7 |
| Auditoria contextual e vínculo de consistência nativo | `consistencia.py` conserva as regras; o owner expõe leitura atual e só traduz path legado por paridade completa, única, editável e com fonte; a correção reutiliza o propositor e a preparação G4 | leitura não grava; reauditoria encerra o achado; duplicidade, bloqueio, divergência ou ausência de fonte permanecem manuais |
| Parecer contextual no painel nativo | `pareceres`/`parecer_achados` persistidos e RLS existentes; `parecer_correcao.situar` conserva classificação global; proposta objetiva reutiliza preparo/aplicador G4; atendimento é derivado de `revisoes` imutáveis | citação literal deve localizar um único bloco nativo; recomendação não vira replacement automaticamente; operação persistida permanece pendente de revisão jurídica mesmo após encerrar o alvo anterior |
| Aceite C09 integrado | cenário sintético executa classificação conjunta, proposta objetiva, aplicador G4, PostgREST/JWT/RLS, Chromium/WASM, confirmação exata e atendimento derivado | `c09-aceite-owner.md`; PASS local integrado, sem promover a semente offline nem substituir GoTrue/homologação-alvo |
| Aceite C11 aprovado/emitido integrado | DFD apto é congelado no Chromium/WASM; quatro heads são aprovados e emitidos pela RPC canônica sob papel segregado; checkpoint/edição posterior não produz efeito | `c11-aceite-imutabilidade.md`; pacotes persistidos reabrem byte a byte e o canvas permanece congelado; GoTrue-alvo pendente |
| Aceite C11 de imutabilidade | PostgreSQL/PostgREST/JWT sintético/RLS local executa checkpoint, aprovação, emissão e tentativas de nova escrita sobre os estados aprovado e emitido | `c11-aceite-imutabilidade.md`; revisão, bytes, hash e vínculo aprovado permanecem intactos; Auth real ainda pendente |
| Aceite C12 de isolamento | dois tenants atravessam policies reais, PostgREST e dois processos Chromium/WASM com owners/JWTs sintéticos distintos; troca de identidade revoga o namespace documental | `c12-aceite-isolamento.md`; leituras cruzadas bidirecionais recusadas e commit de A não altera B; emissão/refresh/revogação GoTrue ainda pendentes; Storage N/A |
| Evidência factual e catálogo RAG no painel nativo | fatos canônicos do RPC privado do owner; `fontes_conhecimento`, `documentos_referencia` e chunks pelo cliente autenticado/RLS; conferência literal exige acesso ao processo | somente leitura e sem pesquisa externa; presença da citação pode ser verificada, mas integridade da fonte permanece pendente enquanto seu contrato de hash não for definido |
| Histórico e restauração no painel nativo | metadados imutáveis de `documentos_editor_revisoes` lidos pelo mesmo cliente autenticado/RLS e owner; `DocumentoService.restaurar` conserva CAS/idempotência | limita a cinquenta revisões, exige uma corrente e não expõe payload; restauração confirmada cria nova revisão e remonta o canvas; recibos da sessão permanecem identificados separadamente |
| Revogação da sessão WordCraft | `auth.entrar`/`auth.sair` e o owner operacional compartilham uma fronteira de identidade fechada; owner, bridges, checkpoints, preparações, widgets, caches e eventos do componente pertencem ao usuário/tenant/secretaria correntes | logout e troca de identidade removem todo o namespace documental antes da próxima montagem; mesma identidade preserva o owner e renovação de token não invalida rascunho |
| Guarda de transição do editor legado | `wordcraft_operacional.render` compara o texto canônico de `documentos` com `edicoes_pendentes` e o widget legado do documento corrente antes de carregar runtime, owner ou importador | divergência, inclusive texto vazio, bloqueia a montagem e preserva o rascunho na sessão; valor igual e rascunho de outro documento não bloqueiam; salvar ou descartar continua sob o fluxo legado |
| Estrutura institucional, biblioteca e montagem no painel nativo | `institutional_snapshot` da própria revisão, templates `PUBLISHED` visíveis pela RLS e `montar_itens` sobre dados canônicos do processo | identidade/portaria/signatários não são recalculados; itens usam `Decimal`; `documentos_suportados` no payload versionado liga tipo ao template, com secretaria sobre município e empate bloqueado |
| Prévia explícita de template publicado | `DocumentoService` relê artefato/versão e cláusulas publicadas pela RLS, impõe escopo e vigência UTC do processo, recalcula hashes canônicos e reutiliza `templates_gov.montar` contra os dados e a revisão nativa | somente leitura e determinística; secretaria prevalece sobre município; aplicação integrada comprovada separadamente |
| Preparação e aplicação nativa do template efetivo | renderer institucional, `planilha.injetar_tabela`, importador/validador WordCraft e índice nativo existentes produzem alvo selado; RPC grava revisão, índice e linhagem atomicamente | PostgREST/JWT sintético/RLS e remount Chromium/WASM passaram com origem preservada; GoTrue/infraestrutura-alvo pendentes |
| `achados.estruturar` com blocos nativos opcionais | mesmas regras/classificação/escopo, usando endereços nativos confirmados | projeção é leitura; títulos de assinatura sem número precisam conservar proteção |
| Protocolo/host/Rust de controle do canvas | mesma instância/Session, solicitação freeze/release correlacionada e drenagem de input antes da prova | `controle-canvas.md`; testes não certificam IME/frame/toolbar reais |
| `.github/workflows/auth-real.yml`, `scripts/ensaio_auth_real.py`, testes Auth/gateway | GoTrue oficial local antes do schema da aplicação, clientes e owner existentes; sem fixture Auth reduzida | `auth-real-ci.md`; preflight/tar real e61 testes passaram, login real ainda exige CI |
| `.github/workflows/wordcraft-fidelity.yml`, scripts/testes de QA LibreOffice | corpus novo, mesmo motor WASM, mesmo `_docx_em_pdf`, três caminhos PDF e artefatos sintéticos | `libreoffice-local.md`; execução Linux e aceite visual separados |
| `scripts/wordcraft_libreoffice_extract.py` | extrair MSI oficial para runtime QA marcado, sem instalação global ou serviços | usado no ensaio Windows; Linux registra identidade de distribuição própria |
| `scripts/wordcraft_full_roundtrip.py` | executar16 entradas pelos importador/validador/exportador/reimportador reais e oráculos existentes | prova real realizada; cada etapa conserva seu resultado, sem aprovação visual |
| `scripts/wordcraft_browser_qa.mjs`, contratos Node e step em `wordcraft-build.yml` | QA Linux/Chromium headless pinado sobre o bundle, três checkpoints sintéticos do mesmo build e perfis determinísticos de 20 e 100 páginas; mesmo EditorController e API pública GovConnectEditor | três casos e os dois perfis de escala passaram localmente; os PDFs do canvas repetiram os PDFs de 20 e 100 páginas admitidos; ACK é simulado, sem alegar observação manual, sessão Auth real ou persistência backend conjunta |
