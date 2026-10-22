# Gov Conect API (`apps/api`)

FastAPI que vai substituir, por partes, o acesso do Streamlit ao domínio
(ADR-001 e ADR-006 em `docs/migracao-saas-2026-10-22/DECISOES_ADR.md`).
Hoje (P01) ela **não autoriza ninguém**: falta o verificador de JWT, que
entra no P02. Por isso `/health/ready` responde 503 — e deve.

```bash
cd apps/api
pip install -r requirements-dev.txt
python -m pytest -q
APP_ENV=development uvicorn govconect_api.asgi:app --port 8000
```

| Rota | Hoje |
|---|---|
| `GET /health/live` | 200, sem dependência externa |
| `GET /health/ready` | 503 até existir verificador de token |
| `GET /api/v1/me` | 401 sem bearer; 503 com bearer (sem verificador) |

Variáveis (só ambiente, nunca `secrets.toml`):

| Variável | Regra |
|---|---|
| `APP_ENV` | `development` (padrão), `test`, `staging`, `production` |
| `SUPABASE_URL` | obrigatória e `https` em staging/produção |
| `GOVCONECT_CORS_ORIGINS` | vazia = sem CORS; lista de `https://host`; `*` recusado sempre |
| `GOVDOCS_MODO_ABERTO` | sem efeito na API; ligada em staging/produção, a API não sobe |

Contrato: `openapi.v1.json`. Mudou o código, regere com
`python -m govconect_api.contrato > openapi.v1.json` — a prova
`test_contrato_openapi.py` reprova a divergência.
