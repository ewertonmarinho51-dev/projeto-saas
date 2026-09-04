"""Fronteira de apresentação do GovBot em Streamlit Components v2.

O markup, o estilo e o JavaScript são ativos locais e imutáveis. Dados da
sessão entram exclusivamente pelo parâmetro ``data`` do componente; o
frontend os insere em nós de texto e devolve um único trigger ``event``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import streamlit as st


_ROOT = Path(__file__).resolve().parents[2]
_ASSET_DIR = _ROOT / "assets" / "govbot"
_MASCOT_MARKER = "<!-- GOVBOT_MASCOT -->"
_COMPONENT_NAME = "govdocs_govbot"


def _asset_text(name: str) -> str:
    """Lê um ativo confiável e versionado do próprio projeto."""
    return (_ASSET_DIR / name).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _component_assets() -> tuple[str, str, str]:
    html_source = _asset_text("govbot.html")
    if _MASCOT_MARKER not in html_source:
        raise RuntimeError("marcador do mascote ausente em govbot.html")
    html_source = html_source.replace(
        _MASCOT_MARKER,
        _asset_text("mascot.svg"),
        1,
    )
    return html_source, _asset_text("govbot.css"), _asset_text("govbot.js")


@lru_cache(maxsize=1)
def _component_renderer():
    """Registra uma única definição v2, reutilizada por todas as montagens."""
    html_source, css_source, js_source = _component_assets()
    return st.components.v2.component(
        _COMPONENT_NAME,
        html=html_source,
        css=css_source,
        js=js_source,
        isolate_styles=True,
    )


def _ignore_event_change() -> None:
    """Callback vazio necessário para expor o trigger no resultado tipado."""


def _json_serializable_data(data: dict[str, Any]) -> dict[str, Any]:
    """Falha cedo se a view-model tentar atravessar a fronteira com objetos."""
    try:
        json.dumps(data, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise TypeError("data do GovBot deve ser serializável em JSON") from error
    return data


def _event_from_result(result: Any) -> dict[str, Any] | None:
    if result is None:
        return None
    event = getattr(result, "event", None)
    if event is None and isinstance(result, Mapping):
        event = result.get("event")
    if not isinstance(event, Mapping):
        return None
    return dict(event)


def render_govbot(data: dict, key: str = "govbot") -> dict | None:
    """Monta o painel e devolve somente o trigger transitório ``event``.

    A validação de allowlists, IDs e alvos continua no orquestrador Python;
    esta função limita-se a garantir uma view-model JSON e a não transformar
    estado persistente do componente em ação.
    """
    if not isinstance(data, dict):
        raise TypeError("data do GovBot deve ser um dicionário")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("key do GovBot deve ser uma string não vazia")

    result = _component_renderer()(
        data=_json_serializable_data(data),
        key=key,
        width="content",
        height="content",
        on_event_change=_ignore_event_change,
    )
    return _event_from_result(result)


__all__ = ["render_govbot"]
