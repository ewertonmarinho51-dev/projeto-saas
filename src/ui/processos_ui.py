"""
Painel de controle de processos.

Substitui o expander "Processos salvos" da barra lateral, que era um
`selectbox` rotulado por data, órgão e objeto — dava para retomar um
processo, não para SABER em que pé ele está.

O que a tela mostra por linha: nome (editável na própria lista), quando
foi criado e alterado, status, etapa atual e progresso. Nenhum desses
quatro últimos vem de coluna: todos são derivados em `src/processos.py`,
das mesmas `etapa`, `documentos` e `aprovados` que o wizard usa para
navegar. Ver o comentário da migração 0022 sobre por que não são
colunas.
"""

from __future__ import annotations

import streamlit as st

from .. import auth, db, processos, state
from . import components

# Chaves de sessão. Prefixadas para não colidir com os widgets do
# formulário matriz, que vivem no mesmo `st.session_state`.
BUSCA = "processos_busca"
ORDEM = "processos_ordem"
RENOMEANDO = "processos_renomeando"
EXCLUINDO = "processos_excluindo"

ORDENACOES = {
    "Alteração mais recente": "atualizado_em",
    "Criação mais recente": "criado_em",
    "Status": "status",
}

# Cor da tarja de status. `st.badge` aceita um conjunto fechado de cores;
# o mapa deixa a escolha explícita em vez de espalhada pelo laço.
COR_DO_STATUS = {
    processos.EM_ELABORACAO: "blue",
    processos.AGUARDANDO_PRECOS: "orange",
    processos.EM_REVISAO: "violet",
    processos.CONCLUIDO: "green",
    processos.ARQUIVADO: "gray",
}


def render_processos() -> None:
    """Tela inteira do painel."""
    components.render_page_header(
        "Processos",
        "Todos os seus processos de contratação, com o andamento de cada um.",
    )

    if not db.disponivel():
        st.info(
            "Os processos são salvos no banco de dados, que não está "
            "configurado neste ambiente. O processo aberto agora continua "
            "funcionando normalmente nesta sessão."
        )
        return

    usuario = auth.usuario_logado()
    # Administrador vê os processos do município; servidor vê os seus.
    # É a mesma regra do expander anterior — o painel não amplia acesso.
    filtro = None if auth.eh_admin() else (usuario or {}).get("id")
    try:
        lista = db.listar_processos(usuario_id=filtro)
    except db.ErroBanco as erro:
        st.warning(str(erro))
        return

    if not lista:
        st.info(
            "Nenhum processo salvo ainda. Comece pela aba **Novo processo** — "
            "o andamento é salvo sozinho a cada etapa aprovada."
        )
        return

    _render_filtros()
    visiveis = processos.ordenar(
        processos.filtrar(lista, st.session_state.get(BUSCA, "")),
        ORDENACOES.get(st.session_state.get(ORDEM, ""), "atualizado_em"),
    )

    if not visiveis:
        st.caption(
            f"Nenhum processo encontrado para "
            f"“{st.session_state.get(BUSCA, '')}”."
        )
        return

    st.caption(
        f"{len(visiveis)} de {len(lista)} processo(s)"
        if len(visiveis) != len(lista) else f"{len(lista)} processo(s)"
    )
    # Aviso ÚNICO, no topo, e não um por linha: a causa é uma só, e
    # repeti-la em cada processo transformaria a explicação em ruído.
    if not db.coluna_nome_disponivel():
        st.info(
            "**Renomear está indisponível** enquanto a migração 0022 não "
            "for aplicada ao banco. Até lá cada processo aparece pelo órgão "
            "e pelo objeto; o andamento e o *Continuar de onde parei* "
            "funcionam normalmente."
        )
    for processo in visiveis:
        _render_linha(processo)


def _render_filtros() -> None:
    coluna_busca, coluna_ordem = st.columns([3, 2])
    coluna_busca.text_input(
        "Buscar",
        key=BUSCA,
        placeholder="Nome, órgão ou objeto…",
        help="Não precisa acertar os acentos nem as maiúsculas.",
    )
    coluna_ordem.selectbox("Ordenar por", list(ORDENACOES), key=ORDEM)


def _render_linha(processo: dict) -> None:
    """Uma linha do painel: identidade, andamento e ações."""
    resumo = processos.resumo(processo)
    processo_id = resumo["id"]
    aberto = st.session_state.get("processo_id") == processo_id

    with st.container(border=True):
        if st.session_state.get(RENOMEANDO) == processo_id:
            _render_edicao_do_nome(resumo)
        else:
            _render_cabecalho_da_linha(resumo, aberto)

        feitos, total = resumo["progresso"]
        # O número vai em TEXTO além da barra. A barra sozinha comunica
        # "mais ou menos por aí" — quem precisa saber se faltam um ou
        # três documentos não tem como ler isso de um preenchimento. E
        # leitor de tela não anuncia largura de barra.
        st.progress(resumo["progresso_fracao"])
        st.caption(f"**{feitos} de {total}** documentos concluídos")

        coluna_etapa, coluna_datas = st.columns([2, 3])
        coluna_etapa.markdown(f"**Etapa atual:** {resumo['etapa']}")
        coluna_datas.caption(
            f"Criado em {resumo['criado_em']} · "
            f"Última alteração em {resumo['atualizado_em']}"
        )

        _render_acoes(resumo, aberto)


