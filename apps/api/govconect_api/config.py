"""
Configuração da API, lida SOMENTE do ambiente.

Nada de `st.secrets` aqui: a API não conhece o Streamlit, e um segredo
que dependesse de `.streamlit/secrets.toml` faria a API herdar o
arquivo do app antigo sem ninguém decidir.

A regra que atravessa o arquivo: configuração ruim em staging ou
produção NÃO sobe. Um servidor que "funciona com aviso" depois de ler
`GOVDOCS_MODO_ABERTO=1` é um servidor aberto que avisa — e aviso em log
ninguém lê às três da manhã.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

AMBIENTES = ("development", "test", "staging", "production")
AMBIENTES_PROTEGIDOS = ("staging", "production")

_VERDADEIRO = ("1", "true", "on", "sim", "yes")


class ConfiguracaoInvalida(RuntimeError):
    """A API se recusa a subir. A mensagem nunca carrega valor de segredo."""


@dataclass(frozen=True)
class Configuracao:
    ambiente: str
    supabase_url: str
    origens_cors: tuple[str, ...]
    # Chave PUBLICÁVEL: vai no cabeçalho `apikey` das chamadas ao
    # PostgREST, ao lado do JWT do usuário. Nunca a chave de servidor —
    # esta API não a lê, e por isso não pode atravessar o RLS.
    supabase_chave_publica: str = field(default="", repr=False)
    # Só para a pilha descartável local, que assina com segredo HS256.
    # Produção assina com ES256 e publica o JWKS; lá o segredo é recusado.
    jwt_segredo_hs256: str = field(default="", repr=False)
    limite_por_minuto: int = 120
    # Pesquisa de preços na API (P04). DESLIGADA por padrão em todo
    # ambiente: 05_SEGURANCA manda não ligar `price_research` antes de
    # auth + RLS + limites + auditoria aprovados. Ligar é ato explícito.
    precos_habilitado: bool = False

    @property
    def jwt_emissor(self) -> str:
        return f"{self.supabase_url}/auth/v1" if self.supabase_url else ""

    @property
    def jwks_url(self) -> str:
        return f"{self.jwt_emissor}/.well-known/jwks.json" if self.jwt_emissor else ""

    @property
    def autenticacao_configurada(self) -> bool:
        return bool(self.supabase_url and self.supabase_chave_publica)

    @property
    def protegido(self) -> bool:
        return self.ambiente in AMBIENTES_PROTEGIDOS

    @property
    def expor_documentacao(self) -> bool:
        # /docs e /redoc só em desenvolvimento: a especificação versionada
        # mora em `openapi.v1.json`, e a página interativa em produção é
        # um mapa entregue a quem varre o domínio.
        return self.ambiente in ("development", "test")


def _ler(ambiente: dict[str, str], nome: str) -> str:
    return (ambiente.get(nome) or "").strip()


def _papel_de_chave_jwt(valor: str) -> str:
    """Papel DECLARADO numa chave legada em formato JWT; "" se não for JWT.

    Sem verificar assinatura: aqui só interessa recusar a `service_role`
    colada no lugar da `anon`, e o papel declarado basta para isso.
    """
    import base64
    import json

    partes = valor.split(".")
    if len(partes) != 3:
        return ""
    try:
        carga = partes[1] + "=" * (-len(partes[1]) % 4)
        return str(json.loads(base64.urlsafe_b64decode(carga)).get("role", ""))
    except Exception:  # noqa: BLE001 — chave opaca não é JWT
        return ""


def _origem_valida(origem: str, protegido: bool) -> bool:
    partes = urlsplit(origem)
    if partes.path not in ("", "/") or partes.query or partes.fragment:
        return False
    if partes.scheme == "https" and partes.hostname:
        return True
    # http só para a máquina do desenvolvedor, e só fora de staging/produção
    return (not protegido and partes.scheme == "http"
            and partes.hostname in ("localhost", "127.0.0.1"))


def carregar(ambiente: dict[str, str] | None = None) -> Configuracao:
    """Lê e valida. Levanta `ConfiguracaoInvalida` em vez de adivinhar."""
    env = dict(os.environ if ambiente is None else ambiente)

    nome_ambiente = _ler(env, "APP_ENV") or "development"
    if nome_ambiente not in AMBIENTES:
        raise ConfiguracaoInvalida(
            f"APP_ENV desconhecido; use um de {', '.join(AMBIENTES)}.")
    protegido = nome_ambiente in AMBIENTES_PROTEGIDOS

    # A API não tem modo aberto, em ambiente nenhum. A variável existe
    # para o Streamlit de desenvolvimento; ligada num deploy da API ela
    # só pode ser engano ou cópia do env antigo — e as duas coisas
    # merecem parar a subida, não ser ignoradas em silêncio.
    if protegido and _ler(env, "GOVDOCS_MODO_ABERTO").lower() in _VERDADEIRO:
        raise ConfiguracaoInvalida(
            "GOVDOCS_MODO_ABERTO ligado em ambiente protegido. A API não "
            "tem modo aberto; remova a variável.")

    supabase_url = _ler(env, "SUPABASE_URL").rstrip("/")
    if supabase_url:
        partes = urlsplit(supabase_url)
        if not partes.hostname or (protegido and partes.scheme != "https"):
            raise ConfiguracaoInvalida(
                "SUPABASE_URL inválida (staging e produção exigem https).")
    elif protegido:
        raise ConfiguracaoInvalida("SUPABASE_URL ausente.")

    origens = tuple(o.strip().rstrip("/") for o in
                    _ler(env, "GOVCONECT_CORS_ORIGINS").split(",") if o.strip())
    # Curinga com credencial é o CORS que libera o cookie da sessão para
    # qualquer site. Recusado em TODO ambiente: o hábito de desenvolvimento
    # é exatamente o que vai parar em produção.
    if "*" in origens:
        raise ConfiguracaoInvalida(
            "GOVCONECT_CORS_ORIGINS não aceita '*'; liste as origens.")
    invalidas = [o for o in origens if not _origem_valida(o, protegido)]
    if invalidas:
        raise ConfiguracaoInvalida(
            f"Origem CORS inválida: {invalidas[0]} (só esquema://host[:porta]; "
            "https em staging e produção).")

    chave_publica = _ler(env, "SUPABASE_KEY")
    if protegido and not chave_publica:
        raise ConfiguracaoInvalida("SUPABASE_KEY (chave publicável) ausente.")
    # A chave de servidor no lugar da publicável é o erro que faria a API
    # atravessar o RLS sem ninguém notar. Recusa pelo formato conhecido.
    if (chave_publica.startswith("sb_secret_")
            or _papel_de_chave_jwt(chave_publica) == "service_role"):
        raise ConfiguracaoInvalida(
            "SUPABASE_KEY recebeu a chave de servidor; use a publicável.")

    segredo = _ler(env, "SUPABASE_JWT_SECRET")
    if segredo and nome_ambiente == "production":
        raise ConfiguracaoInvalida(
            "SUPABASE_JWT_SECRET não é aceito em produção: a verificação é "
            "pelo JWKS (ES256). Remova a variável.")

    try:
        limite = int(_ler(env, "GOVCONECT_LIMITE_POR_MINUTO") or 120)
    except ValueError:
        raise ConfiguracaoInvalida(
            "GOVCONECT_LIMITE_POR_MINUTO precisa ser inteiro.") from None
    if not 1 <= limite <= 10_000:
        raise ConfiguracaoInvalida("GOVCONECT_LIMITE_POR_MINUTO fora de 1–10000.")

    return Configuracao(ambiente=nome_ambiente, supabase_url=supabase_url,
                        origens_cors=origens,
                        supabase_chave_publica=chave_publica,
                        jwt_segredo_hs256=segredo, limite_por_minuto=limite,
                        precos_habilitado=_ler(env, "PRICE_RESEARCH_ENABLED").lower()
                        in _VERDADEIRO)
