# Testes, métricas, operação e gates de PR
## Matriz mínima por camada
- Unit Python: domínio `src/precos`, Decimal, fontes, Estatística, relatório, documentos; preservação de fixture real já anonimizada de 210 itens e valor global de referência do projeto.
- Contract: Pydantic/OpenAPI; erros e compatibilidade TypeScript; verificações automáticas de serialização decimais.
- Integration: FastAPI TestClient/HTTPX com banco de homologação separado; RLS com tokens distintos; Redis/worker; timeout e idempotência.
- E2E Playwright: login válido/inválido, logout, deep links, tenant A/B, criar/salvar/retomar processo, pesquisar/cesta/emitir relatório, editar/aprovar/exportar; mobile.
- Segurança: segredo em bundle/log, CORS/CSRF, XSS, SSRF, SQLi, uploads, RBAC, rate limit, dependency scan e ToB.
- Performance: medir baseline e pós-change: fluxo de retirada da cesta com 100–210 itens, latência p50/p95/p99 por rota, custo das queries e LCP/INP/CLS.

## Valores-alvo iniciais (HIPÓTESES, calibrar com carga real)
- Rotas leves GET p95 < 500 ms no staging sem tráfego externo e com dataset padronizado; p99 < 1 s; sem fixar compromisso contratual antes do benchmark.
- Interação retirar item da cesta: percepção imediata (otimista UI), confirmação na API e recálculo correto; sem bloquear toda a página.
- Jobs longos respondem `202` em < 1 s, progresso exibido; timeout por fonte e retry limitados; nenhuma chamada externa duplica efeitos.
- Disponibilidade meta inicial a discutir: 99,5% mensal para serviço novo; somente após monitoramento real definir SLO formal e error budget.

## Observabilidade
- Logs estruturados de API/worker/proxy com trace_id/request_id/tenant_id (pseudônimo), status, elapsed_ms, source_name, job_id, sem dados de documentos.
- Métricas RED: rate/erro/duração; negócios: jobs iniciados/concluídos, fontes de preço com falha, relatório gerado, rejeições auth, orçamentos IA.
- Alertas: API fora, 5xx sustentados, fila crescendo, erro no worker, auth 401/403 anômalos, backup falho, consumo de tokens acima do limite.
- SLI = métrica observada; SLO = objetivo; error budget = margem de falha tolerada. Criar painel e runbook de incidentes antes de cutover.
- Cada incidente registra impacto, janela temporal, causa, mitigação e ação preventiva sem culpa (postmortem).

## Critério de cada PR
- Escopo vertical pequeno e isolado + o que foi preservado no legado.
- Testes relevantes green, incluindo CI existente; `lint`, `tsc --noEmit`, testes FastAPI, pytest, E2E/fotos quando UI.
- Sem segredos, migrations destrutivas, novo endpoint sem auth, dependências sem lock, warnings críticos sem justificativa.
- Checklist de revisão de segurança e ADR atualizado quando muda contrato.
- Nada de passar teste simulando que endpoint retorna sucesso se lógica real não foi conectada.
