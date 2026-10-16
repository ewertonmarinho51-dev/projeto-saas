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
import tomllib

ROOT = Path(__file__).resolve().parents[1]
IO_PATCH = ROOT / "integrations/wordcraft/io-fidelity.patch"
CARGO_PATH = "apps/wordcraft-web/Cargo.toml"
CARGO_SHA = "eda03c9e096f2a45cd55e5e5001e8f0850ceacf107864705cdd9c16928bfc8e0"
LIB_SECTION = '\n[lib]\nname = "govconnect_wordcraft"\npath = "src/govconnect.rs"\n'
DEPENDENCIES = '[dependencies]\nserde = { workspace = true }\nsha2 = { workspace = true }\n'
LOCK_BEFORE_SHA = "4cd08e46c389033f3f3d031026c3f674f74765899790e9f05b475557377bff68"
LOCK_AFTER_SHA = "e6b2bae022650e4fdc2dacdcb3ba90e7f3037e6a8cfa2a87dfa6b25be2883170"
LOCK_WEB_BEFORE = '''[[package]]
name = "wordcraft-web"
version = "0.7.0"
dependencies = [
 "eframe",
 "egui",
 "js-sys",
 "log",
 "rfd",
 "serde_json",
 "wasm-bindgen",
 "wasm-bindgen-futures",
 "web-sys",
 "wordcraft-doc",
 "wordcraft-engine",
 "wordcraft-fonts",
 "wordcraft-ui-egui",
]
'''
LOCK_WEB_AFTER = LOCK_WEB_BEFORE.replace(' "serde_json",\n', ' "serde",\n "serde_json",\n "sha2",\n')


def integrated_cargo(base: bytes) -> bytes:
    marker = b"[dependencies]\n"
    if base.count(marker) != 1:
        raise ValueError("Pinned dependency table is missing or ambiguous")
    return base.replace(marker, DEPENDENCIES.encode(), 1) + LIB_SECTION.encode()


def validate_lock_delta(before: bytes, after: bytes) -> None:
    previous, current = (tomllib.loads(raw.decode("utf-8")) for raw in (before, after))
    old_entries = [item for item in previous["package"] if item["name"] == "wordcraft-web"]
    new_entries = [item for item in current["package"] if item["name"] == "wordcraft-web"]
    if len(old_entries) != 1 or len(new_entries) != 1:
        raise ValueError("Lock delta has an ambiguous root package")
    old, new = old_entries[0], new_entries[0]
    if (old["version"] != "0.7.0" or new["dependencies"] != sorted([*old["dependencies"], "serde", "sha2"])):
        raise ValueError("Lock delta is not the two approved direct dependencies")
    new["dependencies"] = old["dependencies"]
    if previous != current:
        raise ValueError("Lock delta changed another package, version, source or checksum")


def integrated_lock(raw: bytes) -> bytes:
    raw = raw.replace(b"\r\n", b"\n")
    digest = hashlib.sha256(raw).hexdigest()
    before, after = LOCK_WEB_BEFORE.encode(), LOCK_WEB_AFTER.encode()
    if digest == LOCK_AFTER_SHA:
        if raw.count(after) != 1:
            raise ValueError("Integrated lock package differs")
        validate_lock_delta(raw.replace(after, before, 1), raw)
        return raw
    if digest != LOCK_BEFORE_SHA or raw.count(before) != 1:
        raise ValueError("Cargo.lock differs from the audited upstream/integration bytes")
    result = raw.replace(before, after, 1)
    if hashlib.sha256(result).hexdigest() != LOCK_AFTER_SHA:
        raise ValueError("Integrated Cargo.lock hash differs")
    validate_lock_delta(raw, result)
    return result
MAIN_PATH = "apps/wordcraft-web/src/main.rs"
MAIN_SHA = "7aabe7a19c7443a09874079a612a03803313c76e92fa83036941bbabd0021e4d"
CATALOG_CODES = frozenset({"bg", "cs", "de", "es", "et", "fr", "hu", "it", "ja", "pl", "pt-br", "ru",
                           "sr", "sr-latn", "tr", "uk", "zh-hans", "zh-hant"})


