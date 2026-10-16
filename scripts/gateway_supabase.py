#!/usr/bin/env python3
"""
Adaptador de caminho entre o cliente Supabase e um PostgREST nu.

    python scripts/gateway_supabase.py --porta 3001 --destino http://127.0.0.1:3000

POR QUE ISTO PRECISA EXISTIR

O `supabase-py` monta os endereços assim (medido na 2.31.0):

    rest_url    = <SUPABASE_URL>/rest/v1
    auth_url    = <SUPABASE_URL>/auth/v1
    storage_url = <SUPABASE_URL>/storage/v1

Um PostgREST avulso serve na RAIZ e não conhece prefixo. Apontar o app
direto para ele devolveria 404 em tudo — não porque a consulta esteja
errada, mas porque o caminho tem duas partes a mais.

Este adaptador tira `/rest/v1` e repassa o resto INTACTO: método,
cabeçalhos, corpo, query. Ele não interpreta a requisição, não
reescreve filtro nem corpo, e não decide nada sobre autorização — quem
decide é o PostgREST, com o JWT, e o Postgres, com o RLS. Se ele
começasse a tomar decisões, a bateria passaria a medir o adaptador.

`/auth/v1` RECUSA COM 501, DE PROPÓSITO

Não há GoTrue neste ambiente. A recusa é explícita e com código
próprio para que a ausência apareça como ausência: o `db.py` cai no
caminho legado da tabela `usuarios`, que é o que se quer exercitar, e
o laudo pode dizer com honestidade que a emissão de JWT de usuário NÃO
foi testada aqui.

Devolver 200 vazio seria pior: o app acharia que autenticou.

`--destino-auth http://127.0.0.1:<porta>` habilita somente o encaminhamento
para um GoTrue REAL local. Sem essa opção o mesmo 501 continua valendo.
"""

from __future__ import annotations

import argparse
import http.server
import socketserver
import urllib.error
import urllib.request
from urllib.parse import urlsplit

PREFIXO_REST = "/rest/v1"
PREFIXO_AUTH = "/auth/v1"

# Cabeçalhos que o cliente HTTP local recalcula sozinho. Repassá-los
# corrompe a requisição (Host errado, Content-Length em conflito com o
# corpo já lido, encoding que o urllib não aplicou).
NAO_REPASSAR = {"host", "content-length", "connection", "accept-encoding"}

DESTINO = "http://127.0.0.1:3000"
DESTINO_AUTH: str | None = None
MAX_BODY = 24 * 1024 * 1024


def destino_loopback(value: str) -> str:
    """Explicit local HTTP origin only; no DNS, credentials, path or redirects."""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
                or parsed.port is None or not 1 <= parsed.port <= 65535
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("Destino do gateway deve ser uma origem HTTP loopback explícita.") from None
    return value.rstrip("/")


class SemRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _prefixo(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith((prefix + "/", prefix + "?"))


class Adaptador(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # O log padrão do BaseHTTPRequestHandler escreve a QUERY STRING na
    # saída de erro, e a query string carrega os filtros do PostgREST —
    # inclusive valores de dados de teste. O laudo anexa logs; este fica
    # mudo.
    def log_message(self, formato, *args):  # noqa: D102, N802
        pass

    def _repassar(self) -> None:
        caminho = self.path
        destino = DESTINO
        if _prefixo(caminho, PREFIXO_AUTH):
            if DESTINO_AUTH is None:
                self._recusar_auth()
                return
            destino = DESTINO_AUTH
            caminho = caminho[len(PREFIXO_AUTH):] or "/"
        elif _prefixo(caminho, PREFIXO_REST):
            caminho = caminho[len(PREFIXO_REST):] or "/"
        elif caminho.startswith("/storage/v1") or caminho.startswith(
                "/functions/v1"):
            self._responder(501, b'{"erro":"servico ausente na homologacao"}')
            return

        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            if not 0 <= tamanho <= MAX_BODY or self.headers.get("Transfer-Encoding"):
                raise ValueError()
        except ValueError:
            self.close_connection = True
            self._responder(413, b'{"erro":"corpo HTTP recusado"}')
            return
        corpo = self.rfile.read(tamanho) if tamanho else None

        cabecalhos = {nome: valor for nome, valor in self.headers.items()
                      if nome.lower() not in NAO_REPASSAR}

        pedido = urllib.request.Request(
            destino + caminho, data=corpo, method=self.command,
            headers=cabecalhos)
        try:
            with urllib.request.build_opener(SemRedirect).open(pedido, timeout=20) as resposta:
                self._devolver(resposta.status, resposta.headers,
                               resposta.read(MAX_BODY + 1))
        except urllib.error.HTTPError as erro:
            # 4xx e 5xx do PostgREST são RESPOSTA, não falha do
            # adaptador: o corpo traz o código PGRST e a mensagem, que
            # é justamente o que o `db.py` lê para decidir.
            self._devolver(erro.code, erro.headers, erro.read(MAX_BODY + 1))
        except (urllib.error.URLError, TimeoutError):
            self._responder(
                502, b'{"erro":"servico local inalcancavel"}')

    def _recusar_auth(self) -> None:
        self._responder(
            501,
            b'{"erro":"GoTrue ausente: este ambiente de homologacao nao '
            b'emite JWT de usuario"}')

    def _responder(self, codigo: int, corpo: bytes) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _devolver(self, codigo: int, cabecalhos, corpo: bytes) -> None:
        if len(corpo) > MAX_BODY:
            self._responder(502, b'{"erro":"resposta local excessiva"}')
            return
        self.send_response(codigo)
        for nome, valor in cabecalhos.items():
            if nome.lower() in ("content-length", "transfer-encoding",
                                "connection"):
                continue
            self.send_header(nome, valor)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    do_GET = _repassar        # noqa: N815
    do_POST = _repassar       # noqa: N815
    do_PATCH = _repassar      # noqa: N815
    do_PUT = _repassar        # noqa: N815
    do_DELETE = _repassar     # noqa: N815
    do_HEAD = _repassar       # noqa: N815
    do_OPTIONS = _repassar    # noqa: N815


class Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def principal(argv: list[str] | None = None) -> int:
    global DESTINO, DESTINO_AUTH

    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--porta", type=int, default=3001)
    analisador.add_argument("--destino", default=DESTINO)
    analisador.add_argument("--destino-auth", default=None)
    argumentos = analisador.parse_args(argv)
    DESTINO = destino_loopback(argumentos.destino)
    DESTINO_AUTH = destino_loopback(argumentos.destino_auth) if argumentos.destino_auth is not None else None

    with Servidor(("127.0.0.1", argumentos.porta), Adaptador) as servidor:
        print(f"adaptador em http://127.0.0.1:{argumentos.porta} "
              f"-> {DESTINO}", flush=True)
        servidor.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
