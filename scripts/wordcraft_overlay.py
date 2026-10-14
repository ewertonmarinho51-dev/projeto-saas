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
MAIN_PATH = "apps/wordcraft-web/src/main.rs"
MAIN_SHA = "7aabe7a19c7443a09874079a612a03803313c76e92fa83036941bbabd0021e4d"


def contained(source: Path, relative: str) -> Path:
    path = (source / relative).resolve()
    if not path.is_relative_to(source):
        raise ValueError("Overlay path escaped the isolated upstream checkout")
    return path


def apply(source: Path, *, browser=False):
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
    writes = [(cargo, base + section), (lib, adapter)]
    if browser:
        main = contained(source, MAIN_PATH)
        main_bytes = main.read_bytes().replace(b"\r\n", b"\n")
        replacement = (ROOT / "integrations/wordcraft/main.rs").read_bytes().replace(b"\r\n", b"\n")
        if main_bytes != replacement and hashlib.sha256(main_bytes).hexdigest() != MAIN_SHA:
            raise ValueError("Upstream browser main.rs differs from the audited bytes")
        module = contained(source, "apps/wordcraft-web/src/govconnect_browser.rs")
        module_bytes = (ROOT / "integrations/wordcraft/govconnect_browser.rs").read_bytes()
        if module.exists() and module.read_bytes() != module_bytes:
            raise ValueError("An unrelated browser integration file already exists")
        writes.extend([(main, replacement), (module, module_bytes)])
    # Every target is validated before writing any of them.
    for path, content in writes:
        path.write_bytes(content)
    return {"upstream_sha": pin, "adapter_sha256": hashlib.sha256(adapter).hexdigest(),
            "cargo_sha256": hashlib.sha256(base + section).hexdigest(),
            "browser_bridge": browser,
            "status": "OVERLAY_APPLIED_NOT_COMPILED"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--browser", action="store_true", help="Use the explicit document-scoped WASM entry point")
    args = p.parse_args()
    print(json.dumps(apply(args.source, browser=args.browser), indent=2))


if __name__ == "__main__":
    main()
