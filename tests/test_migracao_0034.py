"""
A 0034 (Base de Conhecimento: o admin grava trechos e exclui a
referência com o próprio JWT) aplicada de verdade, num PostgreSQL
descartável.

O que ela promete: o ADMIN grava trecho de documento do PRÓPRIO tenant e
exclui a referência do próprio tenant, levando os trechos junto; usuário
comum não grava nem exclui; o admin de outra prefeitura não alcança; e
ninguém apaga trecho solto. E a conferência morde quando o DELETE em
`chunks_referencia` aparece.
"""

from __future__ import annotations

import pathlib
import re
import sys
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import claims, como, voltar_a_ser_servidor  # noqa: E402

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0034_base_conhecimento_escrita_admin.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))

requer_pg = pytest.mark.usefixtures("ensaio_sql")


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def test_grants_nome_a_nome_e_so_os_dois():
    assert "grant insert on public.chunks_referencia to authenticated;" in SQL
    assert "grant delete on public.documentos_referencia to authenticated;" in SQL
    assert len(re.findall(r"^\s*grant\b", SQL, re.IGNORECASE | re.MULTILINE)) == 2


@pytest.mark.parametrize("proibido", [
    r"grant\s+[^;]*\bdelete\b[^;]*\bon\s+public\.chunks_referencia\b",
    r"grant\s+[^;]*\bupdate\b", r"\bto\s+anon\b", r"using\s*\(\s*true\s*\)",
    r"disable\s+row\s+level\s+security", r"\bdrop\s+table\b", r"\bdelete\s+from\b",
])
def test_nao_abre_o_que_nao_deve(proibido):
    assert not re.search(proibido, SQL, re.IGNORECASE), proibido


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0034 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0034_base_conhecimento_escrita_admin.sql" in SEQUENCIA_EM_ENSAIO
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
        for chave in ("tenant_a", "tenant_b"):
            c.execute("insert into tenants (slug, nome, uf) values (%s, %s, 'PA') returning id",
                      (f"{chave}-{uuid.uuid4().hex[:8]}", chave))
            dados[chave] = str(c.fetchone()[0])
        for chave, tenant in (("doc_a", "tenant_a"), ("doc_b", "tenant_b")):
            c.execute("insert into documentos_referencia (tenant_id, titulo, categoria, nome_arquivo) "
                      "values (%s, %s, 'lei', 'lei.pdf') returning id", (dados[tenant], chave))
            dados[chave] = str(c.fetchone()[0])
        c.execute("insert into chunks_referencia (documento_id, ordem, conteudo) values (%s, 0, 'art. 1')",
                  (dados["doc_a"],))
    banco.commit()
    dados["admin_a"] = claims("u-admin-a", papel="admin", tenant=dados["tenant_a"])
    dados["comum_a"] = claims("u-comum-a", papel="usuario", tenant=dados["tenant_a"])
    return dados


def _executar(banco, jwt, sql, params=()):
    """(sqlstate ou None, linhas afetadas), sempre desfeito."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, jwt)
        try:
            c.execute(sql, params)
            return None, c.rowcount
        except Exception as erro:  # noqa: BLE001
            return getattr(erro, "sqlstate", "erro"), 0


INSERE_TRECHO = "insert into chunks_referencia (documento_id, ordem, conteudo) values (%s, 1, 'art. 2')"
EXCLUI_DOC = "delete from documentos_referencia where id = %s"


@requer_pg
def test_admin_grava_trecho_do_proprio_tenant(banco, cenario):
    assert _executar(banco, cenario["admin_a"], INSERE_TRECHO, (cenario["doc_a"],)) == (None, 1)


@requer_pg
def test_admin_nao_grava_trecho_em_documento_de_outro_tenant(banco, cenario):
    estado, _ = _executar(banco, cenario["admin_a"], INSERE_TRECHO, (cenario["doc_b"],))
    assert estado == "42501"


@requer_pg
def test_usuario_comum_nao_grava_trecho(banco, cenario):
    estado, _ = _executar(banco, cenario["comum_a"], INSERE_TRECHO, (cenario["doc_a"],))
    assert estado == "42501"


@requer_pg
def test_admin_exclui_a_referencia_e_os_trechos_caem_junto(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["admin_a"])
        c.execute(EXCLUI_DOC, (cenario["doc_a"],))
        assert c.rowcount == 1
        voltar_a_ser_servidor(c)
        c.execute("select count(*) from chunks_referencia where documento_id = %s", (cenario["doc_a"],))
        assert c.fetchone()[0] == 0


@requer_pg
def test_quem_nao_pode_excluir_nao_alcanca_a_linha(banco, cenario):
    # RLS em DELETE não dá erro: a linha simplesmente não é vista.
    assert _executar(banco, cenario["comum_a"], EXCLUI_DOC, (cenario["doc_a"],)) == (None, 0)
    assert _executar(banco, cenario["admin_a"], EXCLUI_DOC, (cenario["doc_b"],)) == (None, 0)


@requer_pg
def test_ninguem_apaga_trecho_solto(banco, cenario):
    estado, _ = _executar(banco, cenario["admin_a"],
                          "delete from chunks_referencia where documento_id = %s", (cenario["doc_a"],))
    assert estado == "42501"


@requer_pg
def test_a_conferencia_morde_com_delete_nos_trechos(banco, cenario):
    import psycopg

    conferencia = TEXTO[TEXTO.index("do $$"):]
    with pytest.raises(psycopg.errors.RaiseException, match="delete_em_chunks"):
        with banco.transaction(force_rollback=True), banco.cursor() as c:
            voltar_a_ser_servidor(c)
            c.execute("grant delete on public.chunks_referencia to authenticated")
            c.execute(conferencia)
