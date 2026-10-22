# Decisões de arquitetura — migração Streamlit → Gov Conect 2.0

Status: **Aceita** (vale e já tem código), **Proposta** (vale como
direção, revisão humana antes de implementar). Mudar uma decisão
aceita exige ADR nova, não edição silenciosa desta.

---

## ADR-001 — Monólito modular + BFF, convivendo com o Streamlit

**Status:** Aceita (P01 implementa a primeira parte).

**Contexto.** Domínio Python maduro e testado (4.464 provas), 69
módulos já puros, deploy de um host só, tráfego não medido.

**Decisão.**
- `apps/api/` — FastAPI, `/api/v1`, contrato em `openapi.v1.json`
  versionado e comparado por teste. Importa de `src/` **só módulos puros**
  (lista medida em INVENTARIO_REAL §4); nunca `db`, `auth`, `state`.
- `apps/web/` — Next.js App Router + TypeScript (P03). Não executa regra
  licitatória, não conhece chave de servidor. Fala com a API pelo
  servidor Next (BFF) com o access token da sessão; o navegador não
  chama a API direto no MVP. CORS fica desligado por padrão e, se ligado,
  só com origens explícitas (`GOVCONECT_CORS_ORIGINS`; `*` recusado).
- Sem Kubernetes, microserviços, Kafka, gRPC, Saga, Terraform (matriz
  111: itens C). Escala com evidência (p95, CPU, memória, custo).

**Consequências.** Duas suítes (raiz e `apps/api`) com dependências
separadas; job `api` no CI prova que a API sobe **sem o Streamlit
instalado**.

---

## ADR-002 — Sessão Supabase SSR/PKCE; autorização independente na API e no RLS

**Status:** Aceita no desenho; P01 entrega a guarda falha-fechada, P02
o verificador.

**Decisão.**
1. **Web**: `@supabase/ssr` com PKCE; autorização no servidor com
   `getClaims()`/`getUser()` conforme o risco, nunca `getSession().user`.
   Cookies `Secure`, `SameSite=Lax`, escopo mínimo. Rotas autenticadas
   com `Cache-Control: private, no-store`.
2. **API**: toda rota em `/api/v1` depende de `exigir_identidade`
   (no roteador; prova por comportamento em `test_rotas_privadas.py`).
   O verificador confere assinatura (JWKS do projeto), `iss`, `aud`
   (`authenticated`), `exp`, e lê `tenant_id`/`papel`/`secretaria_id`
   **só** de `app_metadata`. Em seguida confere o vínculo em `usuarios`
   (`ativo`) com o JWT do próprio usuário — revogação não espera o `exp`.
3. **Banco**: operação de usuário vai ao PostgREST **com o JWT do
   usuário**, não com a chave de servidor; o RLS da 0020/0025 é a
   terceira camada, e é exercido. Chave de servidor só em tarefa
   administrativa explícita, auditada.
4. Falha fechada sem exceção: sem cabeçalho → 401; sem verificador →
   503; verificador com erro inesperado → 500 com envelope; banco fora →
   503. Nenhum caminho vira 200.
5. A API não tem modo aberto. `GOVDOCS_MODO_ABERTO` em staging/produção
   impede a subida.

**Resolvido (P02, 22/10/2026).** Produção publica no JWKS uma chave EC
P-256 (ES256). A API verifica só ES256/RS256 pelo JWKS, com cache de
10 min (o da borda do Supabase), e recusa `SUPABASE_JWT_SECRET` em
produção — o segredo HS256 fica restrito à pilha local, se alguém
precisar. O algoritmo aceito é fixado pelo modo, nunca lido do token
(prova de `alg: none` e de confusão HS256-com-chave-pública em
`test_verificador.py`).

**Implementado no P02:** verificador (`verificador.py`), vínculo em
`usuarios` lido com o JWT do usuário a cada requisição (revogação
imediata), cliente PostgREST sem caminho para a chave de servidor
(`supabase_rest.py`), `/processos` com cursor, `Idempotency-Key`
(0030) e `If-Match`, limite por usuário em memória. Prova de
autorização real: job `api-rls`.

---

## ADR-003 — Storage privado e links assinados curtos

**Status:** Proposta (P04/P05).

Artefatos (DOCX/PDF/relatório) em bucket privado; download só por
`GET /api/v1/artefatos/{id}/download`, que confere tenant e gera URL
assinada de curta duração (≤ 5 min). URL assinada nunca vai a log.

---

## ADR-004 — Jobs: Redis + Celery para o que é longo; estado no Postgres

**Status:** Proposta (P04 introduz; P06 opera).

- Só tarefa longa vai para fila: coleta de preços, relatório, exportação,
  geração documental. CRUD responde síncrono.
- `POST` de tarefa devolve **202** + `job_id` + `status_url`; o estado de
  negócio (`queued/running/succeeded/failed/cancelled`, tentativas,
  progresso, tenant, dono) mora numa tabela do Postgres com RLS. O broker
  não é fonte de verdade.
- `Idempotency-Key` obrigatória nas criações com custo; unicidade
  `(tenant_id, idempotency_key)` no banco.
- Celery com `acks_late`, `time_limit`, retry só para erro transitório,
  backoff com jitter e teto; falha final registrada (DLQ lógica) com
  reprocesso administrativo.
