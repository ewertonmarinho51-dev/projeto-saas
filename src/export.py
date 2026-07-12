"""
Exportação dos documentos aprovados para .docx e .pdf.

Os textos gerados pela IA vêm em Markdown simples (títulos #/##/###,
listas e negrito **texto**). Este módulo converte esse Markdown em um
DOCX ESTRUTURADO com os estilos institucionais dos documentos aprovados
(Times New Roman 12, espaçamento 1,5, 6 pt após parágrafo, texto
justificado, cláusulas numeradas em negrito, controle de linhas órfãs e
título preso ao conteúdo). O PDF é obtido preferencialmente CONVERTENDO
esse DOCX via LibreOffice — garantindo que DOCX e PDF tenham o mesmo
conteúdo e a mesma formatação; sem LibreOffice no ambiente, cai para o
renderizador fpdf2 (fonte Times), com aviso via motor_pdf().
"""

import io
import re
import shutil
import zipfile
from datetime import date

from .config import DOCUMENTOS, SEQUENCIA_DOCUMENTOS

# Padrão institucional (medido nos documentos manuais aprovados)
FONTE_CORPO = "Times New Roman"
TAMANHO_CORPO = 12          # pt
ESPACO_LINHAS = 1.5
ESPACO_DEPOIS = 6           # pt após parágrafos
MARGEM_SUP_CM = 2.5
MARGEM_INF_CM = 2.5
MARGEM_ESQ_CM = 2.0
MARGEM_DIR_CM = 2.0

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
def _definir_fonte(estilo, nome: str, tamanho_pt: float, negrito: bool = False):
    """Aplica a fonte também em rFonts hAnsi/cs (Word ignora só o ascii)."""
    from docx.oxml.ns import qn
    from docx.shared import Pt

    estilo.font.name = nome
    estilo.font.size = Pt(tamanho_pt)
    estilo.font.bold = negrito
    rpr = estilo.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        rfonts.set(qn(attr), nome)


def _novo_estilo(doc, nome: str, base: str = "Normal"):
    from docx.enum.style import WD_STYLE_TYPE

    try:
        estilo = doc.styles[nome]
    except KeyError:
        estilo = doc.styles.add_style(nome, WD_STYLE_TYPE.PARAGRAPH)
        if base:
            estilo.base_style = doc.styles[base]
    return estilo


def _docx_novo():
    """
    Documento A4 com os ESTILOS INSTITUCIONAIS centralizados (nada de
    formatação manual parágrafo a parágrafo):
      GovDocs Corpo / Titulo / Clausula / Item 1..3 / Tabela / Nota / Assinatura.
    """
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
    from docx.shared import Cm, Pt

    doc = Document()
    secao = doc.sections[0]
    secao.page_width, secao.page_height = Cm(21.0), Cm(29.7)  # A4
    secao.top_margin, secao.bottom_margin = Cm(MARGEM_SUP_CM), Cm(MARGEM_INF_CM)
    secao.left_margin, secao.right_margin = Cm(MARGEM_ESQ_CM), Cm(MARGEM_DIR_CM)

    def _paragrafo(estilo, *, alinhamento=WD_ALIGN_PARAGRAPH.JUSTIFY,
                   depois=ESPACO_DEPOIS, linhas=ESPACO_LINHAS, recuo_cm=0.0,
                   manter_com_proximo=False):
        pf = estilo.paragraph_format
        pf.alignment = alinhamento
        pf.space_after = Pt(depois)
        pf.space_before = Pt(0)
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = linhas
        pf.widow_control = True            # sem linhas órfãs/viúvas
        pf.keep_with_next = manter_com_proximo
        if recuo_cm:
            pf.left_indent = Cm(recuo_cm)

    # Normal = corpo (herdado por tudo)
    normal = doc.styles["Normal"]
    _definir_fonte(normal, FONTE_CORPO, TAMANHO_CORPO)
    _paragrafo(normal)

    corpo = _novo_estilo(doc, "GovDocs Corpo")
    _definir_fonte(corpo, FONTE_CORPO, TAMANHO_CORPO)
    _paragrafo(corpo)

    titulo = _novo_estilo(doc, "GovDocs Titulo")
    _definir_fonte(titulo, FONTE_CORPO, 14, negrito=True)
    _paragrafo(titulo, alinhamento=WD_ALIGN_PARAGRAPH.CENTER, depois=12,
               manter_com_proximo=True)

    clausula = _novo_estilo(doc, "GovDocs Clausula")
    _definir_fonte(clausula, FONTE_CORPO, TAMANHO_CORPO, negrito=True)
    _paragrafo(clausula, alinhamento=WD_ALIGN_PARAGRAPH.LEFT, depois=6,
               manter_com_proximo=True)  # título nunca separa do 1º parágrafo

    for nome, recuo in (("GovDocs Item 1", 0.75), ("GovDocs Item 2", 1.5),
                        ("GovDocs Item 3", 2.25)):
        item = _novo_estilo(doc, nome)
        _definir_fonte(item, FONTE_CORPO, TAMANHO_CORPO)
        _paragrafo(item, recuo_cm=recuo)

    nota = _novo_estilo(doc, "GovDocs Nota")
    _definir_fonte(nota, FONTE_CORPO, 10)
    _paragrafo(nota, depois=4, linhas=1.0)

    assin = _novo_estilo(doc, "GovDocs Assinatura")
    _definir_fonte(assin, FONTE_CORPO, TAMANHO_CORPO)
    _paragrafo(assin, alinhamento=WD_ALIGN_PARAGRAPH.CENTER, depois=0,
               manter_com_proximo=True)  # bloco de assinatura não divide
    return doc


