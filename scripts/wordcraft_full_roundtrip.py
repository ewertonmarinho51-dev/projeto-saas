"""Run the verified full synthetic corpus through the actual pinned WASM worker.

Outputs are private QA artifacts in a fresh workspace directory. A refusal or
fidelity difference is retained per case and makes the run fail. No browser,
database, AI call, hosted Supabase or deployment is involved.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import zipfile

from wordcraft_corpus import (ROOT, inspect_full_docx, text_blocks,
                              verify_full_inputs, _verificar_entrada_docx)

sys.path.insert(0, str(ROOT))
from src.wordcraft_native import aplicar_patch, importar_docx, exportar, validar


def digest(data):
    return hashlib.sha256(data).hexdigest()


C10_EDIT_FROM = "C10-EXTERNAL"
C10_EDIT_TO = "C10-EXTERNAL-EDITED"


def _replace_json_text_once(value, old: str, new: str):
    """Apply one controlled editor mutation without depending on model layout."""
    count = 0

    def visit(item):
        nonlocal count
        if isinstance(item, str):
            occurrences = item.count(old)
            count += occurrences
            return item.replace(old, new)
        if isinstance(item, list):
            return [visit(child) for child in item]
        if isinstance(item, dict):
            return {key: visit(child) for key, child in item.items()}
        return item

    changed = visit(value)
    if count != 1:
        raise ValueError(f"controlled edit target count differs: {count}")
    return changed


def _c10_patch_plan(content: bytes) -> dict:
    """Build the same bounded native replace command used by product patches."""
    model = json.loads(content)
    matches = []
    occurrences = 0
    for index, block in enumerate(model["document"]["body"]):
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            occurrences += block["text"].count(C10_EDIT_FROM)
            start = block["text"].find(C10_EDIT_FROM)
            if start >= 0:
                matches.append((index, block["text"], start))
    if occurrences != 1 or len(matches) != 1:
        raise ValueError(f"controlled edit target count differs: {occurrences}")
    index, text, start_chars = matches[0]
    start_byte = len(text[:start_chars].encode("utf-8"))
    old_bytes = C10_EDIT_FROM.encode("utf-8")
    return {
        "schema": "gc-wordcraft-native-patch/v1",
        "source_hash": digest(content),
        "source_revision": 1,
        "operations": [{
            "op": "replace_text", "story": "body", "path": [index],
            "start_byte": start_byte, "end_byte": start_byte + len(old_bytes),
            "old_text": C10_EDIT_FROM, "new_text": C10_EDIT_TO,
        }],
    }


def _declared_feature_snapshot(docx: bytes) -> dict:
    """Measure every feature that C10 declares, including the PAGE field."""
    inspected = inspect_full_docx(docx)
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        footer_xml = b"\n".join(archive.read(name) for name in archive.namelist()
                                 if name.startswith("word/footer") and name.endswith(".xml"))
    return {
        "nested_table": inspected["table_rows"] == [2, 2],
        "horizontal_merge": inspected["horizontal_spans"] == [2],
        "header": inspected["headers"] == 1,
        "footer": inspected["footers"] == 1,
        "page_field": b"PAGE" in footer_xml,
        "page_break": inspected["explicit_page_breaks"] == 1,
    }


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
            stage = "native_import_and_validation"
            try:
                content = importar_docx(source, **runtime)
                validar(content, **runtime)
                entry["steps"][stage] = "PASS"
                if case["id"] == "C10":
                    stage = "controlled_edit"
                    content = aplicar_patch(
                        content, revision=1, plano=_c10_patch_plan(content), **runtime)
                    validar(content, **runtime)
                    entry["steps"][stage] = "PASS"
                (target / "checkpoint.json").write_bytes(content)
                entry["checkpoint_sha256"] = digest(content)
                entry["checkpoint_bytes"] = len(content)
            except Exception as error:
                entry["steps"][stage] = "REFUSED_" + type(error).__name__
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
                        expected_blocks = text_blocks(source)
                        if case["id"] == "C10":
                            expected_blocks = _replace_json_text_once(
                                expected_blocks, C10_EDIT_FROM, C10_EDIT_TO)
                        entry["steps"]["ordered_text_stories_links"] = "PASS" if expected_blocks == text_blocks(artifact) else "DIFFERENT"
                        oracle = json.loads((inputs / variant["oracle"]).read_bytes())
                        if case["id"] == "C10":
                            oracle = _replace_json_text_once(
                                oracle, C10_EDIT_FROM, C10_EDIT_TO)
                        stage = "source_oracles_and_structures"
                        try:
                            _verificar_entrada_docx(artifact,oracle)
                            entry["steps"]["source_oracles_and_structures"] = "PASS"
                        except ValueError as error:
                            # This message comes only from our fixture checker,
                            # contains no native exception or document text.
                            entry["steps"]["source_oracles_and_structures"] = "DIFFERENT"
                            entry["oracle_difference"] = str(error)
                        if case["id"] == "C10":
                            stage = "declared_feature_fidelity"
                            before = _declared_feature_snapshot(source)
                            after = _declared_feature_snapshot(artifact)
                            entry["declared_features_before"] = before
                            entry["declared_features_after"] = after
                            entry["steps"][stage] = (
                                "PASS" if before == after and all(after.values()) else "DIFFERENT")
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
