"""
Gerenciamento de estado do wizard (st.session_state).

O Streamlit reexecuta o script a cada interação; tudo que precisa
sobreviver entre os passos (dados do formulário, documentos gerados,
aprovações) vive em st.session_state, inicializado aqui.
"""

import streamlit as st

from . import db
from .config import SEQUENCIA_DOCUMENTOS


def inicializar() -> None:
    """Garante que todas as chaves de estado existam antes do 1º render."""
    padroes = {
        "etapa": 0,            # 0=formulário | 1..4=documentos | 5=sucesso
        "dados": {},           # respostas do Formulário Matriz
        "documentos": {},      # doc_key -> texto gerado/editado
        "aprovados": set(),    # doc_keys aprovados pelo usuário
        "processo_id": None,   # uuid do processo no Supabase (None = não salvo)
        "usuario": None,       # {id, nome, login, papel} após o login
        "modo_demo": False,
        "api_key_manual": "",
        "openai_key_manual": "",
    }
    for chave, valor in padroes.items():
        if chave not in st.session_state:
            st.session_state[chave] = valor


def autosalvar() -> None:
    """
    Salva o processo no Supabase (se configurado). Falhas de banco nunca
    interrompem o fluxo do wizard — viram apenas um aviso na tela.
    """
    if not db.disponivel() or not st.session_state.dados:
        return
    try:
        usuario = st.session_state.get("usuario") or {}
        st.session_state.processo_id = db.salvar_processo(
            st.session_state.processo_id,
            st.session_state.dados,
            st.session_state.documentos,
            st.session_state.aprovados,
            st.session_state.etapa,
            usuario_id=usuario.get("id"),
        )
    except db.ErroBanco as erro:
        st.warning(f"Progresso não salvo no banco: {erro}")


def carregar_processo_salvo(proc: dict) -> None:
    """Restaura um processo salvo no Supabase para a sessão atual."""
    st.session_state.processo_id = proc["id"]
    st.session_state.dados = proc.get("dados") or {}
    st.session_state.documentos = proc.get("documentos") or {}
    st.session_state.aprovados = set(proc.get("aprovados") or [])
    ir_para(int(proc.get("etapa") or 0))


def ir_para(etapa: int) -> None:
    st.session_state.etapa = etapa
    st.rerun()


def doc_da_etapa(etapa: int) -> str:
    """Etapas 1..4 correspondem a dfd, etp, tr, edital."""
    return SEQUENCIA_DOCUMENTOS[etapa - 1]


def aprovar_e_avancar(doc_key: str, texto_editado: str) -> None:
    """Salva a versão editada pelo usuário, marca como aprovado e avança."""
    st.session_state.documentos[doc_key] = texto_editado
    st.session_state.aprovados.add(doc_key)
    st.session_state.etapa += 1
    autosalvar()  # persiste cada avanço no Supabase (quando configurado)
    st.rerun()


def descartar_documento(doc_key: str) -> None:
    """Remove o documento gerado (usado no 'Gerar novamente')."""
    st.session_state.documentos.pop(doc_key, None)
    st.session_state.aprovados.discard(doc_key)


def invalidar_a_partir_de(doc_key: str) -> None:
    """
    Ao voltar e alterar um documento (ou o formulário), os documentos
    seguintes ficam desatualizados — remove-os para forçar nova geração.
    """
    if doc_key == "formulario":
        posteriores = SEQUENCIA_DOCUMENTOS
    else:
        idx = SEQUENCIA_DOCUMENTOS.index(doc_key)
        posteriores = SEQUENCIA_DOCUMENTOS[idx + 1 :]
    for chave in posteriores:
        descartar_documento(chave)


def reiniciar_processo() -> None:
    """Limpa tudo e volta ao Formulário Matriz (novo processo no banco)."""
    for chave in ("dados", "documentos"):
        st.session_state[chave] = {}
    st.session_state.aprovados = set()
    st.session_state.processo_id = None
    ir_para(0)