# Links Markdown: [texto](url) — usados para compactar URLs (fonte de preço)
_RE_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def _segmentos_bold(texto: str) -> list[dict]:
    segs, pos = [], 0
    for m in _RE_NEGRITO.finditer(texto):
        if m.start() > pos:
            segs.append({"text": texto[pos : m.start()], "bold": False, "url": None})
        segs.append({"text": m.group(1), "bold": True, "url": None})
        pos = m.end()
    if pos < len(texto):
        segs.append({"text": texto[pos:], "bold": False, "url": None})
    return segs


def _segmentos_ricos(texto: str) -> list[dict]:
    """Divide o texto em trechos: negrito (**), links [t](url) e texto simples."""
    segs, pos = [], 0
    for m in _RE_LINK.finditer(texto):
        if m.start() > pos:
            segs.extend(_segmentos_bold(texto[pos : m.start()]))
        segs.append({"text": m.group(1), "bold": False, "url": m.group(2)})
        pos = m.end()
    if pos < len(texto):
        segs.extend(_segmentos_bold(texto[pos:]))
    return segs or [{"text": texto, "bold": False, "url": None}]


def _docx_hyperlink(par, url: str, texto: str) -> None:
    """Insere um hyperlink clicável (azul, sublinhado) no parágrafo."""
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    r_id = par.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    cor = OxmlElement("w:color"); cor.set(qn("w:val"), "1B4F8A")
    sub = OxmlElement("w:u"); sub.set(qn("w:val"), "single")
    rpr.append(cor); rpr.append(sub); run.append(rpr)
    t = OxmlElement("w:t"); t.text = texto; run.append(t)
    link.append(run)
    par._p.append(link)


def _docx_runs_ricos(par, texto: str) -> None:
    """Preenche o parágrafo com runs de negrito e hyperlinks compactos."""
    for seg in _segmentos_ricos(texto):
        if seg["url"]:
            _docx_hyperlink(par, seg["url"], seg["text"])
        elif seg["text"]:
            run = par.add_run(seg["text"])
            if seg["bold"]:
                # só marca quando positivo: run.bold=False anularia o negrito
                # herdado do estilo (ex.: títulos de cláusula)
                run.bold = True


def _docx_paragrafo_com_negrito(doc, texto: str, estilo: str | None = None):
    """Adiciona parágrafo com negrito (**) e links clicáveis [t](url)."""
    par = doc.add_paragraph(style=estilo)
    _docx_runs_ricos(par, texto)
    return par


