# Proposta — o DELETE de `service_role`, tabela a tabela

**17/09/2026.** Documento de DECISÃO, não de execução. **Nada foi
aplicado**: nenhum `revoke` de DELETE foi executado em produção nem no
projeto de ensaio por causa deste arquivo. As consultas que o embasam
são `SELECT` em catálogo (`information_schema.role_table_grants`,
`pg_constraint`, `pg_proc`, `pg_class`) — nenhuma linha de dado de
negócio foi lida.

A 0024 fechou o TRUNCATE. Este documento é o achado vizinho que ela
deixou explicitamente aberto: `service_role` tem **DELETE em 26 das 32
tabelas** de `public` e é `BYPASSRLS`. Quem obtiver a chave de servidor
apaga linha por linha, e o PostgREST expõe o verbo DELETE.

---

## 1. O que o aplicativo REALMENTE apaga

Levantado por leitura do código, não por suposição.

| Caminho | Tabela |
|---|---|
| `src/db.py:1385` (`.table("config_orgaos").delete()`) | `config_orgaos` |
| `src/db.py:1402` (`.table("processos").delete()`) | `processos` |
| `src/rag.py:447` (`.table("documentos_referencia").delete()`) | `documentos_referencia` |

São **três**. Não há outro `.delete(` em `src/`. Os quatro `.rpc(` do
aplicativo chamam `registrar_evento_governanca` e funções de busca
vetorial; **nenhuma função de `public` contém `delete from`** (medido em
`pg_proc`). Ou seja: não existe caminho indireto de exclusão escondido
atrás de uma RPC.

### A exceção que parece uma e não é

`chunks_referencia` é apagada quando um documento sai — mas por
`on delete cascade` de `documentos_referencia`, não por comando do
aplicativo. A ação referencial do PostgreSQL roda por dentro da
constraint, com os privilégios do dono da tabela, e **não exige DELETE
de quem disparou**. Revogar o DELETE de `chunks_referencia` não quebra a
reindexação do RAG.

Isso vale a pena estar escrito porque é exatamente o tipo de detalhe que
faz um endurecimento "óbvio" quebrar produção — só que aqui ele aponta
para o lado seguro, e a tentação seria manter o privilégio por via das
dúvidas.

---

## 2. As 26, classificadas

`fks` = quantas chaves estrangeiras apontam para a tabela.

### Manter DELETE — 3 tabelas

O aplicativo depende. Revogar quebra um botão que funciona hoje.

| Tabela | fks | Por quê |
|---|---|---|
| `processos` | 2 | Excluir processo é função do painel |
| `config_orgaos` | 0 | Excluir órgão é função da administração |
| `documentos_referencia` | 1 | Remoção de documento da base de conhecimento |

### Trilha e histórico — 13 tabelas

