import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from scripts import wordcraft_distribution_notices as notices


def package(identity, name, source=None):
    return {"id": identity, "name": name, "version": "1.0.0", "source": source}


def edge(identity, *kinds):
    return {"pkg": identity, "dep_kinds": [{"kind": kind, "target": None} for kind in kinds]}


def test_closure_follows_normal_build_and_mixed_edges_but_never_dev_only():
    metadata = {"packages": [package("r", "wordcraft-web"), package("n", "normal"),
        package("b", "build"), package("d", "dev"), package("m", "mixed"), package("t", "transitive")],
        "resolve": {"nodes": [
            {"id": "r", "deps": [edge("n", None), edge("b", "build"), edge("d", "dev"), edge("m", "dev", None)]},
            {"id": "n", "deps": [edge("t", "build")]}, {"id": "b", "deps": []},
            {"id": "d", "deps": []}, {"id": "m", "deps": []}, {"id": "t", "deps": []}]}}
    _, packages = notices.closure(metadata)
    assert {item["name"] for item in packages} == {"wordcraft-web", "normal", "build", "mixed", "transitive"}
    metadata["resolve"]["nodes"][0]["deps"].append(edge("unknown", None))
    with pytest.raises(ValueError, match="missing node"):
        notices.closure(metadata)


@pytest.mark.parametrize("expression", [None, "", "LicenseRef-private", "MIT AND", "MIT WITH invented", "(MIT OR Apache-2.0"])
def test_missing_unknown_and_invalid_spdx_never_become_approved(expression):
    assert notices.audit_spdx(expression)["review"]


def test_legacy_separator_and_alternative_copyleft_are_reported_without_silent_choice():
    report = notices.audit_spdx("MIT/Apache-2.0")
    assert report["normalized"] == "MIT OR Apache-2.0"
    assert not report["review"]
    report = notices.audit_spdx("Apache-2.0 OR GPL-2.0-only")
    assert "GPL-2.0-only" in report["identifiers"]
    assert "COPYLEFT_BRANCH_REQUIRES_EXPLICIT_REVIEW_OR_LICENSE_CHOICE" in report["review"]
    report = notices.audit_spdx("(MIT OR Apache-2.0) AND OFL-1.1 AND Ubuntu-font-1.0")
    assert "SPECIAL_FONT_TERMS_REQUIRE_REVIEW" in report["review"]


def test_notice_names_do_not_mistake_rust_identifiers_for_license_files():
    for name in ("LICENSE.APACHE", "LICENSE.MIT", "COPYING.LIB", "NOTICE", "OFL-Inter.txt", "emoji-icon-font-mit-license.txt"):
        assert notices._is_notice(name)
    assert not notices._is_notice("gen_MemoryAttribution.rs")


def test_parent_walk_is_repository_bounded_and_never_inherits_a_registry_sibling(tmp_path):
    boundary = tmp_path / "upstream"
    package_root = boundary / "crates" / "sample"
    package_root.mkdir(parents=True)
    (boundary / "LICENSE-MIT").write_text("Synthetic license", encoding="utf-8")
    (tmp_path / "NOTICE").write_text("Must not inherit", encoding="utf-8")
    files, _ = notices._candidates(package_root, boundary)
    assert files == {boundary / "LICENSE-MIT"}
    files, _ = notices._candidates(package_root, package_root)
    assert not files
    with pytest.raises(ValueError):
        notices._candidates(tmp_path, boundary)


def test_collection_records_missing_text_and_refuses_cross_package_license_file(tmp_path, monkeypatch):
    upstream, registry, git = (tmp_path / name for name in ("upstream", "registry", "git"))
    for root in (upstream, registry, git):
        root.mkdir()
    app = upstream / "apps/wordcraft-web"
    app.mkdir(parents=True)
    (app / "Cargo.toml").write_text('[package]\nname="wordcraft-web"\nversion="1.0.0"\n', encoding="utf-8")
    (upstream / "LICENSE-MIT").write_text("Copyright synthetic author\nSynthetic license text.\n", encoding="utf-8")
    source = "registry+https://github.com/rust-lang/crates.io-index"
    lock = ('version = 4\n\n[[package]]\nname = "wordcraft-web"\nversion = "1.0.0"\n\n'
            '[[package]]\nname = "sample"\nversion = "1.0.0"\nsource = "' + source + '"\n')
    (upstream / "Cargo.lock").write_text(lock, encoding="utf-8")
    subprocess.run(["git", "init", str(upstream)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(upstream), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(upstream), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-m", "Synthetic notice fixture"], check=True, capture_output=True)
    pin = subprocess.run(["git", "-C", str(upstream), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    config = tmp_path / "config/docs/wordcraft"
    config.mkdir(parents=True)
    (config / "upstream.lock.json").write_text(json.dumps({"commit": pin}), encoding="utf-8")
    monkeypatch.setattr(notices, "ROOT", tmp_path / "config")
    monkeypatch.setattr(notices, "UPSTREAM_EXTRA", ())
    crate = registry / "index/sample-1.0.0"
    crate.mkdir(parents=True)
    (crate / "Cargo.toml").write_text('[package]\nname="sample"\nversion="1.0.0"\n', encoding="utf-8")
    outside = crate.parent / "outside"
    outside.mkdir()
    private = b"synthetic sentinel must never be copied from a neighboring package"
    (outside / "LICENSE.txt").write_bytes(private)
    root_package = {**package("r", "wordcraft-web"), "manifest_path": str(app / "Cargo.toml"),
                    "license": "MIT", "license_file": None}
    dependency = {**package("s", "sample", source), "manifest_path": str(crate / "Cargo.toml"),
                  "license": None, "license_file": "../outside/LICENSE.txt"}
    metadata = {"packages": [root_package, dependency], "resolve": {"nodes": [
        {"id": "r", "deps": [edge("s", None)]}, {"id": "s", "deps": []}]}}
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    output = tmp_path / "notices"
    manifest = notices.collect(metadata_path=metadata_path, upstream=upstream, registry=registry, git=git, output=output)
    sample = next(item for item in manifest["packages"] if item["name"] == "sample")
    assert sample["status"] == "REVIEW" and not sample["files"]
    assert "SPDX_MISSING" in sample["review"]
    assert any("OUTSIDE_DECLARED_BOUNDARY" in item for item in sample["review"])
    assert manifest["counts"]["packages_without_any_text"] == 1
    for item in manifest["files"]:
        content = (output / item["path"]).read_bytes()
        assert content != private
        assert hashlib.sha256(content).hexdigest() == item["sha256"]
    assert all(path.suffix == ".txt" for path in (output / "licenses").iterdir())
    with pytest.raises(ValueError, match="new directory"):
        notices.collect(metadata_path=metadata_path, upstream=upstream, registry=registry, git=git, output=output)
