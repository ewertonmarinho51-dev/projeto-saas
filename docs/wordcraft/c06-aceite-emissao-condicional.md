# C06 — emissão condicional da ARP

Estado: **PASS LOCAL DO OWNER, UI LEGADA E POSTGRESQL REAL**

O owner da emissão oficial deixou de aceitar o conjunto de documentos indicado
pela UI como autoridade. Antes de exportar qualquer byte, ele relê `processos.dados`
pelo cliente autenticado e deriva a sequência completa com
`config.exportaveis_do_processo`, a mesma regra canônica do fluxo existente.

Para processo SRP, o conjunto obrigatório inclui DFD, ETP, Mapa de Riscos, TR,
Edital e ARP. Para processo sem SRP, inclui os cinco primeiros e proíbe ARP,
mesmo que a UI ou um estado residual a envie. O owner também recusa omitir ARP
de um processo SRP e recusa formulário ausente ou inválido. A decisão ocorre
antes de montar DOCX/PDF ou chamar a RPC de emissão.

## Cobertura

- SRP com ARP: aceito e segue para empacotamento;
- não SRP sem ARP: aceito e segue para empacotamento;
- não SRP com ARP residual: recusado antes do empacotamento;
- SRP sem ARP: recusado antes do empacotamento;
- transições SRP → não SRP e não SRP → SRP no estado legado;
- ZIP/PDF/DOCX legado e botões finais seguem a mesma regra canônica.

Uma migration aditiva instala um trigger antes da inserção do snapshot oficial.
Ele relê `processos.dados` e compara a decisão SRP com a presença da ARP no JSON
validado pela RPC. A função do trigger não é executável diretamente por `anon`,
`authenticated` ou `service_role`.

Em PostgreSQL 16 local descartável, uma chamada `service_role` com processo SRP
sem ARP e outra com processo não SRP contendo ARP residual foram recusadas com
`PT409`; nenhuma emissão parcial permaneceu. A emissão não SRP coerente, retry
idempotente, imutabilidade e isolamento continuaram aprovados. O PostgREST local
também recusou `anon` na RPC de emissão; o caminho positivo autenticado com JWT
emitido pelo GoTrue permanece fora deste aceite. Nenhuma migration remota,
emissão oficial ou produção foi tocada.
