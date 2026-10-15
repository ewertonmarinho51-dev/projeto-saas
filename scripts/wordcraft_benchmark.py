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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import wordcraft_corpus as corpus
from src.wordcraft_native import MAX_BYTES, exportar, validar


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--inputs", type=Path, default=ROOT / "tests/fixtures/wordcraft")
    parser.add_argument("--checkpoints", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3, choices=range(1, 11))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    destination = args.out.resolve()
    if destination.exists() or not destination.parent.is_dir() or destination.suffix.lower() != ".json":
        parser.error("Output must be a new .json file in an existing directory")
    try:
        result = benchmark(node=args.node, bundle=args.bundle, manifest_sha256=args.manifest_sha256,
                           inputs=args.inputs, checkpoints=args.checkpoints, repetitions=args.repetitions)
        encoded = (json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
        with destination.open("xb") as output:
            output.write(encoded)
    except Exception:
        # No native exception, document payload or arbitrary input path is echoed.
        print("Benchmark refused or failed; no benchmark result was confirmed.", file=sys.stderr)
        return 2
    print("3 reviewed synthetic cases measured; local benchmark JSON written; no document artifact persisted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
