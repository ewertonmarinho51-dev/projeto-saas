"""QA guard/lifecycle tests; actual LO evidence is a separate local artifact."""
import io
import json
from pathlib import Path
import shutil
import zipfile

import pytest

from scripts import wordcraft_libreoffice_extract as extractor
from scripts import wordcraft_libreoffice_qa as qa


def test_controlled_c10_roundtrip_expectation_is_exact_and_isolated():
    original = {"body": [
        "C10-EXTERNAL Modelo original de QA com tabela aninhada, célula mesclada e campo de página.",
        "unchanged"], "headers": ["header"], "footers": [], "links": ["https://example.invalid"]}
    expected = qa.expected_roundtrip_blocks("C10/modelo.docx", original)
    assert expected["body"][0].startswith("C10-EXTERNAL-EDITED Modelo")
    assert expected["body"][1:] == ["unchanged"]
    assert expected["headers"] == original["headers"] and expected["links"] == original["links"]
    assert original["body"][0].startswith("C10-EXTERNAL Modelo")
    assert qa.expected_roundtrip_blocks("C09/parecer.docx", original) == original


def rewrite_part(data, name, transform):
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as changed:
        for item in original.infolist():
            content = original.read(item.filename)
            changed.writestr(item.filename, transform(content) if item.filename == name else content)
    return result.getvalue()


def seed():
    from scripts.wordcraft_corpus import gerar_docx
    return gerar_docx("QA sintético", "Marcador QA-CODE\n\n[Referência](https://example.invalid/qa)")


def test_admission_preserves_inert_link_and_page_field():
    data = rewrite_part(seed(), "word/document.xml", lambda value: value.replace(
        b"</w:body>", b'<w:p><w:fldSimple w:instr=" PAGE "/></w:p></w:body>'))
    assert qa.admit_synthetic_docx(data) == ["https://example.invalid/qa"]


@pytest.mark.parametrize("target", ["https://real.example/qa", "https://user:password@example.invalid/qa",
                                    "https://example.invalid:443/qa", "file:///C:/Windows/win.ini"])
def test_admission_refuses_external_sources(target):
    data = rewrite_part(seed(), "word/_rels/document.xml.rels", lambda value: value.replace(
        b"https://example.invalid/qa", target.encode()))
    with pytest.raises(ValueError):
        qa.admit_synthetic_docx(data)


@pytest.mark.parametrize("field", ["DDEAUTO cmd.exe", "INCLUDETEXT https://example.invalid/qa", "INCLUDEPICTURE x", "HYPERLINK x"])
def test_admission_refuses_active_or_unrecognized_fields(field):
    data = rewrite_part(seed(), "word/document.xml", lambda value: value.replace(
        b"</w:body>", f'<w:p><w:fldSimple w:instr="{field}"/></w:p></w:body>'.encode()))
    with pytest.raises(ValueError):
        qa.admit_synthetic_docx(data)


def test_admission_reuses_macro_policy():
    data = rewrite_part(seed(), "[Content_Types].xml", lambda value: value.replace(
        b"wordprocessingml.document.main+xml", b"wordprocessingml.macroEnabled.main+xml"))
    with pytest.raises(ValueError):
        qa.admit_synthetic_docx(data)


def test_confinement_refuses_repo_inputs_toolchain_and_existing(tmp_path, monkeypatch):
    work, repo, inputs = tmp_path / "work", tmp_path / "work/repo", tmp_path / "work/corpus"
    for path in (work, repo, inputs):
        path.mkdir(exist_ok=True)
    monkeypatch.setattr(qa, "WORK_ROOT", work)
    monkeypatch.setattr(qa, "ROOT", repo)
    for forbidden in (work, repo / "new", inputs / "new", work / "toolchain/new", tmp_path / "foreign", inputs):
        with pytest.raises(ValueError):
            qa.confined_output(forbidden, inputs)
    existing = work / "old"
    existing.mkdir()
    with pytest.raises(ValueError, match="new"):
        qa.confined_output(existing, inputs)
    assert qa.confined_output(work / "fresh", inputs) == work / "fresh"


@pytest.mark.parametrize("name", ["..", "../evil", "x\\evil", "", "x|../evil"])
def test_msi_target_refuses_path_traversal(name):
    with pytest.raises(ValueError):
        extractor.target_name(name)


def test_msi_target_uses_target_long_name():
    assert extractor.target_name("LIBREO~1|LibreOffice:.") == "LibreOffice"
    assert extractor.target_name(".") == ""


def test_runtime_provenance_refuses_unpinned_before_opening_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(qa, "WORK_ROOT", tmp_path)
    directory = tmp_path / "toolchain/lo"
    directory.mkdir(parents=True)
    receipt = directory / "receipt.json"
    receipt.write_text(json.dumps({"schema": "forged"}))
    with pytest.raises(ValueError, match="provenance"):
        qa.validate_runtime(receipt)


