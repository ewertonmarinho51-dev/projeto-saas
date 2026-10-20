"""Offline QA extraction of one pinned official MSI; never installs a product.

Only read-only MSI database APIs, embedded CAB expansion and confined copies are
used. This fallback does not start Windows Installer or execute MSI actions.
"""
from __future__ import annotations

import argparse
import ctypes
from functools import cache
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = ROOT.parent
SHA256 = "c6298b10cfa1748bcbedad94c62ce771e240e5021bfd6d7a967cd571b04b5312"
MSI_NAME = "LibreOffice_26.8.1_Win_x86-64.msi"
OFFICIAL = "https://download.documentfoundation.org/libreoffice/stable/26.8.1/win/x86_64/" + MSI_NAME
MIRROR = "https://tdf.c3sl.ufpr.br/libreoffice/stable/26.8.1/win/x86_64/" + MSI_NAME


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def confined(path: Path) -> Path:
    result = path.resolve()
    allowed = (WORK_ROOT / "toolchain").resolve()
    if (not allowed.is_relative_to(WORK_ROOT.resolve())
            or result == allowed or not result.is_relative_to(allowed)):
        raise ValueError("QA toolchain path escaped work/toolchain")
    return result


def target_name(value: str) -> str:
    """MSI target:source and short|long filename syntax; no host directories."""
    name = value.split(":", 1)[0].rsplit("|", 1)[-1]
    if name == ".":
        return ""
    if not name or name in {".."} or any(char in name for char in "/\\:\x00"):
        raise ValueError("Unsafe MSI target filename")
    return name


def _stream(msi: Path, name: str, output: Path) -> None:
    """Documented MsiRecordReadStream, without invoking the installation engine."""
    api = ctypes.WinDLL("msi")
    uint = ctypes.c_uint
    api.MsiOpenDatabaseW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(uint)]
    api.MsiDatabaseOpenViewW.argtypes = [uint, ctypes.c_wchar_p, ctypes.POINTER(uint)]
    api.MsiViewExecute.argtypes = [uint, uint]
    api.MsiViewFetch.argtypes = [uint, ctypes.POINTER(uint)]
    api.MsiRecordReadStream.argtypes = [uint, uint, ctypes.c_void_p, ctypes.POINTER(uint)]
    api.MsiCloseHandle.argtypes = [uint]
    database, view, record = uint(), uint(), uint()

    def check(code: int) -> None:
        if code:
            raise OSError(code, "Read-only MSI stream API failed")

    try:
        check(api.MsiOpenDatabaseW(str(msi), None, ctypes.byref(database)))
        if not name.replace("_", "").replace(".", "").isalnum():
            raise ValueError("Unexpected cabinet name")
        check(api.MsiDatabaseOpenViewW(database, "SELECT `Data` FROM `_Streams` WHERE `Name`='" + name + "'", ctypes.byref(view)))
        check(api.MsiViewExecute(view, 0))
        check(api.MsiViewFetch(view, ctypes.byref(record)))
        buffer = ctypes.create_string_buffer(1024 * 1024)
        with output.open("xb") as stream:
            while True:
                count = uint(len(buffer))
                check(api.MsiRecordReadStream(record, 1, buffer, ctypes.byref(count)))
                if not count.value:
                    break
                stream.write(buffer.raw[:count.value])
    finally:
        for handle in (record, view, database):
            if handle.value:
                api.MsiCloseHandle(handle)


