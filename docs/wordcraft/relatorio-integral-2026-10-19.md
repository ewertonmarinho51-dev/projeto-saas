# Relatório integral GovConnect + WordCraft

**Marco:** G0–G7, fechamento local antes de homologação externa  
**Data:** 19/10/2026  
**Git GovConnect:** branch `feature/wordcraft-wasm-govconnect`; base
`770f969882f9c6c2fb55d23b68385bf601e87012`; HEAD funcional auditado
`d834d89a5e916d0450bb863adc66be7dbf8b07f5`  
**WordCraft upstream SHA:** `533615620ef91ae57fa7aa4cd77fd98b2179e693`
(0.7.0); integração GovConnect em 130 commits incrementais até o HEAD auditado  
**Ambiente:** Windows local isolado; PostgreSQL/PostgREST descartável; Chromium
141.0.7390.37; Rust GNU/WASM; sem WSL, Docker ou Podman  
**Flag WordCraft:** OFF; somente laboratório/QA local  
**Migrations aplicadas em produção:** NÃO

O commit que contém este relatório é documental e posterior ao HEAD funcional
acima; não altera runtime, schema ou evidências citadas.

## A. Objetivo alcançado

O editor WordCraft WASM abre, edita, faz checkpoint, persiste por CAS, recarrega,
restaura, aplica patches tipados com Undo/Redo e exporta DOCX/PDF no laboratório.
GovConnect permanece dono de identidade, tenant, processo, fatos, aprovação,
emissão e auditoria. O formato autoritativo é `gc-wordcraft-snapshot/v1`; originais,
índices, snapshots e revisões anteriores são preservados.

As seis capacidades usam os owners existentes: GovBot por seleção, auditoria,
templates institucionais, correção de parecer, verificação de evidências e
montagem estrutural. Aprovação e emissão são atos separados e transacionais.
Dois tenants e dois canvas foram exercitados sem leitura cruzada usando RLS e
JWTs sintéticos locais.

O resultado é **IMPLEMENTADO PENDENTE HOMOLOGAÇÃO**. Auth/GoTrue real, fidelidade
LibreOffice Linux, revisão jurídica das licenças, infraestrutura-alvo e canário
não estão concluídos. Portanto a integração não está apta para produção e o
legado permanece como rollback.

## B. Alterações reais

| Arquivo/componente | Antes | Depois | Por que | Teste/evidência |
|---|---|---|---|---|
| `integrations/wordcraft/*` | upstream sem contrato GovConnect | codec, bridge e comandos nativos tipados sobre Session | usar o motor nativo sem criar editor paralelo | Rust DOCX 243; layout 250; navegador real |
| `assets/wordcraft_editor/*` | sem host fechado | protocolo, nonce, instância, outbox, ACK e limites | conter browser/WASM e correlacionar checkpoints | contratos Node 21/21; Chromium |
| `src/documentos_editor.py` + migrations aditivas | Markdown e artefatos legados | revisões imutáveis, CAS, originais, índice, snapshot, aprovação, emissão e templates | um owner documental versionado | SQL/PostgREST local; rollback e stale |
| `src/wordcraft_capacidades.py` e `src/patches.py` | capacidades sem endereço nativo | compilação única para paths/hashes nativos | não duplicar corretor ou regras | G4/G5 e C09 |
| `src/ui/wordcraft_operacional.py` | sem superfície WordCraft operacional | superfície exclusiva sob uma flag e guarda de rascunho | evitar duas UIs ativas e preservar rollback | testes de transição G6 |
| corpus/roundtrip/LibreOffice QA | cobertura estreita | C01–C12, 16 variantes e comparador de três caminhos | medir perda e fidelidade | 16/16, 135 etapas, 87 páginas nativas |
| browser/benchmark | sem orçamento observado | 1/20/100 páginas, 210 itens, memória, gzip/Brotli e mobile emulado | medir antes de definir limites | evidências de `benchmark.md` e `browser-qa.md` |
| workflows separados | sem gates completos | build WASM, Auth real e fidelidade Linux independentes | falhar fechado e preservar artifacts | contratos YAML; execução externa pendente |

Diff acumulado contra a base auditada: 161 arquivos, 30.421 inserções e 70
remoções antes deste relatório. As remoções não apagam migrations, histórico ou
caminhos legados necessários ao rollback.

## C. Substituições e código redundante

