"""Generate synthetic fidelity inputs with the existing product exporter.

No tenant documents, network, database, AI calls or second export engine.
Decimal is an independent fixture oracle, not a new production calculator.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import planilha
from src.export import gerar_docx, gerar_pdf, motor_pdf

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def itens_sinteticos() -> list[dict]:
    return [{"codigo": f"GC-SYN-{i:04d}",
             "descricao": f"Material sintético {i:03d} para ensaio de tabela e paginação",
             "unidade": "UN", "quantidade": str(1 + i % 7),
             "valor_unitario": f"{100 + i // 10},{i % 100:02d}",
             "fonte": f"https://example.invalid/precos/{i}"} for i in range(1, 211)]


def tabela_sintetica() -> tuple[str, dict]:
    source = itens_sinteticos()
    expected = [Decimal(row["quantidade"]) * Decimal(row["valor_unitario"].replace(",", "."))
                for row in source]
    computed, total = planilha.calcular(source)
    if len(computed) != 210 or any(Decimal(str(row["valor_total"])) != wanted
                                  for row, wanted in zip(computed, expected)):
        raise ValueError("Existing calculator differs from the independent fixture oracle")
    if Decimal(str(total)) != sum(expected):
        raise ValueError("Existing global total differs from the fixture oracle")
    return planilha.para_markdown(computed, total), {
        "items": 210, "codes": [row["codigo"] for row in source],
        "line_totals_decimal": [str(value.quantize(Decimal("0.01"))) for value in expected],
        "global_total_decimal": str(sum(expected).quantize(Decimal("0.01")))}


def inspect_docx(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        page = root.find(f".//{W}pgSz")
        text = "\n".join(node.text or "" for node in root.iter(W + "t"))
        return {"page_twips": {key.rsplit("}", 1)[-1]: value for key, value in page.attrib.items()},
                "table_rows": [len(table.findall(W + "tr")) for table in root.iter(W + "tbl")],
                "hyperlinks": len(list(root.iter(W + "hyperlink"))),
                "headers": len([name for name in archive.namelist() if name.startswith("word/header") and name.endswith(".xml")]),
                "footers": len([name for name in archive.namelist() if name.startswith("word/footer") and name.endswith(".xml")]),
                "text": text}


def generate(output: Path, *, pdf=False) -> dict:
    if pdf and motor_pdf() != "libreoffice":
        raise ValueError("Visual reference requires the real institutional LibreOffice engine")
    table, oracle = tabela_sintetica()
    intro = ("Corpus inteiramente sintético para comparar importação, edição e exportação. "
             "Não representa processo administrativo, órgão ou assinatura real.\n\n")
    signatures = ("\n\n## Assinaturas de teste\n\n**Pessoa Sintética A**\n\n"
                  "Responsável fictício pelo ensaio\n\n**Pessoa Sintética B**\n\nRevisor fictício\n")
    cases = {
        "01-texto-listas-links": ("Ensaio de texto listas e links", intro +
            "# Objeto sintético\n\nParágrafo com **negrito**, *itálico* e caracteres ç ã é §.\n\n"
            "## Requisitos\n\n- Preservar primeiro item\n- Preservar segundo item\n\n"
            "1. Etapa inicial\n2. Etapa final\n\n[Referência sintética](https://example.invalid/referencia)\n", None, ""),
        "02-tabela-210-itens": ("Ensaio da planilha com 210 itens", intro + table, None, ""),
        "03-timbrado-assinaturas": ("Ensaio de identidade e assinaturas", intro +
            "# Identidade institucional sintética\n\nO cabeçalho e o rodapé devem permanecer na página A4.\n\n"
            "## Quadro de teste\n\n| Campo | Valor |\n|---|---|\n| Revisão | Sintética 1 |\n| Escopo | Ensaio local |\n",
            {"cabecalho": "ÓRGÃO SINTÉTICO PARA TESTES DE FIDELIDADE",
             "rodape": "Ensaio GovConnect sem validade administrativa"}, signatures),
    }
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": "gc-wordcraft-corpus/v1", "synthetic_only": True,
                "status": "INPUTS_GENERATED_NOT_ROUNDTRIP_APPROVED", "oracle": oracle, "cases": []}
    for name, (title, markdown, branding, signature) in cases.items():
        data = gerar_docx(title, markdown, branding, signature)
        inspection = inspect_docx(data)
        if inspection["page_twips"] != {"w": "11906", "h": "16838"}:
            raise ValueError("Existing export is not the expected A4 fixture")
        if name.startswith("02") and any(code not in inspection["text"] for code in oracle["codes"]):
            raise ValueError("The exported fixture dropped an item")
        (output / (name + ".docx")).write_bytes(data)
        (output / (name + ".md")).write_text(markdown + signature, encoding="utf-8")
        inspection.pop("text")
        entry = {"name": name, "sha256_docx": hashlib.sha256(data).hexdigest(), **inspection}
        if pdf:
            from pypdf import PdfReader
            rendered = gerar_pdf(title, markdown, branding, signature)
            if motor_pdf() != "libreoffice":
                raise ValueError("PDF fallback cannot approve the institutional reference")
            reader = PdfReader(io.BytesIO(rendered))
            extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
            if name.startswith("02") and any(code not in extracted for code in oracle["codes"]):
                raise ValueError("PDF reference dropped or split a synthetic item code")
            if name.startswith("03") and any(label not in extracted for label in
                    (branding["cabecalho"], branding["rodape"], "Pessoa Sintética A", "Pessoa Sintética B")):
                raise ValueError("PDF reference lost institutional text or signatures")
            (output / (name + ".pdf")).write_bytes(rendered)
            entry.update(sha256_pdf=hashlib.sha256(rendered).hexdigest(), pages=len(reader.pages),
                         pdf_engine=motor_pdf(), visual_review="PENDING")
        manifest["cases"].append(entry)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pdf", action="store_true", help="Require the institutional LibreOffice engine")
    args = parser.parse_args()
    print(json.dumps(generate(args.out, pdf=args.pdf), ensure_ascii=False, indent=2))
