#!/usr/bin/env python3
"""
Banco de HOMOLOGAÇÃO local: o schema real, num cluster descartável.

    python scripts/homologacao_local.py --recriar

POR QUE ISTO EXISTE, E POR QUE NÃO É O `ensaio_local.py`

`ensaio_local.py` cria um banco NOVO a cada execução e o descarta no
fim. É o certo para uma prova de RLS: nenhuma rodada herda o estado da
anterior.

Uma bateria de navegação precisa do oposto. O §5 da auditoria manda
salvar um processo, recarregar a página, sair e REABRIR o processo
salvo. Isso exige um banco que sobreviva ao fim do comando — e que o
PostgREST possa servir por minutos, não por uma transação.

Este módulo reaproveita a preparação do ensaio (PREÂMBULO, ordem das
migrações, emulação de `auth`) e muda só o ciclo de vida: banco
NOMEADO, persistente, recriável sob pedido.

O QUE ESTE AMBIENTE É — E O QUE ELE NÃO É

  É   : PostgreSQL de verdade, com as migrações do repositório, RLS
        ligado, e PostgREST de verdade na frente. O `db.py` fala HTTP
        com ele exatamente como fala com o Supabase.
  NÃO É: GoTrue. Não há emissão nem validação de JWT de usuário por um
        servidor de identidade. O `autenticar_no_supabase` não encontra
        ninguém e o app cai no caminho legado da tabela `usuarios` —
        que é, hoje, o caminho de produção para quem ainda não migrou.

Essa fronteira vai no laudo. Um ambiente que se apresentasse como
Supabase completo seria pior que nenhum: passaria a ser citado como se
cobrisse a identidade.

NENHUMA CREDENCIAL REAL ENTRA AQUI

O segredo de JWT é gerado na hora, fica fora do repositório e morre com
o ambiente. Não há chave de produção, de projeto Supabase ou de
provedor de LLM em lugar nenhum deste caminho.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from ensaio_local import (  # noqa: E402
    PREAMBULO,
    EnsaioLocal,
    exigir_dsn_local,
    migracoes_do_schema,
    sequencia_em_ensaio,
)

DSN_ADMIN_PADRAO = "postgresql://postgres@/postgres?host=/tmp/pgens"
BANCO_PADRAO = "homologacao"

# `authenticator` precisa ENTRAR: é o papel com que o PostgREST abre a
# conexão antes de trocar para `anon`/`authenticated`/`service_role`.
# No ensaio ele é `nologin`, porque lá ninguém se conecta como ele.
LOGIN_DO_AUTHENTICATOR = """
alter role authenticator login;
grant connect on database "{banco}" to authenticator;
"""


def _dsn_do_banco(dsn_admin: str, banco: str) -> str:
    base, _, resto = dsn_admin.partition("?")
    base = base.rsplit("/", 1)[0] + "/" + banco
    return f"{base}?{resto}" if resto else base


def _existe(dsn_admin: str, banco: str) -> bool:
    import psycopg

    with psycopg.connect(dsn_admin, autocommit=True) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute("select 1 from pg_database where datname = %s",
                           (banco,))
            return cursor.fetchone() is not None


def _derrubar(dsn_admin: str, banco: str) -> None:
    import psycopg

    with psycopg.connect(dsn_admin, autocommit=True) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                "select pg_terminate_backend(pid) from pg_stat_activity "
                "where datname = %s and pid <> pg_backend_pid()", (banco,))
            cursor.execute(f'drop database if exists "{banco}"')


def _criar(dsn_admin: str, banco: str) -> None:
    import psycopg

    with psycopg.connect(dsn_admin, autocommit=True) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(f'create database "{banco}"')


def montar(dsn_admin: str = DSN_ADMIN_PADRAO, banco: str = BANCO_PADRAO,
           recriar: bool = False) -> dict:
    """
    Deixa o banco de homologação pronto. Devolve o relatório.

    Idempotente quando `recriar` é falso: se o banco já existe, nada é
    aplicado de novo — reaplicar as migrações sobre um schema pronto
    quebraria em `already exists` e, pior, apagaria o estado que a
    bateria de navegação está usando.
    """
    import psycopg

    exigir_dsn_local(dsn_admin)
    relatorio: dict = {"banco": banco, "recriado": False, "reaproveitado": False}

    if recriar and _existe(dsn_admin, banco):
        _derrubar(dsn_admin, banco)

    if _existe(dsn_admin, banco):
        relatorio["reaproveitado"] = True
        relatorio["dsn"] = _dsn_do_banco(dsn_admin, banco)
        return relatorio

    _criar(dsn_admin, banco)
    relatorio["recriado"] = True
    dsn = _dsn_do_banco(dsn_admin, banco)
    relatorio["dsn"] = dsn

    aplicadas: list[str] = []
    with psycopg.connect(dsn) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(PREAMBULO)
            cursor.execute(LOGIN_DO_AUTHENTICATOR.format(banco=banco))
            for arquivo in list(migracoes_do_schema()) + list(
                    sequencia_em_ensaio()):
                try:
                    cursor.execute(arquivo.read_text())
                except Exception as erro:  # noqa: BLE001
                    raise EnsaioLocal(
                        f"{arquivo.name}: {type(erro).__name__}: {erro}"
                    ) from erro
                aplicadas.append(arquivo.name)
        conexao.commit()

    relatorio["migracoes"] = aplicadas
    return relatorio


def conferir(dsn: str) -> dict:
    """Fotografia do banco pronto — o que o laudo cita como evidência."""
    import psycopg

    with psycopg.connect(dsn) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                "select count(*), count(*) filter (where rowsecurity) "
                "from pg_tables where schemaname = 'public'")
            total, com_rls = cursor.fetchone()
            cursor.execute(
                "select count(*) from pg_policies where schemaname = 'public'")
            (politicas,) = cursor.fetchone()
            cursor.execute(
                "select table_name from information_schema.tables "
                "where table_schema = 'public' order by table_name")
            tabelas = [linha[0] for linha in cursor.fetchall()]
    return {"tabelas": total, "com_rls": com_rls, "sem_rls": total - com_rls,
            "politicas": politicas, "nomes": tabelas}


def principal(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--dsn", default=DSN_ADMIN_PADRAO)
    analisador.add_argument("--banco", default=BANCO_PADRAO)
    analisador.add_argument("--recriar", action="store_true")
    argumentos = analisador.parse_args(argv)

    relatorio = montar(argumentos.dsn, argumentos.banco, argumentos.recriar)
    estado = ("reaproveitado" if relatorio["reaproveitado"]
              else f"criado com {len(relatorio['migracoes'])} migrações")
    print(f"banco de homologação {relatorio['banco']}: {estado}")

    foto = conferir(relatorio["dsn"])
    print(f"  tabelas: {foto['tabelas']}  com RLS: {foto['com_rls']}  "
          f"sem RLS: {foto['sem_rls']}  políticas: {foto['politicas']}")
    if foto["sem_rls"]:
        print("  ATENÇÃO: há tabela sem RLS — confira antes de confiar no "
              "teste de isolamento (§17).")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
