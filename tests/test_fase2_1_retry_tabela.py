"""
Fase 2.1 — o retry de tabela do fpdf2 é atômico.

`_pdf_render_tabela` tenta a tabela em 9, 7 e 6 pt, porque o fpdf2 não
divide uma linha entre páginas e levanta `ValueError` quando uma linha é
mais alta que a folha. O ponto cego: esse erro é levantado **no meio do
laço de linhas** (`fpdf/table.py`, "The row with index N is too high"),
com as linhas anteriores JÁ DESENHADAS no buffer da página. O código
restaurava a posição do cursor e tentava de novo — e reposicionar o
cursor não desfaz conteúdo emitido.

Resultado medido antes da correção, com 20 linhas antes da linha alta:

    1 ValueError  → cada um dos 20 códigos aparecia 2 vezes
    2 ValueError  → 3 vezes
    3 ValueError  → 4 vezes (as 3 tentativas + o caminho degradado)

Um dossiê exportado afirmando itens que o processo não tem. A correção
transforma cada tentativa numa transação, com o `FPDFRecorder` do próprio
fpdf2: ou a tabela inteira entra, ou o PDF volta ao que era.

O fallback tem de preservar INTEGRALIDADE, não apenas não lançar exceção.
"""

import re
from collections import Counter

import pytest

from src import export

pymupdf = pytest.importorskip("pymupdf",
                              reason="a prova lê o PDF renderizado")

LINHAS_ANTES = 20


