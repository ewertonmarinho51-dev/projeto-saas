"""
`st` para quem roda COM ou SEM o Streamlit.

`src/db.py` usava o Streamlit em oito pontos — `secrets`, `session_state`
e os decoradores de cache — e isso bastava para que todo módulo que toca
o banco (repositório e serviço de cotações inclusive) arrastasse o
Streamlit para dentro de qualquer processo. A API (apps/api) não pode
carregá-lo: o job `api` do CI roda sem ele instalado, de propósito.

Regra:

* no app Streamlit (o padrão), `st` É o módulo `streamlit`. Nada muda —
  inclusive os testes que trocam `db.st.session_state` continuam valendo;
* com `GOVDOCS_SEM_STREAMLIT=1` (a API liga antes de importar `src`), ou
  sem o pacote instalado, `st` é um substituto puro:
    - `session_state` vive num `ContextVar`, por requisição. Quem abre é
      `sessao_da_requisicao(token, tenant_id)`, com a identidade que a API
      JÁ VERIFICOU; fora dela o estado é vazio, e o domínio recusa como
      recusaria um Streamlit sem login (`SemSessao`);
    - `secrets` é vazio: configuração vem do ambiente (o `_segredo` de
      `db.py` já cai para `os.getenv`);
    - `cache_resource` / `cache_data` memorizam por argumentos, com `ttl`
      e `.clear()` — a mesma interface que o código e os testes usam.

Nada aqui decide autorização. Quem decide é o RLS, com o token do usuário.
"""

from __future__ import annotations

import contextvars
import functools
import os
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

SEM_STREAMLIT = os.getenv("GOVDOCS_SEM_STREAMLIT", "").strip() in ("1", "true", "on")


# ---------------------------------------------------------------------------
# Substitutos puros
# ---------------------------------------------------------------------------
_ESTADO: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "govdocs_estado_da_requisicao", default=None)


class _EstadoDaRequisicao:
    """Interface mínima de `st.session_state` sobre um ContextVar."""

    def _dados(self) -> dict:
        dados = _ESTADO.get()
        return dados if dados is not None else {}

    def get(self, chave, padrao=None):
        return self._dados().get(chave, padrao)

    def __getitem__(self, chave):
        return self._dados()[chave]

    def __setitem__(self, chave, valor):
        dados = _ESTADO.get()
        if dados is None:
            # Escrever fora de uma requisição seria estado global entre
            # usuários — exatamente o que o ContextVar existe para impedir.
            raise RuntimeError("estado de sessão fora de sessao_da_requisicao()")
        dados[chave] = valor

    def __contains__(self, chave):
        return chave in self._dados()

    def pop(self, chave, *padrao):
        return self._dados().pop(chave, *padrao)

    def setdefault(self, chave, padrao=None):
        # Fora de uma requisição devolve o padrão sem guardar: `registrar_geracao`
        # chama isto depois de a IA responder, e o registro não pode derrubar uma
        # resposta já paga nem virar estado global entre usuários.
        dados = _ESTADO.get()
        return padrao if dados is None else dados.setdefault(chave, padrao)

    def __getattr__(self, chave):
        try:
            return self._dados()[chave]
        except KeyError:
            raise AttributeError(chave) from None


def _memorizar(func=None, *, ttl=None, **_ignorado):
    """`st.cache_resource`/`st.cache_data` sem Streamlit: por argumentos,
    com validade opcional e `.clear()`. Exceção NÃO entra no cache."""
    def decorar(f):
        guardados: dict = {}
        trava = threading.Lock()
        validade = None if ttl is None else float(ttl)

        @functools.wraps(f)
        def envolvida(*args, **kwargs):
            chave = (args, tuple(sorted(kwargs.items())))
            agora = time.monotonic()
            with trava:
                achado = guardados.get(chave)
                if achado is not None and (validade is None or agora - achado[0] < validade):
                    return achado[1]
            valor = f(*args, **kwargs)
            with trava:
                guardados[chave] = (agora, valor)
            return valor

        def limpar():
            with trava:
                guardados.clear()

        envolvida.clear = limpar
        return envolvida

    return decorar(func) if callable(func) else decorar


def _para_o_log(nivel: int):
    """`st.warning`/`info`/`error` sem tela: a mensagem vai para o log da API."""
    import logging

    registro = logging.getLogger("govdocs.dominio")

    def emitir(mensagem="", *_args, **_kwargs):
        registro.log(nivel, "%s", str(mensagem)[:500])

    return emitir


_SUBSTITUTO = SimpleNamespace(
    session_state=_EstadoDaRequisicao(),
    secrets={},
    cache_resource=_memorizar,
    cache_data=_memorizar,
    warning=_para_o_log(30),
    info=_para_o_log(20),
    error=_para_o_log(40),
)

if SEM_STREAMLIT:
    st = _SUBSTITUTO
else:
    try:
        import streamlit as st  # noqa: F401 — o app de sempre
    except ImportError:  # pragma: no cover — sem o pacote, o substituto
        st = _SUBSTITUTO


def sem_streamlit() -> bool:
    """True no processo da API/worker: não há credencial de servidor."""
    return st is _SUBSTITUTO


def configurar_supabase(url: str, chave_publica: str) -> None:
    """URL do projeto e chave PUBLICÁVEL para o cliente do usuário do
    domínio (`db.cliente_do_usuario`), vindas da MESMA configuração da API.

    Sem isto, o domínio as procuraria no ambiente: com a API configurada
    por outro caminho, as duas metades divergiriam e o domínio recusaria
    toda sessão (foi o que a prova real da cesta mostrou). Só vale no
    substituto — no app, `st.secrets` é do Streamlit. Chave de servidor
    NUNCA entra aqui: a API não a tem.
    """
    if st is not _SUBSTITUTO:
        return
    if chave_publica.startswith("sb_secret_"):
        raise ValueError("chave de servidor no lugar da publicável")
    _SUBSTITUTO.secrets.update({"SUPABASE_URL": url, "SUPABASE_KEY": chave_publica})


@contextmanager
def sessao_da_requisicao(token: str, tenant_id: str, usuario: dict | None = None):
    """O `session_state` de UMA requisição da API: o token já verificado e
    o tenant que veio dele. Some ao sair, mesmo com exceção.

    `usuario` é o `st.session_state["usuario"]` do Streamlit — o vínculo
    (`auth_user_id`, `secretaria_id`, `nome`) que `contexto` e o timbrado
    leem. Só com dados JÁ verificados pela API, nunca do corpo do pedido.
    """
    from . import db  # import tardio: este módulo é importado por db

    estado = {db.CHAVE_DA_SESSAO: token, "tenant_id": tenant_id}
    if usuario is not None:
        estado["usuario"] = dict(usuario)
    marca = _ESTADO.set(estado)
    try:
        yield
    finally:
        _ESTADO.reset(marca)
