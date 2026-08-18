# Achado P0 — vulnerabilidade de autorização no banco

**14–15/08/2026.** Preparação para revisão humana. **Nada foi aplicado:**
nenhum SQL executado, nenhuma chave rotacionada, nenhuma alteração em
produção, nenhum push. Nenhum valor de credencial, hash de senha ou dado
pessoal foi lido, impresso ou registrado. As consultas de diagnóstico
foram `SELECT` em catálogo (`pg_tables`, `pg_policies`, `pg_class`,
`pg_proc`, `pg_default_acl`) — **nenhuma linha de dado de negócio**.

---

## 1. Classificação

Esta seção é deliberadamente literal sobre o que está provado e o que
não está. A versão anterior deste documento chamava o achado de
"incidente" e instruía a "tratar como comprometimento possível de
contas"; a redação misturava vulnerabilidade com evento, e essa mistura
leva a decisões erradas — inclusive a decisões apressadas em produção.

| Dimensão | Situação | Base |
|---|---|---|
| **Vulnerabilidade de autorização** | **CONFIRMADA** | Catálogo de produção: 26 de 28 tabelas com políticas `using (true)` para `anon` e os quatro privilégios concedidos |
| **Impacto potencial** | **CRÍTICO** | Inclui `usuarios` com UPDATE/INSERT/DELETE abertos — tomada de conta administrativa |
| **Exposição da chave publicável** | **NÃO PROVADA** | Chave não versionada; app é Streamlit e não a publica ao cliente; não há evidência de vazamento |
| **Comprometimento anterior** | **NÃO PROVADO** | Sem trilha de acesso não é possível afirmar que ocorreu — **nem que não ocorreu** |
| **Prioridade** | **P0 PREVENTIVA** | Corrigir com urgência máxima, **sem declarar incidente consumado** |

### O que isso muda na prática

- **Não** se comunica violação de dados, **não** se notificam titulares e
  **não** se aciona plano de resposta a incidente. Nada sustenta isso.
- **Sim**, corrige-se com prioridade máxima: a vulnerabilidade é real,
  está em produção e o impacto potencial é total.
- A revisão de contas e a redefinição de senhas (passo `g`) continuam no
  runbook — como **medida precaucional**, não como remediação de um
  comprometimento constatado.
- Se, durante a execução, surgir **evidência** de acesso indevido
  (conta administrativa desconhecida, alteração inexplicada, registro em
  log de plataforma), a classificação muda para incidente e o plano de
  resposta passa a valer. Essa checagem é o passo `g`.

### Correção de uma afirmação do diagnóstico anterior

`docs/seguranca-config-app.md` afirmou que a chave publicável "vai para
o navegador de qualquer visitante". **Isso está errado para esta
arquitetura.** O GovDocs é um app **Streamlit**: roda inteiro no
servidor, e o navegador recebe a interface renderizada por websocket —
`st.secrets`, o cliente Supabase e a chave ficam no processo do
servidor.

Verifiquei também que a chave real **não está versionada**: os três
arquivos do repositório que casam com o padrão (`README.md`,
`secrets.toml.example`, `src/ui/login.py`) contêm apenas o placeholder
`sb_publishable_...`, e `.gitignore` cobre `.streamlit/secrets.toml`.

O que permanece verdadeiro:

- a chave publicável **deve ser tratada como pública** — é a premissa do
  modelo do Supabase, que assume a autorização no RLS, e ela circula por
  painel, backups de configuração, logs de plataforma e pela própria API
  de gestão do projeto;
- **a vulnerabilidade material é a combinação de grants e políticas
  permissivas.** Com `anon` detendo SELECT/INSERT/UPDATE/DELETE e
  políticas `using (true)`, o RLS é um no-op: quem obtiver a chave por
  qualquer via tem controle total do banco.

---

## 2. Matriz de acesso (produção, somente leitura)

**28 tabelas** em `public`; **26 com acesso anônimo irrestrito**; 2 de
backup sem política (fechadas por RLS sem policy).

