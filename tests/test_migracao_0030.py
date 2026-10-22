"""
A 0030 aplicada de verdade, num PostgreSQL descartável.

O que se mede é o CATÁLOGO e o COMPORTAMENTO: a chave de idempotência é
única por município e só por município, NULL não colide (as linhas do
Streamlit), o formato inválido é recusado, nenhum privilégio mudou, e a
conferência da própria migração reprova quando o índice falta — a prova
de que o bloco `do $$` morde em vez de enfeitar.

Cada prova que escreve roda dentro de transação desfeita no fim: o banco
da fixture é compartilhado pelo módulo.
"""

from __future__ import annotations

import pathlib
import uuid

import pytest

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0030_api_idempotencia_processos.sql")


class _Desfaz(Exception):
    pass


@pytest.fixture(scope="module")
def banco_com_0030(banco):
    # A fixture `banco` já aplicou (está em SEQUENCIA_EM_ENSAIO). Aplicar
    # de novo é a prova de idempotência, antes de qualquer outra.
    with banco.cursor() as cursor:
        cursor.execute(MIGRACAO.read_text(encoding="utf-8"))
    return banco


def _em_transacao_desfeita(conexao, corpo):
    import psycopg

    with pytest.raises(_Desfaz):
        with conexao.transaction():
            with conexao.cursor() as cursor:
                corpo(cursor, psycopg)
            raise _Desfaz


def _tenant(cursor) -> str:
    cursor.execute("insert into public.tenants (slug, nome) values (%s, 'Ensaio 0030') "
                   "returning id", ("ensaio-0030-" + uuid.uuid4().hex,))
    return str(cursor.fetchone()[0])


def _processo(cursor, tenant, chave):
    cursor.execute("insert into public.processos (tenant_id, orgao, objeto, dados, "
                   "idempotency_key) values (%s, 'o', 'x', '{}', %s) returning id",
                   (tenant, chave))
    return cursor.fetchone()[0]


def test_reaplicar_e_inofensivo(banco_com_0030):
    with banco_com_0030.cursor() as cursor:
        cursor.execute(MIGRACAO.read_text(encoding="utf-8"))


def test_mesma_chave_no_mesmo_municipio_colide(banco_com_0030):
    def corpo(cursor, psycopg):
        a = _tenant(cursor)
        _processo(cursor, a, "chave-repetida-01")
        with pytest.raises(psycopg.errors.UniqueViolation):
            with banco_com_0030.transaction():
                _processo(cursor, a, "chave-repetida-01")
    _em_transacao_desfeita(banco_com_0030, corpo)


def test_mesma_chave_em_municipios_diferentes_nao_colide(banco_com_0030):
    def corpo(cursor, psycopg):
        _processo(cursor, _tenant(cursor), "chave-compartilhada")
        _processo(cursor, _tenant(cursor), "chave-compartilhada")
    _em_transacao_desfeita(banco_com_0030, corpo)


def test_processos_sem_chave_nao_colidem(banco_com_0030):
    # As linhas do Streamlit nascem com NULL — várias, no mesmo tenant.
    def corpo(cursor, psycopg):
        a = _tenant(cursor)
        _processo(cursor, a, None)
        _processo(cursor, a, None)
    _em_transacao_desfeita(banco_com_0030, corpo)


@pytest.mark.parametrize("chave", ["curta", "tem espaco no meio",
                                   "x" * 129, "acento-ção-01"])
def test_formato_invalido_e_recusado(banco_com_0030, chave):
    def corpo(cursor, psycopg):
        with pytest.raises(psycopg.errors.CheckViolation):
            with banco_com_0030.transaction():
                _processo(cursor, _tenant(cursor), chave)
    _em_transacao_desfeita(banco_com_0030, corpo)


def test_privilegios_de_rede_continuam_os_mesmos(banco_com_0030):
    with banco_com_0030.cursor() as cursor:
        cursor.execute(
            "select grantee, string_agg(privilege_type, ',' order by privilege_type) "
            "from information_schema.role_table_grants where table_schema='public' "
            "and table_name='processos' and grantee in ('anon','authenticated') "
            "group by grantee")
        assert dict(cursor.fetchall()) == {"authenticated": "INSERT,SELECT,UPDATE"}


def test_a_conferencia_morde_sem_o_indice(banco_com_0030):
    # Mutação: some o índice; o bloco de conferência, sozinho, tem de
    # levantar. Sem isto a conferência poderia estar só decorando.
    texto = MIGRACAO.read_text(encoding="utf-8")
    conferencia = texto[texto.index("do $$"):]

    def corpo(cursor, psycopg):
        cursor.execute("drop index public.processos_tenant_idempotency_uidx")
        with pytest.raises(psycopg.errors.RaiseException, match="indice_unico_parcial"):
            with banco_com_0030.transaction():
                cursor.execute(conferencia)
    _em_transacao_desfeita(banco_com_0030, corpo)
