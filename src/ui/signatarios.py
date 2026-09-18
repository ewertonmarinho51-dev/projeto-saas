"""
Seleção de signatários — tipo primeiro, depois só quem pode.

A ORDEM DOS DOIS CAMPOS É A FUNCIONALIDADE

Primeiro o usuário escolhe O TIPO de signatário (§29); só então o sistema
mostra os servidores elegíveis (§30). Invertido — uma lista de servidores
e um campo de função ao lado — o sistema viraria um formulário onde
alguém digita que o Antonio é pregoeiro, e a designação passaria a ser
uma afirmação do operador em vez de um ato administrativo.

Com a ordem certa, a lista de "Equipe de Planejamento" tem exatamente os
membros da portaria vigente. Se a portaria não existe, a lista é vazia e
a tela DIZ por quê — em vez de oferecer cinquenta servidores do município
para uma assinatura que exige designação formal (§31).

TUDO ATRÁS DA FLAG, e o rascunho é reversível: a escolha vive em
`processos.dados` até a aprovação. É lá que ela vira snapshot (§35).
"""

from __future__ import annotations

import datetime as _dt

import streamlit as st

from .. import (assinaturas, contexto, db, emissao, instituicional_bridge,
                portarias)


def render(doc_key: str) -> None:
    """Bloco de assinaturas do documento em edição. Nunca levanta."""
    try:
        if not instituicional_bridge.ativo():
            return
        _render(doc_key)
    except db.ErroBanco as erro:
        # Sem as tabelas da 0025 a seleção não existe, e o documento
        # continua sendo aprovado pelo caminho legado. Avisar é melhor
        # que sumir: o administrador precisa saber que o bloco de
        # assinatura não vai sair.
        st.info(f"Seleção de signatários indisponível: {erro}")


def _render(doc_key: str) -> None:
    escolhas = instituicional_bridge.escolhas_da_sessao(doc_key)
    institucional = contexto.contexto_institucional()
    secretaria_id = institucional.get("secretaria_id")

    referencia = emissao.data_de_referencia(
        {"criado_em": st.session_state.get("processo_criado_em")})

    servidores = db.listar_servidores()
    portaria, aviso = _portaria_vigente(secretaria_id, referencia)

    with st.expander(
            f"Assinaturas do documento ({len(escolhas)})",
            expanded=bool(escolhas)):
        st.caption(
            "Quem assina é escolhido pela FUNÇÃO. O sistema mostra apenas "
            "servidores com essa designação vigente nesta secretaria, na "
            "data do processo — não a lista inteira do município."
        )

        if aviso:
            st.error(aviso)
        elif portaria:
            st.caption(f"Equipe de Planejamento: {portarias.citacao(portaria)}")

        _render_escolhidos(doc_key, escolhas, servidores)
        st.divider()
        _render_adicionar(doc_key, escolhas, servidores, portaria,
                          secretaria_id, referencia)


def _portaria_vigente(secretaria_id: str | None,
                      referencia: _dt.date) -> tuple[dict | None, str]:
    """
    A portaria e, se houver problema, a frase que o operador precisa ler.

    Conflito não é resolvido aqui — nem por data, nem por número. O
    documento sai sem a citação e o painel administrativo é onde isso se
    conserta.
    """
    try:
        acervo = db.listar_portarias(secretaria_id=secretaria_id)
    except db.ErroBanco as erro:
        return None, str(erro)
    try:
        return portarias.resolver(acervo, secretaria_id=secretaria_id,
                                  data_referencia=referencia), ""
    except portarias.PortariaAmbigua as erro:
        return None, str(erro)
    except portarias.ErroPortaria as erro:
        return None, f"Portaria com data ilegível: {erro}"