| Tabela | Operações abertas a `anon` | Uso legítimo pelo app |
|---|---|---|
| `usuarios` | SELECT, INSERT, UPDATE, DELETE | **exclusivo servidor** |
| `config_app` | SELECT, INSERT, UPDATE, DELETE | **exclusivo servidor** |
| `config_orgaos` | SELECT, INSERT, UPDATE, DELETE | autenticado (leitura), admin (escrita) |
| `processos` | SELECT, INSERT, UPDATE, DELETE | autenticado, por dono/tenant |
| `revisoes` | SELECT, INSERT, UPDATE | autenticado, por tenant |
| `geracoes`, `decisoes`, `simulacoes`, `qualidade_scores`, `fatos_canonicos` | SELECT, INSERT (+UPDATE em alguns) | autenticado, por tenant |
| `pareceres`, `parecer_achados`, `melhoria_clusters`, `melhoria_propostas`, `aprendizado_feedback` | SELECT, INSERT (+UPDATE em alguns) | autenticado |
| `governanca_*` (5 tabelas) | SELECT, INSERT (+UPDATE em 2) | autenticado (leitura), admin (escrita); `governanca_eventos` deveria ser append-only |
| `regras_conhecimento`, `fontes_conhecimento`, `documentos_referencia`, `chunks_referencia` | SELECT, INSERT, UPDATE, DELETE | autenticado (leitura), admin (escrita) |
| `secretarias` | SELECT, INSERT, UPDATE, DELETE | autenticado (leitura) |
| `tenants` | SELECT | autenticado (leitura) |
| `chunks_referencia_bkp_20260811`, `documentos_referencia_bkp_20260811` | **nenhuma** | manutenção (fora do app) ✅ |

### Além das tabelas

Esta parte não existia no diagnóstico anterior e é onde estava a lacuna
mais séria.

- **Views:** nenhuma em `public`. Nenhuma materializada, nenhuma foreign
  table.
- **Funções expostas:** `buscar_chunks_textual` e
  `buscar_chunks_vetorial`, ambas `SECURITY INVOKER`, com **EXECUTE
  concedido a `PUBLIC`** além de `anon` e `authenticated`. Como são
  INVOKER, herdam o RLS do chamador e não escalam hoje — mas o EXECUTE
  aberto vira contorno pronto do RLS no dia em que alguma virar
  `SECURITY DEFINER`. `set_atualizado_em` está fechada. As demais são
  operadores do `pgvector` e **não devem ser revogadas** (revogá-las
  quebra índices e comparações). **Nenhuma `SECURITY DEFINER` exposta.**
- **Sequences:** `chunks_referencia_id_seq` e
  `governanca_publicacoes_numero_seq` concedem `SELECT/UPDATE/USAGE` a
  `anon` e `authenticated`. `USAGE`+`UPDATE` permitem `nextval`/`setval`:
  **dá para adulterar a numeração de publicações da governança sem tocar
  em tabela alguma.**
- **Default privileges — a causa da recorrência.** Existem
  `ALTER DEFAULT PRIVILEGES` em `public`, para os donos `postgres` **e**
  `supabase_admin`, concedendo a `anon` e `authenticated`: tabelas
  futuras → **todos** os privilégios; funções futuras → EXECUTE;
  sequences futuras → `rwU`. **Sem revogar isso, a próxima migração que
  criar uma tabela recria a vulnerabilidade inteira** — e explica por que
  ela apareceu em 26 tabelas de uma vez.
- **Schemas expostos pela Data API:** `public` e `graphql_public`. O
  segundo concede a `anon` tudo em objetos futuros, e
  `graphql_public.graphql()` consulta os **mesmos** objetos de `public`.
  O resolvedor respeita RLS e grants, então fechar `public` o fecha
  junto; ainda assim, a recomendação é **desmarcar `graphql_public`** em
  Settings → API → Exposed schemas, já que o app não usa GraphQL.
- **Storage:** **0 buckets**. Há default privileges abertos no schema
  `storage`, mas ele é gerenciado pelo Supabase e não deve ser alterado
  por migração da aplicação. Se algum dia houver bucket, ele exige
  revisão específica.

### `usuarios` — por que é o achado crítico

A migração 0004 anotou que "os hashes PBKDF2 mitigam exposição de
senhas". O raciocínio para na metade: PBKDF2 impede **inverter** o hash,
não **substituí-lo**. Com UPDATE liberado, gera-se o hash de uma senha
própria (formato em `src/auth.py`, repositório público), troca-se
`senha_hash` do administrador e entra-se pela tela normal. INSERT
liberado permite criar conta já com `papel='admin'`; DELETE permite
apagar todas.

