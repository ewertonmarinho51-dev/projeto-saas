"""
A 0040 (`documentos_gerados`) aplicada de verdade, num PostgreSQL descartável.

O que ela promete: os nomes dos documentos, nunca o texto; quem lê é quem já lê a
linha, porque o RLS de `processos` decide antes; `anon` não executa. E a
conferência morde quando uma dessas garantias some.
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
            / "supabase" / "migrations" / "0040_documentos_gerados.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))

requer_pg = pytest.mark.usefixtures("ensaio_sql")

MARCA = "texto-sigiloso-do-documento"
LEITURA = "select p.id, public.documentos_gerados(p) from public.processos p where p.id = %s"


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def test_concessao_nome_a_nome():
    assert ("grant execute on function public.documentos_gerados(public.processos) "
            "to authenticated;") in SQL
    assert len(re.findall(r"^\s*grant\b", SQL, re.IGNORECASE | re.MULTILINE)) == 2


@pytest.mark.parametrize("proibido", [
    r"\bto\s+anon\b", r"\bto\s+public\b", r"all\s+functions", r"default\s+privileges",
    r"\bsecurity\s+definer\b", r"disable\s+row\s+level\s+security", r"\bdrop\s+",
    r"using\s*\(\s*true\s*\)", r"create\s+policy", r"alter\s+table",
])
def test_nao_abre_o_que_nao_deve(proibido):
    assert not re.search(proibido, SQL, re.IGNORECASE), proibido


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0040 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")


def test_recarrega_o_esquema_do_postgrest():
    assert "notify pgrst, 'reload schema'" in SQL


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0040_documentos_gerados.sql" in SEQUENCIA_EM_ENSAIO
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cenario(banco):
    from psycopg.types.json import Jsonb

    dados: dict = {}
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência: reaplicar não muda nada
        for chave in ("a", "b"):
            c.execute("insert into tenants (slug, nome, uf) values (%s, %s, 'PA') returning id",
                      (f"t-{chave}-{uuid.uuid4().hex[:8]}", chave))
            tenant = str(c.fetchone()[0])
            dados[f"tenant_{chave}"] = tenant
            c.execute("insert into processos (tenant_id, orgao, objeto, documentos) "
                      "values (%s, 'Saúde', 'Luvas', %s) returning id",
                      (tenant, Jsonb({"dfd": MARCA, "etp": MARCA})))
            dados[f"processo_{chave}"] = str(c.fetchone()[0])
        c.execute("insert into processos (tenant_id, orgao, objeto, documentos) "
                  "values (%s, 'Saúde', 'Sem documentos', '{}') returning id", (dados["tenant_a"],))
        dados["vazio"] = str(c.fetchone()[0])
    banco.commit()
    dados["usuario_a"] = claims("u-a", papel="admin", tenant=dados["tenant_a"])
    return dados


def _ler(banco, jwt, processo, papel="authenticated"):
    """(sqlstate ou None, linhas), sempre desfeito."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, jwt, papel)
        try:
            c.execute(LEITURA, (processo,))
            return None, c.fetchall()
        except Exception as erro:  # noqa: BLE001
            return getattr(erro, "sqlstate", "erro"), []


@requer_pg
def test_devolve_os_nomes_e_nunca_o_texto(banco, cenario):
    erro, linhas = _ler(banco, cenario["usuario_a"], cenario["processo_a"])
    assert erro is None and [l[1] for l in linhas] == [["dfd", "etp"]]
    assert MARCA not in str(linhas)


@requer_pg
def test_processo_sem_documentos_devolve_lista_vazia(banco, cenario):
    erro, linhas = _ler(banco, cenario["usuario_a"], cenario["vazio"])
    assert erro is None and [l[1] for l in linhas] == [[]]


@requer_pg
def test_outro_orgao_nao_ve_nada(banco, cenario):
    # Passar pelo motivo certo: a linha do órgão B existe e a função a leria.
    erro, linhas = _ler(banco, cenario["usuario_a"], cenario["processo_b"])
    assert erro is None and linhas == []
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(LEITURA, (cenario["processo_b"],))
        assert [l[1] for l in c.fetchall()] == [["dfd", "etp"]]


@requer_pg
def test_anon_nao_executa(banco, cenario):
    erro, linhas = _ler(banco, "{}", cenario["processo_a"], papel="anon")
    assert erro == "42501" and linhas == []


# Cada ramo da conferência, quebrado de propósito: um `grant` que não pegou não dá
# erro, e só este bloco o denuncia.
FUNCAO = "public.documentos_gerados(public.processos)"
MUTACOES = [
    (f"revoke execute on function {FUNCAO} from authenticated", "authenticated_sem_execute"),
    (f"grant execute on function {FUNCAO} to anon", "anon_executa"),
    (f"alter function {FUNCAO} security definer", "security_definer"),
    (f"alter function {FUNCAO} volatile", "nao_estavel"),
    ("grant select on public.processos to anon", "anon_le_tabela"),
    ("alter table public.processos disable row level security", "rls_desligado"),
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
