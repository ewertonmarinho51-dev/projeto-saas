"""
Guarda de identidade das rotas privadas — falha fechada.

Toda rota sob `/api/v1` depende de `exigir_identidade`, e
`tests/test_rotas_privadas.py` reprova a rota que esquecer. A guarda
não tem atalho: sem cabeçalho é 401; com cabeçalho e sem verificador
configurado é 503. Não existe caminho em que "não consegui verificar"
vire "deixo passar".

O verificador real (JWT do Supabase Auth, assinatura e claims conferidas
no servidor, vínculo institucional na tabela `usuarios`) entra no P02.
Até lá a API não autoriza NINGUÉM — e é exatamente isso que ela deve
fazer enquanto não sabe verificar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fastapi import Request

from .erros import ErroApi

_DESAFIO = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class Identidade:
    """Quem chama, derivado do token VERIFICADO e do vínculo no banco.

    Nunca do corpo, da query ou de `user_metadata` — que o próprio
    usuário edita. `tenant_id` e `papel` vêm de `app_metadata`, gravável
    só pela Admin API (ver a 0020, ETAPA B).
    """

    auth_user_id: str
    tenant_id: str
    papel: str
    secretaria_id: str | None = None


class TokenRecusado(Exception):
    """Assinatura, emissor, audiência ou prazo não conferem."""


class VerificadorDeToken(Protocol):
    def verificar(self, token: str) -> Identidade:
        """Devolve a identidade ou levanta `TokenRecusado`."""


def _token_bearer(request: Request) -> str:
    cabecalho = request.headers.get("authorization", "")
    esquema, _, token = cabecalho.partition(" ")
    if esquema.lower() != "bearer" or not token.strip() or " " in token.strip():
        raise ErroApi(401, "UNAUTHENTICATED",
                      "Sessão ausente, expirada ou inválida", _DESAFIO)
    return token.strip()


def exigir_identidade(request: Request) -> Identidade:
    token = _token_bearer(request)
    verificador: VerificadorDeToken | None = getattr(
        request.app.state, "verificador_de_token", None)
    if verificador is None:
        raise ErroApi(503, "AUTH_UNAVAILABLE",
                      "Autenticação indisponível neste ambiente")
    try:
        return verificador.verificar(token)
    except TokenRecusado:
        raise ErroApi(401, "UNAUTHENTICATED",
                      "Sessão ausente, expirada ou inválida", _DESAFIO) from None