| Recurso antigo | Recurso novo | Estado | Gate pendente | Retirada prevista |
|---|---|---|---|---|
| TipTap/text area | WordCraft WASM | LEGADO MANTIDO PARA COMPATIBILIDADE; superfícies exclusivas pela flag | Auth real, canário e rollback | somente após canário aprovado |
| Markdown autoritativo | snapshot nativo versionado | novos documentos usam o owner nativo local; consumidores históricos preservados | migração/homologação de todos os consumidores | adaptador de leitura histórica permanece |
| DOCX/PDF legados | exportação WordCraft | coexistindo por gate de fidelidade | LibreOffice Linux e revisão visual | escolha por formato após G3 |
| aplicação textual dispersa | aplicador G4 único | IMPLEMENTADO E TESTADO localmente | canário operacional | remover chamadas obsoletas depois do canário |
| painéis separados de análise | painel contextual nativo | IMPLEMENTADO PENDENTE HOMOLOGAÇÃO | Auth real/artefato operacional | ocultar rotas concorrentes depois de G5/G7 |

Nenhuma funcionalidade legada foi apagada porque a substituição integral ainda
não foi comprovada. A decisão detalhada está em `g6-paridade-retirada.md`.

## D. Testes e evidências

| ID | Teste | Resultado | Evidência/artifact | Defeito pendente |
|---|---|---|---|---|
| C01–C12 | round-trip nativo integral | PASS 16/16; 135 etapas | `comparison.json` SHA `b41ca4f...` | inspeção LO Linux |
| G1 | abrir→editar→commit→reload→DOCX/PDF | PASS LOCAL | `g1-evidencias.md` | ambiente-alvo |
| G2 | CAS, conflito, restart, restauração e RLS | PASS LOCAL | `persistencia-g2.md` | JWT GoTrue real |
| G4 | patch, stale, rollback, ACK e Undo | PASS LOCAL | `aplicador-canonico.md` | canário |
| C08 | 210 itens/Decimal/total | PASS LOCAL | `c08-aceite-210-itens.md` | LO Linux |
| C09 | parecer→diff→revalidação | PASS LOCAL | `c09-aceite-owner.md` | revisão jurídica operacional |
| C11 | aprovação/emissão imutável | PASS LOCAL | `c11-aceite-imutabilidade.md` | Auth real |
| C12 | dois tenants e dois canvas | PASS LOCAL PARCIAL | `c12-aceite-isolamento.md` | sessões GoTrue reais |
| PERF-20/100 | abrir/exportar perfis exatos | PASS LOCAL | browser SHA `5fb03fd6...` | orçamento alvo |
| PERF-MOBILE | 390×844 touch emulado | PASS técnico e layout emulado corrigido | browser SHA `b26f967d...`; screenshot `dba96708...` | aparelho físico e homologação humana |
| PERF-ASSETS | bruto/gzip/Brotli | PASS LOCAL | browser SHA `cefd4dc...` | `Content-Encoding` no host alvo |
| PERF-IA | seleção versus documento inteiro | PASS LOCAL | 608 vs 12.634 tokens; SHA `fa790e10...` | custo USD requer modelo/preço explícito |
| REG-PY | todos `test_wordcraft*.py` | PASS 502 / SKIP 1 | 42,37 s | `bash -n` somente em Linux |
| REG-NODE | host, validador e browser | PASS 66/66 | execução local conjunta | CI do HEAD atual |
| REG-PRODUTO | suíte Python integral, 3.853 casos coletados | PASS 3.382 / SKIP 471 | JUnit `tests-full-branch-review-utf8.xml`, SHA `048dbfc6...`; 293,22 s | skips de integrações externas permanecem separados |

SKIP e simulação não são promovidos a PASS real. JWT sintético não é Auth real;
emulação móvel não é aparelho físico; raster histórico não aprova o corpus atual.
A primeira tentativa da suíte integral sob sandbox encerrou no primeiro `AppTest`.
O caso isolado passou fora do sandbox em 8,87 s. Uma rodada integral inicial fora
do sandbox expôs 54 leituras CP1252 de arquivos UTF-8, quatro paths Git temporários
longos e um assert derivado do mojibake. A repetição com `PYTHONUTF8=1` e basetemp
curto eliminou todas essas causas e concluiu sem falhas. O JUnit final possui
786.331 bytes e SHA-256
`048dbfc6e062ee2ce335118fc835ef67036a66fbd2e529e7b9f6845bbe5306fd`.

