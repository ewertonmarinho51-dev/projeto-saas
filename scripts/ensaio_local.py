#!/usr/bin/env python3
"""
Ensaio da camada SQL num PostgreSQL LOCAL e descartável.

    python scripts/ensaio_local.py --dsn "postgresql://postgres@/postgres?host=/tmp/pgens"

Por que isto existe
-------------------
As provas de autorização estavam todas PULANDO por falta de um projeto
Supabase descartável. Um teste que pula não prova nada, e uma matriz de
28 tabelas que ninguém executou é uma promessa, não uma contenção.

Este módulo levanta o schema REAL — as migrações do repositório, sem
cópia nem paráfrase — num Postgres local, e deixa a 0020 aplicada e
exercitável. As provas então RODAM.

O que ele prova, e o que NÃO prova
----------------------------------
PROVA: tudo que vive no banco. Políticas de RLS, `SECURITY DEFINER`,
a matriz papel×evento, a resolução de escopo da aprovação, os GRANTs.
É onde a autorização mora, e é o que estava sem execução.

NÃO PROVA: PostgREST (tradução de HTTP para SQL, códigos PGRST*),
GoTrue (emissão e validação de JWT, `app_metadata` gravável só por
servidor) nem o cliente `supabase-py`. Aqui o JWT é INJETADO via
`request.jwt.claims`, que é exatamente o que o PostgREST faz — mas
quem confere a assinatura é o GoTrue, e ele não está neste ensaio.

Essa fronteira é dita no laudo. Um ensaio que se apresentasse como
completo seria pior que nenhum: passaria a ser usado como se cobrisse
a rede.

Emulação do `auth`
------------------
`auth.uid()` e `auth.jwt()` são reproduzidos com a MESMA definição que
o Supabase usa: leitura de `request.jwt.claims`. Não é uma versão
simplificada — é a implementação, e é por isso que a 0020 roda aqui
sem nenhuma adaptação.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import uuid

RAIZ = pathlib.Path(__file__).resolve().parent.parent
MIGRACOES = RAIZ / "supabase/migrations"

# As quatro migrações de contenção/autorização são o objeto do ensaio,
# aplicadas NA ORDEM do runbook. As demais são o schema sobre o qual elas
# atuam.
#
# Elas já NÃO têm o sufixo `.NAO_APLICAR`: as três primeiras foram
# aplicadas em produção em 06/09/2026 e a 0021 no ambiente de ensaio.
# Continuam AQUI, e não entre as migrações de schema, porque a ORDEM
# entre elas é o que importa — a 0021 chama funções da 0020, a 0020
# depende do fechamento da 0019.
#
# Ensaiar a 0020 sozinha esconderia uma dependência real: é a 0019 que
# revoga o `EXECUTE ON FUNCTIONS FROM PUBLIC` default, e sem ela toda
# função criada pela 0020 — o gatilho da trilha inclusive — nasce
# executável por `anon`. O ensaio pegou isso na primeira execução.
SEQUENCIA_EM_ENSAIO = (
    "0018_rls_config_app_e_processos.sql",
    "0019_emergencial_fecha_anon.sql",
    "0020_definitiva_supabase_auth_rls.sql",
    # A 0021 entra na sequência, e não entre as migrações de schema,
    # porque DEPENDE da 0020: suas políticas chamam `tenant_do_jwt`,
    # `secretaria_do_jwt` e `e_admin`. Aplicada antes, nem seria
    # criada — e, se fosse, as tabelas de pesquisa de preços nasceriam
    # no mundo pré-0019, onde `anon` ainda tem grant amplo.
    # Destravada nesta rodada (o sufixo saiu), mas continua AQUI e
    # não entre as migrações de schema: a ordem importa mais que a
    # extensão do arquivo.
    "0021_pesquisa_precos.sql",
)


class EnsaioLocal(RuntimeError):
    """A preparação falhou. É erro, nunca skip."""


# ---------------------------------------------------------------------------
# Emulação do ambiente Supabase
#
# Papéis e schema `auth`. As definições de `auth.uid()`/`auth.jwt()` são
# as do Supabase: ler `request.jwt.claims`, que o PostgREST injeta na
# transação. É o que permite a 0020 rodar aqui SEM ADAPTAÇÃO — e uma
# migração que precisasse ser adaptada para o ensaio não estaria sendo
# ensaiada.
# ---------------------------------------------------------------------------
PREAMBULO = """
create extension if not exists pgcrypto;

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin noinherit bypassrls;
  end if;
  -- `supabase_admin` é dono de objetos no Supabase real, e a 0019
  -- ajusta `alter default privileges` PARA ELE além de para `postgres`.
  -- Sem o papel aqui, a 0019 falha — e falhar por papel ausente é
  -- justamente o tipo de coisa que só um ensaio EXECUTADO revela.
  if not exists (select 1 from pg_roles where rolname = 'supabase_admin') then
    create role supabase_admin nologin noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticator') then
    create role authenticator nologin noinherit;
  end if;
