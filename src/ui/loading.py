"""Progresso acessível por estágios reais, sem percentuais simulados."""
from functools import lru_cache
from pathlib import Path
import uuid
import streamlit as st

ROTULOS = {
    "PREPARANDO": "Preparando as informações",
    "GERANDO": "Elaborando o documento",
    "REVISANDO": "Revisando o documento",
    "FINALIZANDO": "Finalizando",
    "PRONTO": "Documento pronto",
    "ERRO": "Não foi possível concluir o documento. Seu trabalho anterior foi preservado.",
}


@lru_cache(maxsize=1)
def _componente():
    raiz = Path(__file__).resolve().parents[2] / "assets" / "loading"
    return st.components.v2.component(
        "govdocs_loading", html='<div class="gc-loading-root"></div>',
        css=(raiz / "loading.css").read_text(encoding="utf-8"),
        js=(raiz / "loading.js").read_text(encoding="utf-8"), isolate_styles=False)


def render(titulo, etapa, *, ativo=True):
    return _componente()(data={"titulo": titulo, "etapa": etapa,
                              "rotulo": ROTULOS[etapa], "ativo": ativo},
                         key=f"gc_generation_progress_{uuid.uuid4().hex}", height=0)
