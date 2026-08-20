"""
Fase 5 do padrão ouro — apresentação do dossiê exportado.

Defeitos medidos no PDF auditado (190 páginas): colunas de largura
uniforme quebrando palavra a cada poucos caracteres ("ESPECIFICA ÇÃO",
"PASTA SANFONAD A" — 455 fragmentos de 1 a 3 letras no texto extraído),
coluna final vazia em todas as linhas da tabela e 203 blocos de texto
saindo pela margem direita.
"""

import json
import re
from pathlib import Path

import pytest

from src import export, planilha

FIXTURE = Path(__file__).parent / "fixtures" / "caso_210_itens.json"


@pytest.fixture(scope="module")
def itens():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["itens"]


@pytest.fixture(scope="module")
def dossie(itens):
    texto = planilha.injetar_tabela(
        "## 1. DO OBJETO\n\n1.1. Aquisição de materiais.\n"
        "1.2. Segunda alínea, sem linha em branco antes.\n\n"
        "## 2. DA ESTIMATIVA\n\n[[TABELA_ITENS]]\n\n"
        "## 3. DO ENCERRAMENTO\n\n3.1. Fim.\n", itens)
    pdf = export.gerar_pdf_consolidado({"tr": texto}, None)
    pymupdf = pytest.importorskip("pymupdf")
    return pymupdf.open(stream=pdf, filetype="pdf")


# ---------------------------------------------------------------------------
# Larguras de coluna
# ---------------------------------------------------------------------------
def test_colunas_recebem_larguras_proporcionais_ao_texto():
    linhas = [["Código", "Descrição", "Un"],
              ["572704", "ALMOFADA PARA CARIMBO 12x9cm, " * 6, "UNIDADE"]]
    pesos = export._pesos_das_colunas(linhas)
    assert len(pesos) == 3
    # a descrição fica claramente mais larga que o código
    assert pesos[1] > pesos[0] * 1.5
    # e nenhuma coluna some nem estoura
    assert all(export._COL_MIN_CM <= p <= export._COL_MAX_CM for p in pesos)


def test_link_markdown_pesa_pelo_rotulo_e_nao_pela_url():
    """No papel o link ocupa 4 caracteres ("link"), não os 120 da URL."""
    assert export._texto_renderizado("[link](https://a.b/ccc)") == "link"
    url_longa = "[link](https://exemplo.com/" + "x" * 120 + ")"
    pesos = export._pesos_das_colunas(
        [["Descrição", "Fonte"], ["descrição de item " * 4, url_longa]])
    assert pesos[0] > pesos[1] * 1.5


def test_coluna_totalmente_vazia_e_descartada():
    linhas = [["A", "B", ""], ["1", "2", ""]]
    assert export._remover_colunas_vazias(linhas) == [["A", "B"], ["1", "2"]]
    # coluna com qualquer conteúdo permanece
    mantida = [["A", "B", "C"], ["1", "2", ""]]
    assert export._remover_colunas_vazias(mantida) == mantida


# ---------------------------------------------------------------------------
# Resultado no PDF renderizado
# ---------------------------------------------------------------------------
def test_pdf_nao_quebra_palavras_a_cada_poucos_caracteres(dossie, itens):
    texto = "\n".join(p.get_text() for p in dossie)
    # Linha com 1-3 letras: no dossiê auditado eram 455 (palavras
    # partidas pela coluna estreita). Restam apenas palavras curtas
    # legítimas fechando linha justificada ("de", "com").
    fragmentos = re.findall(r"(?m)^[a-záéíóúãõç]{1,3}\n", texto)
    assert len(fragmentos) < 40, fragmentos[:10]
    partidas = [f for f in fragmentos
                if f.strip() not in {"de", "da", "do", "e", "em", "no",
                                     "na", "com", "por", "a", "o", "ou",
                                     "os", "as", "um", "ao"}]
    assert not partidas, partidas

    # A quebra que interessa é a que a RENDERIZAÇÃO produz. O caso real
    # nasceu de uma extração de PDF e já traz palavras partidas na
    # própria fonte ("fechamento em el ástico", "tampa integr ada",
    # "visor de ident ificação"): reprovar por elas seria testar o
    # fixture, não o exportador — e esconderia o defeito verdadeiro atrás
    # de um ruído que o exportador não causou nem pode corrigir.
    fonte = " ".join((i.get("descricao") or "") for i in itens)
    for quebrada in ("ESPECIFICA ÇÃO", "SANFONAD A", "el ástico",
                     "integr ada", "ident ificação"):
        if quebrada in fonte:
            continue
        assert quebrada not in texto, quebrada


def test_pdf_nao_tem_texto_fora_da_margem(dossie):
    fora = [b for p in dossie for b in p.get_text("blocks")
            if b[2] > p.rect.width - 20]
    assert not fora, fora[:3]


def test_pdf_preserva_a_planilha_integral(dossie, itens):
    texto = "\n".join(p.get_text() for p in dossie)
    ausentes = [str(i["codigo"]) for i in itens
                if str(i["codigo"]) not in texto]
    assert not ausentes, ausentes[:5]
    assert "8.024.834,67" in texto
