# C06 — emissão condicional da ARP

Estado: **PASS LOCAL DO OWNER E UI LEGADA; RPC SQL REAL AINDA PENDENTE**

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

Os testes do owner usam transporte e motor determinísticos; os testes legados
exercitam a geração e a UI Streamlit. Ainda falta repetir a recusa por PostgREST
contra a RPC real com estado SQL adulterado para que o banco seja também uma
linha independente de defesa. Nenhuma emissão oficial ou produção foi tocada.
