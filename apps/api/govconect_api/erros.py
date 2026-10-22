"""
Envelope único de erro: `{"code", "message", "request_id"}`.

Nenhuma resposta de erro repete o que o cliente mandou nem o texto da
exceção. A lição veio do app antigo: exceção do PostgREST carrega a
credencial no cabeçalho e na URL, e repassá-la para a tela vazou o
segredo (ver `docs/seguranca-achado-p0.md`). Aqui o cliente recebe um
código estável; o detalhe, quando existe, fica no log do servidor
amarrado ao `request_id`.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_log = logging.getLogger("govconect_api")

_CODIGO_POR_STATUS = {
    400: ("BAD_REQUEST", "Requisição inválida"),
    401: ("UNAUTHENTICATED", "Sessão ausente, expirada ou inválida"),
    403: ("FORBIDDEN", "Acesso negado"),
    404: ("NOT_FOUND", "Recurso não encontrado"),
    405: ("METHOD_NOT_ALLOWED", "Método não permitido"),
    409: ("CONFLICT", "Conflito de versão"),
    422: ("VALIDATION_ERROR", "Dados inválidos"),
    429: ("RATE_LIMITED", "Limite de requisições excedido"),
    503: ("UNAVAILABLE", "Serviço indisponível"),
}


class ErroApi(Exception):
    """Erro com código estável. `message` vai ao cliente: nada de segredo."""

    def __init__(self, status: int, code: str, message: str,
                 headers: dict[str, str] | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}


def request_id_de(request: Request) -> str:
    return getattr(request.state, "request_id", "") or ""


def resposta_de_erro(request: Request, status: int, code: str, message: str,
                     headers: dict[str, str] | None = None,
                     extra: dict | None = None) -> JSONResponse:
    request_id = request_id_de(request)
    # O cabeçalho vai aqui também: o 500 é montado FORA das camadas de
    # middleware, e sem isto justamente a resposta que mais precisa de
    # correlação sairia sem ela.
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message,
                 "request_id": request_id, **(extra or {})},
        headers={**(headers or {}), "X-Request-ID": request_id,
                 "Cache-Control": "no-store"},
    )


def instalar(app: FastAPI) -> None:
    @app.exception_handler(ErroApi)
    async def _erro_api(request: Request, exc: ErroApi):
        return resposta_de_erro(request, exc.status, exc.code, exc.message,
                                exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code, message = _CODIGO_POR_STATUS.get(
            exc.status_code, ("HTTP_ERROR", "Erro na requisição"))
        return resposta_de_erro(request, exc.status_code, code, message,
                                getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validacao(request: Request, exc: RequestValidationError):
        # O padrão do FastAPI devolve `input` — o valor recebido. Num corpo
        # com documento ou planilha, isso ecoaria o conteúdo inteiro. Sai
        # só ONDE e QUE TIPO de erro, que é o que o cliente precisa.
        campos = [{"loc": list(erro.get("loc", ())), "type": erro.get("type")}
                  for erro in exc.errors()]
        return resposta_de_erro(request, 422, "VALIDATION_ERROR",
                                "Dados inválidos", extra={"fields": campos})

    @app.exception_handler(Exception)
    async def _inesperado(request: Request, exc: Exception):
        # Só o TIPO vai ao log. O texto da exceção pode trazer URL com
        # chave ou trecho de documento; o tipo e o request_id bastam para
        # achar o caso, e o resto se reproduz em ambiente controlado.
        _log.error("erro_inesperado request_id=%s tipo=%s",
                   request_id_de(request), type(exc).__name__)
        return resposta_de_erro(request, 500, "INTERNAL_ERROR",
                                "Erro interno")