def extract(msi: Path, image: Path) -> dict:
    if os.name != "nt":
        raise RuntimeError("Pinned Windows MSI extraction requires Windows")
    import _msi

    msi, image = confined(msi), confined(image)
    if msi.name != MSI_NAME or digest(msi) != SHA256:
        raise ValueError("MSI does not match the official TDF SHA256")
    if image.exists():
        raise ValueError("Extraction output must be new; never overlay a runtime")
    if (image.parent / "extraction-receipt.json").exists():
        raise ValueError("Preserve the previous extraction receipt; use a new toolchain namespace")
    scratch = confined(image.with_name(image.name + "-cab"))
    if scratch.exists():
        raise ValueError("CAB scratch already exists; inspect it before retrying")
    database = _msi.OpenDatabase(str(msi), _msi.MSIDBOPEN_READONLY)

    def rows(table: str) -> list[list[str]]:
        view = database.OpenView("SELECT * FROM `" + table + "`")
        view.Execute(None)
        values = []
        while (record := view.Fetch()) is not None:
            values.append([record.GetString(i) for i in range(1, record.GetFieldCount() + 1)])
        view.Close()
        return values

    media, files = rows("Media"), rows("File")
    directories = {row[0]: row[1:] for row in rows("Directory")}
    components = {row[0]: row[2] for row in rows("Component")}
    if len(media) != 1 or not media[0][3].startswith("#") or len(files) != 19427:
        raise ValueError("Pinned MSI cabinet inventory differs")
    cabinet_name = media[0][3][1:]

    @cache
    def directory(key: str, ancestors: tuple = ()) -> Path:
        if key == "TARGETDIR":
            return image
        if key in ancestors or key not in directories:
            raise ValueError("Invalid MSI directory tree")
        parent, value = directories[key]
        result = directory(parent, (*ancestors, key)) / target_name(value)
        if not result.is_relative_to(image):
            raise ValueError("MSI directory escaped output")
        return result

    destinations = []
    seen = set()
    for row in files:
        key, component, filename, size = row[:4]
        if target_name(key) != key:
            raise ValueError("Unsafe CAB file key")
        destination_directory = directory(components[component])
        # The vendor MSI carries both AMD64 and ARM64 VC runtimes with the same
        # logical System64 filenames. Preserve both without evaluating install
        # conditions or overlaying one architecture over the other.
        if destination_directory == image / "System64":
            if "_amd64." in component:
                destination_directory /= "amd64"
            elif "_arm64." in component:
                destination_directory /= "arm64"
        destination = destination_directory / target_name(filename)
        normalized = str(destination).casefold()
        if normalized in seen:
            raise ValueError("Duplicate MSI destination")
        seen.add(normalized)
        destinations.append((key, destination, int(size)))
    scratch.mkdir(parents=True)
    print("MSI inventory validated: 19427 files; reading official embedded CAB", flush=True)
    cabinet = scratch / cabinet_name
    _stream(msi, cabinet_name, cabinet)
    print("CAB stream saved; expanding locally", flush=True)
    expanded = scratch / "expanded"
    expanded.mkdir()
    expand = Path(os.environ["SystemRoot"]) / "System32" / "expand.exe"
    with (scratch / "expand.log").open("wb") as log:
        subprocess.run([str(expand), str(cabinet), "-F:*", str(expanded)],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    actual = {path.name for path in expanded.iterdir() if path.is_file()}
    if actual != {row[0] for row in files} or any(path.is_dir() for path in expanded.iterdir()):
        raise ValueError("Expanded CAB inventory differs from MSI File table")
    image.mkdir()
    print("CAB inventory validated; rebuilding local image", flush=True)
    runtime_files = []
    for key, destination, size in destinations:
        source = expanded / key
        if source.stat().st_size != size:
            raise ValueError("Expanded CAB file size differs from MSI metadata")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        runtime_files.append({"path": destination.relative_to(image).as_posix(),
                              "bytes": size, "sha256": digest(destination)})
    soffice = image / "LibreOffice" / "program" / "soffice.com"
    receipt = {"schema": "gc-wordcraft-lo-extraction/v1", "official_url": OFFICIAL,
               "effective_url": MIRROR, "published_sha256": SHA256,
               "msi": str(msi), "msi_sha256": digest(msi), "image": str(image),
               "method": "MSI_READONLY_STREAM_CAB_EXPAND_NO_INSTALL_ACTIONS",
               "soffice": str(soffice), "soffice_sha256": digest(soffice),
               "files": runtime_files}
    (image.parent / "extraction-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--msi", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path)
    args = parser.parse_args()
    receipt = extract(args.msi, args.image)
    print(json.dumps({key: value for key, value in receipt.items() if key != "files"}, indent=2))