def _render_escolhidos(doc_key: str, escolhas: list[dict],
                       servidores: list[dict]) -> None:
    if not escolhas:
        st.caption("Nenhum signatário selecionado. O documento sairá sem "
                   "bloco de assinatura.")
        return

    nomes = {s["id"]: s["nome"] for s in servidores}
    for indice, escolha in enumerate(escolhas):
        col_nome, col_sobe, col_remove = st.columns([6, 1, 1])
        nome = nomes.get(escolha.get("servidor_id"))
        rotulo = assinaturas.ROTULOS.get(escolha.get("funcao"),
                                         escolha.get("funcao") or "")
        if nome:
            col_nome.write(f"**{indice + 1}.** {nome} — {rotulo}")
        else:
            # O servidor saiu do cadastro depois de escolhido. A tela
            # mostra o problema; o congelamento descarta a linha em vez
            # de imprimir assinatura sem nome.
            col_nome.warning(
                f"**{indice + 1}.** servidor removido do cadastro — {rotulo}")

        if indice > 0 and col_sobe.button(
                "↑", key=f"sobe_{doc_key}_{indice}",
                help="Subir na ordem do documento"):
            escolhas[indice - 1], escolhas[indice] = (escolhas[indice],
                                                      escolhas[indice - 1])
            instituicional_bridge.guardar_escolhas(doc_key, escolhas)
            st.rerun()

        if col_remove.button("✕", key=f"remove_{doc_key}_{indice}",
                             help="Remover signatário"):
            escolhas.pop(indice)
            instituicional_bridge.guardar_escolhas(doc_key, escolhas)
            st.rerun()


def _render_adicionar(doc_key: str, escolhas: list[dict],
                      servidores: list[dict], portaria: dict | None,
                      secretaria_id: str | None,
                      referencia: _dt.date) -> None:
    col_tipo, col_pessoa, col_botao = st.columns([3, 3, 1])

    # §29 — o TIPO primeiro. Ver o cabeçalho do módulo.
    funcao = col_tipo.selectbox(
        "Tipo de signatário", assinaturas.TIPOS_DE_SIGNATARIO,
        format_func=lambda f: assinaturas.ROTULOS.get(f, f),
        key=f"tipo_sig_{doc_key}")

    try:
        funcoes_do_servidor = db.listar_funcoes_de_servidores(secretaria_id)
        membros = (db.listar_membros_de_portaria(portaria["id"])
                   if portaria else [])
    except db.ErroBanco as erro:
        st.error(str(erro))
        return

    elegiveis = assinaturas.elegiveis(
        funcao=funcao, servidores=servidores,
        funcoes_do_servidor=funcoes_do_servidor, portaria=portaria,
        membros_da_portaria=membros, secretaria_id=secretaria_id,
        data_referencia=referencia)

    ja_escolhidos = {(e.get("servidor_id"), e.get("funcao")) for e in escolhas}
    disponiveis = [s for s in elegiveis
                   if (s["id"], funcao) not in ja_escolhidos]

    if not disponiveis:
        col_pessoa.caption(_por_que_vazio(funcao, elegiveis, portaria))
        return

    nomes = {s["id"]: s["nome"] for s in disponiveis}
    servidor_id = col_pessoa.selectbox(
        "Servidor", list(nomes), format_func=lambda i: nomes[i],
        key=f"pessoa_sig_{doc_key}")

    if col_botao.button("Adicionar", key=f"add_sig_{doc_key}",
                        use_container_width=True):
        # Reconfere no momento de gravar: entre montar a lista e o
        # clique, a portaria pode ter sido revogada.
        try:
            assinaturas.conferir_elegibilidade(
                servidor_id=servidor_id, funcao=funcao,
                elegiveis_agora=elegiveis)
        except assinaturas.ErroAssinatura as erro:
            st.error(str(erro))
            return
        escolhas.append({"servidor_id": servidor_id, "funcao": funcao})
        instituicional_bridge.guardar_escolhas(doc_key, escolhas)
        st.rerun()


def _por_que_vazio(funcao: str, elegiveis: list[dict],
                   portaria: dict | None) -> str:
    """
    A lista vazia precisa dizer o motivo.

    "Nenhum servidor disponível" manda o operador procurar defeito no
    lugar errado. Cada causa aqui leva a uma ação diferente: cadastrar
    portaria, designar função, ou simplesmente perceber que todos já
    foram adicionados.
    """
    if elegiveis:
        return "Todos os elegíveis já foram adicionados."
    if funcao in assinaturas.FUNCOES_DE_PORTARIA:
        if not portaria:
            return ("Esta secretaria não tem Portaria de Equipe de "
                    "Planejamento vigente na data do processo. Cadastre-a "
                    "em Administração → Instituição → Portarias.")
        return ("A portaria vigente não tem membros com esta função. "
                "Designe-os em Administração → Instituição → Portarias.")
    return ("Nenhum servidor tem esta designação vigente nesta secretaria. "
            "Cadastre a função em Administração → Instituição.")
