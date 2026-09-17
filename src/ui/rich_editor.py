"""Adaptador do editor visual para o Markdown canônico do state existente."""
from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

import bleach
import streamlit as st
from markdown_it import MarkdownIt

from .. import state

MAX_DOCUMENTO = 2_000_000
_TAGS = ["p", "br", "strong", "em", "h1", "h2", "h3", "h4", "h5", "h6",
         "ul", "ol", "li", "blockquote", "hr", "pre", "code", "table", "thead",
         "tbody", "tr", "th", "td", "a", "s"]


def hash_texto(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def sanitizar_markdown(texto):
    if not isinstance(texto, str) or len(texto) > MAX_DOCUMENTO:
        raise ValueError("Conteúdo do documento inválido ou muito extenso.")
    # Markdown continua sendo texto, nunca HTML confiável. A sanitização ocorre
    # na fronteira de renderização e de colagem; reescapar o texto aqui corrompe
    # ampersands, autolinks e sucessivas aprovações sem edição.
    return texto


def html_do_markdown(texto):
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    html = md.render(texto)
    # br é a única marca HTML representável na tabela Markdown do processo.
    html = html.replace("&lt;br&gt;", "<br>").replace("&lt;br/&gt;", "<br>")
    return bleach.clean(html, tags=_TAGS,
                        attributes={"a": ["href", "title"], "ol": ["start"]},
                        protocols=["http", "https", "mailto"], strip=True)


def aceitar_evento(sessao, doc_key, evento):
    """Recusa replay e revisão antiga antes de promover o draft a pending."""
    if not isinstance(evento, Mapping):
        return None
    registro = (sessao.get("_rich_editors") or {}).get(doc_key) or {}
    if evento.get("version") != registro.get("version"):
        return None
    if evento.get("source") != hash_texto((sessao.get("documentos") or {}).get(doc_key, "")):
        return None
    seq = evento.get("sequence")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq <= registro.get("sequence", 0):
        return None
    acao = evento.get("action", "draft")
    if acao not in {"draft", "approve", "back", "regenerate"}:
        return None
    try:
        texto = sanitizar_markdown(evento.get("markdown"))
    except ValueError:
        return None
    registro["sequence"] = seq
    sessao[f"editor_{doc_key}"] = texto
    original = (sessao.get("documentos") or {}).get(doc_key)
    pendentes = sessao.setdefault("edicoes_pendentes", {})
    if texto == original:
        pendentes.pop(doc_key, None)
    else:
        pendentes[doc_key] = texto
    return acao, texto


@lru_cache(maxsize=1)
def _renderer():
    assets = Path(__file__).resolve().parents[2] / "assets" / "rich_editor"
    return st.components.v2.component(
        "govdocs_rich_editor", html='<section class="gc-rich-editor"></section>',
        js=(assets / "editor.bundle.js").read_text(encoding="utf-8"),
        css=(assets / "editor.css").read_text(encoding="utf-8"), isolate_styles=True)


def _changed(doc_key):
    # O callback roda antes do roteamento: sair pelo stepper não pode deixar
    # o último draft aguardando um editor que já saiu da tela.
    from ..operacao_documento import ocupada
    if ocupada(st.session_state):
        return
    resultado = st.session_state.get(f"rich_editor_{doc_key}")
    evento = (resultado.get("edit") if isinstance(resultado, Mapping)
              else getattr(resultado, "edit", None))
    aceito = aceitar_evento(st.session_state, doc_key, evento)
    if aceito and aceito[0] != "draft":
        st.session_state["_rich_editors"][doc_key]["action"] = aceito


def render_editor(doc_key, texto_base, *, disabled=False):
    sessao = st.session_state
    texto = sessao.get("edicoes_pendentes", {}).get(doc_key, texto_base)
    # A key editorial é a mesma que o GovBot já hidrata após patch/undo.
    texto = sessao.get(f"editor_{doc_key}", texto)
    source = hash_texto(texto_base)
    registros = sessao.setdefault("_rich_editors", {})
    registro = registros.setdefault(doc_key, {})
    if registro.get("source") != source:
        if registro.get("source") is not None:
            # Uma correção externa (por exemplo, parecer) mudou o canônico.
            # O rascunho da versão anterior não pode sobrescrever essa correção.
            texto = texto_base
            sessao.setdefault("edicoes_pendentes", {}).pop(doc_key, None)
            sessao[f"editor_{doc_key}"] = texto_base
        registro.pop("action", None)
        registro.update(version=uuid.uuid4().hex, source=source, sequence=0)
    versao = registro["version"]
    resultado = _renderer()(
        data={"doc": doc_key, "markdown": texto, "html": html_do_markdown(texto),
              "version": versao, "source": source, "sequence": registro.get("sequence", 0),
              "disabled": disabled},
        key=f"rich_editor_{doc_key}", height="content", width="stretch",
        on_edit_change=lambda: _changed(doc_key))
    evento = (resultado.get("edit") if isinstance(resultado, Mapping)
              else getattr(resultado, "edit", None))
    aceito = aceitar_evento(sessao, doc_key, evento)
    return registro.pop("action", None) or aceito or (None, texto)
