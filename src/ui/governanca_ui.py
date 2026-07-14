"""
Página "Governança" — Centro de Governança da Plataforma (pacote V6).

Visível SOMENTE quando `flag_governance_center` está ligada E o usuário
tem papel de governança (servidor comum nunca vê — T09). Os módulos
entram por fase; nesta Fase 2, Visão Geral + Catálogo de Cláusulas
(`flag_clause_catalog_admin`). A interface esconde programação:
formulários e botões, nunca JSON como forma principal de edição.
"""

import streamlit as st

from .. import auth, catalogo, db, governanca

_ROTULOS_STATUS = {
    "DRAFT": "rascunho",
    "UNDER_REVIEW": "em revisão",
    "APPROVED_FOR_SIMULATION": "aprovada p/ simulação",
    "SHADOW": "em shadow",
    "SCHEDULED": "agendada",
    "PUBLISHED": "PUBLICADA",
    "SUPERSEDED": "superada",
    "REVOKED": "revogada",
}

_ROTULOS_COMPORTAMENTO = {
    "FIXED_LOCKED": "Fixa (imutável)",
    "FIXED_PARAMETERIZED": "Fixa com parâmetros",
    "CONDITIONAL_LOCKED": "Condicional (texto fixo)",
    "HYBRID": "Híbrida",
    "AI_GENERATED": "Gerada por IA",
}


def disponivel() -> bool:
    return (db.flag_ativa(governanca.FLAG_CENTRO)
            and auth.acessa_centro_governanca())


def render_governanca() -> None:
    st.subheader("Centro de Governança")
    papel = auth.papel_governanca()
    st.caption(
        f"Seu papel: **{papel}**. Aqui o conhecimento documental é "
        "operado pela interface — cláusulas, políticas, modelos e "
        "templates versionados, com revisão, simulação e publicação. "
        "Nada é publicado automaticamente."
    )
    aba_visao, aba_catalogo = st.tabs(["Visão geral",
                                       "Catálogo de cláusulas"])
    with aba_visao:
        _render_visao_geral()
    with aba_catalogo:
        if db.flag_ativa(governanca.FLAG_CATALOGO):
            _render_catalogo()
        else:
            st.info("O Catálogo de Cláusulas está desligado "
                    "(flag_clause_catalog_admin).")


def _render_visao_geral() -> None:
    try:
        itens = catalogo.listar_com_situacao()
    except db.ErroBanco as erro:
        st.error(str(erro))
        return
    publicadas = sum(1 for i in itens if i["publicada"])
    rascunhos = sum(1 for i in itens if i["ultima"]
                    and i["ultima"]["status"] in ("DRAFT", "UNDER_REVIEW"))
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Cláusulas no catálogo", len(itens))
    col_b.metric("Publicadas (vigentes)", publicadas)
    col_c.metric("Em elaboração/revisão", rascunhos)
    st.caption(
        "Módulos por fase: Catálogo (ativo) · Políticas de Aplicação · "
        "Biblioteca de Modelos · Construtor de Templates · Herança · "
        "Assistente de Implantação · Pareceres · Laboratório · "
        "Publicações — chegam nas fases seguintes, cada um com sua flag."
    )


def _render_catalogo() -> None:
    somente_leitura = auth.somente_auditoria()

    if not somente_leitura:
        with st.expander("Nova cláusula"):
            _render_form_nova_clausula()
        if auth.pode_criar_governanca() and st.button(
            "Importar rascunhos dos perfis aprovados (DFD/ETP/TR)",
            help="Cada cláusula dos perfis institucionais vira um "
                 "RASCUNHO do catálogo — nada é publicado.",
        ):
            try:
                criadas = catalogo.semear_dos_perfis()
                st.success(f"{len(criadas)} rascunho(s) criado(s).")
                st.rerun()
            except (catalogo.ErroCatalogo, db.ErroBanco,
                    governanca.ErroContrato) as erro:
                st.error(str(erro))

    st.divider()
    try:
        itens = catalogo.listar_com_situacao()
    except db.ErroBanco as erro:
        st.error(str(erro))
        return
    if not itens:
        st.caption("Catálogo vazio. Crie uma cláusula ou importe os "
                   "perfis aprovados.")
        return
    for item in itens:
        _render_clausula(item, somente_leitura)


