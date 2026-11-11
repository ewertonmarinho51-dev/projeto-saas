"""
A 0043 (busca do PNCP por termo) aplicada de verdade, num PostgreSQL
descartável.

O que ela promete: a tabela de termos é só do servidor (nem `anon` nem
`authenticated` a alcançam, e o servidor não apaga); a contratação aceita o
estado `parcial` sem perder os da 0042; e a conferência morde quando uma
dessas garantias some.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import claims, como, voltar_a_ser_servidor  # noqa: E402

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0043_precos_pncp_termos.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))

requer_pg = pytest.mark.usefixtures("ensaio_sql")


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def test_cabecalho_diz_o_estado():
    assert TEXTO.startswith("-- ## 0043 —")
    assert "ESTADO: APLICADA EM PRODUÇÃO em 11/11/2026 (registro 20261111124057" in TEXTO
    assert "O QUE ESTA MIGRAÇÃO NÃO RESOLVE" in TEXTO


def test_tabela_nasce_fechada_e_so_do_servidor():
    assert re.search(r"alter table public\.precos_pncp_termos enable row level security", SQL)
    assert "revoke all on public.precos_pncp_termos from anon, authenticated, public" in SQL
    assert ("revoke truncate, references, trigger on public.precos_pncp_termos "
            "from service_role") in SQL
    assert "revoke maintain on public.precos_pncp_termos from service_role" in SQL
    concessoes = re.findall(r"^\s*grant\s+(.+?);", SQL, re.IGNORECASE | re.MULTILINE)
    # DELETE de propósito: fila de trabalho, não trilha (revisão de 11/11/2026)
    assert concessoes == [
        "select, insert, update, delete on public.precos_pncp_termos to service_role"]


@pytest.mark.parametrize("proibido", [
    r"\bto\s+anon\b", r"\bto\s+authenticated\b", r"\bto\s+public\b", r"create\s+policy",
    r"default\s+privileges", r"\bsecurity\s+definer\b", r"disable\s+row\s+level\s+security",
    r"\btenant_id\b", r"grant\s+[^;]*\btruncate\b", r"\bdrop\s+table\b",
])
def test_nao_abre_o_que_nao_deve(proibido):
    assert not re.search(proibido, SQL, re.IGNORECASE), proibido


def test_estado_parcial_sem_perder_os_anteriores():
    restricao = SQL[SQL.index("add constraint precos_pncp_contratacoes_estado_check"):]
    restricao = restricao[:restricao.index(";")]
    for estado in ("pendente", "coletada", "sem_resultado", "fora_do_piloto", "falha",
                   "parcial"):
        assert f"'{estado}'" in restricao
    # o código usa o mesmo nome
    from src.precos import pncp_indice

    assert pncp_indice.PARCIAL == "parcial"


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0043 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")
    assert "notify pgrst, 'reload schema'" in SQL


def test_esta_na_sequencia_do_ensaio_depois_da_0042():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert SEQUENCIA_EM_ENSAIO.index("0043_precos_pncp_termos.sql") == \
        SEQUENCIA_EM_ENSAIO.index("0042_precos_pncp_indice.sql") + 1
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
USUARIO = claims("u-a", papel="usuario")


@pytest.fixture(scope="module")
def cenario(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência: reaplicar não muda nada
        c.execute("insert into public.precos_pncp_termos (nucleo) values "
                  "('analisador bioquimico') on conflict do nothing")
        voltar_a_ser_servidor(c)
    banco.commit()
    return {}


def _como(banco, sql, parametros=(), papel="authenticated", jwt=USUARIO):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, jwt, papel)
        try:
            c.execute(sql, parametros)
            return None, (c.fetchall() if c.description else [])
        except Exception as erro:  # noqa: BLE001
            return getattr(erro, "sqlstate", "erro"), []


@requer_pg
@pytest.mark.parametrize("papel,jwt", [("authenticated", USUARIO), ("anon", "{}")])
@pytest.mark.parametrize("sql", [
    "select * from public.precos_pncp_termos",
    "insert into public.precos_pncp_termos (nucleo) values ('cimento')",
    "update public.precos_pncp_termos set falhas = 1",
    "delete from public.precos_pncp_termos",
])
def test_usuario_nao_alcanca_os_termos(banco, cenario, papel, jwt, sql):
    assert _como(banco, sql, papel=papel, jwt=jwt)[0] == "42501"


@requer_pg
def test_servidor_le_escreve_e_apaga_termo_mas_nao_trunca(banco, cenario):
    erro, linhas = _como(banco, "select nucleo from public.precos_pncp_termos",
                         papel="service_role", jwt="{}")
    assert erro is None and ("analisador bioquimico",) in linhas
    assert _como(banco, "update public.precos_pncp_termos set falhas = falhas + 1",
                 papel="service_role", jwt="{}")[0] is None
    assert _como(banco, "delete from public.precos_pncp_termos where nucleo = 'x'",
                 papel="service_role", jwt="{}")[0] is None
    assert _como(banco, "truncate public.precos_pncp_termos",
                 papel="service_role", jwt="{}")[0] == "42501"


@requer_pg
@pytest.mark.parametrize("nucleo", ["ab", "x" * 121])
def test_nucleo_tem_tamanho_limitado(banco, cenario, nucleo):
    assert _como(banco, "insert into public.precos_pncp_termos (nucleo) values (%s)",
                 (nucleo,), papel="service_role", jwt="{}")[0] == "23514"


@requer_pg
@pytest.mark.parametrize("estado,aceito", [("parcial", True), ("coletada", True),
                                           ("qualquer", False)])
def test_contratacao_aceita_parcial(banco, cenario, estado, aceito):
    erro, _ = _como(banco, "insert into public.precos_pncp_contratacoes "
                    "(numero_controle, estado) values ('x-1-000001/2026', %s)", (estado,),
                    papel="service_role", jwt="{}")
    assert (erro is None) is aceito


MUTACOES = [
    ("alter table public.precos_pncp_termos disable row level security", "rls_desligado"),
    ("grant select on public.precos_pncp_termos to anon", "anon_alcanca"),
    ("grant select (nucleo) on public.precos_pncp_termos to authenticated",
     "authenticated_alcanca"),
    ("grant truncate on public.precos_pncp_termos to service_role", "service_role_trunca_ou_amarra"),
    ("grant trigger on public.precos_pncp_termos to service_role", "service_role_trunca_ou_amarra"),
    ("revoke delete on public.precos_pncp_termos from service_role", "service_role_sem_escrita"),
    ("revoke update on public.precos_pncp_termos from service_role", "service_role_sem_escrita"),
    ("create policy p on public.precos_pncp_termos for select to authenticated using (true)",
     "politica_inesperada"),
    ("alter table public.precos_pncp_contratacoes drop constraint "
     "precos_pncp_contratacoes_estado_check", "estado_parcial_ausente"),
]


@requer_pg
@pytest.mark.parametrize("mutacao,denuncia", MUTACOES)
def test_a_conferencia_morde(banco, cenario, mutacao, denuncia):
    import psycopg

    conferencia = TEXTO[TEXTO.rindex("do $$"):]
    with pytest.raises(psycopg.errors.RaiseException, match=denuncia):
        with banco.transaction(force_rollback=True), banco.cursor() as c:
            voltar_a_ser_servidor(c)
            c.execute(mutacao)
            c.execute(conferencia)


@requer_pg
def test_a_conferencia_passa_no_estado_certo(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO[TEXTO.rindex("do $$"):])
