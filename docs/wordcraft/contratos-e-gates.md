# Contratos e gates observados

Snapshot de integração: 16/10/2026. O relatório formal mais recente fica em
`outputs/RELATORIO_WORDCRAFT_CONTINUACAO_10.md` na pasta da tarefa. Resultados
históricos não substituem CI do commit atual ou a versão efetivamente implantada.

## Autoridade, formato e transporte

GovConnect continua dono de identidade, processo, fatos, aprovação, trilha e
emissão. `DocumentoService` reutiliza os clientes canônicos de usuário e servidor;
seu contexto é reconciliado com o JWT e os atos sensíveis rechecados nas RPCs.
`Ponte` valida o transporte, sem conceder ACL ou produzir persistência.

O formato experimental `gc-wordcraft-snapshot/v1` preserva modelo, media e
passthrough. JSON isolado de Document não serve: no upstream pinado, media e
passthrough têm serde(skip). O codec nativo, a validação e a exportação usam o
mesmo motor. Nenhum novo documento nativo é salvo como Markdown. Projeções de
análise são somente leitura, sem autoridade de persistência ou endereço de edição.

O build integrado `38823785860`, commit `f23a6c5`, passou em codec, patches,
histórico da Session, UI, Clippy, WASM e import/export. Isso não comprova que os
incrementos posteriores de controle do canvas já estejam compilados ou observados.

O envelope fechado exige protocol/request/instance/session/document/revision/
event/sequence/nonce/payload. O componente v2 conserva a instância entre reruns.
O outbox transmite até 256 eventos não consumidos, sem descartar rascunho; o ACK
de transporte apenas remove o prefixo aceito. Limite individual: 8 MiB de bytes,
SHA-256 e inteiros seguros para JavaScript. Tenant, papel, plano de IA e ACK não
são concedidos por eventos do cliente. `source_ok` é só contrato interno do host.

A gravação usa CAS e operação idempotente no banco. O ACK de persistência exige
revisão/hash/operação confirmados pelo owner. Digitação durante envio mantém o
rascunho dirty depois do ACK anterior. Retry conserva os bytes e a operação;
conflito impede sobrescrita e requer reconciliação. Picker/download upstream não
participa desse fluxo. Recursos externos e comandos genéricos de Session não são
expostos à LLM; o adaptador aceita operações textuais fechadas e delimitadas.

## Persistência, aprovação e patches

Originais de importação, índice de blocos, snapshot institucional e restauração
ficam na revisão imutável existente. Restaurar cria nova revisão CAS; histórias
sem prova continuam desconhecidas. IDs só são preservados quando unicidade ou
linhagem de uma operação verificada justificam a identidade. Posição parecida
não prova identidade. A importação é admitida antes de chegar ao WASM.

A aprovação individual reutiliza governanca_aprovacoes, qualidade e evento
canônico na mesma transação. Vincula revisão/hash/build/fontes/snapshot exatos.
O ramo nativo não rotula Markdown antigo como aprovado nem avança o wizard.
A navegação e o pacote ZIP auditável já consomem somente revisões nativas
aprovadas. A emissão oficial é uma ação separada: persiste os pacotes DOCX/PDF,
vincula fontes, artefatos, aprovação, snapshot e build, registra a publicação
na governança existente e cruza `aprovado` → `emitido` atomicamente. Reabrir a
emissão usa os bytes imutáveis persistidos. O documento consolidado único e a
prova via PostgREST/Auth real permanecem pendentes. O controle
freeze/release do canvas está em implementação e testes; não se declara frescor
da revisão visível apenas porque o backend conhecia o estado ready/saved.

Patches passam pelo mesmo corretor/aplicador/FIXED/escopo/diff. A preparação é
backend e selada pela instância do owner. O wrapper de lote reutiliza checkpoint,
com CAS de todas as fontes, grava revisões e auditoria do ciclo na mesma transação.
Falha no segundo alvo ou evento reverte tudo. Checkpoints do host precisam
corresponder exatamente aos bytes preparados. Para alvo único, o host agora
aplica o comando na Session viva, valida o hash de destino e correlaciona o
checkpoint ao mesmo `operation_id`; o ACK só sai depois do recibo transacional.
Divergência ou recusa nativa verifica a restauração exata e mantém o canvas
utilizável, sem inventar checkpoint ou ACK. O hash usado pela Session viva é o
dos bytes persistidos que abriram o editor; ele só muda após ACK do backend ou
recarga limpa. Isso evita recusar um contêiner JSON válido apenas porque sua
serialização não canônica difere da serialização interna do documento. A prova
positiva com finding real havia parado num bundle anterior. O adapter atual foi
recompilado localmente e o runner provou patch, stale rejection, Undo/Redo e dois
canvas simultâneos independentes; essa prova ainda usa ACK de transporte
simulado. O mesmo runner capturou a seleção nativa, passou uma resposta mockada
pelo gateway e compilador GovBot reais, aplicou o resultado no canvas, confirmou
o hash alterado por ACK simulado e só então desfez para o hash exato, confirmado
por outro ACK simulado. O teste conjunto que substitui esses ACKs pelo commit e
recibo reais do backend no mesmo percurso permanece pendente.

