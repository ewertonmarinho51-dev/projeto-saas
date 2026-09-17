---
name: revisar-migracao
description: >
  Ritual de migração de banco deste projeto — auditar, ensaiar em dois
  níveis, aplicar com conferência que falha sozinha, medir antes e depois,
  registrar no cabeçalho. Use ao escrever, revisar ou aplicar qualquer
  arquivo em supabase/migrations/, e antes de qualquer mudança de schema,
  grant, política de RLS ou privilégio.
---

# Revisar migração

O risco recorrente número um deste projeto, e não por opinião: em
setembro de 2026 a mesma classe de defeito apareceu **três vezes**.

- A 0018–0020 fecharam o `anon`, que tinha `using (true)` em 26 de 28
  tabelas.
- A 0021 revogou `DELETE` de `service_role` e afirmou por escrito que a
  trilha era append-only "até para a credencial de servidor". Não era: o
  `TRUNCATE` ficou, porque o default do Supabase concede `arwdDxtm` e
  ninguém tinha olhado o `D`.
- A 0024, três anos de auditoria depois, encontrou esse mesmo `TRUNCATE`
  ainda de pé em **26 das 32 tabelas** — porque a 0021 consertou as
  tabelas dela e não a fábrica que produz as próximas.

O padrão: **corrigir o privilégio nomeado no achado em vez da classe do
problema**. É isso que este ritual existe para impedir.

## O ritual

### 1. Auditar antes de escrever

Meça o estado atual em catálogo, nunca por memória:

```sql
select grantee, privilege_type, count(*)
from information_schema.role_table_grants
where table_schema = 'public'
group by 1, 2 order by 1, 2;

select d.defaclrole::regrole::text, d.defaclobjtype, d.defaclacl::text
from pg_default_acl d
where d.defaclnamespace = 'public'::regnamespace;
```

Duas perguntas que a 0021 não fez:

- **quem CRIA o objeto?** Em `public` há duas entradas de
  `pg_default_acl` — a de `postgres` e a de `supabase_admin` —, e qual
  vale depende do dono. Migração roda como `postgres`;
- **o que acontece com a PRÓXIMA tabela?** Revogar no estoque sem
  estreitar o default é conserto com validade até a migração seguinte.

### 2. Escrever

Cabeçalho `-- ##` com: o número, o que faz, **ESTADO** (aplicável ou
não), e se foi aplicada em produção — com data e o nome com que entrou.
Depois, o raciocínio: o achado, por que importa, e **o que a migração
NÃO resolve**. Essa última seção não é modéstia; é o que impede a
próxima pessoa de acreditar em contenção que não existe.

Forma genérica (`all tables in schema public`) quando a afirmação é
sobre o schema inteiro; lista nome a nome quando cada tabela foi uma
decisão. A escolha errada engana: listar 32 nomes sugere que alguém
decidiu cada um, e a primeira tabela nova fica de fora em silêncio.

### 3. Conferência que falha sozinha

Toda migração que **afirma** um estado termina medindo se o alcançou:

```sql
do $$
declare faltou text;
begin
  select string_agg(...) into faltou from information_schema... ;
  if faltou is not null then
    raise exception 'A 00NN não cumpriu o que afirma: %', faltou;
  end if;
end
$$;
```

Razão exata: **um `revoke` que não pega não levanta erro.** Ele não faz
nada e devolve sucesso. Sem o bloco, o arquivo declara contenção e o
banco discorda, calado.

### 4. Ensaiar nos dois níveis, nesta ordem

```bash
# 1) PostgreSQL local descartável, schema real
GOVDOCS_ENSAIO_PG_DSN="postgresql://postgres@/postgres?host=/tmp/pgens" \
  python -m pytest tests/ -q
```

Migração de contenção entra em `SEQUENCIA_EM_ENSAIO`
(`scripts/ensaio_local.py`), **por último** quando afirma algo sobre o
schema inteiro. O glob roda antes da sequência; ali ela conferiria um
mundo em que a 0020 ainda não passou, passaria, e não teria provado
nada.

O ensaio local é **de propósito mais permissivo** que a realidade:
reproduz a entrada larga de `pg_default_acl`. Ensaio pessimista gera
revoke a mais; ensaio otimista deixa buraco. Foi o ensaio largo que
revelou o TRUNCATE.

2) Depois, o **projeto Supabase descartável** — é ele que tem as seis
entradas reais de `pg_default_acl` e o `supabase_admin` de verdade.
Nunca o de produção.

### 5. Provar que a prova morde

Aplique a mutação: remova a linha que faz o trabalho e rode. Se a suíte
continuar verde, a prova é enfeite.

Duas armadilhas medidas neste repositório:

- **passar pelo motivo errado.** `truncate processos cascade` era
  recusado mesmo sem a 0024, porque o fecho do CASCADE toca uma tabela
  da 0021. A prova foi reescrita para criar o próprio par pai/filho;
- **a conferência encobrindo a prova.** Mute também com o bloco `do $$`
  desativado, senão você só provou que a migração se autodenuncia.

### 6. Aplicar em produção — só a pedido explícito do operador

Nunca por iniciativa própria, nunca "já que estou aqui".

1. medir ANTES, com a consulta do passo 1;
2. aplicar por `apply_migration`, com nome `m00NN_...`;
3. medir DEPOIS — e conferir o que **não** deveria ter mudado (a 0024
   conferiu que o `DELETE` seguia em 26, e contagem de linhas nas
   tabelas principais);
4. conferir por COMPORTAMENTO quando der, numa tabela descartável criada
   e apagada na hora. **Nunca** ensaie sobre dado de produção o comando
   que a migração existe para impedir, nem dentro de rollback;
5. **atualizar o cabeçalho** registrando a aplicação, e comitar. A 0023
   ficou dizendo "não aplicada" depois de aplicada, e um arquivo de
   migração que mente sobre produção é pior que arquivo ausente, porque
   é consultado com confiança.

## Proibido

- `drop table` para "começar de novo", apagar dados, recriar banco;
- desabilitar RLS para facilitar; `DROP ... CASCADE` como atalho;
- `using (true)` em produção, salvo tabela realmente pública com
  justificativa escrita;
- alterar produção em silêncio;
- seguir adiante quando a migração põe dado existente em risco — **pare,
  corrija, ensaie, e só então continue.**

## O dono

`postgres` mantém tudo, e isso é correto: é o dono das tabelas, tem os
privilégios por construção do PostgreSQL, e revogar dele seria teatro —
ele se reconcede no comando seguinte. Conter o dono não é contenção; é
uma linha a mais no arquivo e uma falsa sensação a mais na auditoria.
