from pathlib import Path
import io
import json
import struct
import subprocess
from types import SimpleNamespace
from zipfile import ZipFile, ZIP_BZIP2, ZIP_DEFLATED

import pytest

from src import wordcraft_native as native

CONTENT = b"synthetic private-looking model bytes; never logged"


@pytest.fixture
def runtime(tmp_path):
    node = tmp_path / "node"
    node.write_bytes(b"unit test placeholder, not an executable")
    return dict(node=node, bundle=tmp_path, manifest_sha256="a" * 64)


def test_ipc_so_aceita_confirmacao_fechada_e_nao_herda_segredos(runtime, monkeypatch):
    seen = {}
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "synthetic sentinel")
    monkeypatch.setenv("NODE_OPTIONS", "synthetic forbidden preload")
    def fake(args, **kwargs):
        seen.update(args=args, **kwargs)
        return SimpleNamespace(returncode=0, stdout=b'{"valid":true}', stderr=CONTENT)
    monkeypatch.setattr(native.subprocess, "run", fake)
    native.validar(CONTENT, **runtime)
    assert seen["input"] == CONTENT
    assert all(CONTENT.decode() not in arg for arg in seen["args"])
    assert set(seen["env"]) <= {"SystemRoot", "WINDIR", "TEMP", "TMP"}
    assert seen["timeout"] == 30


@pytest.mark.parametrize("code,reply", [(0, b'{"valid":1}'), (0, b'{"valid":true,"extra":1}'),
    (0, b'{"valid":false}'), (3, b'{"valid":true}'), (0, b'not JSON'),
    (2, b'{"valid":0,"code":"MODEL_REJECTED"}'), (0, b'{"valid":false,"valid":true}')])
def test_resposta_ambigua_nunca_aprova_modelo(runtime, monkeypatch, code, reply):
    monkeypatch.setattr(native.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=code, stdout=reply, stderr=CONTENT))
    with pytest.raises(native.MotorIndisponivel) as error:
        native.validar(CONTENT, **runtime)
    assert CONTENT.decode() not in str(error.value)


def test_rejeicao_nativa_e_timeout_falham_sem_logar_payload(runtime, monkeypatch):
    monkeypatch.setattr(native.subprocess, "run", lambda *a, **k:
        SimpleNamespace(returncode=2, stdout=b'{"valid":false,"code":"MODEL_REJECTED"}', stderr=CONTENT))
    with pytest.raises(native.ModeloRecusado):
        native.validar(CONTENT, **runtime)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("synthetic", 30, output=CONTENT)
    monkeypatch.setattr(native.subprocess, "run", timeout)
    with pytest.raises(native.MotorIndisponivel) as error:
        native.validar(CONTENT, **runtime)
    assert CONTENT.decode() not in str(error.value)


def test_bytes_excessivos_e_runtime_ausente_nao_executam_processo(runtime, monkeypatch):
    monkeypatch.setattr(native.subprocess, "run", lambda *a, **k: pytest.fail("must reject before spawn"))
    with pytest.raises(native.ModeloRecusado):
        native.validar(b"", **runtime)
    with pytest.raises(native.ModeloRecusado):
        native.validar(b"x" * (native.MAX_BYTES + 1), **runtime)
    with pytest.raises(native.MotorIndisponivel):
        native.validar(CONTENT, **{**runtime, "node": Path("relative-node")})


@pytest.mark.parametrize("formato,data", [("docx", b"PK\x03\x04synthetic"), ("pdf", b"%PDF-synthetic")])
def test_export_ipc_is_binary_bounded_and_typed(runtime, monkeypatch, formato, data):
    seen = {}
    def fake(args, **kwargs):
        seen.update(args=args, **kwargs)
        return SimpleNamespace(returncode=0, stdout=data, stderr=CONTENT)
    monkeypatch.setattr(native.subprocess, "run", fake)
    assert native.exportar(CONTENT, formato=formato, **runtime) == data
    assert seen["args"][-2:] == ["--export-format", formato]
    assert seen["input"] == CONTENT
    assert set(seen["env"]) <= {"SystemRoot", "WINDIR", "TEMP", "TMP"}


@pytest.mark.parametrize("code,data", [(0, b""), (0, b'{"valid":true}'),
                                      (0, b"PK\x03\x04not a PDF"), (3, b"%PDF-not success")])
def test_ambiguous_export_never_returns_an_artifact(runtime, monkeypatch, code, data):
    monkeypatch.setattr(native.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=code, stdout=data, stderr=CONTENT))
    with pytest.raises(native.MotorIndisponivel):
        native.exportar(CONTENT, formato="pdf", **runtime)


