"""
Exportação dos documentos aprovados para .docx e .pdf.

Os textos gerados pela IA vêm em Markdown simples (títulos #/##/###,
listas e negrito **texto**). Este módulo converte esse Markdown em
documentos Word (python-docx) e PDF (fpdf2), individualmente, em arquivo
único consolidado e em pacote .zip.
"""

import io
import re
import zipfile
from datetime import date

from .config import DOCUMENTOS, SEQUENCIA_DOCUMENTOS

# ---------------------------------------------------------------------------
# Utilitários de parsing do Markdown simplificado
# ---------------------------------------------------------------------------
_RE_NEGRITO = re.compile(r"\*\*(.+?)\*\*")


def _classificar_linha(linha: str) -> tuple[str, str]:
    """Retorna (tipo, conteúdo) para cada linha do Markdown."""
    txt = linha.rstrip()
    if not txt.strip():
        return "vazio", ""
    if txt.startswith("### "):
        return "h3", txt[4:].strip()
    if txt.startswith("## "):
        return "h2", txt[3:].strip()
    if txt.startswith("# "):
        return "h1", txt[2:].strip()
    if re.match(r"^\s*[-*]\s+", txt):
        return "item", re.sub(r"^\s*[-*]\s+", "", txt)
    if txt.strip().startswith("|"):
        return "tabela", txt.strip()
    return "par", txt


def _limpar_inline(texto: str) -> str:
    """Remove marcações inline (negrito/itálico) para saídas sem rich text."""
    texto = _RE_NEGRITO.sub(r"\1", texto)
    return texto.replace("*", "")


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------
def _docx_novo():
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    estilo = doc.styles["Normal"]
    estilo.font.name = "Calibri"
    estilo.font.size = Pt(11)
    return doc


def _docx_paragrafo_com_negrito(doc, texto: str, estilo: str | None = None):
    """Adiciona parágrafo respeitando trechos em **negrito**."""
    par = doc.add_paragraph(style=estilo)
    pos = 0
    for m in _RE_NEGRITO.finditer(texto):
        if m.start() > pos:
            par.add_run(texto[pos : m.start()])
        par.add_run(m.group(1)).bold = True
        pos = m.end()
    if pos < len(texto):
        par.add_run(texto[pos:])
    return par


def _docx_inserir_markdown(doc, texto_md: str) -> None:
    linhas = texto_md.splitlines()
    tabela_buffer: list[str] = []

    def descarregar_tabela():
        if not tabela_buffer:
            return
        linhas_tab = [
            [c.strip() for c in ln.strip("|").split("|")]
            for ln in tabela_buffer
            if not re.match(r"^\|?[\s:|-]+\|?$", ln)  # descarta linha ---|---
        ]
        if linhas_tab:
            tabela = doc.add_table(rows=len(linhas_tab), cols=len(linhas_tab[0]))
            tabela.style = "Table Grid"
            for i, linha in enumerate(linhas_tab):
                for j, celula in enumerate(linha[: len(tabela.columns)]):
                    tabela.cell(i, j).text = _limpar_inline(celula)
                    if i == 0:
                        for run in tabela.cell(i, j).paragraphs[0].runs or [
                            tabela.cell(i, j).paragraphs[0].add_run("")
                        ]:
                            run.bold = True
        tabela_buffer.clear()

    for linha in linhas:
        tipo, conteudo = _classificar_linha(linha)
        if tipo == "tabela":
            tabela_buffer.append(conteudo)
            continue
        descarregar_tabela()
        if tipo == "h1":
            doc.add_heading(_limpar_inline(conteudo), level=1)
        elif tipo == "h2":
            doc.add_heading(_limpar_inline(conteudo), level=2)
        elif tipo == "h3":
            doc.add_heading(_limpar_inline(conteudo), level=3)
        elif tipo == "item":
            _docx_paragrafo_com_negrito(doc, conteudo, estilo="List Bullet")
        elif tipo == "par":
            _docx_paragrafo_com_negrito(doc, conteudo)
    descarregar_tabela()


