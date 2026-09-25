"""
Bloqueio de chamadas pagas de LLM, no nível da REDE — e a contagem delas.

§3 da auditoria pré-operacional: `chamadas reais às APIs de LLMs = 0`.

ONDE O BLOQUEIO MORA — E POR QUE NÃO NO DNS

A primeira versão deste arquivo interceptava `socket.getaddrinfo`, com
o raciocínio de que todo cliente HTTP passa por lá. A PROVA DE CAMINHO
REAL DERRUBOU ISSO na primeira execução: `llm.chamar_ia_texto` devolveu
um **401 vindo da OpenAI de verdade**, com `tentativas() == 0`.

A causa é o proxy. Com `HTTPS_PROXY` configurado — como neste ambiente
e em boa parte das redes corporativas —, o cliente resolve o nome DO
PROXY; o destino viaja dentro do `CONNECT`. Bloqueio por DNS não vê
nada, e a requisição sai.

Custou zero naquele caso (401 não consome tokens), mas o caminho estava
aberto: com chave válida, teria faturado. Registrado no relatório como
achado da própria ferramenta de auditoria.

O bloqueio passou para onde o DESTINO é visível — o transporte HTTP,
antes de o cliente decidir por onde sair:

    httpx.HTTPTransport.handle_request        (openai, google-genai)
    httpx.AsyncHTTPTransport.handle_async_request
    requests.adapters.HTTPAdapter.send        (google-genai, urllib)

e o guarda de DNS FICA, como segunda camada: pega o caminho direto, sem
proxy, e qualquer cliente que não use nenhuma das bibliotecas acima.

POR QUE NÃO POR MONKEYPATCH DO `llm.py`

Trocar `llm._chamar_openai` por um dublê prova que aquele caminho foi
desviado. Não prova nada sobre:

  - o fallback para o Gemini, que usa outro SDK;
  - o OpenRouter, que usa o SDK da OpenAI com outra `base_url`;
  - os EMBEDDINGS do RAG, que não passam por `llm.py`;
  - retentativas internas do próprio SDK;
  - qualquer caminho que ninguém lembrou de patchar.

A auditoria pede o oposto de "escondi as chaves": pede garantia de que
nenhuma requisição paga saia. Isso só se prova onde todas elas
convergem — a resolução de nome do host.

TODO CLIENTE HTTP PASSA POR `socket.getaddrinfo`. `openai`, `httpx`,
`requests`, `google-genai`, `urllib` — todos. Interceptar ali pega
inclusive o caminho que não existe hoje e alguém acrescentar amanhã.

O QUE **NÃO** É BLOQUEADO, E POR QUÊ

Supabase, Let's Encrypt, PyPI e o resto da internet continuam
alcançáveis. O §3 é explícito: não desativar a conectividade necessária
ao funcionamento normal. Um bloqueio total provaria "nada foi chamado"
pelo motivo errado — o app nem teria subido.

É uma LISTA DE NEGAÇÃO, e ela é a superfície auditável desta garantia:
host de LLM que não estiver aqui passa. Por isso a lista é explícita, e
por isso `tentativas()` existe — o número é a evidência, não a promessa.

USO

    import sem_llm
    sem_llm.instalar()
    ...
    assert sem_llm.tentativas() == 0

Ou, para um processo inteiro (Streamlit):

    PYTHONPATH=scripts python -c "import sem_llm; sem_llm.instalar()" ...
"""

from __future__ import annotations

import json
import os
import socket
import threading
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# A LISTA DE NEGAÇÃO
#
# Sufixos de host. Cobre os três motores que `llm.py` conhece, os
# endpoints de embedding, e os agregadores mais comuns — porque um
# `OPENAI_BASE_URL` apontado para outro lugar é exatamente o tipo de
# desvio que uma auditoria de custo precisa pegar.
# ---------------------------------------------------------------------------
HOSTS_PAGOS = (
    "api.openai.com",
    "openai.azure.com",
    "generativelanguage.googleapis.com",   # Gemini + embeddings
    "aiplatform.googleapis.com",           # Vertex
    "openrouter.ai",
    "api.anthropic.com",
    "api.cohere.ai",
    "api.mistral.ai",
    "api.together.xyz",
    "api.groq.com",
    "api.deepseek.com",
    "api.perplexity.ai",
    "huggingface.co",
    "api-inference.huggingface.co",
)

_LIVRO = Path(os.environ.get("GOVDOCS_LIVRO_SEM_LLM")
              or "/tmp/govdocs_sem_llm.jsonl")

_trava = threading.Lock()
_tentativas: list[dict] = []
_original = None


class ChamadaPagaBloqueada(RuntimeError):
    """
    Uma chamada paga foi TENTADA. É achado, não acidente.

    Levanta em vez de devolver vazio de propósito: uma chamada
    silenciosamente neutralizada faria o teste seguir e o relatório
    dizer "tudo bem", quando o que aconteceu foi o sistema tentar
    gastar dinheiro.
    """


def _e_pago(host: str) -> bool:
    alvo = (host or "").strip().lower().rstrip(".")
    return any(alvo == h or alvo.endswith("." + h) for h in HOSTS_PAGOS)


