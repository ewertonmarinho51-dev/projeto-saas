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
from ensaio_seguranca import SQL_DOS_OBJETOS_DE_ENSAIO  # noqa: E402

DSN_ADMIN_PADRAO = "postgresql://postgres@/postgres?host=/tmp/pgens"
BANCO_PADRAO = "homologacao"

# `authenticator` precisa ENTRAR: é o papel com que o PostgREST abre a
# conexão antes de trocar para `anon`/`authenticated`/`service_role`.
# No ensaio ele é `nologin`, porque lá ninguém se conecta como ele.
LOGIN_DO_AUTHENTICATOR = """
alter role authenticator login;
grant connect on database "{banco}" to authenticator;
"""


# ---------------------------------------------------------------------------
# AS FLAGS QUE PRODUÇÃO TEM — medidas, não supostas
#
# Lidas de `config_app` do projeto de produção em 24/09/2026 (somente
# SELECT; nenhuma linha foi escrita lá). Todas valiam "1".
#
# Sem espelhá-las, a homologação subia com TUDO desligado e a auditoria
# testaria um sistema que ninguém usa: sem Mapa de Riscos no fluxo, sem
# GovBot, sem editor rico, sem consolidação de demandas. O §2 manda
# identificar o que está efetivamente implantado; testar outra
# configuração produz um laudo sobre um programa que não existe.
#
# A lista é EXPLÍCITA e datada de propósito. Ligar "tudo que houver"
# faria a homologação divergir de produção no dia em que alguém
# acrescentasse uma flag nova — e a divergência não apareceria em
# lugar nenhum.
FLAGS_ESPELHADAS_DE_PRODUCAO = (
    "flag_achados_estruturados", "flag_canonical_facts",
    "flag_clause_catalog_admin", "flag_confidence_emission_gate",
    "flag_confidence_score_shadow", "flag_correcao_automatica",
    "flag_corretor_shadow", "flag_demand_consolidation",
    "flag_editor_rico", "flag_explanations", "flag_gate_emissao",
    "flag_govbot", "flag_govbot_alertas", "flag_governance_center",
    "flag_governance_publication_gate", "flag_improvement_laboratory",
    "flag_institutional_learning_capture",
    "flag_institutional_learning_publish", "flag_knowledge_engine_active",
    "flag_knowledge_engine_shadow", "flag_legal_opinion_batch_processing",
    "flag_legal_opinion_correction", "flag_legal_opinion_ingestion",
    "flag_loading_overlay", "flag_mapa_riscos",
    "flag_model_family_resolution_active",
    "flag_model_family_resolution_shadow", "flag_multi_prefeituras",
    "flag_onboarding_assistant", "flag_price_research",
    "flag_process_consistency", "flag_reauditoria", "flag_secretarias",
    "flag_tela_progresso", "flag_template_builder",
    "flag_tenant_inheritance_admin", "flag_visual_policy_builder",
)


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

            # Os objetos descartáveis do ensaio de contenção, na ordem
            # que é o próprio teste: criados DEPOIS das migrações, eles
            # nascem sob os default privileges já revogados. Criados
            # antes, provariam o mundo anterior.
            #
            # Sem eles, 114 provas de `tests/test_seguranca_contencao.py`
            # não rodam — e são justamente as que exercitam a autorização
            # ATRAVÉS do PostgREST, camada que o ensaio SQL local
            # declaradamente não cobre.
            cursor.execute(SQL_DOS_OBJETOS_DE_ENSAIO)

            cursor.executemany(
                "insert into public.config_app (chave, valor) values (%s, '1') "
                "on conflict (chave) do update set valor = excluded.valor",
                [(chave,) for chave in FLAGS_ESPELHADAS_DE_PRODUCAO])
        conexao.commit()

    relatorio["migracoes"] = aplicadas
    relatorio["objetos_de_ensaio"] = True
    relatorio["flags"] = len(FLAGS_ESPELHADAS_DE_PRODUCAO)
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
                "select tablename from pg_tables where schemaname = 'public' "
                "and not rowsecurity order by tablename")
            sem_rls = [linha[0] for linha in cursor.fetchall()]
            cursor.execute(
                "select count(*) from pg_policies where schemaname = 'public'")
            (politicas,) = cursor.fetchone()
            cursor.execute(
                "select table_name from information_schema.tables "
                "where table_schema = 'public' order by table_name")
            tabelas = [linha[0] for linha in cursor.fetchall()]
    return {"tabelas": total, "com_rls": com_rls, "sem_rls": sem_rls,
            "politicas": politicas, "nomes": tabelas}


# `ensaio_objeto_novo` nasce SEM RLS e SEM grant de propósito: é o
# canário que prova que os default privileges foram revogados. Se `anon`
# conseguir lê-la, o problema está nos defaults, não nela. Listá-la como
# achado faria o relatório gritar exatamente onde não há nada errado — e
# um alarme que sempre toca é um alarme que ninguém lê.
TABELAS_SEM_RLS_POR_DESENHO = frozenset({"ensaio_objeto_novo"})


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
    inesperadas = [t for t in foto["sem_rls"]
                   if t not in TABELAS_SEM_RLS_POR_DESENHO]
    print(f"  tabelas: {foto['tabelas']}  com RLS: {foto['com_rls']}  "
          f"sem RLS: {len(foto['sem_rls'])}  políticas: {foto['politicas']}")
    if foto["sem_rls"]:
        print(f"  sem RLS por desenho (canário do ensaio): "
              f"{', '.join(sorted(set(foto['sem_rls']) - set(inesperadas)))}")
    if inesperadas:
        print(f"  ATENÇÃO: tabela sem RLS e sem explicação: "
              f"{', '.join(inesperadas)} — confira antes de confiar no "
              "teste de isolamento (§17).")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
