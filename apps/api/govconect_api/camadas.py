"""
Camadas que valem para TODA requisição: identificador de correlação,
cabeçalhos de resposta, linha de acesso e métricas (`observabilidade`).

ASGI puro, e não `BaseHTTPMiddleware`: este último roda o handler em
outra tarefa e já quebrou propagação de contexto e streaming em versões
do Starlette. Para dois cabeçalhos, o caminho simples é o certo.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from .observabilidade import METRICAS, pseudonimo

_log = logging.getLogger("govconect_api.acesso")

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
        inicio = time.perf_counter()
        status = [500]

        async def enviar(mensagem):
            if mensagem["type"] == "http.response.start":
                status[0] = int(mensagem.get("status") or 500)
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

        try:
            await self.app(scope, receive, enviar)
        finally:
            _registrar(scope, request_id, status[0], time.perf_counter() - inicio)


def _modelo_da_rota(scope) -> str:
    """`/api/v1/precos/pesquisas/{pesquisa_id}` a partir do caminho real.

    O objeto da rota casada guarda o caminho RELATIVO ao roteador em que
    nasceu (roteadores aninhados), então o modelo sai do próprio caminho:
    cada segmento que é o valor de um parâmetro vira `{nome}`. A query
    nunca entra (`scope["path"]` não a tem)."""
    if scope.get("route") is None:
        return "desconhecida"
    valores = {str(v): k for k, v in (scope.get("path_params") or {}).items()}
    caminho = str(scope.get("path") or "")
    return "/".join("{" + valores[s] + "}" if s in valores else s
                    for s in caminho.split("/")) or "desconhecida"


def _registrar(scope, request_id: str, status: int, duracao_s: float) -> None:
    """A linha de acesso e as métricas. Rota é o MODELO casado pelo
    roteador; sem casar (404 de caminho inventado), `desconhecida` — senão
    cada URL varrida viraria uma série nova."""
    rota = _modelo_da_rota(scope)
    metodo = str(scope.get("method") or "")
    identidade = (scope.get("state") or {}).get("identidade")
    METRICAS.requisicao(metodo=metodo, rota=rota, status=status, duracao_s=duracao_s)
    if rota.startswith("/health"):
        return          # sonda a cada 15 s não é tráfego de usuário
    _log.info("requisicao", extra={
        "evento": "requisicao", "request_id": request_id, "metodo": metodo, "rota": rota,
        "status": status, "duracao_ms": round(duracao_s * 1000, 1),
        "tenant": pseudonimo(getattr(identidade, "tenant_id", None))})
