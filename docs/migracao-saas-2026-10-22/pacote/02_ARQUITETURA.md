# ADR-001: modular monolith + BFF, sem overengineering
**Decisão:** 1 aplicação web Next.js (App Router, TypeScript), 1 API Python FastAPI, 1 worker Celery (somente para tarefas de geração, importação, coleta e relatório longos), Redis para broker/cache/limites, Supabase (Postgres, Auth, RLS, Storage), Caddy como reverse proxy TLS. Deploy inicial Docker Compose em um único host, com serviços privados. Componentes reaproveitados do `src/` atual.

```text
Navegador ──HTTPS──> CDN/borda opcional ──> Caddy (TLS, roteamento, headers)
                                                   ├─ /        → Next.js (marketing/login/app)
                                                   └─ /api/v1  → FastAPI (JWT validado + tenancy)
                                                                       ├─ serviços de domínio Python existentes
                                                                       ├─ Supabase Postgres/Auth/Storage
                                                                       └─ Redis: fila/resultado/cache
                                                                                  └─ Celery worker (jobs)
SSE GET /api/v1/jobs/{id}/events ← FastAPI/Redis pubsub ou polling seguro (nunca a fila como fonte de verdade)
```

## Fronteiras
- `apps/web/`: páginas, forms, design system e SSR; não executa regra licitatória; não conhece segredos de IA, Supabase server-key ou banco.
- `apps/api/`: rotas HTTP, contratos Pydantic, auth, scopes, autorização, orquestração, rate limits, validação e audit trail. Idealmente usa BFF Next.js para chamadas autenticadas; se browser chama API diretamente, proteger CORS/origem e tokens adequadamente.
- `src/` legado: manter módulos puros; refatorar cuidadosamente acessos a `st.session_state`, `st.secrets` e `st.cache_*` por portas/adapters, evitando importar Streamlit em API/worker. Substituir `src/state.py` por persistência/versionamento sem duplicar regra.
- `workers/` ou `apps/worker/`: tarefas com identificador, tenant, owner, status, tentativas e progresso; idempotência e dedup no banco; sem confiar na fila como única fonte de verdade.
- `supabase/migrations/`: único histórico; migrações incrementais, compatíveis com versões adjacentes, revisão humana.

## Comunicação
- HTTP JSON para operações curtas; SSE **somente** progresso unidirecional (fallback polling 2–5 s e backoff). WebSocket só se edição simultânea ao vivo for comprovadamente necessária.
- Operações longas retornam HTTP 202 + `job_id` + `status_url` + `events_url`. Celery `acks_late`, time limits e retries cuidadosamente controlados; efeitos externos protegidos por idempotência.
- Versionamento `/api/v1`, OpenAPI versionado, envelope de erro com `code`, `message`, `request_id`; dados monetários como strings decimais.

## MVP de produção: o que NÃO adicionar já
Sem Kubernetes, Helm, Terraform complexo, service discovery, gRPC, Kafka, sharding, multirregião, Saga, eleição de líder ou read replicas. Justificativa: host inicialmente pequeno, uma implantação, componentes acoplados por domínio e tráfego não medido. **Escalar com evidência, não com checklists de buzzwords.**

## Limites de infraestrutura
Para VPS de entrada próximo a 1 vCPU/4 GB, validar perfil de memória e p95/p99 com Next + API + worker + Redis. Se estourar, usar serviço gerenciado ou VPS maior antes de replicar serviços. Supabase permanece gerenciado. `celery --concurrency=1` é ponto de partida para carga e não garantia de throughput.

## Decisões que o Claude precisa registrar
ADR-002 sessão Supabase SSR/PKCE e autorização independente em API/RLS; ADR-003 Storage e links assinados curtos; ADR-004 filas e idempotência; ADR-005 observabilidade e custos; ADR-006 estratégia de migração strangler e coexistência; ADR-007 limites VPS e plano de expansão.
