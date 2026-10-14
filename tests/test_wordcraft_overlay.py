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
