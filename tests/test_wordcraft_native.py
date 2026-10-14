from pathlib import Path
import subprocess
from types import SimpleNamespace

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
