"""Overlay cannot target another revision or overwrite unrelated source edits."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import hashlib

import pytest

SPEC = importlib.util.spec_from_file_location(
    "wordcraft_overlay", Path(__file__).resolve().parents[1] / "scripts/wordcraft_overlay.py")
overlay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(overlay)
PIN = "533615620ef91ae57fa7aa4cd77fd98b2179e693"


def seed(tmp_path, monkeypatch):
    cargo = tmp_path / overlay.CARGO_PATH
    cargo.parent.mkdir(parents=True)
    cargo.write_bytes(b"[package]\nname = 'fixture'\n")
    (cargo.parent / "src").mkdir()
    monkeypatch.setattr(overlay, "CARGO_SHA", hashlib.sha256(cargo.read_bytes()).hexdigest())
    monkeypatch.setattr(overlay.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=PIN))
    monkeypatch.setattr(overlay, "ui_patches", lambda pin: [])
    return cargo


def test_overlay_idempotente(tmp_path, monkeypatch):
    cargo = seed(tmp_path, monkeypatch)
    original = cargo.read_bytes()
    first = overlay.apply(tmp_path)
    assert overlay.apply(tmp_path) == first
    assert cargo.read_bytes() == original + overlay.LIB_SECTION.encode()
    assert first["status"] == "OVERLAY_APPLIED_NOT_COMPILED"


def test_sha_divergente_nao_altera_arquivo(tmp_path, monkeypatch):
    cargo = seed(tmp_path, monkeypatch)
    monkeypatch.setattr(overlay.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="another"))
    before = cargo.read_bytes()
    with pytest.raises(ValueError, match="SHA"):
        overlay.apply(tmp_path)
    assert cargo.read_bytes() == before


def test_crlf_de_checkout_windows_nao_diverge_do_pin_lf(tmp_path, monkeypatch):
    cargo = seed(tmp_path, monkeypatch)
    cargo.write_bytes(cargo.read_bytes().replace(b"\n", b"\r\n"))
    assert overlay.apply(tmp_path)["status"] == "OVERLAY_APPLIED_NOT_COMPILED"
    assert b"\r\n" not in cargo.read_bytes()


def test_fonte_divergente_nao_altera_arquivo(tmp_path, monkeypatch):
    cargo = seed(tmp_path, monkeypatch)
    cargo.write_bytes(b"unrelated edit")
    with pytest.raises(ValueError, match="Cargo"):
        overlay.apply(tmp_path)
    assert cargo.read_bytes() == b"unrelated edit"


def test_nao_sobrescreve_adaptador_alheio(tmp_path, monkeypatch):
    cargo = seed(tmp_path, monkeypatch)
    lib = cargo.parent / "src/govconnect.rs"
    lib.write_text("unrelated code")
    before = cargo.read_bytes()
    with pytest.raises(ValueError, match="unrelated"):
        overlay.apply(tmp_path)
    assert cargo.read_bytes() == before and lib.read_text() == "unrelated code"


def test_caminho_confinado(tmp_path):
    with pytest.raises(ValueError, match="escaped"):
        overlay.contained(tmp_path.resolve(), "../outside")


def test_browser_entrypoint_idempotente(tmp_path, monkeypatch):
    cargo = seed(tmp_path, monkeypatch)
    main = cargo.parent / "src/main.rs"
    main.write_bytes(b"fn main() { /* fixture */ }\n")
    monkeypatch.setattr(overlay, "MAIN_SHA", hashlib.sha256(main.read_bytes()).hexdigest())
    first = overlay.apply(tmp_path, browser=True)
    assert overlay.apply(tmp_path, browser=True) == first
    assert first["browser_bridge"]
    assert (cargo.parent / "src/govconnect_browser.rs").is_file()


def test_browser_divergente_recusa_antes_de_qualquer_escrita(tmp_path, monkeypatch):
    cargo = seed(tmp_path, monkeypatch)
    main = cargo.parent / "src/main.rs"
    main.write_bytes(b"unrelated browser change")
    before = cargo.read_bytes()
    with pytest.raises(ValueError, match="main.rs"):
        overlay.apply(tmp_path, browser=True)
    assert cargo.read_bytes() == before
    assert not (cargo.parent / "src/govconnect.rs").exists()


def brand_fixture(tmp_path):
    path = tmp_path / "ui.rs"
    path.write_bytes(b"commercial_link(); copyright();\n")
    result = b"independent_source(); copyright();\n"
    return path, {"path": "ui.rs", "before_sha256_lf": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "after_sha256_lf": hashlib.sha256(result).hexdigest(),
                  "replacements": [{"before": "commercial_link()", "after": "independent_source()"}]}


def test_brand_preserva_copyright_e_recusa_drift(tmp_path):
    path, spec = brand_fixture(tmp_path)
    target, content = overlay.planned_ui_patch(tmp_path.resolve(), spec)
    assert target == path.resolve() and b"copyright()" in content
    assert b"commercial_link" not in content
    path.write_bytes(content)
    assert overlay.planned_ui_patch(tmp_path.resolve(), spec)[1] == content
    path.write_bytes(content + b"unrelated edit")
    with pytest.raises(ValueError, match="audited"):
        overlay.planned_ui_patch(tmp_path.resolve(), spec)


def test_brand_digest_incorreto_nao_escreve(tmp_path):
    path, spec = brand_fixture(tmp_path)
    before = path.read_bytes()
    spec["after_sha256_lf"] = "0" * 64
    with pytest.raises(ValueError, match="digest"):
        overlay.planned_ui_patch(tmp_path.resolve(), spec)
    assert path.read_bytes() == before
