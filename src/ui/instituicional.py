"""
Painel institucional: Prefeitura, Módulos, Servidores e Portarias.

UMA ABA, NÃO QUATRO

O escopo pede quatro áreas novas na Administração, e o painel já tem seis
abas. Dez abas no topo seria a "Administração virando ERP gigantesco" que
o próprio escopo proíbe — e, pior, empurraria "Usuários" e "Chaves de IA"
para fora do campo de visão de quem abre a tela.

Então a navegação é em dois níveis: uma aba "Instituição" com um seletor
interno. O segundo nível custa um clique e devolve o topo do painel para
o que o administrador usa toda semana.

TUDO ATRÁS DE UMA FLAG, DESLIGADA

`flag_multi_prefeituras` nasce desligada. Com ela desligada, esta aba nem
aparece — e sem a migração 0025 aplicada, as consultas falhariam de
qualquer jeito. A flag existe para que ligar seja uma decisão, e para que
desligar seja o rollback.
"""

from __future__ import annotations

import datetime as _dt

import streamlit as st

from .. import assinaturas, db, modulos, portarias

FLAG_MULTI_PREFEITURAS = "multi_prefeituras"

# Os módulos que o painel oferece por prefeitura e por secretaria. São os
# que o produto de fato entrega hoje; a flag global de cada um continua
# sendo a palavra final, e a tela diz isso.
MODULOS_OFERECIDOS = (
    ("price_research", "Pesquisa de Preços"),
    ("demand_consolidation", "Consolidação de Solicitações de Despesa"),
    ("legal_opinion_correction", "Correção por Parecer Jurídico"),
    ("canonical_facts", "Fatos Canônicos"),
    ("process_consistency", "Consistência do Processo"),
)

_SECOES = ("Prefeitura", "Módulos", "Servidores", "Portarias")


def ativo() -> bool:
    return db.flag_ativa(FLAG_MULTI_PREFEITURAS)


def render() -> None:
    st.caption(
        "Cadastro institucional da prefeitura: dados, módulos habilitados, "
        "servidores e portarias. É daqui que o sistema tira, sozinho, o "
        "timbrado, a equipe de planejamento e quem pode assinar cada "
        "documento — sem ninguém digitar isso a cada processo."
    )

    if not _exigir_migracao():
        return

    secao = st.radio("Seção", _SECOES, horizontal=True,
                     label_visibility="collapsed")
    st.divider()

    if secao == "Prefeitura":
        _render_prefeitura()
    elif secao == "Módulos":
        _render_modulos()
    elif secao == "Servidores":
        _render_servidores()
    else:
        _render_portarias()


def _exigir_migracao() -> bool:
    """
    Uma consulta barata que falha cedo e EXPLICA.

    Sem isto, a primeira tela quebraria com um erro de PostgREST sobre
    relação inexistente — mensagem que não diz ao administrador o que
    fazer. A migração é pré-requisito, e a tela tem que dizer qual.
    """
    try:
        db.listar_funcoes_administrativas()
        return True
    except db.ErroBanco as erro:
        st.error(str(erro))
        st.info(
            "Se as tabelas ainda não existem, aplique a migração "
            "`supabase/migrations/0025_multi_prefeituras_servidores_"
            "portarias.sql`. Ela cria dez tabelas, não altera nenhuma "
            "linha existente e não toca em `secretarias` nem em "
            "`config_orgaos`."
        )
        return False


# ---------------------------------------------------------------------------
# PREFEITURA (§8)
# ---------------------------------------------------------------------------
CAMPOS_DA_PREFEITURA = (
    ("nome_oficial", "Nome oficial", "Ex.: Município de Paragominas"),
    ("cnpj", "CNPJ", "00.000.000/0001-00"),
    ("sigla", "Sigla", "Ex.: PMP"),
    ("cidade", "Cidade", "Ex.: Paragominas"),
    ("endereco", "Endereço", "Rua, número, bairro"),
    ("telefone", "Telefone", "(00) 0000-0000"),
    ("email", "E-mail institucional", "contato@municipio.gov.br"),
    ("site", "Site", "https://..."),
)


def _render_prefeitura() -> None:
    try:
        tenant = db.tenant_atual_registro()
    except db.ErroBanco as erro:
        st.error(str(erro))
        return

    st.markdown(f"##### {tenant.get('nome') or 'Prefeitura'}")
    st.caption(
        "Campos opcionais. Nada é preenchido automaticamente — o sistema "
        "não inventa CNPJ nem endereço."
    )

    with st.form("form_prefeitura"):
        valores: dict = {}
        for i in range(0, len(CAMPOS_DA_PREFEITURA), 2):
            colunas = st.columns(2)
            for coluna, (chave, rotulo, exemplo) in zip(
                    colunas, CAMPOS_DA_PREFEITURA[i:i + 2]):
                valores[chave] = coluna.text_input(
                    rotulo, value=tenant.get(chave) or "", placeholder=exemplo)
        if st.form_submit_button("Salvar dados institucionais",
                                 type="primary", use_container_width=True):
            try:
                db.salvar_dados_do_tenant(
                    {k: (v.strip() or None) for k, v in valores.items()})
                st.success("Dados salvos.")
                st.rerun()
            except db.ErroBanco as erro:
                st.error(str(erro))


