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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.source)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
