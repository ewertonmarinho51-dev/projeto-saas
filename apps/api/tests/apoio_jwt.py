"""
Emissor de JWT para as provas de UNIDADE — assinatura real, chave do teste.

Nada aqui substitui a prova de RLS: estes tokens nunca chegam a um
PostgreSQL. Quem prova isolamento entre municípios é `tests_rls/`, contra
GoTrue e PostgREST de verdade. Aqui se prova a VERIFICAÇÃO: assinatura,
algoritmo, emissor, audiência, prazo e de onde vêm tenant e papel.
"""

from __future__ import annotations

import json
import time
import uuid

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from govconect_api.supabase_rest import ClienteRest

EMISSOR = "https://exemplo-staging.supabase.co/auth/v1"
TENANT_A = "aaaaaaaa-0000-4000-8000-000000000001"
SECRETARIA_A = "aaaaaaaa-0000-4000-8000-0000000000a1"
USUARIO_A = "aaaaaaaa-0000-4000-8000-00000000a001"
LINHA_A = "aaaaaaaa-0000-4000-8000-0000000000f1"


class Emissor:
    def __init__(self) -> None:
        self.chave = ec.generate_private_key(ec.SECP256R1())
        self.kid = uuid.uuid4().hex

    def token(self, *, sub: str = USUARIO_A, tenant: str | None = TENANT_A,
              papel: str | None = "usuario", secretaria: str | None = SECRETARIA_A,
              role: str = "authenticated", aud: str = "authenticated",
              iss: str = EMISSOR, exp_em: int = 300, chave=None, kid=None,
              alg: str = "ES256", extra: dict | None = None) -> str:
        agora = int(time.time())
        meta = {}
        if tenant is not None:
            meta["tenant_id"] = tenant
        if papel is not None:
            meta["papel"] = papel
        if secretaria is not None:
            meta["secretaria_id"] = secretaria
        corpo = {"sub": sub, "role": role, "aud": aud, "iss": iss,
                 "iat": agora, "exp": agora + exp_em, "app_metadata": meta,
                 **(extra or {})}
        return jwt.encode(corpo, chave or self.chave, algorithm=alg,
                          headers={"kid": kid or self.kid})

    def chave_para(self, token: str):
        cabecalho = jwt.get_unverified_header(token)
        if cabecalho.get("kid") != self.kid:
            raise jwt.PyJWKClientError("kid desconhecido")
        return self.chave.public_key()


class PostgrestFalso:
    """Responde como o PostgREST e REGISTRA cada chamada para conferência.

    Não avalia RLS — não finge. Devolve o que o teste mandou devolver.
    """

    def __init__(self) -> None:
        self.chamadas: list[httpx.Request] = []
        self.usuarios = [{"id": LINHA_A, "ativo": True, "tenant_id": TENANT_A}]
        self.respostas: dict[tuple[str, str], list[httpx.Response]] = {}

    def responder(self, metodo: str, tabela: str, status: int, corpo) -> None:
        self.respostas.setdefault((metodo, tabela), []).append(
            httpx.Response(status, json=corpo))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.chamadas.append(request)
        tabela = request.url.path.rsplit("/", 1)[-1]
        fila = self.respostas.get((request.method, tabela))
        if fila:
            return fila.pop(0)
        if tabela == "usuarios":
            return httpx.Response(200, json=self.usuarios)
        return httpx.Response(200, json=[])

    def cliente(self) -> ClienteRest:
        return ClienteRest("https://exemplo-staging.supabase.co",
                           "chave-publicavel-de-teste",
                           transporte=httpx.MockTransport(self))

    def corpo(self, request: httpx.Request):
        return json.loads(request.content) if request.content else None