Não há trilha de acesso que permita afirmar se isso ocorreu. **Ausência
de evidência não é evidência de ausência** — e também não é evidência de
ocorrência. Daí a revisão de contas do passo `g` ser precaucional.

---

## 3. Mapa de operações do aplicativo

Extraído do código (35 chamadas, 21 objetos). "Servidor" = jamais deve
ser possível com a chave publicável.

| Tabela | Operações | Onde | Acesso necessário |
|---|---|---|---|
| `usuarios` | select, insert, update | `auth.autenticar`, `criar_usuario`, `listar_usuarios`, `atualizar_usuario` | **servidor** |
| `config_app` | select, upsert | `db.obter_config`, `db.salvar_config`, `db.flag_ativa` | **servidor** |
| `processos` | select, delete (+ upsert em `salvar_processo`) | `db.carregar_processo`, `listar_processos`, `excluir_processo` | autenticado, dono/tenant |
| `revisoes` | select, insert, update | `db.criar_revisao`, `obter_revisao_por_chave`, `atualizar_revisao` | autenticado, tenant |
| `geracoes` | insert | `db.registrar_geracao_bd` | autenticado |
| `fatos_canonicos` | select, insert, update | `db.salvar_fatos`, `listar_fatos`, `atualizar_fato` | autenticado, tenant |
| `decisoes`, `simulacoes`, `qualidade_scores` | select, insert | `registrar_decisao`, `simular`, `salvar_score` | autenticado |
| `governanca_*` | select, insert | `criar_versao_governanca`, `registrar_aprovacao`, `registrar_release`, `registrar_evento_governanca` | autenticado (leitura), admin (escrita); eventos **append-only** |
| `pareceres`, `parecer_achados`, `melhoria_*`, `aprendizado_feedback` | select, insert, update | `analisar`, `criar_proposta`, `decidir_proposta`, `salvar_feedback` | autenticado |
| `regras_conhecimento`, `fontes_conhecimento` | select | `listar_regras` | autenticado (leitura) |
| `documentos_referencia`, `chunks_referencia` | insert, delete | `indexar_arquivo`, `excluir_referencia` | **admin** |
| `config_orgaos` | select, delete | `listar_orgaos`, `excluir_orgao` | autenticado (leitura), admin (escrita) |
| `secretarias` | select | `listar_secretarias` | autenticado |
| RPC `buscar_chunks_*` | execute | `rag.consulta_*` | autenticado |

**Nada no app precisa de acesso anônimo.** O único conteúdo público é a
tela de login.

---

## 4. O que mudou no código desta branch

1. **Credencial exclusivamente de servidor.** `SUPABASE_SECRET_KEY`
   (formato `sb_secret_…`) passa a ser a credencial primária, lida de
   Streamlit Secrets ou do ambiente — **nunca do banco** (a credencial
   do banco não pode depender do banco). A `service_role` legada
   (`SUPABASE_SERVICE_KEY`, JWT) continua aceita **apenas para a
   transição**, com aviso de descontinuação exibido na Administração.
   O aviso descreve formato e origem; **nunca o valor**.

2. **Falha realmente fechada — modo de manutenção.** Com
   `GOVDOCS_EXIGIR_CREDENCIAL_SERVIDOR=1` e sem credencial de servidor,
   o app entra em **manutenção**: bloqueia login, persistência,
   aprovação, geração oficial e emissão. **Não** há operação degradada
   "sem persistência" e **não** há fallback para a chave publicável.

   A versão anterior deste plano deixava o app rodar sem banco, o que
   era pior do que parece: um servidor concluiria um processo inteiro
   sem rastro persistido, e o "sem persistência" convidava a contornar a
   contenção em vez de concluí-la.

   A barreira é repetida em cada caminho, para não depender da ordem de
   renderização da interface: `app.py` (porta de entrada),
   `db._cliente`, `auth.autenticar`, `auth.criar_usuario`,
   `state.aprovar_e_avancar` e `revisao.emissao_liberada`.

   **`auth.modo_aberto()` devolve `False` em manutenção.** Sem essa
   guarda, uma variável `GOVDOCS_MODO_ABERTO=1` esquecida no ambiente
   transformaria a falha fechada em "app inteiro liberado sem login" —
   exatamente durante a contenção.