# parágrafos que começam com numeração hierárquica: 1.1. / 1.1.1. / 1.1.1.1.
_RE_NIVEL = re.compile(r"^\s*\d{1,2}(\.\d{1,2}){1,3}\.?\s")


def _estilo_do_paragrafo(texto: str) -> str:
    """Estilo institucional conforme a profundidade da numeração do texto."""
    if "____" in texto:
        return "GovDocs Assinatura"
    m = _RE_NIVEL.match(texto)
    if not m:
        return "GovDocs Corpo"
    profundidade = m.group(0).count(".")  # 1.1.=2  1.1.1.=3  1.1.1.1.=4
    return {2: "GovDocs Item 1", 3: "GovDocs Item 2"}.get(profundidade,
                                                          "GovDocs Item 3")


def _docx_formatar_tabela(tabela) -> None:
    """Cabeçalho repetido por página, linha sem quebra e fonte do padrão."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    for i, linha in enumerate(tabela.rows):
        tr_pr = linha._tr.get_or_add_trPr()
        if i == 0:  # repete o cabeçalho nas páginas seguintes
            cab = OxmlElement("w:tblHeader")
            cab.set(qn("w:val"), "true")
            tr_pr.append(cab)
        sem_quebra = OxmlElement("w:cantSplit")  # linha não divide entre páginas
        tr_pr.append(sem_quebra)
        for cel in linha.cells:
            for par in cel.paragraphs:
                pf = par.paragraph_format
                pf.space_after = Pt(2)
                pf.line_spacing = 1.0
                for run in par.runs:
                    run.font.name = FONTE_CORPO
                    run.font.size = Pt(10)
                    if i == 0:
                        run.font.bold = True


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
            n_cols = max(len(l) for l in linhas_tab)
            linhas_tab = [l + [""] * (n_cols - len(l)) for l in linhas_tab]
            tabela = doc.add_table(rows=len(linhas_tab), cols=n_cols)
            tabela.style = "Table Grid"
            for i, linha in enumerate(linhas_tab):
                for j, celula in enumerate(linha[: len(tabela.columns)]):
                    par = tabela.cell(i, j).paragraphs[0]
                    if i == 0:  # cabeçalho: negrito, sem links
                        par.add_run(_limpar_inline(celula)).bold = True
                    else:
                        _docx_runs_ricos(par, celula)
            _docx_formatar_tabela(tabela)
        tabela_buffer.clear()

    for linha in linhas:
        tipo, conteudo = _classificar_linha(linha)
        if tipo == "tabela":
            tabela_buffer.append(conteudo)
            continue
        descarregar_tabela()
        if tipo in ("h1", "h2", "h3"):
            # cláusulas numeradas em negrito, presas ao 1º parágrafo
            _docx_paragrafo_com_negrito(
                doc, _limpar_inline(conteudo), estilo="GovDocs Clausula")
        elif tipo == "item":
            _docx_paragrafo_com_negrito(doc, "•  " + conteudo,
                                        estilo="GovDocs Item 1")
        elif tipo == "par":
            _docx_paragrafo_com_negrito(doc, conteudo,
                                        estilo=_estilo_do_paragrafo(conteudo))
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
    doc.add_paragraph(titulo.upper(), style="GovDocs Titulo")
    _docx_inserir_markdown(doc, texto_md)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def gerar_docx_consolidado(documentos: dict[str, str], branding: dict | None = None) -> bytes:
    doc = _docx_novo()
    _docx_aplicar_branding(doc, branding)
    doc.add_paragraph("DOCUMENTOS DA FASE PREPARATÓRIA — LEI Nº 14.133/2021",
                      style="GovDocs Titulo")
    doc.add_paragraph(f"Dossiê gerado em {date.today().strftime('%d/%m/%Y')}.",
                      style="GovDocs Nota")
    for doc_key in SEQUENCIA_DOCUMENTOS:
        if doc_key not in documentos:
            continue
        doc.add_page_break()
        doc.add_paragraph(DOCUMENTOS[doc_key]["titulo"].upper(),
                          style="GovDocs Titulo")
        _docx_inserir_markdown(doc, documentos[doc_key])
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# PDF — caminho principal: DOCX estilizado -> LibreOffice -> PDF
# ---------------------------------------------------------------------------
def motor_pdf() -> str:
    """'libreoffice' (DOCX convertido — padrão institucional fiel) ou
    'fpdf2' (fallback quando o LibreOffice não está no ambiente)."""
    return "libreoffice" if (shutil.which("soffice") or
                             shutil.which("libreoffice")) else "fpdf2"


def _docx_em_pdf(docx_bytes: bytes) -> bytes | None:
    """Converte DOCX em PDF com o LibreOffice; None se indisponível/falhar."""
    import os
    import subprocess
    import tempfile

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        entrada = os.path.join(tmp, "documento.docx")
        with open(entrada, "wb") as fh:
            fh.write(docx_bytes)
        try:
            subprocess.run(
                [soffice, "--headless", "--convert-to", "pdf",
                 "--outdir", tmp, entrada],
                check=True, capture_output=True, timeout=120,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
        saida = os.path.join(tmp, "documento.pdf")
        if not os.path.exists(saida):
            return None
        with open(saida, "rb") as fh:
            return fh.read()


def _pdf_aplicar_marca(pdf_bytes: bytes, branding: dict | None) -> bytes:
    """Marca d'água (imagem translúcida ou texto) SOB o texto, via PyMuPDF."""
    b = branding or {}
    img_marca = _img_bytes(b, "marca_img")
    texto_marca = (b.get("marca_dagua") or "").strip()
    if not img_marca and not texto_marca:
        return pdf_bytes
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for pagina in doc:
            w, h = pagina.rect.width, pagina.rect.height
            if img_marca:
                lado = w * 0.70
                rect = fitz.Rect((w - lado) / 2, h * 0.30,
                                 (w + lado) / 2, h * 0.30 + lado * 0.6)
                pagina.insert_image(rect, stream=img_marca, overlay=False)
            else:
                pagina.insert_text(
                    fitz.Point(w * 0.18, h * 0.60), texto_marca,
                    fontsize=48, rotate=90, color=(0.90, 0.90, 0.90),
                    overlay=False,
                )
        return doc.tobytes()
    except Exception:  # noqa: BLE001 — marca é acessório; nunca quebra o PDF
        return pdf_bytes


