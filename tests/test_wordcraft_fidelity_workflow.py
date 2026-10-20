"""Executable namespace/provenance contracts for isolated Linux fidelity CI."""
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/wordcraft-fidelity.yml"
BUILD_WORKFLOW = ROOT / ".github/workflows/wordcraft-build.yml"
ZIP_SHA = "a57bdc0b05660afb3ea37e0625e50fc2d33e78fa9e995822210e51580c79221d"
PRODUCER = "39fec20fc5e94590a95cfd9af8d0ce34d07c3e54"
MANIFEST_SHA = "bd306cdb4709a43314366375da91ca1d00b2dd6db3c7683fff44eb15eb087548"


def workflow():
    # YAML 1.1 SafeLoader treats the GitHub `on` key as bool. BaseLoader keeps
    # the workflow's spelling without globally changing PyYAML resolvers.
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def step_starting(name):
    return next(step for step in workflow()["jobs"]["fidelity"]["steps"] if step.get("name", "").startswith(name))


def python_blocks(step):
    return re.findall(r"(?ms)^python - <<'PY'\n(.*?)^PY(?:\n|$)", step["run"])


def run_python_block(step):
    blocks = python_blocks(step)
    assert len(blocks) == 1
    exec(compile(blocks[0], str(WORKFLOW), "exec"), {"__name__": "__main__"})


def test_workflow_has_read_only_permissions_no_services_and_scoped_artifact_token():
    value = workflow()
    assert value["permissions"] == {"contents": "read", "actions": "read"}
    job = value["jobs"]["fidelity"]
    assert job["runs-on"] == "ubuntu-24.04" and "services" not in job
    assert value["concurrency"]["cancel-in-progress"] == "false"
    assert "workflow_dispatch" in value["on"]
    token_steps = [step for step in job["steps"] if "github.token" in json.dumps(step)]
    assert len(token_steps) == 1 and token_steps[0]["name"].startswith("Download and admit pinned")
    assert "secrets." not in WORKFLOW.read_text() and "pull_request_target" not in value["on"]
    checkout = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] == "false"


def test_workflow_embedded_python_is_syntactically_valid():
    blocks = [block for step in workflow()["jobs"]["fidelity"]["steps"] if "run" in step for block in python_blocks(step)]
    assert len(blocks) == 4
    for block in blocks:
        ast.parse(block)


