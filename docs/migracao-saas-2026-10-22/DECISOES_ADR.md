# Decisões de arquitetura — migração Streamlit → Gov Conect 2.0

Status: **Aceita** (vale e já tem código), **Proposta** (vale como
direção, revisão humana antes de implementar). Mudar uma decisão
aceita exige ADR nova, não edição silenciosa desta.

---

## ADR-001 — Monólito modular + BFF, convivendo com o Streamlit

**Status:** Aceita (P01 implementa a primeira parte).

**Contexto.** Domínio Python maduro e testado (4.464 provas), 69
módulos já puros, deploy de um host só, tráfego não medido.

**Decisão.**
- `apps/api/` — FastAPI, `/api/v1`, contrato em `openapi.v1.json`
  versionado e comparado por teste. Importa de `src/` **só módulos puros**
  (lista medida em INVENTARIO_REAL §4); nunca `db`, `auth`, `state`.
- `apps/web/` — Next.js App Router + TypeScript (P03). Não executa regra
  licitatória, não conhece chave de servidor. Fala com a API pelo
  servidor Next (BFF) com o access token da sessão; o navegador não
  chama a API direto no MVP. CORS fica desligado por padrão e, se ligado,
  só com origens explícitas (`GOVCONECT_CORS_ORIGINS`; `*` recusado).
- Sem Kubernetes, microserviços, Kafka, gRPC, Saga, Terraform (matriz
  111: itens C). Escala com evidência (p95, CPU, memória, custo).

**Consequências.** Duas suítes (raiz e `apps/api`) com dependências
separadas; job `api` no CI prova que a API sobe **sem o Streamlit
instalado**.

---

## ADR-002 — Sessão Supabase SSR/PKCE; autorização independente na API e no RLS

**Status:** Aceita no desenho; P01 entrega a guarda falha-fechada, P02
o verificador.

**Decisão.**
1. **Web**: `@supabase/ssr` com PKCE; autorização no servidor com
   `getClaims()`/`getUser()` conforme o risco, nunca `getSession().user`.
   Cookies `Secure`, `SameSite=Lax`, escopo mínimo. Rotas autenticadas
   com `Cache-Control: private, no-store`.
2. **API**: toda rota em `/api/v1` depende de `exigir_identidade`
   (no roteador; prova por comportamento em `test_rotas_privadas.py`).
   O verificador confere assinatura (JWKS do projeto), `iss`, `aud`
   (`authenticated`), `exp`, e lê `tenant_id`/`papel`/`secretaria_id`
   **só** de `app_metadata`. Em seguida confere o vínculo em `usuarios`
   (`ativo`) com o JWT do próprio usuário — revogação não espera o `exp`.
3. **Banco**: operação de usuário vai ao PostgREST **com o JWT do
   usuário**, não com a chave de servidor; o RLS da 0020/0025 é a
   terceira camada, e é exercido. Chave de servidor só em tarefa
   administrativa explícita, auditada.
4. Falha fechada sem exceção: sem cabeçalho → 401; sem verificador →
   503; verificador com erro inesperado → 500 com envelope; banco fora →
   503. Nenhum caminho vira 200.
5. A API não tem modo aberto. `GOVDOCS_MODO_ABERTO` em staging/produção
   impede a subida.

**Resolvido (P02, 22/10/2026).** Produção publica no JWKS uma chave EC
P-256 (ES256). A API verifica só ES256/RS256 pelo JWKS, com cache de
10 min (o da borda do Supabase), e recusa `SUPABASE_JWT_SECRET` em
produção — o segredo HS256 fica restrito à pilha local, se alguém
precisar. O algoritmo aceito é fixado pelo modo, nunca lido do token
(prova de `alg: none` e de confusão HS256-com-chave-pública em
`test_verificador.py`).

**Implementado no P02:** verificador (`verificador.py`), vínculo em
`usuarios` lido com o JWT do usuário a cada requisição (revogação
imediata), cliente PostgREST sem caminho para a chave de servidor
(`supabase_rest.py`), `/processos` com cursor, `Idempotency-Key`
(0030) e `If-Match`, limite por usuário em memória. Prova de
autorização real: job `api-rls`.

---

## ADR-003 — Artefatos: efêmeros no Redis para relatório; Storage privado só quando houver o que guardar

