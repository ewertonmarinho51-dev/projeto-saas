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
| `scripts/wordcraft_preflight.py` | verificar fontes pinadas, ferramentas e assets; build local futuro/CI | executável sem serviços e sem segredos | baixo; não substitui compilação |
| `tests/test_wordcraft_protocol.py` | regressões negativas e lifecycle do contrato | pytest offline | sem dependência de LLM |
| `tests/test_wordcraft_preflight.py` | impedir aprovação falsa com source/toolchain ausentes ou divergentes | pytest offline | pré-requisitos não certificam G1 |
| `docs/wordcraft/upstream.lock.json` | manifesto de origem e versão auditada | preflight | hash Git não prova build |
| `.github/workflows/wordcraft-build.yml` | ensaio de build upstream pinado em runner Linux, sem deploy ou segredos | cargo xtask ci, Trunk e hashes de lock/assets | gate 0; não prova integração GovConnect |
| `vercel.json` | impedir auto-deploy da branch isolada por integração externa preexistente | configuração oficial git.deploymentEnabled por branch | controle de execução, não altera produção |

Não foi escolhido formato canônico definitivo. JSON nativo existe em `engine::io`, mas
roundtrip, IDs e fidelidade ainda precisam ser medidos. Não se grava novo documento como Markdown.
Nenhum backend novo de patches, tenants, IA, processos ou assinaturas será criado.
Nenhuma remoção de legado antes da prova de substituição e do aceite correspondente.
