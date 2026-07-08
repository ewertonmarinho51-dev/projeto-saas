"""
Captura visual de identidade a partir de um documento-modelo (PDF/DOCX).

O administrador envia um documento oficial do órgão; o sistema renderiza
a 1ª página e recorta três faixas como imagens PNG:
  - cabeçalho   (faixa superior)
  - rodapé      (faixa inferior)
  - marca d'água (região central, aplicada com transparência no PDF)

As imagens são carimbadas nos documentos gerados mantendo EXATAMENTE a
mesma posição relativa (proporção da página A4), pois o recorte é feito
em porcentagem da altura/largura da página-modelo.

Dependências: PyMuPDF (render do PDF) e Pillow (recorte/opacidade).
DOCX é convertido para PDF via LibreOffice (soffice) quando disponível.
"""

import base64
import io
import os
import shutil
import subprocess
import tempfile

RENDER_DPI = 150  # resolução do render da página-modelo


class ErroBranding(Exception):
    """Erro de captura de identidade com mensagem amigável."""


# ---------------------------------------------------------------------------
# Entrada: PDF direto ou DOCX convertido para PDF
# ---------------------------------------------------------------------------
def _docx_para_pdf(dados: bytes) -> bytes:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise ErroBranding(
            "Para capturar identidade de arquivos DOCX é necessário o "
            "LibreOffice instalado no servidor. Envie um PDF ou instale o "
            "LibreOffice (packages.txt: libreoffice)."
        )
    with tempfile.TemporaryDirectory() as tmp:
        entrada = os.path.join(tmp, "modelo.docx")
        with open(entrada, "wb") as fh:
            fh.write(dados)
        try:
            subprocess.run(
                [soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, entrada],
                check=True, capture_output=True, timeout=90,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ErroBranding(f"Falha ao converter o DOCX: {exc}") from exc
        saida = os.path.join(tmp, "modelo.pdf")
        if not os.path.exists(saida):
            raise ErroBranding("A conversão do DOCX não gerou PDF.")
        with open(saida, "rb") as fh:
            return fh.read()


def _para_pdf(nome_arquivo: str, dados: bytes) -> bytes:
    extensao = nome_arquivo.rsplit(".", 1)[-1].lower() if "." in nome_arquivo else ""
    if extensao == "pdf":
        return dados
    if extensao == "docx":
        return _docx_para_pdf(dados)
    raise ErroBranding(f"Formato .{extensao or '?'} não suportado. Envie PDF ou DOCX.")


# ---------------------------------------------------------------------------
# Render da página-modelo
# ---------------------------------------------------------------------------
def renderizar_modelo(nome_arquivo: str, dados: bytes):
    """Renderiza a 1ª página do modelo e devolve uma imagem Pillow (RGB)."""
    from PIL import Image

    pdf_bytes = _para_pdf(nome_arquivo, dados)
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if doc.page_count == 0:
            raise ErroBranding("O documento-modelo não tem páginas.")
        pagina = doc.load_page(0)
        pix = pagina.get_pixmap(dpi=RENDER_DPI)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        doc.close()
        return img
    except ErroBranding:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ErroBranding(f"Não foi possível renderizar o modelo: {exc}") from exc


# ---------------------------------------------------------------------------
# Recorte das faixas (percentuais da página-modelo)
# ---------------------------------------------------------------------------
def _png_bytes(img) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def recortar_cabecalho(img, altura_pct: float) -> bytes:
    """Faixa superior: 0 até altura_pct (%) da altura da página."""
    larg, alt = img.size
    corte = max(1, int(alt * altura_pct / 100))
    return _png_bytes(img.crop((0, 0, larg, corte)))


def recortar_rodape(img, altura_pct: float) -> bytes:
    """Faixa inferior: últimos altura_pct (%) da altura da página."""
    larg, alt = img.size
    corte = max(1, int(alt * altura_pct / 100))
    return _png_bytes(img.crop((0, alt - corte, larg, alt)))


def recortar_marca_dagua(img, opacidade: float = 0.12) -> bytes:
    """
    Região central (miolo) da página como marca d'água, com opacidade
    reduzida embutida no PNG (RGBA). `opacidade` de 0 a 1.
    """
    from PIL import Image

    larg, alt = img.size
    # miolo: descarta 22% de topo e base (onde ficam cabeçalho/rodapé)
    caixa = img.crop((0, int(alt * 0.22), larg, int(alt * 0.78))).convert("RGBA")
    alpha = caixa.split()[3].point(lambda a: int(a * max(0.0, min(1.0, opacidade))))
    caixa.putalpha(alpha)
    return _png_bytes(caixa)


# ---------------------------------------------------------------------------
# Serialização para o banco (base64) e leitura de volta
# ---------------------------------------------------------------------------
def para_base64(png: bytes | None) -> str:
    return base64.b64encode(png).decode() if png else ""


def de_base64(texto: str | None) -> bytes | None:
    if not texto:
        return None
    try:
        return base64.b64decode(texto)
    except Exception:  # noqa: BLE001 — valor inválido: ignora
        return None