def _render_form_nova_clausula() -> None:
    with st.form("form_nova_clausula", clear_on_submit=True):
        col1, col2 = st.columns(2)
        chave = col1.text_input(
            "Chave estável", placeholder="clausula.tr.garantia",
            help="Identificador permanente (minúsculas, pontos, hífens).")
        titulo = col2.text_input("Título da cláusula")
        col3, col4 = st.columns(2)
        comportamento = col3.selectbox(
            "Comportamento", governanca.COMPORTAMENTOS_CLAUSULA,
            format_func=lambda c: _ROTULOS_COMPORTAMENTO.get(c, c))
        tipo_documental = col4.selectbox(
            "Tipo documental", ["dfd", "etp", "tr", "edital"])
        texto = st.text_area(
            "Texto da cláusula (um parágrafo por linha em branco)",
            height=160,
            help="Use {{parametro}} para os campos parametrizados.")
        parametros = st.text_input(
            "Parâmetros permitidos (separados por vírgula)",
            placeholder="prazo, percentual",
            help="Obrigatório para cláusulas fixas com parâmetros.")
        base_legal = st.text_input(
            "Base legal / fontes", placeholder="art. 96, Lei 14.133/2021")
        enviado = st.form_submit_button("Criar rascunho", type="primary",
                                        use_container_width=True)
    if enviado:
        payload = {
            "titulo": titulo.strip(),
            "tipo_documental": tipo_documental,
            "comportamento": comportamento,
            "blocos": [b.strip() for b in (texto or "").split("\n\n")
                       if b.strip()],
            "parametros_permitidos": [
                p.strip() for p in parametros.split(",") if p.strip()],
            "base_legal": [b.strip() for b in base_legal.split(";")
                           if b.strip()],
        }
        try:
            catalogo.criar_clausula(chave.strip(), payload)
            st.success(f"Rascunho '{chave}' criado.")
            st.rerun()
        except (catalogo.ErroCatalogo, db.ErroBanco,
                governanca.ErroContrato) as erro:
            st.error(str(erro))


def _render_clausula(item: dict, somente_leitura: bool) -> None:
    artefato, ultima = item["artefato"], item["ultima"]
    publicada = item["publicada"]
    situacao = (_ROTULOS_STATUS.get(ultima["status"], ultima["status"])
                if ultima else "sem versões")
    escopo = "plataforma" if artefato.get("tenant_id") is None \
        else "município"
    with st.expander(
        f"`{artefato['chave_estavel']}` — "
        f"{(ultima or {}).get('payload', {}).get('titulo', '')} "
        f"· v{(ultima or {}).get('versao', 0)} ({situacao}) · {escopo}"
    ):
        if publicada and publicada is not ultima:
            st.caption(
                f"Vigente: v{publicada['versao']} (hash "
                f"`{publicada['hash'][:12]}…`) — a edição abaixo é de "
                "uma versão em elaboração.")
        if not ultima:
            return
        payload = ultima["payload"]
        st.markdown(
            f"**Comportamento:** "
            f"{_ROTULOS_COMPORTAMENTO.get(payload.get('comportamento'))} · "
            f"**Documento:** {payload.get('tipo_documental', '—')} · "
            f"**Hash:** `{ultima['hash'][:12]}…`"
        )
        for bloco in payload.get("blocos", []):
            st.markdown(f"> {bloco}")
        if payload.get("parametros_permitidos"):
            st.caption("Parâmetros permitidos: "
                       + ", ".join(payload["parametros_permitidos"]))
        if payload.get("base_legal"):
            st.caption("Base legal: " + "; ".join(payload["base_legal"]))
        if somente_leitura:
            return

        if governanca.versao_artefato_editavel(ultima):
            novo_texto = st.text_area(
                "Editar texto do rascunho",
                value="\n\n".join(payload.get("blocos", [])),
                key=f"edita_{ultima['id']}", height=120)
            if st.button("Salvar rascunho", key=f"salva_{ultima['id']}"):
                try:
                    catalogo.editar_rascunho(
                        ultima, artefato["chave_estavel"],
                        {**payload, "blocos": [
                            b.strip() for b in novo_texto.split("\n\n")
                            if b.strip()]})
                    st.rerun()
                except (catalogo.ErroCatalogo, db.ErroBanco,
                        governanca.ErroContrato) as erro:
                    st.error(str(erro))
        elif ultima.get("status") == "PUBLISHED" and \
                auth.pode_criar_governanca():
            if st.button("Derivar nova versão (editar)",
                         key=f"deriva_{ultima['id']}"):
                try:
                    catalogo.derivar_nova_versao(artefato, ultima)
                    st.rerun()
                except (catalogo.ErroCatalogo, db.ErroBanco) as erro:
                    st.error(str(erro))

        destinos = catalogo.proximas_transicoes(ultima)
        if destinos:
            col_sel, col_btn = st.columns([2, 1])
            destino = col_sel.selectbox(
                "Avançar para", destinos,
                format_func=lambda d: _ROTULOS_STATUS.get(d, d),
                key=f"destino_{ultima['id']}",
                label_visibility="collapsed")
            if col_btn.button("Aplicar", key=f"aplica_{ultima['id']}",
                              use_container_width=True):
                try:
                    catalogo.transicionar(artefato, ultima, destino)
                    st.rerun()
                except (catalogo.ErroCatalogo, db.ErroBanco) as erro:
                    st.error(str(erro))