@pytest.mark.parametrize("mutation", ["binary", "extra", "duplicate"])
def test_runtime_inventory_rejects_changed_extra_and_duplicate_files(tmp_path, monkeypatch, mutation):
    # Tiny filesystem contract fixture, not a claimed vendor runtime. Only its
    # MSI identity/schema are mocked; file inventory/hash checks remain real.
    monkeypatch.setattr(qa, "WORK_ROOT", tmp_path)
    directory = tmp_path / "toolchain/lo"
    image = directory / "image"
    executable = image / "LibreOffice/program/soffice.com"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"synthetic executable, never executed")
    msi = directory / extractor.MSI_NAME
    msi.write_bytes(b"synthetic metadata")
    original_digest = qa.digest
    monkeypatch.setattr(qa, "digest", lambda path: extractor.SHA256 if path == msi else original_digest(path))
    monkeypatch.setattr(qa, "validate_profile_properties", lambda _: None)
    item = {"path": executable.relative_to(image).as_posix(), "bytes": executable.stat().st_size,
            "sha256": original_digest(executable)}
    receipt = {"schema": "gc-wordcraft-lo-extraction/v1", "published_sha256": extractor.SHA256,
               "msi_sha256": extractor.SHA256, "method": "MSI_READONLY_STREAM_CAB_EXPAND_NO_INSTALL_ACTIONS",
               "image": str(image), "msi": str(msi), "soffice": str(executable),
               "soffice_sha256": original_digest(executable), "files": [item]}
    target = directory / "receipt.json"
    target.write_text(json.dumps(receipt))
    assert qa.validate_runtime(target)[0] == executable
    if mutation == "binary":
        executable.write_bytes(b"changed")
    elif mutation == "extra":
        (image / "unexpected.dll").write_bytes(b"extra")
    else:
        receipt["files"].append(item)
        target.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        qa.validate_runtime(target)


def test_command_uses_private_profile_and_no_listener(tmp_path):
    command = qa.conversion_command(tmp_path / "soffice.com", tmp_path / "profile", tmp_path / "x.docx", tmp_path / "out")
    assert "-env:UserInstallation=" + (tmp_path / "profile").as_uri() in command
    assert "-env:CrashDirectory=" + (tmp_path / "crash").as_uri() in command
    assert "-env:CrashDumpEnable=false" in command
    assert "pdf:writer_pdf_Export" in command
    assert not any("--accept" in item or "--env:" in item for item in command)


@pytest.mark.parametrize("success_attempt", [1, 2, None])
def test_missing_pdf_retry_is_bounded_and_preserves_attempt_logs(tmp_path, monkeypatch, success_attempt):
    source, output = tmp_path / "seed.docx", tmp_path / "output"
    source.write_bytes(b"admitted upstream contract fixture")
    output.mkdir()
    calls = []

    def child(command, env, timeout):
        calls.append(command)
        if len(calls) == success_attempt:
            (output / "seed.pdf").write_bytes(b"%PDF-contract-artifact")
        return {"pid": len(calls), "returncode": 0, "output": "observed child result", "seconds": 0.1}

    monkeypatch.setattr(qa, "run_owned", child)
    if success_attempt:
        _, attempts = qa.convert_missing_pdf(tmp_path / "soffice.com", source, output, run_id=2, timeout=30)
        assert len(attempts) == success_attempt and attempts[-1]["pdf_created"]
    else:
        with pytest.raises(ValueError, match="two recorded"):
            qa.convert_missing_pdf(tmp_path / "soffice.com", source, output, run_id=2, timeout=30)
    assert len(calls) == (success_attempt or 2)
    assert len(list(output.glob("invocation-run-2-attempt-*.json"))) == len(calls)
    assert all((output / f"_scratch-run-2-attempt-{number}/profile/user/registrymodifications.xcu").is_file()
               for number in range(1, len(calls) + 1))


def test_existing_pdf_is_never_reconverted_or_overwritten(tmp_path, monkeypatch):
    (tmp_path / "seed.pdf").write_bytes(b"existing immutable artifact")
    monkeypatch.setattr(qa, "run_owned", lambda *args: pytest.fail("must not reconvert"))
    with pytest.raises(ValueError, match="Unrecorded PDF"):
        qa.convert_missing_pdf(tmp_path / "soffice.com", tmp_path / "seed.docx", tmp_path, run_id=0, timeout=30)
    assert (tmp_path / "seed.pdf").read_bytes() == b"existing immutable artifact"


