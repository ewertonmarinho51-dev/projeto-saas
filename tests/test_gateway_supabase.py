"""Real loopback forwarding against a test stub; this is not a GoTrue proof."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import threading

import pytest

from scripts import gateway_supabase as gateway


@contextmanager
def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


class Stub(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.calls.append((self.path, self.headers.get("Authorization"), body))
        response = b'{"stub":true}'
        self.send_response(403)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def request(port, path, body=b"{}"):
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        client.request("POST", path, body=body, headers={"Authorization": "Bearer synthetic-unit-only"})
        response = client.getresponse()
        return response.status, response.read()
    finally:
        client.close()


@pytest.mark.parametrize("value", ["https://127.0.0.1:80", "http://outside.invalid:80", "http://localhost:80",
    "http://127.0.0.1", "http://user:pass" + "@" + "127.0.0.1:80", "http://127.0.0.1:80/path",
    "http://127.0.0.1:80/?query=private", "http://127.0.0.1:80/#fragment", "http://127.0.0.1:99999"])
def test_only_explicit_loopback_origin_is_accepted(value):
    with pytest.raises(ValueError):
        gateway.destino_loopback(value)


def test_loopback_normalization():
    assert gateway.destino_loopback("http://127.0.0.1:54321/") == "http://127.0.0.1:54321"
    assert gateway.destino_loopback("http://[::1]:54321") == "http://[::1]:54321"


def test_auth_default_remains_explicit_501_without_contacting_upstream(monkeypatch, capsys):
    monkeypatch.setattr(gateway, "DESTINO_AUTH", None)
    with serve(gateway.Adaptador) as port:
        status, body = request(port, "/auth/v1/token?grant_type=password", b'{"password":"synthetic-private"}')
    assert status == 501 and b"GoTrue ausente" in body
    assert "private" not in capsys.readouterr().err


@pytest.mark.parametrize("prefix", ["/auth/v1", "/rest/v1"])
def test_optional_auth_and_existing_rest_forward_body_query_headers_and_error_status(monkeypatch, prefix):
    Stub.calls = []
    with serve(Stub) as upstream:
        monkeypatch.setattr(gateway, "DESTINO", f"http://127.0.0.1:{upstream}")
        monkeypatch.setattr(gateway, "DESTINO_AUTH", f"http://127.0.0.1:{upstream}")
        with serve(gateway.Adaptador) as port:
            status, body = request(port, prefix + "/token?grant_type=password", b'{"synthetic":"request"}')
    assert status == 403 and body == b'{"stub":true}'
    assert Stub.calls == [("/token?grant_type=password", "Bearer synthetic-unit-only", b'{"synthetic":"request"}')]


def test_oversized_body_is_refused_before_upstream(monkeypatch):
    Stub.calls = []
    monkeypatch.setattr(gateway, "MAX_BODY", 4)
    with serve(Stub) as upstream:
        monkeypatch.setattr(gateway, "DESTINO", f"http://127.0.0.1:{upstream}")
        with serve(gateway.Adaptador) as port:
            status, _ = request(port, "/rest/v1/rpc/test", b"excessive")
    assert status == 413 and not Stub.calls
