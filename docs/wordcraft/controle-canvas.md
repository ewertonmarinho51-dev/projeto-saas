# Controle do canvas antes de aprovação e patches

Decisão registrada antes da implementação deste incremento, em 15/10/2026.
Reutiliza a mesma Ponte, host Streamlit v2 e GovConnectEditor/Session. Não há
segundo editor, persistência de navegador ou comando genérico de Session.

O estado `ready/saved` conhecido pelo servidor não demonstra que o canvas ainda
está limpo: uma digitação pode preceder seu aviso `document.changed`. Antes de
um ato sobre a revisão visível, o backend precisa solicitar um bloqueio com UUID
novo, revisão e hash exatos. O host conserva seu checkpoint pendente no mesmo
fluxo CAS/ACK; não cria uma confirmação local de gravação. Se houver digitação
ainda não observada pelo backend, recusa o bloqueio e o autosave normal precisa
terminar antes de uma nova solicitação e análise. Quando estiver limpo,
bloqueia interação nativa antes de ler bytes/hash/geração e responde ao comando.
Se conteúdo, revisão ou contexto divergir, a operação não ganha autorização.

O bloqueio nativo conserva Session, seleção e histórico. O hook de input deixa
de encaminhar eventos enquanto bloqueado; a renderização continua. A API de
edição também recusa mutações externas durante esse bloqueio, salvo o método
específico de patch preparado e correlacionado que será integrado separadamente.
Não substituir documento nem remontar a instância para aplicar uma correção.

A resposta é um evento fechado, com escopo/nonce/sequência existentes e o UUID
do comando backend. O servidor não aceita comando de aprovação, tenant, papel,
plano de IA ou ACK emitido pelo navegador. Somente sua própria solicitação
pendente pode receber prova de canvas congelado; ela continua sujeita a ACL,
fontes, revisão/hash e transação no owner. Essa prova não é uma aprovação.

O servidor libera o bloqueio explicitamente, usando o mesmo UUID. Em erro de
commit, mantém rascunho e permite reconciliação; em aprovação, pode conservar
o canvas somente leitura. Mudança de documento/logout destrói a instância e
invalida a solicitação. Eventos atrasados de outra instância não a reativam.

Testes previstos: digitação antes do pedido, edição durante hashing/ACK,
checkpoint/erro/conflito pendente, comando repetido/divergente, evento forjado,
geração/hash errados, release stale, rerun sem perda de instância e bloqueio
efetivo de teclado/toolbar no navegador real. Testes Python/Node e Rust não
substituem a prova de interface. Enquanto esta estiver pendente, não se declara
apto o consumidor operacional de aprovação ou o Undo de um patch persistido.

Decisão de drenagem registrada antes do código em 16/10/2026: pedir bloqueio
não pode apagar uma tecla/IME que o eframe já capturou e ainda não aplicou.
No eframe 0.36.2 pinado, `AppRunner::logic` coleta RawInput, chama
`raw_input_hook` e então executa `WordApp.logic` e `WordApp.ui`. A edição de
texto chega à Session no UI; um hook isolado ainda não constitui barreira.

O pedido nativo passa por requested/draining/locked. Desde requested, as APIs
externas de edição recusam mutação. RawInput já capturado continua pelo fluxo
normal durante draining; somente um UI concluído, sem teclas/botões mantidos
nem preedit IME ativo, pode declarar locked. Composição pendente continua a
receber seus eventos; nunca ganha uma prova parcial. A inicialização de fontes
precisa ter terminado antes de aceitar o pedido. Aba oculta, sem UI efetivo,
não ganha prontidão. Nenhuma Session é substituída e não há fila de documento
paralela, persistência no navegador ou comandos de texto sintéticos.

O host exige `interaction_lock_ready()` explícito e aguarda frames antes de
serializar/hash, com teto de 120 tentativas e 1.500 ms. A espera de um frame
também tem watchdog. Bundle antigo, timeout ou contexto divergente recusam a
prova e liberam o pedido com segurança. Cada retomada assíncrona revalida a
operação, estado, revisão e hash; dispose não publica nem reativa a instância.
Edição drenada que altere dirty/geração recusa freeze como dirty, conserva os
bytes na mesma Session e volta ao checkpoint/CAS/ACK normal antes de nova
análise e UUID. Conflito durante o hash não pode ressuscitar frozen; release
exige uma prova concluída e UUID terminal não pode ser reutilizado.

Os testes Node injetam explicitamente o avanço de frames de um stub de
transporte para verificar ordem, input pendente, IME, timeout e cancelamento.
Não simulam uma comprovação de navegador, teclado, composição ou toolbar reais.
Essa comprovação permanece um gate independente com o WASM recompilado.

Uma prova que já entrou no outbox conserva o bloqueio mesmo se o transporte
lançar erro: eventual entrega ainda precisa descrever um canvas bloqueado.
Ela não produz uma segunda resposta de falha conflitante. Antes de qualquer
prova, erros/timeout liberam o pedido; depois dela, só release correlacionado
ou encerramento do contexto remove o bloqueio.

Verificação local: 30 testes Node do host passaram, incluindo watchdog com
relógio real e callbacks de frame injetados; 107 testes Python de Ponte/overlay
passaram em 1,01 s. Rustfmt e diff-check passaram. O novo método WASM e o input
real de teclado/IME ainda precisam do build e ensaio no navegador; os stubs
Node não são apresentados como prova desses comportamentos nativos.
