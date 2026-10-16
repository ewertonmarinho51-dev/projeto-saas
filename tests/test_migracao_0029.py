"""
A 0029 (Cotações unificadas) — revisada ANTES de alguém aplicá-la.

Duas camadas, como a prova da 0028:

* leitura do ARQUIVO, que roda sempre: a migração é aditiva, nasce com o
  sufixo `.NAO_APLICAR`, não afrouxa RLS, não concede nada a `anon`,
  mantém todos os tipos de evento da 0021 e copia as colunas novas na
  revisão;
* aplicação num PostgreSQL DESCARTÁVEL (fixture `banco`), que roda só
  com `GOVDOCS_ENSAIO_PG_DSN` — nesta máquina pula, e o relatório do
  gate diz isso. Lá a prova é sobre o CATÁLOGO: idempotência, RLS ligada
  e forçada, nenhum grant a `anon`, trilha imutável.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_MIGRACOES = (pathlib.Path(__file__).resolve().parent.parent
              / "supabase" / "migrations")
MIGRACAO = _MIGRACOES / "0029_cotacoes_unificadas.sql.NAO_APLICAR"
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(l for l in TEXTO.splitlines() if not l.strip().startswith("--"))


def test_nasce_travada_e_sem_par_aplicavel():
    assert MIGRACAO.exists()
    assert not (_MIGRACOES / "0029_cotacoes_unificadas.sql").exists(), (
        "a 0029 só perde o sufixo com autorização expressa")


@pytest.mark.parametrize("proibido", [
    r"\bdrop\s+table\b", r"\bdrop\s+column\b",
    r"^\s*truncate\b",   # o comando; "revoke ... truncate" é o desejado
    r"disable\s+row\s+level\s+security", r"\bdelete\s+from\b",
    r"grant\s+[^;]*\bto\s+anon\b", r"grant\s+[^;]*\bdelete\b",
    r"grant\s+[^;]*\bupdate\b[^;]*pesquisa_preco_emissoes",
])
def test_e_aditiva_e_nao_afrouxa_seguranca(proibido):
    assert not re.search(proibido, SQL, re.IGNORECASE | re.MULTILINE), proibido


def test_tabela_nova_nasce_com_rls_ligada_forcada_e_append_only():
    for trecho in (
            "alter table public.pesquisa_preco_emissoes enable row level security",
            "alter table public.pesquisa_preco_emissoes force row level security",
            "revoke all on public.pesquisa_preco_emissoes from anon, authenticated, public",
            "revoke delete, truncate on public.pesquisa_preco_emissoes from service_role",
            "grant select, insert on public.pesquisa_preco_emissoes to authenticated",
            "before update or delete on public.pesquisa_preco_emissoes"):
        assert trecho in SQL, trecho
    politicas = re.findall(r'create policy "([^"]+)"', SQL)
    assert politicas == ["pesquisa_preco_emissoes_le",
                         "pesquisa_preco_emissoes_insere"]
    assert "using (true)" not in SQL.lower()


def test_todos_os_tipos_de_evento_da_0021_continuam_validos():
    original = (_MIGRACOES / "0021_pesquisa_precos.sql").read_text(
        encoding="utf-8")
    bloco = re.search(r"check \(tipo in \((.*?)\)\)", original, re.S).group(1)
    antigos = set(re.findall(r"'([a-z_]+)'", bloco))
    novo = re.search(r"check \(tipo in \((.*?)\)\);", SQL, re.S).group(1)
    atuais = set(re.findall(r"'([a-z_]+)'", novo))
    assert antigos <= atuais
    assert {"excecao_registrada", "relatorio_emitido",
            "busca_registrada"} <= atuais


def test_os_tipos_que_o_codigo_grava_existem_na_migracao():
    """Nenhum `registrar_evento(..., "<tipo>")` do pacote fica sem CHECK."""
    novo = re.search(r"check \(tipo in \((.*?)\)\);", SQL, re.S).group(1)
    aceitos = set(re.findall(r"'([a-z_]+)'", novo))
    raiz = pathlib.Path(__file__).resolve().parent.parent / "src"
    usados = set()
    for arquivo in list((raiz / "precos").glob("*.py")) + \
            list((raiz / "ui").glob("*.py")):
        texto = arquivo.read_text(encoding="utf-8")
        usados |= set(re.findall(
            r'registrar_evento\(\s*[^,]+,\s*"([a-z_]+)"', texto))
    assert usados and usados <= aceitos, usados - aceitos


def test_revisao_copia_as_colunas_novas_e_a_flag_nasce_desligada():
    assert "i.lote, i.uf, i.removido_em" in SQL
    assert "('flag_unified_quotations', 'off')" in SQL
    rollback = (pathlib.Path(__file__).resolve().parent.parent / "docs"
                / "cotacoes" / "0029_rollback.sql").read_text(encoding="utf-8")
    assert "drop table if exists public.pesquisa_preco_emissoes" in rollback
    assert "not valid" in rollback


# ---------------------------------------------------------------------------
# Aplicação real — só com o banco de ensaio
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def banco_com_0029(banco):
    with banco.cursor() as cursor:
        cursor.execute(TEXTO)
        cursor.execute(TEXTO)   # idempotente: a segunda aplicação não levanta
    return banco


def test_catalogo_apos_aplicar(banco_com_0029):
    with banco_com_0029.cursor() as cursor:
        cursor.execute(
            "select relrowsecurity, relforcerowsecurity from pg_class "
            "where relname='pesquisa_preco_emissoes' "
            "and relnamespace='public'::regnamespace")
        assert cursor.fetchone() == (True, True)
        cursor.execute(
            "select count(*) from information_schema.role_table_grants "
            "where table_name='pesquisa_preco_emissoes' and grantee='anon'")
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "select column_name from information_schema.columns "
            "where table_name='pesquisa_preco_itens' and column_name in "
            "('revisao','lote','uf','removido_em')")
        assert {r[0] for r in cursor.fetchall()} == {
            "revisao", "lote", "uf", "removido_em"}
