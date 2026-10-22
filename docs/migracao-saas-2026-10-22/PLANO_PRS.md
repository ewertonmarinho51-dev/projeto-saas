# Plano de PRs — fases, dependências, gates

Um PR por fase, branch `claude/migracao-nextjs-api-<fase>`, base `main`.
Merge sempre pelo operador, com CI verde. Nenhuma fase toca produção,
banco de produção, DNS, segredos, Supabase Auth ou flags publicadas.

| PR | Escopo | Depende de | Gate para fechar | Risco |
|---|---|---|---|---|
| **P01** (este) | inventário, ADRs, plano; `apps/api` com live/ready, guarda falha-fechada, envelope de erro, request_id, CORS allowlist, contrato OpenAPI; job `api` no CI | — | suíte da raiz inalterada; `apps/api` verde **sem Streamlit instalado**; toda rota v1 recusa sem credencial | baixo: pasta nova, nada importa dela |
| **P02** | verificador JWT (JWKS, `iss`/`aud`/`exp`, `app_metadata`), vínculo `usuarios.ativo`; `GET /me`; `GET/POST/GET{id}/PATCH{id} /processos` com JWT do usuário no PostgREST, cursor, `Idempotency-Key`, `If-Match`; rate limit inicial em memória (Redis no P04) | P01; decisão do operador sobre assinatura assimétrica (ADR-002) só para staging | RLS **real** com pilha descartável (Postgres + GoTrue + PostgREST, como `auth-real.yml`): tenant A×B, usuário×admin, revogado, token vencido/forjado/outra audiência → 401/403/404; 409 em edição concorrente; mesma Idempotency-Key não duplica | médio: autorização. Mitigado por provas negativas e pelo revisor `revisor-de-banco-e-seguranca` |
| **P03** | `apps/web` Next.js: tokens do logo, hero, `/entrar` (Supabase SSR/PKCE), `/app` protegido no servidor, shell e lista de processos real via BFF | P02 | Playwright 375/768/1440: login válido/ inválido, logout, deep link protegido, tenant B não vê A; nenhum segredo no bundle (varredura do `.next`) | médio: sessão em cookie, CSRF |
| **P04** | preços ponta a ponta reutilizando `src/precos/*` puros: criar pesquisa (202 + job), estado, cesta (retirada/inclusão em Decimal, string no JSON), relatório; Redis + Celery; SSRF allowlist; flag `PRICE_RESEARCH_ENABLED` desligada | P02, P03 | fixture de 210 itens com valor global idêntico ao do Streamlit; retry não duplica; fonte fora → erro controlado | alto: maior superfície externa |
| **P05** | documentos via adapter do WordCraft (contrato provisório de 11_CONCORRENCIA), aprovação humana auditada, exportação por job, Storage privado + link assinado | P04; contrato estável do editor | suíte e workflows WordCraft verdes sem alteração nos arquivos dele | alto: fronteira com outra frente |
| **P06** | compose `web/api/worker/redis/caddy`, Dockerfiles multi-stage não-root, health, logs JSON, métricas, alertas, backup/restauração ensaiados, rollback por SHA em staging | P02–P04 | staging isolado no ar; restauração e rollback comprovados | médio |
| **P07** | auditoria `insecure-defaults` (ToB, com autorização para instalar) + ASVS 5 por endpoint, testes de ataque de 05_SEGURANCA em staging, UAT, plano de cutover | P06 | zero crítica/alta explorável; autorização explícita do operador | — |

## P01 — o primeiro PR de código mínimo testável

Arquivos novos:

```text
apps/api/govconect_api/{__init__,asgi,camadas,config,contrato,erros,main,seguranca}.py
apps/api/tests/{conftest,test_config,test_contrato_openapi,test_falha_fechada,
                test_rotas_privadas,test_saude_e_camadas,test_sem_streamlit}.py
apps/api/{requirements.txt,requirements-dev.txt,pytest.ini,openapi.v1.json,README.md}
conftest.py                       # raiz ignora apps/ (dependências separadas)
.github/workflows/ci.yml          # + job `api`; job `testes` intocado
docs/migracao-saas-2026-10-22/    # inventário, ADRs, plano, pacote de especificação
```

Nada em `src/`, `supabase/`, `implantacao/`, WordCraft ou workflows
WordCraft.

## Próximo passo concreto (P02)

1. Verificador com PyJWT (`PyJWKClient`, cache curto respeitando a
   rotação) — `iss = <SUPABASE_URL>/auth/v1`, `aud = authenticated`,
   algoritmos permitidos `ES256`/`RS256` (nunca `none`, nunca HS
   misturado com chave pública).
2. Repositório de processos SEM Streamlit, em `apps/api` ou num módulo
   puro novo de `src/` (decidir no PR, com o revisor de banco), falando
   com o PostgREST pelo JWT do usuário.
3. Harness de teste que reaproveita `scripts/ensaio_auth_real.py`/
   `scripts/ensaio_local.py` para subir a pilha descartável e emitir
   JWTs reais de dois tenants.
