# Etapa E — quem opera com qual credencial

Documento de estado. Registra **o que já foi movido** para o JWT do
usuário, **o que ainda não foi**, e **o que nunca vai ser** — porque
depende legitimamente da credencial de servidor.

Data: 16/08/2026. Branch: `correcao-achados-ensaio-seguranca`.

> **Esta etapa NÃO está concluída.** Ver "O que falta", ao final. Nada
> aqui autoriza declarar a contenção como CONTIDA ou pronta para
> produção.

## O problema em uma frase

Enquanto toda operação passa pelo cliente de servidor, o RLS da 0020
**não é exercido em lugar nenhum**: a credencial secreta o atravessa
por definição. Uma política que nunca é avaliada não protege — ela só
parece proteger, o que é pior, porque a matriz de 28 tabelas passa a
ser lida como garantia.

## Os dois clientes

| | `db._cliente()` | `db.cliente_do_usuario()` |
|---|---|---|
| credencial | `SUPABASE_SECRET_KEY` | chave publicável + JWT do usuário |
| RLS | **atravessa** | **sujeito** |
| identidade | nenhuma (`auth.uid()` é nulo) | o usuário autenticado |
| cache | `st.cache_resource` (singleton) | nenhum — o token expira e roda |
| ausência | app em MANUTENÇÃO | devolve `None`, **sem cair para o servidor** |

`cliente_do_usuario()` devolver `None` em vez de cair para o servidor é
deliberado. A queda silenciosa é exatamente o defeito: quem chama
decide o que fazer com a ausência, e a decisão fica visível no ponto de
chamada.

## O login por Supabase Auth existe

Era a peça que faltava, e sem ela nada mais adiantava: enquanto a
autenticação foi a tabela `usuarios` com `senha_hash` conferido no
Python, **não existia JWT de usuário**, e sem JWT toda requisição ia com
a credencial de servidor.