@pytest.mark.parametrize("success_second", [True, False])
def test_nonzero_invocations_are_logged_and_retry_limit_is_two(tmp_path, monkeypatch, success_second):
    calls = []
    source = tmp_path / "source.docx"
    source.write_bytes(b"admitted source fixture")

    def child(*args):
        calls.append(args)
        if success_second and len(calls) == 2:
            (tmp_path / "source.pdf").write_bytes(b"%PDF-contract")
            return {"returncode": 0}
        error = RuntimeError("observed native process failure")
        error.invocation_result = {"returncode": 3221226505, "output": "", "error_type": "RuntimeError"}
        raise error

    monkeypatch.setattr(qa, "run_owned", child)
    if success_second:
        assert len(qa.convert_missing_pdf(tmp_path / "soffice.com", source, tmp_path, run_id=7, timeout=30)[1]) == 2
    else:
        with pytest.raises(RuntimeError, match="native process failure"):
            qa.convert_missing_pdf(tmp_path / "soffice.com", source, tmp_path, run_id=7, timeout=30)
    assert len(calls) == 2
    assert json.loads((tmp_path / "invocation-run-7-attempt-1.json").read_text())["returncode"] == 3221226505
    assert (tmp_path / "invocation-run-7-attempt-2.json").is_file()


def test_linux_institutional_mode_is_explicit_and_refuses_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(qa, "LINUX", False)
    with pytest.raises(RuntimeError, match="Linux runner"):
        qa.validate_system_runtime(tmp_path / "soffice")


def test_linux_wrapper_has_own_profile_group_deadline_and_reduced_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "must-not-inherit")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-inherit")
    env, wrapper = qa.system_adapter_environment(Path("/usr/lib/libreoffice/program/soffice"), tmp_path, qa.PROFILE_ITEMS)
    command = wrapper.read_text()
    assert "/usr/bin/timeout --signal=TERM --kill-after=5s 100s" in command
    assert '"$@"' in command and "--foreground" not in command
    assert "-env:UserInstallation=" + (tmp_path / "profile").as_uri() in command
    assert not {"SUPABASE_SERVICE_KEY", "GITHUB_TOKEN", "CRASH_DUMP_ENABLE"}.intersection(env)
    assert env["TMPDIR"] == str(tmp_path / "tmp") and env["HOME"] == str(tmp_path / "home")


@pytest.mark.parametrize("success_attempt", [1, 2, None])
def test_linux_mode_calls_existing_adapter_without_fallback_and_restores_env(tmp_path, monkeypatch, success_attempt):
    from src import export
    source = tmp_path / "source.docx"
    source.write_bytes(b"admitted DOCX fixture")
    calls = []
    original_env, original_temp = dict(qa.os.environ), qa.tempfile.tempdir

    def existing(data):
        assert data == b"admitted DOCX fixture"
        assert "SUPABASE_SERVICE_KEY" not in qa.os.environ
        assert qa.tempfile.tempdir == qa.os.environ["TMPDIR"]
        calls.append(data)
        return b"%PDF-real-adapter-contract" if len(calls) == success_attempt else None

    monkeypatch.setattr(export, "_docx_em_pdf", existing)
    monkeypatch.setattr(export, "gerar_pdf", lambda *args, **kwargs: pytest.fail("fallback must never execute"))
    if success_attempt:
        _, attempts = qa.convert_institutional_pdf(Path("/usr/lib/libreoffice/program/soffice"), source, tmp_path, items=qa.PROFILE_ITEMS)
        assert len(attempts) == success_attempt
        assert (tmp_path / "source.pdf").read_bytes() == b"%PDF-real-adapter-contract"
    else:
        with pytest.raises(ValueError, match="no fallback"):
            qa.convert_institutional_pdf(Path("/usr/lib/libreoffice/program/soffice"), source, tmp_path, items=qa.PROFILE_ITEMS)
        assert not (tmp_path / "source.pdf").exists()
    assert len(calls) == (success_attempt or 2)
    # Failure diagnostics must not print inherited host environment values.
    assert qa.json_digest(dict(qa.os.environ)) == qa.json_digest(original_env)
    assert qa.tempfile.tempdir == original_temp
    assert len(list(tmp_path.glob("_institutional-attempt-*/adapter-result.json"))) == len(calls)


def test_linux_adapter_exception_restores_process_state(tmp_path, monkeypatch):
    from src import export
    source = tmp_path / "source.docx"
    source.write_bytes(b"admitted DOCX fixture")
    original_env, original_temp = dict(qa.os.environ), qa.tempfile.tempdir
    def interrupted(_):
        raise KeyboardInterrupt()
    monkeypatch.setattr(export, "_docx_em_pdf", interrupted)
    with pytest.raises(KeyboardInterrupt):
        qa.convert_institutional_pdf(Path("/usr/lib/libreoffice/program/soffice"), source, tmp_path, items=qa.PROFILE_ITEMS)
    assert qa.json_digest(dict(qa.os.environ)) == qa.json_digest(original_env)
    assert qa.tempfile.tempdir == original_temp
    assert not (tmp_path / "source.pdf").exists()


