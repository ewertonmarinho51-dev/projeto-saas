# Matriz de aplicação — 111 conceitos de engenharia
**A** = implementar no MVP ou como gate de segurança; **B** = preparar quando houver demanda/medição; **C** = estudar como decisão arquitetural, **não** instalar agora. As prioridades são relativas ao SaaS Gov Conect em fase inicial em VPS de pequeno porte, não uma avaliação universal da tecnologia.

| Nº | Conceito | Prioridade | Implementação concreta/decisão |
|---:|---|:---:|---|
| 1 | Limite de Requisições | **A** | Redis por IP/usuário/tenant; quotas por LLM/fonte com 429 e Retry-After |
| 2 | Cache | **A** | Redis para consulta externa pública, chave com fonte/versão/parâmetros; nunca sessão compartilhada |
| 3 | Balanceamento de Carga | **B** | um backend inicial; preparar Caddy upstreams se houver 2+ réplicas |
| 4 | Proxies Reversos | **A** | reutilizar Caddy TLS e rede privada, sem expor portas web/api/redis |
| 5 | API Gateways | **B** | Caddy+FastAPI bastam; gateway dedicado só com múltiplos consumidores/serviços |
| 6 | CI/CD | **A** | GitHub Actions lint/test/build/security, staging e promoção manual |
| 7 | Docker | **A** | multi-stage, compose web/api/worker/redis/caddy, não-root |
| 8 | Kubernetes | **C** | não instalar; avaliar apenas com necessidade real de orquestração |
| 9 | Descoberta de Serviços | **B** | DNS de serviços do Compose; mesh/registry desnecessário agora |
| 10 | Circuit Breakers | **A** | limite de falhas/cooldown para PNCP, Compras.gov e LLM, sem mascarar erro |
| 11 | Timeouts | **A** | timeouts HTTP por fonte, operação e job; sem espera indefinida |
| 12 | Retries | **A** | somente transientes/seguros e ações idempotentes; cap por tipo de erro |
| 13 | Backoff Exponencial | **A** | backoff com jitter, respeito a Retry-After, limite máximo |
| 14 | Idempotência | **A** | Idempotency-Key/unique constraint em job, geração/registro e pesquisas de custo |
| 15 | Filas de Mensagens | **A** | Redis+Celery para jobs demorados e status persistido no Postgres |
| 16 | Pub/Sub | **B** | Redis Pub/Sub como notificação transitória SSE; não única fonte do estado |
| 17 | Arquitetura Orientada a Eventos | **B** | eventos internos versionados para progresso/auditoria, sem event bus global |
| 18 | Transações Distribuídas | **C** | evitar; manter transações ACID locais e side effects separados |
| 19 | Padrão Saga | **C** | só se surgirem múltiplos serviços com compensações complexas |
| 20 | Dead Letter Queues | **A** | falha final registrada e reprocessamento administrativo controlado |
| 21 | Cron Jobs | **B** | agendamentos limitados para limpeza de cache/relatórios/retensão, sem cron em replicas |
| 22 | WebSockets | **B** | somente se coedição em tempo real for requisito; SSE é padrão inicial |
| 23 | Long Polling | **C** | fallback polling convencional basta; não desenvolver long polling específico |
| 24 | Server-Sent Events | **B** | progresso unidirecional de jobs com auth e fallback GET/poll |
| 25 | Índices no Banco | **A** | auditar EXPLAIN/ANALYZE, índices tenant_id + filtros e FKs |
| 26 | Otimização de Queries | **A** | perfis de query, paginação cursor, projeções e limites |
| 27 | Queries N+1 | **A** | instrumentar e eliminar nas listagens, batch/joins controlados |
| 28 | Pool de Conexões | **A** | pool conforme Supabase/PgBouncer e limite do plano |
| 29 | Réplicas de Leitura | **C** | não provisionar até crescimento confirmado e acordo de consistência |
| 30 | Sharding | **C** | não iniciar; custos/RLS/transações aumentam complexidade |
| 31 | Particionamento | **C** | somente após EXPLAIN justificar para trilhas/eventos muito grandes |
| 32 | Replicação | **B** | delegar à camada Supabase/infra, validar backup/PITR |
| 33 | Eleição de Líder | **C** | não criar em single-host; coordenar cron via lock se necessário |
| 34 | Teorema CAP | **C** | princípio de decisão, não tarefa de desenvolvimento |
| 35 | Consistência Eventual | **B** | aplicar apenas a progresso/cache/job; dados legais e valores precisam consistência forte |
| 36 | Lock Otimista | **A** | version/ETag em processo/documento/cesta para prevenir sobrescrita |
| 37 | Lock Pessimista | **B** | transações de atualização específicas; medir contenção e deadlocks |
| 38 | Locks Distribuídos | **B** | somente jobs/cron concorrentes; Redis/DB lock com TTL e fencing adequado |
| 39 | Condições de Corrida | **A** | testes concorrentes de edição, repetição de pesquisa e emissão |
| 40 | Deadlocks | **B** | ordem de locks e timeouts; monitorar banco em staging |
| 41 | Vazamento de Memória | **A** | medir workers/parser PDF/DOCX, tempo de vida/reinício com observação |
| 42 | Coleta de Lixo | **C** | delegar runtime; otimizar após profiling |
| 43 | Thread Safety | **A** | isolamento de clients/estado da sessão; tasks puras e testes de concorrência |
| 44 | Backpressure | **A** | quotas fila/tenant, limiares e rejeição 429/503 controlada |
| 45 | Autoscaling | **C** | não implantar no VPS inicial; dimensionamento e limites primeiro |
| 46 | Escala Horizontal | **B** | arquitetura stateless permite réplica futura, sessões fora do processo |
| 47 | Escala Vertical | **B** | aumentar VPS antes de orquestração quando CPU/RAM saturarem |
| 48 | CDN | **B** | assets públicos cacheados, conteúdo privado sempre no-store |
| 49 | Cache na Borda | **B** | somente marketing/assets com cache-control correto |
| 50 | Invalidação de Cache | **A** | TTL/versionamento; nunca reutilizar conteúdo privado entre tenants |
| 51 | Feature Flags | **A** | isolar nova UI/doc editor/preços; default off e gate da autenticação |
| 52 | Deploy Blue-Green | **B** | se houver recursos e schema compatível; troca por Caddy |
| 53 | Releases Canário | **C** | não justificar com poucos usuários; feature flag/piloto governado |
| 54 | Rolling Deploys | **B** | compose recreate controlado, migrações compatíveis, job drain |
| 55 | Rollbacks | **A** | imagem SHA anterior; schema expand/contract e backups verificados |
| 56 | Health Checks | **A** | /health/live, /health/ready, worker heartbeat |
| 57 | Liveness e Readiness Probes | **A** | separar processo vivo vs aptidão de servir requisição |
| 58 | Monitoramento | **A** | uptime, erro, fila, CPU/RAM, fontes, custo IA |
| 59 | Logs | **A** | estruturados, request_id, sanitização LGPD e sem tokens/documentos |
| 60 | Rastreamento Distribuído | **B** | OpenTelemetry básico web→api→worker quando rastrear latência |
| 61 | Métricas | **A** | RED e jobs; histogramas latência p50/p95/p99 |
| 62 | Alertas | **A** | 5xx, auth anômala, fila travada, falha backup, orçamento IA |
| 63 | SLOs | **B** | definir após baseline; exemplo 99,5% inicial revisável |
| 64 | SLIs | **A** | latência, disponibilidade, sucesso de jobs, fontes verificáveis |
| 65 | Error Budgets | **B** | calcular após SLO acordado; orientar ritmo de releases |
| 66 | Observabilidade | **A** | logs+métricas+traces correlacionáveis |
| 67 | Gestão de Segredos | **A** | env seguro, sem NEXT_PUBLIC segredos, escopo por serviço, rotação |
| 68 | IAM | **A** | Supabase Auth, RBAC institucional e autorização tenant; menor privilégio |
| 69 | OAuth | **B** | Supabase Auth/PKCE; SSO de órgãos no futuro se exigido |
| 70 | Rotação de JWT | **A** | sessão/refresh/expiração e verificação de claims; plano rotação chave |
| 71 | TLS | **A** | Caddy HTTPS e HTTPS em provedores; redirecionamento e HSTS |
| 72 | Criptografia em Repouso | **A** | validar Supabase, Storage, backups e retenção |
| 73 | Criptografia em Trânsito | **A** | HTTPS/TLS entre cliente/provedor; portas internas privadas |
| 74 | WAF | **B** | avaliar WAF gerenciado na borda após medição de ataques |
| 75 | Proteção contra DDoS | **B** | borda/provedor + rate limit; não alegar imunidade |
| 76 | CORS | **A** | allowlist restrita de origens e métodos, sem wildcard credenciado |
| 77 | CSRF | **A** | proteção em cookies e mutações, Origin/CSRF token quando aplicável |
| 78 | SQL Injection | **A** | queries parametrizadas, sem interpolação e testes negativos |
| 79 | XSS | **A** | sanitização outputs/LLM, React escaping, CSP compatível |
| 80 | SSRF | **A** | egress allowlist, DNS/IP e redirects bloqueados nas fontes URLs |
| 81 | Migrations de Banco | **A** | aditivas, versionadas, rollback lógico e testes staging |
| 82 | Versionamento de Schema | **A** | contratos adaptados e expand/contract, OpenAPI v1 |
| 83 | Recuperação de Desastres | **A** | runbook restore, RPO/RTO definidos com operador |
| 84 | Backups | **A** | banco+Storage e restauração comprovada antes de cutover |
| 85 | Failover | **B** | gerenciado no Supabase; para VPS planejar manualmente fallback |
| 86 | Deploy Multirregião | **C** | não; latência/legalidade/custo desproporcionais no início |
| 87 | Engenharia do Caos | **B** | testes simples de queda Redis/fonte/API em staging, não caos em prod |
| 88 | Otimização de Custos | **A** | quotas IA/fonte, capacidade worker, cache e gastos por tenant |
| 89 | Cold Starts | **B** | containers residentes; medir somente em funções serverless futuras |
| 90 | Limites do Serverless | **C** | não usar serverless para PDF/doc/LLM longo sem limites comprovados |
| 91 | Latência | **A** | time to first byte, UI e APIs medidos |
| 92 | Throughput | **B** | medir jobs/min e solicitações/s; dimensionar por gargalo |
| 93 | Latência p99 | **A** | instrumentar percentis p95/p99 por rota/job relevante |
| 94 | Latência de Cauda | **A** | isolamento de jobs, timeouts por fonte, filas limitadas |
| 95 | Partições de Rede | **B** | simular indisponibilidade parcial e comportamento consistente |
| 96 | Clock Skew | **B** | UTC, expiração JWT e NTP, tolerâncias de relógio razoáveis |
| 97 | DNS | **A** | revisar DNS domínio, certificados, registros e TTL no cutover |
| 98 | TCP vs UDP (usuário: VDP) | **B** | Caddy 443/tcp e 443/udp para HTTP/3; entendimento operacional |
| 99 | HTTP/2 vs HTTP/3 | **B** | usar protocolos suportados por Caddy, sem customização prematura |
| 100 | gRPC | **C** | não; REST/SSE suficientes para web+API inicial |
| 101 | Webhooks | **B** | quando houver integrações externas, assinatura HMAC, timestamp e dedup |
| 102 | Versionamento de API | **A** | /api/v1 e contratos OpenAPI, política de deprecação |
| 103 | Versionamento Semântico | **A** | tags/releases e compatibilidade do frontend/backend |
| 104 | Infraestrutura como Código | **B** | compose versionado; avaliar IaC quando infra crescer |
| 105 | Terraform | **C** | não inicialmente; gerenciar 1 VPS+Supabase com runbooks auditados |
| 106 | Helm Charts | **C** | somente com Kubernetes futuro |
| 107 | Cache de Build | **A** | cache Docker/CI, builds reproduzíveis e lockfiles |
| 108 | Inferno de Dependências | **A** | pin por lockfile, scan SBOM e atualização controlada |
| 109 | Incidentes em Produção | **A** | runbook de contenção, comunicação, SLI e restauração |
| 110 | Plantão | **B** | definir responsável, escalonamento, canal de alerta e horário realista |
| 111 | Postmortems | **B** | relatório pós-incidente com correção e aprendizado, sem culpa |

## Aplicação prática
A falta de Kubernetes ou Kafka **não** impede produção. O que impede é segurança fraca, dados perdidos, autorização/RLS não comprovados, fluxo do produto inoperante, segredo vazado, impossibilidade de recuperar dados ou falta de monitoramento. Padrões B/C são registrados como decisões adiadas com gatilho de adoção; não devem virar tarefas automáticas no backlog inicial.