def test_unapproved_export_does_not_start_a_process(runtime, monkeypatch):
    monkeypatch.setattr(native.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not execute"))
    with pytest.raises(native.ModeloRecusado):
        native.exportar(CONTENT, formato="html", **runtime)


def docx_bytes(*, overrides=None, extra=(), compression=ZIP_DEFLATED):
    parts = {
        "[Content_Types].xml": b'''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
          <Default Extension="xml" ContentType="application/xml"/>
          <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
          <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
          </Types>''',
        "_rels/.rels": b'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
          <Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
          </Relationships>''',
        "word/document.xml": b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Synthetic</w:t></w:r></w:p></w:body></w:document>''',
    }
    parts.update(overrides or {})
    output = io.BytesIO()
    with ZipFile(output, "w", compression=compression) as archive:
        for name, data in [*parts.items(), *extra]:
            archive.writestr(name, data)
    return output.getvalue()


@pytest.mark.parametrize("name", ["01-texto-listas-links.docx", "02-tabela-210-itens.docx", "03-timbrado-assinaturas.docx"])
def test_docx_preflight_accepts_existing_synthetic_corpus(name):
    native.preflight_docx((Path(__file__).parent / "fixtures/wordcraft" / name).read_bytes())


@pytest.mark.parametrize("name", ["../outside.xml", "/word/document.xml", "word/../outside.xml",
    "word/vbaProject.bin", "word/embeddings/oleObject1.bin",
    "word/activeX/activeX1.xml", "word/afchunk1.html", "unexpected.xml", "word/fonts/private.odttf"])
def test_docx_unsupported_paths_or_parts_reject_before_wasm(runtime, monkeypatch, name):
    monkeypatch.setattr(native.subprocess, "run", lambda *a, **k: pytest.fail("must reject before spawn"))
    with pytest.raises(native.ModeloRecusado):
        native.importar_docx(docx_bytes(extra=[(name, b"synthetic")]), **runtime)


@pytest.mark.parametrize("data", [b"", b"plain text", b"{}", b"PK\x03\x04invalid ZIP", b"%PDF-document"])
def test_import_admission_requires_actual_bounded_docx_before_spawn(runtime, monkeypatch, data):
    monkeypatch.setattr(native.subprocess, "run", lambda *a, **k: pytest.fail("must reject before spawn"))
    with pytest.raises(native.ModeloRecusado):
        native.importar_docx(data, **runtime)


def test_docx_encryption_duplicate_parts_compression_and_symlinks_are_rejected():
    data = bytearray(docx_bytes())
    for signature, offset in [(b"PK\x03\x04", 6), (b"PK\x01\x02", 8)]:
        at = data.find(signature)
        flags = struct.unpack_from("<H", data, at + offset)[0]
        struct.pack_into("<H", data, at + offset, flags | 1)
    with pytest.raises(native.ModeloRecusado):
        native.preflight_docx(bytes(data))


def test_raw_zip_backslash_name_is_not_normalized_into_a_different_part():
    data = docx_bytes().replace(b"word/document.xml", b"word\\document.xml")
    with pytest.raises(native.ModeloRecusado):
        native.preflight_docx(data)
    with pytest.warns(UserWarning, match="Duplicate name"):
        duplicate = docx_bytes(extra=[("word/document.xml", b"duplicate")])
    with pytest.raises(native.ModeloRecusado):
        native.preflight_docx(duplicate)
    with pytest.raises(native.ModeloRecusado):
        native.preflight_docx(docx_bytes(compression=ZIP_BZIP2))
    data = bytearray(docx_bytes())
    central = data.find(b"PK\x01\x02")
    struct.pack_into("<I", data, central + 38, 0o120777 << 16)
    with pytest.raises(native.ModeloRecusado):
        native.preflight_docx(bytes(data))


@pytest.mark.parametrize("limit,value", [("MAX_DOCX_PARTS", 2), ("MAX_DOCX_PART_BYTES", 100),
                                       ("MAX_DOCX_EXPANDED_BYTES", 500)])
def test_docx_zip_limits_reject_before_spawn(runtime, monkeypatch, limit, value):
    data = docx_bytes()
    monkeypatch.setattr(native, limit, value)
    monkeypatch.setattr(native.subprocess, "run", lambda *a, **k: pytest.fail("must reject before spawn"))
    with pytest.raises(native.ModeloRecusado):
        native.importar_docx(data, **runtime)


@pytest.mark.parametrize("xml", [b"<!DOCTYPE document [<!ENTITY x 'value'>]><document>&x;</document>",
    "<!DOCTYPE document [<!ENTITY x 'value'>]><document>&x;</document>".encode("utf-16"),
    b"<unclosed", b"<document/>",
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:altChunk/></w:document>',
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:instrText>DDEAUTO cmd </w:instrText></w:document>'])
def test_unsafe_or_invalid_xml_never_reaches_engine(runtime, monkeypatch, xml):
    monkeypatch.setattr(native.subprocess, "run", lambda *a, **k: pytest.fail("must reject before spawn"))
    with pytest.raises(native.ModeloRecusado):
        native.importar_docx(docx_bytes(overrides={"word/document.xml": xml}), **runtime)


@pytest.mark.parametrize("kind,target,mode", [("image", "https://example.invalid/image.png", "External"),
    ("hyperlink", "file:///private/file", "External"), ("hyperlink", "javascript:alert(1)", "External"),
    ("hyperlink", "https://user:pass@example.invalid/private", "External"),
    ("attachedTemplate", "https://example.invalid/template.dotx", "External"),
    ("styles", "../../outside.xml", "Internal"), ("styles", "missing.xml", "Internal"),
    ("hyperlink", "https://example.invalid", "Unexpected")])
def test_relationships_cannot_load_files_network_or_missing_parts(runtime, monkeypatch, kind, target, mode):
    root = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="r1" Type="{native._REL_BASE}{kind}" Target="{target}" TargetMode="{mode}"/>'
            '</Relationships>').encode()
    monkeypatch.setattr(native.subprocess, "run", lambda *a, **k: pytest.fail("must reject before spawn"))
    with pytest.raises(native.ModeloRecusado):
        native.importar_docx(docx_bytes(extra=[("word/_rels/document.xml.rels", root)]), **runtime)


def test_docx_wrong_content_type_is_not_an_importable_document():
    with ZipFile(io.BytesIO(docx_bytes())) as archive:
        types = archive.read("[Content_Types].xml")
    for changed in [types.replace(b"document.main+xml", b"macroEnabled.main+xml"),
                    types.replace(b"/word/document.xml", b"/missing.xml")]:
        with pytest.raises(native.ModeloRecusado):
            native.preflight_docx(docx_bytes(overrides={"[Content_Types].xml": changed}))


def test_docx_corrupt_data_is_rejected_instead_of_silently_dropped():
    data = bytearray(docx_bytes())
    filename_len, extra_len = struct.unpack_from("<HH", data, 26)
    data[30 + filename_len + extra_len] ^= 0xff
    with pytest.raises(native.ModeloRecusado):
        native.preflight_docx(bytes(data))


def test_forged_small_expanded_size_cannot_hide_a_deflate_bomb(runtime, monkeypatch):
    data = bytearray(docx_bytes())
    with ZipFile(io.BytesIO(data)) as archive:
        part = archive.getinfo("word/document.xml")
    # Make central/local metadata and prefix CRC agree while the deflate stream
    # still expands to the original full XML. Admission must inspect actual EOF.
    central = data.find(b"PK\x01\x02")
    while data[central + 46:central + 46 + len(part.filename)] != part.filename.encode():
        central = data.find(b"PK\x01\x02", central + 4)
        assert central != -1
    import zlib
    crc = zlib.crc32(b"<")
    struct.pack_into("<I", data, part.header_offset + 14, crc)
    struct.pack_into("<I", data, part.header_offset + 22, 1)
    struct.pack_into("<I", data, central + 16, crc)
    struct.pack_into("<I", data, central + 24, 1)
    monkeypatch.setattr(native.subprocess, "run", lambda *a, **k: pytest.fail("must reject before spawn"))
    with pytest.raises(native.ModeloRecusado):
        native.importar_docx(bytes(data), **runtime)


def test_split_dde_instructions_and_excessive_xml_depth_are_rejected():
    for xml in [
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:instrText>DD</w:instrText><w:instrText>EAUTO cmd</w:instrText></w:document>',
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        + '<w:p>' * 66 + '</w:p>' * 66 + '</w:document>',
    ]:
        with pytest.raises(native.ModeloRecusado):
            native.preflight_docx(docx_bytes(overrides={"word/document.xml": xml.encode()}))


CHECKPOINT = json.dumps({"schema": "gc-wordcraft-snapshot/v1", "document": {"body": []},
                         "media": {}, "passthrough": {}}).encode()


def test_import_uses_typed_binary_ipc_without_filename_or_inherited_secrets(runtime, monkeypatch):
    seen = {}
    data = docx_bytes()
    def fake(args, **kwargs):
        seen.update(args=args, **kwargs)
        return SimpleNamespace(returncode=0, stdout=CHECKPOINT, stderr=CONTENT)
    monkeypatch.setattr(native.subprocess, "run", fake)
    assert native.importar_docx(data, **runtime) == CHECKPOINT
    assert seen["args"][-2:] == ["--import-format", "docx"]
    assert seen["input"] == data
    assert set(seen["env"]) <= {"SystemRoot", "WINDIR", "TEMP", "TMP"}


@pytest.mark.parametrize("code,response", [(0, b""), (0, b'{}'), (0, b'{"valid":true}'),
    (0, CHECKPOINT.replace(b"snapshot/v1", b"snapshot/v2")), (0, b"not JSON"), (3, CHECKPOINT),
    (0, CHECKPOINT.replace(b'"media": {}', b'"media": {}, "media": {}'))])
def test_import_never_returns_ambiguous_checkpoint(runtime, monkeypatch, code, response):
    monkeypatch.setattr(native.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=code, stdout=response, stderr=CONTENT))
    with pytest.raises(native.MotorIndisponivel):
        native.importar_docx(docx_bytes(), **runtime)
