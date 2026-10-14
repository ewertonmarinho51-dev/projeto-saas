"""Stage hash-verified JS/WASM/notices in an explicitly marked local QA lab.

No network, server setup, production deployment, documents or credentials. Obtain
the expected artifact digest and producer commit from the authenticated CI read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = ROOT.parent
MARKER = "LOCAL_WORDCRAFT_QA_ONLY\n"
MAX_ARCHIVE = 100 * 1024 * 1024
MAX_TOTAL = 200 * 1024 * 1024


def safe_name(value):
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._/-]+", value)
            or value.startswith("/") or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise ValueError("Unsafe local asset path")
    return value


def install(archive: Path, lab: Path, *, artifact_sha256: str, producer_commit: str) -> dict:
    lab = lab.resolve(strict=True)
    if (not lab.is_relative_to(WORK_ROOT.resolve()) or lab == ROOT.resolve()
            or (lab / ".wordcraft-local-qa").read_text(encoding="utf-8") != MARKER):
        raise ValueError("Destination is not an explicitly marked isolated QA lab")
    pin = json.loads((ROOT / "docs/wordcraft/upstream.lock.json").read_text(encoding="utf-8"))["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", producer_commit) or not re.fullmatch(r"[0-9a-f]{64}", artifact_sha256):
        raise ValueError("Expected CI commit and artifact digest are mandatory")
    if archive.stat().st_size > MAX_ARCHIVE or hashlib.sha256(archive.read_bytes()).hexdigest() != artifact_sha256:
        raise ValueError("Artifact archive size or digest differs")
    plan = []
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if (len(entries) > 256 or len({item.filename for item in entries}) != len(entries)
                or sum(item.file_size for item in entries) > MAX_TOTAL):
            raise ValueError("Artifact archive is ambiguous or too large")
        for item in entries:
            safe_name(item.filename.rstrip("/"))
        manifest = json.loads(bundle.read("qa-manifest.json"))
        if (manifest.get("status") != "INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED"
                or manifest.get("upstream_commit") != pin
                or manifest.get("govconnect_commit") != producer_commit):
            raise ValueError("Artifact producer or upstream pin differs")
        assets = manifest["files"]
        if not isinstance(assets, list) or not 2 <= len(assets) <= 100:
            raise ValueError("Invalid asset inventory")
        for entry in assets:
            name = safe_name(entry["path"])
            if not name.endswith((".js", ".wasm")) or name.startswith("notices/"):
                raise ValueError("Only JS/WASM assets belong to the public QA namespace")
            content = bundle.read(name)
            if (type(entry["bytes"]) is not int or not 0 < entry["bytes"] <= 80 * 1024 * 1024
                    or len(content) != entry["bytes"] or hashlib.sha256(content).hexdigest() != entry["sha256"]):
                raise ValueError("Asset size or digest differs")
            if name.endswith(".wasm") and not content.startswith(b"\0asm\x01\0\0\0"):
                raise ValueError("Invalid WASM file header")
            plan.append((name, content))
        modules = [name for name, _ in plan if "/" not in name and name.endswith(".js")]
        binaries = [name for name, _ in plan if "/" not in name and name.endswith(".wasm")]
        if len(modules) != 1 or len(binaries) != 1 or len({name for name, _ in plan}) != len(plan):
            raise ValueError("Ambiguous root module/WASM inventory")
        notices_bytes = bundle.read("notices/manifest.json")
        notices = json.loads(notices_bytes)
        if notices.get("status") != "UPSTREAM_AND_FONT_NOTICES_VERIFIED" or notices.get("upstream_commit") != pin:
            raise ValueError("Required upstream/font notices were not verified")
        notice_paths = [safe_name(entry["path"]) for entry in notices["files"]]
        if len(notice_paths) != 13 or len(set(notice_paths)) != 13:
            raise ValueError("Pinned upstream/font notice inventory differs")
        for entry in notices["files"]:
            relative = safe_name(entry["path"])
            content = bundle.read("notices/" + relative)
            if (len(content) > 200_000 or b"\0" in content
                    or hashlib.sha256(content).hexdigest() != entry["sha256_canonical_lf"]):
                raise ValueError("Notice text digest differs")
            content.decode("utf-8")
            plan.append(("notices/" + relative, content))
        plan.extend([("notices/manifest.json", notices_bytes), ("qa-manifest.json", bundle.read("qa-manifest.json"))])
    destination = lab / "static/wordcraft"
    resolved = destination.resolve()
    if not resolved.is_relative_to(lab) or resolved == lab:
        raise ValueError("Static namespace escaped the QA lab")
    allowed = {name for name, _ in plan}
    if len(allowed) != len(plan):
        raise ValueError("Duplicate staged asset/notice paths")
    if destination.exists():
        for existing in destination.rglob("*"):
            if existing.is_file() and existing.relative_to(destination).as_posix() not in allowed:
                raise ValueError("QA namespace contains unrelated files; nothing overwritten")
    writes = []
    for name, content in plan:
        target = (destination / name).resolve()
        if not target.is_relative_to(resolved) or target == resolved:
            raise ValueError("Asset destination escaped its namespace")
        if target.exists() and (not target.is_file() or target.read_bytes() != content):
            raise ValueError("Existing QA asset differs; use a new isolated lab")
        writes.append((target, content))
    # Validate the complete bundle and destination before creating any asset.
    for target, content in writes:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {"status": "STAGED_FOR_LOCAL_QA_ONLY", "producer_commit": producer_commit,
            "artifact_sha256": artifact_sha256, "module_url": "/app/static/wordcraft/" + modules[0],
            "wasm_url": "/app/static/wordcraft/" + binaries[0]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--producer-commit", required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.archive, args.lab, artifact_sha256=args.artifact_sha256,
                             producer_commit=args.producer_commit), indent=2))
