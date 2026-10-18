# C12 — aceite local de isolamento documental e de sessão

Data: 18/10/2026  
Escopo: PostgreSQL/RLS real local e fronteira de sessão Streamlit  
Estado: **PASS LOCAL PARCIAL; GoTrue/PostgREST autenticado e navegador ainda pendentes; Storage N/A no desenho atual**

O manifesto C12 permanece `NOT_TESTED`, pois seus DOCX com marcadores
disjuntos são entradas offline. A execução funcional está dividida em duas
provas correlacionadas pelos mesmos marcadores.

| ID | Camada | Ações e observado | Estado |
|---|---|---|---|
| C12-SQL-01 | PostgreSQL/RLS | cria processos e revisões para tenants A/B; cada sessão `authenticated` lê somente seu marcador; escrita cruzada falha com `InsufficientPrivilege`; `anon` não possui `SELECT` na tabela privada; consulta administrativa final confirma uma revisão original por tenant | PASS LOCAL |
| C12-SESSION-01 | sessão/cache/bridge | coloca owner, documento, bridge, preparação, projeção e evento do componente do tenant A; login no tenant B revoga todo o namespace antes de armazenar a nova identidade; nenhum marcador A permanece | PASS LOCAL |
| C12-HTTP-ANON-01 | PostgREST real local | 68 provas de catálogo/comportamento; `anon` não lê tabelas privadas, não escreve no objeto descartável e não executa RPCs documentais, inclusive emissão e aplicação de template | PASS LOCAL LIMITADO |
| C12-STORAGE-01 | arquitetura atual | zero buckets; bytes nativos persistem nas tabelas privadas e o ensaio registra Storage como `NAO_APLICAVEL` | N/A CONDICIONAL |

Os testes usam `QA-TENANT-A-ONLY` e `QA-TENANT-B-ONLY`, os mesmos marcadores
conceituais do corpus. A prova SQL executa as migrations completas em banco
descartável e as policies reais; os claims são sintéticos injetados como o
PostgREST faria, portanto não provam emissão ou assinatura JWT pelo GoTrue.

Ainda faltam:

- login real de A/B pelo GoTrue e acesso através do PostgREST;
- execução no navegador que confirme isolamento do iframe e dos caches do
  processo real, além da recusa já coberta pelo protocolo fechado;
- isolamento completo das demais superfícies da aplicação no mesmo ensaio.

Essas lacunas impedem promover C12 a PASS end-to-end ou encerrar G7.