`auth.autenticar` tenta o Supabase Auth primeiro (`sign_in_with_password`,
com a chave **publicável** — o login é a única operação anterior à
identidade, e fazê-la com a credencial de servidor apagaria a diferença
entre "o servidor autenticou alguém" e "o servidor decidiu que estava
tudo bem"). Em caso de sucesso, `entrar()` guarda o access token em
`st.session_state["supabase_access_token"]`, que é de onde
`db.cliente_do_usuario()` o lê. `sair()` o apaga — sessão encerrada que
deixasse o JWT para trás continuaria autorizando requisições.

Duas regras que o caminho de transição precisa ter, e tem:

- **falha no Supabase Auth cai para o legado enquanto a porta estiver
  aberta.** A primeira versão tentava distinguir "senha errada" de
  "conta não existe" pela mensagem do GoTrue, para não dar uma segunda
  chance contra outro banco de senhas. Mas o GoTrue devolve
  `Invalid login credentials` para os dois casos, de propósito —
  distinguir permitiria enumerar usuários. A leitura era adivinhação, e
  **trancou o login em produção**: sem backfill, toda conta é
  inexistente no Supabase Auth, e todo mundo era recusado antes de
  chegar ao legado, com a senha certa. A regra de "sem segunda chance"
  passou a morar onde é verificável: no interruptor
  `GOVDOCS_EXIGIR_SUPABASE_AUTH`. Ligado, não há legado para tentar;
- **conta sem vínculo em `usuarios` não entra.** Autenticar não é
  autorizar: sem linha vinculada não há tenant, secretaria nem papel.

`GOVDOCS_EXIGIR_SUPABASE_AUTH=1` fecha a porta legada. É o interruptor
final da Etapa E.

## Já movido para o JWT do usuário

| operação | módulo | observação |
|---|---|---|
| **login** | `auth.autenticar` / `auth.entrar` | Supabase Auth, token na sessão |
| registrar evento na trilha | `db.registrar_evento_governanca` | agora é a **RPC**, não `insert` |
| decidir proposta de melhoria | `laboratorio.decidir_proposta` | `update` em `melhoria_propostas` |
| registrar aprovação | `laboratorio.registrar_aprovacao` | `insert` em `governanca_aprovacoes` |

Nos três, a ausência de sessão **recusa a operação** com mensagem
explícita. Um ato de governança cujo registro não pôde ser feito não
pode ser dado como praticado.

## Precisa legitimamente da credencial de servidor

Estas operações **não têm** usuário autenticado a quem atribuir, ou
atuam sobre o próprio mecanismo de autenticação. Movê-las para o JWT do
usuário não as tornaria mais seguras — as tornaria impossíveis.

| operação | módulo | por quê |
|---|---|---|
| autenticar pelo caminho legado (ler `usuarios`, conferir `senha_hash`) | `auth._autenticar_legado` | roda **antes** de existir sessão; sai de cena com `GOVDOCS_EXIGIR_SUPABASE_AUTH=1` |
| resolver o vínculo institucional após o login | `auth._usuario_por_auth_id` | a linha de `usuarios` é lida para descobrir tenant/secretaria, antes de haver contexto |
| criar o primeiro administrador | `auth.criar_usuario` | instalação: não há usuário para autenticar |
| ler `config_app` / `config_orgaos` | `db` | configuração da instalação, não dado de usuário; as políticas da 0020 mantêm essas tabelas fechadas a `authenticated` |
| sonda de privilégio da credencial | `db.sondar_credencial_ativa` | o objeto da sonda **é** a credencial de servidor |
| indexação/embeddings do RAG | `rag` | rotina de servidor, sem usuário na origem |

Cada linha desta tabela é uma exceção **nomeada**. Exceção sem nome é
como a situação anterior voltaria.

## Ainda NÃO movido — o débito desta etapa

Todo o restante de `db.py` (processos, revisões, fatos canônicos,
decisões, gerações, qualidade, feedback, artefatos e versões de
governança), além de `pareceres.py`, `conhecimento.py`, `politicas.py` e
`ui/governanca_ui.py`, continua no cliente de servidor.

O código do login existe agora; o que falta é operacional e não dá para
fazer daqui: a **0020 precisa ser aplicada** (é ela que cria
`auth_user_id`, as políticas e a RPC) e as **contas precisam existir no
Supabase Auth**, com papel, tenant e secretaria em `app_metadata` — que
só a Admin API grava.

Enquanto isso, quem entra pelo caminho legado não tem token, e as
operações movidas **recusam**. É falha fechada, não regressão: dá para
entrar e usar o app, não dá para praticar ato de governança fingindo
que foi registrado.

**Consequência para a implantação:** este código pode ir ao ar antes da
0020 — login e uso normal seguem funcionando — mas os atos de
governança (aprovar, publicar, decidir proposta) vão recusar até que a
0020 esteja aplicada e o backfill feito. Quem implantar sem seguir a
ordem abaixo tira o Centro de Governança do ar sem tirar o app.

## Ordem de implantação

1. rodar o **ensaio SQL local** (`scripts/ensaio_local.py` +
   `tests/test_ensaio_sql_local.py`) — feito, 47 provas passando, e foi
   ele que achou os dois defeitos de `default privileges`;
2. aplicar a **0018/0019/0020** num projeto de ensaio descartável e
   rodar as fases A e B, para cobrir PostgREST e GoTrue, que o ensaio
   local não cobre;
3. **backfill**: para cada linha de `usuarios`, criar a conta no
   Supabase Auth pela Admin API com
   `app_metadata = {papel, tenant_id, secretaria_id, papel_governanca}`
   e gravar o id em `usuarios.auth_user_id`. Nunca em `user_metadata`,
   que o próprio usuário edita;
4. implantar este código, ainda com a porta legada aberta, e conferir
   que os logins passam a trazer token;
5. ligar `GOVDOCS_EXIGIR_SUPABASE_AUTH=1` — a porta legada fecha;
6. migrar o restante da tabela "ainda não movido", uma área por vez,
   rodando o ensaio a cada passo.

## O que falta para a Etapa E fechar

- [x] ensaio da camada SQL executado (47 provas)
- [x] login por Supabase Auth, com token na sessão
- [x] trilha de governança pela RPC, com o JWT do usuário
- [ ] 0018/0019/0020 aplicadas em projeto de ensaio, fases A e B sem
      skip (cobre PostgREST e GoTrue)
- [ ] backfill das contas no Supabase Auth
- [ ] `GOVDOCS_EXIGIR_SUPABASE_AUTH=1` em produção
- [ ] operações de processo/revisão/geração no JWT do usuário
- [ ] prova de que o fluxo normal completo roda **sem** a credencial de
      servidor