# ---------------------------------------------------------------------------
# MÓDULOS (§9, §10)
# ---------------------------------------------------------------------------
def _render_modulos() -> None:
    st.caption(
        "Três níveis, e o de baixo nunca abre o que o de cima fechou: o "
        "módulo precisa existir no sistema, a prefeitura precisa tê-lo "
        "habilitado, e a secretaria pode dispensá-lo."
    )

    try:
        no_tenant = db.modulos_do_tenant()
        secretarias = db.listar_secretarias()
    except db.ErroBanco as erro:
        st.error(str(erro))
        return

    st.markdown("##### Na Prefeitura")
    for modulo, rotulo in MODULOS_OFERECIDOS:
        global_ = db.flag_ativa(modulo)
        coluna_rotulo, coluna_estado = st.columns([3, 2])
        coluna_rotulo.write(rotulo)
        if not global_:
            # Não é caixa desmarcada: é caixa que não existe. Marcar algo
            # que a flag global desliga daria a impressão de contratação.
            coluna_estado.caption("indisponível nesta versão do sistema")
            continue
        ligado = coluna_estado.toggle(
            rotulo, value=no_tenant.get(modulo, False),
            key=f"mod_tenant_{modulo}", label_visibility="collapsed")
        if ligado != no_tenant.get(modulo, False):
            try:
                db.salvar_modulo_do_tenant(modulo, ligado)
                st.rerun()
            except db.ErroBanco as erro:
                st.error(str(erro))

    if not secretarias:
        return

    st.divider()
    st.markdown("##### Por secretaria")
    nomes = {s["id"]: s.get("nome") or s.get("sigla") or "—"
             for s in secretarias}
    escolhida = st.selectbox("Secretaria", list(nomes),
                             format_func=lambda i: nomes[i])
    try:
        na_secretaria = db.modulos_da_secretaria(escolhida)
    except db.ErroBanco as erro:
        st.error(str(erro))
        return

    for modulo, rotulo in MODULOS_OFERECIDOS:
        if not db.flag_ativa(modulo):
            continue
        atual = modulos.estado_valido(na_secretaria.get(modulo))
        coluna_rotulo, coluna_estado = st.columns([3, 2])
        herdado = "ligado" if no_tenant.get(modulo) else "desligado"
        coluna_rotulo.write(rotulo)
        coluna_rotulo.caption(f"herdar = {herdado} (estado da Prefeitura)")
        novo = coluna_estado.selectbox(
            rotulo, [modulos.HERDAR, modulos.HABILITADO, modulos.DESABILITADO],
            index=[modulos.HERDAR, modulos.HABILITADO,
                   modulos.DESABILITADO].index(atual),
            key=f"mod_sec_{escolhida}_{modulo}", label_visibility="collapsed")
        if novo != atual:
            try:
                db.salvar_modulo_da_secretaria(escolhida, modulo, novo)
                st.rerun()
            except db.ErroBanco as erro:
                # A recusa de habilitar o que o tenant proíbe chega aqui,
                # e a mensagem já diz o que fazer.
                st.error(str(erro))


