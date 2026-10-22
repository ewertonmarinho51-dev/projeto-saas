# Política de segurança e verificação — OWASP ASVS 5
**Objetivo:** segurança por desenho, não auditoria decorativa. Jamais afirmar 'à prova de invasão'. Trail of Bits `insecure-defaults` é uma etapa, não substitui revisão humana, testes de autorização e pentest.

## Gates obrigatórios
- **Fail closed:** rodar ambientes com `GOVDOCS_MODO_ABERTO` ausente, `GOVDOCS_EXIGIR_CREDENCIAL_SERVIDOR` desligado, `SUPABASE_URL` ausente, conexão indisponível, claims inválidas, usuário revogado e tenant ausente. **Nenhum endpoint privado autoriza**. Recusar qualquer variável tipo `REQUIRE_AUTH=false` ou fallback admin em produção.
- **Autorização 3 camadas:** verificação server-side sessão Supabase, middleware/dependency FastAPI, RLS no Postgres. `auth_user_id`/tenant/role/secretaria derivam de identidade validada e tabela institucional; ignorar payload do cliente que tente promovê-los. Nunca usar `user_metadata` como fonte de privilégio.
- **Sessão:** Next.js App Router + Supabase Auth PKCE SSR com `@supabase/ssr` nas versões da documentação atual. Verificar claims no servidor (`getClaims`/`getUser` segundo risco), revalidação, logout, refresh e revogação. Cookies `Secure`, `SameSite`, caminho/escopo mínimos; onde houver cookie acessível via JS, não alegar `HttpOnly`. Nunca confiar exclusivamente em `getSession().user` para autorização.
- **Cookies e cache:** rotas autenticadas `Cache-Control: private, no-store`; CDN não cacheia `Set-Cookie`, HTML ou respostas tenant. Evitar ISR/SSG com conteúdo privado.
- **RLS:** testar acessos `anon`, `authenticated` de tenants A/B, role usuário/admin, revogados, CRUD, joins, Storage e RPC. Testar com JWTs reais de homologação, não somente `service_role` (que contorna RLS).
- **Segredos:** `SUPABASE_SECRET_KEY`, service-role legado, API keys e assinatura JWT exclusivamente no servidor e secret store/env protegido; nunca `NEXT_PUBLIC_*`, logs, previews ou PR. Rotação planejada sem downtime.
- **Entrada:** Pydantic com tamanho/tipos limites; allowlist URL e bloqueio de IPs internos para evitar SSRF nas fontes/links de preços; importar XLSX/PDF/DOCX com tamanho, MIME, parser isolado, antimalware conforme risco; neutralizar fórmulas em XLSX exportado; segurança de HTML produzido por LLM.
- **Web:** CORS por origens explícitas, CSRF em operações via cookie, CSP com nonce quando compatível, XSS por sanitização, SQL parametrizado, limites por IP+usuário+tenant (Redis), TLS, HSTS após domínio confirmado; WAF e DDoS de borda opcionais baseados em exposição.
- **Jobs:** ownership por tenant em cada leitura/progresso/download; idempotency key, dedup, rate/cost limits, limites de concorrência, limite de tempo; sem execução de comandos arbitrários enviados pelo usuário.
- **Auditoria:** logs estruturados com request_id, job_id, tenant_id, ator e operação, sem corpo do documento/senha/token; trilhas administrativas protegidas contra manipulação e com política de retenção.
- **Supply chain:** lockfiles, dependabot/renovate controlado, análise SAST/dependências/secrets, build imutável, pin de container image por digest em produção quando aplicável, desabilitar componentes de diagnóstico externos desnecessários.

## Testes de ataque mínimos em staging
1. `GET /api/v1/processos` sem bearer; com token vencido; token de outra audiência; assinatura inválida → 401.
2. Usuario de tenant B solicita `GET/PATCH/DELETE /processos/{uuid_A}` e artefatos de A → 403/404 sem vazamento da existência; trilha registra negação.
3. Admin de tenant A não acessa tenant B; usuário não promove papel pelo body; usuário revogado perde acesso em prazo definido.
4. Alteração concorrente com mesmo `version` → uma aceita, outra 409; sem perda silenciosa.
5. Idempotency-Key repetida para criação/pesquisa/download pago → mesmo resultado/status, sem efeito duplo.
6. URL externa aponta a `127.0.0.1`, `169.254.169.254`, `localhost`, IPv6 local, hostname com redirecionamento interno → bloqueada; nenhuma requisição interna.
7. XSS no nome do processo/itens/resultado de IA não executa; upload ilegítimo rejeitado.
8. Falha de broker, Supabase, API de preços, LLM → timeouts e mensagens de erro sem segredo, fila controlada, fallback só homologado.
9. Varredura `insecure-defaults` com triagem de falso positivo + auditoria OWASP ASVS; demonstrar evidência por endpoint e arquivo.

## Trail of Bits — execução de complemento
1. Ler `https://github.com/trailofbits/skills/tree/main/plugins/insecure-defaults` e revisar scripts/hooks; instalar **somente com autorização**.
2. Codex: `codex plugin marketplace add trailofbits/skills`, depois `codex plugin add insecure-defaults@trailofbits`. Claude: `/plugin marketplace add trailofbits/skills` e `/plugin install insecure-defaults@trailofbits` se usar a versão Claude.
3. No contexto apropriado: `/insecure-defaults:audit src/` **e** revisar `apps/`, `implantacao/` e configs; classificar default alcançável, sink, severidade, exploração, correção, re-teste. Plugin não garante ausência de invasões.

**Gate definitivo:** nenhuma flag `price_research` ou afim ligada na produção antes de autenticação + RLS + rate limit + orçamento de IA aprovados.