3. **Nenhum segredo em interface, log, erro ou banco — em duas camadas.**
   Expressão regular sozinha não defende contra um formato de credencial
   que ainda não conhecemos. Então:

   - a **interface** nunca recebe o texto original da exceção: recebe
     mensagem genérica e um **identificador de correlação**
     (`Referência: FA3C91B2`);
   - o **log** recebe o texto já sanitizado por `db.redigir()`, que
     cobre JWT, `sb_publishable_`/`sb_secret_`, `sk-`, `AIza`, tokens do
     GitHub, hashes PBKDF2, parâmetros nomeados em querystring, cabeçalho
     e JSON, formas percent-encoded, credencial embutida em URL, a
     referência do projeto e sobras opacas longas.

   Isso corrigiu um vazamento real: o caminho genérico de
   `_traduzir_erro` repassava a exceção bruta, e erros de API trazem a
   credencial no cabeçalho. O mesmo tratamento foi aplicado a
   `src/auth.py`, `src/rag.py` e `src/llm.py` — em `llm`, o campo
   `detalhe` de `ErroGeracaoIA` ia para a tela **e** para a coluna de
   auditoria de `registrar_geracao`, e um 401 de OpenAI/Gemini ecoa a
   própria chave.

---

## 5. Contenção em duas fases

### Fase emergencial — `0019_emergencial_fecha_anon.sql.NAO_APLICAR`

Tudo dirigido pelo **catálogo**, nunca por lista escrita à mão. A versão
anterior enumerava nomes de política e teria deixado passar
`anon_select_geracoes`, `anon_insert_geracoes` e `anon_select_tenants`;
enumerava tabelas e deixava de fora as duas de backup. Agora cobre:

1. **políticas** — todas as que citam `anon`, `authenticated` ou
   `public`, por varredura de `pg_policies`;
2. **tabelas** — revoga privilégios e força RLS em todas as de
   `pg_tables`;
3. **sequences** — revoga `USAGE`/`SELECT`/`UPDATE`;
4. **funções e RPCs** — revoga EXECUTE de `anon`/`authenticated`/`PUBLIC`,
   preservando as de extensão (`pgvector`);
5. **default privileges** — revoga para `postgres` **e**
   `supabase_admin`, em tabelas, sequences e funções futuras;
6. **schemas expostos** — orientação para desmarcar `graphql_public`
   (configuração de painel, não SQL);
7. **append-only** de `governanca_eventos`.

O arquivo traz um bloco de **verificação** (cinco consultas que devem
devolver zero linhas) e um **rollback de uso restrito**: ele reabre o
banco para `anon` e por isso **só pode ser executado com o app em
manutenção e o acesso público fechado**. Nenhuma migração toca em linha,
então não há dado a restaurar.

### Fase definitiva — `0020_definitiva_supabase_auth_rls.sql.NAO_APLICAR`

Autorização de volta ao banco: Supabase Auth como fonte única de
identidade, `auth_user_id` em `usuarios`, dono e tenant em cada
registro, políticas por `auth.uid()` com **`USING` e `WITH CHECK`** em
toda escrita, privilégio mínimo por operação (sem `delete` — exclusão
lógica preserva auditoria), e retirada progressiva da credencial
privilegiada.

**Papel administrativo mora em `app_metadata`, nunca em
`user_metadata`.** `user_metadata` é editável pelo próprio usuário via
`auth.updateUser()`: guardar `papel: 'admin'` ali entrega escalação de
privilégio de graça. `app_metadata` só é gravável com credencial de
servidor. O papel viaja no JWT e é lido pelas políticas sem consultar
tabela — o que também evita recursão de RLS.

### Credencial de servidor **não** é a solução

Ela ignora RLS por definição: adotá-la como modelo permanente move toda
a autorização para o código do app, sem rede de proteção no banco. Na
transição ela fica **somente no servidor**, com **inventário explícito**
das operações que ignoram RLS — hoje, todas as da seção 3. A fase
definitiva esvazia essa lista uma política por vez.

---

## 6. Runbook — ordem obrigatória

**Nenhum passo entre `f` e `i` pode reabrir o aplicativo.** A ordem
importa mais que a velocidade: executar `f` antes de `d` derruba o app;
reabrir antes de `i` expõe um app que ainda não foi verificado.