def _docx_aplicar_branding(doc, branding: dict | None) -> None:
    """
    Cabeçalho e rodapé institucionais no DOCX. Prioriza IMAGENS capturadas
    do modelo (inseridas na largura do conteúdo, na área de header/footer);
    sem imagem, usa TEXTO. A marca d'água translúcida é aplicada apenas no
    PDF (limitação do formato DOCX).
    """
    if not branding:
        return
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    img_cab = _img_bytes(branding, "cabecalho_img")
    img_rod = _img_bytes(branding, "rodape_img")
    secao = doc.sections[0]
    largura_conteudo = secao.page_width - secao.left_margin - secao.right_margin

    def _imagem(par, png: bytes):
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        par.add_run().add_picture(io.BytesIO(png), width=largura_conteudo)

    if img_cab:
        _imagem(secao.header.paragraphs[0], img_cab)
    elif branding.get("cabecalho"):
        par = secao.header.paragraphs[0]
        par.text = branding["cabecalho"]
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in par.runs:
            run.font.size = Pt(9)
            run.font.bold = True

    if img_rod:
        _imagem(secao.footer.paragraphs[0], img_rod)
    elif branding.get("rodape"):
        par = secao.footer.paragraphs[0]
        par.text = branding["rodape"]
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in par.runs:
            run.font.size = Pt(8)


def gerar_docx(titulo: str, texto_md: str, branding: dict | None = None) -> bytes:
    doc = _docx_novo()
    _docx_aplicar_branding(doc, branding)
    doc.add_heading(titulo, level=0)
    _docx_inserir_markdown(doc, texto_md)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def gerar_docx_consolidado(documentos: dict[str, str], branding: dict | None = None) -> bytes:
    doc = _docx_novo()
    _docx_aplicar_branding(doc, branding)
    doc.add_heading("Documentos da Fase Preparatória — Lei nº 14.133/2021", level=0)
    doc.add_paragraph(f"Dossiê gerado em {date.today().strftime('%d/%m/%Y')}.")
    for doc_key in SEQUENCIA_DOCUMENTOS:
        if doc_key not in documentos:
            continue
        doc.add_page_break()
        doc.add_heading(DOCUMENTOS[doc_key]["titulo"], level=1)
        _docx_inserir_markdown(doc, documentos[doc_key])
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
# As fontes nativas do fpdf2 usam Latin-1; substituímos os caracteres
# tipográficos comuns fora dessa tabela para não quebrar a exportação.
_SUBSTITUICOES_LATIN1 = {
    "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", "•": "-",
    " ": " ", "→": "->",
}


def _latin1_seguro(texto: str) -> str:
    for orig, subst in _SUBSTITUICOES_LATIN1.items():
        texto = texto.replace(orig, subst)
    return texto.encode("latin-1", errors="replace").decode("latin-1")


def _img_bytes(branding: dict, chave_b64: str, chave_legada: str = "") -> bytes | None:
    """Extrai PNG (bytes) de um campo base64 do branding, se houver."""
    from .branding import de_base64

    return de_base64((branding or {}).get(chave_b64) or "")


def _pdf_novo(branding: dict | None = None):
    """
    PDF A4 com identidade visual opcional do órgão.

    Prioriza IMAGENS capturadas de um documento-modelo (cabeçalho e rodapé
    carimbados na mesma posição relativa; marca d'água central translúcida).
    Sem imagens, cai para as versões em TEXTO (cabecalho/rodape/marca_dagua).
    branding pode conter: cabecalho_img, rodape_img, marca_img (base64 PNG),
    cabecalho_pct, rodape_pct (alturas em % da página) e os campos de texto.
    """
    from fpdf import FPDF

    b = branding or {}
    img_cab = _img_bytes(b, "cabecalho_img")
    img_rod = _img_bytes(b, "rodape_img")
    img_marca = _img_bytes(b, "marca_img")
    cab_pct = float(b.get("cabecalho_pct") or 14)
    rod_pct = float(b.get("rodape_pct") or 10)

    marca_txt = _latin1_seguro(b.get("marca_dagua") or "")
    cab_txt = _latin1_seguro(b.get("cabecalho") or "")
    rod_txt = _latin1_seguro(b.get("rodape") or "")

    # Alturas reservadas (mm) quando há imagem de cabeçalho/rodapé
    cab_h = (297.0 * cab_pct / 100.0) if img_cab else 0.0
    rod_h = (297.0 * rod_pct / 100.0) if img_rod else 0.0

    class PDFInstitucional(FPDF):
        def header(self):
            # Marca d'água (imagem central translúcida ou texto diagonal)
            if img_marca:
                larg = self.w * 0.7
                self.image(io.BytesIO(img_marca), x=(self.w - larg) / 2,
                           y=self.h * 0.28, w=larg)
            elif marca_txt:
                self.set_font("Helvetica", "B", 46)
                self.set_text_color(228, 228, 228)
                with self.rotation(45, self.w / 2, self.h / 2):
                    self.text(self.w / 2 - self.get_string_width(marca_txt) / 2,
                              self.h / 2, marca_txt)
                self.set_text_color(0, 0, 0)
            # Cabeçalho (imagem no topo, largura total) ou texto
            if img_cab:
                self.image(io.BytesIO(img_cab), x=0, y=0, w=self.w, h=cab_h)
            elif cab_txt:
                self.set_font("Helvetica", "B", 9)
                self.set_text_color(90, 90, 90)
                self.cell(0, 5, cab_txt, align="C", new_x="LMARGIN", new_y="NEXT")
                self.set_draw_color(200, 200, 200)
                self.line(self.l_margin, self.get_y() + 1,
                          self.w - self.r_margin, self.get_y() + 1)
                self.set_text_color(0, 0, 0)
            self.set_y(max(self.t_margin, cab_h + 4))

        def footer(self):
            if img_rod:
                self.image(io.BytesIO(img_rod), x=0, y=self.h - rod_h,
                           w=self.w, h=rod_h)
                return
            self.set_y(-14)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(120, 120, 120)
            if rod_txt:
                self.cell(0, 4, rod_txt, align="C", new_x="LMARGIN", new_y="NEXT")
            self.cell(0, 4, f"Página {self.page_no()}/{{nb}}", align="C")
            self.set_text_color(0, 0, 0)

    pdf = PDFInstitucional(format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=max(22, rod_h + 6))
    pdf.set_margins(left=20, top=max(20, cab_h + 6), right=20)
    return pdf