**Status:** Revisada no P04d (22/10/2026). Relatório de preços: Aceita.
Documentos (P05): Proposta.

Proposta original: artefatos em bucket privado, download por URL assinada
de até 5 min.

**Revisão (P04d).** O relatório de preços é REPRODUTÍVEL (mesmo resultado,
mesmo identificador decisório) e a prova permanente da emissão já mora no
banco (`pesquisa_preco_emissoes`, 0029: hash do conteúdo decisório e hash
do arquivo entregue). O Streamlit não guarda o arquivo: gera e entrega.
Então:

- o worker gera o arquivo e o guarda no Redis da rede interna por 30 min,
  com nome, tipo e SHA-256 gravados PELO WORKER (`artefatos.py`);
- `GET /api/v1/jobs/{id}/artefato` confere o job pelo RLS da 0031 (dono +
  município) e devolve o arquivo; o web o repassa por rota própria. Não há
  URL assinada para vazar em log, nem política nova em `storage.objects`;
- tipo de arquivo de lista fechada (PDF, DOCX, XLSX, ZIP), `attachment`,
  `nosniff`; teto de 50 MB;
- `api_jobs.resultado` (0032) é só exibição — o dono pode reescrevê-lo, e
  o download não o lê.

Bucket privado com URL assinada continua sendo a direção para o que
PRECISA ficar guardado (documentos do processo, P05). Decidir lá, com
retenção.

---

## ADR-004 — Jobs: Redis + Celery para o que é longo; estado no Postgres

**Status:** Proposta (P04 introduz; P06 opera).

- Só tarefa longa vai para fila: coleta de preços, relatório, exportação,
  geração documental. CRUD responde síncrono.
- `POST` de tarefa devolve **202** + `job_id` + `status_url`; o estado de
  negócio (`queued/running/succeeded/failed/cancelled`, tentativas,
  progresso, tenant, dono) mora numa tabela do Postgres com RLS. O broker
  não é fonte de verdade.
- `Idempotency-Key` obrigatória nas criações com custo; unicidade
  `(tenant_id, idempotency_key)` no banco.
- Celery com `acks_late`, `time_limit`, retry só para erro transitório,
  backoff com jitter e teto; falha final registrada (DLQ lógica) com
  reprocesso administrativo.
- `--concurrency=1` como ponto de partida no VPS; medir antes de subir.
- **Implementado no P04c (22/10/2026)**: `api_jobs` (0031) com RLS do
  dono; `POST /precos/pesquisas/{id}/coleta` → 202; `GET /jobs/{id}`;
  worker Celery (`govconect_api.fila`) que roda o passo REENTRANTE do
  domínio (`cotacoes.pesquisar_em_lote`, um item por vez) — o ponto de
  retomada é o estado dos itens, não o broker.
- **Decisão consequente — o token do usuário viaja no aviso da fila.**
  As tabelas de preços (0021) só aceitam escrita do `authenticated`, e o
  worker não tem (nem deve ter) credencial de servidor. O token vai na
  mensagem com `expires` igual à validade dele, fora do log (`argsrepr`),
  num Redis só da rede interna. Quando ele está a 90 s de vencer, o job
  para com `SESSION_EXPIRED` e o usuário recomeça sem perder o coletado.
  Alternativa rejeitada: um papel de worker com credencial própria e
  política dedicada — mais superfície e mais uma credencial para girar,
  para um ganho que só aparece em coletas de mais de uma hora.
- SSE só depois de o polling funcionar.
- **P04d (22/10/2026)**: segundo tipo de job, `relatorio_precos` (0032),
  tarefa `govconect.emitir_relatorio`. O worker roda a MESMA regra de
  emissão do Streamlit (`src/precos/emissao.py`, extraída de
  `precos_ui.py`): conferência do teto, ciência exigida na hora de gerar
  (`ciencia.exigir`), renderização pelo motor institucional, registro da
  emissão (0029). PDF depende do LibreOffice no host do worker (P06); sem
  ele, o job falha com a mensagem do domínio e o DOCX continua saindo.

---

## ADR-005 — Observabilidade e custo

**Status:** Proposta (base em P02, completa em P06).

