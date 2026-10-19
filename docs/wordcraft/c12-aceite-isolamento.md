# C12 — aceite local de isolamento documental e de sessão

Data: 19/10/2026
Escopo: PostgreSQL/RLS, PostgREST autenticado, canvas Chromium/WASM e fronteira de sessão Streamlit
Estado: **PASS LOCAL PARCIAL; GoTrue real ainda pendente; Storage N/A no desenho atual**

O manifesto C12 permanece `NOT_TESTED`, pois seus DOCX com marcadores
disjuntos são entradas offline. A execução funcional está dividida em duas
provas correlacionadas pelos mesmos marcadores.

| ID | Camada | Ações e observado | Estado |
|---|---|---|---|
| C12-SQL-01 | PostgreSQL/RLS | cria processos e revisões para tenants A/B; cada sessão `authenticated` lê somente seu marcador; escrita cruzada falha com `InsufficientPrivilege`; `anon` não possui `SELECT` na tabela privada; consulta administrativa final confirma uma revisão original por tenant | PASS LOCAL |
| C12-SESSION-01 | sessão/cache/bridge | coloca owner, documento, bridge, preparação, projeção e evento do componente do tenant A; login no tenant B revoga todo o namespace antes de armazenar a nova identidade; nenhum marcador A permanece | PASS LOCAL |
| C12-HTTP-ANON-01 | PostgREST real local | 68 provas de catálogo/comportamento; `anon` não lê tabelas privadas, não escreve no objeto descartável e não executa RPCs documentais, inclusive emissão e aplicação de template | PASS LOCAL LIMITADO |
| C12-HTTP-CANVAS-02 | PostgREST/RLS + Chromium/WASM | dois JWTs sintéticos de tenants distintos atravessam o PostgREST real; o tenant B não abre nem cria checkpoint no documento A; probes antes/depois conservam instância, geração e hash do canvas A, e head/revisões/auditoria permanecem idênticos | PASS LOCAL |
| C12-TWO-CANVAS-03 | dois processos Chromium/WASM + dois owners/JWTs sintéticos | cria documento próprio para A e B; cada owner reabre somente sua head; dois processos de browser mantêm tokens de instância e hashes distintos; leituras cruzadas A→B e B→A são recusadas; commit de A não altera geração, hash ou instância de B | PASS LOCAL |
| C12-STORAGE-01 | arquitetura atual | zero buckets; bytes nativos persistem nas tabelas privadas e o ensaio registra Storage como `NAO_APLICAVEL` | N/A CONDICIONAL |

Os testes usam `QA-TENANT-A-ONLY` e `QA-TENANT-B-ONLY`, os mesmos marcadores
conceituais do corpus. A prova SQL executa as migrations completas em banco
descartável e as policies reais; os claims são sintéticos injetados como o
PostgREST faria, portanto não provam emissão ou assinatura JWT pelo GoTrue.

Ainda faltam:

- login real de A/B pelo GoTrue; os JWTs desta prova foram cunhados pelo harness
  local e não comprovam emissão, refresh ou revogação pelo serviço Auth;
- entrega das credenciais aos dois processos de navegador pelo fluxo real do
  GoTrue; os dois processos Chromium/WASM e os dois owners segregados já foram
  exercitados, mas os tokens continuam cunhados pelo harness;
- isolamento completo das demais superfícies da aplicação no mesmo ensaio.

Essas lacunas impedem promover C12 a PASS end-to-end ou encerrar G7.

O relatório integrado mais recente passou **40/40 checks**, com ambos os
browsers, processos, banco e login descartável encerrados. SHA-256:
`167bb5080ea1e71304a478873890b2565c0ccdc01f1954e4b7ed08c519a19ea0`.