# ---------------------------------------------------------------------------
# PDF — fallback fpdf2 (sem LibreOffice no ambiente)
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


def _pdf_render_tabela(pdf, linhas_tab: list[str]) -> None:
    """
    Renderiza uma tabela Markdown como tabela real do fpdf2 (com links).

    O fpdf2 NÃO divide uma linha entre páginas: uma célula muito longa
    (ex.: descrição de item vinda de planilha) estoura a altura da página
    e levanta ValueError ("row ... too high"). Estratégia: tenta fontes
    decrescentes; em último caso, degrada para parágrafos "Rótulo: valor"
    — o download nunca pode quebrar.
    """
    linhas = [
        [_latin1_seguro(c.strip()) for c in ln.strip("|").split("|")]
        for ln in linhas_tab
        if not re.match(r"^\|?[\s:|-]+\|?$", ln)  # descarta a linha ---|---
    ]
    if not linhas:
        return
    n = max(len(l) for l in linhas)
    linhas = [l + [""] * (n - len(l)) for l in linhas]
    largura = pdf.w - pdf.l_margin - pdf.r_margin

    for fonte_pt, altura_linha in ((9, 5), (7, 3.5), (6, 3)):
        try:
            pdf.set_font("Times", "", fonte_pt)
            with pdf.table(markdown=True, first_row_as_headings=True,
                           line_height=altura_linha, width=largura) as tabela:
                for linha in linhas:
                    fpdf_linha = tabela.row()
                    for celula in linha:
                        fpdf_linha.cell(celula)
            pdf.ln(2)
            return
        except ValueError:
            continue  # linha alta demais até para esta fonte — reduz e tenta

    # Último recurso: conteúdo em parágrafos (nunca perde dados nem quebra)
    cabecalho = linhas[0]
    pdf.set_font("Times", "", 10)
    for linha in linhas[1:]:
        texto = "; ".join(
            f"{cab}: {val}" for cab, val in zip(cabecalho, linha) if val
        )
        pdf.multi_cell(largura, 5, _latin1_seguro(texto),
                       new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    pdf.ln(2)


def _pdf_inserir_markdown(pdf, texto_md: str) -> None:
    largura = pdf.w - pdf.l_margin - pdf.r_margin
    buffer_tab: list[str] = []

    def flush_tabela():
        if buffer_tab:
            _pdf_render_tabela(pdf, buffer_tab)
            buffer_tab.clear()

    for linha in texto_md.splitlines():
        tipo, conteudo = _classificar_linha(linha)
        if tipo == "tabela":
            buffer_tab.append(conteudo)
            continue
        flush_tabela()
        # títulos: sem marcação inline; corpo/itens: markdown (negrito e
        # links [texto](url) clicáveis e compactos)
        limpo = _latin1_seguro(_limpar_inline(conteudo))
        rico = _latin1_seguro(conteudo)
        if tipo == "vazio":
            pdf.ln(3)
        elif tipo == "h1":
            pdf.set_font("Times", "B", 13)
            pdf.multi_cell(largura, 7, limpo)
            pdf.ln(1)
        elif tipo == "h2":
            pdf.set_font("Times", "B", 12)
            pdf.multi_cell(largura, 6, limpo)
            pdf.ln(1)
        elif tipo == "h3":
            pdf.set_font("Times", "B", 12)
            pdf.multi_cell(largura, 6, limpo)
        elif tipo == "item":
            pdf.set_font("Times", "", 12)
            pdf.multi_cell(largura, 6.5, "  -  " + rico, markdown=True)
        else:
            pdf.set_font("Times", "", 12)
            pdf.multi_cell(largura, 6.5, rico, markdown=True)
    flush_tabela()


def _pdf_bytes(pdf) -> bytes:
    saida = pdf.output()
    return bytes(saida)


def gerar_pdf(titulo: str, texto_md: str, branding: dict | None = None) -> bytes:
    """
    PDF do documento. Caminho principal: DOCX estilizado -> LibreOffice
    (mesmo conteúdo/formatação do DOCX, Times 12/1,5/6pt/justificado).
    Fallback: renderizador fpdf2 (fonte Times nativa).
    """
    convertido = _docx_em_pdf(gerar_docx(titulo, texto_md, branding))
    if convertido:
        return _pdf_aplicar_marca(convertido, branding)

    pdf = _pdf_novo(branding)
    pdf.add_page()
    pdf.set_font("Times", "B", 14)
    pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin, 8,
                   _latin1_seguro(titulo.upper()), align="C",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    _pdf_inserir_markdown(pdf, texto_md)
    return _pdf_bytes(pdf)


def gerar_pdf_consolidado(documentos: dict[str, str], branding: dict | None = None) -> bytes:
    convertido = _docx_em_pdf(gerar_docx_consolidado(documentos, branding))
    if convertido:
        return _pdf_aplicar_marca(convertido, branding)

    pdf = _pdf_novo(branding)
    pdf.add_page()
    pdf.set_font("Times", "B", 14)
    largura = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.multi_cell(
        largura, 8,
        _latin1_seguro("DOCUMENTOS DA FASE PREPARATÓRIA - LEI Nº 14.133/2021"),
        align="C", new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_font("Times", "", 10)
    pdf.multi_cell(largura, 6, f"Dossiê gerado em {date.today().strftime('%d/%m/%Y')}.",
                   new_x="LMARGIN", new_y="NEXT")
    for doc_key in SEQUENCIA_DOCUMENTOS:
        if doc_key not in documentos:
            continue
        pdf.add_page()
        pdf.set_font("Times", "B", 13)
        pdf.multi_cell(largura, 8, _latin1_seguro(DOCUMENTOS[doc_key]["titulo"].upper()),
                       align="C", new_x="LMARGIN", new_y="NEXT")
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