def _sem_query(caminho: str) -> str:
    """
    Só o caminho. A query string NUNCA entra — o Gemini manda a chave
    em `?key=…`, e este livro vira anexo de relatório.
    """
    return (caminho or "").split("?", 1)[0].split("#", 1)[0]


def _registrar(host: str, porta, caminho: str = "") -> None:
    evento = {
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": host,
        "porta": porta,
        # O CAMINHO, porque sem ele o livro não distingue
        # `/v1/chat/completions` de `/v1/embeddings` — e a distinção É o
        # achado: uma única geração de documento dispara as duas coisas,
        # com preços e volumes diferentes. "Duas tentativas para
        # api.openai.com" não diz qual delas cresce numa bateria
        # operacional; com o caminho, diz.
        "caminho": _sem_query(caminho),
        # NUNCA o corpo da requisição, nem cabeçalho, nem chave: este
        # livro vira anexo de relatório, e anexo de relatório vaza.
    }
    with _trava:
        _tentativas.append(evento)
        try:
            with _LIVRO.open("a", encoding="utf-8") as saida:
                saida.write(json.dumps(evento, ensure_ascii=False) + "\n")
        except OSError:
            pass  # o livro é conveniência; a contagem em memória é a prova


def _barrar(host: str, porta, caminho: str = "") -> None:
    _registrar(str(host), porta, caminho)
    raise ChamadaPagaBloqueada(
        f"CHAMADA PAGA BLOQUEADA: {host}:{porta}. Esta bateria roda com "
        "orçamento zero (§3). Use mock ou fixture — e registre o caminho "
        "que tentou sair, porque ele é o que gastaria dinheiro na rodada "
        "operacional."
    )


_originais: dict = {}


# Marca no próprio substituto. Ver o comentário gêmeo em
# `ia_simulada`: identificar a instalação por um registro paralelo
# permite que o registro e o efeito divirjam, e foi assim que a
# interceptação sumiu na CI sem ninguém notar.
_MARCA = "_govdocs_sem_llm"


def ativo() -> bool:
    """O bloqueio está de pé NESTE processo, agora?"""
    if getattr(socket.getaddrinfo, _MARCA, False):
        return True
    try:
        import httpx
    except ImportError:
        return False
    return bool(getattr(httpx.HTTPTransport.handle_request, _MARCA, False))


def instalar() -> None:
    """Idempotente: chamar duas vezes não empilha dois interceptadores."""
    global _original
    if _original is not None or ativo():
        return

    # --- camada 1: o TRANSPORTE HTTP, onde o destino é visível -------
    # É esta que pega o tráfego por proxy — a que faltava.
    try:
        import httpx

        _originais["httpx"] = httpx.HTTPTransport.handle_request
        _originais["httpx_async"] = (
            httpx.AsyncHTTPTransport.handle_async_request)

        def httpx_guardado(self, request):
            if _e_pago(request.url.host):
                _barrar(request.url.host, request.url.port or 443,
                        request.url.path)
            return _originais["httpx"](self, request)

        async def httpx_guardado_async(self, request):
            if _e_pago(request.url.host):
                _barrar(request.url.host, request.url.port or 443,
                        request.url.path)
            return await _originais["httpx_async"](self, request)

        setattr(httpx_guardado, _MARCA, True)
        setattr(httpx_guardado_async, _MARCA, True)
        httpx.HTTPTransport.handle_request = httpx_guardado
        httpx.AsyncHTTPTransport.handle_async_request = httpx_guardado_async
    except ImportError:
        pass

    try:
        from requests import adapters

        _originais["requests"] = adapters.HTTPAdapter.send

        def requests_guardado(self, request, *args, **kwargs):
            from urllib.parse import urlparse

            alvo = urlparse(request.url)
            if _e_pago(alvo.hostname or ""):
                _barrar(alvo.hostname, alvo.port or 443, alvo.path)
            return _originais["requests"](self, request, *args, **kwargs)

        setattr(requests_guardado, _MARCA, True)
        adapters.HTTPAdapter.send = requests_guardado
    except ImportError:
        pass

    # --- camada 2: o DNS, para o caminho direto sem proxy -------------
    _original = socket.getaddrinfo

    def guardado(host, porta, *args, **kwargs):
        if _e_pago(str(host)):
            _barrar(str(host), porta)
        return _original(host, porta, *args, **kwargs)

    setattr(guardado, _MARCA, True)
    socket.getaddrinfo = guardado


def remover() -> None:
    global _original
    if _original is not None:
        socket.getaddrinfo = _original
        _original = None
    if "httpx" in _originais:
        import httpx

        httpx.HTTPTransport.handle_request = _originais.pop("httpx")
        httpx.AsyncHTTPTransport.handle_async_request = _originais.pop(
            "httpx_async")
    if "requests" in _originais:
        from requests import adapters

        adapters.HTTPAdapter.send = _originais.pop("requests")


def tentativas() -> int:
    """Quantas chamadas pagas foram TENTADAS. O critério do §3 é zero."""
    with _trava:
        return len(_tentativas)


def relatorio() -> list[dict]:
    with _trava:
        return list(_tentativas)


def zerar() -> None:
    with _trava:
        _tentativas.clear()
