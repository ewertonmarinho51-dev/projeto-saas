"""
Guarda de identidade das rotas privadas — falha fechada.

Toda rota sob `/api/v1` depende de `exigir_identidade`, e
`tests/test_rotas_privadas.py` reprova a rota que esquecer. A guarda
não tem atalho: sem cabeçalho é 401; com cabeçalho e sem verificador
configurado é 503. Não existe caminho em que "não consegui verificar"
vire "deixo passar".

O verificador real mora em `verificador.py` (assinatura, claims e
vínculo em `usuarios`). Sem ele configurado, a API não autoriza
NINGUÉM — que é o que ela deve fazer enquanto não sabe verificar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from fastapi import Request

from .erros import ErroApi, request_id_de

_log = logging.getLogger("govconect_api")
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
    # `usuarios.id` — o identificador da tabela própria do app, diferente
    # de `auth_user_id`. O Streamlit lista processos do servidor por ele.
    usuario_id: str = ""
    # Papel no Centro de Governança (`app_metadata.papel_governanca`, do
    # vocabulário `governanca.PAPEIS_GOVERNANCA`); None = sem acesso, salvo
    # admin, que opera como admin_municipal — a regra do Streamlit.
    papel_governanca: str | None = None
    # O token segue com a identidade para as chamadas ao PostgREST irem
    # com ELE. Fora do repr e da comparação: não aparece em log nem em
    # mensagem de asserção.
    token: str = field(default="", repr=False, compare=False)


class TokenRecusado(Exception):
    """Assinatura, emissor, audiência ou prazo não conferem."""


class SemVinculo(Exception):
    """Token autêntico, mas sem vínculo institucional válido e ativo."""


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
        identidade = verificador.verificar(token)
    except TokenRecusado as exc:
        _log.info("token_recusado request_id=%s motivo=%s",
                  request_id_de(request), exc)
        raise ErroApi(401, "UNAUTHENTICATED",
                      "Sessão ausente, expirada ou inválida", _DESAFIO) from None
    except SemVinculo as exc:
        # Motivo só no log: dizer ao cliente "sua conta existe mas está
        # desativada" é informação que quem testa credenciais quer ter.
        _log.info("acesso_negado request_id=%s motivo=%s",
                  request_id_de(request), exc)
        raise ErroApi(403, "FORBIDDEN", "Acesso negado") from None
    request.state.identidade = identidade
    return identidade
