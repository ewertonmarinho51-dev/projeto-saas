"""Minimal loopback-only PostgREST client for the disposable HTTP rehearsal.

This is not an application SDK. It exists only so the security harness can
exercise the real gateway/PostgREST boundary when supabase-py is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Response:
    data: object


class HttpError(RuntimeError):
    def __init__(self, status: int, raw: bytes):
        self.status = status
        try:
            value = json.loads(raw)
        except Exception:
            value = {}
        self.code = value.get("code") if isinstance(value, dict) else None
        self.details = value if isinstance(value, dict) else None
        # Preserve the same structured evidence used by supabase-py without
        # ever adding the request headers/JWT to the exception.
        super().__init__(value if isinstance(value, dict) and value else {"status": status})


class Query:
    def __init__(self, client, path: str):
        self.client, self.path = client, path
        self.method, self.body, self.params = "GET", None, []
        self.headers = {}

    def select(self, columns="*"):
        self.method = "GET"
        self.params.append(("select", columns))
        return self

    def limit(self, value):
        self.params.append(("limit", str(value)))
        return self

    def eq(self, key, value):
        self.params.append((key, "eq." + str(value)))
        return self

    def neq(self, key, value):
        self.params.append((key, "neq." + str(value)))
        return self

    def insert(self, value):
        self.method, self.body = "POST", value
        self.headers["Prefer"] = "return=representation"
        return self

    def update(self, value):
        self.method, self.body = "PATCH", value
        self.headers["Prefer"] = "return=representation"
        return self

    def delete(self):
        self.method = "DELETE"
        self.headers["Prefer"] = "return=representation"
        return self

    def execute(self):
        return Response(self.client._request(self.method, self.path, self.params,
                                             self.body, self.headers))


class Rpc(Query):
    def __init__(self, client, name, params):
        super().__init__(client, "/rest/v1/rpc/" + quote(name, safe=""))
        self.method, self.body = "POST", params


class Storage:
    def list_buckets(self):
        # The local rehearsal intentionally starts no Storage service and the
        # canonical schema has zero buckets. This is an explicit N/A result.
        return []


class Client:
    def __init__(self, base: str, key: str):
        parts = urlsplit(base)
        if (parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parts.username or parts.password or parts.query or parts.fragment
                or parts.path not in {"", "/"}):
            raise ValueError("HTTP rehearsal client accepts loopback root only")
        self.base, self.key, self.storage = base.rstrip("/"), key, Storage()

    def table(self, name):
        if not isinstance(name, str) or not name.replace("_", "").isalnum():
            raise ValueError("Invalid PostgREST table")
        return Query(self, "/rest/v1/" + quote(name, safe=""))

    def rpc(self, name, params):
        return Rpc(self, name, params)

    def _request(self, method, path, params, body, extra_headers):
        query = "?" + urlencode(params) if params else ""
        headers = {"apikey": self.key, "Authorization": "Bearer " + self.key,
                   "Accept": "application/json", **extra_headers}
        encoded = None
        if body is not None:
            encoded = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.base + path + query, data=encoded, method=method, headers=headers)
        try:
            with build_opener(_NoRedirect).open(request, timeout=20) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise HttpError(502, json.dumps({
                        "code": "LOCAL_RESPONSE_LIMIT",
                        "message": "PostgREST response exceeded rehearsal bound",
                    }).encode("utf-8"))
        except HTTPError as error:
            raw = error.read(64 * 1024)
            raise HttpError(error.code, raw) from None
        if not raw:
            return None
        return json.loads(raw)


def create_client(base: str, key: str) -> Client:
    return Client(base, key)
