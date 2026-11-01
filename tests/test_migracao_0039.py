"""
A 0039 (job de elaboração e um job ativo por pessoa e processo) aplicada de
verdade, num PostgreSQL descartável.

O que ela promete: o tipo novo entra sem afrouxar o resto; a mesma pessoa não
tem dois jobs ativos no mesmo processo; job encerrado não impede pedir de
novo; job de outro processo, de outra pessoa ou de outro tipo não é afetado.
"""

from __future__ import annotations

import pathlib
import re
import sys
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import voltar_a_ser_servidor  # noqa: E402

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0039_api_jobs_elaboracao.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))

requer_pg = pytest.mark.usefixtures("ensaio_sql")
TIPO = "elaboracao_documento"


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("proibido", [
    r"\bgrant\b", r"\brevoke\b", r"\bdrop\s+table\b", r"\bdrop\s+column\b", r"\bdrop\s+policy\b",
    r"\bcreate\s+policy\b", r"disable\s+row\s+level\s+security", r"using\s*\(\s*true\s*\)",
    r"\bdelete\s+from\b", r"^\s*truncate\b",
])
def test_nao_mexe_em_privilegio_nem_em_dado(proibido):
    assert not re.search(proibido, SQL, re.IGNORECASE | re.MULTILINE), proibido


def test_mantem_os_tipos_que_ja_existem():
    for tipo in ("coleta_precos", "relatorio_precos", TIPO):
        assert f"'{tipo}'" in SQL


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0039 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0039_api_jobs_elaboracao.sql" in SEQUENCIA_EM_ENSAIO
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cenario(banco):
    dados: dict = {}
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência: reaplicar não muda nada
        c.execute("insert into tenants (slug, nome, uf) values (%s, 't', 'PA') returning id",
                  (f"t-{uuid.uuid4().hex[:8]}",))
        dados["tenant"] = str(c.fetchone()[0])
        for chave in ("a", "b"):
            dados[chave] = str(uuid.uuid4())
            c.execute("insert into auth.users (id) values (%s)", (dados[chave],))
    banco.commit()
    return dados


def _job(c, cenario, *, dono="a", recurso=None, tipo=TIPO, estado="queued"):
    recurso = recurso or str(uuid.uuid4())
    c.execute("insert into public.api_jobs (tenant_id, auth_user_id, tipo, recurso_id, estado, "
              "idempotency_key) values (%s,%s,%s,%s,%s,%s) returning id",
              (cenario["tenant"], cenario[dono], tipo, recurso, estado, "chave-" + uuid.uuid4().hex))
    return c.fetchone()[0]


def _tentar(banco, passos):
    """Roda desfeito e devolve o SQLSTATE do erro, ou None."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        try:
            passos(c)
        except Exception as erro:  # noqa: BLE001
            return getattr(erro, "sqlstate", "erro")
    return None


@requer_pg
def test_tipo_novo_entra_e_tipo_desconhecido_nao(banco, cenario):
    assert _tentar(banco, lambda c: _job(c, cenario)) is None
    assert _tentar(banco, lambda c: _job(c, cenario, tipo="outro_tipo")) == "23514"


@requer_pg
def test_tipos_antigos_seguem_valendo(banco, cenario):
    assert _tentar(banco, lambda c: _job(c, cenario, tipo="coleta_precos")) is None
    assert _tentar(banco, lambda c: _job(c, cenario, tipo="relatorio_precos")) is None


@requer_pg
@pytest.mark.parametrize("estado", ["queued", "running"])
def test_segundo_job_ativo_da_mesma_pessoa_e_recusado(banco, cenario, estado):
    alvo = str(uuid.uuid4())

    def passos(c):
        _job(c, cenario, recurso=alvo, estado=estado)
        _job(c, cenario, recurso=alvo)

    assert _tentar(banco, passos) == "23505"


@requer_pg
@pytest.mark.parametrize("estado", ["succeeded", "failed", "cancelled"])
def test_job_encerrado_nao_impede_pedir_de_novo(banco, cenario, estado):
    alvo = str(uuid.uuid4())

    def passos(c):
        _job(c, cenario, recurso=alvo, estado=estado)
        _job(c, cenario, recurso=alvo)

    assert _tentar(banco, passos) is None


@requer_pg
def test_outra_pessoa_e_outro_processo_nao_colidem(banco, cenario):
    alvo = str(uuid.uuid4())

    def passos(c):
        _job(c, cenario, recurso=alvo)
        _job(c, cenario, dono="b", recurso=alvo)
        _job(c, cenario)

    assert _tentar(banco, passos) is None


@requer_pg
def test_o_indice_nao_alcanca_outros_tipos(banco, cenario):
    alvo = str(uuid.uuid4())

    def passos(c):
        _job(c, cenario, recurso=alvo, tipo="coleta_precos")
        _job(c, cenario, recurso=alvo, tipo="coleta_precos")

    assert _tentar(banco, passos) is None


@requer_pg
def test_sem_o_indice_o_clique_repetido_passaria(banco, cenario):
    """A prova morde: o 23505 acima é deste índice, não de outra coisa."""
    alvo = str(uuid.uuid4())

    def passos(c):
        c.execute("drop index public.api_jobs_elaboracao_ativa")
        _job(c, cenario, recurso=alvo)
        _job(c, cenario, recurso=alvo)

    assert _tentar(banco, passos) is None


@requer_pg
def test_conferencia_morde_sem_o_indice(banco, cenario):
    conferencia = TEXTO[TEXTO.index("do $$"):]

    def passos(c):
        c.execute("drop index public.api_jobs_elaboracao_ativa")
        c.execute(conferencia)

    assert _tentar(banco, passos) is not None