- `--concurrency=1` como ponto de partida no VPS; medir antes de subir.
- **Implementado no P04c (22/10/2026)**: `api_jobs` (0031) com RLS do
  dono; `POST /precos/pesquisas/{id}/coleta` → 202; `GET /jobs/{id}`;
  worker Celery (`govconect_api.fila`) que roda o passo REENTRANTE do
  domínio (`cotacoes.pesquisar_em_lote`, um item por vez) — o ponto de
  retomada é o estado dos itens, não o broker.
- **Decisão consequente — o token do usuário viaja no aviso da fila.**
  As tabelas de preços (0021) só aceitam escrita do `authenticated`, e o
  worker não tem (nem deve ter) credencial de servidor. O token vai na
  mensagem com `expires` igual à validade dele, fora do log (`argsrepr`),
  num Redis só da rede interna. Quando ele está a 90 s de vencer, o job
  para com `SESSION_EXPIRED` e o usuário recomeça sem perder o coletado.
  Alternativa rejeitada: um papel de worker com credencial própria e
  política dedicada — mais superfície e mais uma credencial para girar,
  para um ganho que só aparece em coletas de mais de uma hora.
- SSE só depois de o polling funcionar.

---

## ADR-005 — Observabilidade e custo

**Status:** Proposta (base em P02, completa em P06).

Logs JSON com `request_id` (já em P01: `X-Request-ID` aceito do proxy
só se bem formado, senão gerado), `tenant_id` pseudonimizado, rota,
status, `elapsed_ms`; nunca corpo de documento, token ou texto de
exceção (P01 já registra só o tipo da exceção). Métricas RED e de job;
custo de IA por tenant reaproveitando `0028_controle_de_consumo_e_cache`.

---

## ADR-006 — Migração strangler, sem big bang

**Status:** Aceita.

- O Streamlit continua sendo o produto até o caminho crítico estar
  reproduzido e validado no novo (critérios de 03_ROADMAP_GATES).
- Ordem: API (P02) → web login/shell (P03) → preços ponta a ponta (P04)
  → documentos via adapter do WordCraft (P05) → operação (P06) →
  auditoria e cutover (P07).
- Extração de `src/db.py` é **aditiva**: módulos novos sem Streamlit ao
  lado do antigo; o Streamlit migra para eles depois, com a suíte dele
  verde. Nenhum PR desta frente reescreve `db.py`/`auth.py`/`state.py`
  de uma vez.
- **P04b, 22/10/2026:** o primeiro passo dessa extração foi o
  `src/streamlit_opcional.py`. O `db.py` usava o Streamlit em só oito
  pontos (`secrets`, `session_state`, `cache_resource`, `cache_data`);
  agora importa `st` desse módulo, que é o Streamlit de verdade no app
  (inclusive para os testes que trocam `db.st.session_state`) e um
  substituto puro com `GOVDOCS_SEM_STREAMLIT=1` (a API liga no
  `__init__`). Na API, o `session_state` é um `ContextVar` por requisição,
  aberto por `sessao_da_requisicao(token, tenant)` com a identidade JÁ
  verificada. Com isso a API chama a MESMA regra da cesta
  (`cotacoes.alterar_status_referencia`) em vez de reescrevê-la — regra
  duplicada diverge na primeira correção feita só de um lado.
- Feature flags novas nascem desligadas: `PRICE_RESEARCH_ENABLED`,
  `DOCUMENTS_NEXT_UI_ENABLED`. `price_research` não liga sem auth + RLS
  + rate limit + orçamento de IA aprovados.

---

## ADR-007 — Limites do VPS

**Status:** Proposta (P06).

Compose com `web`, `api`, `worker`, `redis`, `caddy`; só o Caddy publica
porta (80/443, 443/udp). Containers não-root, `read_only` onde der,
`tmpfs` para temporários, limites de memória. Medir RAM/p95 com os cinco
serviços no host real antes do cutover; se estourar, VPS maior antes de
replicar serviço. Streamlit sai do compose só depois do cutover.

---

## ADR-008 — Matriz dos 111: o que entra em cada PR

**Status:** Aceita como triagem; B/C não viram tarefa sem gatilho.

| PR | Itens A cobertos |
|---|---|
| P01 (este) | 4 (proxy: sem porta nova), 11 (sem I/O ainda), 56/57 (live/ready separados), 59 (request_id, sem texto de exceção), 66 (correlação), 67 (config só do ambiente, sem modo aberto), 76 (CORS allowlist, `*` recusado), 82/102 (`/api/v1` + OpenAPI versionado), 108 (dependências fixadas) |
| P02 | 1 (rate limit inicial), 14 (Idempotency-Key em processo), 25/26/27 (consulta paginada por cursor com índice tenant), 28 (pool), 36 (`If-Match`/version), 39 (corrida de edição), 68/70 (IAM, JWT), 78 (PostgREST parametrizado), 81 (migração aditiva se precisar) |
| P03 | 77 (CSRF/Origin), 79 (XSS/CSP com nonce), 51 (flag da nova UI), 91 (TTFB/LCP medidos) |
| P04 | 2/50 (cache de fonte pública), 10/12/13 (circuit breaker, retry, backoff nas fontes), 15/20 (fila e falha final), 44 (backpressure por tenant), 80 (SSRF nos links), 88 (quota) |
| P06 | 6/7/107 (CI, Docker multi-stage, cache), 55 (rollback por SHA), 58/61/62/64/93/94 (métricas e alertas), 71/73 (TLS), 83/84 (backup e restauração testada), 97 (DNS), 109 (runbook) |
| P07 | 72 (criptografia em repouso verificada), auditoria ToB + ASVS 5, 103 (release semântica) |

Itens B e C seguem a coluna da matriz: registrados com gatilho de
adoção, sem implementação.