def _render_cabecalho_da_linha(resumo: dict, aberto: bool) -> None:
    coluna_nome, coluna_status = st.columns([4, 2])
    titulo = resumo["nome"]
    if aberto:
        # Quem está com o processo aberto precisa reconhecê-lo na lista
        # sem cruzar identificadores.
        titulo += "  ·  *aberto agora*"
    coluna_nome.markdown(f"#### {titulo}")
    with coluna_status:
        st.badge(resumo["status"],
                 color=COR_DO_STATUS.get(resumo["status"], "gray"))
    if not resumo["nome_proprio"] and db.coluna_nome_disponivel():
        # Sem nome próprio, o título acima já é "órgão — objeto"; repetir
        # os dois embaixo seria ruído. A dica diz o que fazer a respeito.
        #
        # Ela cala junto com o botão. Na queda sem a coluna, NENHUMA linha
        # tem nome próprio — a coluna nem veio na consulta —, então a dica
        # apareceria em todas, apontando uma vez por processo para um
        # controle que a própria tela acabou de esconder.
        coluna_nome.caption("Sem nome. Use **Renomear** para dar um.")


def _render_edicao_do_nome(resumo: dict) -> None:
    """Edição inline do nome, com o rascunho isolado por processo."""
    chave = f"processos_nome_{resumo['id']}"
    st.text_input(
        "Nome do processo",
        value=resumo["nome_proprio"],
        key=chave,
        max_chars=120,
        placeholder="Ex.: Aquisição de material de expediente 2027",
        help="Nome livre, só para você encontrar o processo depois. "
             "Não aparece em nenhum documento gerado.",
    )
    coluna_salvar, coluna_cancelar = st.columns(2)
    if coluna_salvar.button("Salvar nome", key=f"salvar_nome_{resumo['id']}",
                            type="primary", use_container_width=True):
        try:
            db.renomear_processo(resumo["id"], st.session_state.get(chave, ""))
        except db.ErroBanco as erro:
            st.error(str(erro))
            return
        st.session_state.pop(RENOMEANDO, None)
        st.rerun()
    if coluna_cancelar.button("Cancelar", key=f"cancelar_nome_{resumo['id']}",
                              use_container_width=True):
        st.session_state.pop(RENOMEANDO, None)
        st.rerun()


def _render_acoes(resumo: dict, aberto: bool) -> None:
    coluna_abrir, coluna_renomear, coluna_excluir = st.columns(3)

    rotulo = "Continuar de onde parei" if not aberto else "Abrir novamente"
    if coluna_abrir.button(rotulo, key=f"abrir_{resumo['id']}",
                           use_container_width=True):
        _abrir(resumo["id"])

    # Sem a coluna no banco, o botão não aparece. O aviso do topo já
    # explicou a ausência — repetir a explicação aqui, botão a botão,
    # diria a mesma coisa tantas vezes quantos forem os processos.
    if db.coluna_nome_disponivel() and coluna_renomear.button(
            "Renomear", key=f"renomear_{resumo['id']}",
            use_container_width=True):
        st.session_state[RENOMEANDO] = resumo["id"]
        st.rerun()

    # Excluir existia no painel antigo e é preservado: tirar a única
    # forma de apagar um processo seria uma regressão disfarçada de
    # redesenho. O que MUDA é a confirmação — o botão antigo apagava no
    # primeiro clique, e um processo com quatro documentos aprovados não
    # deveria sumir por um clique errado numa lista.
    if st.session_state.get(EXCLUINDO) == resumo["id"]:
        st.warning(
            f"Excluir **{resumo['nome']}** em definitivo? "
            "Os documentos gerados vão junto."
        )
        confirma, desiste = st.columns(2)
        if confirma.button("Sim, excluir", key=f"conf_excluir_{resumo['id']}",
                           type="primary", use_container_width=True):
            _excluir(resumo["id"])
        if desiste.button("Manter", key=f"nao_excluir_{resumo['id']}",
                          use_container_width=True):
            st.session_state.pop(EXCLUINDO, None)
            st.rerun()
    elif coluna_excluir.button("Excluir", key=f"excluir_{resumo['id']}",
                               use_container_width=True):
        st.session_state[EXCLUINDO] = resumo["id"]
        st.rerun()


def _excluir(processo_id: str) -> None:
    try:
        db.excluir_processo(processo_id)
    except db.ErroBanco as erro:
        st.error(str(erro))
        return
    if st.session_state.get("processo_id") == processo_id:
        # O processo aberto deixou de existir: a sessão não pode seguir
        # apontando para um id que o banco não tem mais, senão o próximo
        # salvamento recriaria uma linha órfã.
        st.session_state.processo_id = None
        st.session_state["_save_status"] = "nao_salvo"
    st.session_state.pop(EXCLUINDO, None)
    st.rerun()


def _abrir(processo_id: str) -> None:
    """
    Carrega o processo na sessão e leva o servidor de volta ao wizard.

    `carregar_processo_salvo` já restaura a etapa exata, então "retomar
    de onde parou" não é promessa da tela: é o comportamento que o
    `state` sempre teve, agora com um botão que o nomeia.
    """
    try:
        processo = db.carregar_processo(processo_id)
    except db.ErroBanco as erro:
        st.error(str(erro))
        return
    if not processo:
        st.warning("Processo não encontrado. Pode ter sido excluído.")
        return
    st.session_state.pagina = "Novo processo"
    # `carregar_processo_salvo` termina em `st.rerun()`, então a troca de
    # página acima precisa vir ANTES — depois dela não há linha que rode.
    state.carregar_processo_salvo(processo)


__all__ = ["render_processos"]
