"""
A 0032 (job de relatório) aplicada de verdade, num PostgreSQL descartável.

Alarga a 0031 sem afrouxar nada: o tipo `relatorio_precos` passa, um
tipo desconhecido continua recusado, `resultado` nasce `{}` e não aceita
não-objeto nem texto gigante, o dono grava o próprio resultado e o colega
do município continua sem ver o job — e a conferência morde quando a
CHECK nova some.
"""

from __future__ import annotations

import json
import pathlib
import uuid

import pytest

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0032_api_jobs_relatorio.sql")


class _Desfaz(Exception):
    pass


@pytest.fixture(scope="module")
def banco_com_0032(banco):
    with banco.cursor() as cursor:
        cursor.execute(MIGRACAO.read_text(encoding="utf-8"))   # idempotência
    return banco


def _transacao(conexao, corpo):
    import psycopg

    with pytest.raises(_Desfaz):
        with conexao.transaction():
            with conexao.cursor() as cursor:
                corpo(cursor, psycopg)
            raise _Desfaz


def _cenario(cursor):
    tenant = str(cursor.execute(
        "insert into public.tenants (slug, nome) values (%s, 'Ensaio 0032') returning id",
        ("ensaio-0032-" + uuid.uuid4().hex,)).fetchone()[0])
    dono, outro = str(uuid.uuid4()), str(uuid.uuid4())
    for uid in (dono, outro):
        cursor.execute("insert into auth.users (id) values (%s)", (uid,))
    return tenant, dono, outro


def _como(cursor, sub, tenant):
    cursor.execute("set local role authenticated")
    cursor.execute("select set_config('request.jwt.claims', %s, true)",
                   (json.dumps({"sub": sub, "role": "authenticated",
                                "app_metadata": {"tenant_id": tenant, "papel": "usuario"}}),))


def _inserir(cursor, tenant, dono, tipo="relatorio_precos"):
    return cursor.execute(
        "insert into public.api_jobs (tenant_id, auth_user_id, tipo, recurso_id, "
        "idempotency_key) values (%s,%s,%s,%s,%s) returning id",
        (tenant, dono, tipo, str(uuid.uuid4()), "chave-" + uuid.uuid4().hex)).fetchone()[0]


_SQL = "\n".join(linha for linha in MIGRACAO.read_text(encoding="utf-8").splitlines()
                 if not linha.strip().startswith("--"))


@pytest.mark.parametrize("proibido", [
    r"\bdrop\s+table\b", r"\bdrop\s+column\b", r"^\s*truncate\b",
    r"disable\s+row\s+level\s+security", r"\bdelete\s+from\b",
    r"\bdrop\s+policy\b", r"\bgrant\b", r"\bcreate\s+policy\b",
])
def test_e_aditiva_e_nao_mexe_em_autorizacao(proibido):
    """Sem tabela ou coluna removida, e nenhuma política ou grant tocado:
    a autorização da 0031 vale inteira para o tipo novo."""
    import re

    assert not re.search(proibido, _SQL, re.IGNORECASE | re.MULTILINE), proibido


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0032 não cumpriu o que afirma" in _SQL
    assert _SQL.rstrip().endswith("$$;")


def test_reaplicar_e_inofensivo(banco_com_0032):
    with banco_com_0032.cursor() as cursor:
        cursor.execute(MIGRACAO.read_text(encoding="utf-8"))


def test_dono_cria_job_de_relatorio_e_grava_o_resultado(banco_com_0032):
    def corpo(cursor, psycopg):
        tenant, dono, _ = _cenario(cursor)
        _como(cursor, dono, tenant)
        job = _inserir(cursor, tenant, dono)
        assert cursor.execute("select resultado from public.api_jobs where id=%s",
                              (job,)).fetchone() == ({},)
        cursor.execute("update public.api_jobs set estado='succeeded', resultado=%s "
                       "where id=%s", (json.dumps({"nome": "r.docx", "tamanho": 10}), job))
        assert cursor.rowcount == 1
    _transacao(banco_com_0032, corpo)


def test_coleta_continua_valendo(banco_com_0032):
    def corpo(cursor, psycopg):
        tenant, dono, _ = _cenario(cursor)
        _como(cursor, dono, tenant)
        _inserir(cursor, tenant, dono, tipo="coleta_precos")
    _transacao(banco_com_0032, corpo)


def test_tipo_desconhecido_continua_recusado(banco_com_0032):
    def corpo(cursor, psycopg):
        tenant, dono, _ = _cenario(cursor)
        with pytest.raises(psycopg.errors.CheckViolation):
            with banco_com_0032.transaction():
                _inserir(cursor, tenant, dono, tipo="exportacao_qualquer")
    _transacao(banco_com_0032, corpo)


@pytest.mark.parametrize("valor", ['[]', '"texto"', json.dumps({"x": "a" * 5000})])
def test_resultado_so_objeto_pequeno(banco_com_0032, valor):
    def corpo(cursor, psycopg):
        tenant, dono, _ = _cenario(cursor)
        job = _inserir(cursor, tenant, dono)
        with pytest.raises(psycopg.errors.CheckViolation):
            with banco_com_0032.transaction():
                cursor.execute("update public.api_jobs set resultado=%s::jsonb where id=%s",
                               (valor, job))
    _transacao(banco_com_0032, corpo)


def test_colega_do_municipio_nao_ve_o_job_de_relatorio(banco_com_0032):
    def corpo(cursor, psycopg):
        tenant, dono, outro = _cenario(cursor)
        job = _inserir(cursor, tenant, dono)
        _como(cursor, outro, tenant)
        assert cursor.execute("select count(*) from public.api_jobs where id=%s",
                              (job,)).fetchone() == (0,)
        cursor.execute("update public.api_jobs set resultado='{}' where id=%s", (job,))
        assert cursor.rowcount == 0
    _transacao(banco_com_0032, corpo)


def test_a_conferencia_morde_sem_a_check_nova(banco_com_0032):
    texto = MIGRACAO.read_text(encoding="utf-8")
    conferencia = texto[texto.index("do $$"):]

    def corpo(cursor, psycopg):
        cursor.execute("alter table public.api_jobs drop constraint api_jobs_tipo_check")
        cursor.execute("alter table public.api_jobs add constraint api_jobs_tipo_check "
                       "check (tipo in ('coleta_precos'))")
        with pytest.raises(psycopg.errors.RaiseException, match="tipo_relatorio"):
            with banco_com_0032.transaction():
                cursor.execute(conferencia)
    _transacao(banco_com_0032, corpo)
