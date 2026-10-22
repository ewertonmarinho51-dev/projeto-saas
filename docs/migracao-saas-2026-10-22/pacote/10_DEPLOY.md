# Implantação enxuta e segura — evolução do deploy atual
O repo já possui `implantacao/docker-compose.yml`, `Caddyfile`, Dockerfile e `promover.sh`. Evoluir **sem substituir cegamente**: preservar volumes TLS, deploy por tag SHA, rede privada e runtime WordCraft montado read-only.

## Infra fase inicial
- Containers: `web` Next.js (`3000` interno), `api` FastAPI (`8000` interno), `worker` Celery (sem porta), `redis` (sem porta), `caddy` (80/443 públicos). Supabase gerenciado externo.
- Caddy: `/api/v1/*` à API; `/health` relevante a checks; resto Next; cert TLS automático e headers. Não publicar `3000`, `8000`, `6379`, `8501` na rede pública; manter acesso SSH restrito.
- `readiness`: responde 503 se não puder atender tráfego; `liveness` local não depende de Supabase, para evitar reinícios em cascata quando provedor falhar.
- Dockerfiles multi-stage, dependências lockadas e usuários não-root, `read_only` onde viável, `tmpfs` para temporários, limites adequados ao host. Healthchecks e stop_grace_period sem destruir jobs.
- Redis maxmemory/persistência de fila cuidadosamente configurados; broker não é banco de auditoria: job de negócio persistido em Postgres.
- CI/CD: GitHub Actions lint/unit/contract/security/build; push staging isolado por SHA, smoke, aprovação manual, promote com rollback para imagem anterior. Não expor credenciais SSH na saída da action.
- Secrets: `/etc/govdocs/env` e serviço de secrets onde disponível; segredos por app (proxy não recebe tokens), acesso mínimo, rotação.

## Preparação e cutover
1. Auditar DNS/TLS e infraestrutura atual **sem mexer na produção**; levantar memória real/CPU/RAM/IO.
2. Subir staging em domínio e **Supabase separado**; rodar migrações lá.
3. Backups e restauração testada. Backup do Storage privado e configurações RLS junto aos dados.
4. Executar testes navegacionais, carga adequada e pentest/autorização isolada; confirmar custos.
5. Deploy blue-green **somente se recursos suportarem**; senão rolling simples/switch do Caddy com manutenção curta controlada. Nunca fazer migração destrutiva no mesmo instante do rollback.
6. Smoke após corte: login, tenant, pesquisa, geração/export, filas, logs/alertas; observar SLI e custo. Plano de retorno à versão anterior documentado.
7. Manter Streamlit como rollback temporário **apenas se** versão/schema compatíveis e rota não permitir login inseguro; desligá-lo ao concluir migração.

## Operação
Escopo inicial: on-call leve do operador com alertas de indisponibilidade e orçamento; incidentes e postmortems. Crescer host/serviços por pressão de p95, CPU/memória ou custo, não por antecipação.