Logs JSON com `request_id` (já em P01: `X-Request-ID` aceito do proxy
só se bem formado, senão gerado), `tenant_id` pseudonimizado, rota,
status, `elapsed_ms`; nunca corpo de documento, token ou texto de
exceção (P01 já registra só o tipo da exceção). Métricas RED e de job;
custo de IA por tenant reaproveitando `0028_controle_de_consumo_e_cache`.

---

## ADR-006 — Migração strangler, sem big bang

**Status:** Aceita.

- O Streamlit continua sendo o produto até o caminho crítico estar
  reproduzido e validado no novo (critérios de 03_ROADMAP_GATES).
- Ordem: API (P02) → web login/shell (P03) → preços ponta a ponta (P04)
  → documentos via adapter do WordCraft (P05) → operação (P06) →
  auditoria e cutover (P07).
- Extração de `src/db.py` é **aditiva**: módulos novos sem Streamlit ao
  lado do antigo; o Streamlit migra para eles depois, com a suíte dele
  verde. Nenhum PR desta frente reescreve `db.py`/`auth.py`/`state.py`
  de uma vez.
- **P04b, 22/10/2026:** o primeiro passo dessa extração foi o
  `src/streamlit_opcional.py`. O `db.py` usava o Streamlit em só oito
  pontos (`secrets`, `session_state`, `cache_resource`, `cache_data`);
  agora importa `st` desse módulo, que é o Streamlit de verdade no app
  (inclusive para os testes que trocam `db.st.session_state`) e um
  substituto puro com `GOVDOCS_SEM_STREAMLIT=1` (a API liga no
  `__init__`). Na API, o `session_state` é um `ContextVar` por requisição,
  aberto por `sessao_da_requisicao(token, tenant)` com a identidade JÁ
  verificada. Com isso a API chama a MESMA regra da cesta
  (`cotacoes.alterar_status_referencia`) em vez de reescrevê-la — regra
  duplicada diverge na primeira correção feita só de um lado.
- **P04d, 22/10/2026 — achado e correção.** As flags do painel
  (`config_app`) eram lidas pela "credencial de servidor", que na API é
  só a chave publicável (`anon`, fechado pela 0019): no processo da API
  TODA flag lia desligada. A coleta do P04c rodava pela API sem teto
  automático e sem triagem pré-cesta; a emissão pularia a ciência (RF-03).
  Correção: `flags_do_app()` (0033, SECURITY DEFINER, só `flag_*` com
  valor booleano, só `authenticated`) — a TABELA continua fechada; na API
  o `db._cliente()` passa a ser o cliente do USUÁRIO (o RLS decide), e
  falha de leitura de flag nunca vira "desligada" (vale a última leitura
  boa; sem nenhuma, erro). `contexto.py` deixou de importar o Streamlit
  direto.
- Feature flags novas nascem desligadas: `PRICE_RESEARCH_ENABLED`,
  `DOCUMENTS_NEXT_UI_ENABLED`. `price_research` não liga sem auth + RLS
  + rate limit + orçamento de IA aprovados.

---

## ADR-007 — Limites do VPS

**Status:** Proposta (P06).

Compose com `web`, `api`, `worker`, `redis`, `caddy`; só o Caddy publica
porta (80/443, 443/udp). Containers não-root, `read_only` onde der,
`tmpfs` para temporários, limites de memória. Medir RAM/p95 com os cinco
serviços no host real antes do cutover; se estourar, VPS maior antes de
replicar serviço. Streamlit sai do compose só depois do cutover.

---

## ADR-008 — Matriz dos 111: o que entra em cada PR

**Status:** Aceita como triagem; B/C não viram tarefa sem gatilho.

| PR | Itens A cobertos |
|---|---|
| P01 (este) | 4 (proxy: sem porta nova), 11 (sem I/O ainda), 56/57 (live/ready separados), 59 (request_id, sem texto de exceção), 66 (correlação), 67 (config só do ambiente, sem modo aberto), 76 (CORS allowlist, `*` recusado), 82/102 (`/api/v1` + OpenAPI versionado), 108 (dependências fixadas) |
| P02 | 1 (rate limit inicial), 14 (Idempotency-Key em processo), 25/26/27 (consulta paginada por cursor com índice tenant), 28 (pool), 36 (`If-Match`/version), 39 (corrida de edição), 68/70 (IAM, JWT), 78 (PostgREST parametrizado), 81 (migração aditiva se precisar) |
| P03 | 77 (CSRF/Origin), 79 (XSS/CSP com nonce), 51 (flag da nova UI), 91 (TTFB/LCP medidos) |
| P04 | 2/50 (cache de fonte pública), 10/12/13 (circuit breaker, retry, backoff nas fontes), 15/20 (fila e falha final), 44 (backpressure por tenant), 80 (SSRF nos links), 88 (quota) |
| P06 | 6/7/107 (CI, Docker multi-stage, cache), 55 (rollback por SHA), 58/61/62/64/93/94 (métricas e alertas), 71/73 (TLS), 83/84 (backup e restauração testada), 97 (DNS), 109 (runbook) |
| P07 | 72 (criptografia em repouso verificada), auditoria ToB + ASVS 5, 103 (release semântica) |

