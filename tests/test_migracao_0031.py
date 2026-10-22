"""
A 0031 (jobs da API) aplicada de verdade, num PostgreSQL descartável.

Catálogo e comportamento: RLS ligada e forçada; o dono lê e atualiza o
próprio job, ninguém mais (nem o colega do mesmo município); job nasce
`queued`; chave de idempotência única por município; estado fora do
vocabulário recusado; servidor sem DELETE/TRUNCATE; e a conferência da
própria migração morde quando uma política some.
"""

from __future__ import annotations

import pathlib
import uuid

import pytest

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0031_api_jobs.sql")


class _Desfaz(Exception):
    pass


@pytest.fixture(scope="module")
def banco_com_0031(banco):
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
    """Um município, dois usuários do Auth (fixture do ensaio)."""
    tenant = str(cursor.execute(
        "insert into public.tenants (slug, nome) values (%s, 'Ensaio 0031') returning id",
        ("ensaio-0031-" + uuid.uuid4().hex,)).fetchone()[0])
    dono, outro = str(uuid.uuid4()), str(uuid.uuid4())
    for uid in (dono, outro):
        cursor.execute("insert into auth.users (id) values (%s)", (uid,))
    return tenant, dono, outro


def _como(cursor, sub, tenant):
    import json

    cursor.execute("set local role authenticated")
    cursor.execute("select set_config('request.jwt.claims', %s, true)",
                   (json.dumps({"sub": sub, "role": "authenticated",
                                "app_metadata": {"tenant_id": tenant, "papel": "usuario"}}),))


def _inserir(cursor, tenant, dono, chave="chave-job-0001", estado="queued"):
    return cursor.execute(
        "insert into public.api_jobs (tenant_id, auth_user_id, tipo, recurso_id, "
        "idempotency_key, estado) values (%s,%s,'coleta_precos',%s,%s,%s) returning id",
        (tenant, dono, str(uuid.uuid4()), chave, estado)).fetchone()[0]


def test_reaplicar_e_inofensivo(banco_com_0031):
    with banco_com_0031.cursor() as cursor:
        cursor.execute(MIGRACAO.read_text(encoding="utf-8"))


def test_dono_cria_le_e_atualiza_o_proprio_job(banco_com_0031):
    def corpo(cursor, psycopg):
        tenant, dono, _ = _cenario(cursor)
        _como(cursor, dono, tenant)
        job = _inserir(cursor, tenant, dono)
        cursor.execute("update public.api_jobs set estado='running', feitos=1, total=3 "
                       "where id=%s", (job,))
        assert cursor.rowcount == 1
        assert cursor.execute("select estado from public.api_jobs where id=%s",
                              (job,)).fetchone() == ("running",)
    _transacao(banco_com_0031, corpo)


def test_outro_usuario_do_mesmo_municipio_nao_ve_nem_altera(banco_com_0031):
    def corpo(cursor, psycopg):
        tenant, dono, outro = _cenario(cursor)
        job = _inserir(cursor, tenant, dono)          # como servidor
        _como(cursor, outro, tenant)
        assert cursor.execute("select count(*) from public.api_jobs where id=%s",
                              (job,)).fetchone() == (0,)
        cursor.execute("update public.api_jobs set estado='cancelled' where id=%s", (job,))
        assert cursor.rowcount == 0
    _transacao(banco_com_0031, corpo)


def test_job_nao_nasce_concluido(banco_com_0031):
    def corpo(cursor, psycopg):
        tenant, dono, _ = _cenario(cursor)
        _como(cursor, dono, tenant)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with banco_com_0031.transaction():
                _inserir(cursor, tenant, dono, estado="succeeded")
    _transacao(banco_com_0031, corpo)


def test_nao_cria_job_em_nome_de_outro(banco_com_0031):
    def corpo(cursor, psycopg):
        tenant, dono, outro = _cenario(cursor)
        _como(cursor, outro, tenant)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with banco_com_0031.transaction():
                _inserir(cursor, tenant, dono)
    _transacao(banco_com_0031, corpo)


def test_mesma_chave_no_mesmo_municipio_colide(banco_com_0031):
    def corpo(cursor, psycopg):
        tenant, dono, _ = _cenario(cursor)
        _inserir(cursor, tenant, dono, chave="repetida-0001")
        with pytest.raises(psycopg.errors.UniqueViolation):
            with banco_com_0031.transaction():
                _inserir(cursor, tenant, dono, chave="repetida-0001")
    _transacao(banco_com_0031, corpo)


def test_estado_fora_do_vocabulario_e_recusado(banco_com_0031):
    def corpo(cursor, psycopg):
        tenant, dono, _ = _cenario(cursor)
        with pytest.raises(psycopg.errors.CheckViolation):
            with banco_com_0031.transaction():
                _inserir(cursor, tenant, dono, estado="pausado")
    _transacao(banco_com_0031, corpo)


def test_privilegios(banco_com_0031):
    with banco_com_0031.cursor() as cursor:
        cursor.execute(
            "select grantee, string_agg(privilege_type, ',' order by privilege_type) "
            "from information_schema.role_table_grants where table_schema='public' "
            "and table_name='api_jobs' and grantee in ('anon','authenticated','service_role') "
            "group by grantee")
        grants = dict(cursor.fetchall())
    assert "anon" not in grants
    assert grants["authenticated"] == "INSERT,SELECT,UPDATE"
    assert "DELETE" not in grants.get("service_role", "")
    assert "TRUNCATE" not in grants.get("service_role", "")


def test_a_conferencia_morde_sem_uma_politica(banco_com_0031):
    texto = MIGRACAO.read_text(encoding="utf-8")
    conferencia = texto[texto.index("do $$"):]

    def corpo(cursor, psycopg):
        cursor.execute('drop policy "api_jobs_edita" on public.api_jobs')
        with pytest.raises(psycopg.errors.RaiseException, match="tres_politicas"):
            with banco_com_0031.transaction():
                cursor.execute(conferencia)
    _transacao(banco_com_0031, corpo)
