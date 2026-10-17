"""
Amostras e comparativo do Relatório de Cotação (pacote de 16/10/2026).

Gera, a partir dos cenários SINTÉTICOS de `tests/relatorio_cotacao_apoio.py`
(os mesmos das provas), o relatório ANTERIOR (Markdown → export.gerar_pdf)
e o NOVO (projeção → DOCX → PDF) do MESMO snapshot, mede páginas, bytes,
links e tempo, e renderiza capturas PNG para homologação.

Uso:
    python scripts/relatorio_cotacao_amostras.py SAIDA [--sem-anterior]

Precisa do LibreOffice no PATH (o mesmo motor da produção). Nada aqui
toca banco, rede ou IA. Os dados são fictícios.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

MOMENTO = datetime(2026, 10, 16, 23, 30, tzinfo=timezone.utc)


def _marca_institucional() -> dict:
    """Timbrado SINTÉTICO desenhado aqui (nenhum ativo de terceiro)."""
    from PIL import Image, ImageDraw

    from PIL import ImageFont

    def fonte(tamanho, negrito=False):
        for nome in (("DejaVuSans-Bold.ttf" if negrito else "DejaVuSans.ttf"),
                     ("arialbd.ttf" if negrito else "arial.ttf")):
            try:
                return ImageFont.truetype(nome, tamanho)
            except OSError:
                continue
        return ImageFont.load_default()

    img = Image.new("RGB", (1600, 170), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 22, 170), fill=(27, 79, 138))
    d.text((60, 32), "PREFEITURA MUNICIPAL DE EXEMPLO (FICTÍCIA)",
           fill=(23, 32, 51), font=fonte(46, True))
    d.text((60, 100), "Secretaria de Administração — dados de demonstração",
           fill=(75, 85, 101), font=fonte(32))
    d.line((0, 166, 1600, 166), fill=(213, 221, 232), width=3)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return {"orgao": "Prefeitura Municipal de Exemplo (fictícia)",
            "cabecalho_img": base64.b64encode(buffer.getvalue()).decode()}


def _medir(pdf: bytes, segundos: float) -> dict:
    import pymupdf

    doc = pymupdf.open(stream=pdf)
    return {"paginas": len(doc), "bytes": len(pdf),
            "segundos": round(segundos, 1),
            "links": sum(len(p.get_links()) for p in doc),
            "fontes": sorted({f[3].split("+")[-1] for p in doc
                              for f in p.get_fonts()})}


def _png(pdf: bytes, paginas: list[int], prefixo: Path) -> list[str]:
    import pymupdf

    doc = pymupdf.open(stream=pdf)
    saidas = []
    for n in paginas:
        if 1 <= n <= len(doc):
            caminho = prefixo.with_name(f"{prefixo.name}_p{n:03d}.png")
            doc[n - 1].get_pixmap(dpi=110).save(caminho)
            saidas.append(caminho.name)
    return saidas


def main() -> int:
    from src import export
    from src.precos import documento_cotacao as dc
    from src.precos import relatorio
    from src.precos import relatorio_view as rv
    from tests.relatorio_cotacao_apoio import cenario

    parser = argparse.ArgumentParser()
    parser.add_argument("saida")
    parser.add_argument("--sem-anterior", action="store_true")
    args = parser.parse_args()
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)

    if export.motor_pdf() != "libreoffice":
        print("LibreOffice ausente: as amostras exigem o motor institucional")
        return 2

    plano = [
        # (rótulo, cenário, tipo, branding, páginas a capturar)
        ("compacto_5itens_871", "historico_5_871", "cotacao", None,
         [1, 2, 3, -1]),
        ("compacto_210itens", "processo_210", "cotacao", None, [1, 4, -1]),
        ("analitico_5itens_871", "historico_5_871", "analitico", None,
         [1, 2, -1]),
        ("institucional", "minima", "cotacao", "marca", [1, 2]),
        ("pendencias", "pendencias", "cotacao", None, [1, 2, 3]),
        ("vazio", "vazio", "cotacao", None, [1]),
    ]
    resultado: dict = {"emitido_em": MOMENTO.isoformat(),
                       "motor": export.motor_pdf(),
                       "renderer": dc.VERSAO_RENDERER, "amostras": {}}
    for rotulo, nome, tipo, marca, paginas in plano:
        pesquisa, itens, refs = cenario(nome)
        vista = rv.projetar(pesquisa, itens, refs, emitido_em=MOMENTO,
                            branding=_marca_institucional() if marca else None)
        inicio = time.perf_counter()
        if tipo == "cotacao":
            docx = dc.relatorio_de_cotacao_docx(vista)
            pdf = dc.em_pdf(docx, dict(vista.branding or {}) or None)
            (saida / f"{rotulo}.docx").write_bytes(docx)
        else:
            pdf = dc.relatorio_analitico_pdf(vista)
        novo = _medir(pdf, time.perf_counter() - inicio)
        (saida / f"{rotulo}.pdf").write_bytes(pdf)
        import pymupdf

        total = len(pymupdf.open(stream=pdf))
        novo["capturas"] = _png(pdf, [total if p == -1 else p
                                      for p in paginas], saida / rotulo)
        registro = {"cenario": nome, "itens": len(itens),
                    "referencias": vista.total_referencias,
                    "consideradas": vista.total_consideradas,
                    "subtotal_concluidos": str(vista.subtotal_concluidos),
                    "valor_global": (None if vista.valor_global is None
                                     else str(vista.valor_global)),
                    "hash_decisorio": vista.hash_decisorio, "novo": novo}
        if not args.sem_anterior and tipo == "cotacao" and itens:
            inicio = time.perf_counter()
            antigo = export.gerar_pdf(
                "Relatório de Pesquisa de Preços",
                relatorio.completo(pesquisa, itens, refs, emitido_em=MOMENTO))
            registro["anterior_completo"] = _medir(
                antigo, time.perf_counter() - inicio)
            (saida / f"{rotulo}_ANTERIOR.pdf").write_bytes(antigo)
            registro["anterior_completo"]["capturas"] = _png(
                antigo, [1, 4], saida / f"{rotulo}_ANTERIOR")
        resultado["amostras"][rotulo] = registro
        print(rotulo, json.dumps(novo, ensure_ascii=False), flush=True)

    pesquisa, itens, refs = cenario("historico_5_871")
    (saida / "memoria_analitica_5itens_871.xlsx").write_bytes(
        relatorio.xlsx_analitico(pesquisa, itens, refs))
    (saida / "metricas.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