end $$;

grant anon, authenticated, service_role to authenticator;

grant usage on schema public to anon, authenticated, service_role;

create schema if not exists auth;
grant usage on schema auth to anon, authenticated, service_role;

-- `auth.users` de verdade tem muito mais colunas; aqui ficam as que a
-- 0020 referencia (a FK de `auth_user_id`) e o `raw_app_meta_data`,
-- que é onde papel/tenant/secretaria moram.
create table if not exists auth.users (
  id uuid primary key default gen_random_uuid(),
  email text unique,
  raw_app_meta_data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- DEFINIÇÃO DO SUPABASE, não uma simplificação.
create or replace function auth.uid() returns uuid
language sql stable as $fn$
  select coalesce(
    nullif(current_setting('request.jwt.claim.sub', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
  )::uuid
$fn$;

create or replace function auth.jwt() returns jsonb
language sql stable as $fn$
  select coalesce(
    nullif(current_setting('request.jwt.claim', true), ''),
    nullif(current_setting('request.jwt.claims', true), '')
  )::jsonb
$fn$;

create or replace function auth.role() returns text
language sql stable as $fn$
  select coalesce(
    nullif(current_setting('request.jwt.claim.role', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role')
  )
$fn$;

grant execute on function auth.uid(), auth.jwt(), auth.role()
  to anon, authenticated, service_role;

-- DEFAULT PRIVILEGES DO SUPABASE — a parte que faltava, e que fez o
-- ensaio ser MAIS FROUXO que a realidade.
--
-- O Supabase configura o schema `public` com `alter default privileges
-- ... grant all on tables to postgres, anon, authenticated,
-- service_role`. Sem isso aqui, toda tabela criada no ensaio nascia sem
-- grant nenhum, e uma migração que dependesse do revoke explícito
-- passava — enquanto no Supabase real a mesma tabela nascia com ALL
-- para `service_role`.
--
-- Foi assim que a 0021 chegou a ser aplicada no projeto de ensaio
-- afirmando "não há grant de DELETE para ninguém" e o `service_role`
-- tendo DELETE nas quatro tabelas. O ensaio precisa ser tão permissivo
-- quanto o ambiente que ele imita — senão ele prova o mundo errado.
--
-- ADENDO, medido no Supabase de produção em 06/09/2026: o
-- `pg_default_acl` do schema `public` lá tem DUAS entradas, e qual
-- delas vale depende de QUEM cria a tabela —
--
--   dono `supabase_admin`: `arwdDxtm` a postgres, anon, authenticated
--                          e service_role;
--   dono `postgres`      : `arwdDxtm` só a postgres e service_role.
--
-- As migrações rodam como `postgres`, então na prática vale a segunda,
-- mais estreita. O ensaio reproduz de propósito a PRIMEIRA, que é a
-- mais larga: assim ele acusa todo privilégio que a migração não
-- revogar explicitamente, em vez de depender da circunstância de ter
-- rodado com um dono e não com o outro. Ensaio pessimista gera revoke
-- a mais; ensaio otimista deixa buraco. Foi este ensaio, mais largo
-- que a realidade, que revelou o TRUNCATE de `service_role` que a
-- 0021 não revogava — e que produção de fato concedia.
alter default privileges in schema public
  grant all on tables to postgres, anon, authenticated, service_role;
alter default privileges in schema public
  grant all on functions to postgres, anon, authenticated, service_role;
alter default privileges in schema public
  grant all on sequences to postgres, anon, authenticated, service_role;
"""


def migracoes_do_schema() -> list[pathlib.Path]:
    """
    As `.sql` aplicáveis, em ordem. `.PENDENTE` e `.NAO_APLICAR` fora.

    E fora também o que já está em `SEQUENCIA_EM_ENSAIO`. Sem esta
    exclusão, uma migração que PERDE o sufixo `.NAO_APLICAR` — como a
    0021 ao ser destravada nesta rodada — passa a casar com o glob e é
    aplicada DUAS vezes: uma aqui, na ordem numérica, e outra na
    sequência. A primeira viria antes da 0020, cujas funções ela chama,
    e o ensaio quebraria com um erro que não tem nada a ver com o
    conteúdo da migração.

    A sequência é a autoridade sobre ordem; o glob cuida do resto.
    """
    em_sequencia = set(SEQUENCIA_EM_ENSAIO)
    return sorted(caminho for caminho
                  in MIGRACOES.glob("[0-9][0-9][0-9][0-9]_*.sql")
                  if caminho.name not in em_sequencia)


def sequencia_em_ensaio() -> list[pathlib.Path]:
    caminhos = []
    for nome in SEQUENCIA_EM_ENSAIO:
        caminho = MIGRACOES / nome
        if not caminho.exists():
            raise EnsaioLocal(f"migração em ensaio não encontrada: {caminho}")
        caminhos.append(caminho)
    return caminhos


# ---------------------------------------------------------------------------
# `.NAO_APLICAR` é para PRODUÇÃO
#
# A extensão existe para impedir que a migração seja aplicada por
# engano no banco real. Aplicá-la num cluster local descartável é o
# oposto disso: é o único jeito de saber se ela funciona antes que
# alguém a aplique de verdade.
#
# A guarda abaixo torna a distinção MECÂNICA, não uma promessa: o DSN
# precisa ser local, e a recusa é explícita.
# ---------------------------------------------------------------------------
_HOSPEDEIROS_LOCAIS = ("localhost", "127.0.0.1", "::1", "")


def exigir_dsn_local(dsn: str) -> str:
    """
    Recusa qualquer DSN que não seja de um cluster local.

    Sem isto, a mesma ferramenta que ensaia serviria para aplicar a
    0020 em produção com uma variável de ambiente trocada.
    """
    if "supabase" in dsn.lower() or "pooler" in dsn.lower():
        raise EnsaioLocal(
            "DSN aponta para Supabase. Este ensaio aplica migrações "
            "`.NAO_APLICAR` e só roda em cluster local descartável.")
    hospedeiro = ""
    achado = re.search(r"@([^/?:]*)", dsn)
    if achado:
        hospedeiro = achado.group(1)
    socket = re.search(r"host=(/[^&\s]*)", dsn)
    if not socket and hospedeiro not in _HOSPEDEIROS_LOCAIS:
        raise EnsaioLocal(
            f"DSN não é local: {hospedeiro!r}. Use socket unix ou "
            "localhost.")
    return dsn


def criar_banco_descartavel(dsn: str) -> tuple[str, str]:
    """
    Cria um banco NOVO para esta execução e devolve (dsn_novo, nome).

    Reaproveitar o banco entre execuções faz a segunda rodada morrer em
    `relation already exists` — e, pior, faz uma rodada herdar o estado
    da anterior. Um ensaio que depende de ter sido limpo à mão não é
    reprodutível.
    """
    import psycopg

    exigir_dsn_local(dsn)
    nome = f"ensaio_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(dsn, autocommit=True) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(f'create database "{nome}"')
    if "/" in dsn.split("?")[0].rsplit("@", 1)[-1]:
        base, _, resto = dsn.partition("?")
        base = base.rsplit("/", 1)[0] + "/" + nome
        novo = f"{base}?{resto}" if resto else base
    else:  # pragma: no cover — DSN sem nome de banco
        novo = dsn
    return novo, nome


def descartar_banco(dsn_admin: str, nome: str) -> None:
    """Some com o banco da execução. Falha aqui avisa e não derruba."""
    import psycopg

    try:
        with psycopg.connect(dsn_admin, autocommit=True) as conexao:
            with conexao.cursor() as cursor:
                cursor.execute(
                    "select pg_terminate_backend(pid) from pg_stat_activity "
                    "where datname = %s and pid <> pg_backend_pid()", (nome,))
                cursor.execute(f'drop database if exists "{nome}"')
    except Exception as erro:  # noqa: BLE001
        print(f"  (aviso) banco de ensaio remanescente {nome}: "
              f"{type(erro).__name__}")


def preparar(conexao) -> dict:
    """
    Levanta o schema inteiro e aplica a 0020. Devolve o relatório.

    Qualquer falha levanta — nunca devolve um banco pela metade, porque
    um ensaio sobre schema incompleto mede outra coisa.
    """
    relatorio = {"preambulo": False, "migracoes": [], "em_ensaio": []}
    with conexao.cursor() as cursor:
        cursor.execute(PREAMBULO)
        relatorio["preambulo"] = True

        for arquivo in migracoes_do_schema():
            try:
                cursor.execute(arquivo.read_text())
            except Exception as erro:  # noqa: BLE001
                raise EnsaioLocal(
                    f"{arquivo.name}: {type(erro).__name__}: {erro}") from erro
            relatorio["migracoes"].append(arquivo.name)

        for alvo in sequencia_em_ensaio():
            try:
                cursor.execute(alvo.read_text())
            except Exception as erro:  # noqa: BLE001
                raise EnsaioLocal(
                    f"{alvo.name}: {type(erro).__name__}: {erro}") from erro
            relatorio["em_ensaio"].append(alvo.name)
    conexao.commit()
    return relatorio


# ---------------------------------------------------------------------------
# Sessões: virar `authenticated` com um JWT injetado
#
# É o que o PostgREST faz a cada requisição: `set local role` para o
# papel do token e `set local request.jwt.claims` para o conteúdo dele.
# ---------------------------------------------------------------------------
def claims(sub: str, papel: str = "usuario", tenant: str | None = None,
           secretaria: str | None = None,
           papel_governanca: str | None = None) -> str:
    metadados: dict = {"papel": papel}
    if tenant:
        metadados["tenant_id"] = tenant
    if secretaria:
        metadados["secretaria_id"] = secretaria
    if papel_governanca:
        metadados["papel_governanca"] = papel_governanca
    return json.dumps({"sub": sub, "role": "authenticated",
                       "app_metadata": metadados})


def como(cursor, corpo_do_jwt: str, papel_do_banco: str = "authenticated"):
    """Assume a identidade dentro da transação corrente."""
    cursor.execute(f"set local role {papel_do_banco}")
    cursor.execute("select set_config('request.jwt.claims', %s, true)",
                   (corpo_do_jwt,))


def voltar_a_ser_servidor(cursor) -> None:
    cursor.execute("reset role")
    cursor.execute("select set_config('request.jwt.claims', '', true)")


def novo_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Vocabulário do veredito
#
# Três estados, os mesmos do ensaio remoto — e três, não dois, porque
# "não consegui" não é "foi negado". Um erro de schema, de sintaxe ou
# de tipo não mede autorização nenhuma; contá-lo como negação faz um
# banco quebrado parecer um banco contido.
#
# Vivia duplicado em `tests/test_ensaio_sql_local.py`. Com a Fase 3 da
# pesquisa de preços passaram a ser dois arquivos de prova usando o
# mesmo classificador, e duas cópias de um veredito de segurança são
# exatamente o tipo de coisa que diverge sem ninguém notar.
# ---------------------------------------------------------------------------
PERMITIDO = "PERMITIDO"
NEGADO = "NEGADO"
INCONCLUSIVO = "INCONCLUSIVO"

# `42501` é insufficient_privilege: a negação inequívoca. `42P17`
# (recursão de política) NÃO entra aqui — é defeito, não decisão.
SQLSTATE_DE_NEGACAO = "42501"


def classificar_sql(erro: Exception) -> str:
    """NEGADO só com `42501`. Todo o resto é INCONCLUSIVO."""
    if getattr(erro, "sqlstate", None) == SQLSTATE_DE_NEGACAO:
        return NEGADO
    return INCONCLUSIVO


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dsn", required=True,
                   help="DSN de um cluster PostgreSQL LOCAL e descartável")
    args = p.parse_args()

    import psycopg

    try:
        dsn = exigir_dsn_local(args.dsn)
    except EnsaioLocal as erro:
        print(f"RECUSADO — {erro}")
        return 2

    with psycopg.connect(dsn) as conexao:
        try:
            relatorio = preparar(conexao)
        except EnsaioLocal as erro:
            print(f"PREPARAÇÃO FALHOU — {erro}")
            return 1

    print(f"preâmbulo ................ {relatorio['preambulo']}")
    print(f"migrações do schema ...... {len(relatorio['migracoes'])}")
    for nome in relatorio["migracoes"]:
        print(f"    {nome}")
    print(f"migrações em ensaio ...... {len(relatorio['em_ensaio'])}")
    for nome in relatorio["em_ensaio"]:
        print(f"    {nome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
