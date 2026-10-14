# Contratos e gates observados

## Autoridade e formato

O GovConnect continua dono de identidade, processo, fatos, aprovação, trilha e emissão.
`src/wordcraft_protocol.py` é somente a fronteira de validação do protocolo; não é
DocumentoService, CAS, RLS nem persistência. Não há import desse módulo no fluxo operacional.
O campo experimental `gc-wordcraft-snapshot/v1` identifica o contêiner candidato do
adaptador Rust, ainda pendente de compilação e testes. A validação Python do envelope
não valida o modelo documental: não enviar esses bytes diretamente ao banco.

**JSON nativo isolado não é candidato seguro para documento institucional.** No SHA
inspecionado, `crates/doc/src/lib.rs::Document` usa `#[serde(skip)]` em `media` e
`passthrough`. O `engine::io` abre JSON via `serde_json::from_slice`. Assim, serializar
apenas o modelo omite imagens e partes de origem. Isso precisa de um contêiner que
preserve esses campos ou DOCX com fidelidade demonstrada antes de escolher o canônico.
É evidência estática, não teste Rust de roundtrip. Posições usam story/path/offset;
não foi comprovada estabilidade de IDs após inserção de parágrafos ou tabelas.

## Fronteira implementada, ainda sem transporte

- Envelope fechado: protocol/request/instance/session/document/revision/event/sequence/nonce/payload.
- Não aceita tenant, role, comandos, caminhos ou eventos ACK vindos do cliente.
- Origin configurada, janela validada pelo host (`event.source`, a implementar), nonce e replay.
- Máximo 8 MiB decodificados, sequência inteira segura para JavaScript, hash SHA-256.
- opening → ready → dirty → saving → saved somente com ACK confiável correlacionado.
- Edição durante envio/erro continua dirty após confirmação do checkpoint anterior.
- Timeout/erro conserva o mesmo request e bytes para retry idempotente pelo futuro backend.
- Conflito bloqueia novas alterações e ACKs tardios; exige reconciliação explícita.

Não inferir autenticação a partir de `source_ok`: ele é um contrato interno para o
futuro adaptador, não uma alegação confiável de um evento do navegador. ACL real deve
ocorrer em cada operação do backend, com JWT do usuário e transação de revisão.

## Lacunas do shell upstream

`apps/wordcraft-web/src/web.rs` constrói `WebShell { app, inbox, saves }`; o documento
é aberto pela inbox e Save usa serviços de download/picker. `app.autosave = false`.
Não existe neste código a API GovConnect proposta. Picker cancelado já possui guarda
própria, mas download concluído não significa commit no GovConnect.

O wrapper deve substituir serviços de arquivos e desabilitar recursos externos no
modo embutido, expor apenas operações tipadas e preservar a instância entre reruns.
Comandos de IA continuam passando pelo pipeline de patches canônico. Nenhum comando
genérico de `Session::run` será exposto ao browser ou à LLM.

## Gates desta entrega parcial

| Gate | Estado | Evidência / dependência |
|---|---|---|
| 0 Auditoria | BLOCKED (parcial) | HEADs, código-chave e licenças lidos; fontes/build/SBOM completos ausentes |
| 1 Vertical slice | BLOCKED | sem toolchain completo, WASM compilado ou ponte browser conectada |
| 2 Persistência | BLOCKED | depende de G1; sem CAS/RLS/roundtrip real |
| 3 Exportação | BLOCKED | sem corpus comparativo WordCraft × legado |
| 4 GovBot/Patches | BLOCKED | regressão do aplicador passa; sem âncoras nativas homologadas |
| 5 Seis capacidades | BLOCKED | serviços atuais preservados, integração contextual não implementada |
| 6 Limpeza | BLOCKED | nenhuma substituição comprovada; nenhuma retirada autorizável |
| 7 Homologação | BLOCKED | sem prova E2E, isolamento, emissão ou performance |

Flags operacionais não foram alteradas. Não existe opção WordCraft habilitada.
Não houve merge, deploy, migration aplicada, convite Auth ou consumo de IA paga.

## Retomada reproduzível

1. Obter checkout completo do SHA em `upstream.lock.json`, com Cargo.lock e sub-recursos necessários.
2. Disponibilizar Rust compatível (upstream requer 1.90+), target wasm32-unknown-unknown e Trunk;
   fixar as versões efetivamente usadas no manifesto de build antes de declarar reprodução.
3. Executar `python scripts/wordcraft_preflight.py --source CAMINHO` (apenas pré-requisitos).
4. No upstream executar `cargo xtask ci`; na pasta apps/wordcraft-web, `trunk build --release`.
5. Conservar log, hashes de Cargo.lock/assets/WASM, tamanho e ferramentas; auditar dependências e fontes.
6. Adaptar shell Rust e host Streamlit segundo os contratos 02; provar abrir/editar/checkpoint/
   ACK persistido/reabrir/exportar num documento sintético A4 antes de promover G1.

Trunk exige obtenção de suas dependências de build; presença de executável não é prova
de build. Testes Python de contrato não certificam segurança do transporte nem RLS.

## Substituição e rollback

### Entrega de eventos pelo componente v2

O estado `edit` transporta `{events: [envelope, ...]}` com todos os eventos ainda
não consumidos, em sequência. Isso preserva checkpoint/changed quando atualizações
de estado são coalescidas. `Ponte.receber_lote` valida o lote inteiro em uma cópia
antes de consumir qualquer evento novo. Prefixos já consumidos podem reaparecer em
reruns. Lacunas, desordem e lote inválido não consomem estado. Limites: 256 eventos
pendentes e 16 Mi caracteres de payload base64 no lote; limites individuais permanecem.

O futuro renderer devolve `event_ack=ponte.sequence` após aceitação do lote, para o
host retirar somente o prefixo consumido. Esse ACK de transporte não significa save.
Gravação continua exigindo commit backend, revisão/hash e `confirmar_checkpoint`;
somente então o renderer devolve `ack` de persistência. A fila não grava dados fora
da memória do componente. Overflow exige reconciliação sem descartar o rascunho.

Testes Node/Python cobrem coalescência simulada e atomicidade. Streamlit/browser real,
timeout, desmontagem e callback persistido continuam pendentes do gate 1.

Todos os recursos da matriz 03 permanecem no estado **LEGADO MANTIDO PARA COMPATIBILIDADE**.
O código novo é isolado e sem consumidores operacionais: reverter seu commit retira
a fundação sem tocar documentos. Não existe ainda rollback de documentos WordCraft
porque nenhum documento foi migrado/criado nesse formato. Para futura ativação:
preservar bytes originais, revisões, snapshots e artefatos antes de trocar UI; flag
isolada não fornece rollback de dados. Retirar TipTap ou exportadores agora seria incorreto.
