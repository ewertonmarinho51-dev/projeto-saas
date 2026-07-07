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


def gerar_docx(titulo: str, texto_md: str) -> bytes:
    doc = _docx_novo()
    doc.add_heading(titulo, level=0)
    _docx_inserir_markdown(doc, texto_md)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def gerar_docx_consolidado(documentos: dict[str, str]) -> bytes:
    doc = _docx_novo()
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


def _pdf_novo():
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(left=20, top=20, right=20)
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


def gerar_pdf(titulo: str, texto_md: str) -> bytes:
    pdf = _pdf_novo()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(pdf.w - 40, 8, _latin1_seguro(titulo))
    pdf.ln(4)
    _pdf_inserir_markdown(pdf, texto_md)
    return _pdf_bytes(pdf)


def gerar_pdf_consolidado(documentos: dict[str, str]) -> bytes:
    pdf = _pdf_novo()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(
        pdf.w - 40, 8,
        _latin1_seguro("Documentos da Fase Preparatória - Lei nº 14.133/2021"),
    )
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(pdf.w - 40, 6, f"Dossiê gerado em {date.today().strftime('%d/%m/%Y')}.")
    for doc_key in SEQUENCIA_DOCUMENTOS:
        if doc_key not in documentos:
            continue
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 15)
        pdf.multi_cell(pdf.w - 40, 8, _latin1_seguro(DOCUMENTOS[doc_key]["titulo"]))
        pdf.ln(3)
        _pdf_inserir_markdown(pdf, documentos[doc_key])
    return _pdf_bytes(pdf)


# ---------------------------------------------------------------------------
# Pacote ZIP com todos os arquivos individuais
# ---------------------------------------------------------------------------
def gerar_zip(documentos: dict[str, str], formato: str) -> bytes:
    """`formato`: 'docx' ou 'pdf'. Zipa um arquivo por documento aprovado."""
    gerador = gerar_docx if formato == "docx" else gerar_pdf
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, doc_key in enumerate(SEQUENCIA_DOCUMENTOS, start=1):
            if doc_key not in documentos:
                continue
            meta = DOCUMENTOS[doc_key]
            nome = f"{i:02d}-{meta['sigla'].replace('/', '-')}.{formato}"
            zf.writestr(nome, gerador(meta["titulo"], documentos[doc_key]))
    return buffer.getvalue()
