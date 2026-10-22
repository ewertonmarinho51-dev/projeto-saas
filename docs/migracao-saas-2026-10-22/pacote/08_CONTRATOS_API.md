# Contratos-alvo HTTP (design proposal; validar modelo real antes de codificar)
Base: `/api/v1`, OpenAPI gerado por FastAPI. Todos os endpoints privados exigem sessão autenticada e verificação de acesso por tenant no servidor + RLS.

## Endpoints iniciais
| Método | Rota | Finalidade |
|---|---|---|
| GET | `/health/live` | processo vivo, sem dependência externa |
| GET | `/health/ready` | dependências necessárias disponíveis; sem segredo exposto |
| GET | `/api/v1/me` | identidade segura + role/tenant derivadas da sessão |
| GET | `/api/v1/processos?limit=20&cursor=...` | paginação e filtragem server-side por tenant |
| POST | `/api/v1/processos` | cria processo, idempotency key |
| GET | `/api/v1/processos/{id}` | detalhe; acesso owner/role/tenant |
| PATCH | `/api/v1/processos/{id}` | edição com `If-Match`/version otimista |
| POST | `/api/v1/precos/pesquisas` | inicia pesquisa assíncrona; HTTP 202 |
| GET | `/api/v1/precos/pesquisas/{id}` | estado da coleta e referências verificáveis |
| PATCH | `/api/v1/precos/pesquisas/{id}/cesta` | inclusão/retirada/triagem, recalcula em Decimal |
| POST | `/api/v1/precos/pesquisas/{id}/relatorios` | geração assíncrona do relatório |
| GET | `/api/v1/jobs/{id}` | estado autorizado da tarefa |
| GET | `/api/v1/jobs/{id}/events` | SSE (opcional depois de GET/poll) |
| POST | `/api/v1/documentos` | adaptador para pipeline documental existente |
| GET | `/api/v1/documentos/{id}` | recuperar snapshot/revisões |
| PATCH | `/api/v1/documentos/{id}` | alterações via contrato do editor, versionadas |
| POST | `/api/v1/documentos/{id}/aprovar` | validação humana, auditar quem e quando |
| POST | `/api/v1/documentos/{id}/exportacoes` | gerar DOCX/PDF via job e storage privado |
| GET | `/api/v1/artefatos/{id}/download` | checa permissão, gera URL assinada curta |

## Modelos: convenções
- IDs: UUID. `tenant_id`, `auth_user_id`, privilégios **sempre derivados no servidor**. Requests tentem incluir `tenant_id` devem rejeitar ou ignorar, e registrar tentativa.
- `quantidade`, `valor_unitario`, `valor_total`: `string` decimal canonizada no JSON; regras de arredondamento no domínio Python, nunca `float` do frontend.
- Datas: ISO 8601 UTC; moeda BRL, unidades explícitas; links de proveniência não podem apontar para host de rede local.
- Status de job: `queued`, `running`, `succeeded`, `failed`, `cancelled`; timestamps, progresso 0–100 quando mensurável; falhas com código seguro.
- Erro: `{ "code": "FORBIDDEN", "message": "Acesso negado", "request_id": "..." }`, status HTTP coerente.
- Headers: `X-Request-ID`; `Idempotency-Key` para operações de custo/efeito; `If-Match`/`ETag` nas atualizações concorrentes.
- Jobs e artefatos só são visíveis ao tenant e ao usuário autorizado; links assinados expiram e não entram em log.

## Contratos críticos de frontend
- O frontend não gera dados fictícios ou 'mocka' API em produção. Fixtures somente em testes e demo explicitamente local.
- Enquanto F4 WordCraft não estiver estável, pode haver 'Em preparação' funcional com gate off, sem alterar editor.
- Endpoints novos documentados e testados antes de ligar flags; codegen OpenAPI→TS opcional para reduzir drift.
