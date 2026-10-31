"""
A 0038 (`authenticated` executa as funções de busca da Base) aplicada de
verdade, num PostgreSQL descartável.

O que ela promete: quem tem JWT busca na Base do PRÓPRIO órgão; pedir o
`tenant` de outro órgão devolve zero linhas, porque quem decide é o RLS;
`anon` não executa. E a conferência morde quando qualquer uma dessas
garantias some, em especial `security definer`, que anularia o RLS.
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
            / "supabase" / "migrations" / "0038_busca_rag_para_authenticated.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))

requer_pg = pytest.mark.usefixtures("ensaio_sql")

BUSCA = "select titulo, conteudo from public.buscar_chunks_textual(%s, 6, %s)"


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def test_grants_nome_a_nome_e_so_os_dois():
    assert "grant execute on function public.buscar_chunks_textual(text, integer, uuid) to authenticated;" in SQL
    assert ("grant execute on function public.buscar_chunks_vetorial(public.vector, integer, uuid)"
            " to authenticated;") in SQL
    assert len(re.findall(r"^\s*grant\b", SQL, re.IGNORECASE | re.MULTILINE)) == 2


@pytest.mark.parametrize("proibido", [
    r"\bto\s+anon\b", r"\bto\s+public\b", r"all\s+functions", r"default\s+privileges",
    r"security\s+definer\b(?!\()", r"disable\s+row\s+level\s+security", r"\bdrop\s+",
    r"using\s*\(\s*true\s*\)",
])
def test_nao_abre_o_que_nao_deve(proibido):
    # O texto da conferência cita `security_definer` com sublinhado, de propósito.
    assert not re.search(proibido, SQL, re.IGNORECASE), proibido


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0038 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0038_busca_rag_para_authenticated.sql" in SEQUENCIA_EM_ENSAIO
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cenario(banco):
    dados: dict = {}
    marca = f"licitacao{uuid.uuid4().hex[:8]}"
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência: reaplicar não muda nada
        for chave in ("a", "b"):
            c.execute("insert into tenants (slug, nome, uf) values (%s, %s, 'PA') returning id",
                      (f"t-{chave}-{uuid.uuid4().hex[:8]}", chave))
            tenant = str(c.fetchone()[0])
            dados[f"tenant_{chave}"] = tenant
            c.execute("insert into documentos_referencia (tenant_id, titulo, categoria, nome_arquivo) "
                      "values (%s, %s, 'lei', 'lei.pdf') returning id", (tenant, f"doc-{chave}"))
            doc = str(c.fetchone()[0])
            c.execute("insert into chunks_referencia (documento_id, ordem, conteudo) "
                      "values (%s, 0, %s)", (doc, f"{marca} do orgao {chave}"))
    banco.commit()
    dados["marca"] = marca
    dados["usuario_a"] = claims("u-a", papel="usuario", tenant=dados["tenant_a"])
    return dados


def _buscar(banco, jwt, marca, tenant, papel="authenticated"):
    """(sqlstate ou None, títulos), sempre desfeito."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, jwt, papel)
        try:
            c.execute(BUSCA, (marca, tenant))
            return None, [linha[0] for linha in c.fetchall()]
        except Exception as erro:  # noqa: BLE001
            return getattr(erro, "sqlstate", "erro"), []


@requer_pg
def test_usuario_busca_na_base_do_proprio_orgao(banco, cenario):
    erro, titulos = _buscar(banco, cenario["usuario_a"], cenario["marca"], cenario["tenant_a"])
    assert erro is None and titulos == ["doc-a"]


@requer_pg
def test_pedir_o_tenant_de_outro_orgao_nao_traz_nada(banco, cenario):
    # Passar pelo motivo certo: a linha do órgão B existe e a busca a acharia.
    erro, titulos = _buscar(banco, cenario["usuario_a"], cenario["marca"], cenario["tenant_b"])
    assert erro is None and titulos == []
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(BUSCA, (cenario["marca"], cenario["tenant_b"]))
        assert [linha[0] for linha in c.fetchall()] == ["doc-b"]


@requer_pg
def test_anon_nao_executa(banco, cenario):
    erro, titulos = _buscar(banco, "{}", cenario["marca"], cenario["tenant_a"], papel="anon")
    assert erro == "42501" and titulos == []


@requer_pg
def test_sem_o_grant_o_erro_de_producao_volta(banco, cenario):
    """A prova morde: é este o 42501 do log de produção."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("revoke execute on function public.buscar_chunks_textual(text, integer, uuid) "
                  "from authenticated")
        como(c, cenario["usuario_a"])
        import psycopg

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(BUSCA, (cenario["marca"], cenario["tenant_a"]))


# Cada ramo da conferência, quebrado de propósito: um `grant` que não pegou
# não dá erro, e só este bloco o denuncia.
MUTACOES = [
    ("revoke execute on function public.buscar_chunks_textual(text, integer, uuid) from authenticated",
     "authenticated_sem_execute"),
    ("revoke execute on function public.buscar_chunks_vetorial(public.vector, integer, uuid) from authenticated",
     "authenticated_sem_execute"),
    ("grant execute on function public.buscar_chunks_textual(text, integer, uuid) to anon", "anon_executa"),
    ("alter function public.buscar_chunks_textual(text, integer, uuid) security definer", "security_definer"),
    ("alter table public.chunks_referencia disable row level security", "rls_desligado"),
    ("grant select on public.documentos_referencia to anon", "anon_le_tabela"),
]


@requer_pg
@pytest.mark.parametrize("mutacao,denuncia", MUTACOES)
def test_a_conferencia_morde(banco, cenario, mutacao, denuncia):
    import psycopg

    conferencia = TEXTO[TEXTO.index("do $$"):]
    with pytest.raises(psycopg.errors.RaiseException, match=denuncia):
        with banco.transaction(force_rollback=True), banco.cursor() as c:
            voltar_a_ser_servidor(c)
            c.execute(mutacao)
            c.execute(conferencia)


@requer_pg
def test_a_conferencia_passa_no_estado_certo(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO[TEXTO.index("do $$"):])
