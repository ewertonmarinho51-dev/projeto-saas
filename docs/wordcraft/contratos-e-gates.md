# Contratos e gates observados

## Autoridade e formato

O GovConnect continua dono de identidade, processo, fatos, aprovação, trilha e emissão.
`src/wordcraft_protocol.py` é somente a fronteira de validação do protocolo; não é
DocumentoService, CAS, RLS nem persistência. Não há import desse módulo no fluxo operacional.
O campo experimental `gc-wordcraft-snapshot/v1` identifica o contêiner candidato do
adaptador Rust. Os 11 testes nativos passaram no run 38651115647; a API WASM integrada
e o roundtrip do corpus ainda aguardam conclusão do build. A validação Python do envelope
não valida o modelo documental: não enviar esses bytes diretamente ao banco.

**JSON nativo isolado não é candidato seguro para documento institucional.** No SHA
inspecionado, `crates/doc/src/lib.rs::Document` usa `#[serde(skip)]` em `media` e
`passthrough`. O `engine::io` abre JSON via `serde_json::from_slice`. Assim, serializar
apenas o modelo omite imagens e partes de origem. Isso precisa de um contêiner que
preserve esses campos ou DOCX com fidelidade demonstrada antes de escolher o canônico.
O contêiner do adaptador preserva media/passthrough e tem testes nativos de roundtrip;
isso ainda não prova a fidelidade de importação/exportação dos documentos institucionais.
Posições usam story/path/offset;
não foi comprovada estabilidade de IDs após inserção de parágrafos ou tabelas.

## Fronteira implementada, ainda sem proprietário de persistência

- Envelope fechado: protocol/request/instance/session/document/revision/event/sequence/nonce/payload.
- Não aceita tenant, role, comandos, caminhos ou eventos ACK vindos do cliente.
- Origin configurada e nonce/replay no protocolo. O transporte atual é o estado do componente
  Streamlit v2, não um listener público de postMessage. `source_ok` permanece uma condição
  interna do chamador e nunca representa autenticação ou autorização do usuário.
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
O overlay cria uma entrada explícita em `govconnect_browser.rs` com a própria Session,
sem usar esse shell de picker/download. Picker cancelado já possui guarda
própria, mas download concluído não significa commit no GovConnect.

O wrapper usa Services::default, restringe recursos externos e expõe operações tipadas.
O host conserva a instância entre reruns; o laboratório local comprovou abertura, edição, commit, ACK e recarga com WASM real. A exportação da revisão editada continua pendente.
Comandos de IA continuam passando pelo pipeline de patches canônico. Nenhum comando
genérico de `Session::run` será exposto ao browser ou à LLM.

## Gates desta entrega parcial

| Gate | Estado | Evidência / dependência |
|---|---|---|
| 0 Auditoria | PARCIAL | baseline upstream reproduzido; SBOM e 13 avisos reunidos; revisão de distribuição incompleta |
| 1 Vertical slice | EM EXECUÇÃO | 12 testes nativos passam; build 896 aprovado; navegador local abriu/editou/gravou/reabriu texto e célula; exportação da revisão editada pendente |
| 2 Persistência | PARCIAL | owner mínimo para G1 implementado; 13 testes SQL reais de CAS/RLS/histórico; migração de legado e homologação definitivas pendentes |
| 3 Exportação | PENDENTE | corpus sintético canônico gerado (3 DOCX/PDF, tabela de 210 itens); roundtrip e aprovação visual pendentes |
| 4 GovBot/Patches | BLOCKED | regressão do aplicador passa; sem âncoras nativas homologadas |
| 5 Seis capacidades | BLOCKED | serviços atuais preservados, integração contextual não implementada |
| 6 Limpeza | BLOCKED | nenhuma substituição comprovada; nenhuma retirada autorizável |
| 7 Homologação | BLOCKED | sem prova E2E, isolamento, emissão ou performance |

Flags operacionais não foram alteradas. Não existe opção WordCraft habilitada.
Não houve merge, migration remota, convite Auth ou consumo de IA paga. A migration 20261015035015 foi aplicada somente ao PostgreSQL descartável em loopback. O primeiro
push disparou uma integração Vercel preexistente, que falhou; o auto-deploy desta branch
foi depois desabilitado em vercel.json. Não há evidência de implantação bem-sucedida.

## Retomada reproduzível

1. Usar a revisão pinada em `upstream.lock.json` e o overlay da mesma revisão GovConnect.
2. Executar o workflow isolado wordcraft-build.yml: Rust 1.99.0, target wasm32 e Trunk
   0.21.14 verificado por hash. O Windows local não tem o linker MSVC; WSL não instalado.
3. A reutilização do baseline exige run, ZIP, pin e Cargo.lock exatos; qualquer falha
   retorna aos gates upstream completos. Os testes/build da integração sempre executam.
4. Preservar logs e artefatos. Instalar JS/WASM apenas em laboratório marcado usando
   wordcraft_local_assets.py com SHA do ZIP e commit produtor verificados.
5. Validar checkpoints no backend via wordcraft_native.py com Node 24 e SHA do manifesto
   fixado pelo servidor; nunca aceitar caminhos/hashes do cliente como configuração.
6. Usar DocumentoService e concluir a exportação da revisão persistida editada; abrir/editar/checkpoint/ACK/reabrir já foi observado no laboratório A4 e tabela sintética.

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

O renderer devolve `event_ack=ponte.sequence` após aceitação do lote, para o
host retirar somente o prefixo consumido. Esse ACK de transporte não significa save.
Gravação continua exigindo commit backend, revisão/hash e `confirmar_checkpoint`;
somente então o renderer devolve `ack` de persistência. A fila não grava dados fora
da memória do componente. Overflow exige reconciliação sem descartar o rascunho.

Testes Node/Python cobrem coalescência simulada, atomicidade, falhas do IPC e evento
changed emitido antes do ACK mas entregue depois dele. O laboratório real usa
PostgreSQL/PostgREST em loopback, JWT sintético verificado e o bundle 896 pinado.
Texto: revisão 2 reaberta com hash idêntico. Tabela: revisão 3 reaberta após edição
real de célula, hash e82d3f9b2f7e229c7074d4d16bfdcdc7d9a81c3096833b9de1c6d76c26a4fd5f.
Isso não certifica GoTrue, staging, exportação editada, fidelidade institucional ou G7.
O título nativo ainda exibe estado baseado em arquivo local; o estado de persistência
válido é o confirmado pelo host. Essa divergência visual permanece pendente.

Todos os recursos da matriz 03 permanecem no estado **LEGADO MANTIDO PARA COMPATIBILIDADE**.
O código novo é isolado e sem consumidores operacionais: reverter seu commit retira
a fundação sem tocar documentos. Não existe ainda rollback de documentos WordCraft
para documentos de produção; somente documentos sintéticos foram criados no laboratório. Histórico sintético fica preservado no banco local. Para futura ativação:
preservar bytes originais, revisões, snapshots e artefatos antes de trocar UI; flag
isolada não fornece rollback de dados. Retirar TipTap ou exportadores agora seria incorreto.