def _pdf_inserir_markdown(pdf, texto_md: str) -> None:
    largura = pdf.w - pdf.l_margin - pdf.r_margin
    for linha in texto_md.splitlines():
        tipo, conteudo = _classificar_linha(linha)
        conteudo = _latin1_seguro(_limpar_inline(conteudo))
        if tipo == "vazio":
            pdf.ln(3)
        elif tipo == "h1":
            pdf.set_font("Helvetica", "B", 14)
            pdf.multi_cell(largura, 7, conteudo)
            pdf.ln(1)
        elif tipo == "h2":
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(largura, 6, conteudo)
            pdf.ln(1)
        elif tipo == "h3":
            pdf.set_font("Helvetica", "B", 11)
            pdf.multi_cell(largura, 6, conteudo)
        elif tipo == "item":
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(largura, 5.5, "  -  " + conteudo)
        elif tipo == "tabela":
            pdf.set_font("Courier", "", 8)
            pdf.multi_cell(largura, 4.5, conteudo)
        else:
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(largura, 5.5, conteudo)


def _pdf_bytes(pdf) -> bytes:
    saida = pdf.output()
    return bytes(saida)


def gerar_pdf(titulo: str, texto_md: str, branding: dict | None = None) -> bytes:
    pdf = _pdf_novo(branding)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(pdf.w - 40, 8, _latin1_seguro(titulo),
                  new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    _pdf_inserir_markdown(pdf, texto_md)
    return _pdf_bytes(pdf)


def gerar_pdf_consolidado(documentos: dict[str, str], branding: dict | None = None) -> bytes:
    pdf = _pdf_novo(branding)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(
        pdf.w - 40, 8,
        _latin1_seguro("Documentos da Fase Preparatória - Lei nº 14.133/2021"),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(pdf.w - 40, 6, f"Dossiê gerado em {date.today().strftime('%d/%m/%Y')}.",
                  new_x="LMARGIN", new_y="NEXT")
    for doc_key in SEQUENCIA_DOCUMENTOS:
        if doc_key not in documentos:
            continue
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 15)
        pdf.multi_cell(pdf.w - 40, 8, _latin1_seguro(DOCUMENTOS[doc_key]["titulo"]),
                      new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        _pdf_inserir_markdown(pdf, documentos[doc_key])
    return _pdf_bytes(pdf)


# ---------------------------------------------------------------------------
# Pacote ZIP com todos os arquivos individuais
# ---------------------------------------------------------------------------
def gerar_zip(documentos: dict[str, str], formato: str, branding: dict | None = None) -> bytes:
    """`formato`: 'docx' ou 'pdf'. Zipa um arquivo por documento aprovado."""
    def gerador(titulo, texto):
        fn = gerar_docx if formato == "docx" else gerar_pdf
        return fn(titulo, texto, branding)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, doc_key in enumerate(SEQUENCIA_DOCUMENTOS, start=1):
            if doc_key not in documentos:
                continue
            meta = DOCUMENTOS[doc_key]
            nome = f"{i:02d}-{meta['sigla'].replace('/', '-')}.{formato}"
            zf.writestr(nome, gerador(meta["titulo"], documentos[doc_key]))
    return buffer.getvalue()
