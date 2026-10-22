"""
Camadas que valem para TODA requisição: identificador de correlação e
cabeçalhos de resposta.

ASGI puro, e não `BaseHTTPMiddleware`: este último roda o handler em
outra tarefa e já quebrou propagação de contexto e streaming em versões
do Starlette. Para dois cabeçalhos, o caminho simples é o certo.
"""

from __future__ import annotations

import re
import uuid

# Aceita o id que o proxy mandar só se tiver cara de id. Um valor livre
# iria parar no log tal como veio — e log que aceita quebra de linha do
# cliente é log que o cliente escreve.
_FORMATO_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def request_id_valido(valor: str) -> bool:
    return bool(_FORMATO_REQUEST_ID.fullmatch(valor or ""))


class CamadaDeRequisicao:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        recebido = ""
        for nome, valor in scope.get("headers", ()):
            if nome == b"x-request-id":
                recebido = valor.decode("latin-1")
                break
        request_id = recebido if request_id_valido(recebido) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def enviar(mensagem):
            if mensagem["type"] == "http.response.start":
                cabecalhos = [(n, v) for n, v in mensagem.get("headers", ())
                              if n.lower() not in (b"x-request-id",
                                                   b"cache-control",
                                                   b"x-content-type-options")]
                cabecalhos += [
                    (b"x-request-id", request_id.encode("latin-1")),
                    # Nada desta API é público e cacheável: identidade,
                    # processo, cesta, relatório. `no-store` em tudo evita
                    # que uma CDN ou proxy entregue a resposta de um
                    # município a outro.
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ]
                mensagem = {**mensagem, "headers": cabecalhos}
            await send(mensagem)

        await self.app(scope, receive, enviar)