def validate_catalog_parity(catalogs: dict[str, bytes]) -> None:
    """Cheap pre-check of pinned upstream key-set contracts; Rust audit still runs."""
    if catalogs.keys() != CATALOG_CODES:
        raise ValueError("Integration labels must cover all pinned UI catalogs")
    keys = {}
    for code, content in catalogs.items():
        entries = []
        for line in content.decode("utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            columns = line.split("\t")
            if len(columns) != 3:
                raise ValueError("Unexpected pinned catalog row shape")
            entries.append(columns[1])
        keys[code] = set(entries)
    for code in ("pt-br", "uk", "sr", "sr-latn", "cs", "de"):
        if keys[code] != keys["zh-hans"]:
            raise ValueError(f"Catalog key parity differs: {code}/zh-hans")
    if keys["tr"] != keys["ru"]:
        raise ValueError("Catalog key parity differs: tr/ru")
    for code in ("es", "tr", "et", "zh-hans"):
        if not keys[code].issubset(keys["it"]):
            raise ValueError(f"Italian catalog lacks keys from {code}")
    for code in CATALOG_CODES - {"pl", "it", "hu", "bg"}:
        if not keys[code].issubset(keys["pl"]):
            raise ValueError(f"Polish catalog lacks keys from {code}")


def contained(source: Path, relative: str) -> Path:
    path = (source / relative).resolve()
    if not path.is_relative_to(source):
        raise ValueError("Overlay path escaped the isolated upstream checkout")
    return path


def io_patch_state(source: Path) -> str:
    """Validate the reviewed core patch without changing the upstream checkout."""
    if not IO_PATCH.is_file():
        raise ValueError("Reviewed I/O fidelity patch is missing")
    command = ["git", "apply", "--check", "--ignore-space-change", str(IO_PATCH)]
    forward = subprocess.run(command, cwd=source, capture_output=True, text=True, timeout=20)
    if getattr(forward, "returncode", 0) == 0:
        return "pending"
    reverse = subprocess.run(
        ["git", "apply", "--reverse", "--check", "--ignore-space-change", str(IO_PATCH)],
        cwd=source, capture_output=True, text=True, timeout=20,
    )
    if getattr(reverse, "returncode", 0) == 0:
        return "applied"
    raise ValueError("Upstream I/O paths differ from both audited states")


def ui_patches(pin: str) -> list[dict]:
    manifest = json.loads((ROOT / "integrations/wordcraft/ui-patches.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "gc-wordcraft-ui-patches/v1" or manifest.get("upstream_commit") != pin:
        raise ValueError("Brand patch manifest does not match the audited pin")
    return manifest["patches"]


def planned_ui_patch(source: Path, spec: dict) -> tuple[Path, bytes]:
    path = contained(source, spec["path"])
    data = path.read_bytes().replace(b"\r\n", b"\n")
    digest = hashlib.sha256(data).hexdigest()
    if digest == spec["after_sha256_lf"]:
        return path, data
    if digest != spec["before_sha256_lf"]:
        raise ValueError("UI source differs from the audited bytes")
    text = data.decode("utf-8")
    for change in spec["replacements"]:
        if not change["before"] or text.count(change["before"]) != 1:
            raise ValueError("Brand replacement is missing or ambiguous")
        text = text.replace(change["before"], change["after"], 1)
    result = text.encode("utf-8")
    if hashlib.sha256(result).hexdigest() != spec["after_sha256_lf"]:
        raise ValueError("Patched UI digest differs from the reviewed result")
    return path, result


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
    if base.count(DEPENDENCIES.encode()) == 1:
        base = base.replace(DEPENDENCIES.encode(), b"[dependencies]\n", 1)
    if hashlib.sha256(base).hexdigest() != CARGO_SHA:
        raise ValueError("Upstream Cargo.toml differs from the audited bytes")
    lib = contained(source, "apps/wordcraft-web/src/govconnect.rs")
    adapter = (ROOT / "integrations/wordcraft/govconnect.rs").read_bytes()
    if lib.exists() and lib.read_bytes() != adapter:
        raise ValueError("An unrelated integration file already exists")
    cargo_bytes = integrated_cargo(base)
    lock = contained(source, "Cargo.lock")
    lock_bytes = integrated_lock(lock.read_bytes())
    writes = [(cargo, cargo_bytes), (lock, lock_bytes), (lib, adapter)]
    example = contained(source, "apps/wordcraft-web/examples/govconnect_fixture.rs")
    example_bytes = (ROOT / "integrations/wordcraft/govconnect_fixture.rs").read_bytes()
    if example.exists() and example.read_bytes() != example_bytes:
        raise ValueError("An unrelated QA example already exists")
    writes.append((example, example_bytes))
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
        patches = ui_patches(pin)
        ui_writes = [planned_ui_patch(source, spec) for spec in patches]
        if patches:
            catalogs = {Path(spec["path"]).stem: content for spec, (_, content) in zip(patches, ui_writes)
                        if "/i18n/" in spec["path"] and spec["path"].endswith(".tsv")}
            validate_catalog_parity(catalogs)
        writes.extend(ui_writes)
    # Every target is validated before writing any of them.
    io_state = io_patch_state(source)
    if io_state == "pending":
        subprocess.run(
            ["git", "apply", "--ignore-space-change", str(IO_PATCH)],
            cwd=source, capture_output=True, text=True, check=True, timeout=20,
        )
    for path, content in writes:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return {"upstream_sha": pin, "adapter_sha256": hashlib.sha256(adapter).hexdigest(),
            "cargo_sha256": hashlib.sha256(cargo_bytes).hexdigest(),
            "cargo_lock_upstream_sha256_lf": LOCK_BEFORE_SHA,
            "cargo_lock_integration_sha256_lf": hashlib.sha256(lock_bytes).hexdigest(),
            "cargo_lock_delta": "wordcraft-web direct dependencies: serde and sha2 only; versions/source/checksums unchanged",
            "browser_bridge": browser,
            "io_fidelity_patch_sha256": hashlib.sha256(IO_PATCH.read_bytes()).hexdigest(),
            "io_fidelity_patch": "applied" if io_state == "pending" else "already_applied",
            "status": "OVERLAY_APPLIED_NOT_COMPILED"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--browser", action="store_true", help="Use the explicit document-scoped WASM entry point")
    args = p.parse_args()
    print(json.dumps(apply(args.source, browser=args.browser), indent=2))


if __name__ == "__main__":
    main()
