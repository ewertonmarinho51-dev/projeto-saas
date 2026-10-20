"""Confined real LibreOffice QA of the complete synthetic G3 corpus.

No database, provider, listener or network input is used. Explicit Linux CI mode
reuses the existing institutional DOCX converter without any fallback.
Outputs remain evidence awaiting visual inspection.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes
import difflib
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import unicodedata
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = ROOT.parent
WINDOWS = os.name == "nt"
LINUX = sys.platform.startswith("linux")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.wordcraft_corpus import text_blocks, verify_full_inputs, _verificar_entrada_docx
from scripts.wordcraft_libreoffice_extract import SHA256, digest
from src.wordcraft_native import preflight_docx

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
PROFILE_ITEMS = [
    ("/org.openoffice.Office.Common/Misc", "CrashReport", "false"),
    ("/org.openoffice.Office.Common/Misc", "UseOpenCL", "false"),
    ("/org.openoffice.Office.Calc/Formula/Calculation", "OpenCLAutoSelect", "false"),
    ("/org.openoffice.Office.Common/Security/Scripting", "MacroSecurityLevel", "3"),
    ("/org.openoffice.Office.Common/Security/Scripting", "DisableMacrosExecution", "true"),
    ("/org.openoffice.Inet/Settings", "ooInetProxyType", "2"),
    ("/org.openoffice.Inet/Settings", "ooInetHTTPProxyName", "127.0.0.1"),
    ("/org.openoffice.Inet/Settings", "ooInetHTTPProxyPort", "9"),
    ("/org.openoffice.Inet/Settings", "ooInetHTTPSProxyName", "127.0.0.1"),
    ("/org.openoffice.Inet/Settings", "ooInetHTTPSProxyPort", "9"),
    ("/org.openoffice.Inet/Settings", "ooInetNoProxy", ""),
    ("/org.openoffice.Office.Jobs/Jobs/UpdateCheck/Arguments", "AutoCheckEnabled", "false"),
    ("/org.openoffice.Office.Jobs/Jobs/UpdateCheck/Arguments", "AutoDownloadEnabled", "false"),
]


def validate_profile_properties(soffice: Path, *, allow_missing_optional: bool = False) -> list:
    namespace = "{http://openoffice.org/2001/registry}"
    registry = soffice.parent.parent / "share/registry"
    available = set()

    def walk(element, path):
        name = element.get(namespace + "name")
        path = path + "/" + name if name else path
        if element.tag == "prop":
            available.add(path)
        for child in element:
            walk(child, path)

    for filename in ("main.xcd", "onlineupdate.xcd"):
        if allow_missing_optional and filename == "onlineupdate.xcd" and not (registry / filename).is_file():
            continue
        root = ET.fromstring((registry / filename).read_bytes())
        for component in root:
            if component.tag in {namespace + "component-schema", namespace + "component-data"}:
                package = component.get(namespace + "package", "")
                name = component.get(namespace + "name", "")
                # The registry addresses components with package.name; nodes
                # below them are slash-separated in registrymodifications.xcu.
                for child in component:
                    walk(child, "/" + package + "." + name)
    required = [item for item in PROFILE_ITEMS if not allow_missing_optional or
                item[0].startswith(("/org.openoffice.Inet/", "/org.openoffice.Office.Common/Security/"))]
    if any(path + "/" + name not in available for path, name, _ in required):
        raise ValueError("Pinned runtime lacks required macro/network profile properties")
    return [item for item in PROFILE_ITEMS if item[0] + "/" + item[1] in available]


def confined_output(path: Path, inputs: Path, *, resume: bool = False) -> Path:
    path = path.resolve()
    if (path == WORK_ROOT or not path.is_relative_to(WORK_ROOT)
            or path.is_relative_to(ROOT) or path.is_relative_to(WORK_ROOT / "toolchain")
            or path.is_relative_to(inputs) or inputs.is_relative_to(path)):
        raise ValueError("QA output must be separate under work, outside repo, inputs and toolchain")
    if path.exists() and not resume:
        raise ValueError("QA output must be new; stale artifacts are not evidence")
    return path


def validate_runtime(receipt_path: Path) -> tuple[Path, dict]:
    toolchain = (WORK_ROOT / "toolchain").resolve()
    receipt_path = receipt_path.resolve(strict=True)
    if not toolchain.is_relative_to(WORK_ROOT.resolve()) or not receipt_path.is_relative_to(toolchain):
        raise ValueError("Runtime receipt escaped work/toolchain")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (receipt.get("schema") != "gc-wordcraft-lo-extraction/v1"
            or receipt.get("msi_sha256") != SHA256 or receipt.get("published_sha256") != SHA256
            or receipt.get("method") != "MSI_READONLY_STREAM_CAB_EXPAND_NO_INSTALL_ACTIONS"):
        raise ValueError("Unpinned LibreOffice provenance")
    image = Path(receipt["image"]).resolve(strict=True)
    msi = Path(receipt["msi"]).resolve(strict=True)
    if not image.is_relative_to(toolchain) or not msi.is_relative_to(toolchain) or digest(msi) != SHA256:
        raise ValueError("Official MSI changed or escaped toolchain")
    soffice = Path(receipt["soffice"]).resolve(strict=True)
    if soffice != image / "LibreOffice" / "program" / "soffice.com":
        raise ValueError("Runtime executable differs from extracted image")
    def check_file(item):
        target = (image / item["path"]).resolve(strict=True)
        if (not target.is_relative_to(image) or not target.is_file()
                or target.stat().st_size != item["bytes"] or digest(target) != item["sha256"]):
            raise ValueError("Extracted runtime inventory changed")
        return target

    with ThreadPoolExecutor(max_workers=8) as executor:
        checked = list(executor.map(check_file, receipt["files"]))
    seen = set(checked)
    if len(seen) != len(checked):
        raise ValueError("Duplicate extracted runtime inventory entry")
    actual = {path.resolve() for path in image.rglob("*") if path.is_file()}
    if actual != seen or digest(soffice) != receipt["soffice_sha256"]:
        raise ValueError("Unexpected runtime file or executable digest")
    validate_profile_properties(soffice)
    return soffice, receipt


def admit_synthetic_docx(data: bytes) -> list[str]:
    """Reuse upload admission, then narrow inert QA hyperlinks and fields."""
    preflight_docx(data)
    links = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            if not name.endswith((".xml", ".rels")):
                continue
            root = ET.fromstring(archive.read(name))
            if name.endswith(".rels"):
                for relation in root:
                    if relation.get("TargetMode") == "External":
                        target = relation.get("Target", "")
                        parsed = urlsplit(target)
                        if (not relation.get("Type", "").endswith("/hyperlink")
                                or parsed.scheme != "https" or parsed.hostname != "example.invalid"
                                or parsed.username or parsed.password or parsed.port is not None):
                            raise ValueError("QA only permits inert example.invalid hyperlink metadata")
                        links.append(target)
            fields = [node.text or "" for node in root.iter(W + "instrText")]
            fields += [node.get(W + "instr", "") for node in root.iter(W + "fldSimple")]
            if any(value.strip().upper() != "PAGE" for value in fields):
                raise ValueError("QA refuses active or unrecognized document fields")
            if any(node.tag in {W + "altChunk", W + "object", W + "control"} for node in root.iter()):
                raise ValueError("QA refuses embedded active content")
    return sorted(links)


def make_profile(profile: Path, items: list | None = None) -> None:
    user = profile / "user"
    user.mkdir(parents=True)
    (profile.parent / "crash").mkdir(exist_ok=True)
    # Property paths are checked against the official extracted registry above.
    content = ['<?xml version="1.0" encoding="UTF-8"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">']
    for path, name, value in PROFILE_ITEMS if items is None else items:
        content.append(f'<item oor:path="{path}"><prop oor:name="{name}" oor:op="fuse"><value>{value}</value></prop></item>')
    content.append("</oor:items>")
    (user / "registrymodifications.xcu").write_text("\n".join(content), encoding="utf-8")


def child_environment(soffice: Path, scratch: Path) -> dict:
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "SystemDrive", "COMSPEC", "PATHEXT") if key in os.environ}
    system = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    image = soffice.parents[2]
    env["PATH"] = os.pathsep.join(map(str, (soffice.parent, image / "System64" / "amd64", image / "System", system / "System32")))
    for key, part in (("TEMP", "tmp"), ("TMP", "tmp"), ("APPDATA", "roaming"), ("LOCALAPPDATA", "local"), ("USERPROFILE", "home")):
        directory = scratch / part
        directory.mkdir(parents=True, exist_ok=True)
        env[key] = str(directory)
    env.update(http_proxy="http://127.0.0.1:9", https_proxy="http://127.0.0.1:9", ALL_PROXY="http://127.0.0.1:9", NO_PROXY="")
    # The official application embeds Python for its dictionaries/UNO loader.
    # Keep generated bytecode out of the verified read-only runtime inventory.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(scratch / "pycache")
    env["CrashDumpEnable"] = "false"
    return env


def json_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_system_runtime(soffice: Path) -> tuple[Path, dict, list]:
    """Explicit Ubuntu CI runtime, never presented as the pinned Windows MSI."""
    if not LINUX:
        raise RuntimeError("The institutional adapter proof requires a disposable Linux runner")
    soffice = soffice.resolve(strict=True)
    if soffice != Path("/usr/lib/libreoffice/program/soffice") or not os.access(soffice, os.X_OK):
        raise ValueError("Only the distribution LibreOffice launcher is admitted in this CI mode")
    timeout = Path("/usr/bin/timeout").resolve(strict=True)
    binary = soffice.with_name("soffice.bin").resolve(strict=True)
    items = validate_profile_properties(soffice, allow_missing_optional=True)
    packages = subprocess.run(["/usr/bin/dpkg-query", "--show", "--showformat=${Package}\t${Version}\t${db:Status-Status}\n",
                               "libreoffice-common", "libreoffice-core", "libreoffice-writer", "coreutils"],
                              env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                              check=True, capture_output=True, timeout=15).stdout.decode("utf-8")
    if len(packages.splitlines()) != 4 or any(not line.endswith("\tinstalled") for line in packages.splitlines()):
        raise ValueError("Required distribution packages are not installed")
    files = [soffice, binary, timeout, soffice.parent.parent / "share/registry/main.xcd"]
    update = soffice.parent.parent / "share/registry/onlineupdate.xcd"
    if update.is_file():
        files.append(update)
    provenance = {"runtime_source": "UBUNTU_DISTRIBUTION_PACKAGES_NOT_WINDOWS_MSI", "packages": packages,
                  "executables_and_registry": [{"path": str(path), "sha256": digest(path)} for path in files],
                  "profile_items_omitted_optional": [list(item) for item in PROFILE_ITEMS if item not in items]}
    return soffice, provenance, items


def system_adapter_environment(soffice: Path, scratch: Path, items: list) -> tuple[dict, Path]:
    """Wrap only the existing product adapter's selected soffice executable."""
    profile = scratch / "profile"
    make_profile(profile, items)
    for name in ("bin", "tmp", "home", "config", "cache"):
        (scratch / name).mkdir()
    log = scratch / "libreoffice.log"
    wrapper = scratch / "bin/soffice"
    command = ["/usr/bin/timeout", "--signal=TERM", "--kill-after=5s", "100s", str(soffice),
               "-env:UserInstallation=" + profile.as_uri(), "-env:CrashDumpEnable=false",
               "-env:CrashDirectory=" + (scratch / "crash").as_uri(),
               "--nologo", "--nodefault", "--norestore", "--nofirststartwizard"]
    wrapper.write_text('#!/bin/sh\nexec ' + shlex.join(command) + ' "$@" >>' + shlex.quote(str(log)) + ' 2>&1\n', encoding="utf-8")
    wrapper.chmod(0o700)
    env = {"PATH": str(scratch / "bin") + ":/usr/bin:/bin", "HOME": str(scratch / "home"),
           "XDG_CONFIG_HOME": str(scratch / "config"), "XDG_CACHE_HOME": str(scratch / "cache"),
           "TMPDIR": str(scratch / "tmp"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
           "SAL_USE_VCLPLUGIN": "gen", "PYTHONDONTWRITEBYTECODE": "1", "CrashDumpEnable": "false",
           "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9",
           "ALL_PROXY": "http://127.0.0.1:9", "NO_PROXY": ""}
    return env, wrapper


def convert_institutional_pdf(soffice: Path, source: Path, output: Path, *, items: list) -> tuple[dict, list]:
    """No fallback: call src.export._docx_em_pdf unchanged in a private CLI env.

    This function temporarily replaces this process's environment and tempfile
    root. It is only used by the sequential standalone QA CLI, never a server.
    """
    from src.export import _docx_em_pdf
    pdf = output / (source.stem + ".pdf")
    if pdf.exists():
        raise ValueError("Unrecorded PDF exists; preserve it for inspection")
    attempts = []
    data = source.read_bytes()
    for attempt in (1, 2):
        scratch = output / f"_institutional-attempt-{attempt}"
        scratch.mkdir()
        env, _ = system_adapter_environment(soffice, scratch, items)
        original_env, original_temp = dict(os.environ), tempfile.tempdir
        started = time.monotonic()
        try:
            os.environ.clear()
            os.environ.update(env)
            tempfile.tempdir = env["TMPDIR"]
            converted = _docx_em_pdf(data)
        finally:
            os.environ.clear()
            os.environ.update(original_env)
            tempfile.tempdir = original_temp
        log = scratch / "libreoffice.log"
        result = {"adapter": "src.export._docx_em_pdf", "attempt": attempt, "source_sha256": digest(source),
                  "seconds": round(time.monotonic() - started, 3), "pdf_created": converted is not None,
                  "output": log.read_text(encoding="utf-8", errors="replace")[:12000] if log.exists() else "",
                  "log_sha256": digest(log) if log.exists() else None}
        (scratch / "adapter-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        attempts.append(result)
        if converted is not None:
            if not converted.startswith(b"%PDF-"):
                raise ValueError("Institutional adapter returned a non-PDF artifact")
            with pdf.open("xb") as stream:
                stream.write(converted)
            return result, attempts
    diagnostic = json.dumps(attempts, ensure_ascii=True, separators=(",", ":"))
    raise ValueError("Existing institutional LibreOffice adapter failed in two recorded attempts; "
                     f"no fallback allowed; diagnostics={diagnostic}")


class _OwnedWindowsJob:
    """Kill only this invocation and its descendants when the job handle closes."""
    def __init__(self, process: subprocess.Popen):
        from ctypes import wintypes as wt

        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wt.DWORD), ("minimum", ctypes.c_size_t), ("maximum", ctypes.c_size_t),
                        ("active", wt.DWORD), ("affinity", ctypes.c_size_t), ("priority", wt.DWORD), ("scheduling", wt.DWORD)]

        class Limits(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_uint64 * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
        self.api.CreateJobObjectW.restype = wt.HANDLE
        self.api.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
        self.api.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
        self.api.QueryInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p]
        self.api.CloseHandle.argtypes = [wt.HANDLE]
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Limits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None

    def wait_empty(self, timeout: float) -> None:
        from ctypes import wintypes as wt

        class Accounting(ctypes.Structure):
            _fields_ = [("times", ctypes.c_int64 * 4), ("faults", wt.DWORD),
                        ("total", wt.DWORD), ("active", wt.DWORD), ("terminated", wt.DWORD)]

        deadline = time.monotonic() + timeout
        while True:
            accounting = Accounting()
            if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if accounting.active == 0:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("Owned LibreOffice descendants did not exit before deadline")
            time.sleep(0.05)


