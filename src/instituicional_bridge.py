"""
A ponte entre a sessão e o congelamento — e ela existe para ser fina.

`src/emissao.py` é lógica pura: recebe listas e devolve snapshots, sem
saber que Streamlit ou Supabase existem. `src/state.py` é a sessão. Este
módulo é o único lugar que conhece os dois, e ele faz uma coisa só: ler o
que a sessão sabe, pedir ao banco o que falta, e chamar `emissao`.

POR QUE NÃO PÔR ISSO DENTRO DE `state.py`

Porque `aprovar_e_avancar` é o caminho crítico do produto — é o botão que
o servidor aperta — e ele já carrega manutenção, aprendizado, autosave e
navegação. Acrescentar ali a leitura de quatro tabelas faria a função que
mais importa do sistema crescer em uma direção que não é a dela.

TUDO ATRÁS DA FLAG. Com `flag_multi_prefeituras` desligada — o padrão —
este módulo não consulta nada e o documento sai pelo caminho legado
(§58). Processo antigo, sem snapshot, continua funcionando igual.
"""

from __future__ import annotations

import logging

import streamlit as st

from . import emissao

_log = logging.getLogger("govdocs.instituicional")


def ativo() -> bool:
    from . import db
    from .ui import instituicional

    return db.flag_ativa(instituicional.FLAG_MULTI_PREFEITURAS)


def escolhas_da_sessao(doc_key: str) -> list[dict]:
    """
    Os signatários que o usuário marcou para ESTE documento.

    Enquanto o documento é rascunho a escolha vive em
    `processos.dados[CHAVE_ESCOLHA]`, junto do resto do processo — pelo
    mesmo motivo que a consolidação de demanda mora lá: é dado DO
    processo, e uma tabela separada criaria um segundo lugar onde a mesma
    coisa vive.
    """
    dados = st.session_state.get("dados") or {}
    por_documento = dados.get(emissao.CHAVE_ESCOLHA) or {}
    escolhas = por_documento.get(doc_key) or []
    return [e for e in escolhas if isinstance(e, dict)]


def guardar_escolhas(doc_key: str, escolhas: list[dict]) -> None:
    """Grava a escolha do rascunho. O autosave do processo persiste."""
    dados = st.session_state.setdefault("dados", {})
    dados.setdefault(emissao.CHAVE_ESCOLHA, {})[doc_key] = escolhas


def congelar_na_aprovacao(doc_key: str) -> bool:
    """
    Chamada por `state.aprovar_e_avancar`. Nunca levanta.

    Devolve se congelou — hoje ninguém usa o retorno no fluxo, e ele
    existe para o teste poder medir a diferença entre "não fez porque a
    flag está desligada" e "tentou e falhou". As duas viram `False`, e a
    segunda deixa log; distingui-las no retorno seria precisão que o
    chamador não usa.
    """
    try:
        if not ativo():
            return False
        return _congelar(doc_key)
    except Exception as erro:  # noqa: BLE001 — aprovação não para
        _log.warning("congelamento pulado em %s: %s", doc_key, erro)
        return False


def _congelar(doc_key: str) -> bool:
    from . import contexto, db, portarias

    processo_id = st.session_state.get("processo_id")
    if not processo_id:
        return False

    escolhas = escolhas_da_sessao(doc_key)
    institucional = contexto.contexto_institucional()
    secretaria_id = institucional.get("secretaria_id")

    secretarias = db.listar_secretarias()
    identidade, origem = contexto.resolver_identidade(secretarias, secretaria_id)
    nome_da_secretaria = next(
        (s.get("nome") for s in secretarias if s.get("id") == secretaria_id),
        None)

    # A data de referência é a CRIAÇÃO do processo, não hoje. Ver
    # `emissao.data_de_referencia`.
    processo = {"criado_em": st.session_state.get("processo_criado_em")}
    referencia = emissao.data_de_referencia(processo)

    portaria = None
    try:
        portaria = portarias.resolver(
            db.listar_portarias(secretaria_id=secretaria_id),
            secretaria_id=secretaria_id,
            data_referencia=referencia)
    except portarias.ErroPortaria as erro:
        # Conflito de portarias NÃO é resolvido por arbítrio aqui: o
        # documento sai sem o número, e o painel administrativo é onde
        # isso se conserta. Ver `src/portarias.py`.
        _log.warning("portaria não resolvida para %s: %s", doc_key, erro)

    def gravar(linha_identidade: dict, linhas_signatarios: list[dict]) -> None:
        db.gravar_identidade_do_documento(processo_id, doc_key,
                                          linha_identidade)
        db.gravar_signatarios(processo_id, doc_key, linhas_signatarios)

    return emissao.congelar(
        processo_id, doc_key, escolhas=escolhas,
        servidores=db.listar_servidores(), secretaria_id=secretaria_id,
        secretaria_nome=nome_da_secretaria, portaria=portaria,
        identidade=identidade, origem=origem, gravar=gravar)


def bloco_para_exportacao(doc_key: str) -> str:
    """
    O bloco de assinatura do documento — lido SÓ do snapshot.

    Devolve string vazia quando não há snapshot, e é assim que processo
    antigo continua exportando como sempre exportou. Nunca consulta o
    cadastro vivo: é essa a promessa que o snapshot existe para cumprir.
    """
    try:
        if not ativo():
            return ""
        from . import db

        processo_id = st.session_state.get("processo_id")
        if not processo_id:
            return ""
        return emissao.bloco_de_assinaturas(
            db.signatarios_do_documento(processo_id, doc_key))
    except Exception as erro:  # noqa: BLE001 — exportar não pode quebrar
        _log.warning("bloco de assinatura indisponível em %s: %s",
                     doc_key, erro)
        return ""
