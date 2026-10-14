"""Install the narrow Rust adapter into the exact, isolated upstream checkout.

No network, database, publishing or global installation. The source manifest is
checked against the pinned upstream SHA and known bytes before any edit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CARGO_PATH = "apps/wordcraft-web/Cargo.toml"
CARGO_SHA = "eda03c9e096f2a45cd55e5e5001e8f0850ceacf107864705cdd9c16928bfc8e0"
LIB_SECTION = '\n[lib]\nname = "govconnect_wordcraft"\npath = "src/govconnect.rs"\n'


def contained(source: Path, relative: str) -> Path:
    path = (source / relative).resolve()
    if not path.is_relative_to(source):
        raise ValueError("Overlay path escaped the isolated upstream checkout")
    return path


def apply(source: Path):
    source = source.resolve(strict=True)
    pin = json.loads((ROOT / "docs/wordcraft/upstream.lock.json").read_text(encoding="utf-8"))["commit"]
    p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source,
                       capture_output=True, text=True, check=True, timeout=20)
    if p.stdout.strip() != pin:
        raise ValueError("Upstream SHA does not match the audited pin")
    cargo = contained(source, CARGO_PATH)
    original = cargo.read_bytes().replace(b"\r\n", b"\n")
    section = LIB_SECTION.encode()
    base = original[:-len(section)] if original.endswith(section) else original
    if hashlib.sha256(base).hexdigest() != CARGO_SHA:
        raise ValueError("Upstream Cargo.toml differs from the audited bytes")
    lib = contained(source, "apps/wordcraft-web/src/govconnect.rs")
    adapter = (ROOT / "integrations/wordcraft/govconnect.rs").read_bytes()
    if lib.exists() and lib.read_bytes() != adapter:
        raise ValueError("An unrelated integration file already exists")
    cargo.write_bytes(base + section)
    lib.write_bytes(adapter)
    return {"upstream_sha": pin, "adapter_sha256": hashlib.sha256(adapter).hexdigest(),
            "cargo_sha256": hashlib.sha256(base + section).hexdigest(),
            "status": "OVERLAY_APPLIED_NOT_COMPILED"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(apply(args.source), indent=2))


if __name__ == "__main__":
    main()