def test_profile_disables_macros_and_child_drops_provider_secrets(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    qa.make_profile(profile)
    text = (profile / "user/registrymodifications.xcu").read_text()
    assert 'oor:name="DisableMacrosExecution"' in text
    assert '<value>true</value>' in text and '<value>3</value>' in text
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "must-not-inherit")
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-not-inherit")
    env = qa.child_environment(tmp_path / "image/LibreOffice/program/soffice.com", tmp_path / "scratch")
    assert "SUPABASE_SERVICE_KEY" not in env and "OPENROUTER_API_KEY" not in env
    assert env["https_proxy"] == "http://127.0.0.1:9"
    assert "arm64" not in env["PATH"]
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["PYTHONPYCACHEPREFIX"] == str(tmp_path / "scratch/pycache")
    assert 'oor:name="UseOpenCL"' in text


def test_profile_properties_refuse_runtime_without_verified_schema(tmp_path):
    registry = tmp_path / "LibreOffice/share/registry"
    registry.mkdir(parents=True)
    for name in ("main.xcd", "onlineupdate.xcd"):
        (registry / name).write_text('<oor:data xmlns:oor="http://openoffice.org/2001/registry"/>')
    with pytest.raises(ValueError, match="properties"):
        qa.validate_profile_properties(tmp_path / "LibreOffice/program/soffice.com")


def test_linux_registry_can_omit_optional_settings_but_requires_macro_and_proxy(tmp_path):
    from xml.etree import ElementTree as ET
    namespace = "{http://openoffice.org/2001/registry}"
    registry = tmp_path / "LibreOffice/share/registry"
    registry.mkdir(parents=True)
    root = ET.Element(namespace + "data")
    selected = [item for item in qa.PROFILE_ITEMS if item[0].startswith(
        ("/org.openoffice.Inet/", "/org.openoffice.Office.Common/Security/"))]
    components = {}
    for path, name, _ in selected:
        component_name, *nodes = path.lstrip("/").split("/")
        if component_name not in components:
            package, local = component_name.rsplit(".", 1)
            components[component_name] = ET.SubElement(root, namespace + "component-schema", {
                namespace + "package": package, namespace + "name": local})
        parent = components[component_name]
        for node in nodes:
            found = next((child for child in parent if child.get(namespace + "name") == node), None)
            parent = found if found is not None else ET.SubElement(parent, "node", {namespace + "name": node})
        ET.SubElement(parent, "prop", {namespace + "name": name})
    (registry / "main.xcd").write_bytes(ET.tostring(root))
    soffice = tmp_path / "LibreOffice/program/soffice"
    assert qa.validate_profile_properties(soffice, allow_missing_optional=True) == selected
    security = next(node for node in root.iter("prop") if node.get(namespace + "name") == "DisableMacrosExecution")
    security.set(namespace + "name", "unsupported")
    (registry / "main.xcd").write_bytes(ET.tostring(root))
    with pytest.raises(ValueError, match="macro/network"):
        qa.validate_profile_properties(soffice, allow_missing_optional=True)


class FakeProcess:
    pid = 4242
    returncode = None
    _handle = 999

    def __init__(self, error=None):
        self.error = error
        self.killed = False
        self.waited = False

    def communicate(self, timeout):
        if self.error:
            raise self.error
        self.returncode = 0
        return b"real child output", None

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout):
        self.waited = True


