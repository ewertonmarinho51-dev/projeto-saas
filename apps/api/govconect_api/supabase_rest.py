"""
Cliente do PostgREST que SÓ fala com o JWT do usuário.

Não existe, neste arquivo, caminho para a chave de servidor. É a
diferença que importa em relação a `src/db.py::_cliente()`, que carrega
a credencial secreta e atravessa o RLS: lá a contenção de tenant é um
`.eq("tenant_id", …)` escrito à mão em cada consulta (achado P0 de
24/09); aqui quem decide é a política da 0020, avaliada pelo Postgres
para o dono do token.

`apikey` leva a chave PUBLICÁVEL, que identifica o projeto e não dá
acesso a nada sozinha; `Authorization` leva o token do usuário.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from .erros import ErroApi

_log = logging.getLogger("govconect_api")

# Curto de propósito. Requisição de usuário que espera 30 s pelo banco
# segura a thread, e trinta delas param a API inteira.
TIMEOUT = httpx.Timeout(5.0, connect=3.0)


@dataclass
class RespostaRest:
    status: int
    dados: object
    cabecalhos: httpx.Headers

    @property
    def codigo_pg(self) -> str:
        return self.dados.get("code", "") if isinstance(self.dados, dict) else ""


class ClienteRest:
    def __init__(self, supabase_url: str, chave_publica: str,
                 transporte: httpx.BaseTransport | None = None) -> None:
        self._base = f"{supabase_url}/rest/v1"
        self._http = httpx.Client(timeout=TIMEOUT, transport=transporte,
                                  follow_redirects=False)
        self._chave_publica = chave_publica

    def requisitar(self, token: str, metodo: str, tabela: str, *,
                   params: dict | list | None = None, corpo=None,
                   prefer: str | None = None) -> RespostaRest:
        if not token:
            # Defesa em profundidade: a guarda já barrou sem token, mas este
            # cliente não pode virar anônimo por um chamador descuidado.
            raise ErroApi(401, "UNAUTHENTICATED",
                          "Sessão ausente, expirada ou inválida")
        cabecalhos = {"apikey": self._chave_publica,
                      "Authorization": f"Bearer {token}",
                      "Accept": "application/json"}
        if prefer:
            cabecalhos["Prefer"] = prefer
        try:
            r = self._http.request(metodo, f"{self._base}/{tabela}",
                                   params=params, json=corpo,
                                   headers=cabecalhos)
        except httpx.HTTPError as exc:
            _log.warning("supabase_indisponivel tipo=%s", type(exc).__name__)
            raise ErroApi(503, "DATABASE_UNAVAILABLE",
                          "Banco de dados indisponível") from None
        try:
            dados = r.json() if r.content else None
        except ValueError:
            dados = None
        resposta = RespostaRest(r.status_code, dados, r.headers)
        if r.status_code in (401, 403) and resposta.codigo_pg in (
                "PGRST301", "PGRST302", "PGRST303"):
            # Token que o PostgREST recusou (vencido no caminho, assinatura
            # rotacionada). A API já tinha verificado; aqui só não piora.
            raise ErroApi(401, "UNAUTHENTICATED",
                          "Sessão ausente, expirada ou inválida",
                          {"WWW-Authenticate": "Bearer"})
        if r.status_code >= 500:
            _log.warning("supabase_erro status=%s codigo=%s", r.status_code,
                         resposta.codigo_pg)
            raise ErroApi(503, "DATABASE_UNAVAILABLE",
                          "Banco de dados indisponível")
        return resposta

    def fechar(self) -> None:
        self._http.close()