Aqui revogar não é só contenção: é coerência com o que a plataforma já
afirma. `governanca_eventos` **já** não aceita DELETE de `authenticated`
desde a 0020 ("sem política de INSERT, UPDATE ou DELETE — nenhuma
escrita direta, por ninguém, nem o admin"). A credencial de servidor
apagar o que o admin não pode apagar é a contradição que a 0021 corrigiu
nas tabelas de preço e que ninguém estendeu ao resto.

`aprendizado_feedback`, `decisoes`, `geracoes`, `governanca_aprovacoes`,
`governanca_artefatos`, `governanca_eventos`, `governanca_publicacoes`,
`governanca_versoes`, `parecer_achados`, `pareceres`,
`qualidade_scores`, `revisoes`, `simulacoes`.

**Risco de revogar: baixo.** Nenhum código apaga nelas. O que muda é o
dia em que alguém quiser "limpar" registros antigos — e esse dia deve
passar por uma migração com nome, não pela credencial do app.

### Cadastro e estrutura — 4 tabelas

`config_app`, `secretarias`, `tenants`, `usuarios`.

**Risco de revogar: baixo hoje, médio amanhã.** Nenhum código apaga
nelas. Mas são exatamente as tabelas de uma futura tela de
administração ("remover secretaria", "desativar usuário"). A pergunta
para você é de produto, não de banco: *remover* ou *desativar*? Se a
resposta for desativar — e para órgão público quase sempre é, porque o
histórico precisa continuar atribuível —, o DELETE não faz falta nunca.

`tenants` merece nota à parte: **26 chaves estrangeiras** apontam para
ela. Um DELETE ali já falharia por integridade referencial na primeira
linha. O privilégio é, na prática, decorativo — e decoração em matriz de
privilégio é o que faz auditoria futura acreditar em contenção que não
existe.

### Conhecimento e RAG — 6 tabelas

`chunks_referencia`, `fatos_canonicos`, `fontes_conhecimento`,
`melhoria_clusters`, `melhoria_propostas`, `regras_conhecimento`.

**Risco de revogar: o mais alto dos quatro grupos, e ainda assim
moderado.** Nenhum código apaga nelas hoje. Mas reindexação é uma
operação que, por natureza, às vezes precisa remover — e a 0012 e a 0015
existem justamente por causa de uma reindexação. Se a resposta for
"reindexar recria do zero", o DELETE some com elas.

Recomendação para este grupo: revogar **depois** dos outros dois, e num
commit separado, para que uma quebra tenha endereço óbvio.

---

## 3. O que isto vale, honestamente

Não muito contra o pior cenário, e vale dizer com todas as letras: quem
tiver a chave de servidor continuará apagando em `processos` — o dado
que mais importa. Nenhuma matriz de privilégio conserta uma chave
vazada; o que conserta é rotação, e rotação é decisão sua.

O que se ganha é real, mas é outra coisa:

1. **superfície menor** — de 26 tabelas apagáveis para 3;
2. **coerência** — a trilha de governança deixa de ser apagável por uma
   credencial que o próprio sistema descreve como não podendo escrever
   nela;
3. **auditoria que não mente** — a matriz passa a dizer o que o sistema
   faz, em vez de refletir um default do Supabase que ninguém escolheu.

O que NÃO se ganha: contenção contra a chave vazada, que continua o
achado de primeira ordem.

---

## 4. Como eu faria, se você mandar

Uma migração `0025`, no mesmo formato da 0024 — revoke explícito, e um
bloco de conferência que **falha a migração** se o catálogo não
corresponder ao cabeçalho. Mais:

- **provas antes do SQL**, em `tests/`, incluindo a guarda invertida que
  já existe na 0024: se alguém revogar DELETE das três tabelas que o app
  usa, a suíte cai;
- **ensaio nos dois níveis** antes de produção — PostgreSQL local com o
  schema real e o projeto Supabase descartável, que tem os
  `pg_default_acl` de verdade;
- **em commits separados por grupo**, na ordem trilha → cadastro →
  conhecimento, para que uma quebra tenha endereço;
- **e a volta atrás documentada**: `grant delete on public.<tabela> to
  service_role` desfaz qualquer uma destas linhas em um comando. É
  privilégio, não dado — reversível de verdade, ao contrário do que esta
  migração protege.

O que eu **não** faria sem você decidir: mexer no DELETE das três
tabelas do grupo 1, e tocar em `anon`, `authenticated` ou em qualquer
política de RLS. Nada aqui altera RLS.

---

## 5. A pergunta que decide

Só uma, e é de produto:

> Em `secretarias`, `usuarios` e `config_orgaos`, "remover" significa
> apagar a linha ou marcar como inativa?

Se for marcar como inativa, os grupos 2 e 3 (17 tabelas) podem ser
revogados sem ressalva, e o grupo 4 fica para depois da decisão sobre
reindexação. Se for apagar a linha, `usuarios` e `secretarias` saem da
lista e entram na fila de "tela de administração ainda não escrita".