# ---------------------------------------------------------------------------
# SERVIDORES (§15)
# ---------------------------------------------------------------------------
def _render_servidores() -> None:
    st.caption(
        "Cadastro institucional. Sem CPF: o documento precisa de nome, "
        "cargo, matrícula e função — guardar dado pessoal sem necessidade "
        "funcional é obrigação assumida sem contrapartida."
    )

    with st.form("form_novo_servidor", clear_on_submit=True):
        st.markdown("##### Novo servidor")
        col_nome, col_cargo = st.columns([3, 2])
        nome = col_nome.text_input("Nome", placeholder="Nome completo")
        cargo = col_cargo.text_input("Cargo",
                                     placeholder="Ex.: Agente Administrativo")
        col_mat, col_email = st.columns(2)
        matricula = col_mat.text_input("Matrícula", placeholder="Opcional")
        email = col_email.text_input("E-mail", placeholder="Opcional")
        if st.form_submit_button("Cadastrar servidor", type="primary",
                                 use_container_width=True):
            if not nome.strip():
                st.error("Informe o nome do servidor.")
            else:
                try:
                    db.salvar_servidor({
                        "nome": nome.strip(), "cargo": cargo.strip() or None,
                        "matricula": matricula.strip() or None,
                        "email": email.strip() or None})
                    st.success(f"{nome.strip()} cadastrado.")
                    st.rerun()
                except db.ErroBanco as erro:
                    st.error(str(erro))

    try:
        servidores = db.listar_servidores(incluir_inativos=True)
    except db.ErroBanco as erro:
        st.error(str(erro))
        return

    if not servidores:
        st.info("Nenhum servidor cadastrado ainda.")
        return

    st.markdown(f"##### {len(servidores)} servidor(es)")
    for servidor in servidores:
        col_nome, col_cargo, col_ativo = st.columns([3, 2, 1])
        rotulo = servidor.get("nome") or "—"
        if servidor.get("matricula"):
            rotulo += f" · mat. {servidor['matricula']}"
        col_nome.write(rotulo)
        col_cargo.caption(servidor.get("cargo") or "sem cargo")
        ativo_atual = bool(servidor.get("ativo", True))
        novo = col_ativo.toggle("Ativo", value=ativo_atual,
                                key=f"srv_{servidor['id']}",
                                label_visibility="collapsed")
        if novo != ativo_atual:
            try:
                db.salvar_servidor({"ativo": novo}, servidor["id"])
                st.rerun()
            except db.ErroBanco as erro:
                st.error(str(erro))


# ---------------------------------------------------------------------------
# PORTARIAS (§19–§22, §52, §54)
# ---------------------------------------------------------------------------
TIPOS_DE_PORTARIA = (
    ("EQUIPE_PLANEJAMENTO", "Equipe de Planejamento"),
    ("PREGOEIRO", "Pregoeiro"),
    ("AGENTE_CONTRATACAO", "Agente de Contratação"),
    ("FISCAL", "Fiscal"),
    ("GESTOR", "Gestor"),
    ("COMISSAO", "Comissão"),
    ("OUTRO", "Outro"),
)


def _render_portarias() -> None:
    try:
        secretarias = db.listar_secretarias()
    except db.ErroBanco as erro:
        st.error(str(erro))
        return

    if not secretarias:
        st.info("Cadastre uma secretaria antes de registrar portarias.")
        return

    nomes = {s["id"]: s.get("nome") or s.get("sigla") or "—"
             for s in secretarias}
    secretaria_id = st.selectbox("Secretaria", list(nomes),
                                 format_func=lambda i: nomes[i])

    _form_nova_portaria(secretaria_id)

    try:
        acervo = db.listar_portarias(secretaria_id=secretaria_id)
    except db.ErroBanco as erro:
        st.error(str(erro))
        return

    if not acervo:
        st.info("Nenhuma portaria registrada nesta secretaria.")
        return

    _avisar_conflito(acervo, secretaria_id)

    st.markdown("##### Histórico")
    st.caption(
        "Portaria não se apaga: revoga-se. O histórico é o que permite a "
        "um documento de 2025 continuar citando a portaria de 2025."
    )
    hoje = _dt.date.today()
    for portaria in acervo:
        _render_uma_portaria(portaria, hoje)


def _avisar_conflito(acervo: list[dict], secretaria_id: str) -> None:
    """
    O aviso de §50, na tela onde ele se conserta.

    Duas portarias vigentes do mesmo tipo não é dúvida do sistema — é
    defeito de cadastro, e quem o conserta está olhando para esta tela.
    """
    hoje = _dt.date.today()
    for codigo, rotulo in TIPOS_DE_PORTARIA:
        try:
            portarias.resolver(acervo, secretaria_id=secretaria_id,
                               tipo=codigo, data_referencia=hoje)
        except portarias.PortariaAmbigua as erro:
            st.error(f"**{rotulo}** — {erro}")
        except portarias.ErroPortaria as erro:
            st.warning(str(erro))


