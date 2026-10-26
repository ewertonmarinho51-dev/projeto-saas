"""
Cliente RESTRITO da Admin API do Supabase Auth (ADR-010).

É o único lugar da API que segura a credencial de servidor, e ela só sai
daqui para `{SUPABASE_URL}/auth/v1/admin/users…`. O cliente sabe quatro
coisas, de propósito poucas:

* `conta(uid)`: ler UMA conta (para conferir o tenant antes de escrever);
* `criar(email, nome, escopo)`: conta confirmada, com `app_metadata` no
  mesmo ato — sem janela de conta sem escopo;
* `atualizar_escopo(uid, escopo)`: gravar `app_metadata`;
* `bloquear(uid, sim)`: impedir (ou devolver) a entrada e a RENOVAÇÃO de
  token — é o que faz "desativar" valer também fora da API, no PostgREST
  direto, quando o token atual vencer;
* `desfazer_criacao(uid)`: apagar a conta que ESTA requisição acabou de
  criar, quando o vínculo em `usuarios` falha. Quem chama garante isso.

Não lista contas, não troca e-mail nem senha, não gera link. Erros do
provedor nunca carregam o corpo da resposta para cima: ele pode ecoar
dados da conta.
"""

from __future__ import annotations

import logging

import httpx

_log = logging.getLogger("govconect_api")


class ErroAdminAuth(Exception):
    """A Admin API não respondeu como esperado (transporte ou 5xx)."""


class ContaJaExiste(Exception):
    """Já há conta no Auth com este e-mail."""


class EmailRecusado(Exception):
    """O Auth recusou o e-mail por outro motivo (formato, domínio…)."""


# "Bloqueado" no Auth: o GoTrue mede em duração; ~100 anos é o "até
# desbloquear" que ele aceita, e "none" desfaz.
BLOQUEIO = "876000h"


def _json(resposta: httpx.Response) -> dict:
    try:
        corpo = resposta.json()
    except ValueError:
        raise ErroAdminAuth("resposta ilegível da Admin API") from None
    return corpo if isinstance(corpo, dict) else {}


class AdminDoAuth:
    def __init__(self, supabase_url: str, chave: str, *,
                 transporte: httpx.BaseTransport | None = None) -> None:
        if not chave.startswith("sb_secret_"):
            raise ValueError("a Admin API só aceita a chave sb_secret_")
        self._base = f"{supabase_url.rstrip('/')}/auth/v1/admin/users"
        self._http = httpx.Client(
            headers={"apikey": chave, "Authorization": f"Bearer {chave}"},
            timeout=10.0, transport=transporte)

    def fechar(self) -> None:
        self._http.close()

    def _pedir(self, metodo: str, caminho: str = "", corpo: dict | None = None) -> httpx.Response:
        try:
            resposta = self._http.request(metodo, self._base + caminho, json=corpo)
        except httpx.HTTPError as exc:
            raise ErroAdminAuth("Admin API inacessível") from exc
        if resposta.status_code >= 500:
            _log.warning("admin_auth_falhou metodo=%s status=%s", metodo, resposta.status_code)
            raise ErroAdminAuth(f"Admin API respondeu {resposta.status_code}")
        return resposta

    def conta(self, uid: str) -> dict | None:
        resposta = self._pedir("GET", f"/{uid}")
        if resposta.status_code == 404:
            return None
        if resposta.status_code != 200:
            raise ErroAdminAuth(f"leitura da conta: {resposta.status_code}")
        return _json(resposta)

    def criar(self, email: str, nome: str, escopo: dict) -> str:
        resposta = self._pedir("POST", corpo={
            "email": email, "email_confirm": True,
            "app_metadata": escopo, "user_metadata": {"nome": nome}})
        if resposta.status_code in (409, 422):
            # O corpo não sobe: ele pode ecoar o e-mail. Só o CÓDIGO decide.
            corpo = _json(resposta) if resposta.content else {}
            codigo = str(corpo.get("error_code") or corpo.get("code") or "")
            texto = str(corpo.get("msg") or corpo.get("message") or "").lower()
            ja_existe = codigo in ("email_exists", "user_already_exists") or "already" in texto
            if resposta.status_code == 409 or ja_existe:
                raise ContaJaExiste()
            raise EmailRecusado()
        if resposta.status_code not in (200, 201):
            raise ErroAdminAuth(f"criação da conta: {resposta.status_code}")
        uid = str(_json(resposta).get("id") or "")
        if not uid:
            raise ErroAdminAuth("criação da conta sem id")
        return uid

    def atualizar_escopo(self, uid: str, escopo: dict) -> None:
        resposta = self._pedir("PUT", f"/{uid}", {"app_metadata": escopo})
        if resposta.status_code != 200:
            raise ErroAdminAuth(f"atualização do escopo: {resposta.status_code}")

    def bloquear(self, uid: str, bloquear: bool) -> None:
        resposta = self._pedir("PUT", f"/{uid}", {"ban_duration": BLOQUEIO if bloquear else "none"})
        if resposta.status_code != 200:
            raise ErroAdminAuth(f"bloqueio da conta: {resposta.status_code}")

    def desfazer_criacao(self, uid: str) -> None:
        resposta = self._pedir("DELETE", f"/{uid}")
        if resposta.status_code not in (200, 204, 404):
            raise ErroAdminAuth(f"desfazer criação: {resposta.status_code}")
