"""Run the verified full synthetic corpus through the actual pinned WASM worker.

Outputs are private QA artifacts in a fresh workspace directory. A refusal or
fidelity difference is retained per case and makes the run fail. No browser,
database, AI call, hosted Supabase or deployment is involved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

from wordcraft_corpus import ROOT, text_blocks, verify_full_inputs, _verificar_entrada_docx

sys.path.insert(0, str(ROOT))
from src.wordcraft_native import importar_docx, exportar, validar


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(inputs: Path, output: Path, *, node: Path, bundle: Path, manifest_sha256: str) -> dict:
    manifest = verify_full_inputs(inputs)
    inputs, output = inputs.resolve(strict=True), output.resolve()
    work = ROOT.parent.resolve()
    if (not output.is_relative_to(work) or output.is_relative_to(ROOT.resolve())
            or output == work or output.exists() or output.is_relative_to(inputs)
            or inputs.is_relative_to(output)):
        raise ValueError("Fresh private QA directory under work required")
    if not node.is_absolute() or not node.is_file():
        raise ValueError("Explicit installed Node executable required")
    runtime = dict(node=node, bundle=bundle.resolve(strict=True), manifest_sha256=manifest_sha256)
    output.mkdir(parents=True)
    report = {"schema":"gc-wordcraft-full-roundtrip/v1", "synthetic_only":True,
        "status":"NATIVE_EXECUTION_FIDELITY_NOT_APPROVED", "visual_review":"PENDING",
        "input_manifest_sha256":digest((inputs / "full-manifest.json").read_bytes()),
        "engine_manifest_sha256":manifest_sha256, "cases":[]}
    failures = 0
    for case in manifest["cases"]:
        for variant in case["variants"]:
            entry = {"case":case["id"], "source":variant["docx"], "steps":{}}
            report["cases"].append(entry)
            source = (inputs / variant["docx"]).read_bytes()
            target = output / case["id"] / Path(variant["docx"]).stem
            target.mkdir(parents=True)
            entry["source_sha256"] = digest(source)
            start = time.perf_counter()
            try:
                content = importar_docx(source, **runtime)
                validar(content, **runtime)
                (target / "checkpoint.json").write_bytes(content)
                entry["checkpoint_sha256"] = digest(content)
                entry["checkpoint_bytes"] = len(content)
                entry["steps"]["native_import_and_validation"] = "PASS"
            except Exception as error:
                entry["steps"]["native_import_and_validation"] = "REFUSED_" + type(error).__name__
                entry["elapsed_ms"] = round((time.perf_counter()-start)*1000,2)
                failures += 1
                print(json.dumps({"case":entry["source"],"import":"REFUSED","error_type":type(error).__name__}),flush=True)
                continue
            for fmt in ("docx","pdf"):
                stage = "export_" + fmt
                try:
                    artifact = exportar(content, formato=fmt, **runtime)
                    (target / ("roundtrip." + fmt)).write_bytes(artifact)
                    entry["steps"]["export_"+fmt] = "PASS"
                    entry[fmt+"_sha256"] = digest(artifact)
                    entry[fmt+"_bytes"] = len(artifact)
                    if fmt == "docx":
                        stage = "ordered_text_stories_links"
                        entry["steps"]["ordered_text_stories_links"] = "PASS" if text_blocks(source) == text_blocks(artifact) else "DIFFERENT"
                        oracle = json.loads((inputs / variant["oracle"]).read_bytes())
                        stage = "source_oracles_and_structures"
                        try:
                            _verificar_entrada_docx(artifact,oracle)
                            entry["steps"]["source_oracles_and_structures"] = "PASS"
                        except ValueError as error:
                            # This message comes only from our fixture checker,
                            # contains no native exception or document text.
                            entry["steps"]["source_oracles_and_structures"] = "DIFFERENT"
                            entry["oracle_difference"] = str(error)
                        stage = "reimport_exported_docx"
                        reopened = importar_docx(artifact, **runtime)
                        (target / "reimported-checkpoint.json").write_bytes(reopened)
                        entry["steps"]["reimport_exported_docx"] = "PASS"
                    else:
                        stage = "pdf_parsing"
                        from pypdf import PdfReader
                        import io
                        pdf = PdfReader(io.BytesIO(artifact))
                        entry["steps"][stage] = "PASS"
                        entry["pdf_pages"] = len(pdf.pages)
                        pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                        oracle = json.loads((inputs / variant["oracle"]).read_bytes())
                        entry["pdf_item_code_count"] = len(oracle.get("codes", []))
                        entry["pdf_item_code_coverage"] = "CHECKED" if entry["pdf_item_code_count"] else "NOT_APPLICABLE"
                        stage = "pdf_item_codes"
                        entry["steps"]["pdf_item_codes"] = "PASS" if all(code in pdf_text for code in oracle.get("codes",[])) else "DIFFERENT"
                except Exception as error:
                    entry["steps"][stage] = "REFUSED_" + type(error).__name__
            entry["elapsed_ms"] = round((time.perf_counter()-start)*1000,2)
            if any(value != "PASS" for value in entry["steps"].values()):
                failures += 1
            print(json.dumps({"case":entry["source"],"steps":entry["steps"],"pdf_pages":entry.get("pdf_pages")}),flush=True)
    report["cases_with_failure_or_difference"] = failures
    report["variant_count"] = len(report["cases"])
    (output / "comparison.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs","out","node","bundle"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--manifest-sha256",required=True)
    args = parser.parse_args()
    report = run(args.inputs,args.out,node=args.node,bundle=args.bundle,manifest_sha256=args.manifest_sha256)
    print(json.dumps({"variants":report["variant_count"],"failures_or_differences":report["cases_with_failure_or_difference"],"visual_review":"PENDING"}))
    return int(bool(report["cases_with_failure_or_difference"]))


if __name__ == "__main__":
    raise SystemExit(main())
