"""
Aplicar a pesquisa ao processo sem estado de tela (P04f).

`aplicacao.descartar_por_planilha` precisa descartar EXATAMENTE o que
`state.invalidar_a_partir_de("formulario")` descarta no Streamlit — senão a
API e a tela dariam ao mesmo processo cadeias documentais diferentes. A
prova roda as duas sobre o mesmo processo, em vários formatos.
"""

from __future__ import annotations

import copy

import pytest
import streamlit as st

from src import state
from src.config import CHAVE_FLUXO_MAPA, DOCUMENTOS
from src.precos import aplicacao

TEXTO = "## 1. OBJETO\n\nTexto.\n"

CENARIOS = {
    "sem documentos": ({}, {}, set()),
    "dfd e etp aprovados": ({}, {"dfd": TEXTO, "etp": TEXTO}, {"dfd", "etp"}),
    "cadeia inteira com ata": ({"srp": "Sim"},
                               {k: TEXTO for k in ("dfd", "etp", "tr", "edital", "arp")},
                               {"dfd", "etp", "tr", "edital", "arp"}),
    "fluxo com mapa de riscos": ({CHAVE_FLUXO_MAPA: True},
                                 {"dfd": TEXTO, "etp": TEXTO, "mapa_riscos": TEXTO},
                                 {"dfd", "etp"}),
    "aprovado sem texto": ({}, {"dfd": TEXTO}, {"dfd", "etp"}),
}


@pytest.mark.parametrize("nome", sorted(CENARIOS))
def test_mesma_cascata_que_o_streamlit(nome):
    dados, documentos, aprovados = CENARIOS[nome]
    dados = {"objeto": "Aquisição", **dados}

    st.session_state.clear()
    st.session_state["dados"] = copy.deepcopy(dados)
    st.session_state["documentos"] = copy.deepcopy(documentos)
    st.session_state["edicoes_pendentes"] = {}
    st.session_state["aprovados"] = set(aprovados)
    try:
        state.invalidar_a_partir_de("formulario")
        esperado_docs = dict(st.session_state["documentos"])
        esperado_aprov = sorted(st.session_state["aprovados"])
    finally:
        st.session_state.clear()

    ficam, aprov, descartados = aplicacao.descartar_por_planilha(
        dados, copy.deepcopy(documentos), sorted(aprovados))
    assert ficam == esperado_docs
    assert aprov == esperado_aprov
    assert set(descartados) == (set(documentos) | set(aprovados)) - set(ficam) - set(aprov)


def test_aplicar_ao_processo_nao_muda_a_linha_original():
    processo = {"dados": {"itens": [{"descricao": "Caneta", "unidade": "UN", "quantidade": 10,
                                     "valor_unitario": 1.0}], "valor_estimado": 10.0},
                "documentos": {"dfd": TEXTO}, "aprovados": ["dfd"]}
    original = copy.deepcopy(processo)
    pesquisa = {"id": "p", "nome": "Pesquisa", "estado": "completed", "processo_id": "proc"}
    resultado = aplicacao.aplicar_ao_processo(processo, pesquisa, [])
    assert processo == original
    assert resultado.documentos == {} and resultado.aprovados == []
    assert resultado.descartados == ["dfd"]


@pytest.mark.parametrize("estado,processo,dados,trecho", [
    ("applied", "proc", {"itens": [1]}, "já foi aplicada"),
    ("archived", "proc", {"itens": [1]}, "arquivada"),
    ("review", "proc", {"itens": [1]}, "Conclua a pesquisa"),
    ("completed", None, {"itens": [1]}, "Abra o processo"),
    ("completed", "outro", {"itens": [1]}, "outro processo"),
    ("completed", "proc", {}, "não tem planilha"),
])
def test_impedimentos(estado, processo, dados, trecho):
    pesquisa = {"estado": estado, "processo_id": "proc"}
    assert trecho in aplicacao.impedimento(pesquisa, processo, dados)


def test_pesquisa_autonoma_nao_se_aplica():
    assert "autônoma" in aplicacao.impedimento({"estado": "completed"}, "proc", {"itens": [1]})


def test_sem_impedimento():
    assert aplicacao.impedimento({"estado": "completed", "processo_id": "proc"}, "proc",
                                 {"itens": [1]}) == ""


def test_todos_os_documentos_da_sequencia_existem_no_catalogo():
    from src.config import SEQUENCIA_COM_MAPA, SEQUENCIA_DOCUMENTOS

    assert set(SEQUENCIA_COM_MAPA) | set(SEQUENCIA_DOCUMENTOS) <= set(DOCUMENTOS)