def _tabela(n_linhas: int, chars_da_linha_alta: int) -> list[str]:
    """Tabela com códigos únicos e uma última linha deliberadamente alta."""
    linhas = ["| Código | Descrição |", "|---|---|"]
    for i in range(n_linhas):
        linhas.append(f"| C{i:05d} | Descrição do item {i}, texto curto. |")
    gigante = "palavra " * (chars_da_linha_alta // 8)
    linhas.append(f"| C{n_linhas:05d} | {gigante}|")
    return linhas


def _render(linhas_tab: list[str]) -> tuple[bytes, int]:
    """Renderiza e devolve (pdf, nº de ValueError levantados pelo fpdf2)."""
    import fpdf.table as ft

    quedas = {"n": 0}
    original = ft.Table.render

    def render_contando(self, *args, **kwargs):
        try:
            return original(self, *args, **kwargs)
        except ValueError:
            quedas["n"] += 1
            raise

    ft.Table.render = render_contando
    try:
        pdf = export._pdf_novo(None)
        pdf.add_page()
        export._pdf_render_tabela(pdf, linhas_tab)
        return bytes(pdf.output()), quedas["n"]
    finally:
        ft.Table.render = original


def _codigos(pdf_bytes: bytes) -> Counter:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    texto = "".join(p.get_text() for p in doc).replace("\n", "")
    return Counter(re.findall(r"C\d{5}", texto))


# ---------------------------------------------------------------------------
# Controle: a montagem realmente derruba uma tentativa
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("chars", [8000, 12000, 20000])
def test_a_montagem_derruba_ao_menos_uma_tentativa(chars):
    """
    Sem isto o teste abaixo poderia estar passando por nunca exercitar o
    retry — que é justamente o caminho sob suspeita.
    """
    _, quedas = _render(_tabela(LINHAS_ANTES, chars))
    assert quedas >= 1, "nenhuma tentativa falhou: o retry não foi exercitado"


# ---------------------------------------------------------------------------
# A prova: tentativa fracassada não deixa resíduo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("chars", [8000, 12000, 20000, 40000])
def test_cada_codigo_aparece_exatamente_uma_vez(chars):
    pdf, quedas = _render(_tabela(LINHAS_ANTES, chars))
    contagem = _codigos(pdf)
    repetidos = {c: n for c, n in contagem.items() if n > 1}
    assert not repetidos, (f"{quedas} tentativa(s) fracassada(s) deixaram "
                           f"resíduo: {list(repetidos.items())[:5]}")
    assert len(contagem) == LINHAS_ANTES + 1, sorted(contagem)
    assert sum(contagem.values()) == LINHAS_ANTES + 1


def test_nenhum_item_se_perde_quando_todas_as_tentativas_caem(monkeypatch):
    """
    Desfazer não pode virar apagar. Com TODAS as tentativas derrubadas, o
    caminho degradado (parágrafos "Rótulo: valor") ainda tem de entregar
    os 21 itens — integralidade, não só ausência de exceção.
    """
    import fpdf.table as ft

    monkeypatch.setattr(
        ft.Table, "render",
        lambda self, *a, **k: (_ for _ in ()).throw(
            ValueError("The row with index 3 is too high")))

    pdf = export._pdf_novo(None)
    pdf.add_page()
    export._pdf_render_tabela(pdf, _tabela(LINHAS_ANTES, 200))
    contagem = _codigos(bytes(pdf.output()))
    assert len(contagem) == LINHAS_ANTES + 1, sorted(contagem)
    assert all(n == 1 for n in contagem.values()), contagem


def test_caminho_degradado_preserva_descricao_e_cabecalho(monkeypatch):
    """O texto do item também precisa sobreviver, não só o código."""
    import fpdf.table as ft

    monkeypatch.setattr(
        ft.Table, "render",
        lambda self, *a, **k: (_ for _ in ()).throw(ValueError("too high")))

    pdf = export._pdf_novo(None)
    pdf.add_page()
    export._pdf_render_tabela(pdf, _tabela(3, 200))
    doc = pymupdf.open(stream=bytes(pdf.output()), filetype="pdf")
    texto = "".join(p.get_text() for p in doc).replace("\n", " ")
    for i in range(3):
        assert f"item {i}," in texto, i
    assert "Código" in texto and "Descrição" in texto


def test_sem_mecanismo_de_desfazer_vai_direto_ao_caminho_seguro(monkeypatch):
    """
    Se o `FPDFRecorder` sumir numa versão futura do fpdf2, renderizar sem
    rede seria arriscar duplicação. A escolha é a inversa: cai no caminho
    degradado, que é íntegro por construção.
    """
    monkeypatch.setattr(export, "_ponto_de_retorno", lambda _pdf: None)
    pdf = export._pdf_novo(None)
    pdf.add_page()
    export._pdf_render_tabela(pdf, _tabela(5, 200))
    contagem = _codigos(bytes(pdf.output()))
    assert len(contagem) == 6 and all(n == 1 for n in contagem.values())


# ---------------------------------------------------------------------------
# O caminho normal não pode ter sido prejudicado
# ---------------------------------------------------------------------------
def test_tabela_que_cabe_continua_saindo_como_tabela():
    pdf, quedas = _render(_tabela(30, 100))
    assert quedas == 0
    contagem = _codigos(pdf)
    assert len(contagem) == 31 and all(n == 1 for n in contagem.values())


def test_desfazer_nao_apaga_o_que_ja_havia_no_documento():
    """
    O rewind restaura o estado ANTERIOR à tentativa — não o documento em
    branco. O que já estava na página antes da tabela permanece.
    """
    import fpdf.table as ft

    original = ft.Table.render
    ft.Table.render = lambda self, *a, **k: (_ for _ in ()).throw(
        ValueError("too high"))
    try:
        pdf = export._pdf_novo(None)
        pdf.add_page()
        pdf.set_font("Times", "", 12)
        pdf.multi_cell(0, 6, "PARAGRAFO ANTERIOR A TABELA",
                       new_x="LMARGIN", new_y="NEXT")
        export._pdf_render_tabela(pdf, _tabela(4, 200))
        pdf.multi_cell(0, 6, "PARAGRAFO POSTERIOR A TABELA",
                       new_x="LMARGIN", new_y="NEXT")
        saida = bytes(pdf.output())
    finally:
        ft.Table.render = original

    doc = pymupdf.open(stream=saida, filetype="pdf")
    texto = "".join(p.get_text() for p in doc).replace("\n", " ")
    assert "PARAGRAFO ANTERIOR A TABELA" in texto
    assert "PARAGRAFO POSTERIOR A TABELA" in texto
    contagem = _codigos(saida)
    assert len(contagem) == 5 and all(n == 1 for n in contagem.values())
