# P02 — Gate F1: FastAPI e fail-closed
Implemente vertical slice real da API FastAPI reutilizando domínio Python; endpoints live/readiness, `/api/v1/me`, listar/criar/consultar processo com tenant/role derivados do token verificado. Faça isolamento `src/` puro vs Streamlit; não copie lógica, não migre WordCraft nesta fase.

Auth via Supabase Auth (JWT assinado/claims validadas no servidor e vínculo institucional) + autorização por rota + RLS comprovado em testes com identidades tenant A e tenant B. Se banco não disponível/secret ausente/flag de auth off/token expirado: FAIL CLOSED. Nunca confiar em `tenant_id` do body. Implementar erros 401/403/404 sanitizados, `request_id`, limites iniciais e CORS restrito. Contratos OpenAPI e testes de casos negativos são obrigatórios, inclusive acessos cruzados e falha do Supabase.

Não conectar à produção nem aplicar migrations reais sem autorização; use staging isolado. Registrar endpoints e testes. Execute pytest + CI antigo. Só fechar PR com gate auth comprovado. Se não for possível testar RLS real, reporte BLOCKED e mantenha flags off.
