# Relatório GO/NO-GO: migração Gov Conect 2.0 (PRELIMINAR)

Data: 22/10/2026. Base: `main` depois do #85 (P06a) e do #86 (P06b).

## Decisão: **NO-GO**

O P07 manda NO-GO quando "falta acesso ao editor funcional", quando não
há "rollback/backup válido" e quando o staging não existe ou é o banco de
produção. As três condições valem hoje. Nada aqui autoriza corte, e nenhum
corte foi feito.

**Decisão do operador em 23/10/2026 (ADR-009):** por enquanto, mesmo
domínio e mesmo projeto Supabase; staging isolado volta quando o sistema
for implantado em outros lugares. Consequência neste relatório: o critério
"staging não pode ser o banco de produção" passa a **risco aceito pelo
operador** para a fase de **convivência** (Next nos caminhos próprios,
Streamlit em `/`, desligável por uma linha). O **corte** (o Next como
porta principal) continua NO-GO pelos outros bloqueios: editor e prova de
backup/rollback no host.

**Convivência LIGADA em 23/10/2026** (v1.10.12 + `sha-2ba32f995632`,
RUNBOOK_P06 §4a): Next em `/entrar`, `/app/*`, `/privacidade`; Streamlit
em `/`; API e `/health/*` não expostos (conferido de fora). Pesquisa de
preços LIGADA na interface nova no mesmo dia, por decisão do operador:
a regra original ("não ligar antes da auditoria aprovada") foi afastada por
ele, com o achado médio 2 (senha vazada) ainda pendente.

| Bloqueio | Estado | O que destrava |
|---|---|---|
| Editor (P05) | **BLOCKED**: runtime WordCraft `INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED`, canário de 21/10 reprovado | entrega da frente WordCraft com artefato aprovado |
| Staging isolado | inexistente | projeto Supabase e domínio próprios (operador) |
| Backup e restauração testados | não feitos | staging |
| Rollback de imagem testado | não feito | staging |
| Capacidade do host | medida em 23/10 (RUNBOOK_P06 §3): 1 vCPU, 3,9 GB; swap de 2 GB criado no mesmo dia. Memória com rede de segurança; CPU é o gargalo | VPS 2 vCPU / 8 GB antes do corte (plano mantido pelo operador); latência medida em staging |
| Pentest/exploração | não feito (só em staging autorizado) | staging |
| `insecure-defaults` (Trail of Bits) | não rodado: Codex CLI não disponível nesta sessão | operador com o CLI autorizado |

## O que está provado (com evidência)

| Requisito do P07 | Evidência |
|---|---|
| RLS tenant A × B, revogação e expiração de sessão | job `api-rls` (pilha real GoTrue ES256 + PostgREST): `test_rls_processos`, `test_rls_precos`, `test_rls_cesta`, `test_rls_coleta`, `test_rls_relatorios` |
| Build do front sem segredo | job `imagens`: o build do web recusa chave de servidor; `NEXT_PUBLIC_*` só URL e chave publicável |
| Origem/CORS | CORS desligado por padrão; `*` recusado (`test_config`); a API não é publicada pelo Caddy |
| CSRF | ações do web são server actions (checagem de Origin do Next); a API exige Bearer, sem cookie |
| XSS/CSP | CSP com nonce por requisição (P03, `tests/seguranca.test.ts`) |
| SSRF/links | `links.resolver`: só https e host oficial (PNCP, Compras.gov) |
| Rate limit | API 120/min por usuário; login 5 por IP+e-mail a cada 15 min |
| Idempotência | `Idempotency-Key` com unicidade no banco (0030, 0031) e provas de repetição |
| Workers | Celery + Redis reais em `api-rls` e `web-e2e`; token fora do log; job para antes do `exp` |
| Preço em Decimal | nenhum `float`/`Number()` sobre dinheiro na API ou no web; JSON com string decimal |
| Relatório não fictício | emissão pelo motor institucional, registrada com o hash do byte entregue (`test_rls_relatorios`) |
| Ciência na emissão | exigida pelo worker na hora de gerar; mutação reprova |
| Fluxo no navegador | Playwright `web-e2e`: login, processos, preços, cesta, coleta, emissão e download (capturas no artefato `web-e2e-telas`) |
| Logs sem dado sensível | `test_observabilidade`: sem ids no caminho, query, token, texto de exceção ou id de município |

Fluxos que o P07 pede e ainda NÃO existem no web: documentos, aprovar e
exportar documento (dependem do P05).

## Achados da auditoria estática (por severidade)

Leitura do código desta frente; não substitui pentest.

**MÉDIO**

1. ~~**Redis sem autenticação.**~~ **CORRIGIDO no P06c (#89, 0a1cdf6).**
   Os avisos da fila levam o token do usuário (ADR-004), e a proteção era
   só a rede. Agora o Redis do compose exige `requirepass`, a API recusa
   subir em staging/produção com `REDIS_URL` sem senha, e o job `imagens`
   prova PING sem senha = NOAUTH. Resta: TLS se o Redis sair do host.
2. **Proteção contra senha vazada desligada no Supabase Auth** (advisor
   `auth_leaked_password_protection`). *Fix*: ligar no painel (decisão do
   operador; muda o comportamento do cadastro de senha).

**BAIXO**

3. **Limitadores em memória, por processo** (login no web, requisições na
   API): zeram ao reiniciar e não valem entre réplicas. Aceito pela
   ADR-007 (um processo); com réplica, Redis.
4. **O limite de login conta as entradas que deram certo.** Quem entra e
   sai 6 vezes em 15 min do mesmo IP fica bloqueado (achado no E2E do
   P04d). *Fix* sugerido: zerar a chave no sucesso; é decisão de
   segurança, não feita aqui.
5. **O dono do job reescreve `estado`/`resultado` do próprio job** pelo
   PostgREST (0031/0032 declaram). Efeito só na tela dele; download e
   registro da emissão não leem esses campos.

**INFORMATIVO**

6. `flags_do_app()` (0033) mostra a qualquer autenticado quais flags estão
   ligadas. Intencional: é o que a API precisa para valer a mesma política
   da tela.
7. Avisos anteriores do advisor: `vector` em `public`; funções SECURITY
   DEFINER executáveis por `authenticated` (`aprovacao_no_escopo`,
   `registrar_evento_governanca`, `revisar_pesquisa_preco`, e agora
   `flags_do_app`, todas com `search_path` fixo).

**Fora desta frente (WordCraft), registrados sem alteração**

8. As tabelas `documentos_editor*` estão em produção, mas o inventário de
   segurança as dá como não implantadas.
9. As mesmas três estão com RLS ligada e **não forçada**.

## Para virar GO

1. P05 desbloqueado e integrado (editor funcional, aprovação e exportação).
2. Staging isolado com as migrações, smoke completo e prova de
   restauração de backup e de rollback de imagem.
3. Host com folga para os serviços novos e o Streamlit de rollback
   (swap de 2 GB feito em 23/10; falta 2 vCPU / 8 GB antes do corte),
   com a latência medida em staging.
4. Achado 2 corrigido (o 1 já está, no #89) e o 4 decidido.
5. Plano de implantação final aprovado explicitamente pelo operador.
