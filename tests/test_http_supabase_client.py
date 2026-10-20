import pytest

from scripts.http_supabase_client import Client, HttpError


def test_client_is_loopback_only_and_builds_closed_table_and_rpc_queries(monkeypatch):
    client = Client("http://127.0.0.1:55441", "synthetic-jwt")
    calls = []
    monkeypatch.setattr(client, "_request", lambda *args: calls.append(args) or [])
    assert client.table("documentos_editor").select("id").eq("id", "x").limit(1).execute().data == []
    assert calls[-1][:4] == ("GET", "/rest/v1/documentos_editor",
        [("select", "id"), ("id", "eq.x"), ("limit", "1")], None)
    client.rpc("documento_editor_emitir", {"p_process": "x"}).execute()
    assert calls[-1][:4] == ("POST", "/rest/v1/rpc/documento_editor_emitir", [], {"p_process": "x"})
    assert client.storage.list_buckets() == []


@pytest.mark.parametrize("url", ["https://127.0.0.1", "http://example.invalid",
    "http://user:password@localhost", "http://127.0.0.1/rest/v1", "http://127.0.0.1?x=1"])
def test_client_refuses_non_loopback_or_ambiguous_roots(url):
    with pytest.raises(ValueError):
        Client(url, "synthetic")


def test_http_error_preserves_postgres_code_without_request_secret():
    error = HttpError(401, b'{"code":"42501","message":"permission denied"}')
    assert error.code == "42501" and error.details["message"] == "permission denied"
    assert "synthetic-jwt" not in str(error)
