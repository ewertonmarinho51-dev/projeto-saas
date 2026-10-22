"""
Fábrica da API do Gov Conect.

`criar_app()` não lê nada no import: quem sobe o servidor é `asgi.py`,
e os testes montam a aplicação com o ambiente que quiserem. Assim um
`import govconect_api.main` nunca derruba a coleta de testes por causa
de uma variável da máquina.

Esta API convive com o Streamlit (estratégia strangler, ADR-006). De
`src/` importa só módulo puro (hoje `src.processos`) — a prova mecânica
está em `tests/test_sem_streamlit.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import erros, precos, processos
from .camadas import CamadaDeRequisicao
from .config import Configuracao, carregar
from .limites import Limitador, aplicar_limite
from .seguranca import Identidade, VerificadorDeToken, exigir_identidade
from .supabase_rest import ClienteRest
from .verificador import VerificadorSupabase

VERSAO_API = "0.2.0"


class Vivo(BaseModel):
    status: str


class Pronto(BaseModel):
    status: str
    checks: dict[str, str]


class Me(BaseModel):
    auth_user_id: str
    tenant_id: str
    papel: str
    secretaria_id: str | None = None


def _rotas_de_saude(config: Configuracao) -> APIRouter:
    rotas = APIRouter(prefix="/health", tags=["saude"])

    @rotas.get("/live", response_model=Vivo)
    def vivo() -> Vivo:
        # Sem tocar Supabase, Redis ou provedor de IA. Se o liveness
        # dependesse deles, uma queda do provedor faria o orquestrador
        # reiniciar a API em cascata — e reiniciar não conserta o
        # provedor de ninguém.
        return Vivo(status="ok")

    @rotas.get("/ready", response_model=Pronto,
               responses={503: {"model": Pronto}})
    def pronto(request: Request) -> JSONResponse:
        # Só nomes e "ok"/"ausente": nem URL, nem prefixo de chave, nem
        # mensagem de erro do provedor. Prontidão é lida por máquina, e
        # o que ela expõe fica exposto para quem alcançar a rota.
        checks = {
            "configuracao": "ok" if config.supabase_url else "ausente",
            "verificador_de_token": (
                "ok" if request.app.state.verificador_de_token is not None
                else "ausente"),
        }
        ok = all(v == "ok" for v in checks.values())
        corpo = Pronto(status="ready" if ok else "not_ready", checks=checks)
        return JSONResponse(corpo.model_dump(), status_code=200 if ok else 503)

    return rotas


def _rotas_v1() -> APIRouter:
    # A dependência está no ROTEADOR, não em cada rota: rota nova nasce
    # protegida, e esquecer a guarda passa a exigir esforço.
    # Ordem importa: o limite conta por USUÁRIO verificado, então vem
    # depois da identidade.
    rotas = APIRouter(prefix="/api/v1", tags=["v1"],
                      dependencies=[Depends(exigir_identidade),
                                    Depends(aplicar_limite)])

    @rotas.get("/me", response_model=Me,
               responses={401: {"description": "Sessão ausente ou inválida"},
                          503: {"description": "Autenticação indisponível"}})
    def me(identidade: Identidade = Depends(exigir_identidade)) -> Me:
        return Me(auth_user_id=identidade.auth_user_id,
                  tenant_id=identidade.tenant_id, papel=identidade.papel,
                  secretaria_id=identidade.secretaria_id)

    rotas.include_router(processos.rotas())
    rotas.include_router(precos.rotas())
    return rotas


def _montar_autenticacao(config: Configuracao, rest: ClienteRest | None):
    """(verificador, rest) a partir da configuração; (None, None) sem ela."""
    if not config.autenticacao_configurada:
        return None, rest
    rest = rest or ClienteRest(config.supabase_url, config.supabase_chave_publica)
    if config.jwt_segredo_hs256:
        verificador = VerificadorSupabase(emissor=config.jwt_emissor, rest=rest,
                                          segredo_hs256=config.jwt_segredo_hs256)
    else:
        verificador = VerificadorSupabase(emissor=config.jwt_emissor, rest=rest,
                                          jwks_url=config.jwks_url)
    return verificador, rest


def criar_app(config: Configuracao | None = None,
              verificador: VerificadorDeToken | None = None,
              rest: ClienteRest | None = None) -> FastAPI:
    config = config or carregar()
    if verificador is None:
        verificador, rest = _montar_autenticacao(config, rest)
    app = FastAPI(
        title="Gov Conect API",
        version=VERSAO_API,
        docs_url="/docs" if config.expor_documentacao else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.expor_documentacao else None,
    )
    app.state.config = config
    app.state.verificador_de_token = verificador
    app.state.rest = rest
    app.state.limitador = Limitador(config.limite_por_minuto)

    erros.instalar(app)

    app.include_router(_rotas_de_saude(config))
    app.include_router(_rotas_v1())

    if config.origens_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.origens_cors),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key",
                           "If-Match", "X-Request-ID"],
            expose_headers=["X-Request-ID", "ETag", "Location", "Retry-After",
                            "Idempotent-Replayed"],
            max_age=600,
        )
    # Por último = mais externa: até a resposta do CORS leva request_id.
    app.add_middleware(CamadaDeRequisicao)
    return app