## E. Fidelity e operação

- DOCX/PDF: 16 variantes importadas, validadas, exportadas e reimportadas; PDF
  nativo total de 87 páginas. A comparação LibreOffice corrigida em Linux falta.
- Texto/tabelas: oráculos conferem texto, links, headers/footers, 210 códigos,
  linhas monetárias, Decimal e total. Recursos C10 declarados são preservados.
- Timbrado/snapshot: identidade, secretaria, portaria e signatários são congelados
  por revisão e não recalculados na reabertura.
- Performance: perfis exatos de 20/100 páginas; bundle 41.860.573 bytes bruto,
  15.492.381 gzip e 9.804.706 Brotli; memória de browser/WASM registrada.
- Mobile: execução e exportação passam em 390×844; o WASM confirma faixa
  recolhida, interface 75%, largura da página e coluna única, e a captura não
  repete o recorte material anterior. `mobile_usability_approved=false`
  permanece correto porque aparelho físico e homologação humana não ocorreram.
- IA: uma chamada hipotética em ambos os cenários; recorte por seleção evita
  12.026 tokens de entrada (95,1876%); zero chamadas pagas no ensaio.

## F. Segurança e licença

- Browser serve somente mapa explícito em loopback, CSP/COOP/COEP, sem documentos
  em static, sem segredos no WASM e com envelope fechado/limites de bytes.
- Owner reconcilia perfil/tenant, revalida atos sensíveis e usa RPCs transacionais.
  RLS local foi exercitada; Auth real permanece requisito separado.
- Lock upstream fixa WordCraft `5336156`; overlay recusa fonte/bytes divergentes.
- Closure de distribuição: 251 pacotes, 186 textos; 17 exigem revisão, 12 não
  trazem texto e 14 não trazem licença de código. Distribuição não aprovada.
- Marcas upstream foram removidas do build integrado; fontes incluídas possuem
  proveniência/avisos, sem redistribuição de fontes proprietárias conhecidas.
- Nenhum segredo, PII, documento real ou chamada paga foi usado nas provas.

## G. Gates

| Gate | Estado | Evidência |
|---|---|---|
| 0 Auditoria | BLOCKED | closure reproduzida; revisão jurídica de 17 pacotes pendente |
| 1 POC editor | PASS LOCAL | navegador real, persistência/reload e exportação |
| 2 Persistência | BLOCKED | implementação local passa; falta Auth real |
| 3 Exportação | BLOCKED | nativo passa; LibreOffice Linux/raster atual pendente |
| 4 GovBot/Patches | PASS LOCAL | owner único, stale, atomicidade e Undo comprovados |
| 5 Seis capacidades | BLOCKED | todas passam localmente; falta homologação/Auth real |
| 6 Limpeza | BLOCKED | exclusividade de UI passa; retirada depende de canário e G0/G2/G3/G7 |
| 7 Homologação | BLOCKED | infraestrutura-alvo, Auth real, mobile e orçamento finais pendentes |

## H. Próximos passos exatos

1. Executar `.github/workflows/wordcraft-fidelity.yml` em Ubuntu e preservar os
   artifacts, incluindo raster de todos os PDFs e `bash -n`.
2. Executar `.github/workflows/auth-real.yml` com GoTrue oficial e provar login,
   refresh, revogação, mudança de perfil e RLS cruzada com JWT real.
3. Submeter a closure de licenças à revisão responsável; não distribuir antes do
   aceite ou resolução dos pacotes sem texto/licença.
4. Homologar no host/tenant de teste: `Content-Encoding`, cold/warm, memória,
   mobile físico, latência de locks e orçamento. Flags continuam OFF.
5. Com autorização específica, executar canário de um tenant e provar rollback
   preservando revisões nativas e rascunhos legados.
6. Somente após os gates anteriores, inventariar chamadas restantes, remover UI
   concorrente/código morto e repetir regressão antes de pedir merge/deploy.

Rollback: desligar a flag restaura a superfície legada; revisões, originais,
snapshots, auditoria e pacotes nativos permanecem imutáveis. Não executar down
migration destrutiva nem converter revisões nativas de volta para Markdown.

**Veredito: NÃO APTO.** A branch está apta para revisão técnica e para executar
os workflows externos de homologação, mas não está apta para rollout, retirada
do legado, merge ou produção.
