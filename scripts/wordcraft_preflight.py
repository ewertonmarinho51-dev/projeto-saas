"""Read-only local build preflight. No network, install, DB, flag or LLM calls.

Usage: python scripts/wordcraft_preflight.py --source ../wordcraft
Exit 0 means build prerequisites found; it never certifies the integration.
Exit 2 means blocked. JSON on stdout is suitable for a milestone report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("Cargo.toml", "Cargo.lock", "AGENTS.md", "LICENSE-MIT", "LICENSE-APACHE",
            "NOTICE", "ATTRIBUTION.md", "docs/brand/LICENSE-brand.txt",
            "apps/wordcraft-web/src/main.rs", "apps/wordcraft-web/src/web.rs",
            "apps/wordcraft-web/Trunk.toml")


def run(args, cwd=None):
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20,
                           stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return -1, "unavailable"


def inspect(source: Path):
    lock = json.loads((ROOT / "docs/wordcraft/upstream.lock.json").read_text(encoding="utf-8"))
    blockers = []
    tools = {}
    for name in ("git", "rustc", "cargo", "rustup", "trunk"):
        executable = shutil.which(name)
        code, version = run([executable, "--version"]) if executable else (-1, "missing")
        tools[name] = {"available": code == 0, "version": version}
        if code != 0:
            blockers.append(f"tool:{name}")
    rust_version = re.search(r"rustc (\d+)\.(\d+)", tools["rustc"]["version"])
    minimum = tuple(int(n) for n in lock["minimum_rust"].split("."))
    if rust_version and tuple(map(int, rust_version.groups())) < minimum:
        blockers.append("tool:rust_version_below_minimum")
    source = source.resolve()
    files = {}
    for rel in REQUIRED:
        path = source / rel
        if not path.is_file():
            blockers.append(f"source:{rel}")
        else:
            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    head = None
    if (source / ".git").exists() and tools["git"]["available"]:
        code, head = run(["git", "rev-parse", "HEAD"], source)
        if code or head != lock["commit"]:
            blockers.append("source:commit_mismatch")
        code, dirty = run(["git", "status", "--porcelain"], source)
        if code or dirty:
            blockers.append("source:uncommitted_changes_require_patch_manifest")
    else:
        blockers.append("source:git_provenance_unavailable")
    if tools["rustup"]["available"]:
        code, targets = run(["rustup", "target", "list", "--installed"])
        if code or "wasm32-unknown-unknown" not in targets.splitlines():
            blockers.append("tool:wasm32-unknown-unknown")
    return {"status": "BLOCKED" if blockers else "PREREQUISITES_FOUND_NOT_BUILT",
            "expected_commit": lock["commit"], "observed_commit": head,
            "tools": tools, "source_hashes": files, "blockers": blockers,
            "gate1": "NOT_RUN", "production_changed": False}


def verify_baseline(archive: Path, run_metadata: dict, source: Path, lock: dict) -> dict:
    """Verify immutable prior evidence, never substitute for adapter checks/build."""
    if (run_metadata.get("id") != lock["baseline_run"]
            or run_metadata.get("status") != "completed" or run_metadata.get("conclusion") != "success"
            or run_metadata.get("head_sha") != lock["baseline_govconnect_commit"]
            or (run_metadata.get("repository") or {}).get("full_name") != "ewertonmarinho51-dev/projeto-saas"):
        raise ValueError("Baseline run identity or successful conclusion differs")
    code, head = run(["git", "rev-parse", "HEAD"], source)
    if code or head != lock["commit"]:
        raise ValueError("Current upstream checkout differs from the baseline pin")
    code, changed = run(["git", "status", "--porcelain"], source)
    if code or changed:
        raise ValueError("Baseline reuse requires an unmodified upstream checkout")
    if archive.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("Baseline evidence archive exceeds its bounded size")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != lock["baseline_artifact_sha256"]:
        raise ValueError("Baseline artifact digest differs")
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if (len(entries) > 100 or len({e.filename for e in entries}) != len(entries)
                or sum(e.file_size for e in entries) > 16 * 1024 * 1024):
            raise ValueError("Baseline archive contents exceed their bounds")
        if bundle.read("upstream-sha.txt").decode("ascii").strip() != lock["commit"]:
            raise ValueError("Baseline evidence belongs to another upstream")
        recorded = bundle.read("Cargo.lock.sha256").decode("ascii").strip()
        match = re.fullmatch(r"([0-9a-f]{64})\s+Cargo\.lock", recorded)
        current = hashlib.sha256((source / "Cargo.lock").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if match is None or match[1] != current:
            raise ValueError("Baseline lockfile differs from the current pinned input")
    return {"status": "BASELINE_EVIDENCE_VERIFIED_NOT_ADAPTER_APPROVED", "upstream_commit": head,
            "baseline_run": lock["baseline_run"], "artifact_sha256": lock["baseline_artifact_sha256"],
            "gate1": "NOT_RUN"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--baseline-zip", type=Path)
    parser.add_argument("--run-metadata", type=Path)
    args = parser.parse_args()
    if args.baseline_zip or args.run_metadata:
        if not args.baseline_zip or not args.run_metadata:
            parser.error("baseline verification needs both archive and run metadata")
        lock = json.loads((ROOT / "docs/wordcraft/upstream.lock.json").read_text(encoding="utf-8"))
        result = verify_baseline(args.baseline_zip, json.loads(args.run_metadata.read_text(encoding="utf-8")), args.source, lock)
        print(json.dumps(result, indent=2))
        return 0
    result = inspect(args.source)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
