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
from dataclasses import dataclass
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

    return Configuracao(ambiente=nome_ambiente, supabase_url=supabase_url,
                        origens_cors=origens)
