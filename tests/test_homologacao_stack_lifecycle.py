"""Startup ownership contracts; no process, socket probe or database is real."""
import signal
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import homologacao_stack as stack


class FilhoSimulado:
    def __init__(self):
        self.returncode = None
        self.signals = []
        self.waits = []
        self.killed = False

    def poll(self):
        return self.returncode

    def send_signal(self, value):
        self.signals.append(value)

    def wait(self, timeout=None):
        self.waits.append(timeout)
        self.returncode = 0
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -1


@pytest.fixture
def startup(monkeypatch):
    spawned = []
    ready = []
    monkeypatch.setattr(stack, "BINARIO_PGRST", sys.executable)
    monkeypatch.setattr(stack, "_porta_livre", lambda port: True)

    def popen(*args, **kwargs):
        child = FilhoSimulado()
        spawned.append(child)
        return child

    def wait_for_port(port, *, processo):
        ready.append((port, processo))

    monkeypatch.setattr(stack.subprocess, "Popen", popen)
    monkeypatch.setattr(stack, "_esperar_porta", wait_for_port)
    return spawned, ready


def subir(kind):
    if kind == "postgrest":
        return stack.subir_postgrest("dbname=synthetic-only host=127.0.0.1", "synthetic-only-secret")
    return stack.subir_adaptador()


@pytest.mark.parametrize("kind", ["postgrest", "adaptador"])
@pytest.mark.parametrize("failure_type", [stack.ErroPilha, KeyboardInterrupt, SystemExit])
def test_startup_failure_terminates_its_own_child_before_propagating(startup, monkeypatch, kind, failure_type):
    spawned, ready = startup
    failure = failure_type("synthetic startup failure")

    def fail_wait(port, *, processo):
        ready.append((port, processo))
        raise failure

    monkeypatch.setattr(stack, "_esperar_porta", fail_wait)
    with pytest.raises(failure_type) as caught:
        subir(kind)
    assert caught.value is failure
    assert len(spawned) == 1
    child = spawned[0]
    assert ready == [(stack.PORTA_PGRST if kind == "postgrest" else stack.PORTA_ADAPTADOR, child)]
    # Exercise the real _encerrar path against the simulated child.
    assert child.signals == [signal.SIGTERM]
    assert child.waits == [10]
    assert child.poll() == 0
    assert not child.killed


@pytest.mark.parametrize("kind", ["postgrest", "adaptador"])
def test_success_returns_the_live_child_to_its_caller(startup, kind):
    spawned, ready = startup
    child = subir(kind)
    assert spawned == [child]
    assert ready == [(stack.PORTA_PGRST if kind == "postgrest" else stack.PORTA_ADAPTADOR, child)]
    assert child.poll() is None
    assert child.signals == child.waits == []
    assert not child.killed


def test_missing_postgrest_binary_is_rejected_before_popen(startup, monkeypatch, tmp_path):
    spawned, ready = startup
    monkeypatch.setattr(stack, "BINARIO_PGRST", str(tmp_path / "missing-postgrest-binary"))
    with pytest.raises(stack.ErroPilha, match="postgrest não encontrado"):
        subir("postgrest")
    assert spawned == ready == []


@pytest.mark.parametrize("kind", ["postgrest", "adaptador"])
def test_occupied_port_does_not_start_or_terminate_any_child(startup, monkeypatch, kind):
    spawned, ready = startup
    monkeypatch.setattr(stack, "_porta_livre", lambda port: False)
    with pytest.raises(stack.ErroPilha, match="ocupada"):
        subir(kind)
    assert spawned == ready == []
