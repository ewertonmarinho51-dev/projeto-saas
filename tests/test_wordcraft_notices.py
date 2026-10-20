import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "wordcraft_notices", Path(__file__).resolve().parents[1] / "scripts/wordcraft_notices.py")
notices = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notices)


def fixture(tmp_path, monkeypatch):
    upstream = tmp_path / "upstream"
    package = tmp_path / "epaint_default_fonts-0.36.2"
    for relative in list(notices.UPSTREAM_FILES) + ["assets/fonts/" + n for n in notices.UPSTREAM_FONTS]:
        target = upstream / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Synthetic upstream license fixture\n", encoding="utf-8")
    provenance = json.loads((notices.FONT_SOURCE / "PROVENANCE.json").read_text())
    for name in provenance["files"]:
        target = package / "fonts" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((notices.FONT_SOURCE / name).read_bytes().replace(b"\n", b"\r\n"))
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"packages": [{"name": "epaint_default_fonts", "version": "0.36.2",
                                                  "manifest_path": str(package / "Cargo.toml")}]}))
    monkeypatch.setattr(notices.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(stdout="533615620ef91ae57fa7aa4cd77fd98b2179e693"))
    return upstream, package, metadata, tmp_path / "notices"


def test_consolida_avisos_sem_copiar_fontes_binarias(tmp_path, monkeypatch):
    upstream, package, metadata, output = fixture(tmp_path, monkeypatch)
    result = notices.collect(metadata, upstream, output)
    assert result["status"] == "UPSTREAM_AND_FONT_NOTICES_VERIFIED"
    assert len(result["files"]) == 13
    assert (output / "epaint_default_fonts/UFL.txt").is_file()
    assert (output / "wordcraft/NOTICE").is_file()
    assert not list(output.rglob("*.ttf"))
    assert notices.collect(metadata, upstream, output) == result


def test_texto_alterado_falha_antes_de_gerar_bundle(tmp_path, monkeypatch):
    upstream, package, metadata, output = fixture(tmp_path, monkeypatch)
    (package / "fonts/UFL.txt").write_text("altered license")
    with pytest.raises(ValueError, match="differs"):
        notices.collect(metadata, upstream, output)
    assert not output.exists()


def test_versao_divergente_nao_e_aprovada(tmp_path, monkeypatch):
    upstream, package, metadata, output = fixture(tmp_path, monkeypatch)
    content = json.loads(metadata.read_text())
    content["packages"][0]["version"] = "9.0.0"
    metadata.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="version"):
        notices.collect(metadata, upstream, output)
    assert not output.exists()


def test_destino_confinado_e_sem_sobrescrever_checkout(tmp_path, monkeypatch):
    upstream, package, metadata, output = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="escapes"):
        notices.confined(tmp_path.resolve(), "../outside")
    with pytest.raises(ValueError, match="outside"):
        notices.collect(metadata, upstream, upstream / "bundle")