def _form_nova_portaria(secretaria_id: str) -> None:
    with st.form("form_nova_portaria", clear_on_submit=True):
        st.markdown("##### Nova portaria")
        col_tipo, col_num, col_ano = st.columns([3, 1, 1])
        tipo = col_tipo.selectbox(
            "Tipo", [c for c, _ in TIPOS_DE_PORTARIA],
            format_func=lambda c: dict(TIPOS_DE_PORTARIA)[c])
        numero = col_num.text_input("Número", placeholder="003")
        ano = col_ano.number_input("Ano", min_value=2000, max_value=2100,
                                   value=_dt.date.today().year, step=1)
        col_pub, col_ini, col_fim = st.columns(3)
        publicacao = col_pub.date_input("Publicação", value=None,
                                        format="DD/MM/YYYY")
        inicio = col_ini.date_input("Início da vigência",
                                    value=_dt.date.today(),
                                    format="DD/MM/YYYY")
        fim = col_fim.date_input("Fim (opcional)", value=None,
                                 format="DD/MM/YYYY")
        if st.form_submit_button("Registrar portaria", type="primary",
                                 use_container_width=True):
            if not numero.strip():
                st.error("Informe o número da portaria.")
            elif fim and inicio and fim < inicio:
                st.error("O fim da vigência é anterior ao início.")
            else:
                try:
                    db.salvar_portaria({
                        "secretaria_id": secretaria_id, "tipo": tipo,
                        "numero": numero.strip(), "ano": int(ano),
                        "data_publicacao": publicacao.isoformat() if publicacao else None,
                        "data_inicio_vigencia": inicio.isoformat(),
                        "data_fim_vigencia": fim.isoformat() if fim else None,
                        "status": "RASCUNHO"})
                    st.success(
                        f"Portaria {numero.strip()}/{int(ano)} registrada como "
                        "RASCUNHO. Ative-a abaixo quando estiver publicada.")
                    st.rerun()
                except db.ErroBanco as erro:
                    st.error(str(erro))


_CORES = {"ATIVA": "🟢", "FUTURA": "🔵", "EXPIRADA": "⚪",
          "REVOGADA": "🔴", "RASCUNHO": "🟡"}


def _render_uma_portaria(portaria: dict, hoje: _dt.date) -> None:
    try:
        situacao = portarias.situacao(portaria, hoje)
    except portarias.ErroPortaria:
        situacao = "RASCUNHO"

    titulo = (f"{_CORES.get(situacao, '⚪')} "
              f"Portaria {portaria.get('numero')}/{portaria.get('ano')} — "
              f"{dict(TIPOS_DE_PORTARIA).get(portaria.get('tipo'), portaria.get('tipo'))}"
              f" · {situacao}")

    with st.expander(titulo, expanded=situacao == "ATIVA"):
        st.caption(portarias.citacao(portaria))

        declarado = (portaria.get("status") or "RASCUNHO").upper()
        novo = st.selectbox(
            "Situação declarada", ["RASCUNHO", "ATIVA", "REVOGADA"],
            index=["RASCUNHO", "ATIVA", "REVOGADA"].index(
                declarado if declarado in ("RASCUNHO", "ATIVA", "REVOGADA")
                else "RASCUNHO"),
            key=f"status_{portaria['id']}",
            help="EXPIRADA e FUTURA são efeito da vigência e o sistema "
                 "calcula sozinho. Aqui fica a DECISÃO administrativa: "
                 "uma portaria pode ser revogada antes do fim da vigência.")
        if novo != declarado:
            try:
                db.salvar_portaria({"status": novo}, portaria["id"])
                st.rerun()
            except db.ErroBanco as erro:
                st.error(str(erro))

        _render_membros(portaria)


def _render_membros(portaria: dict) -> None:
    try:
        membros = db.listar_membros_de_portaria(portaria["id"])
        servidores = db.listar_servidores()
    except db.ErroBanco as erro:
        st.error(str(erro))
        return

    st.markdown("**Membros**")
    if membros:
        for membro in membros:
            rotulo = assinaturas.ROTULOS.get(membro.get("funcao"),
                                             membro.get("funcao") or "")
            linha = f"{membro.get('nome') or '—'} — {rotulo}"
            if not membro.get("servidor_ativo", True):
                linha += "  ⚠️ servidor inativo no cadastro"
            st.write(linha)
    else:
        st.caption("Nenhum membro designado.")

    if not servidores:
        st.caption("Cadastre servidores na seção **Servidores** para "
                   "designá-los aqui.")
        return

    # §53: adicionar membro REFERENCIA cadastro existente. Não há campo de
    # texto livre aqui de propósito — criar pessoa nova por dentro da
    # portaria produziria dois "Antonio" que o sistema não sabe serem o
    # mesmo.
    nomes = {s["id"]: s["nome"] for s in servidores}
    col_serv, col_func, col_btn = st.columns([3, 2, 1])
    servidor_id = col_serv.selectbox(
        "Servidor", list(nomes), format_func=lambda i: nomes[i],
        key=f"add_srv_{portaria['id']}", label_visibility="collapsed")
    funcao = col_func.selectbox(
        "Função", ["EQUIPE_PLANEJAMENTO", "COORDENADOR_EQUIPE_PLANEJAMENTO"],
        format_func=lambda f: assinaturas.ROTULOS.get(f, f),
        key=f"add_func_{portaria['id']}", label_visibility="collapsed")
    if col_btn.button("Adicionar", key=f"add_btn_{portaria['id']}",
                      use_container_width=True):
        try:
            db.salvar_membro_de_portaria(
                portaria["id"], servidor_id, funcao,
                ordem=len(membros) + 1)
            st.rerun()
        except db.ErroBanco as erro:
            st.error(str(erro))