Itens B e C seguem a coluna da matriz: registrados com gatilho de
adoção, sem implementação.

---

## ADR-009 — Convivência no mesmo domínio e no mesmo projeto Supabase

**Status:** Aceita por decisão do operador em 23/10/2026 ("vamos fazer
tudo no mesmo domínio e no mesmo projeto atual do Supabase por enquanto;
quando o projeto estiver sendo implementado em outros lugares fazemos
estas questões").

**Contexto.** O pacote (P06/P07) pede staging com Supabase e domínio
isolados e declara NO-GO se "staging for banco de produção". Hoje há um
município, um projeto Supabase e um domínio.

**Decisão.**
- Não há staging separado por enquanto. O Gov Conect 2.0 sobe no MESMO
  host, no MESMO `govconect.com` e contra o MESMO projeto Supabase.
- O domínio é dividido por caminho (`implantacao/Caddyfile.convivencia`):
  `/entrar`, `/app/*` (menos `/app/static/*`, que é do Streamlit),
  `/auth/*`, `/privacidade`, `/_next/*` e os arquivos do Next vão para o
  `web`; todo o resto continua no Streamlit. É a ADR-006 (strangler)
  aplicada ao endereço: o `/` de sempre não muda.
- A API continua sem rota pública; o RLS é o mesmo dos dois apps, porque
  o banco é o mesmo.
- A convivência liga e desliga por uma linha
  (`GOVCONECT_CADDYFILE=Caddyfile.convivencia` em `implantacao/.env`).

**Consequências e riscos aceitos.**
- Teste no ar é teste com dado real. Smoke só com o tenant e as contas do
  canário; nunca com dados de município de verdade.
- Migração da API vai direto para produção (já era assim: 0030–0033 foram
  ensaiadas no descartável e medidas em produção). O ensaio no projeto
  descartável continua obrigatório.
- Um erro no `web` afeta só os caminhos dele; o Streamlit segue servindo.
- Revisitar quando houver um segundo município ou outro ambiente: aí
  staging isolado e domínio próprio voltam a ser pré-requisito.

## ADR-010 — Exceção estreita à ADR-002: Admin API do Auth para gestão de usuários (M7c)

**Status:** Aceita em 26/10/2026, por decisão do operador ("rota só de
admin na API que usa a credencial de servidor apenas para a Admin API do
Auth"). Revisada pelo `revisor-de-banco-e-seguranca`.

**Contexto.** A ADR-002 tira a chave de servidor da API: toda operação de
usuário vai ao PostgREST com o JWT dele, e o RLS decide. Gestão de usuário
é a exceção de natureza: papel, prefeitura e secretaria moram em
`app_metadata` do Supabase Auth (é DALI que a API e o RLS os leem, nunca de
`user_metadata` nem de `usuarios`), e `app_metadata` só a Admin API grava.
A aba "Usuários" do Streamlit edita a tabela legada `usuarios`
(login/senha), que a interface nova não usa para entrar.

**Decisão.**
1. **Uma chave, um uso.** `GOVCONECT_AUTH_ADMIN_KEY` (formato
   `sb_secret_…`; JWT legado `service_role` recusado na subida) é lida pela
   configuração da API e entregue SÓ ao cliente `admin_auth.AdminDoAuth`.
   Ela vai apenas para `{SUPABASE_URL}/auth/v1/admin/users…`; nunca para o
   PostgREST, o domínio (`configurar_supabase` continua recusando
   `sb_secret_`), o worker nem o log. Sem a chave, as rotas que precisam
   dela respondem 503 `ADMIN_AUTH_UNAVAILABLE` (falha fechada) e o resto
   funciona.
2. **O cliente só sabe quatro coisas:** ler UMA conta pelo id, criar conta
   já com escopo, atualizar o `app_metadata` e bloquear/desbloquear a
   entrada (`ban_duration`) — mais o desfazer da conta criada na MESMA
   requisição, se o vínculo em `usuarios` falhar (por qualquer exceção).
   Não lista contas, não apaga conta alheia, não troca e-mail nem senha,
   não gera link.
3. **Escopo vem do chamador, nunca do corpo.** `tenant_id` é o do JWT do
   admin; papel só `usuario`/`admin`; secretaria só do mesmo tenant
   (conferida com o JWT do admin). Antes de alterar `app_metadata`, a API
   lê a conta pela Admin API e exige `app_metadata.tenant_id` igual ao do
   chamador — a Admin API atravessa o RLS, então essa conferência é a
   fronteira. Chaves que a API não gere (ex.: `papel_governanca`) são
   preservadas como estavam.
4. **Desativar = `usuarios.ativo` + bloqueio no Auth.** O `ativo` (pelo
   JWT do admin, política `usuarios_admin_edita` da 0020) corta a API na
   requisição seguinte — o verificador da ADR-002 o confere sempre. Mas
   nenhuma política do banco olha `ativo`: sem o bloqueio, o desativado
   renovaria o token e falaria com o PostgREST direto. O bloqueio impede
   entrar e renovar; o token JÁ emitido vale até vencer (≤ 1 h). Sem a
   chave, desativar ainda corta a API, e a tela avisa que o bloqueio não
   acontece.
5. **"Convidar" = criar a conta confirmada, com escopo no mesmo ato.** O
   convite por e-mail do Supabase devolve o token no fragmento da URL, que
   a rota de servidor `/auth/confirmar` não lê; a conta nasce sem senha e a
   pessoa a define em "Esqueci minha senha" (fluxo PKCE que já funciona).
   Sem janela de conta sem escopo (o script `criar_contas_auth.py` tinha
   uma, entre o convite e o `app_metadata`).
6. **Ninguém mexe em si mesmo, e o último admin não sai:** o admin não
   troca o próprio papel nem se desativa, e ninguém rebaixa nem desativa o
   último administrador ativo do município.
7. **Quem chama é conferido ao vivo.** O papel do JWT pode ter até 1 h:
   antes de convidar ou de mexer em papel e acesso, a API lê a conta do
   CHAMADOR na Admin API e exige `papel = admin`, o mesmo tenant e conta
   não bloqueada. Um admin recém-rebaixado não usa a janela do token para
   rebaixar quem o rebaixou.

**Consequências e riscos aceitos.**
- A chave dá poder total sobre o Auth do projeto. Mitigação: um módulo,
  três chamadas, conferência de tenant antes de toda escrita, guarda de
  admin + papel no JWT antes de tudo, log de cada ato (ids, nunca e-mail).
- Ela fica em `/etc/govdocs/api.env`, que o worker também carrega (mesmo
  `env_file` no compose). O worker a APAGA do próprio ambiente ao subir
  (`fila.sem_credencial_de_servidor`, antes de o pool nascer), para que o
  LibreOffice e outros filhos não a herdem. Separar o arquivo só para a
  API continua sendo o endurecimento certo, quando o compose for revisto.
- Papel e secretaria novos valem no PRÓXIMO token da pessoa (até 1 h, a
  renovação do Supabase). Desativar não espera: corta na hora.
- A linha em `usuarios` de uma conta criada aqui leva `senha_hash`
  inutilizável (`!sem-senha-legada`): o login legado do Streamlit recusa,
  e a pessoa entra pelo e-mail nos dois apps.

**Revisão de segurança (26/10/2026, `revisor-de-banco-e-seguranca`).**
Três bloqueadores, corrigidos antes do merge, cada um com prova que morde
(mutante morto): desativar não cortava o PostgREST direto (→ bloqueio no
Auth); dois admins podiam se rebaixar mutuamente na janela do token, e o
município ficar sem admin (→ conferência ao vivo + último admin); conta
órfã com escopo quando o PostgREST caía no vínculo (→ desfazer em qualquer
exceção). Também: "sem secretaria" envia `null` (o GoTrue mescla
`app_metadata`), e 422 do Auth só vira "já existe" com o código certo.
Risco aceito: o 409 do convite revela que um e-mail já tem conta no
projeto (sonda limitada a 120/min por admin).

## ADR-011 — Exceção estreita à ADR-002: commit documental nativo do WordCraft (Issue #137)

**Status:** **PROPOSTA — aguarda decisão do operador.** Nada é ativado sem
ela: o código fica no `main`, mas sem `GOVCONECT_DOCUMENTOS_ESCRITA_KEY` no
`api.env` o editor da interface nova só lê e exporta, e salvar, importar,
restaurar e aprovar respondem 503 `DOCUMENT_WRITE_UNAVAILABLE` sem tocar o
banco.

**Contexto.** O WordCraft Workspace leva o editor nativo para o Next.js. O
dono documental é `src.documentos_editor.DocumentoService` (único; proibido
duplicar), e ele grava pelas RPCs `documento_editor_checkpoint`,
`documento_editor_aprovar` e `documento_editor_fontes_aprovacao`, que as
migrações `20261015*`–`20261018*` concedem **só a `service_role`**. É de
propósito: essas RPCs confiam nas claims verificadas e no build do motor
que o chamador declara (`p_engine_build_sha256`,
`validation_provenance = server_manifest_sha256`). Se o JWT do usuário
pudesse chamá-las, o navegador poderia declarar um documento "validado pelo
motor" sem ter passado por ele. No Streamlit isso funciona porque o app tem
a chave de servidor; a API, pela ADR-002, não tem.

**Alternativas consideradas.**
1. *Conceder as RPCs a `authenticated`.* Recusada: quebra a prova de
   proveniência acima e exige migração nas tabelas do Codex.
2. *Serviço documental separado com a chave (sidecar).* Mais isolamento,
   mais uma imagem, rede e deploy. Fica como endurecimento se a ADR-011
   for aceita e o canário mostrar que vale.
3. *Proxy para o Streamlit.* Recusada: "nada novo no Streamlit", e o
   editor legado sai quando o novo provar.
4. **Chave própria, só para estas três RPCs (proposta).**

**Decisão proposta.**
1. **Uma chave, um uso.** `GOVCONECT_DOCUMENTOS_ESCRITA_KEY` (`sb_secret_…`;
   JWT legado só na pilha descartável de teste; igual à da Admin API é
   recusada na subida). Fora do `repr` da configuração.
2. **Janela por operação.** `escrita_documental` cria o cliente de servidor
   só durante UM commit (checkpoint, importação, restauração, aprovação) e
   o põe num `ContextVar` que `db._cliente()` lê **só na API**
   (`CLIENTE_DOCUMENTAL`). Fora da janela, `_cliente()` segue a regra de
   sempre (JWT do usuário).
3. **Só três RPCs.** `ClienteDocumental` manda ao servidor apenas
   `documento_editor_checkpoint`, `_aprovar` e `_fontes_aprovacao`; toda
   outra RPC e todo `.table()` vão com o JWT do usuário (RLS). Não há
   `storage`, `auth` nem PostgREST cru. Prova:
   `test_cliente_documental_so_leva_as_rpcs_de_commit_ao_servidor`.
4. **A chave não autoriza.** As RPCs continuam conferindo, com as claims
   do `documento_editor_contexto` do PRÓPRIO usuário, vínculo, processo,
   revisão (CAS) e competência de revisão/aprovação. Antes de qualquer
   commit a API já verificou o JWT, a trava de ambiente, o canário do
   tenant, a visibilidade do processo pelo RLS e o dono da sessão do editor.

**Consequências e riscos.**
- Mais uma chave de servidor no `api.env` (que o worker também carrega; o
  worker não importa o módulo documental). Mitigação: chave separada da
  Admin API, revogável sozinha, janela por operação, lista fechada de RPCs.
- Um bug que chame `db._cliente()` dentro da janela para outra coisa vai
  com o JWT do usuário (não ganha poder): a lista é de nomes de RPC.
- Revisão pelo `revisor-de-banco-e-seguranca` antes de provisionar a chave.

**Para aceitar:** o operador registra "aceito" aqui, cria a chave no painel
do Supabase e a grava em `/etc/govdocs/api.env`; reinicia a `api`.
