# Inventário real — Gate F0 (22/10/2026)

Levantado no código, não no README. Rótulos: **COMPROVADO** (executei e
vi), **NÃO TESTADO** (li, não executei), **BLOQUEADO** (depende de algo
que não tenho ou não posso tocar).

## 1. Estado do repositório

| Item | Valor | Como |
|---|---|---|
| `main` remoto | `7509780` (Merge #75, embeddings key guard) | `gh api .../commits/main` + fetch HTTPS — COMPROVADO |
| Base desta branch | `7509780` | `git checkout -b claude/migracao-nextjs-api-f0 origin/main` |
| Worktree recebido | estava em `4979265`, **63 commits atrás** do main | o `git fetch` por SSH falhou nesta máquina; buscado por HTTPS com o `gh` |
| PRs abertos | #76 `fix/openai-slot-provider-guard` (`src/llm.py`), #62 `claude/auditoria-fontes-fase2` (`src/precos/cesta.py`, `relatorio.py`, `ui/precos_ui.py`) | `gh pr list` — nenhum toca `apps/` nem esta branch |
| Cartographer | configurado em `.mcp.json`, **falhou ao conectar** nesta sessão (`CONNECTION_CLOSED`) | fallback `Grep`/`Glob`, como manda o `CLAUDE.md` |

## 2. WordCraft — já está no `main`

O pacote trata o editor como trabalho de outro agente "em andamento". No
`main` de hoje ele **já foi integrado** (PRs #65, #67–#73: canário por
tenant, runtime de produção, release pinado). Área intocada por esta
frente:

- `src/documentos_editor.py` (2.119 linhas), `src/wordcraft_*.py`,
  `src/ui/wordcraft_*.py`, `integrations/wordcraft/**`,
  `assets/wordcraft_editor/**`, `scripts/wordcraft_*`;
- migrações `20261015035015` … `20261018…` (10 arquivos, `documentos_editor*`
  e `flag_wordcraft_editor`);
- workflows `wordcraft-build.yml`, `wordcraft-fidelity.yml`,
  `wordcraft-release.yml` e `auth-real.yml` (este dispara só na branch do
  WordCraft e por `workflow_dispatch`).

**Conflito com esta frente: nenhum.** Este PR só cria `apps/`, `docs/migracao-saas-2026-10-22/`,
um `conftest.py` na raiz e um job novo no `ci.yml`. Pontos de atrito
FUTUROS: `src/auth.py` e `src/state.py` chamam `wordcraft_session` no
`entrar()`/`sair()` — a API não pode reaproveitar essas funções, e não
vai (ver ADR-006).

## 3. Divergências entre a especificação e o código

| Especificação diz | Código diz | Consequência |
|---|---|---|
| `src/estado` | `src/state.py` | nome corrigido no plano |
| chave publicável `SUPABASE_PUBLISHABLE_KEY` | `SUPABASE_KEY` (publicável); servidor em `SUPABASE_SECRET_KEY`, legada `SUPABASE_SERVICE_KEY` | a API lê os nomes que o deploy já tem; `NEXT_PUBLIC_*` só no web |
| — | interruptor `GOVDOCS_EXIGIR_SUPABASE_AUTH` fecha o login legado | a API **não tem** login legado; o interruptor não se aplica a ela |
| editor "em desenvolvimento concorrente" | integrado e em canário de produção | F4 deixa de esperar outro agente; continua sem tocar os arquivos |
| `apps/web`, `apps/api` | não existiam | criados aqui (`apps/api`) |
| staging com Supabase separado | **não há evidência** de projeto de staging; o `CLAUDE.md` cita só o projeto de produção | BLOQUEADO para teste contra staging; ver §8 |
| "README antigo" | `README.md` ainda descreve só o Streamlit | não usado como fonte |

## 4. Acoplamento ao Streamlit — medido

Cada módulo importado num processo limpo, conferindo se `streamlit`
entrou em `sys.modules` (script em scratch; resultado reproduzível com
`python -c "import sys, src.X; print('streamlit' in sys.modules)"`):

- **69 módulos puros**: inclusive 37 dos 39 de `src/precos` (estatística,
  cesta, matching, PNCP, Compras.gov, relatório, evidência…), `src/processos.py`
  (status/etapa/progresso do painel), `src/demanda/*`, `src/export.py`,
  `src/govbot.py`, `src/roteamento.py`, `src/ai_gateway.py`. COMPROVADO.
- **37 módulos puxam o Streamlit**, quase todos por um único caminho:
  `src/db.py` → `import streamlit as st` no topo. Os demais pontos diretos:
  `auth.py`, `state.py`, `llm.py`, `rag.py`, `ambiente.py`, `contexto.py`,
  `conhecimento.py`, `corretor.py`, `fatos.py`, `familias.py`,
  `qualidade.py`, `cache_geracao.py`, `instituicional_bridge.py` e
  imports tardios em `achados.py`, `consistencia.py`,
  `clausulas_deterministicas.py`. Em `src/precos`, só `cotacoes.py` e
  `repositorio.py` (via `db`).

O que `db.py` tira do Streamlit, e o que a API precisa no lugar:

| Uso | Onde | Substituto na API |
|---|---|---|
| `st.secrets` | `_segredo()` | variável de ambiente (`config.py`) |
| `st.session_state["tenant_id"]` | `tenant_atual()` | `Identidade` derivada do token verificado |
| `st.session_state[CHAVE_DA_SESSAO]` | `sessao_do_usuario()` | bearer da requisição |
| `@st.cache_resource` | `_cliente()`, `_sonda_bem_sucedida()` | cliente por requisição com o JWT do usuário |
| `@st.cache_data` | `_config_app_inteira()`, módulos do tenant | cache explícito por tenant (Redis, F5) |

## 5. Identidade e autorização hoje

- **Dois caminhos de login** (`src/auth.py`): Supabase Auth
  (`sign_in_with_password`, guarda access/refresh no `session_state`) e
  legado (tabela `usuarios`, PBKDF2-SHA256 200k). O legado opera com a
  credencial de servidor — **atravessa o RLS**. Fecha com
  `GOVDOCS_EXIGIR_SUPABASE_AUTH=1`. Estado desse interruptor em produção:
  NÃO VERIFICADO (não li o env da VPS, por regra).
- **Modo aberto**: exige ausência de banco **e** `GOVDOCS_MODO_ABERTO=1`,
  e nunca vale em manutenção (`auth.modo_aberto`). Correto para o
  Streamlit; a API não tem modo aberto e recusa subir com a variável em
  staging/produção (COMPROVADO em teste e em `uvicorn` real).
- **Claims**: papel, tenant e secretaria moram em `app_metadata`
  (gravável só pela Admin API). As políticas leem
  `request.jwt.claims -> app_metadata` via `papel_do_jwt()`,
  `tenant_do_jwt()`, `secretaria_do_jwt()` (0020, ETAPA B).
- **RLS de `processos`** (0020): leitura por `pode_ler_processo(tenant,
  secretaria)` — mesmo tenant **e** (admin **ou** mesma secretaria);
  inserção exige `auth_user_id = auth.uid()`; edição exige dono ou admin.
  Sem política de DELETE para `authenticated`.
- **Contenção no app**: `db.listar_processos`/`carregar_processo` filtram
  `tenant_id` à mão porque `_cliente()` é service role (achado P0 de
  24/09). A API não repete esse padrão: operação de usuário vai com o JWT
  do usuário, e o RLS é a camada que decide.
- **Prova existente de RLS**: ensaio SQL local (`tests/test_ensaio_sql_local.py`,
  `test_multi_prefeituras_rls.py`, `test_precos_fase3_rls.py`) aplica as
  migrações num Postgres efêmero e injeta claims; `auth-real.yml` sobe
  GoTrue v2.197.0 + PostgREST v12.2.12 descartáveis e exerce login real.
  É o caminho para o P02 provar RLS **sem tocar produção**.

## 6. Fluxo atual

```text
Navegador ──HTTPS──> Caddy (TLS, HSTS, sem CSP) ──> Streamlit app.py :8501 (só rede interna)
                                                      ├─ src/ui/* (21 telas)
                                                      ├─ src/state.py ── session_state (processo em edição)
                                                      ├─ src/auth.py ─── Supabase Auth | tabela usuarios (legado)
                                                      ├─ src/db.py ───── Supabase: service role (+ JWT do usuário onde exigido)
                                                      ├─ src/precos/* ── PNCP, Compras.gov, TCE-RS, BPS
                                                      ├─ src/llm.py / ai_gateway / roteamento ── OpenAI (Gemini fallback)
                                                      └─ WordCraft runtime (volume :ro)
```

Deploy (`implantacao/`): compose `app` + `caddy`; 8501 só `expose`;
segredos em `/etc/govdocs/env`; Caddy com env próprio; tag na VPS e
`promover.sh`. NÃO TESTADO nesta sessão (não acessei a VPS).

## 7. Testes — baseline

| Suíte | Resultado | Como |
|---|---|---|
| raiz (`tests/`), 4.464 provas coletadas | ver §7.1 | `python -m pytest -q tests` no `.venv311`, Windows |
| `apps/api` (nova) | **48 passed** | `cd apps/api && python -m pytest -q` |
| mutação na API | 8 mutantes, **8 mortos** (2 só depois de apertar as provas) | ver relatório do PR |
| `uvicorn` real | `/health/live` 200, `/health/ready` 503, `/api/v1/me` 401/503; produção + `GOVDOCS_MODO_ABERTO=1` não sobe | COMPROVADO |

### 7.1 Suíte da raiz

`1 failed, 3983 passed, 480 skipped in 330.59s` — Windows, Python
3.11.9, sem Postgres local e sem LibreOffice no PATH (daí os 480
skips: ensaio SQL e PDF real; no CI os dois são obrigatórios e não
pulam). A única falha é o item 4 de §8 (CRLF), preexistente e
alheia a esta frente. COMPROVADO.

## 8. Riscos e bloqueios

1. **Staging de aplicação não existe.** *Corrigido no P02:* existe o
   projeto Supabase `govdocs-ensaio-descartavel`, usado para ensaiar
   migrações (a 0029 passou por ele), com o mesmo `processos` de
   produção. Não é staging do app — não há deploy apontando para ele —,
   mas serve de nível 2 do ensaio de migração. A prova de RLS da API
   roda na pilha descartável local (job `api-rls`).
2. **Modo de assinatura do JWT em produção.** *Resolvido no P02:* o
   JWKS público de produção publica **uma chave EC P-256, ES256**
   (conferido em 22/10/2026, sem credencial). A API verifica pelo JWKS e
   recusa HS256 em produção; o job `api-rls` reproduz o mesmo modo.
3. **Revogação**: JWT vale até `exp`. A API precisa conferir
   `usuarios.ativo` por requisição (com o JWT do usuário, política
   `usuarios_le_a_si`) para "usuário revogado perde acesso em prazo
   definido".
4. `tests/test_wordcraft_notices.py` falha **só nesta máquina**:
   `core.autocrlf=true` converte o texto da licença para CRLF e a
   comparação byte a byte reprova. Preexistente, fora desta frente.
5. Flags em produção (`GOVDOCS_EXIGIR_SUPABASE_AUTH`,
   `GOVDOCS_EXIGIR_CREDENCIAL_SERVIDOR`, `price_research`): NÃO
   VERIFICADO; nada nesta frente as altera.

## 9. Decisão F0

**GO** para P01 (estrutura da API em pasta nova, sem retirar o Streamlit,
sem tocar WordCraft, banco ou produção) — executado neste PR.

**GO** para P02 (executado no PR seguinte): RLS real via pilha
descartável local, no modo de assinatura de produção (ES256).