A captura de seleção agora é um comando servidor, ligado à revisão/hash limpos.
O texto retornado serve apenas para resolver um bloco integral único entre paths
já autorizados por finding do owner; posição do navegador nunca vira endereço
de patch. Edição invalida a seleção. Propostas manuais e do gateway GovBot
existente passam pelo mesmo compilador e diff. A passagem browser/bundle real
usa IA mockada, conforme o plano de testes, e não afirma chamada de provedor.

## Gates da missão integral

| Gate | Estado | Evidência e lacuna material |
|---|---|---|
| G0 Auditoria | PARCIAL | baseline reproduzido; closure WASM com 251 pacotes/186 textos; 17 expressões para revisão, 12 pacotes sem texto e 14 sem texto da licença de código; distribuição não aprovada |
| G1 Percurso mínimo | PASS LOCAL LIMITADO | navegador abriu/editou/salvou/recarregou/exportou texto, timbrado e tabela de 210 itens; g1-evidencias.md; sem promoção a G3/G7 |
| G2 Persistência | PARCIAL | importação, originais, índices, restauração, aprovação, consumidor source-aware, ZIP auditável e emissão oficial transacional implementados; documento consolidado e prova PostgREST/Auth real pendentes |
| G3 Fidelidade | PARCIAL | 16 DOCX passam no roundtrip nativo; 16 PDFs/87 páginas têm revisão visual local sem corte; LO baseline16/70 páginas; derivado6/16 casos,44/50 PNGs iguais e6 diferenças em tabelas; prova Linux pendente após duas falhas limitadas Windows |
| G4 Patches | PARCIAL | motor real preservou79 IDs/27 blocos protegidos,8 negativos recusados;188 SQL passaram; bundle atual passou canvas/patch/Undo, multi-canvas e seleção GovBot mockada pelo gateway real; prova backend coeva passou commit/reopen/retry/stale/auditoria em PostgreSQL/PostgREST/JWT/RLS descartáveis; falta unir canvas→commit→ACK real→Undo posterior no mesmo percurso |
| G5 Seis capacidades | PARCIAL | compilador/painel/host, consumidor source-aware, aplicação transacional de template e pacote auditável ligados sob flag OFF; admissão recusa bundle QA; falta artefato operacional homologado e corpus A-D completo |
| G6 Paridade e retirada | PENDENTE | nenhuma funcionalidade legada retirada; a transição agora falha fechada antes de runtime/importação quando existe rascunho legado divergente e o preserva na sessão; substituição e retirada continuam condicionadas à comprovação integral |
| G7 Homologação | PARCIAL | CAS/RLS/imutabilidade SQL e HTTP sintéticos; runner Chromium passou em CI e Windows coevo, medindo startup, abertura e heap JS/DOM; GoTrue Linux implementado, primeiro run falhou preflight; Auth real, memória total/WASM e orçamento na infraestrutura-alvo pendentes |

CI: f23a6c5 teve build WASM e produto aprovados. O commit publicado 428acb6
acrescentou aprovação/Auth e falhou no scanner por URLs sintéticas de loopback e
no preflight da forma do archive oficial Auth. As correções precisam de novo CI;
nenhuma dessas falhas foi convertida em sucesso por hipótese ou teste parcial.

## Reprodução, ativação e rollback

Usar upstream.lock.json e overlay da mesma revisão, toolchains pinados e hashes
de ZIP/manifesto/assets. Reutilizar somente o baseline upstream aprovado e exato;
os checks da integração sempre executam. Instalar assets apenas no laboratório
marcado, nunca servir checkpoints em static. O IPC Node tem stdin/stdout limitados
e ambiente sem credenciais; config de bundle/manifesto vem do servidor.

Os bancos de ensaio são locais descartáveis em loopback. Sessões/JWTs sintéticos
não são GoTrue. O título corrigido foi observado como Documento1 — GovConnect;
a única confirmação de persistência continua sendo o ACK do backend. Provas
históricas e limitações estão em g1-evidencias.md, persistencia-g2.md,
ato-unico-aprovacao.md, patches-persistencia.md e libreoffice-local.md.

Estado documental mantido pelo Streamlit é ligado à identidade autenticada.
Logout e mudança de usuário, tenant ou secretaria revogam owner, bridges,
checkpoints, preparações, widgets, pacotes e eventos do componente antes de uma
nova montagem. Renovação de token para a mesma identidade conserva o estado.
Essa defesa local não substitui a prova RLS com JWT real de G7.

Ao ligar a superfície WordCraft durante uma sessão, um rascunho divergente no
bucket ou widget do editor legado bloqueia a nova montagem antes de carregar o
runtime, criar owner ou importar documento. O texto permanece na sessão e o
operador deve salvar ou descartar no fluxo legado. Isso evita ocultação e
importação prematura; ainda não comprova paridade nem autoriza retirar o legado.

Todos os recursos da matriz03 permanecem LEGADO MANTIDO PARA COMPATIBILIDADE.
TipTap, exportador e consumidores antigos não foram retirados. Não há flag
operacional WordCraft ativa, merge, migration remota ou deploy autorizado.
O primeiro push histórico disparou Vercel e falhou; o auto-deploy da branch foi
depois desabilitado em vercel.json. Não há implantação bem-sucedida comprovada.

Rollback operacional exige preservar originais, revisões, snapshots e artefatos,
além de consumidor source-aware. Reverter flag/UI não converte dados nativos.
Somente dados sintéticos foram usados; nenhum rollback de dados em produção foi
executado ou certificado. Missão permanece ativa e não apta para produção.
