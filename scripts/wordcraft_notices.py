"""Consolidate upstream/font notices from pinned build inputs, never font binaries.

This is a scoped build check, not approval of every Cargo dependency's license.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FONT_SOURCE = ROOT / "integrations/wordcraft/licenses/epaint_default_fonts"
UPSTREAM_FILES = ("LICENSE-MIT", "LICENSE-APACHE", "NOTICE", "ATTRIBUTION.md", "docs/brand/LICENSE-brand.txt")
UPSTREAM_FONTS = ("OFL-Inter.txt", "OFL-JetBrainsMono.txt", "OFL-SourceSans3.txt", "OFL-SourceSerif4.txt")


def canonical(data: bytes) -> bytes:
    if len(data) > 200_000 or b"\0" in data:
        raise ValueError("License input is not bounded text")
    return (data.decode("utf-8").replace("\r\n", "\n").rstrip("\r\n") + "\n").encode("utf-8")


def confined(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Notice path escapes its declared root")
    return target


def collect(metadata_path: Path, upstream: Path, output: Path) -> dict:
    upstream = upstream.resolve(strict=True)
    output = output.resolve()
    if output.is_relative_to(upstream):
        raise ValueError("Notices must be written outside the upstream checkout")
    pin = json.loads((ROOT / "docs/wordcraft/upstream.lock.json").read_text(encoding="utf-8"))["commit"]
    observed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=upstream,
                              capture_output=True, text=True, timeout=20, check=True).stdout.strip()
    if observed != pin:
        raise ValueError("Notice source does not match the audited upstream SHA")
    provenance = json.loads((FONT_SOURCE / "PROVENANCE.json").read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    packages = [p for p in metadata["packages"] if p["name"] == provenance["package"]]
    if len(packages) != 1 or packages[0]["version"] != provenance["version"]:
        raise ValueError("Resolved epaint font version differs from the reviewed texts")
    package_root = Path(packages[0]["manifest_path"]).parent.resolve(strict=True)
    plan = []
    for name in provenance["files"]:
        vendored = canonical(confined(FONT_SOURCE.resolve(), name).read_bytes())
        resolved = canonical(confined(package_root, "fonts/" + name).read_bytes())
        if vendored != resolved:
            raise ValueError(f"Resolved font license differs: {name}")
        plan.append(("epaint_default_fonts/" + name, resolved))
    for relative in UPSTREAM_FILES:
        plan.append(("wordcraft/" + Path(relative).name,
                     canonical(confined(upstream, relative).read_bytes())))
    for name in UPSTREAM_FONTS:
        plan.append(("wordcraft/fonts/" + name,
                     canonical(confined(upstream, "assets/fonts/" + name).read_bytes())))
    # Validate every input and destination before creating or overwriting the bundle.
    writes = [(confined(output, relative), content) for relative, content in plan]
    for target, content in writes:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    manifest = {"status": "UPSTREAM_AND_FONT_NOTICES_VERIFIED", "upstream_commit": pin,
                "epaint_default_fonts": provenance["version"],
                "scope": "Upstream and font notices only; complete runtime-dependency distribution audit remains pending",
                "files": [{"path": relative, "sha256_canonical_lf": hashlib.sha256(content).hexdigest()}
                          for relative, content in plan]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.metadata, args.upstream, args.out), indent=2))


if __name__ == "__main__":
    main()
