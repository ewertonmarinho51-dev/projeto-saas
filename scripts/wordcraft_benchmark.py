"""Measure the real process-per-operation native IPC on reviewed synthetic cases.

No document output, database, network, provider calls or browser-memory claims.
All three checkpoints must match the pinned synthetic DOCX text/links before a
measurement report can be written. Paths and the trusted bundle pin are server
configuration, never browser input.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import time
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import wordcraft_corpus as corpus
from src.wordcraft_native import MAX_BYTES, exportar, importar_docx, validar


def _bounded_file(path: Path, maximum: int) -> bytes:
    if not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError("Missing or excessive local benchmark input")
    with path.open("rb") as stream:
        content = stream.read(maximum + 1)
    if not 0 < len(content) <= maximum:
        raise ValueError("Benchmark input changed or exceeds its byte bound")
    return content


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _closed_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def _synthetic_paged_docx(pages: int = 100) -> bytes:
    """Create a deterministic in-memory scale fixture, never a product exporter."""
    if type(pages) is not int or not 1 <= pages <= 100:
        raise ValueError("Synthetic page count is outside the benchmark bound")
    from docx import Document
    document = Document()
    document.core_properties.title = "GovConnect WordCraft synthetic scale benchmark"
    document.core_properties.subject = "No tenant or production data"
    for page in range(1, pages + 1):
        document.add_heading(f"GC-SCALE-PAGE-{page:03d}", level=1)
        document.add_paragraph("Conteúdo sintético determinístico para medição local do motor nativo.")
        if page < pages:
            document.add_page_break()
    raw = io.BytesIO()
    document.save(raw)
    # python-docx writes current ZIP timestamps. Normalize the package so its
    # hash identifies the fixture definition rather than the execution clock.
    normalized = io.BytesIO()
    with ZipFile(io.BytesIO(raw.getvalue())) as source, ZipFile(normalized, "w", ZIP_DEFLATED) as target:
        for name in sorted(source.namelist()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            target.writestr(info, source.read(name))
    return normalized.getvalue()


def _pdf_pages(content: bytes) -> int:
    from pypdf import PdfReader
    return len(PdfReader(io.BytesIO(content)).pages)


def _runtime(node: Path, bundle: Path, manifest_sha256: str) -> dict:
    if not node.is_absolute() or not node.is_file() or not bundle.is_absolute() or not bundle.is_dir():
        raise ValueError("Explicit local runtime and bundle are required")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        raise ValueError("Explicit trusted manifest SHA-256 is required")
    raw = _bounded_file(bundle / "qa-manifest.json", 128 * 1024)
    if _sha(raw) != manifest_sha256:
        raise ValueError("The local engine manifest differs from its trusted pin")
    manifest = json.loads(raw)
    if (manifest.get("status") != "INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED"
            or not re.fullmatch(r"[0-9a-f]{40}", manifest.get("upstream_commit", ""))
            or not re.fullmatch(r"[0-9a-f]{40}", manifest.get("govconnect_commit", ""))):
        raise ValueError("Unexpected engine provenance")
    environment = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "TEMP", "TMP") if name in os.environ}
    version = subprocess.run([str(node), "--version"], capture_output=True, timeout=10,
                             env=environment, cwd=bundle, check=False)
    if (version.returncode != 0 or len(version.stdout) > 100
            or not re.fullmatch(rb"v[0-9]+\.[0-9]+\.[0-9]+\r?\n?", version.stdout)):
        raise ValueError("Node did not confirm its version")
    return {"node_version": version.stdout.decode("ascii").strip(),
            "python_version": platform.python_version(), "platform": sys.platform,
            "machine": platform.machine(), "engine_manifest_sha256": manifest_sha256,
            "wordcraft_commit": manifest["upstream_commit"],
            "engine_govconnect_commit": manifest["govconnect_commit"]}


def _summary(samples: list[dict]) -> dict:
    values = sorted(sample["elapsed_ms"] for sample in samples)
    result = {"samples": samples, "sample_count": len(values),
            "median_ms": statistics.median(values),
            "p95_ms_nearest_rank": values[math.ceil(0.95 * len(values)) - 1],
            "minimum_ms": values[0], "maximum_ms": values[-1]}
    if "output_bytes" in samples[0]:
        sizes = [sample["output_bytes"] for sample in samples]
        result["output_bytes"] = {"minimum": min(sizes), "maximum": max(sizes),
                                  "median": statistics.median(sizes)}
    return result


def benchmark(*, node: Path, bundle: Path, manifest_sha256: str, inputs: Path,
              checkpoints: Path, repetitions: int) -> dict:
    if type(repetitions) is not int or not 1 <= repetitions <= 10:
        raise ValueError("Repetitions must be an integer from 1 to 10")
    if not node.is_absolute() or not bundle.is_absolute():
        raise ValueError("Explicit absolute Node and bundle paths are required")
    # Only this repository's reviewed, versioned synthetic corpus may enter the
    # benchmark. A different folder marked synthetic is not sufficient proof.
    inputs = inputs.resolve()
    if inputs != (ROOT / "tests/fixtures/wordcraft").resolve():
        raise ValueError("Only the repository's reviewed synthetic corpus is supported")
    manifest = corpus.verify_inputs(inputs)
    node, bundle, checkpoints = node.resolve(), bundle.resolve(), checkpoints.resolve()
    runtime = _runtime(node, bundle, manifest_sha256)
    kwargs = {"node": node, "bundle": bundle, "manifest_sha256": manifest_sha256}
    names = sorted(Path(item["path"]).stem for item in manifest["files"])
    if (not checkpoints.is_dir()
            or sorted(path.name for path in checkpoints.iterdir() if path.is_dir()) != names):
        raise ValueError("Checkpoint cases differ from the reviewed corpus")

    admitted = []
    # Complete admission for ALL cases before recording samples. Exported DOCX
    # bytes remain in memory; failures cannot leave a partial document/report.
    for item in manifest["files"]:
        name = Path(item["path"]).stem
        path = (checkpoints / name / "checkpoint.json").resolve()
        if not path.is_relative_to(checkpoints):
            raise ValueError("Checkpoint escaped the explicit local root")
        checkpoint = _bounded_file(path, MAX_BYTES)
        source = _bounded_file(inputs / item["path"], MAX_BYTES)
        if _sha(source) != item["sha256"]:
            raise ValueError("Synthetic fixture changed during admission")
        expected = corpus.text_blocks(source)
        validar(checkpoint, **kwargs)
        docx = exportar(checkpoint, formato="docx", **kwargs)
        if corpus.text_blocks(docx) != expected:
            raise ValueError("Native checkpoint differs from the reviewed synthetic fixture")
        if name.startswith("02"):
            text = "\n".join(expected["body"])
            if any(code not in text for code in manifest["oracle"]["codes"]):
                raise ValueError("Synthetic table does not retain all 210 item codes")
        admitted.append((name, source, checkpoint, expected))

    cases = []
    for name, source, checkpoint, expected in admitted:
        operations = {"validate": [], "export_docx": [], "export_pdf": []}
        for _ in range(repetitions):
            started = time.perf_counter_ns()
            validar(checkpoint, **kwargs)
            operations["validate"].append({"elapsed_ms": (time.perf_counter_ns() - started) / 1_000_000})
            for format in ("docx", "pdf"):
                started = time.perf_counter_ns()
                content = exportar(checkpoint, formato=format, **kwargs)
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                # Correctness checks are outside the operation timer. Every
                # measured DOCX still has to correspond to its synthetic source.
                if format == "docx" and corpus.text_blocks(content) != expected:
                    raise ValueError("A measured export changed synthetic content")
                operations["export_" + format].append({"elapsed_ms": elapsed_ms,
                    "output_bytes": len(content), "output_sha256": _sha(content),
                    "bytes_ratio_to_source_docx": len(content) / len(source),
                    "bytes_ratio_to_native_checkpoint": len(content) / len(checkpoint)})
        cases.append({"case": name, "source_docx_sha256": _sha(source),
            "source_docx_bytes": len(source), "native_checkpoint_schema": "gc-wordcraft-snapshot/v1",
            "native_checkpoint_sha256": _sha(checkpoint), "native_checkpoint_bytes": len(checkpoint),
            "native_bytes_ratio_to_source_docx": len(checkpoint) / len(source),
            "synthetic_semantic_text_links_headers_footers": "PASS",
            "table_item_codes_verified": 210 if name.startswith("02") else None,
            "operations": {key: _summary(samples) for key, samples in operations.items()}})
    return {"schema": "gc-wordcraft-native-benchmark/v1",
        "status": "LOCAL_SYNTHETIC_OBSERVATIONS_NOT_PRODUCTION_ACCEPTANCE",
        "measured_at_utc": datetime.now(timezone.utc).isoformat(), "runtime": runtime,
        "method": {"repetitions_per_operation_and_case": repetitions,
            "process_model": "NEW_NODE_PROCESS_PER_OPERATION",
            "clock": "time.perf_counter_ns",
            "includes": ["process_spawn", "asset_hash_verification", "wasm_initialization", "native_operation", "ipc"],
            "p95_definition": "Empirical nearest rank: sorted_samples[ceil(0.95*n)-1]; maximum for n<=10",
            "admission": "All 3 checkpoints validated and reexported DOCX semantically compared before timing",
            "warm_start_measured": False, "browser_startup_measured": False, "browser_memory_measured": False,
            "visual_fidelity_approved": False, "twenty_and_hundred_page_cases_measured": False},
        "cases": cases}


def benchmark_full_roundtrip(*, node: Path, bundle: Path, manifest_sha256: str,
                             roundtrip: Path, repetitions: int) -> dict:
    """Measure every artifact admitted by the canonical full-roundtrip receipt."""
    if type(repetitions) is not int or not 1 <= repetitions <= 10:
        raise ValueError("Repetitions must be an integer from 1 to 10")
    root = roundtrip.resolve()
    receipt_path = root / "comparison.json"
    receipt = json.loads(_bounded_file(receipt_path, 512 * 1024),
                         object_pairs_hook=_closed_object)
    if (not isinstance(receipt, dict)
            or receipt.get("schema") != "gc-wordcraft-full-roundtrip/v1"
            or receipt.get("status") != "NATIVE_EXECUTION_FIDELITY_NOT_APPROVED"
            or receipt.get("engine_manifest_sha256") != manifest_sha256
            or not isinstance(receipt.get("cases"), list)
            or len(receipt["cases"]) != 16):
        raise ValueError("Full-roundtrip receipt is incomplete or belongs to another engine")
    runtime = _runtime(node.resolve(), bundle.resolve(), manifest_sha256)
    kwargs = {"node": node.resolve(), "bundle": bundle.resolve(),
              "manifest_sha256": manifest_sha256}
    admitted = []
    identities = set()
    for entry in receipt["cases"]:
        required = {"case", "source", "checkpoint_sha256", "checkpoint_bytes",
                    "docx_sha256", "docx_bytes", "pdf_sha256", "pdf_bytes",
                    "pdf_pages", "pdf_item_code_count", "steps"}
        if (not isinstance(entry, dict) or not required <= entry.keys()
                or not isinstance(entry["source"], str)):
            raise ValueError("Malformed full-roundtrip case")
        relative = Path(entry["source"]).with_suffix("")
        case_root = (root / relative).resolve()
        if not case_root.is_relative_to(root) or (entry["case"], entry["source"]) in identities:
            raise ValueError("Full-roundtrip case escaped its root or was duplicated")
        identities.add((entry["case"], entry["source"]))
        checkpoint = _bounded_file(case_root / "checkpoint.json", MAX_BYTES)
        expected_docx = _bounded_file(case_root / "roundtrip.docx", MAX_BYTES)
        expected_pdf = _bounded_file(case_root / "roundtrip.pdf", MAX_BYTES * 4)
        for content, digest, size in (
                (checkpoint, entry["checkpoint_sha256"], entry["checkpoint_bytes"]),
                (expected_docx, entry["docx_sha256"], entry["docx_bytes"]),
                (expected_pdf, entry["pdf_sha256"], entry["pdf_bytes"])):
            if _sha(content) != digest or len(content) != size:
                raise ValueError("Full-roundtrip artifact differs from its receipt")
        if set(entry["steps"].values()) != {"PASS"}:
            raise ValueError("Full-roundtrip case did not pass every native step")
        admitted.append((entry, checkpoint))

    # No native process starts until every path, receipt field and artifact hash
    # has been admitted. A malformed later case cannot leave partial execution.
    for entry, checkpoint in admitted:
        validar(checkpoint, **kwargs)
        if (_sha(exportar(checkpoint, formato="docx", **kwargs)) != entry["docx_sha256"]
                or _sha(exportar(checkpoint, formato="pdf", **kwargs)) != entry["pdf_sha256"]):
            raise ValueError("Current engine does not reproduce the admitted roundtrip")

    cases = []
    for entry, checkpoint in admitted:
        operations = {"validate": [], "export_docx": [], "export_pdf": []}
        for _ in range(repetitions):
            started = time.perf_counter_ns()
            validar(checkpoint, **kwargs)
            operations["validate"].append({"elapsed_ms": (time.perf_counter_ns() - started) / 1_000_000})
            for format in ("docx", "pdf"):
                started = time.perf_counter_ns()
                content = exportar(checkpoint, formato=format, **kwargs)
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                if _sha(content) != entry[format + "_sha256"]:
                    raise ValueError("Measured export differs from admitted artifact")
                operations["export_" + format].append({"elapsed_ms": elapsed_ms,
                    "output_bytes": len(content), "output_sha256": _sha(content)})
        cases.append({"case": entry["case"], "source": entry["source"],
            "pdf_pages": entry["pdf_pages"],
            "pdf_item_code_count": entry["pdf_item_code_count"],
            "native_checkpoint_sha256": entry["checkpoint_sha256"],
            "native_checkpoint_bytes": len(checkpoint),
            "operations": {key: _summary(samples) for key, samples in operations.items()}})

    scale_profiles = []
    for pages in (20, 100):
        scale_source = _synthetic_paged_docx(pages)
        scale_checkpoint = importar_docx(scale_source, **kwargs)
        validar(scale_checkpoint, **kwargs)
        scale_pdf = exportar(scale_checkpoint, formato="pdf", **kwargs)
        if _pdf_pages(scale_pdf) != pages:
            raise ValueError(f"Native {pages}-page scale fixture changed its page count")
        scale_operations = {"import_docx": [], "validate": [], "export_pdf": []}
        for _ in range(repetitions):
            started = time.perf_counter_ns()
            imported = importar_docx(scale_source, **kwargs)
            scale_operations["import_docx"].append({"elapsed_ms": (time.perf_counter_ns() - started) / 1_000_000,
                "output_bytes": len(imported)})
            if _sha(imported) != _sha(scale_checkpoint):
                raise ValueError(f"Repeated {pages}-page import changed its checkpoint")
            started = time.perf_counter_ns()
            validar(scale_checkpoint, **kwargs)
            scale_operations["validate"].append({"elapsed_ms": (time.perf_counter_ns() - started) / 1_000_000})
            started = time.perf_counter_ns()
            rendered = exportar(scale_checkpoint, formato="pdf", **kwargs)
            scale_operations["export_pdf"].append({"elapsed_ms": (time.perf_counter_ns() - started) / 1_000_000,
                "output_bytes": len(rendered), "output_sha256": _sha(rendered)})
            if _sha(rendered) != _sha(scale_pdf) or _pdf_pages(rendered) != pages:
                raise ValueError(f"Repeated {pages}-page export changed its admitted PDF")
        scale_profiles.append({"profile": f"synthetic-explicit-breaks-{pages}-pages",
            "source_docx_sha256": _sha(scale_source), "source_docx_bytes": len(scale_source),
            "native_checkpoint_sha256": _sha(scale_checkpoint), "native_checkpoint_bytes": len(scale_checkpoint),
            "pdf_sha256": _sha(scale_pdf), "pdf_bytes": len(scale_pdf), "pdf_pages": pages,
            "operations": {key: _summary(samples) for key, samples in scale_operations.items()}})
    return {"schema": "gc-wordcraft-native-benchmark/v2",
        "status": "LOCAL_FULL_SYNTHETIC_OBSERVATIONS_NOT_PRODUCTION_ACCEPTANCE",
        "measured_at_utc": datetime.now(timezone.utc).isoformat(), "runtime": runtime,
        "method": {"repetitions_per_operation_and_case": repetitions,
            "process_model": "NEW_NODE_PROCESS_PER_OPERATION",
            "clock": "time.perf_counter_ns",
            "includes": ["process_spawn", "asset_hash_verification", "wasm_initialization", "native_operation", "ipc"],
            "p95_definition": "Empirical nearest rank: sorted_samples[ceil(0.95*n)-1]; maximum for n<=10",
            "admission": "All 16 canonical full-roundtrip artifacts and hashes verified before timing",
            "browser_startup_measured": False, "browser_memory_measured": False,
            "scale_page_counts_measured": [20, 100], "scale_measurement_kind": "native_import_validate_export_not_browser_open",
            "visual_fidelity_approved": False},
        "coverage": {"case_count": len(cases),
            "maximum_pdf_pages": max(case["pdf_pages"] for case in cases),
            "contains_at_least_twenty_pages": any(case["pdf_pages"] >= 20 for case in cases),
            "contains_210_item_case": any(case["pdf_item_code_count"] == 210 for case in cases),
            "contains_20_page_scale_profile": True, "contains_100_page_scale_profile": True},
        "cases": cases, "scale_profiles": scale_profiles}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--inputs", type=Path, default=ROOT / "tests/fixtures/wordcraft")
    parser.add_argument("--checkpoints", type=Path)
    parser.add_argument("--full-roundtrip", type=Path)
    parser.add_argument("--repetitions", type=int, default=3, choices=range(1, 11))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    destination = args.out.resolve()
    if destination.exists() or not destination.parent.is_dir() or destination.suffix.lower() != ".json":
        parser.error("Output must be a new .json file in an existing directory")
    try:
        if (args.checkpoints is None) == (args.full_roundtrip is None):
            parser.error("Choose exactly one of --checkpoints or --full-roundtrip")
        if args.full_roundtrip is not None:
            result = benchmark_full_roundtrip(node=args.node, bundle=args.bundle,
                manifest_sha256=args.manifest_sha256, roundtrip=args.full_roundtrip,
                repetitions=args.repetitions)
        else:
            result = benchmark(node=args.node, bundle=args.bundle, manifest_sha256=args.manifest_sha256,
                               inputs=args.inputs, checkpoints=args.checkpoints, repetitions=args.repetitions)
        encoded = (json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
        with destination.open("xb") as output:
            output.write(encoded)
    except Exception:
        # No native exception, document payload or arbitrary input path is echoed.
        print("Benchmark refused or failed; no benchmark result was confirmed.", file=sys.stderr)
        return 2
    print(f"{len(result['cases'])} reviewed synthetic cases measured; local benchmark JSON written; no document artifact persisted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
