"""Painel contextual único do editor nativo.

A interface só apresenta fatos produzidos pelos owners. Preparar, confirmar,
descartar, restaurar e consultar continuam sendo ações do chamador autenticado.
"""
from __future__ import annotations

from ..wordcraft_capacidades import painel_unico


def modelo(*, preparacao=None, auditoria_atual=None, pareceres_atuais=None,
           atendimentos_parecer=None,
           evidencias=(), template=None, institucional=None, montagem=None,
           historico=()) -> dict:
    base = painel_unico()
    auditoria = preparacao.auditoria() if preparacao is not None else None
    return {**base,
            "preparacao": ({"operation_id": preparacao.operation_id,
                            "plan_hash": preparacao.plan_hash,
                            "source_bundle_hash": preparacao.source_bundle_hash,
                            "target_bundle_hash": preparacao.target_bundle_hash,
                            "documentos": [r.fonte.doc_key for r in preparacao.resultados],
                            "auditoria": auditoria}
                           if preparacao is not None else None),
            "auditoria_atual": auditoria_atual,
            "pareceres_atuais": pareceres_atuais,
            "atendimentos_parecer": atendimentos_parecer,
            "evidencias": list(evidencias),
            "template": template,
            "institucional": institucional,
            "montagem": montagem,
            "historico": list(historico)}


def renderizar(modelo_painel: dict) -> None:
    """Renderiza as cinco abas sem adquirir poder de mutação."""
    import streamlit as st

    st.subheader("Assistência contextual")
    govbot, auditoria, parecer, evidencias, historico = st.tabs(modelo_painel["abas"])
    preparacao = modelo_painel.get("preparacao")
    with govbot:
        st.caption("Sugestões agem sobre a seleção ou finding auditado e exigem diff e confirmação.")
        if preparacao:
            st.code(preparacao["operation_id"])
            st.json(preparacao["auditoria"]["diff"], expanded=False)
        else:
            st.info("Nenhuma proposta contextual preparada para esta revisão.")
    with auditoria:
        if preparacao:
            antes, depois = preparacao["auditoria"]["reports"]
            st.metric("Achados antes", len(antes["findings"]))
            st.metric("Achados depois", len(depois["findings"]))
            st.caption("Plano " + preparacao["plan_hash"])
        elif modelo_painel.get("auditoria_atual"):
            report = modelo_painel["auditoria_atual"]["report"]
            st.metric("Achados atuais", len(report["findings"]))
            for finding in report["findings"]:
                st.json(finding, expanded=False)
        else:
            st.info("A auditoria contextual será executada pelo owner ao preparar uma proposta.")
        if modelo_painel.get("template"):
            st.caption("Template institucional congelado")
            st.json(modelo_painel["template"], expanded=False)
        if modelo_painel.get("institucional"):
            st.caption("Identidade, portaria e signatários da revisão")
            st.json(modelo_painel["institucional"], expanded=False)
        if modelo_painel.get("montagem"):
            st.caption("Montagem determinística")
            st.json(modelo_painel["montagem"], expanded=False)
    with parecer:
        pendencias = (preparacao or {}).get("auditoria", {}).get("plan", {}).get(
            "unresolvedFindings", [])
        if pendencias:
            st.json(pendencias, expanded=False)
        elif modelo_painel.get("pareceres_atuais"):
            current = modelo_painel["pareceres_atuais"]
            st.metric("Pareceres vinculados", len(current["pareceres"]))
            st.metric("Apontamentos", len(current["findings"]))
            for finding in current["findings"]:
                st.json(finding, expanded=False)
        else:
            st.info("Nenhuma pendência de parecer vinculada à proposta atual.")
        attendance = modelo_painel.get("atendimentos_parecer")
        if attendance:
            st.caption("Atendimentos persistidos na trilha imutável de revisões")
            for report in attendance["reports"]:
                st.json(report, expanded=False)
    with evidencias:
        if modelo_painel["evidencias"]:
            for item in modelo_painel["evidencias"]:
                st.json(item, expanded=False)
        else:
            st.info("Nenhuma evidência foi verificada para a proposta atual.")
    with historico:
        for item in modelo_painel["historico"]:
            st.json(item, expanded=False)
        if not modelo_painel["historico"]:
            st.info("Nenhuma revisão histórica carregada no painel.")
