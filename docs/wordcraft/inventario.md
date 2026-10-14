# Inventário anterior à implementação — 14/10/2026

Base GovConnect: `770f969882f9c6c2fb55d23b68385bf601e87012`.
WordCraft inspecionado e fixado: `533615620ef91ae57fa7aa4cd77fd98b2179e693`.
Branch: `feature/wordcraft-wasm-govconnect`. Produção não alterada.

| Funcionalidade / código | Equivalente WordCraft | Dono / consumidores | Estratégia | Paridade / risco |
|---|---|---|---|---|
| `src/ui/rich_editor.py`, `assets/rich_editor/` | `apps/wordcraft-web`, `WordApp` | state; steps e revisão | SUBSTITUIR após G1/G6 | rerun, caret, undo, ACK; alto |
| `src/state.py`, `src/operacao_documento.py` | Session é buffer, não persistência | processo/autosave/geração | PRESERVAR e INTEGRAR | conflito, restart, aprovações; alto |
| `src/db.py::salvar_processo` | inexistente | Supabase; state | PRESERVAR processos; adicionar CAS documental somente após G1 | update geral atual não é CAS; alto |
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

Não foi escolhido formato canônico definitivo. JSON nativo existe em `engine::io`, mas
roundtrip, IDs e fidelidade ainda precisam ser medidos. Não se grava novo documento como Markdown.
Nenhum backend novo de patches, tenants, IA, processos ou assinaturas será criado.
Nenhuma remoção de legado antes da prova de substituição e do aceite correspondente.
