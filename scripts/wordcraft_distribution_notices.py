"""Collect bounded license texts for a conservative, filtered WASM Cargo closure.

Read-only source audit. No network, source/binary redistribution or legal approval.
Only normal/build edges rooted at wordcraft-web are followed; dev-only edges are
excluded. Cargo feature unification and build tools can overapproximate the linked
WASM. The input JSON alone cannot attest that --filter-platform was used.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT = 2 * 1024 * 1024
MAX_BUNDLE = 64 * 1024 * 1024
PERMISSIVE = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "0BSD",
                        "Zlib", "Unlicense", "BSL-1.0", "Unicode-3.0", "ISC", "CC0-1.0"})
SPECIAL = frozenset({"OFL-1.1", "Ubuntu-font-1.0"})
COPYLEFT = frozenset({"GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later",
                      "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0-only", "AGPL-3.0-only", "MPL-2.0"})
TEXT_EXTENSIONS = {"", ".txt", ".md", ".rst", ".html", ".apache", ".mit", ".bsd", ".isc", ".lib", ".gpl", ".lgpl", ".mpl"}
FONT_TEXTS = {"Hack-Regular.txt", "OFL.txt", "UFL.txt"}
UPSTREAM_EXTRA = ("assets/fonts/OFL-Inter.txt", "assets/fonts/OFL-JetBrainsMono.txt",
                  "assets/fonts/OFL-SourceSans3.txt", "assets/fonts/OFL-SourceSerif4.txt",
                  "docs/brand/LICENSE-brand.txt")


def _read(path: Path, limit: int) -> bytes:
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Input is missing, not a file or excessive")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Input exceeds its byte bound")
    return data


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, *args: str) -> str:
    environment = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            timeout=20, check=True, env=environment)
    if len(result.stdout) > 2 * 1024 * 1024:
        raise ValueError("Git provenance output excessive")
    return result.stdout.decode("utf-8").strip()


def closure(metadata: dict) -> tuple[dict, list[dict]]:
    """Use resolved filtered edges; never guess a dependency from its name."""
    packages = {item["id"]: item for item in metadata["packages"]}
    nodes = {item["id"]: item for item in metadata["resolve"]["nodes"]}
    if len(packages) != len(metadata["packages"]) or len(nodes) != len(metadata["resolve"]["nodes"]):
        raise ValueError("Ambiguous Cargo identifiers")
    roots = [item for item in packages.values() if item["name"] == "wordcraft-web" and item["source"] is None]
    if len(roots) != 1:
        raise ValueError("Exactly one workspace wordcraft-web root is required")
    seen, pending = set(), [roots[0]["id"]]
    while pending:
        identity = pending.pop()
        if identity in seen:
            continue
        if identity not in packages or identity not in nodes:
            raise ValueError("Cargo graph references a missing node")
        seen.add(identity)
        for edge in nodes[identity]["deps"]:
            kinds = edge["dep_kinds"]
            if not kinds or any(kind["kind"] not in {None, "build", "dev"} for kind in kinds):
                raise ValueError("Unknown dependency-kind semantics")
            if any(kind["kind"] in {None, "build"} for kind in kinds):
                pending.append(edge["pkg"])
    return roots[0], sorted((packages[item] for item in seen), key=lambda item: (item["name"], item["version"], item["source"] or ""))


def audit_spdx(raw: str | None) -> dict:
    if not isinstance(raw, str) or not raw.strip():
        return {"declared": raw, "normalized": None, "identifiers": [], "review": ["SPDX_MISSING"]}
    if len(raw) > 4096 or raw.count("(") > 32:
        return {"declared": raw, "normalized": None, "identifiers": [], "review": ["SPDX_EXPRESSION_EXCESSIVE"]}
    normalized = re.sub(r"\s*/\s*", " OR ", raw.strip())
    tokens = re.findall(r"[A-Za-z0-9.+-]+|[()]", normalized)
    review, identifiers = [], set()
    if re.sub(r"\s+", "", normalized) != "".join(tokens):
        review.append("SPDX_UNPARSED_CHARACTERS")
    position = 0

    def expression():
        nonlocal position
        atom()
        while position < len(tokens) and tokens[position] in {"AND", "OR"}:
            position += 1
            atom()

    def atom():
        nonlocal position
        if position >= len(tokens):
            raise ValueError("Incomplete SPDX")
        token = tokens[position]
        position += 1
        if token == "(":
            expression()
            if position >= len(tokens) or tokens[position] != ")":
                raise ValueError("Unbalanced SPDX")
            position += 1
        elif token in {"AND", "OR", ")", "WITH"}:
            raise ValueError("Unexpected SPDX operator")
        else:
            identifiers.add(token)

    try:
        expression()
        if position != len(tokens):
            raise ValueError("Unsupported SPDX expression")
    except ValueError:
        review.append("SPDX_EXPRESSION_UNRECOGNIZED")
    if identifiers - PERMISSIVE - SPECIAL - COPYLEFT:
        review.append("SPDX_IDENTIFIER_UNKNOWN")
    if identifiers & COPYLEFT:
        review.append("COPYLEFT_BRANCH_REQUIRES_EXPLICIT_REVIEW_OR_LICENSE_CHOICE")
    if identifiers & SPECIAL:
        review.append("SPECIAL_FONT_TERMS_REQUIRE_REVIEW")
    return {"declared": raw, "normalized": normalized, "identifiers": sorted(identifiers), "review": review}


def _is_notice(name: str) -> bool:
    upper = name.upper()
    return (bool(re.search(r"(?:^|[-_.])(?:LICENSE|LICENCE|COPYING|COPYRIGHT|NOTICE|ATTRIBUTION)(?:$|[-_.])", upper))
            or name in FONT_TEXTS or upper.startswith("OFL-"))


def _source_boundary(package: dict, upstream: Path, registry: Path, git: Path) -> tuple[str, Path, Path]:
    manifest = Path(package["manifest_path"]).resolve(strict=True)
    source = package["source"]
    if source is None:
        label, boundary = "upstream", upstream
    elif source.startswith("registry+"):
        if source != "registry+https://github.com/rust-lang/crates.io-index":
            raise ValueError("Registry source is not the approved public registry")
        if not manifest.is_relative_to(registry):
            raise ValueError("Registry manifest escaped its explicit root")
        label, boundary = "registry", manifest.parent
    elif source.startswith("git+"):
        uri = urlsplit(source.removeprefix("git+"))
        if uri.scheme != "https" or uri.hostname != "github.com" or uri.username or uri.password:
            raise ValueError("Git source is not a public HTTPS GitHub input")
        if not re.fullmatch(r"[0-9a-f]{40}", uri.fragment) or not manifest.is_relative_to(git):
            raise ValueError("Git source is not confined and commit-pinned")
        parts = manifest.relative_to(git).parts
        if len(parts) < 3:
            raise ValueError("Unexpected Cargo Git checkout layout")
        label, boundary = "git", git / parts[0] / parts[1]
        if not (boundary / ".git").exists() or _git(boundary, "rev-parse", "HEAD") != uri.fragment:
            raise ValueError("Git dependency HEAD differs from the resolved commit")
    else:
        raise ValueError("Unsupported package source")
    if not manifest.is_relative_to(boundary) or manifest.name != "Cargo.toml":
        raise ValueError("Package manifest escaped the authorized repository")
    return label, boundary, manifest.parent


def _candidates(package_root: Path, boundary: Path) -> tuple[set[Path], list[str]]:
    if not package_root.is_relative_to(boundary):
        raise ValueError("Package notice scan escaped its declared boundary")
    candidates, review, entries = set(), [], 0
    for directory, directories, files in os.walk(package_root, followlinks=False):
        parent = Path(directory)
        depth = len(parent.relative_to(package_root).parts)
        kept = []
        for name in directories:
            path = parent / name
            if name in {".git", "target", "node_modules", ".github"}:
                continue
            if path.is_symlink():
                review.append("SYMLINK_DIRECTORY_NOT_TRAVERSED")
                continue
            if depth >= 8:
                review.append("SOURCE_SCAN_DEPTH_LIMIT_REACHED")
                continue
            kept.append(name)
        directories[:] = kept
        entries += len(files)
        if entries > 50_000:
            review.append("SOURCE_SCAN_FILE_LIMIT_REACHED")
            break
        for name in files:
            if _is_notice(name):
                candidates.add(parent / name)
    # Only repository-scoped workspace/Git packages inherit parent notices.
    # Registry boundary equals the package root; sibling crates never qualify.
    parent = package_root
    while parent != boundary:
        parent = parent.parent
        if not parent.is_relative_to(boundary):
            raise ValueError("Parent license walk escaped the explicit boundary")
        candidates.update(path for path in parent.iterdir() if path.is_file() and _is_notice(path.name))
    return candidates, review


def collect(*, metadata_path: Path, upstream: Path, registry: Path, git: Path, output: Path) -> dict:
    upstream, registry, git = (path.resolve(strict=True) for path in (upstream, registry, git))
    if any(not path.is_dir() for path in (upstream, registry, git)):
        raise ValueError("Source roots must be explicit existing directories")
    output = output.resolve()
    if output.exists() or not output.parent.is_dir() or any(output.is_relative_to(path) for path in (upstream, registry, git)):
        raise ValueError("Output must be a new directory outside all source roots")
    pin = json.loads(_read(ROOT / "docs/wordcraft/upstream.lock.json", 64 * 1024))["commit"]
    if _git(upstream, "rev-parse", "HEAD") != pin:
        raise ValueError("Upstream HEAD differs from the audited pin")
    lock_raw = _read(upstream / "Cargo.lock", 4 * 1024 * 1024)
    lock_lf = lock_raw.replace(b"\r\n", b"\n")
    pinned_lock = (_git(upstream, "show", "HEAD:Cargo.lock") + "\n").encode("utf-8")
    if lock_lf != pinned_lock:
        raise ValueError("Cargo.lock differs from the pinned upstream")
    lock = tomllib.loads(lock_raw.decode("utf-8"))
    locked = {(item["name"], item["version"], item.get("source")) for item in lock["package"]}
    raw = _read(metadata_path, 12 * 1024 * 1024)
    root, packages = closure(json.loads(raw))
    if Path(root["manifest_path"]).resolve() != upstream / "apps/wordcraft-web/Cargo.toml":
        raise ValueError("The graph root does not belong to the audited checkout")
    files, records = {}, []
    for package in packages:
        if (package["name"], package["version"], package["source"]) not in locked:
            raise ValueError("Resolved package is absent from pinned Cargo.lock")
        label, boundary, package_root = _source_boundary(package, upstream, registry, git)
        candidates, review = _candidates(package_root, boundary)
        declared_file = package.get("license_file")
        if declared_file:
            candidates.add(package_root / declared_file)
        if package["name"] == "wordcraft-web":
            candidates.update(upstream / name for name in UPSTREAM_EXTRA)
        spdx = audit_spdx(package.get("license"))
        review += spdx["review"]
        collected, copyrights, root_license = [], set(), False
        for candidate in sorted(candidates):
            relative = candidate.relative_to(boundary).as_posix() if candidate.is_relative_to(boundary) else "OUTSIDE_DECLARED_BOUNDARY"
            if ".." in Path(relative).parts:
                relative = "OUTSIDE_DECLARED_BOUNDARY"
            try:
                resolved = candidate.resolve(strict=True)
                if not resolved.is_relative_to(boundary):
                    raise ValueError("License path escaped its declared source root")
                if candidate.suffix.lower() not in TEXT_EXTENSIONS:
                    raise ValueError("License candidate is not an allowed text file")
                content = _read(resolved, MAX_TEXT)
                text = content.decode("utf-8-sig")
                if not content or b"\0" in content:
                    raise ValueError("License text is empty or binary")
            except (ValueError, OSError, UnicodeError):
                review.append("LICENSE_CANDIDATE_MISSING_UNSAFE_OR_NON_TEXT:" + relative)
                continue
            digest = _hash(content)
            target = "licenses/" + digest + ".txt"
            files[target] = content
            collected.append({"path": target, "source_scope": label, "source_relative_path": relative,
                              "sha256": digest, "bytes": len(content)})
            for line in text.splitlines():
                if "copyright" in line.lower() or "©" in line:
                    copyrights.add(line.strip())
            if re.search(r"GNU (?:LESSER |AFFERO )?GENERAL PUBLIC LICENSE|Mozilla Public License", text, re.I):
                review.append("COPYLEFT_TEXT_PRESENT_REVIEW_APPLICABILITY:" + relative)
            if re.search(r"Reserved Font Name|UBUNTU FONT LICEN[CS]E|Bitstream Vera License", text, re.I):
                review.append("FONT_TEXT_TERMS_REQUIRE_SEPARATE_REVIEW:" + relative)
            if (candidate.parent == package_root and candidate.name.upper().startswith(("LICENSE", "LICENCE", "COPYING"))) or declared_file and candidate == package_root / declared_file:
                root_license = True
            if label in {"upstream", "git"} and candidate.parent == boundary and candidate.name.upper().startswith(("LICENSE", "LICENCE", "COPYING")):
                root_license = True
        if not collected:
            review.append("NO_LICENSE_OR_NOTICE_TEXT_FOUND")
        if not root_license:
            review.append("PACKAGE_CODE_LICENSE_TEXT_MISSING")
        records.append({"name": package["name"], "version": package["version"],
            "source": package["source"] or "pinned-workspace", "spdx": spdx,
            "status": "REVIEW" if review else "NOTICES_COLLECTED_REVIEW_STILL_REQUIRED",
            "review": sorted(set(review)), "files": collected, "copyright_lines": sorted(copyrights)})
    if sum(len(content) for content in files.values()) > MAX_BUNDLE:
        raise ValueError("Notice bundle exceeds its bounded text size")
    review_records = [item for item in records if item["review"]]
    manifest = {"schema": "gc-wordcraft-distribution-notices/v1", "status": "DISTRIBUTION_REVIEW_REQUIRED",
        "upstream_commit": pin, "cargo_lock_sha256_lf": _hash(lock_lf), "metadata_sha256": _hash(raw),
        "scope": {"root": "wordcraft-web", "asserted_metadata_filter": "wasm32-unknown-unknown",
            "edges": ["normal", "build"], "dev_only_edges": "excluded",
            "link_map": False, "metadata_filter_attested_by_json": False,
            "feature_unification_and_build_tools_may_overapproximate_runtime": True,
            "legal_approval": False, "source_or_binaries_copied": False,
            "license_text_coverage_is_not_inferred_from_spdx_or_neighbors": True},
        "counts": {"packages": len(records), "review_packages": len(review_records),
            "packages_without_any_text": sum(not item["files"] for item in records),
            "packages_missing_code_license_text": sum("PACKAGE_CODE_LICENSE_TEXT_MISSING" in item["review"] for item in records),
            "unique_text_files": len(files), "text_bytes": sum(map(len, files.values())),
            "source_kinds": dict(Counter("workspace" if item["source"] == "pinned-workspace" else item["source"].split("+", 1)[0] for item in records))},
        "packages": records,
        "files": [{"path": name, "sha256": _hash(content), "bytes": len(content)} for name, content in sorted(files.items())]}
    # Validate all source paths/text and construct the complete plan before writes.
    output.mkdir()
    (output / "licenses").mkdir()
    for name, content in sorted(files.items()):
        with (output / name).open("xb") as destination:
            destination.write(content)
    with (output / "manifest.json").open("xb") as destination:
        destination.write((json.dumps(manifest, ensure_ascii=True, indent=2) + "\n").encode("utf-8"))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--registry-src", type=Path, required=True)
    parser.add_argument("--git-checkouts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = collect(metadata_path=args.metadata, upstream=args.upstream, registry=args.registry_src,
                         git=args.git_checkouts, output=args.out)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        print("Distribution notice collection failed; no approval or complete bundle is claimed.")
        return 2
    print(json.dumps({"status": result["status"], "counts": result["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
