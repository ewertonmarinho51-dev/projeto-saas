# Plano por fases, dependências e gates
Objetivo: entregar **vertical slices** testáveis e úteis, com pequenos PRs, sem freeze no editor do outro agente.

| Ordem | Trabalho | Entregável visível | Gate mínimo |
|---|---|---|---|
| F0 | Inventário, baseline e isolamento | relatórios, branch/worktree, mapa Streamlit→serviços | testes atuais executados; nenhum arquivo WordCraft alterado |
| F1 | Extrair núcleo + API mínima | FastAPI `/health/live`, `/health/ready`, `/api/v1/me`, `/api/v1/processos` | sem import `streamlit` na API; auth e tenancy em todas as rotas privadas |
| F2 | Login real + app shell Next.js | `/`, `/entrar`, `/app`, proteção de rotas, sidebar e navegação | RLS cross-tenant e auth negativa (sem token/expired/forjado) verde |
| F3 | Pesquisa de preços end-to-end | listar → pesquisar → selecionar cesta → emitir relatório | Decimal, provenance, idempotência e progresso testados |
| F4 | Documentos e GovBot (via adapter) | criar/abrir/editar/aprovar/exportar | contrato do outro agente integrado; no regressions WordCraft |
| F5 | Jobs, observabilidade, CI, release | filas Redis/Celery; logs, métricas, traces; Docker Compose | retries limitados, DLQ, health, deploy staging e rollback |
| F6 | Hardening final, UAT e cutover | auditoria ToB+OWASP, testes browser, staging isolado | zero vulnerabilidade crítica/alta explorável e plano de resposta |

**Não esperar F5 para segurança:** controles essenciais em F1 e F2; endurecimento contínuo.

## Dependência de trabalho paralelo
F4 só integra quando o outro agente disponibilizar contratos/tests estáveis. F0–F3 podem ocorrer sem tocar `src/documentos_editor.py`, `src/wordcraft_*.py`, `integrations/wordcraft`, migrações de editor ou workflows WordCraft.

## Critério de sistema funcional (mínimo de produção)
1. Usuário legítimo entra, sai e acessa somente seu tenant; usuário não autorizado não acessa API, relatórios ou arquivos por IDs trocados.
2. Processo pode ser criado, salvo, reaberto, alterado e recuperado após refresh e nova sessão.
3. Pesquisa de preços executa com fonte real permitida, preserva referências rastreáveis, cesta, cálculos em Decimal e relatório sem travar UI.
4. Documentos oficiais aproveitam pipeline testado, revisão/aprovação humana, export DOCX/PDF e prevenção de perda de edição.
5. Jobs mostram progresso e falhas; retry não duplica efeitos; a API não bloqueia por dezenas de segundos.
6. Logs sem dados sensíveis, alarmes em falhas, backup/restauração de dados e relatório de rollback em staging.
7. CI verde com lint/types/testes unitários, API, integração RLS, E2E Playwright e vulnerabilidades bloqueantes resolvidas.

**GO/NO-GO:** nenhum cutover sem comprovante de RLS real, staging isolado, restauração de backup, rollback testado, headers/TLS, budget/cotas de IA, evidências e autorização explícita do operador.
