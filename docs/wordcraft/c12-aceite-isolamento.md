# C12 — aceite local de isolamento documental e de sessão

Data: 18/10/2026  
Escopo: PostgreSQL/RLS real local e fronteira de sessão Streamlit  
Estado: **PASS LOCAL PARCIAL; GoTrue/PostgREST, Storage e navegador ainda pendentes**

O manifesto C12 permanece `NOT_TESTED`, pois seus DOCX com marcadores
disjuntos são entradas offline. A execução funcional está dividida em duas
provas correlacionadas pelos mesmos marcadores.

| ID | Camada | Ações e observado | Estado |
|---|---|---|---|
| C12-SQL-01 | PostgreSQL/RLS | cria processos e revisões para tenants A/B; cada sessão `authenticated` lê somente seu marcador; escrita cruzada falha com `InsufficientPrivilege`; `anon` não possui `SELECT` na tabela privada; consulta administrativa final confirma uma revisão original por tenant | PASS LOCAL |
| C12-SESSION-01 | sessão/cache/bridge | coloca owner, documento, bridge, preparação, projeção e evento do componente do tenant A; login no tenant B revoga todo o namespace antes de armazenar a nova identidade; nenhum marcador A permanece | PASS LOCAL |

Os testes usam `QA-TENANT-A-ONLY` e `QA-TENANT-B-ONLY`, os mesmos marcadores
conceituais do corpus. A prova SQL executa as migrations completas em banco
descartável e as policies reais; os claims são sintéticos injetados como o
PostgREST faria, portanto não provam emissão ou assinatura JWT pelo GoTrue.

Ainda faltam:

- login real de A/B pelo GoTrue e acesso através do PostgREST;
- objetos de Storage privado e URLs temporárias, se essa camada for adotada;
- execução no navegador que confirme isolamento do iframe e dos caches do
  processo real, além da recusa já coberta pelo protocolo fechado;
- isolamento completo das demais superfícies da aplicação no mesmo ensaio.

Essas lacunas impedem promover C12 a PASS end-to-end ou encerrar G7.