| # | Passo | Onde | Por que nesta posição |
|---|---|---|---|
| **a** | Colocar o app em **manutenção** / acesso privado | Streamlit Cloud | Tudo o que vem depois altera autorização com o app no ar; manutenção elimina a janela |
| **b** | **Preservar evidências**: backup do banco, cópia das políticas e grants atuais, exportação dos logs de plataforma | Supabase + Streamlit | Depois de `f` o estado anterior é irrecuperável, e é ele que permite investigar se houve acesso indevido |
| **c** | **Criar/rotacionar credenciais** e gravá-las nos Secrets: `SUPABASE_SECRET_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `GOVDOCS_EXIGIR_CREDENCIAL_SERVIDOR=1` | painéis + Secrets | O código de `d` exige a credencial de servidor; sem ela ele sobe direto em manutenção |
| **d** | **Publicar o código** desta branch: credencial de servidor, redação, falha fechada | deploy | Precisa estar no ar **antes** de `f`; a 0019 revoga justamente o que o código antigo usa |
| **e** | **Remover** `OPENAI_API_KEY` e `GOOGLE_API_KEY` de `config_app` | SQL Editor | Só depois de `c` confirmar que as novas chaves funcionam. `llm._ler_chave` consulta `db.obter_config → session → st.secrets → env`: o app segue pelo terceiro degrau, sem indisponibilidade |
| **f** | Executar a **0019 no ensaio**, conferir, depois **em produção** | SQL Editor | Ensaio primeiro sempre. Em produção só com `d` publicado |
| **g** | **Revisar todas as contas**: remover administradores desconhecidos, redefinir senhas | app / SQL | Medida **precaucional**. Se aparecer conta desconhecida ou alteração inexplicada, a classificação muda para incidente |
| **h** | **Reiniciar o app** para invalidar `st.session_state` | Streamlit Cloud | A sessão vive na memória do servidor, sem tabela nem JWT: reiniciar é a **única** forma de invalidar todas. Uma sessão aberta sobrevive à troca de senha de `g` |
| **i** | **Smoke test privado**: login, criação de processo, geração, aprovação, emissão, Base de Conhecimento | app, acesso restrito | Verificar que a contenção não quebrou o app **antes** de qualquer usuário voltar |
| **j** | **Reabrir o acesso** | Streamlit Cloud | Só aqui |

### Verificação intermediária (após `f`, antes de `g`)

Rodar as cinco consultas do rodapé da 0019 — todas devem devolver zero
linhas — e o `--sondar` do ensaio contra o ambiente de ensaio já
migrado.

### Passos que exigem aprovação humana explícita

Nenhum foi executado.

| Ação | Irreversível? |
|---|---|
| Rotacionar `OPENAI_API_KEY` / `GOOGLE_API_KEY` (`c`) | sim (a antiga morre) |
| Gravar Secrets (`c`) | não |
| `delete from public.config_app where chave in (…)` (`e`) | reversível (regravar) |
| Executar a 0019 (`f`) | reversível pelo rollback, **só com o app em manutenção** |
| Revisar contas / redefinir senhas (`g`) | não |
| Reiniciar o app (`h`) | não |
| Rotacionar a chave publicável do Supabase | exige atualizar o app |
| Renomear `.NAO_APLICAR` → `.sql` | reversível |

---

## 7. Ensaio reproduzível — `scripts/ensaio_seguranca.py`

O script **recusa-se a rodar contra a URL de produção** (verificado) e
imprime apenas objeto, operação, papel e veredito — nunca linha,
credencial, hash ou dado pessoal.

O inventário de tabelas é **lido das migrações**, não escrito à mão: a
versão anterior sondava 6 tabelas de 28 e ainda assim imprimia
"CONTIDO". Um inventário incompleto é pior que nenhum — dá por fechado o
que nunca foi olhado. Um teste local
(`test_o_inventario_cobre_todas_as_tabelas`) falha se a contagem
divergir das 28 confirmadas em produção.

O ensaio prova **quatro** coisas:

1. **`anon` é negado** em toda tabela, RPC e no Storage;
2. **`authenticated` sem política de titularidade também é negado** —
   fechar só o `anon` move o problema para quem se cadastra;
3. **as operações legítimas do servidor continuam funcionando** — é o
   que separa "contido" de "quebrado";
4. **um objeto novo nasce fechado** — prova de que os default privileges
   foram revogados e a vulnerabilidade não volta na próxima migração.

`--instrucoes` imprime o SQL que o operador roda no ensaio (conta comum
para o papel `authenticated`, tabela `ensaio_objeto_novo`) e a sequência
recomendada.

### Security Advisors — executados, e o resultado é ele próprio um achado

Não existe projeto de ensaio nesta organização: `list_projects` devolve
**um único projeto**, `govdocs-wizard` (produção). Provisionar um é
mutação externa, fora do que foi autorizado — então os Advisors foram
rodados em **produção, em modo somente leitura**, como linha de base.

Resultado completo, em 15/08/2026:

| Nível | Achado |
|---|---|
| WARN | `extension_in_public` — extensão `vector` instalada em `public` |
| INFO | `rls_enabled_no_policy` — `chunks_referencia_bkp_20260811` |
| INFO | `rls_enabled_no_policy` — `documentos_referencia_bkp_20260811` |

**É só isso.** Nenhum achado sobre as 26 tabelas com política
`using (true)` para `anon`. Nenhum achado sobre os grants abertos.
Nenhum sobre os default privileges. Nenhum sobre as sequences. Nenhum
sobre o EXECUTE para `PUBLIC`.

E a inversão é completa: os dois únicos INFO apontam justamente as
**duas tabelas corretamente fechadas** (RLS ligado, sem política), e o
linter fica em silêncio sobre as 28 menos essas duas.

A conclusão operacional importa mais que o relatório: **os Security
Advisors não detectam este achado.** Eles verificam se o RLS está
*ligado*, não se a política *autoriza alguma coisa* — e aqui o RLS está
ligado em todas as tabelas. Um "0 achados de severidade alta" desses
Advisors **não é critério de aceitação** para esta contenção; quem
prova o fechamento é o `--sondar` do ensaio, que tenta a operação de
fato.

Os Advisors continuam no runbook, mas como verificação complementar:
rodar de novo no ensaio depois da 0019 e depois da 0020, e conferir que
o `extension_in_public` e os dois `rls_enabled_no_policy` seguem sendo
o teto de severidade — não como prova de que a contenção funcionou.

---

## 8. Testes — `tests/test_seguranca_contencao.py`

**40 locais, sempre executam:**

- credencial atual `sb_secret_…` com prioridade sobre a publicável e
  sobre a legada; `service_role` legada aceita com aviso de
  descontinuação que nunca cita o valor; aviso de formato quando a chave
  não parece secreta;
- manutenção bloqueando conexão, login, bootstrap de administrador,
  aprovação e emissão; manutenção **não** virando modo aberto;
- interface recebendo mensagem genérica com referência única; log
  recebendo texto já sanitizado; redação cobrindo querystring, cabeçalho
  (em duas caixas), JSON, traceback multilinha, percent-encoding,
  credencial em URL, `sb_secret_`, `sb_publishable_`, `sk-`, `AIza`,
  hash PBKDF2 e sobra opaca longa;
- inventário cobrindo as 28 tabelas; migrações ainda `.NAO_APLICAR`;
  0019 dirigida pelo catálogo; 0020 usando `app_metadata` e nunca
  `user_metadata`.

**62 de ensaio, pulados por padrão** — só rodam com
`GOVDOCS_ENSAIO_URL`/`GOVDOCS_ENSAIO_ANON_KEY` de um projeto de ensaio:
`anon` não lê nem escreve em nenhuma das 28 tabelas, não cria
administrador, não altera `papel` nem `senha_hash`, não executa as RPCs;
objeto novo nasce fechado; e o servidor continua operando.

---

## 9. Riscos residuais e pendências

- **Comprometimento anterior não é detectável** com o que existe hoje.
  Não é possível afirmar que ocorreu nem que não ocorreu. Mitigação
  precaucional: passo `g`. Mitigação estrutural: trilha de acesso, que
  não existe e deveria.
- **Sessões ativas.** A sessão vive em `st.session_state` (memória do
  servidor), sem tabela nem JWT: a única forma de invalidar todas é
  reiniciar o app (passo `h`). Uma sessão aberta sobrevive à troca de
  senha.
- **Janela entre rotação e revogação.** A chave antiga funciona até ser
  revogada; a nova, se as políticas ainda estiverem abertas, tem o mesmo
  poder. É por isso que `f` vem logo depois de `d`.
- **Credencial de servidor na transição** concentra risco no servidor;
  enquanto durar, a autorização é responsabilidade do código.
- **A rotação da chave publicável exige atualizar o app**, sob pena de
  indisponibilidade.
- **Backups e réplicas** feitos antes da contenção mantêm o conteúdo
  exposto pelas políticas antigas.
- **Ensaio não executado.** `list_projects` confirma **um único projeto**
  na organização — produção. Provisionar um projeto de ensaio é mutação
  externa, fora do que foi autorizado. Os 62 testes de ensaio ficam
  pendentes até que ele exista. **Nada nesta branch depende dessa
  execução para ser revisado**, mas nada deve ir a produção sem ela: o
  passo `f` do runbook exige o ensaio antes da produção.
- **Os Security Advisors não cobrem este achado** (seção 7). Não
  confiar neles como critério de aceitação — nem antes, nem depois da
  contenção.
- **`graphql_public` exposto** continua sendo configuração de painel, não
  corrigível por migração.

### Achado lateral: a referência do projeto está publicada na `main`

A varredura de histórico desta branch (seção 10) encontrou a referência
do projeto de produção **já versionada e já publicada** em dois arquivos
da `main`, em repositório **público**:

- `CLAUDE.md`, linha 25;
- `docs/p1-inteligencia-documental.md`, linha 315.

Isso **precede esta branch** — não foi introduzido pela contenção, e
removê-lo daqui não conteria nada, porque a `main` já o publicou.

A gravidade é moderada e vale registrar com precisão: a referência
**não é uma credencial**. Ela vai na URL de toda requisição e, com o
RLS correto, conhecê-la não dá acesso a nada. O que ela faz é **entregar
o alvo**: quem varre o GitHub atrás de referências Supabase encontra
esta instalação e pode testá-la contra exatamente a vulnerabilidade da
seção 2 — que hoje está aberta.

Enquanto a 0019 não for aplicada, a combinação "referência pública +
autorização ausente" é o caminho mais curto para explorar o achado. É
mais uma razão para a ordem do runbook, não um item separado de
remediação.

**Decisão pendente do responsável**, porque envolve reescrever
histórico já publicado:

1. remover a referência dos dois arquivos (mudança simples, mas o
   histórico permanece); ou
2. remover e reescrever o histórico da `main` (invalida clones e
   forks); ou
3. **aceitar a exposição** e tratá-la como o que é — a premissa do
   modelo Supabase, em que a referência é pública e a segurança mora no
   RLS. Esta é a escolha coerente **depois** de a 0019 e a 0020 estarem
   aplicadas.

Nesta branch, o único ajuste feito foi em `scripts/ensaio_seguranca.py`:
a guarda contra produção passou a comparar por **hash SHA-256** da
referência, em vez de guardá-la em texto claro. A guarda continua
recusando a URL de produção (verificado), sem acrescentar mais uma
cópia da referência ao repositório público.

---

## 10. Varredura do histórico da branch

Executada sobre `origin/main...HEAD` (4 commits, 2.599 linhas de diff),
procurando JWT, `sb_secret_`, `sb_publishable_`, `sk-`, `AIza`, tokens
do GitHub, hashes PBKDF2 reais, CPF, e-mail, URL de projeto e chave
privada.

**Resultado: nenhuma credencial, nenhum hash real, nenhum dado pessoal.**

As únicas ocorrências que casam com os padrões são **literais falsos**,
criados dentro dos próprios testes para exercitar a redação: uma chave
secreta e uma publicável de fachada, uma chave de IA inventada e um JWT
cuja carga decodifica para `payload-de-teste`. Nenhum deles é, nem já
foi, uma credencial de verdade.

Eles não aparecem escritos aqui — nem em lugar nenhum do disco. São
MONTADOS em tempo de execução, a partir de pedaços que sozinhos não
casam padrão algum (ver `_montar` em `tests/test_seguranca_contencao.py`
e `_montado` em `scripts/varredura_segredos.py`).

A regra chegou pelo caminho mais didático: o **Push Protection do
GitHub recusou o push** deste repositório por causa desses literais. Ele
estava certo. Bloqueia por PADRÃO, não por veracidade — não tem como
saber que a chave é inventada, e não deve acreditar na palavra de quem
empurra. Pedir exceção ao scanner seria repetir, na porta do
repositório, o defeito que este documento inteiro existe para apontar:
o segredo de mentira ensinando todo mundo a desligar o alarme.

O único achado real foi a referência do projeto — tratada acima, e
**anterior a esta branch**.
