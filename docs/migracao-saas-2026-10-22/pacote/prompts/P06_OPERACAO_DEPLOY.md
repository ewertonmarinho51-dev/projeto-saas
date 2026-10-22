# P06 — Gate F5: jobs, CI/CD, Docker e operação
Evolua `implantacao/` existente para web Next, api FastAPI, worker Celery, Redis e Caddy, com portas internas privadas e TLS, sem mexer em produção. Respeite WordCraft read-only. Faça health checks liveness/readiness, stop_grace_period, limites de memória, multi-stage builds, usuário não-root e lockfiles. Redis/worker só o necessário; job e idempotência persistidos no Postgres.

Adicione workflows de CI (pytest atual, testes API/RLS/staging, lint/typecheck Next, Playwright, SAST/dependências/secrets/build) sem quebrar os existentes. Staging deve usar Supabase/Storage/test identities **isolados**, nunca a mesma base da produção. Configure logs estruturados, métricas RED/SLI, alertas e custos IA; crie runbooks restore/rollback e plano de expansão VPS. Documente benchmark CPU/memória no host-alvo; se não couber Next+API+worker+Redis em 1vCPU/4GB, proponha upgrade ou serviço gerenciado, não esconda limitação.

Produza artefatos de staging, smoke scripts, release tag e relatório de rollback testado. Sem deploy produção ou mudanças em DNS/credenciais sem aceite humano explícito.
