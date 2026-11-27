"""
A 0051 aplicada de verdade, num PostgreSQL descartável.

O que ela promete: `aprovacao_no_escopo` (SECURITY DEFINER, recebe o
tenant como argumento) deixa de ser chamável por usuário — nem do próprio
tenant, nem apontando para outro —, e a trilha de governança, que a usa
por dentro, continua registrando evento sobre aprovação. As provas da
trilha em `test_ensaio_sql_local.py` rodam depois da 0051 e cobrem o lado
"permitido"; aqui fica o lado "recusado" e a conferência.
"""

from __future__ import annotations

import pathlib
import re
import sys
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import claims, como, voltar_a_ser_servidor  # noqa: E402

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent / "supabase" / "migrations"
            / "0051_escopo_de_aprovacao_so_por_dentro.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))

requer_pg = pytest.mark.usefixtures("ensaio_sql")
ASSINATURA = "public.aprovacao_no_escopo(uuid, uuid, uuid, text)"


def test_cabecalho_diz_o_estado():
    assert TEXTO.startswith("-- ## 0051 —")
    assert "## ESTADO:" in TEXTO
    assert "O QUE ESTA MIGRAÇÃO NÃO RESOLVE" in TEXTO


@pytest.mark.parametrize("proibido", [
    r"\bto\s+anon\b", r"\bto\s+authenticated\b", r"\bto\s+public\b", r"create\s+policy",
    r"disable\s+row\s+level\s+security", r"\bdrop\b", r"create\s+or\s+replace",
])
def test_so_fecha(proibido):
    assert not re.search(proibido, SQL, re.IGNORECASE), proibido


def test_revoga_de_quem_chama_por_fora():
    assert f"revoke all on function {ASSINATURA}\n  from public, anon, authenticated;" in SQL


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0051 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")


def test_esta_na_sequencia_do_ensaio_depois_da_0050():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert SEQUENCIA_EM_ENSAIO.index(MIGRACAO.name) == \
        SEQUENCIA_EM_ENSAIO.index("0050_precos_cmed_teto.sql") + 1
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


def test_ninguem_no_codigo_chama_a_funcao_por_rpc():
    raiz = pathlib.Path(__file__).resolve().parent.parent
    for pasta in ("src", "apps"):
        for arquivo in (raiz / pasta).rglob("*"):
            if arquivo.suffix in {".py", ".ts", ".tsx"} and "node_modules" not in arquivo.parts:
                assert "aprovacao_no_escopo" not in arquivo.read_text(encoding="utf-8",
                                                                      errors="ignore"), arquivo


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
def _chamar(banco, papel, jwt, tenant):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, jwt, papel)
        try:
            c.execute(f"select {ASSINATURA.split('(')[0]}(%s, %s, %s, %s)",
                      (str(uuid.uuid4()), tenant, None, "admin_municipal"))
            return None
        except Exception as erro:  # noqa: BLE001
            return getattr(erro, "sqlstate", "erro")


@requer_pg
@pytest.mark.parametrize("papel", ["authenticated", "anon"])
def test_usuario_nao_chama_a_resolucao_de_escopo(banco, papel):
    tenant = str(uuid.uuid4())
    jwt = claims("u-a", papel="admin", tenant=tenant, papel_governanca="admin_municipal")
    assert _chamar(banco, papel, jwt, str(uuid.uuid4())) == "42501"
    assert _chamar(banco, papel, jwt, tenant) == "42501"


@requer_pg
def test_dono_da_trilha_mantem_o_execute(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select has_function_privilege(p.proowner, %s, 'execute') "
                  "from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
                  "where n.nspname = 'public' and p.proname = 'registrar_evento_governanca'",
                  (ASSINATURA,))
        assert c.fetchone()[0] is True


@requer_pg
def test_conferencia_morde_se_a_classe_reabrir(banco):
    """Reabre de propósito e roda a migração: tem de recusar."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(f"grant execute on function {ASSINATURA} to authenticated")
        bloco = SQL[SQL.index("do $$"):]
        with pytest.raises(Exception, match="A 0051 não cumpriu o que afirma"):
            c.execute(bloco)


@requer_pg
def test_idempotente(banco):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)
        c.execute(TEXTO)
