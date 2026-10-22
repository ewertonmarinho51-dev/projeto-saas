# Gov Conect API (`apps/api`)

FastAPI que vai substituir, por partes, o acesso do Streamlit ao domínio
(ADR-001 e ADR-006 em `docs/migracao-saas-2026-10-22/DECISOES_ADR.md`).
Autentica pelo JWT do Supabase Auth (ES256, JWKS do projeto) e fala com o
banco **só com o token do usuário** — quem decide o que cada um vê é o
RLS da 0020.

```bash
cd apps/api
pip install -r requirements-dev.txt
python -m pytest -q                 # unidade (PostgREST simulado)
# autorização real: job `api-rls` do CI (Postgres + GoTrue + PostgREST)

# servidor local: a raiz do repositório no caminho, por causa de src.processos
PYTHONPATH=../.. APP_ENV=development uvicorn govconect_api.asgi:app --port 8000
```

| Rota | Comportamento |
|---|---|
| `GET /health/live` | 200, sem dependência externa |
| `GET /health/ready` | 503 sem `SUPABASE_URL` + `SUPABASE_KEY` |
| `GET /api/v1/me` | identidade do token verificado + vínculo ativo em `usuarios` |
| `GET /api/v1/processos?limit&cursor` | lista do município (RLS), paginada por cursor |
| `POST /api/v1/processos` | exige `Idempotency-Key`; repetição devolve o mesmo processo |
| `GET /api/v1/processos/{id}` | 404 também para processo de outro município |
| `PATCH /api/v1/processos/{id}` | exige `If-Match` (ETag do GET); versão velha → 409 |

Erros: 401 sem/inválido token, 403 sem vínculo ou sem permissão de
edição, 404 fora do acesso, 409 conflito, 422 corpo com campo de
identidade (`tenant_id`, `papel`…), 428 sem `If-Match`, 429 limite.

Variáveis (só ambiente, nunca `secrets.toml`):

| Variável | Regra |
|---|---|
| `APP_ENV` | `development` (padrão), `test`, `staging`, `production` |
| `SUPABASE_URL` | obrigatória e `https` em staging/produção |
| `SUPABASE_KEY` | chave **publicável**; a de servidor é recusada |
| `SUPABASE_JWT_SECRET` | só para pilha local HS256; **recusada em produção** |
| `GOVCONECT_LIMITE_POR_MINUTO` | por usuário, padrão 120 |
| `GOVCONECT_CORS_ORIGINS` | vazia = sem CORS; lista de `https://host`; `*` recusado |
| `GOVDOCS_MODO_ABERTO` | sem efeito na API; ligada em staging/produção, a API não sobe |

Contrato: `openapi.v1.json`. Mudou o código, regere com
`PYTHONPATH=.:../.. python -m govconect_api.contrato > openapi.v1.json` — a
prova `test_contrato_openapi.py` reprova a divergência.

A coluna `processos.idempotency_key` vem da migração
`supabase/migrations/0030_api_idempotencia_processos.sql`.
