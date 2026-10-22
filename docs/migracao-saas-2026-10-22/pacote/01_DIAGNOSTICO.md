# Inventário inicial, dívida técnica e verificações obrigatórias
Consulta ao repositório principal em 22/10/2026; confirme HEAD e PRs abertos antes de cada fase.

| Área | Evidência no repo | Direção |
|---|---|---|
| UI Streamlit | `app.py`, `src/ui/*`, `.streamlit/` | transportar comportamento, **não copiar componentes UI** |
| Núcleo documental | `src/estado` (confirmar nomes), `src/prompts.py`, `src/export.py`, `src/govbot.py`, `src/rag.py`, `src/documentos_editor.py`, `src/wordcraft_*` | mapear, encapsular serviços puros e preservar regras |
| Pesquisa de preços | `src/precos/*` (PNCP, Compras.gov, cestas, decisões, estatística Decimal, evidências, relatórios) | reutilizar serviço de domínio, não reimplementar matching |
| Persistência | `src/db.py`, `src/precos/repositorio.py`, Supabase | desvincular Streamlit de camada de domínio |
| Identidade | `src/auth.py`, `src/ui/login.py`, migrações `0018` a `0020` e `0025` | validar vínculo Supabase Auth, bloqueios, RLS e RBAC por tenant |
| Deploy | `implantacao/Dockerfile`, `docker-compose.yml`, `Caddyfile`, `promover.sh` | evoluir para web + api + worker sem abrir portas internas |
| CI | `.github/workflows/ci.yml`, `auth-real.yml`, `wordcraft-*` | adicionar gates sem destruir existentes |
| Skills próprias | `.claude/skills/design-taste`, `design-minimalist`, `design-motion-principles`, `caveman` | reutilizar antes de instalar plugins |
| Mapa de código | Cartographer em `.mcp.json`, `.cartographer/` | existente; Graphify só se lacuna comprovada |
| Referências de segurança | `docs/AUDITORIA_PRE_OPERACIONAL.md`, `docs/runbook-vinculo-supabase-auth.md`, `docs/seguranca-achado-p0.md` | comparar alegações com testes reproduzíveis atuais |

**Bloqueadores prováveis que precisam ser provados, não pressupostos:**
- `src/auth.py` documenta modo aberto quando sem Supabase. Confirmar que nenhuma rota de produção pode funcionar em modo aberto, com flag ausente/falsa, ou com chave pública sem proteção.
- Os scripts de migração de Auth e o RLS existem; exigir evidência do estado **efetivamente aplicado** em cada ambiente. Tests locais não validam produção.
- Supabase service role/secret key: somente em backend, jamais bundle Next.js, `NEXT_PUBLIC_`, resposta HTTP ou logs.
- Streamlit cloud e VPS historicamente apontaram para o mesmo banco. Exigir staging com banco **isolado** antes de migrations e carga.
- WordCraft/editor em desenvolvimento concorrente, cujo esquema pode mudar. Tratar interfaces como contratos temporários e aceitar merge somente após rebase/reteste.
- Fazer inventário de endpoints/serviços, flags, tenants, arquivos, modelos, jobs e licenças; verificar dependências transitivas e entradas de usuários.
- Planilha com 210 itens e valores em Decimal: não transformar monetários em `float`/JS Number para cálculo autoritativo; serializar como string decimal e calcular no backend.

**Gate diagnóstico:** salvar `docs/migracao-saas-2026-10-22/INVENTARIO_REAL.md` com caminhos, símbolos, commits, diagrama do fluxo atual, testes atuais, riscos, flags e decisão GO/NO-GO.
