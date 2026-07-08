"""Testes da captura visual de identidade (branding a partir de PDF/DOCX)."""

import io
import zipfile

import pytest

from src import branding, export


def _pdf_modelo() -> bytes:
    """PDF-modelo com faixa de cabeçalho (topo) e rodapé (base)."""
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.set_fill_color(27, 79, 138)
    pdf.rect(0, 0, 210, 30, "F")  # cabeçalho azul
    pdf.set_xy(0, 12)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(210, 8, "ORGAO DE EXEMPLO", align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(20, 60)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(170, 7, "Corpo do modelo. " * 30)
    pdf.set_fill_color(220, 220, 220)
    pdf.rect(0, 277, 210, 20, "F")  # rodapé cinza
    return bytes(pdf.output())


def test_render_e_recortes_do_pdf():
    img = branding.renderizar_modelo("modelo.pdf", _pdf_modelo())
    larg, alt = img.size
    assert larg > 0 and alt > larg  # A4 retrato

    png_cab = branding.recortar_cabecalho(img, 11)
    png_rod = branding.recortar_rodape(img, 8)
    png_marca = branding.recortar_marca_dagua(img, 0.12)
    for png in (png_cab, png_rod, png_marca):
        assert png[:8] == b"\x89PNG\r\n\x1a\n"  # assinatura PNG

    from PIL import Image
    # cabeçalho recortado tem a altura proporcional pedida
    h_cab = Image.open(io.BytesIO(png_cab)).size[1]
    assert abs(h_cab - int(alt * 0.11)) <= 2


def test_base64_ida_e_volta():
    dados = b"\x89PNG\r\n\x1a\nqualquer"
    assert branding.de_base64(branding.para_base64(dados)) == dados
    assert branding.de_base64("") is None
    assert branding.para_base64(b"") == ""


def test_formato_nao_suportado():
    with pytest.raises(branding.ErroBranding, match="não suportado"):
        branding.renderizar_modelo("planilha.xlsx", b"x" * 200)


def test_carimbo_de_imagens_no_pdf_e_docx():
    img = branding.renderizar_modelo("modelo.pdf", _pdf_modelo())
    brand = {
        "cabecalho_img": branding.para_base64(branding.recortar_cabecalho(img, 11)),
        "rodape_img": branding.para_base64(branding.recortar_rodape(img, 8)),
        "marca_img": branding.para_base64(branding.recortar_marca_dagua(img)),
        "cabecalho_pct": 11.0,
        "rodape_pct": 8.0,
    }
    docs = {"dfd": "# DFD\n\n## 1. Objeto\n\n" + ("Texto do documento. " * 40)}

    pdf = export.gerar_pdf_consolidado(docs, brand)
    assert pdf.startswith(b"%PDF")
    # o PDF resultante deve conter imagens embutidas
    assert b"/Image" in pdf or b"/XObject" in pdf

    docx_bytes = export.gerar_docx_consolidado(docs, brand)
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
        nomes = zf.namelist()
    # imagens de cabeçalho/rodapé embutidas na área de header/footer
    assert any("media" in n for n in nomes)
    assert any("header" in n for n in nomes) and any("footer" in n for n in nomes)


def test_branding_imagem_tem_prioridade_sobre_texto():
    img = branding.renderizar_modelo("modelo.pdf", _pdf_modelo())
    brand = {
        "cabecalho": "TEXTO QUE NAO DEVE APARECER",
        "cabecalho_img": branding.para_base64(branding.recortar_cabecalho(img, 11)),
        "cabecalho_pct": 11.0,
    }
    docx_bytes = export.gerar_docx_consolidado({"dfd": "# X\n\ncorpo"}, brand)
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
        header = ""
        for n in zf.namelist():
            if "header" in n and n.endswith(".xml"):
                header += zf.read(n).decode()
    # com imagem, o texto do cabeçalho não é usado
    assert "TEXTO QUE NAO DEVE APARECER" not in header
