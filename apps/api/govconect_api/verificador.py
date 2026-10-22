"""
Verificador do JWT do Supabase Auth + vínculo institucional.

Duas etapas, as duas obrigatórias:

1. **Assinatura e claims.** Produção assina com ES256 e publica a chave
   em `<SUPABASE_URL>/auth/v1/.well-known/jwks.json` (conferido em
   22/10/2026: uma chave EC P-256). Algoritmos aceitos são fixados pelo
   MODO, nunca lidos do cabeçalho do token: aceitar o `alg` que o token
   declara é a confusão de algoritmo clássica (`none`, ou HS256 assinado
   com a chave pública como segredo). `iss`, `aud`, `exp`, `sub` e
   `role=authenticated` são exigidos.

2. **Vínculo.** Token válido prova quem é, não que ainda pode entrar. A
   linha de `usuarios` é lida COM O PRÓPRIO TOKEN (política
   `usuarios_le_a_si`) e tem de existir, estar ativa e pertencer ao mesmo
   tenant do token. Desativar o servidor corta o acesso na requisição
   seguinte, sem esperar o `exp`.

Tenant, papel e secretaria vêm de `app_metadata`, gravável só pela Admin
API. `user_metadata` é editável pelo próprio usuário e é ignorado.
"""

from __future__ import annotations

import logging
import uuid
from typing import Callable

import jwt

from .erros import ErroApi
from .seguranca import Identidade, SemVinculo, TokenRecusado
from .supabase_rest import ClienteRest

_log = logging.getLogger("govconect_api")

ALGORITMOS_JWKS = ("ES256", "RS256")
AUDIENCIA = "authenticated"
FOLGA_DE_RELOGIO_S = 30
PAPEIS = ("admin", "usuario")


def _uuid_ou_none(valor) -> str | None:
    if valor in (None, ""):
        return None
    try:
        return str(uuid.UUID(str(valor)))
    except (ValueError, TypeError, AttributeError):
        raise SemVinculo("vinculo_malformado") from None


class VerificadorSupabase:
    def __init__(self, *, emissor: str, rest: ClienteRest,
                 chave_para: Callable[[str], object] | None = None,
                 jwks_url: str = "", segredo_hs256: str = "") -> None:
        if bool(segredo_hs256) == bool(chave_para or jwks_url):
            raise ValueError("escolha UM modo: JWKS ou segredo HS256")
        self._emissor = emissor
        self._rest = rest
        self._segredo = segredo_hs256
        if segredo_hs256:
            self._algoritmos = ("HS256",)
            self._chave_para = lambda token: segredo_hs256
        else:
            self._algoritmos = ALGORITMOS_JWKS
            if chave_para is None:
                # Cache curto: a doc do Supabase pede para não guardar o
                # JWKS por mais que os 10 min da borda, senão a rotação
                # de chave tranca usuários legítimos.
                clientes = jwt.PyJWKClient(jwks_url, cache_keys=True,
                                           lifespan=600, timeout=5)
                chave_para = lambda token: clientes.get_signing_key_from_jwt(token).key  # noqa: E731
            self._chave_para = chave_para

    # -- etapa 1 -----------------------------------------------------------
    def claims(self, token: str) -> dict:
        try:
            cabecalho = jwt.get_unverified_header(token)
            if cabecalho.get("alg") not in self._algoritmos:
                raise TokenRecusado("algoritmo")
            chave = self._chave_para(token)
            return jwt.decode(
                token, chave, algorithms=list(self._algoritmos),
                audience=AUDIENCIA, issuer=self._emissor,
                leeway=FOLGA_DE_RELOGIO_S,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]})
        except TokenRecusado:
            raise
        except jwt.PyJWKClientConnectionError:
            # JWKS fora do ar não é token inválido: é a API sem saber
            # verificar. 503 — nunca 200, e nunca culpar o usuário com 401.
            _log.warning("jwks_indisponivel")
            raise ErroApi(503, "AUTH_UNAVAILABLE",
                          "Autenticação indisponível neste ambiente") from None
        except jwt.PyJWKClientError:
            raise TokenRecusado("chave_desconhecida") from None
        except jwt.InvalidTokenError:
            raise TokenRecusado("token_invalido") from None

    # -- etapa 1 + 2 -------------------------------------------------------
    def verificar(self, token: str) -> Identidade:
        claims = self.claims(token)
        if claims.get("role") != "authenticated":
            # `anon` e `service_role` também são JWTs válidos do projeto.
            # Nenhum dos dois é um usuário.
            raise TokenRecusado("papel_de_rede")
        try:
            sub = str(uuid.UUID(str(claims["sub"])))
        except (ValueError, TypeError):
            raise TokenRecusado("sub") from None

        meta = claims.get("app_metadata")
        meta = meta if isinstance(meta, dict) else {}
        tenant = _uuid_ou_none(meta.get("tenant_id"))
        if tenant is None:
            raise SemVinculo("sem_tenant")
        papel = meta.get("papel") or "usuario"
        if papel not in PAPEIS:
            raise SemVinculo("papel_desconhecido")
        secretaria = _uuid_ou_none(meta.get("secretaria_id"))

        resposta = self._rest.requisitar(
            token, "GET", "usuarios",
            params={"select": "id,ativo,tenant_id", "auth_user_id": f"eq.{sub}",
                    "limit": "1"})
        linhas = resposta.dados if resposta.status == 200 else None
        if not isinstance(linhas, list) or not linhas:
            raise SemVinculo("sem_linha_em_usuarios")
        linha = linhas[0]
        if linha.get("ativo") is not True:
            raise SemVinculo("usuario_desativado")
        if _uuid_ou_none(linha.get("tenant_id")) != tenant:
            # Claim e cadastro divergem: alguém mudou um sem o outro. Na
            # dúvida sobre qual município a pessoa representa, nenhum.
            raise SemVinculo("tenant_divergente")

        return Identidade(auth_user_id=sub, tenant_id=tenant, papel=papel,
                          secretaria_id=secretaria,
                          usuario_id=str(linha.get("id") or ""), token=token)