@pytest.mark.parametrize("error", [None, TimeoutError("deadline"), KeyboardInterrupt()])
def test_owned_job_is_closed_on_success_timeout_and_interrupt(monkeypatch, error):
    monkeypatch.setattr(qa, "WINDOWS", True)
    process = FakeProcess(error)
    closed = []

    class Job:
        def __init__(self, child):
            assert child is process

        def close(self):
            closed.append(True)
            process.returncode = process.returncode if process.returncode is not None else -9

        def wait_empty(self, timeout):
            assert timeout > 0

    monkeypatch.setattr(qa.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(qa, "_OwnedWindowsJob", Job)
    if error:
        with pytest.raises(type(error)):
            qa.run_owned(["soffice.com"], {"SystemRoot": r"C:\Windows"}, 10)
    else:
        assert qa.run_owned(["soffice.com"], {"SystemRoot": r"C:\Windows"}, 10)["pid"] == 4242
    assert closed == [True] and process.waited


def test_owned_job_does_not_count_launcher_exit_as_descendant_completion(monkeypatch):
    monkeypatch.setattr(qa, "WINDOWS", True)
    process = FakeProcess()
    closed = []

    class Job:
        def __init__(self, child):
            assert child is process

        def wait_empty(self, timeout):
            raise TimeoutError("owned descendant still active")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(qa.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(qa, "_OwnedWindowsJob", Job)
    with pytest.raises(TimeoutError, match="descendant"):
        qa.run_owned(["soffice.com"], {"SystemRoot": r"C:\Windows"}, 10)
    assert closed == [True] and process.waited


def test_oracle_records_amount_marker_and_link_loss():
    result = qa.compare_oracle("CODE-B CODE-A R$ 1,00", {"codes": ["CODE-A", "CODE-B"],
                                "markers": ["MISSING"], "expected_money": ["R$ 2,00"],
                                "global_total_display": "R$ 3,00", "external_links": ["https://example.invalid/a"]}, [])
    assert result["missing_markers"] == ["MISSING"]
    assert result["missing_expected_money"] == ["R$ 2,00"]
    assert not result["codes_in_order"] and not result["global_total_present"]
    assert result["missing_external_links"] == ["https://example.invalid/a"]
    assert result["status"] == "ISSUES_RECORDED"


def test_repeated_amount_elsewhere_does_not_pass_an_item_row():
    oracle = {"codes": ["CODE-A", "CODE-B"], "expected_money": ["R$ 2,00", "R$ 4,00"],
              "source_items": [{"codigo": "CODE-A", "quantidade": "1", "valor_unitario": "2,00"},
                               {"codigo": "CODE-B", "quantidade": "2", "valor_unitario": "2,00"}]}
    result = qa.compare_oracle("CODE-A 1 WRONG CODE-B 2 R$ 2,00 R$ 4,00", oracle, [])
    assert not result["missing_expected_money"]
    assert result["missing_monetary_row_values"][0]["code"] == "CODE-A"
    assert result["status"] == "ISSUES_RECORDED"


def test_source_decimal_is_localized_independently_for_row_comparison():
    oracle = {"codes": ["CODE-A"], "expected_money": ["R$ 5.002,20"],
              "source_items": [{"codigo": "CODE-A", "quantidade": "4", "valor_unitario": "1250,55"}]}
    result = qa.compare_oracle("CODE-A 4 R$ 1.250,55 R$ 5.002,20", oracle, [])
    assert result["missing_monetary_row_values"] == []
    assert result["status"] == "TEXT_ORACLE_PASS_VISUAL_PENDING"


def test_real_pdf_metrics_render_pages_and_keep_diff_pending(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = tmp_path / "real.pdf"
    document = pymupdf.open()
    page = document.new_page(width=595.276, height=841.89)
    page.insert_text((72, 72), "QA-CODE transformed")
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(70, 60, 240, 80), "uri": "https://example.invalid/qa"})
    document.save(pdf)
    document.close()
    result = qa.pdf_evidence(pdf, seed(), {"codes": ["QA-CODE"], "external_links": ["https://example.invalid/qa"]}, tmp_path, 72)
    assert result["page_count"] == 1 and result["pages"][0]["a4"]
    assert result["oracle_checks"]["status"] == "TEXT_ORACLE_PASS_VISUAL_PENDING"
    assert result["text_diff_groups"] > 0 and result["visual_review"] == "PENDING"
    assert (tmp_path / "pages/page-001.png").read_bytes().startswith(b"\x89PNG")
    assert (tmp_path / "text-diff.json").is_file()


@pytest.fixture(scope="module")
def native_witness_fixture(tmp_path_factory):
    from scripts.wordcraft_corpus import generate_full
    base = tmp_path_factory.mktemp("lo-native-contract")
    inputs, native = base / "inputs", base / "native"
    manifest = generate_full(inputs)
    report = {"schema": "gc-wordcraft-full-roundtrip/v1", "synthetic_only": True,
              "status": "NATIVE_EXECUTION_FIDELITY_NOT_APPROVED", "variant_count": 16,
              "cases_with_failure_or_difference": 0, "engine_manifest_sha256": "a" * 64,
              "input_manifest_sha256": qa.digest(inputs / "full-manifest.json"), "cases": []}
    steps = {name: "PASS" for name in ("native_import_and_validation", "export_docx", "ordered_text_stories_links",
                                     "source_oracles_and_structures", "reimport_exported_docx", "export_pdf", "pdf_item_codes")}
    for case in manifest["cases"]:
        for variant in case["variants"]:
            target = native / case["id"] / Path(variant["docx"]).stem
            target.mkdir(parents=True)
            # Contract fixture only. It does not assert native engine execution.
            (target / "checkpoint.json").write_bytes(b"synthetic QA contract witness")
            (target / "roundtrip.pdf").write_bytes(b"%PDF-contract-never-rendered")
            shutil.copyfile(inputs / variant["docx"], target / "roundtrip.docx")
            report["cases"].append({"case": case["id"], "source": variant["docx"], "steps": steps,
                                    "source_sha256": variant["sha256_docx"],
                                    "checkpoint_sha256": qa.digest(target / "checkpoint.json"),
                                    "docx_sha256": qa.digest(target / "roundtrip.docx"),
                                    "docx_bytes": (target / "roundtrip.docx").stat().st_size,
                                    "pdf_sha256": qa.digest(target / "roundtrip.pdf")})
    (native / "comparison.json").write_text(json.dumps(report))
    return base, inputs, native, manifest


def test_native_exports_require_exact_pinned_completed_corpus(native_witness_fixture, monkeypatch):
    base, inputs, native, manifest = native_witness_fixture
    monkeypatch.setattr(qa, "WORK_ROOT", base)
    monkeypatch.setattr(qa, "ROOT", base / "repo")
    sources, provenance = qa.roundtrip_sources(inputs, manifest, native, qa.digest(native / "comparison.json"))
    assert len(sources) == 16 and sources["C01/dfd.docx"] == native / "C01/dfd/roundtrip.docx"
    assert provenance["native_engine_manifest_sha256"] == "a" * 64


@pytest.mark.parametrize("mutation", ["comparison_digest", "checkpoint", "docx", "missing_step", "wrong_input_manifest"])
def test_native_exports_refuse_stale_hashes_or_unproved_steps(native_witness_fixture, tmp_path, monkeypatch, mutation):
    base, inputs, native, manifest = native_witness_fixture
    target = tmp_path / "native"
    shutil.copytree(native, target)
    monkeypatch.setattr(qa, "WORK_ROOT", base.parent)
    monkeypatch.setattr(qa, "ROOT", base.parent / "repo")
    comparison = target / "comparison.json"
    pin = qa.digest(comparison)
    if mutation == "comparison_digest":
        comparison.write_bytes(comparison.read_bytes() + b" ")
    elif mutation in {"checkpoint", "docx"}:
        artifact = target / "C01/dfd" / ("checkpoint.json" if mutation == "checkpoint" else "roundtrip.docx")
        artifact.write_bytes(artifact.read_bytes() + b"changed")
    else:
        report = json.loads(comparison.read_text())
        if mutation == "missing_step":
            del report["cases"][0]["steps"]["native_import_and_validation"]
        else:
            report["input_manifest_sha256"] = "b" * 64
        comparison.write_text(json.dumps(report))
        pin = qa.digest(comparison)
    with pytest.raises(ValueError):
        qa.roundtrip_sources(inputs, manifest, target, pin)


@pytest.mark.parametrize("mutation", ["incomplete", "pdf_changed", "png_missing"])
def test_three_way_refuses_incomplete_or_changed_evidence(native_witness_fixture, tmp_path, monkeypatch, mutation):
    base, inputs, _, manifest = native_witness_fixture
    monkeypatch.setattr(qa, "WORK_ROOT", base.parent)
    monkeypatch.setattr(qa, "ROOT", base.parent / "repo")
    baseline, derived, output = tmp_path / "baseline", tmp_path / "derived", tmp_path / "comparison"
    for directory in (baseline, derived):
        directory.mkdir()
        (directory / ".synthetic-qa-only").write_text("QA")
    artifact = baseline / "synthetic.pdf"
    artifact.write_bytes(b"contract artifact, never parsed as PDF")
    cases = [{"source": variant["docx"], "pdf": "synthetic.pdf", "pdf_sha256": qa.digest(artifact),
              "page_count": 1, "pages": [{"png": "pages/page-001.png", "png_sha256": "a" * 64}]}
             for case in manifest["cases"] for variant in case["variants"]]
    report = {"schema": "gc-wordcraft-libreoffice-qa/v1", "synthetic_only": True, "completed_docx": 16, "cases": cases,
              "input_bytes_unchanged": True, "inputs_manifest_sha256": qa.digest(inputs / "full-manifest.json")}
    if mutation == "incomplete":
        report["completed_docx"] = 15
    elif mutation == "pdf_changed":
        artifact.write_bytes(b"changed artifact")
    (baseline / "report.json").write_text(json.dumps(report))
    with pytest.raises((ValueError, FileNotFoundError)):
        qa.compare_three_way(inputs, baseline, derived, output)
    assert not output.exists()


@pytest.mark.parametrize("mutation", [None, "prefix", "source", "pdf", "png"])
def test_resume_verifies_prefix_without_rewriting_completed_evidence(native_witness_fixture, tmp_path, mutation):
    _, inputs, _, manifest = native_witness_fixture
    output = tmp_path / "partial"
    output.mkdir()
    (output / ".synthetic-qa-only").write_text("QA")
    receipt = tmp_path / "runtime-receipt.json"
    receipt.write_text("synthetic provenance fixture")
    variants = [(case["id"], variant) for case in manifest["cases"] for variant in case["variants"]]
    source_digests = {variant["docx"]: variant["sha256_docx"] for _, variant in variants}
    cases = []
    for case_id, variant in variants[:2]:
        directory = output / case_id
        directory.mkdir()
        pdf, png = directory / "evidence.pdf", directory / "page.png"
        pdf.write_bytes(b"synthetic immutable PDF contract bytes")
        png.write_bytes(b"synthetic immutable PNG contract bytes")
        cases.append({"source": variant["docx"], "source_sha256": variant["sha256_docx"],
                      "pdf": pdf.relative_to(output).as_posix(), "pdf_sha256": qa.digest(pdf),
                      "page_count": 1, "pages": [{"png": "page.png", "png_sha256": qa.digest(png)}]})
    report = {"schema": "gc-wordcraft-libreoffice-qa/v1", "synthetic_only": True, "cases": cases,
              "inputs_manifest_sha256": qa.digest(inputs / "full-manifest.json"), "runtime_receipt_sha256": qa.digest(receipt)}
    if mutation == "prefix":
        cases.reverse()
    elif mutation == "source":
        source_digests[cases[0]["source"]] = "b" * 64
    elif mutation in {"pdf", "png"}:
        (output / "C01" / ("evidence.pdf" if mutation == "pdf" else "page.png")).write_bytes(b"changed")
    (output / "report.json").write_text(json.dumps(report))
    before = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
    if mutation:
        with pytest.raises(ValueError):
            qa.resumable_report(output, inputs, variants, source_digests, receipt, {})
    else:
        assert len(qa.resumable_report(output, inputs, variants, source_digests, receipt, {})["cases"]) == 2
    assert {path: path.read_bytes() for path in before} == before


def test_conversion_failure_retains_a_terminal_partial_report(native_witness_fixture, tmp_path, monkeypatch):
    base, inputs, _, _ = native_witness_fixture
    monkeypatch.setattr(qa, "WORK_ROOT", base.parent)
    monkeypatch.setattr(qa, "ROOT", base.parent / "repo")
    receipt = tmp_path / "receipt.json"
    receipt.write_text("contract receipt")
    monkeypatch.setattr(qa, "validate_runtime", lambda _: (tmp_path / "soffice.com", {
        "official_url": "synthetic contract", "effective_url": "synthetic contract", "msi_sha256": "a" * 64}))
    monkeypatch.setattr(qa, "run_owned", lambda *args: {"output": "LibreOffice 26.8.1.1", "returncode": 0})
    def failure(*args, **kwargs):
        raise RuntimeError("bounded invocation failed")
    monkeypatch.setattr(qa, "convert_missing_pdf", failure)
    output = tmp_path / "partial"
    with pytest.raises(RuntimeError, match="bounded invocation"):
        qa.run(inputs, output, receipt)
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "CONVERSION_FAILED_PARTIAL_PDFS_PRESERVED"
    assert report["failed_source"] == "C01/dfd.docx" and report["cases"] == []
    assert "completed_docx" not in report


def test_raster_comparison_records_pixels_dimensions_and_excess_pages(tmp_path):
    from PIL import Image
    first, changed, resized, extra = [tmp_path / name for name in ("first.png", "changed.png", "resized.png", "extra.png")]
    Image.new("RGB", (10, 10), "white").save(first)
    image = Image.new("RGB", (10, 10), "white")
    image.putpixel((4, 5), (0, 0, 0))
    image.save(changed)
    Image.new("RGB", (11, 10), "white").save(resized)
    Image.new("RGB", (10, 10), "black").save(extra)
    result = qa.compare_page_rasters([first, first, first], [changed, resized, first, extra], tmp_path / "comparison")
    assert [page["status"] for page in result["pages"]] == ["RASTER_DIFFERENCES_RECORDED", "RASTER_DIMENSIONS_DIFFER",
        "RASTER_PIXELS_IDENTICAL", "PAGE_WITHOUT_ORDINAL_COUNTERPART"]
    assert result["pages"][0]["changed_pixel_fraction"] == 0.01
    assert result["pages"][0]["difference_bbox"] == (4, 5, 5, 6)
    assert Path(result["pages"][0]["difference_png"]["path"]).is_file()
    assert result["pages"][3]["first"] is None
    assert result["visual_fidelity_approved"] is False
    assert result["status"] == "RASTER_DIFFERENCES_RECORDED_VISUAL_REVIEW_REQUIRED"


def test_identical_raster_does_not_grant_visual_fidelity_approval(tmp_path):
    from PIL import Image
    image = tmp_path / "page.png"
    Image.new("RGB", (10, 10), "white").save(image)
    result = qa.compare_page_rasters([image], [image], tmp_path / "comparison")
    assert result["status"] == "RASTER_IDENTICAL_VISUAL_REVIEW_PENDING"
    assert result["visual_fidelity_approved"] is False


def test_no_pages_cannot_be_reported_as_identical_rasters(tmp_path):
    with pytest.raises(ValueError, match="actual pages"):
        qa.compare_page_rasters([], [], tmp_path / "comparison")
    assert not (tmp_path / "comparison").exists()


def test_complete_three_way_renders_every_native_page_and_records_extras_without_approval(native_witness_fixture, tmp_path, monkeypatch):
    """Real PDF/raster processing with synthetic provenance contract fixtures.

    This test does not claim execution of the native engine or LibreOffice.
    """
    pymupdf = pytest.importorskip("pymupdf")
    base, inputs, source_native, manifest = native_witness_fixture
    monkeypatch.setattr(qa, "WORK_ROOT", base.parent)
    monkeypatch.setattr(qa, "ROOT", base.parent / "repo")
    native = tmp_path / "native"
    shutil.copytree(source_native, native)
    native_report = json.loads((native / "comparison.json").read_text())
    single = pymupdf.open()
    single.new_page(width=595.276, height=841.89).insert_text((72, 72), "synthetic contract PDF")
    single_bytes = single.tobytes()
    single.close()
    double = pymupdf.open(stream=single_bytes, filetype="pdf")
    double.new_page(width=595.276, height=841.89).insert_text((72, 72), "second native contract page")
    double_bytes = double.tobytes()
    double.close()
    for case in native_report["cases"]:
        target = native / case["case"] / Path(case["source"]).stem / "roundtrip.pdf"
        target.write_bytes(double_bytes)
        case["pdf_sha256"] = qa.digest(target)
    (native / "comparison.json").write_text(json.dumps(native_report))
    baseline, derived = tmp_path / "baseline", tmp_path / "derived"
    for directory, kind in ((baseline, "ORIGINAL_DOCX"), (derived, "NATIVE_REEXPORTED_DOCX")):
        directory.mkdir()
        (directory / ".synthetic-qa-only").write_text("contract")
        pdf = directory / "synthetic.pdf"
        pdf.write_bytes(single_bytes)
        with pymupdf.open(pdf) as document:
            document[0].get_pixmap(alpha=False).save(directory / "page.png")
        cases = [{"source": variant["docx"], "source_sha256": variant["sha256_docx"], "pdf": "synthetic.pdf",
                  "pdf_sha256": qa.digest(pdf), "page_count": 1,
                  "pages": [{"png": "page.png", "png_sha256": qa.digest(directory / "page.png")}]} 
                 for case in manifest["cases"] for variant in case["variants"]]
        report = {"schema": "gc-wordcraft-libreoffice-qa/v1", "synthetic_only": True, "completed_docx": 16,
                  "input_bytes_unchanged": True, "inputs_manifest_sha256": qa.digest(inputs / "full-manifest.json"),
                  "conversion_input": kind, "runtime_source": "UBUNTU_DISTRIBUTION_PACKAGES_NOT_WINDOWS_MSI",
                  "runtime_identity_sha256": "a" * 64, "runtime_version": {"output": "synthetic contract"}, "dpi": 72, "cases": cases}
        if directory == derived:
            report.update(roundtrip_root=str(native), roundtrip_comparison_sha256=qa.digest(native / "comparison.json"))
        (directory / "report.json").write_text(json.dumps(report))
    output = tmp_path / "comparison"
    result = qa.compare_three_way(inputs, baseline, derived, output)
    assert result["completed_sources"] == 16 and result["native_rendered_pages"] == 32
    assert len(list(output.glob("*/*/wordcraft-pdf/pages/*.png"))) == 32
    assert result["visual_fidelity_approved"] is False and result["cases_with_raster_differences"] == 16
    assert result["cases_with_text_oracle_issues"] > 0  # missing fixture text remains visible
    assert result["cases"][0]["raster_comparisons"]["original-vs-reexported"]["status"] == "RASTER_IDENTICAL_VISUAL_REVIEW_PENDING"
    extra = result["cases"][0]["raster_comparisons"]["original-vs-wordcraft"]["pages"][1]
    assert extra["status"] == "PAGE_WITHOUT_ORDINAL_COUNTERPART" and extra["first"] is None