def run_owned(command: list[str], env: dict, timeout: int) -> dict:
    if not WINDOWS:
        raise RuntimeError("This pinned QA runner is Windows-only")
    started = time.monotonic()
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               creationflags=CREATE_NO_WINDOW)
    job = None
    try:
        job = _OwnedWindowsJob(process)
        stdout, _ = process.communicate(timeout=timeout)
        job.wait_empty(max(0.1, timeout - (time.monotonic() - started)))
        result = {"pid": process.pid, "returncode": process.returncode,
                  "seconds": round(time.monotonic() - started, 3),
                  "output": stdout.decode("utf-8", errors="replace")[:12000]}
        if process.returncode:
            raise RuntimeError("LibreOffice failed: " + json.dumps(result))
        return result
    except BaseException as error:
        error.invocation_result = {"pid": process.pid, "returncode": process.poll(),
                                   "seconds": round(time.monotonic() - started, 3),
                                   "error_type": type(error).__name__,
                                   "output": (locals().get("stdout") or getattr(error, "output", b"") or b"").decode("utf-8", errors="replace")[:12000]}
        if job is None and process.poll() is None:
            # Assignment failure: the trusted launcher is still ours. Kill its
            # tree before propagating; no process-name/global termination.
            subprocess.run([str(Path(env["SystemRoot"]) / "System32" / "taskkill.exe"),
                            "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=15)
        raise
    finally:
        if job is not None:
            job.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=15)


def conversion_command(soffice: Path, profile: Path, source: Path, output: Path) -> list[str]:
    return [str(soffice), "-env:UserInstallation=" + profile.as_uri(),
            "-env:CrashDumpEnable=false",
            "-env:CrashDirectory=" + (profile.parent / "crash").as_uri(), "--headless", "--nologo",
            "--nodefault", "--norestore", "--nofirststartwizard", "--convert-to", "pdf:writer_pdf_Export",
            "--outdir", str(output), str(source)]


def convert_missing_pdf(soffice: Path, source: Path, output: Path, *, run_id: int, timeout: int) -> tuple[dict, list]:
    """At most two fresh-profile attempts, only while no PDF exists.

    Observed launcher-zero/missing-output attempts are retained; an existing
    artifact is never overwritten or silently retried as another PDF engine.
    """
    pdf = output / (source.stem + ".pdf")
    if pdf.exists():
        raise ValueError("Unrecorded PDF exists; preserve it for inspection")
    attempts = []
    for attempt in (1, 2):
        scratch = output / f"_scratch-run-{run_id}-attempt-{attempt}"
        scratch.mkdir()
        profile = scratch / "profile"
        make_profile(profile)
        failure = None
        try:
            result = run_owned(conversion_command(soffice, profile, source, output), child_environment(soffice, scratch), timeout)
        except Exception as error:
            if not hasattr(error, "invocation_result"):
                raise
            failure = error
            result = error.invocation_result
        log = output / f"invocation-run-{run_id}-attempt-{attempt}.json"
        with log.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        attempts.append({**result, "log": log.name, "pdf_created": pdf.is_file()})
        if failure:
            if pdf.exists() or attempt == 2:
                raise failure
            continue
        if pdf.is_file():
            return result, attempts
    raise ValueError("LibreOffice returned without creating a PDF in two recorded fresh-profile attempts")


def compact(value: str) -> str:
    return "".join(unicodedata.normalize("NFC", value).split())


def roundtrip_sources(inputs: Path, manifest: dict, root: Path, comparison_sha256: str) -> tuple[dict, dict]:
    """Admit only exports from a separately pinned completed native QA run.

    comparison.json is provenance of the already validated backend execution,
    not a browser identity witness or an alternative native importer.
    """
    root = root.resolve(strict=True)
    if (not root.is_relative_to(WORK_ROOT) or root.is_relative_to(ROOT)
            or root.is_relative_to(WORK_ROOT / "toolchain") or root.is_relative_to(inputs)
            or inputs.is_relative_to(root)):
        raise ValueError("Native roundtrip evidence escaped its separate work namespace")
    comparison = root / "comparison.json"
    if len(comparison_sha256) != 64 or digest(comparison) != comparison_sha256:
        raise ValueError("Native comparison does not match its externally pinned digest")
    report = json.loads(comparison.read_text(encoding="utf-8"))
    if (report.get("schema") != "gc-wordcraft-full-roundtrip/v1" or report.get("synthetic_only") is not True
            or report.get("status") != "NATIVE_EXECUTION_FIDELITY_NOT_APPROVED"
            or report.get("input_manifest_sha256") != digest(inputs / "full-manifest.json")
            or report.get("variant_count") != 16 or report.get("cases_with_failure_or_difference") != 0
            or len(report.get("cases", [])) != 16):
        raise ValueError("Native comparison is incomplete or belongs to other synthetic inputs")
    expected = {variant["docx"]: (case["id"], variant) for case in manifest["cases"] for variant in case["variants"]}
    entries = {entry["source"]: entry for entry in report["cases"]}
    if len(entries) != 16 or set(entries) != set(expected):
        raise ValueError("Native comparison does not cover the exact original variants")
    required_steps = {"native_import_and_validation", "export_docx", "ordered_text_stories_links",
                      "source_oracles_and_structures", "reimport_exported_docx", "export_pdf", "pdf_item_codes"}
    sources = {}
    for name, (case_id, variant) in expected.items():
        entry = entries[name]
        if (entry.get("case") != case_id or entry.get("source_sha256") != variant["sha256_docx"]
                or not required_steps <= set(entry.get("steps", {}))
                or any(value != "PASS" for value in entry["steps"].values())):
            raise ValueError("Native comparison contains an unproved or mismatched step")
        directory = (root / case_id / Path(name).stem).resolve(strict=True)
        if not directory.is_relative_to(root):
            raise ValueError("Native export directory escaped the pinned run")
        for filename, hash_key in (("checkpoint.json", "checkpoint_sha256"),
                                   ("roundtrip.docx", "docx_sha256"), ("roundtrip.pdf", "pdf_sha256")):
            path = (directory / filename).resolve(strict=True)
            if not path.is_relative_to(root) or digest(path) != entry.get(hash_key):
                raise ValueError("Native checkpoint/export bytes changed after their validated execution")
        source = directory / "roundtrip.docx"
        data = source.read_bytes()
        if len(data) != entry.get("docx_bytes"):
            raise ValueError("Native DOCX length changed")
        admit_synthetic_docx(data)
        if text_blocks(data) != text_blocks((inputs / name).read_bytes()):
            raise ValueError("Native export changed ordered text stories or hyperlink metadata")
        oracle = json.loads((inputs / variant["oracle"]).read_text(encoding="utf-8"))
        _verificar_entrada_docx(data, oracle)
        sources[name] = source
    return sources, {"roundtrip_root": str(root), "roundtrip_comparison_sha256": comparison_sha256,
                     "native_engine_manifest_sha256": report["engine_manifest_sha256"]}


def compare_oracle(text: str, oracle: dict, pdf_links: list[str]) -> dict:
    normalized = compact(text)
    checks = {}
    for key in ("markers", "codes", "clause_titles", "signature_names", "required_text", "expected_money"):
        checks["missing_" + key] = [value for value in oracle.get(key, []) if compact(value) not in normalized]
    checks["forbidden_text_present"] = [value for value in oracle.get("forbidden_text", []) if compact(value) in normalized]
    checks["global_total_present"] = (compact(oracle["global_total_display"]) in normalized
                                      if "global_total_display" in oracle else None)
    codes = oracle.get("codes", [])
    positions = [normalized.find(compact(code)) for code in codes]
    checks["codes_in_order"] = (all(position >= 0 for position in positions)
                                and positions == sorted(positions)) if codes else None
    # Text extraction is not a PDF table parser. Record a conservative row
    # window check in addition to whole-document totals so repeated values in
    # another row cannot alone count as preservation of an item's amount.
    checks["missing_monetary_row_values"] = []
    if "source_items" in oracle and "expected_money" in oracle:
        for index, (item, total) in enumerate(zip(oracle["source_items"], oracle["expected_money"])):
            start = positions[index] if index < len(positions) else -1
            end = positions[index + 1] if index + 1 < len(positions) else len(normalized)
            window = normalized[start:end] if start >= 0 and end > start else ""
            # Source decimal strings are not localized display cells: e.g.
            # 1250,55 is printed as 1.250,55. Derive the expected presentation
            # from the independent source Decimal, not from exported text.
            unit = format(Decimal(item["valor_unitario"].replace(",", ".")), ",.2f")
            unit = unit.replace(",", "_").replace(".", ",").replace("_", ".")
            missing = [value for value in (item["quantidade"], unit, total)
                       if compact(str(value)) not in window]
            if missing:
                checks["missing_monetary_row_values"].append({"code": item["codigo"], "missing": missing})
    expected_links = oracle.get("external_links")
    checks["missing_external_links"] = sorted(set(expected_links or []) - set(pdf_links))
    checks["unexpected_external_links"] = sorted(set(pdf_links) - set(expected_links or [])) if expected_links is not None else []
    checks["status"] = "ISSUES_RECORDED" if (any(checks[key] for key in checks if key.startswith(("missing_", "unexpected_", "forbidden_")))
                                              or checks["global_total_present"] is False or checks["codes_in_order"] is False) else "TEXT_ORACLE_PASS_VISUAL_PENDING"
    return checks


def pdf_evidence(pdf: Path, source: bytes, oracle: dict, output: Path, dpi: int, *, reuse_renders: bool = False) -> dict:
    import pymupdf

    if not pdf.is_file() or not pdf.read_bytes().startswith(b"%PDF-"):
        raise ValueError("LibreOffice did not produce a new real PDF")
    document = pymupdf.open(pdf)
    pages, texts, uris = [], [], []
    renders = output / "pages"
    if not reuse_renders:
        renders.mkdir()
    for number, page in enumerate(document, 1):
        text = page.get_text(sort=True)
        texts.append(text)
        links = page.get_links()
        uris.extend(link["uri"] for link in links if link.get("uri"))
        image = renders / f"page-{number:03d}.png"
        if not reuse_renders:
            page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), alpha=False).save(image)
        elif not image.is_file():
            raise ValueError("Metrics refresh requires the existing rendered evidence")
        pages.append({"page": number, "width_pt": round(page.rect.width, 3), "height_pt": round(page.rect.height, 3),
                      "a4": abs(page.rect.width - 595.276) < 1 and abs(page.rect.height - 841.89) < 1,
                      "text_chars": len(text), "images": len(page.get_images()), "links": len(links),
                      "internal_links": sum(link.get("kind") == pymupdf.LINK_GOTO for link in links),
                      "fonts": sorted({font[3] for font in page.get_fonts(full=True)}),
                      "png": image.relative_to(output).as_posix(), "png_sha256": digest(image)})
    document.close()
    text = "\n\f\n".join(texts)
    blocks = text_blocks(source)
    source_text = "\n".join(blocks["headers"] + blocks["body"] + blocks["footers"]) + "\n"
    (output / "source-text.txt").write_text(source_text, encoding="utf-8")
    (output / "pdf-text.txt").write_text(text, encoding="utf-8")
    source_tokens = unicodedata.normalize("NFC", source_text).split()
    pdf_tokens = unicodedata.normalize("NFC", text).split()
    matcher = difflib.SequenceMatcher(None, source_tokens, pdf_tokens, autojunk=False)
    changes = [{"kind": kind, "source_tokens": source_tokens[i:j], "pdf_tokens": pdf_tokens[k:l]}
               for kind, i, j, k, l in matcher.get_opcodes() if kind != "equal"]
    (output / "text-diff.json").write_text(json.dumps({"normalization": "NFC whitespace tokens; repeated headers and PAGE fields retained",
                                                       "changes": changes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"pdf_sha256": digest(pdf), "pages": pages, "page_count": len(pages),
            "pdf_text_chars": len(text), "source_words": len(source_tokens), "pdf_words": len(pdf_tokens),
            "token_sequence_ratio": round(matcher.ratio(), 6), "text_diff_groups": len(changes),
            "external_links": sorted(set(uris)), "oracle_checks": compare_oracle(text, oracle, uris),
            "visual_review": "PENDING", "wordcraft_roundtrip": "NOT_RUN"}


def resumable_report(output: Path, inputs: Path, variants: list, source_digests: dict, receipt: Path,
                     roundtrip_provenance: dict) -> dict:
    if not (output / ".synthetic-qa-only").is_file():
        raise ValueError("Resume requires an existing marked synthetic QA output")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    if (report.get("schema") != "gc-wordcraft-libreoffice-qa/v1" or report.get("synthetic_only") is not True
            or report.get("inputs_manifest_sha256") != digest(inputs / "full-manifest.json")
            or report.get("runtime_receipt_sha256") != digest(receipt)
            or report.get("roundtrip_comparison_sha256") != roundtrip_provenance.get("roundtrip_comparison_sha256")):
        raise ValueError("Resume provenance differs from the admitted original execution")
    completed = report.get("cases", [])
    if len(completed) > len(variants) or [case["source"] for case in completed] != [variant["docx"] for _, variant in variants[:len(completed)]]:
        raise ValueError("Resume cases are not an exact completed prefix")
    for case in completed:
        pdf = (output / case["pdf"]).resolve(strict=True)
        if (not pdf.is_relative_to(output) or digest(pdf) != case["pdf_sha256"]
                or source_digests.get(case["source"]) != case["source_sha256"]
                or len(case["pages"]) != case["page_count"]):
            raise ValueError("Resume cannot trust changed PDF/source evidence")
        for page in case["pages"]:
            png = (pdf.parent / page["png"]).resolve(strict=True)
            if not png.is_relative_to(output) or digest(png) != page["png_sha256"]:
                raise ValueError("Resume cannot trust changed rendered pages")
    return report


def run(inputs: Path, output: Path, receipt: Path | None, *, dpi: int = 120, timeout: int = 180,
        roundtrip_docx_root: Path | None = None, roundtrip_comparison_sha256: str | None = None,
        resume: bool = False, institutional_adapter: bool = False, system_soffice: Path | None = None) -> dict:
    if institutional_adapter and (resume or receipt or not system_soffice):
        raise ValueError("Linux institutional proof requires an explicit system binary and a new run without MSI receipt")
    if not institutional_adapter and (receipt is None or system_soffice is not None):
        raise ValueError("Windows proof requires the extracted MSI receipt")
    inputs = inputs.resolve(strict=True)
    if not inputs.is_relative_to(WORK_ROOT) or inputs.is_relative_to(ROOT):
        raise ValueError("Only workspace synthetic QA corpus inputs are allowed")
    manifest = verify_full_inputs(inputs)
    variants = [(case["id"], variant) for case in manifest["cases"] for variant in case["variants"]]
    if len(variants) != 16 or not 72 <= dpi <= 180 or not 10 <= timeout <= 600:
        raise ValueError("Invalid full-corpus QA bounds")
    output = confined_output(output, inputs, resume=resume)
    if bool(roundtrip_docx_root) != bool(roundtrip_comparison_sha256):
        raise ValueError("Native export root and pinned comparison digest must be provided together")
    sources = {variant["docx"]: inputs / variant["docx"] for _, variant in variants}
    roundtrip_provenance = {}
    if roundtrip_docx_root:
        sources, roundtrip_provenance = roundtrip_sources(inputs, manifest, roundtrip_docx_root, roundtrip_comparison_sha256)
        native_root = roundtrip_docx_root.resolve(strict=True)
        if output.is_relative_to(native_root) or native_root.is_relative_to(output):
            raise ValueError("LibreOffice output must be separate from native roundtrip evidence")
    admitted = {}
    source_digests = {}
    for _, variant in variants:
        data = sources[variant["docx"]].read_bytes()
        admitted[variant["docx"]] = admit_synthetic_docx(data)
        source_digests[variant["docx"]] = digest(sources[variant["docx"]])
    if institutional_adapter:
        soffice, provenance, profile_items = validate_system_runtime(system_soffice)
    else:
        soffice, provenance = validate_runtime(receipt)
    previous = resumable_report(output, inputs, variants, source_digests, receipt, roundtrip_provenance) if resume else None
    if previous and previous.get("dpi") != dpi:
        raise ValueError("Resume must preserve the original rendering DPI")
    if previous:
        version = previous["runtime_version"]
    else:
        output.mkdir(parents=True)
        (output / ".synthetic-qa-only").write_text("No production acceptance\n", encoding="utf-8")
        version_scratch = output / "_runtime"
        version_scratch.mkdir()
        version_profile = version_scratch / "profile"
        if institutional_adapter:
            env, wrapper = system_adapter_environment(soffice, version_scratch, profile_items)
            # Version mode does not start Writer; wrapper still gives it a
            # private profile and an outer group deadline.
            subprocess.run([str(wrapper), "--headless", "--version"], env=env,
                           capture_output=True, check=True, timeout=110)
            version = {"output": (version_scratch / "libreoffice.log").read_text(encoding="utf-8"),
                       "returncode": 0, "adapter": "DISTRIBUTION_RUNTIME_VERSION_ONLY"}
        else:
            make_profile(version_profile)
            version = run_owned([str(soffice), "-env:UserInstallation=" + version_profile.as_uri(),
                                 "-env:CrashDumpEnable=false",
                                 "-env:CrashDirectory=" + (version_profile.parent / "crash").as_uri(), "--headless", "--version"],
                                child_environment(soffice, version_scratch), 30)
    if (not institutional_adapter and "LibreOffice 26.8.1.1" not in version["output"]) or "LibreOffice " not in version["output"]:
        raise ValueError("Real runtime version differs from pinned MSI")
    runtime_fields = ({**provenance, "runtime_identity_sha256": json_digest({**provenance, "version": version["output"]})}
                      if institutional_adapter else
                      {"official_url": provenance["official_url"], "effective_url": provenance["effective_url"],
                       "msi_sha256": provenance["msi_sha256"], "runtime_receipt_sha256": digest(receipt)})
    report = {"schema": "gc-wordcraft-libreoffice-qa/v1", "synthetic_only": True,
              "scope": ("NATIVE_DOCX_TO_LIBREOFFICE_PDF_COMPARISON_VISUAL_PENDING" if roundtrip_provenance else
                        "PDF_BASELINE_ONLY_NOT_WORDCRAFT_ROUNDTRIP_OR_VISUAL_ACCEPTANCE"),
              "inputs_manifest_sha256": digest(inputs / "full-manifest.json"),
              **runtime_fields,
              "runtime_version": version, "pymupdf_version": __import__("pymupdf").__version__,
              "dpi": dpi, "cases": [], "conversion_input": "NATIVE_REEXPORTED_DOCX" if roundtrip_provenance else "ORIGINAL_DOCX",
              **roundtrip_provenance}
    if previous:
        report = previous
        report["verified_resume_count"] = report.get("verified_resume_count", 0) + 1
    report["status"] = "CONVERSION_IN_PROGRESS_VISUAL_REVIEW_PENDING"
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for case_id, variant in variants[len(report["cases"]):]:
        source = sources[variant["docx"]]
        case_output = output / case_id / variant["name"]
        case_output.mkdir(parents=True, exist_ok=resume)
        if (case_output / (source.stem + ".pdf")).exists():
            raise ValueError("Unrecorded PDF exists; inspect/adopt its backend evidence rather than overwrite")
        try:
            if institutional_adapter:
                invocation, attempts = convert_institutional_pdf(soffice, source, case_output, items=profile_items)
            else:
                invocation, attempts = convert_missing_pdf(soffice, source, case_output,
                                                          run_id=report.get("verified_resume_count", 0), timeout=timeout)
        except BaseException as error:
            report["status"] = "CONVERSION_FAILED_PARTIAL_PDFS_PRESERVED"
            report["failed_source"] = variant["docx"]
            report["error_type"] = type(error).__name__
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise
        if digest(source) != source_digests[variant["docx"]]:
            raise ValueError("QA conversion changed its admitted synthetic DOCX")
        oracle = json.loads((inputs / variant["oracle"]).read_text(encoding="utf-8"))
        evidence = pdf_evidence(case_output / (source.stem + ".pdf"), source.read_bytes(), oracle, case_output, dpi)
        if roundtrip_provenance:
            evidence["wordcraft_roundtrip"] = "PREVIOUS_NATIVE_EXECUTION_HASH_PINNED_VISUAL_PENDING"
        report["cases"].append({"id": case_id, "variant": variant["name"], "source": variant["docx"],
                                "source_sha256": digest(source), "original_source_sha256": variant["sha256_docx"],
                                "admitted_hyperlinks": admitted[variant["docx"]],
                                "pdf": (case_output / (source.stem + ".pdf")).relative_to(output).as_posix(),
                                "invocation": invocation, "conversion_attempts": attempts, **evidence})
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{case_id}/{variant['name']}: {evidence['page_count']} pages; {evidence['oracle_checks']['status']}", flush=True)
    verify_full_inputs(inputs)
    if digest(inputs / "full-manifest.json") != report["inputs_manifest_sha256"]:
        raise ValueError("Synthetic input manifest changed during conversion")
    if roundtrip_provenance:
        roundtrip_sources(inputs, manifest, roundtrip_docx_root, roundtrip_comparison_sha256)
    if institutional_adapter:
        _, final_provenance, _ = validate_system_runtime(system_soffice)
        if final_provenance != provenance:
            raise ValueError("Linux distribution runtime changed during this proof")
    report["input_bytes_unchanged"] = True
    report["completed_docx"] = len(report["cases"])
    report["total_pages"] = sum(case["page_count"] for case in report["cases"])
    report["status"] = "PDFS_RENDERED_VISUAL_REVIEW_PENDING"
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def refresh_metrics(inputs: Path, output: Path) -> dict:
    """Recheck immutable PDFs after a QA comparator change, without running LO.

    Preserve the initial report and validate all PDF/PNG/source hashes before
    writing updated text metrics. Never upgrades visual/WordCraft acceptance.
    """
    inputs, output = inputs.resolve(strict=True), output.resolve(strict=True)
    if (not output.is_relative_to(WORK_ROOT) or output.is_relative_to(ROOT)
            or output.is_relative_to(WORK_ROOT / "toolchain") or output.is_relative_to(inputs)
            or not (output / ".synthetic-qa-only").is_file()):
        raise ValueError("Metrics refresh escaped synthetic QA output")
    manifest = verify_full_inputs(inputs)
    report_path = output / "report.json"
    original = report_path.read_bytes()
    report = json.loads(original)
    if (report.get("schema") != "gc-wordcraft-libreoffice-qa/v1" or report.get("completed_docx") != 16
            or report.get("synthetic_only") is not True or len(report.get("cases", [])) != 16
            or digest(inputs / "full-manifest.json") != report["inputs_manifest_sha256"]):
        raise ValueError("Metrics refresh needs a completed original synthetic baseline")
    sources = {variant["docx"]: inputs / variant["docx"] for case in manifest["cases"] for variant in case["variants"]}
    if report.get("roundtrip_root"):
        sources, _ = roundtrip_sources(inputs, manifest, Path(report["roundtrip_root"]), report["roundtrip_comparison_sha256"])
    for case in report["cases"]:
        pdf, source = (output / case["pdf"]).resolve(strict=True), sources[case["source"]]
        if (not pdf.is_relative_to(output)
                or digest(pdf) != case["pdf_sha256"] or digest(source) != case["source_sha256"]):
            raise ValueError("PDF/source evidence changed before metrics refresh")
        for page in case["pages"]:
            png = (pdf.parent / page["png"]).resolve(strict=True)
            if not png.is_relative_to(output) or digest(png) != page["png_sha256"]:
                raise ValueError("Rendered page changed before metrics refresh")
    backup = output / "report-initial.json"
    with backup.open("xb") as stream:
        stream.write(original)
    for case in report["cases"]:
        source = sources[case["source"]]
        oracle = json.loads((inputs / case["source"]).with_suffix(".oracle.json").read_text(encoding="utf-8"))
        pdf = output / case["pdf"]
        case.update(pdf_evidence(pdf, source.read_bytes(), oracle, pdf.parent, report["dpi"], reuse_renders=True))
        if report.get("roundtrip_root"):
            case["wordcraft_roundtrip"] = "PREVIOUS_NATIVE_EXECUTION_HASH_PINNED_VISUAL_PENDING"
    report["initial_report_sha256"] = digest(backup)
    report["metrics_revision"] = "DECIMAL_UNIT_PRICE_LOCALIZATION_V2"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def compare_page_rasters(first: list[Path], second: list[Path], output: Path) -> dict:
    """Ordinal raster measurements; extra pages are explicit, never truncated."""
    from PIL import Image, ImageChops
    if not first or not second:
        raise ValueError("Raster comparison requires actual pages in both PDF paths")
    output.mkdir(parents=True)
    pages = []
    for index in range(max(len(first), len(second))):
        left = first[index] if index < len(first) else None
        right = second[index] if index < len(second) else None
        entry = {"page": index + 1,
                 "first": {"path": str(left), "sha256": digest(left)} if left else None,
                 "second": {"path": str(right), "sha256": digest(right)} if right else None}
        if left is None or right is None:
            entry["status"] = "PAGE_WITHOUT_ORDINAL_COUNTERPART"
        else:
            with Image.open(left) as one, Image.open(right) as two:
                entry["first_size_px"], entry["second_size_px"] = list(one.size), list(two.size)
                if one.size != two.size:
                    entry["status"] = "RASTER_DIMENSIONS_DIFFER"
                else:
                    diff = ImageChops.difference(one.convert("RGB"), two.convert("RGB"))
                    maximum = ImageChops.lighter(ImageChops.lighter(diff.getchannel(0), diff.getchannel(1)), diff.getchannel(2))
                    changed = sum(maximum.histogram()[1:])
                    entry["changed_pixel_fraction"] = round(changed / (diff.width * diff.height), 8)
                    entry["difference_bbox"] = diff.getbbox()
                    entry["status"] = "RASTER_PIXELS_IDENTICAL" if changed == 0 else "RASTER_DIFFERENCES_RECORDED"
                    if changed:
                        target = output / f"page-{index + 1:03d}-diff.png"
                        diff.save(target)
                        entry["difference_png"] = {"path": str(target), "sha256": digest(target)}
        pages.append(entry)
    return {"mapping_policy": "ORDINAL_PAGES_NO_CONTENT_REALIGNMENT", "first_page_count": len(first),
            "second_page_count": len(second), "visual_fidelity_approved": False,
            "status": ("RASTER_IDENTICAL_VISUAL_REVIEW_PENDING" if all(page["status"] == "RASTER_PIXELS_IDENTICAL" for page in pages)
                       else "RASTER_DIFFERENCES_RECORDED_VISUAL_REVIEW_REQUIRED"), "pages": pages}


def compare_three_way(inputs: Path, baseline: Path, reexported: Path, output: Path) -> dict:
    """Compare three actual PDF artifacts per source, without any conversion."""
    inputs = inputs.resolve(strict=True)
    manifest = verify_full_inputs(inputs)
    baseline, reexported = baseline.resolve(strict=True), reexported.resolve(strict=True)
    output = confined_output(output, inputs)
    reports = []
    for directory in (baseline, reexported):
        if (not directory.is_relative_to(WORK_ROOT) or directory.is_relative_to(ROOT)
                or not (directory / ".synthetic-qa-only").is_file()
                or output.is_relative_to(directory) or directory.is_relative_to(output)):
            raise ValueError("Three-way evidence escaped its separate synthetic QA namespace")
        report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        if (report.get("schema") != "gc-wordcraft-libreoffice-qa/v1" or report.get("synthetic_only") is not True
                or report.get("completed_docx") != 16
                or len(report.get("cases", [])) != 16 or report.get("input_bytes_unchanged") is not True
                or report.get("inputs_manifest_sha256") != digest(inputs / "full-manifest.json")):
            raise ValueError("Three-way comparison requires two complete immutable input runs")
        for case in report["cases"]:
            pdf = (directory / case["pdf"]).resolve(strict=True)
            if not pdf.is_relative_to(directory) or digest(pdf) != case["pdf_sha256"]:
                raise ValueError("Three-way PDF digest changed")
            if len(case["pages"]) != case["page_count"]:
                raise ValueError("A rendered PDF page is missing from the report")
            for page in case["pages"]:
                png = (pdf.parent / page["png"]).resolve(strict=True)
                if not png.is_relative_to(directory) or digest(png) != page["png_sha256"]:
                    raise ValueError("Three-way rendered page changed or is missing")
        reports.append(report)
    original, native_lo = reports
    if original.get("roundtrip_root") or native_lo.get("conversion_input") != "NATIVE_REEXPORTED_DOCX":
        raise ValueError("Three-way inputs must be original DOCX and native reexported DOCX runs")
    def runtime_identity(report):
        if report.get("runtime_source") == "UBUNTU_DISTRIBUTION_PACKAGES_NOT_WINDOWS_MSI":
            if not report.get("runtime_identity_sha256"):
                raise ValueError("Missing Linux runtime identity")
            return report["runtime_identity_sha256"]
        if not report.get("msi_sha256"):
            raise ValueError("Missing pinned Windows runtime identity")
        return report["msi_sha256"]
    if (runtime_identity(original) != runtime_identity(native_lo)
            or original["runtime_version"]["output"] != native_lo["runtime_version"]["output"]):
        raise ValueError("LibreOffice baselines must use the same pinned runtime version")
    if original.get("dpi") != native_lo.get("dpi") or not 72 <= original.get("dpi", 0) <= 180:
        raise ValueError("Three-way raster comparison requires the same admitted DPI")
    native_root = Path(native_lo["roundtrip_root"])
    if output.is_relative_to(native_root) or native_root.is_relative_to(output):
        raise ValueError("Three-way output must be separate from native execution evidence")
    _, provenance = roundtrip_sources(inputs, manifest, native_root, native_lo["roundtrip_comparison_sha256"])
    native_report = json.loads((native_root / "comparison.json").read_text(encoding="utf-8"))
    mappings = [{case["source"]: case for case in report["cases"]} for report in reports]
    native_cases = {case["source"]: case for case in native_report["cases"]}
    expected = {variant["docx"]: variant for case in manifest["cases"] for variant in case["variants"]}
    if any(len(mapping) != 16 or set(mapping) != set(expected) for mapping in mappings):
        raise ValueError("Three-way runs do not contain the same exact variants")

    import pymupdf

    def extracted(pdf):
        with pymupdf.open(pdf) as document:
            text = "\n".join(page.get_text(sort=True) for page in document)
            links = [link["uri"] for page in document for link in page.get_links() if link.get("uri")]
            dimensions = [[round(page.rect.width, 3), round(page.rect.height, 3)] for page in document]
            fonts = sorted({font[3] for page in document for font in page.get_fonts(full=True)})
            return len(document), text, links, dimensions, fonts

    result = {"schema": "gc-wordcraft-three-way-pdf/v1", "synthetic_only": True,
              "status": "COMPARISON_IN_PROGRESS_VISUAL_REVIEW_PENDING", "visual_fidelity_approved": False,
              "input_manifest_sha256": digest(inputs / "full-manifest.json"), **provenance,
              "original_lo_report_sha256": digest(baseline / "report.json"),
              "reexported_lo_report_sha256": digest(reexported / "report.json"), "dpi": original["dpi"], "cases": []}
    output.mkdir(parents=True)
    (output / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, variant in expected.items():
        first, second, native = mappings[0][name], mappings[1][name], native_cases[name]
        if first["source_sha256"] != variant["sha256_docx"] or second["source_sha256"] != native["docx_sha256"]:
            raise ValueError("Three-way source hashes do not correlate with native backend output")
        paths = [baseline / first["pdf"], reexported / second["pdf"],
                 native_root / native["case"] / Path(name).stem / "roundtrip.pdf"]
        values = [extracted(path) for path in paths]
        oracle = json.loads((inputs / variant["oracle"]).read_text(encoding="utf-8"))
        case_output = output / native["case"] / Path(name).stem
        native_output = case_output / "wordcraft-pdf"
        native_output.mkdir(parents=True)
        native_docx = paths[2].with_name("roundtrip.docx")
        native_evidence = pdf_evidence(paths[2], native_docx.read_bytes(), oracle, native_output, original["dpi"])
        native_evidence["wordcraft_roundtrip"] = "PREVIOUS_NATIVE_EXECUTION_HASH_PINNED_VISUAL_PENDING"
        rendered = [[baseline / Path(first["pdf"]).parent / page["png"] for page in first["pages"]],
                    [reexported / Path(second["pdf"]).parent / page["png"] for page in second["pages"]],
                    [native_output / page["png"] for page in native_evidence["pages"]]]
        raster = {label: compare_page_rasters(rendered[left], rendered[right], case_output / label)
                  for label, left, right in (("original-vs-reexported", 0, 1), ("original-vs-wordcraft", 0, 2),
                                            ("reexported-vs-wordcraft", 1, 2))}
        result["cases"].append({"source": name, "original_lo_pages": values[0][0],
                                "reexported_lo_pages": values[1][0], "wordcraft_pdf_pages": values[2][0],
                                "original_vs_reexported_compact_text_equal": compact(values[0][1]) == compact(values[1][1]),
                                "original_vs_reexported_token_ratio": round(difflib.SequenceMatcher(None, values[0][1].split(), values[1][1].split(), autojunk=False).ratio(), 6),
                                "original_lo_oracle": compare_oracle(values[0][1], oracle, values[0][2]),
                                "reexported_lo_oracle": compare_oracle(values[1][1], oracle, values[1][2]),
                                "wordcraft_pdf_oracle": compare_oracle(values[2][1], oracle, values[2][2]),
                                "page_sizes_pt": {key: value[3] for key, value in zip(("original_lo", "reexported_lo", "wordcraft_pdf"), values)},
                                "fonts": {key: value[4] for key, value in zip(("original_lo", "reexported_lo", "wordcraft_pdf"), values)},
                                "artifacts": [{"path": str(path), "sha256": digest(path)} for path in paths],
                                "raster_comparisons": raster, "wordcraft_pdf_rendered_evidence": native_evidence,
                                "visual_review": "PENDING"})
        (output / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["status"] = "THREE_REAL_PDF_PATHS_COMPARED_VISUAL_REVIEW_PENDING"
    result["completed_sources"] = len(result["cases"])
    result["cases_with_raster_differences"] = sum(any(value["status"] != "RASTER_IDENTICAL_VISUAL_REVIEW_PENDING"
                                                    for value in case["raster_comparisons"].values()) for case in result["cases"])
    result["cases_with_text_oracle_issues"] = sum(any(case[key]["status"] == "ISSUES_RECORDED"
                                                    for key in ("original_lo_oracle", "reexported_lo_oracle", "wordcraft_pdf_oracle"))
                                                for case in result["cases"])
    result["native_rendered_pages"] = sum(case["wordcraft_pdf_rendered_evidence"]["page_count"] for case in result["cases"])
    (output / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = ["| Fonte sintética | LO do original | LO do DOCX nativo | PDF WordCraft | Texto compacto entre LO | Raster entre LO |",
            "| --- | ---: | ---: | ---: | --- | --- |"]
    rows.extend(f"| {case['source']} | {case['original_lo_pages']} | {case['reexported_lo_pages']} | {case['wordcraft_pdf_pages']} | {case['original_vs_reexported_compact_text_equal']} | {case['raster_comparisons']['original-vs-reexported']['status']} |" for case in result["cases"])
    (output / "comparison.md").write_text("# Comparação dos três caminhos PDF\n\nMétricas de artefatos reais; inspeção visual permanece pendente. Contagem de páginas isolada não define perda.\n\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--runtime-receipt", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--refresh-metrics", action="store_true", help="Recheck existing PDF hashes/text; never reconvert")
    mode.add_argument("--compare-three-way", action="store_true")
    mode.add_argument("--institutional-adapter", action="store_true", help="Linux CI only: use src.export._docx_em_pdf without fallback")
    parser.add_argument("--system-soffice", type=Path)
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--reexported-pdf-root", type=Path)
    parser.add_argument("--roundtrip-docx-root", type=Path)
    parser.add_argument("--roundtrip-comparison-sha256")
    parser.add_argument("--resume", action="store_true", help="Verify complete prefix by hashes and convert only missing cases")
    parser.add_argument("--dpi", default=120, type=int)
    args = parser.parse_args()
    if args.compare_three_way:
        if not args.baseline_root or not args.reexported_pdf_root:
            parser.error("--compare-three-way requires both PDF run roots")
        report = compare_three_way(args.inputs, args.baseline_root, args.reexported_pdf_root, args.out)
    elif args.refresh_metrics:
        report = refresh_metrics(args.inputs, args.out)
    else:
        if not args.runtime_receipt and not args.institutional_adapter:
            parser.error("Conversion requires --runtime-receipt or --institutional-adapter")
        report = run(args.inputs, args.out, args.runtime_receipt, dpi=args.dpi,
                     roundtrip_docx_root=args.roundtrip_docx_root, roundtrip_comparison_sha256=args.roundtrip_comparison_sha256,
                     resume=args.resume, institutional_adapter=args.institutional_adapter, system_soffice=args.system_soffice)
    print(json.dumps({"completed_cases": len(report["cases"]), "total_pages": report.get("total_pages"), "status": report["status"]}))