def test_browser_build_installs_the_dependency_used_by_synthetic_admission():
    value = yaml.load(BUILD_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = value["jobs"]["upstream"]["steps"]
    install = next(step for step in steps
                   if step.get("name") == "Install pinned synthetic admission dependency")
    assert "'python-docx==1.2.0'" in install["run"]
    assert "'pypdf==6.21.1'" in install["run"]
    admission = next(step for step in steps
                     if step.get("name") == "Exercise the real native canvas, input barrier and undo in Chromium")
    assert "scripts/wordcraft_browser_qa.mjs" in admission["run"]


@pytest.mark.skipif(os.name == "nt", reason="Bash parsing is required on Ubuntu CI; Windows sandbox refuses MSYS named objects (0xC0000022)")
def test_workflow_bash_commands_parse_with_the_real_linux_shell():
    bash = Path(shutil.which("bash") or "")
    assert bash.is_file(), "A real Bash parser is required for workflow command validation"
    for step in workflow()["jobs"]["fidelity"]["steps"]:
        if "run" not in step:
            continue
        parsed = subprocess.run([str(bash), "-n"], input=step["run"], text=True, capture_output=True, timeout=10)
        assert parsed.returncode == 0, parsed.stderr


@pytest.fixture
def ci_env(tmp_path, monkeypatch):
    repo = tmp_path / "work/repo"
    repo.mkdir(parents=True)
    env_file = tmp_path / "github-env"
    evidence = repo / "build-evidence/wordcraft-fidelity"
    for key, value in {"GITHUB_WORKSPACE": repo, "GITHUB_ENV": env_file, "GITHUB_RUN_ID": "12345",
                       "GITHUB_RUN_ATTEMPT": "2", "GITHUB_SHA": "b" * 40, "RUNNER_TEMP": tmp_path / "temp"}.items():
        monkeypatch.setenv(key, str(value))
    return repo, evidence, env_file


def test_namespace_creates_only_fresh_synthetic_siblings_and_records_pins(ci_env):
    repo, evidence, env_file = ci_env
    run_python_block(step_starting("Prepare fresh"))
    values = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
    assert Path(values.pop("FIDELITY_EVIDENCE")) == evidence
    assert len(values) == 6
    assert all(Path(value).parent == repo.parent and not Path(value).exists() for value in values.values())
    receipt = json.loads((evidence / "execution.json").read_text())
    assert receipt["artifact_id"] == 11995992777 and receipt["artifact_sha256"] == ZIP_SHA
    assert receipt["producer_commit"] == PRODUCER and receipt["manifest_sha256"] == MANIFEST_SHA
    assert receipt["visual_review"] == "PENDING" and receipt["synthetic_only"] is True


def test_namespace_refuses_stale_sibling_before_writing_execution_evidence(ci_env):
    repo, evidence, env_file = ci_env
    stale = repo.parent / "wordcraft-fidelity-corpus-12345-2"
    stale.mkdir()
    sentinel = stale / "preserve.txt"
    sentinel.write_text("prior evidence")
    with pytest.raises(ValueError, match="Fresh sibling"):
        run_python_block(step_starting("Prepare fresh"))
    assert sentinel.read_text() == "prior evidence" and not env_file.exists()
    assert not (evidence / "execution.json").exists()


@pytest.mark.parametrize("manifest_valid", [True, False])
def test_artifact_step_passes_exact_pins_to_existing_installer_and_refuses_changed_manifest(ci_env, monkeypatch, manifest_valid):
    from scripts import wordcraft_local_assets as assets
    repo, evidence, env_file = ci_env
    run_python_block(step_starting("Prepare fresh"))
    values = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    calls = []
    def install(archive, lab, **pins):
        calls.append((archive, lab, pins))
        assert (lab / ".wordcraft-local-qa").read_text() == assets.MARKER
        return {"manifest_sha256": MANIFEST_SHA if manifest_valid else "0" * 64,
                "artifact_sha256": pins["artifact_sha256"], "producer_commit": pins["producer_commit"]}
    monkeypatch.setattr(assets, "install", install)
    before = env_file.read_text()
    if manifest_valid:
        run_python_block(step_starting("Download and admit pinned"))
        receipt = json.loads((evidence / "native-artifact-admission.json").read_text())
        assert receipt["artifact_id"] == 11995992777 and receipt["manifest_sha256"] == MANIFEST_SHA
        assert "FIDELITY_NATIVE_BUNDLE=" in env_file.read_text()
    else:
        with pytest.raises(ValueError, match="manifest differs"):
            run_python_block(step_starting("Download and admit pinned"))
        assert env_file.read_text() == before and not (evidence / "native-artifact-admission.json").exists()
    assert len(calls) == 1
    assert calls[0][2] == {"artifact_sha256": ZIP_SHA, "producer_commit": PRODUCER}
    assert calls[0][0].name == "native-qa.zip"


def test_native_and_lo_steps_use_explicit_real_adapters_and_preserve_partial_markers():
    native = step_starting("Execute actual native")["run"]
    assert "scripts/wordcraft_full_roundtrip.py" in native and "--manifest-sha256 " + MANIFEST_SHA in native
    for name in ("Convert original synthetic", "Convert actual native"):
        command = step_starting(name)["run"]
        assert "--institutional-adapter --system-soffice /usr/bin/libreoffice" in command
        assert "--runtime-receipt" not in command and "--refresh-metrics" not in command
    converted = step_starting("Convert actual native")["run"]
    assert '--roundtrip-comparison-sha256 "$FIDELITY_NATIVE_COMPARISON_SHA256"' in converted
    upload = next(step for step in workflow()["jobs"]["fidelity"]["steps"] if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["if"] == "always()" and upload["with"]["include-hidden-files"] == "true"
    assert "RUNNER_TEMP" not in upload["with"]["path"]
    assert "${{ env.FIDELITY_LO_ORIGINAL }}" in upload["with"]["path"]
    assert "${{ env.FIDELITY_LO_REEXPORTED }}" in upload["with"]["path"]
    assert "../" not in upload["with"]["path"]


@pytest.mark.parametrize("text_issues", [0, 1])
def test_summary_keeps_image_differences_pending_and_fails_text_issues_after_recording(tmp_path, monkeypatch, text_issues):
    comparison = tmp_path / "comparison"
    comparison.mkdir()
    summary = tmp_path / "summary.md"
    report = {"cases": [{}] * 16, "cases_with_raster_differences": 16, "cases_with_text_oracle_issues": text_issues,
              "visual_fidelity_approved": False}
    source = comparison / "comparison.json"
    source.write_text(json.dumps(report))
    before = source.read_bytes()
    monkeypatch.setenv("FIDELITY_COMPARISON", str(comparison))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    if text_issues:
        with pytest.raises(SystemExit, match="Text oracle differences"):
            run_python_block(step_starting("Compare three actual"))
    else:
        run_python_block(step_starting("Compare three actual"))
    assert "Cases with raster differences: 16" in summary.read_text()
    assert "visual fidelity is not approved" in summary.read_text()
    assert source.read_bytes() == before
