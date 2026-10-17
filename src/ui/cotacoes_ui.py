"""
Cotações — Minhas Cotações → Elaborar Cotação, numa entrada de menu só.

A tela é a ÚNICA porta para a mesma entidade da Pesquisa de Preços
(migração 0021) quando a flag `unified_quotations` está ligada. Nela o
servidor, sem trocar de módulo:

* cria a cotação (identidade antes dos itens) e inclui/importa itens;
* escolhe um item e pesquisa preços À MÃO, ou clica **Cotação
  automática** — no item ou em lote. Os dois caminhos chamam o mesmo
  `cotacoes.pesquisar_item`, gravam as mesmas referências e refazem a
  mesma cesta;
* revisa a cesta ao lado (considerados N/3, método, exceção, conclusão),
  emite o relatório e aplica ao processo pelos serviços que já existem.

Nada aqui calcula preço ou decide cesta: a tela chama o serviço e só diz
"salvo" depois da resposta dele. A versão (`revisao`) do item lida ao
desenhar viaja em toda alteração — outra aba que mexeu antes faz esta
receber conflito, não sobrescrever (pacote U07).

Visual: tokens do design system (`assets/govconnect.css`), sem copiar
layout, marca ou textos de terceiros.
"""

from __future__ import annotations

import html
import uuid
from datetime import date
from decimal import Decimal

import streamlit as st

from .. import auth, db, governanca
from ..precos import cesta, cotacoes, estatistica, execucao, perfil
from ..precos import filtros as filtros_mod
from ..precos import repositorio as repo
from ..precos.estados import EstadoItem
from ..precos.perfil import inciso_da_fonte
from ..precos import saneamento
from ..precos.relatorio_view import titulo_curto
from . import components, precos_ui

# Navegação interna (estado de INTERAÇÃO, nunca fonte de preço ou cesta).
TELA, COTACAO, ITEM = "cot_tela", "cot_id", "cot_item"
LISTA, NOVA, ELABORAR = "lista", "nova", "elaborar"
LOTE = "cot_lote"
PAGINA_LISTA = "cot_pagina"
POR_PAGINA_LISTA = 20
POR_PAGINA_ITENS = 40
POR_PAGINA_REFERENCIAS = 12
# Itens por passo da Cotação automática: a tela responde a cada passo e
# o estado da cotação é sincronizado uma vez por passo (benchmark G6).
LOTE_POR_PASSO = 3
# Menor janela que a busca por item oferece (passo de 30 dias).
JANELA_MINIMA = 30

ROTULO_ESTADO = {
    "draft": ("Rascunho", "info"), "queued": ("Na fila", "info"),
    "running": ("Pesquisando", "info"), "partial": ("Com pendência", "warning"),
    "review": ("Em revisão", "info"), "completed": ("Concluída", "success"),
    "applied": ("Aplicada ao processo", "success"),
    "archived": ("Arquivada", ""), "failed": ("Falhou", "danger"),
}
ICONE_ITEM = {
    "pending": "○", "searching": "…", "matching": "…", "review": "◐",
    "complete": "✓", "incomplete": "!", "error": "⚠",
}


def disponivel() -> bool:
    """Ligada só com a Pesquisa de Preços ligada E a flag de Cotações."""
    return precos_ui.disponivel() and db.flag_ativa(
        governanca.FLAG_COTACOES_UNIFICADAS)


def _ctx() -> cotacoes.Contexto:
    usuario = auth.usuario_logado() or {}
    return cotacoes.Contexto(
        auth_user_id=str(usuario.get("auth_user_id") or ""),
        secretaria_id=usuario.get("secretaria_id") or None,
        processo_aberto=st.session_state.get("processo_id"))


def _ir(tela: str, **estado) -> None:
    st.session_state[TELA] = tela
    for chave, valor in estado.items():
        st.session_state[chave] = valor


def _chips(itens: list[tuple[str, str]]) -> None:
    partes = "".join(
        f'<span class="gc-chip" data-tone="{html.escape(tom)}">'
        f"{html.escape(texto)}</span>" for texto, tom in itens if texto)
    st.markdown(f'<div class="gc-chips">{partes}</div>', unsafe_allow_html=True)


def _revisao_vista(item: dict | None) -> int | None:
    """
    A versão do item QUANDO esta aba o mostrou — não a de agora.

    No Streamlit o clique roda num script novo, que relê o banco: usar a
    revisão relida faria a aba velha parecer atual e sobrescrever o que a
    outra aba gravou. Por isso a revisão vista fica guardada e só é
    renovada depois de uma gravação desta aba ou do aviso de conflito
    (pacote U07: "falha com opção de atualizar e reaplicar").
    """
    if not item:
        return None
    atual = precos_ui._revisao(item)
    if atual is None:
        return None
    chave = f"_cot_rev_{item['id']}"
    if chave not in st.session_state:
        st.session_state[chave] = atual
    return int(st.session_state[chave])


def _renovar_revisoes() -> None:
    for chave in [c for c in st.session_state if str(c).startswith("_cot_rev_")]:
        st.session_state.pop(chave, None)


def _sem_latex(texto: str) -> str:
    """Dois "R$" no mesmo texto viravam fórmula no Markdown do Streamlit."""
    return str(texto).replace("$", "\\$")


def _moeda(valor) -> str:
    try:
        return estatistica.brl(None if valor in (None, "")
                               else Decimal(str(valor)))
    except (ArithmeticError, ValueError):
        return "—"


def _quantidade(valor) -> str:
    return precos_ui._texto_quantidade(valor)


def render_cotacoes() -> None:
    """Roteador: Minhas Cotações, Nova cotação, Elaborar Cotação."""
    components.render_page_header(
        "Cotações",
        "Pesquisa de preços por item, manual ou automática, na mesma "
        "cotação — com memória de cálculo auditável.")
    if not precos_ui._exigir_sessao():
        return
    tela = st.session_state.get(TELA) or LISTA
    try:
        if tela == NOVA:
            _render_nova()
        elif tela == ELABORAR and st.session_state.get(COTACAO):
            _render_elaborar()
        else:
            _render_lista()
    except repo.ConflitoDeVersao as erro:
        _renovar_revisoes()
        st.warning(f"{erro} A tela foi recarregada com a versão atual — "
                   "confira e refaça a alteração.")
    except cotacoes.ErroCotacao as erro:
        st.error(str(erro))
    except repo.SemSessao as erro:
        st.warning(str(erro))
    except db.ErroBanco as erro:
        st.error(str(erro))


# ---------------------------------------------------------------------------
# Minhas Cotações
# ---------------------------------------------------------------------------
def _render_lista() -> None:
    components.render_section_heading(
        "Minhas Cotações", "Cada cotação reúne os itens, as referências, a "
        "cesta e os relatórios — num lugar só.")
    busca_col, recorte_col, nova_col = st.columns([3, 3, 1.3])
    termo = busca_col.text_input("Buscar cotação", key="cot_busca",
                                 placeholder="nome ou objeto",
                                 label_visibility="collapsed")
    recorte = recorte_col.radio(
        "Situação", ["Em elaboração", "Com pendência", "Concluídas",
                     "Arquivadas", "Todas"],
        horizontal=True, key="cot_recorte", label_visibility="collapsed")
    if nova_col.button("Nova cotação", type="primary",
                       use_container_width=True):
        _ir(NOVA)
        st.rerun()

    ctx = _ctx()
    carregando = st.empty()
    components.render_skeleton(carregando, "Carregando as cotações", linhas=3)
    todas = cotacoes.listar_cotacoes(ctx, recorte="Todas")
    linhas = cotacoes.listar_cotacoes(ctx, busca_texto=termo, recorte=recorte)
    carregando.empty()

    m = st.columns(4)
    m[0].metric("Em elaboração", sum(1 for c in todas if c.estado in
                                     cotacoes.RECORTES["Em elaboração"]))
    m[1].metric("Com pendência", sum(1 for c in todas if c.estado in
                                     cotacoes.RECORTES["Com pendência"]))
    m[2].metric("Concluídas", sum(1 for c in todas if c.estado in
                                  cotacoes.RECORTES["Concluídas"]))
    m[3].metric("Valor concluído", _moeda(sum(
        (c.valor_concluidos for c in todas), Decimal(0))))

    if not linhas:
        st.info("Nenhuma cotação neste recorte. Use **Nova cotação** para "
                "começar — a identificação vem antes dos itens.")
        return
    pagina = int(st.session_state.get(PAGINA_LISTA) or 1)
    total_paginas = max(1, -(-len(linhas) // POR_PAGINA_LISTA))
    pagina = min(pagina, total_paginas)
    for resumo in linhas[(pagina - 1) * POR_PAGINA_LISTA:
                         pagina * POR_PAGINA_LISTA]:
        _linha_da_lista(ctx, resumo)
    if total_paginas > 1:
        a, b, c = st.columns([1, 2, 1])
        if a.button("‹ Anterior", disabled=pagina <= 1, key="cot_ant"):
            st.session_state[PAGINA_LISTA] = pagina - 1
            st.rerun()
        b.caption(f"Página {pagina} de {total_paginas} · {len(linhas)} cotações")
        if c.button("Próxima ›", disabled=pagina >= total_paginas,
                    key="cot_prox"):
            st.session_state[PAGINA_LISTA] = pagina + 1
            st.rerun()


def _linha_da_lista(ctx, resumo: cotacoes.Resumo) -> None:
    with st.container(border=True):
        nome_col, dados_col, acoes_col = st.columns([3.2, 3.2, 1.6])
        with nome_col:
            sufixo = f" · revisão {resumo.versao}" if resumo.versao > 1 else ""
            st.markdown(f"**{html.escape(resumo.nome)}**{sufixo}")
            rotulo, tom = ROTULO_ESTADO.get(resumo.estado, (resumo.estado, ""))
            _chips([(rotulo, tom),
                    ("vinculada a processo" if resumo.vinculada
                     else "autônoma", "")])
            if resumo.objeto:
                st.caption(resumo.objeto[:120])
        with dados_col:
            st.progress(resumo.cobertura,
                        text=f"{resumo.com_minimo}/{resumo.itens} itens com "
                             "3+ preços considerados")
            st.caption(f"{resumo.itens} item(ns) · {resumo.pendentes} "
                       f"pendente(s) · valor concluído "
                       f"{_moeda(resumo.valor_concluidos)}")
        with acoes_col:
            if st.button("Abrir", key=f"cot_abrir_{resumo.id}", type="primary",
                         use_container_width=True):
                _ir(ELABORAR, **{COTACAO: resumo.id, ITEM: None})
                st.rerun()
            with st.popover("Mais", use_container_width=True):
                if st.button("Duplicar", key=f"cot_dup_{resumo.id}",
                             help="Cotação nova, mesmos itens, sem preços."):
                    copia = cotacoes.duplicar(ctx, resumo.id)
                    _ir(ELABORAR, **{COTACAO: str(copia["id"]), ITEM: None})
                    st.rerun()
                if st.button("Arquivar", key=f"cot_arq_{resumo.id}",
                             disabled=resumo.estado == "archived",
                             help="Arquivar não apaga: continua legível."):
                    cotacoes.arquivar(ctx, resumo.id)
                    st.rerun()


# ---------------------------------------------------------------------------
# Nova cotação — identidade antes dos itens
# ---------------------------------------------------------------------------
def _render_nova() -> None:
    components.render_section_heading(
        "Nova cotação", "A identificação vai para o relatório e sustenta a "
        "decisão meses depois.")
    ctx = _ctx()
    processo = ctx.processo_aberto
    chave = st.session_state.setdefault("_cot_nova_chave", uuid.uuid4().hex)
    with st.form("cot_nova"):
        nome = st.text_input("Nome da cotação *", max_chars=cotacoes.MAXIMO_NOME,
                             placeholder="Aquisição de material de expediente")
        objeto = st.text_area("Objeto", height=70)
        a, b = st.columns(2)
        responsavel = a.text_input("Responsável")
        local = a.text_input("Local de referência", placeholder="Município/UF")
        data_base = b.date_input("Data-base", value=date.today(),
                                 format="DD/MM/YYYY")
        perfil_id = b.selectbox("Perfil normativo", list(perfil.PERFIS),
                                format_func=lambda p: perfil.PERFIS[p].nome)
        vincular = st.checkbox(
            "Vincular ao processo aberto nesta sessão", value=bool(processo),
            disabled=not processo)
        with st.expander("Critério percentual de análise crítica (opcional)"):
            st.caption("Sinaliza — sem excluir — preço acima de X% da média "
                       "dos demais ou abaixo de Y% dela. É parâmetro desta "
                       "cotação, não limite legal.")
            usar = st.checkbox("Usar critério percentual")
            c1, c2 = st.columns(2)
            elevado = c1.number_input("Elevado acima de (%)", 1, 1000, 30)
            inexequivel = c2.number_input("Inexequível abaixo de (%)", 1, 99, 70)
        criar = st.form_submit_button("Criar cotação", type="primary")
    if st.button("← Minhas Cotações"):
        _ir(LISTA)
        st.rerun()
    if not criar:
        return
    cotacao = cotacoes.criar_cotacao(ctx, {
        "nome": nome, "objeto": objeto, "responsavel": responsavel,
        "local_referencia": local, "data_base": data_base,
        "perfil_normativo": perfil_id,
        "processo_id": processo if vincular else None,
        "criterio_percentual": {"elevado": elevado, "inexequivel": inexequivel}
        if usar else None}, idempotency_key=f"cotacao:{chave}")
    st.session_state.pop("_cot_nova_chave", None)
    _ir(ELABORAR, **{COTACAO: str(cotacao["id"]), ITEM: None})
    st.rerun()


# ---------------------------------------------------------------------------
# Elaborar Cotação — itens | busca e resultados | cesta
# ---------------------------------------------------------------------------
def _render_elaborar() -> None:
    ctx = _ctx()
    cotacao_id = str(st.session_state[COTACAO])
    # Skeleton só enquanto a leitura no banco está de fato acontecendo:
    # com latência real, a forma da tela aparece antes dos dados.
    carregando = st.empty()
    components.render_skeleton(carregando, "Carregando a cotação", linhas=4)
    cotacao = repo.obter_pesquisa(cotacao_id)
    if not cotacao:
        carregando.empty()
        st.warning("Cotação não encontrada ou fora do seu acesso.")
        _ir(LISTA)
        return
    itens = cotacoes.ativos(repo.listar_itens(cotacao_id))
    carregando.empty()
    perfil_atual = perfil.obter(cotacao.get("perfil_normativo"))
    editavel = cotacao.get("estado") not in ("applied", "archived")

    _cabecalho(ctx, cotacao, itens, perfil_atual, editavel)
    if st.session_state.get(LOTE):
        _render_lote(ctx, cotacao, itens)
        return
    if st.session_state.get("cot_painel_relatorio"):
        _render_relatorio_e_aplicacao(ctx, cotacao, itens)

    ativo = next((i for i in itens
                  if str(i["id"]) == str(st.session_state.get(ITEM))), None)
    if ativo is None and itens:
        ativo = itens[0]
        st.session_state[ITEM] = str(ativo["id"])

    # Três REGIÕES com nome: o CSS (`assets/govconnect.css`, "Elaborar
    # Cotação") dá largura útil a cada uma por faixa de tela — lista
    # estreita, busca flexível, cesta legível; em tela média a lista vira
    # faixa no topo e a cesta vem antes dos resultados, para "Concluir
    # item" ficar à vista. As proporções abaixo só valem sem o CSS.
    esquerda, centro, direita = st.columns([1, 2.4, 1.4], gap="medium")
    with esquerda, st.container(key="cot_regiao_itens"):
        _painel_itens(ctx, cotacao, itens, ativo, editavel)
    if ativo is None:
        with centro, st.container(key="cot_regiao_busca"):
            st.info("Inclua o primeiro item à esquerda, ou importe uma "
                    "planilha. Depois escolha o item e pesquise preços, à "
                    "mão ou pela Cotação automática.")
        return
    referencias = repo.listar_referencias(str(ativo["id"]))
    _revisao_vista(ativo)
    with centro, st.container(key="cot_regiao_busca"):
        _painel_busca(ctx, cotacao, ativo, referencias, editavel)
    with direita, st.container(key="cot_regiao_cesta"):
        _painel_cesta(ctx, cotacao, ativo, referencias, perfil_atual, editavel)


def _cabecalho(ctx, cotacao: dict, itens: list[dict], perfil_atual,
               editavel: bool) -> None:
    titulo, botoes = st.columns([2.6, 2.4])
    with titulo:
        versao = int(cotacao.get("versao") or 1)
        st.markdown(f"### {html.escape(str(cotacao.get('nome') or ''))}"
                    + (f" · revisão {versao}" if versao > 1 else ""))
        rotulo, tom = ROTULO_ESTADO.get(str(cotacao.get("estado")), ("", ""))
        _chips([(rotulo, tom), (perfil_atual.nome, ""),
                (f"data-base {precos_ui._data_base(cotacao):%d/%m/%Y}", ""),
                ("vinculada a processo" if cotacao.get("processo_id")
                 else "autônoma", "")])
    with botoes, st.container(key="cot_acoes"):
        b1, b2, b3 = st.columns(3)
        if b1.button("Cotação automática", type="primary",
                     use_container_width=True, disabled=not (editavel and itens),
                     help="Pesquisa em lote, com a seleção determinística da "
                          "cesta; a revisão continua sendo sua."):
            st.session_state["cot_confirmar_lote"] = True
        if b2.button("Relatório", use_container_width=True,
                     disabled=not itens):
            st.session_state["cot_painel_relatorio"] = not st.session_state.get(
                "cot_painel_relatorio")
            st.rerun()
        if b3.button("← Cotações", use_container_width=True):
            _ir(LISTA, **{COTACAO: None, ITEM: None})
            st.session_state.pop(LOTE, None)
            st.rerun()
    minimo = perfil_atual.minimo_referencias
    com_minimo = sum(1 for i in itens if (cesta.na_cesta_do_item(i) or 0) >= minimo)
    concluidos = [i for i in itens if i.get("estado") == "complete"]
    total = sum((Decimal(str(i["preco_total"])) for i in concluidos
                 if i.get("preco_total") not in (None, "")), Decimal(0))
    with st.container(key="cot_kpis"):
        m = st.columns(4)
        m[0].metric("Itens", len(itens))
        m[1].metric(f"Com {minimo}+ considerados",
                    f"{com_minimo}/{len(itens)}")
        m[2].metric("Pendentes", len(itens) - len(concluidos))
        m[3].metric("Valor (itens concluídos)", _moeda(total))
    if st.session_state.get("cot_confirmar_lote"):
        _confirmar_lote(ctx, cotacao, itens)


# ---------------------------------------------------------------------------
# Cotação automática em lote — reentrante, um item por rerun
# ---------------------------------------------------------------------------
def _opcoes_de_busca() -> dict:
    """Fontes e seletor da rodada — num lugar só, trocável nas provas."""
    opcoes = {"fontes": _fontes()}
    seletor = _seletor()
    if seletor is not None:
        opcoes["seletor"] = seletor
    return opcoes


def _fontes():
    return precos_ui._fontes()


def _motor_semantico():
    """Sinônimos para AMPLIAR a busca; None sem motor configurado."""
    return precos_ui._motor_semantico()


def _seletor():
    """
    O seletor roda sempre no modo automático: a triagem determinística
    não custa nada. O Jev só é consultado com a flag dele, no caso
    ambíguo e dentro do teto (ver `precos.seletor`).
    """
    from ..precos import seletor

    return seletor.seletor_padrao()


def _confirmar_lote(ctx, cotacao: dict, itens: list[dict]) -> None:
    sem_preco = [i for i in itens if i.get("estado") in
                 ("pending", "error", "searching", "matching")]
    nao_concluidos = [i for i in itens if i.get("estado") != "complete"]
    with st.container(border=True):
        st.markdown("**Cotação automática**")
        st.caption("Busca nas fontes oficiais e monta a cesta pela regra "
                   "determinística (comparabilidade, natureza de preço, "
                   "unidade comprovada). Decisões que você já tomou numa "
                   "referência não são desfeitas. Nada é concluído sem você.")
        if db.flag_ativa(governanca.FLAG_JEV_PRECOS):
            st.caption("Análise complementar (Jev) ATIVA em homologação: só "
                       "para casos ambíguos, dentro do orçamento, como "
                       "sugestão registrada — nunca aceita sozinha.")
        escopo = st.radio("Itens", [f"Sem pesquisa ou com falha ({len(sem_preco)})",
                                    f"Todos os não concluídos ({len(nao_concluidos)})"],
                          key="cot_escopo_lote")
        a, b = st.columns(2)
        if a.button("Iniciar", type="primary", key="cot_iniciar_lote"):
            alvo = sem_preco if escopo.startswith("Sem") else nao_concluidos
            if escopo.startswith("Todos"):
                for item in alvo:
                    if item.get("estado") in ("review", "incomplete"):
                        repo.mover_item(str(item["id"]), EstadoItem.BUSCANDO,
                                        item["estado"])
            st.session_state[LOTE] = {"ids": [str(i["id"]) for i in alvo],
                                      "tentados": [], "total": len(alvo),
                                      "relato": []}
            st.session_state.pop("cot_confirmar_lote", None)
            st.rerun()
        if b.button("Cancelar", key="cot_cancelar_lote"):
            st.session_state.pop("cot_confirmar_lote", None)
            st.rerun()


def _render_lote(ctx, cotacao: dict, itens: list[dict]) -> None:
    lote = st.session_state[LOTE]
    tentados = set(lote["tentados"])
    feitos = len(tentados)
    # Progresso REAL (itens já tentados, gravados no estado de cada item);
    # o marcador esconde a faixa do topo enquanto este painel fala.
    st.markdown('<span class="gc-progresso-local" hidden></span>',
                unsafe_allow_html=True)
    st.progress(feitos / max(1, lote["total"]),
                text=f"Cotação automática: {feitos} de {lote['total']} item(ns)")
    parar = st.button("Interromper", key="cot_parar_lote",
                      help="O que já foi pesquisado fica salvo.")
    for linha in lote["relato"][-12:]:
        st.text(linha)
    if parar:
        st.session_state.pop(LOTE, None)
        st.rerun()
        return
    with st.spinner("Consultando fontes oficiais…"):
        resultados, restantes = cotacoes.pesquisar_em_lote(
            ctx, str(cotacao["id"]), modo="automatico", item_ids=lote["ids"],
            tamanho=LOTE_POR_PASSO, ja_tentados=tentados,
            **_opcoes_de_busca())
    por_id = {str(i["id"]): i for i in itens}
    for r in resultados:
        numero = int((por_id.get(r.item_id) or {}).get("numero") or 0)
        lote["relato"].append(f"Item {numero:02d} · {r.consideradas} "
                              f"considerado(s) · {r.mensagem[:70]}")
    lote["tentados"] = sorted(tentados)
    if not restantes or not resultados:
        st.session_state.pop(LOTE, None)
        st.success(f"Cotação automática concluída: {len(tentados)} item(ns). "
                   "Revise a cesta de cada um antes de concluir.")
    st.rerun()


# ---------------------------------------------------------------------------
# Itens (coluna da esquerda)
# ---------------------------------------------------------------------------
def _painel_itens(ctx, cotacao: dict, itens: list[dict], ativo: dict | None,
                  editavel: bool) -> None:
    st.markdown("**Itens**")
    filtro = st.text_input("Filtrar itens", key="cot_filtro_itens",
                           placeholder="buscar item", label_visibility="collapsed")
    visiveis = [i for i in itens
                if filtro.strip().casefold() in str(i.get("descricao") or "").casefold()]
    pagina = int(st.session_state.get("cot_pag_itens") or 1)
    paginas = max(1, -(-len(visiveis) // POR_PAGINA_ITENS))
    pagina = min(pagina, paginas)
    minimo = perfil.obter(cotacao.get("perfil_normativo")).minimo_referencias
    with st.container(key="cot_lista_itens"):
        for item in visiveis[(pagina - 1) * POR_PAGINA_ITENS:
                             pagina * POR_PAGINA_ITENS]:
            n = cesta.na_cesta_do_item(item)
            estado = str(item.get("estado") or "pending")
            texto, icone, _ = components.ESTADO_ITEM.get(
                estado, components.ESTADO_ITEM["pending"])
            # Situação ESCRITA, além do ícone e da cor: nunca só cor (F).
            rotulo = (f"**{int(item.get('numero') or 0):02d}** "
                      f"{titulo_curto(item.get('descricao'), 40)} · "
                      f"{texto} · {'sem busca' if n is None else f'{n}/{minimo}'}")
            if st.button(rotulo, key=f"cot_item_{item['id']}", icon=icone,
                         type="primary" if ativo and item["id"] == ativo["id"]
                         else "secondary", use_container_width=True):
                st.session_state[ITEM] = str(item["id"])
                st.rerun()
    if paginas > 1:
        a, b = st.columns(2)
        if a.button("‹", disabled=pagina <= 1, key="cot_itens_ant"):
            st.session_state["cot_pag_itens"] = pagina - 1
            st.rerun()
        if b.button("›", disabled=pagina >= paginas, key="cot_itens_prox"):
            st.session_state["cot_pag_itens"] = pagina + 1
            st.rerun()
    components.render_legenda_estados()
    if not editavel:
        return
    with st.expander("+ Novo item"):
        _form_item(ctx, cotacao, None)
    with st.expander("Importar planilha ou itens do processo"):
        precos_ui.render_importacao(cotacao, itens)


def _form_item(ctx, cotacao: dict, item: dict | None) -> None:
    chave = f"cot_form_item_{item['id'] if item else 'novo'}"
    with st.form(chave, clear_on_submit=item is None):
        descricao = st.text_area("Descrição e especificação *", height=80,
                                 value=str((item or {}).get("descricao") or ""))
        a, b = st.columns(2)
        unidades_aceitas = precos_ui.unidades_do_dicionario()
        atual = str((item or {}).get("unidade") or "UNIDADE")
        unidade = a.selectbox("Unidade *", unidades_aceitas,
                              index=unidades_aceitas.index(atual)
                              if atual in unidades_aceitas else 0)
        quantidade = b.text_input("Quantidade *",
                                  value=_quantidade((item or {}).get("quantidade"))
                                  if item else "")
        c, d = st.columns(2)
        codigo = c.text_input("Código (opcional)",
                              value=str((item or {}).get("codigo") or ""))
        lote = d.text_input("Lote (opcional)",
                            value=str((item or {}).get("lote") or ""))
        salvar = st.form_submit_button("Salvar item", type="primary")
    if not salvar:
        return
    try:
        linha = cotacoes.salvar_item(
            ctx, str(cotacao["id"]),
            {"descricao": descricao, "unidade": unidade,
             "quantidade": quantidade, "codigo": codigo, "lote": lote},
            item_id=str(item["id"]) if item else None,
            revisao_esperada=_revisao_vista(item) if item else None)
    except cotacoes.ErroCotacao as erro:
        st.error(f"Item não salvo: {erro}.")
        return
    st.session_state[ITEM] = str(linha["id"])
    _renovar_revisoes()
    st.success("Item salvo.")
    st.rerun()


# ---------------------------------------------------------------------------
# Busca e resultados (coluna do centro)
# ---------------------------------------------------------------------------
def _ultima_busca(cotacao_id: str, item_id: str) -> dict | None:
    for evento in repo.listar_eventos(cotacao_id, limite=200):
        if str(evento.get("item_id")) == str(item_id) and \
                evento.get("tipo") in ("busca_concluida", "busca_falhou") and \
                (evento.get("payload") or {}).get("diagnostico"):
            return evento
    return None


def _painel_busca(ctx, cotacao: dict, item: dict, referencias: list[dict],
                  editavel: bool) -> None:
    estado = str(item.get("estado") or "pending")
    descricao = str(item.get("descricao") or "")
    curto = titulo_curto(descricao, 90)
    # Título curto + situação no primeiro olhar; a especificação inteira
    # sob demanda (era um parágrafo de 4 linhas antes de qualquer ação).
    st.markdown(f"**Item {int(item.get('numero') or 0):02d}** · "
                f"{html.escape(curto)} &nbsp; {components.selo_de_estado(estado)}")
    if curto != " ".join(descricao.split()):
        with st.expander("Especificação completa"):
            st.markdown(html.escape(descricao))
    _chips([(f"{_quantidade(item.get('quantidade'))} "
             f"{item.get('unidade') or ''}", ""),
            (f"código {item.get('codigo')}" if item.get("codigo") else "", "")])
    if editavel:
        _acoes_do_item(ctx, cotacao, item)

    if editavel and estado != "complete":
        with st.form(f"cot_busca_{item['id']}"):
            termo = st.text_input("Termo da busca",
                                  value=str(item.get("descricao") or ""),
                                  help="A descrição do item continua sendo a "
                                       "referência de comparação; o termo só "
                                       "amplia a consulta.")
            filtros_box = st.expander("Fontes, janela e UF")
            a, b, c = filtros_box.columns([2, 1, 1])
            nomes = {getattr(f.fonte, "id", ""): getattr(f.fonte, "nome", "")
                     for f in _fontes() if getattr(f, "fonte", None)}
            fontes = a.multiselect("Fontes", list(nomes),
                                   default=list(nomes),
                                   format_func=lambda f: nomes.get(f, f))
            # A janela EFETIVA, nunca a gravada: pesquisas antigas guardam
            # 365 dias (regra anterior), e valor fora de [mín, máx]
            # derrubava a tela com StreamlitValueAboveMaxError — visto em
            # produção. A busca já consultava só 180 (`janela_efetiva`).
            janela = b.number_input(
                "Janela (dias)", JANELA_MINIMA, execucao.JANELA_MAXIMA_DIAS,
                max(JANELA_MINIMA,
                    execucao.janela_efetiva(cotacao.get("filtros"))),
                step=30)
            uf = c.text_input("UF", max_chars=2,
                              value=str((cotacao.get("filtros") or {})
                                        .get("uf") or ""))
            literal = filtros_box.checkbox(
                "Apenas o termo digitado (sem ampliação semântica)",
                value=True,
                help="Desmarcado, a camada semântica (quando configurada) "
                     "sugere SINÔNIMOS para ampliar a consulta. A "
                     "comparação continua contra a descrição do item: "
                     "produto apenas parecido não vira preço.")
            m, auto = st.columns(2)
            manual = m.form_submit_button("Pesquisar preços",
                                          use_container_width=True)
            automatico = auto.form_submit_button(
                "Cotação automática deste item", type="primary",
                use_container_width=True)
        if manual or automatico:
            with st.spinner("Consultando fontes oficiais…"):
                resultado = cotacoes.pesquisar_item(
                    ctx, str(cotacao["id"]), str(item["id"]),
                    modo="automatico" if automatico else "manual",
                    termo=termo,
                    filtros={"janela_dias": int(janela),
                             "uf": uf.strip().upper() or None,
                             "fontes": fontes, "literal": literal},
                    motor_semantico=None if literal else _motor_semantico(),
                    **_opcoes_de_busca())
            st.session_state[f"_cot_msg_{item['id']}"] = resultado.mensagem
            st.rerun()

    ultima = _ultima_busca(str(cotacao["id"]), str(item["id"]))
    if ultima:
        p = ultima.get("payload") or {}
        texto = cotacoes.DIAGNOSTICOS.get(p.get("diagnostico"), "")
        tom = {"fonte_indisponivel": st.error, "zero_resultados": st.info,
               "sem_comparaveis": st.warning,
               "amostra_insuficiente": st.warning}.get(p.get("diagnostico"),
                                                       st.success)
        tom(texto)
        desfechos = " · ".join(
            f"{precos_ui.NOME_FONTE.get(f, f)}: "
            f"{precos_ui.ROTULO_DESFECHO.get(d, d)}"
            for f, d in sorted((p.get("desfechos") or {}).items()))
        st.caption(f"Última busca ({p.get('modo')}, "
                   f"{'termo literal' if (p.get('filtros') or {}).get('literal', True) else 'ampliada'}"
                   f") em "
                   f"{str(p.get('em') or ultima.get('criado_em') or '')[:16].replace('T', ' ')}"
                   f" UTC — {desfechos or 'sem desfecho registrado'}")
        if p.get("termos_extras"):
            st.caption("Termos acrescentados à consulta: "
                       + ", ".join(str(x) for x in p["termos_extras"]))
        # encontradas / comparáveis / consideradas / descartadas (pacote
        # de 17/10/2026): o que a fonte devolveu, o que serve de preço, o
        # que está no cálculo e o que ficou de fora — números distintos.
        with st.container(key="cot_metricas_busca"):
            m = st.columns(4)
            m[0].metric("Encontradas", p.get("brutas", 0))
            m[1].metric("Comparáveis", p.get("elegiveis", 0))
            m[2].metric("Consideradas", len(cesta.consideradas(referencias)))
            m[3].metric("Descartadas", max(0, int(p.get("unicas") or 0)
                                           - int(p.get("elegiveis") or 0)))
        consultadas = len(p.get("desfechos") or {})
        partes = [f"{consultadas} fonte(s) consultada(s)"]
        if p.get("fontes_nao_consultadas"):
            partes.append("não consultada(s) por já haver amostra "
                          "suficiente: " + ", ".join(p["fontes_nao_consultadas"]))
        if p.get("nao_gravadas"):
            partes.append(f"{p['nao_gravadas']} candidata(s) contada(s), "
                          "não gravada(s) (teto da cotação automática)")
        st.caption(" · ".join(partes))
        if p.get("saneamento") or any(
                saneamento.desconsiderada_pelo_jev(r)
                or saneamento.em_revisao_pela_triagem(r) for r in referencias):
            # pacote Jev: o resumo da triagem do item, com o ESTADO ATUAL
            # das referências (uma reinclusão já aparece aqui)
            resumo = saneamento.resumo_do_item(
                referencias, int(p.get("unicas") or len(referencias)))
            st.markdown(f"**Triagem:** {saneamento.frase_do_resumo(resumo)}")
    elif not referencias:
        st.caption("Nenhuma busca ainda. Pesquise à mão para escolher as "
                   "referências, ou use a Cotação automática.")
    _render_referencias(ctx, cotacao, item, referencias, editavel)


def _acoes_do_item(ctx, cotacao: dict, item: dict) -> None:
    with st.popover("Ações do item"):
        a, b = st.columns(2)
        if a.button("↑ Subir", key=f"cot_sobe_{item['id']}"):
            cotacoes.mover_item_na_lista(ctx, str(cotacao["id"]),
                                         str(item["id"]), -1)
            st.rerun()
        if b.button("↓ Descer", key=f"cot_desce_{item['id']}"):
            cotacoes.mover_item_na_lista(ctx, str(cotacao["id"]),
                                         str(item["id"]), +1)
            st.rerun()
        st.markdown("**Editar**")
        _form_item(ctx, cotacao, item)
        if item.get("estado") == "complete":
            motivo = st.text_input("Motivo para reabrir",
                                   key=f"cot_reabrir_m_{item['id']}")
            if st.button("Reabrir item", key=f"cot_reabrir_{item['id']}"):
                cotacoes.reabrir_item(ctx, str(cotacao["id"]), str(item["id"]),
                                      motivo)
                st.rerun()
        # Sem justificativa obrigatória (pacote Jev, RF-02): a trilha
        # registra quem retirou e quando; a confirmação só evita o clique
        # acidental no item inteiro.
        confirmar = f"_cot_rem_ok_{item['id']}"
        if not st.session_state.get(confirmar):
            if st.button("Retirar item", key=f"cot_rem_{item['id']}",
                         help="Não apaga: o item e as referências ficam na "
                              "trilha."):
                st.session_state[confirmar] = True
                st.rerun()
        else:
            st.caption("O item sai da cotação; ele e as referências ficam "
                       "na trilha.")
            motivo_rem = st.text_input("Observação (opcional)",
                                       key=f"cot_rem_m_{item['id']}")
            sim, nao = st.columns(2)
            if sim.button("Confirmar retirada", type="primary",
                          key=f"cot_rem_sim_{item['id']}"):
                cotacoes.remover_item(ctx, str(cotacao["id"]),
                                      str(item["id"]), motivo_rem or None)
                st.session_state.pop(confirmar, None)
                st.session_state[ITEM] = None
                st.rerun()
            if nao.button("Cancelar", key=f"cot_rem_nao_{item['id']}"):
                st.session_state.pop(confirmar, None)
                st.rerun()


def _chips_da_referencia(linha: dict, dentro: bool) -> list[tuple[str, str]]:
    status = str(linha.get("status") or "")
    score = linha.get("score")
    try:
        compat = f"{Decimal(str(score)):.0%} comparável" if score not in (None, "") else ""
    except ArithmeticError:
        compat = ""
    inciso = inciso_da_fonte(linha.get("fonte_id"), linha.get("fonte_tipo"))
    unidade_ok = linha.get("valor_unitario_normalizado") not in (None, "")
    natureza = precos_ui.ROTULO_NATUREZA.get(str(linha.get("natureza_valor")),
                                             str(linha.get("natureza_valor")))
    return [
        ("Considerada" if dentro else
         "Desconsiderada pelo Jev" if saneamento.desconsiderada_pelo_jev(linha)
         else "Requer revisão" if saneamento.em_revisao_pela_triagem(linha)
         else {"selected": "Marcada, fora do cálculo", "rejected": "Excluída",
               "manual_review": "Abaixo do piso", "warning": "Sinalizada",
               "candidate": "Candidata"}.get(status, status),
         "success" if dentro else "danger" if status == "rejected" else ""),
        (precos_ui.NOME_FONTE.get(str(linha.get("fonte_id")),
                                  str(linha.get("fonte_nome") or "")), "info"),
        (f"inciso {inciso}" if inciso else "", ""),
        (natureza, "" if linha.get("natureza_valor") in
         ("praticado", "homologado", "contratado", "adjudicado") else "warning"),
        ("unidade OK" if unidade_ok else "unidade não comprovada",
         "" if unidade_ok else "warning"),
        (compat, ""),
        (precos_ui._data_curta(linha.get("data_resultado")
                               or linha.get("data_compra")), ""),
    ]


def _chips_da_sugestao(analise: dict | None) -> list[tuple[str, str]]:
    """O que a triagem disse — sempre como sugestão, nunca como decisão."""
    if not analise:
        return []
    rotulo = {"COMPARABLE": ("regra: comparável", "success"),
              "INCOMPATIBLE": ("regra: não comparável", "danger"),
              "REVIEW_REQUIRED": ("revisão humana", "warning")}.get(
                  analise.get("decisao"), ("", ""))
    saida = [rotulo]
    if analise.get("recomendacao"):
        saida.append((f"Jev {analise['recomendacao']}", "info"))
    return saida


def _render_referencias(ctx, cotacao: dict, item: dict, referencias: list[dict],
                        editavel: bool) -> None:
    if not referencias:
        return
    from ..precos import seletor

    sugestoes = seletor.sugestoes_do_item(
        repo.listar_eventos(str(cotacao["id"]), limite=200), str(item["id"]))
    st.session_state["_cot_sugestoes"] = sugestoes
    escolhidos = precos_ui._render_filtros(referencias)
    visiveis = filtros_mod.aplicar(referencias, escolhidos)
    dentro = {str(r["id"]) for r in cesta.consideradas(referencias)}
    # Retidas pela triagem pré-cesta: seção própria, com o fundamento de
    # cada uma e a reinclusão consciente — nunca escondidas.
    retidas = [r for r in visiveis
               if saneamento.desconsiderada_pelo_jev(r)
               or saneamento.em_revisao_pela_triagem(r)]
    if retidas:
        ids_retidas = {str(r["id"]) for r in retidas}
        visiveis = [r for r in visiveis if str(r["id"]) not in ids_retidas]
        desconsideradas = sum(1 for r in retidas
                              if saneamento.desconsiderada_pelo_jev(r))
        with st.expander(
                f"Desconsideradas pelo Jev ({desconsideradas}) e em revisão "
                f"({len(retidas) - desconsideradas})"):
            st.caption("Ficaram fora da cesta automática com fundamento "
                       "técnico registrado. Os dados originais estão "
                       "preservados; reincluir põe a cotação na cesta "
                       "SINALIZADA, com o seu motivo na memória de cálculo.")
            for linha in retidas:
                _referencia(ctx, cotacao, item, linha, False, editavel)
    # A decisão primeiro: consideradas no topo, depois por comparabilidade
    visiveis = sorted(visiveis, key=lambda r: (
        str(r["id"]) not in dentro, -float(r.get("score") or 0)))
    chave = f"_cot_mostrar_{item['id']}"
    limite = int(st.session_state.get(chave) or POR_PAGINA_REFERENCIAS)
    for linha in visiveis[:limite]:
        _referencia(ctx, cotacao, item, linha, str(linha["id"]) in dentro,
                    editavel)
    if len(visiveis) > limite:
        st.caption(f"Mostrando {limite} de {len(visiveis)} referência(s).")
        if st.button("Ver mais candidatos", key=f"cot_mais_{item['id']}"):
            st.session_state[chave] = limite + POR_PAGINA_REFERENCIAS
            st.rerun()


def _referencia(ctx, cotacao: dict, item: dict, linha: dict, dentro: bool,
                editavel: bool) -> None:
    with st.container(border=True):
        texto, valor = st.columns([4, 1.4])
        with texto:
            st.markdown(html.escape(str(linha.get("descricao_original") or "")[:180]))
            _chips(_chips_da_referencia(linha, dentro)
                   + _chips_da_sugestao(
                       (st.session_state.get("_cot_sugestoes") or {})
                       .get(str(linha["id"]))))
            st.caption(" · ".join(p for p in (
                str(linha.get("orgao") or ""), str(linha.get("uf") or ""),
                str(linha.get("fornecedor") or "")) if p))
        with valor:
            st.markdown(f"**{_moeda(linha.get('valor_unitario_normalizado') or linha.get('valor_unitario_original'))}**")
            st.caption(f"original {_moeda(linha.get('valor_unitario_original'))}"
                       f" / {linha.get('unidade_original') or '—'}")
        motivos = [m for m in (linha.get("motivos") or []) if m]
        if motivos:
            st.caption(_sem_latex("Por quê: " + "; ".join(
                str(m) for m in motivos[-3:])))
        acao, detalhe = st.columns([1.3, 2])
        if editavel and item.get("estado") != "complete":
            retida = saneamento.desconsiderada_pelo_jev(linha) or \
                saneamento.em_revisao_pela_triagem(linha)
            with acao.popover("Tirar da cesta" if dentro else
                              "Reincluir na cesta" if retida else
                              "Usar na cesta", use_container_width=True):
                if retida:
                    st.caption("Esta cotação ficou fora da cesta pela "
                               "triagem (veja o porquê acima). Reincluída, "
                               "ela entra SINALIZADA e o alerta acompanha o "
                               "preço até a emissão.")
                with st.form(f"cot_ref_{linha['id']}"):
                    # retirar não pede justificativa (pacote Jev, RF-02);
                    # incluir pede, porque muda o preço pelo seu juízo
                    motivo = st.text_input(
                        "Observação (opcional)" if dentro
                        else "Motivo da inclusão",
                        placeholder="mesmo produto e unidade; fora da "
                                    "curva; …")
                    ok = st.form_submit_button(
                        "Retirar da cesta" if dentro else "Confirmar")
                if ok:
                    try:
                        cotacoes.alterar_status_referencia(
                            ctx, str(cotacao["id"]), str(item["id"]),
                            str(linha["id"]), incluir=not dentro,
                            motivo=motivo or None,
                            revisao_esperada=_revisao_vista(item))
                    except cotacoes.ErroCotacao as erro:
                        st.error(str(erro))
                        return
                    _renovar_revisoes()
                    st.rerun()
        # Sob demanda: o conteúdo de um expander é montado mesmo fechado,
        # e eram ~15 elementos por referência, 12 referências por página.
        chave_detalhe = f"_cot_det_{linha['id']}"
        aberto = bool(st.session_state.get(chave_detalhe))
        if detalhe.button("Ocultar detalhe" if aberto else "Detalhe e evidência",
                          key=f"cot_detbtn_{linha['id']}",
                          use_container_width=True):
            st.session_state[chave_detalhe] = not aberto
            st.rerun()
        if aberto:
            precos_ui._render_detalhe(linha)


# ---------------------------------------------------------------------------
# Cesta do item (coluna da direita)
# ---------------------------------------------------------------------------
def _painel_cesta(ctx, cotacao: dict, item: dict, referencias: list[dict],
                  perfil_atual, editavel: bool) -> None:
    """
    Ordem de leitura (pacote de 17/10/2026, G3): preço e N/mínimo; o
    PRÓXIMO PASSO (pendências e "Concluir item" juntos, sem rolar até o
    fim); só então os detalhes, recolhidos. Antes, o botão ficava abaixo
    da estatística, do método e do aviso — fora da primeira tela.
    """
    gravado = item.get("estatisticas") or {}
    est = gravado.get("estatisticas") or {}
    n = len(cesta.consideradas(referencias))
    minimo = perfil_atual.minimo_referencias
    with st.container(border=True, key="cot_resumo_cesta"):
        st.markdown('<div class="gc-cesta-legenda">Preço estimado do item</div>'
                    f'<div class="gc-cesta-preco">{html.escape(_moeda(item.get("preco_estimado")))}</div>',
                    unsafe_allow_html=True)
        provisorio = bool(gravado.get("pendencias"))
        _chips([(f"{n}/{minimo} considerados", "success" if n >= minimo
                 else "warning"),
                ("valor provisório" if provisorio and item.get("preco_estimado")
                 else "", "warning"),
                ("exceção registrada" if (gravado.get("decisoes") or {})
                 .get("excecao") else "", "info"),
                (cesta.METODOS_ROTULO.get(str(item.get("metodo") or ""),
                                          str(item.get("metodo") or "")), "")])
        st.caption(f"Total do item: {_moeda(item.get('preco_total'))}")
        _proximo_passo(ctx, cotacao, item, gravado, n, minimo, editavel)
    if est or gravado.get("anomalias"):
        with st.expander("Estatística da cesta"):
            if est:
                cv = est.get("coeficiente_variacao")
                linhas = [
                    "| Diagnóstico | |", "|---|---:|",
                    f"| Média | {_moeda(est.get('media'))} |",
                    f"| Mediana | {_moeda(est.get('mediana'))} |",
                    f"| Menor / maior | {_moeda(est.get('menor'))} / "
                    f"{_moeda(est.get('maior'))} |",
                    f"| Desvio-padrão | {_moeda(est.get('desvio_padrao'))} |",
                    "| Coef. de variação | " + (
                        estatistica.pct(Decimal(str(cv)))
                        if cv not in (None, "") else "—") + " |"]
                st.markdown("\n".join(linhas).replace("$", "\\$"))
            for anomalia in gravado.get("anomalias") or []:
                st.caption(_sem_latex(f"{_moeda(anomalia.get('valor'))}: "
                                      f"{anomalia.get('motivo', '')}"))
    if editavel:
        revisao = _revisao_vista(item)
        precos_ui.render_metodo_do_item(cotacao, item, revisao=revisao)
        precos_ui._render_cotacao(cotacao, item)
    if item.get("justificativa"):
        with st.expander("Memória de cálculo"):
            st.text(str(item.get("justificativa")))


def _proximo_passo(ctx, cotacao: dict, item: dict, gravado: dict, n: int,
                   minimo: int, editavel: bool) -> None:
    """O que falta para fechar ESTE item, com a ação ao lado do aviso."""
    estado = str(item.get("estado") or "pending")
    if estado == EstadoItem.COMPLETO.value:
        st.success("Item concluído.")
        if editavel:
            st.caption("Para mudar, reabra o item em Ações do item.")
        return
    if not editavel:
        return
    if estado == EstadoItem.EM_REVISAO.value:
        pendencias = gravado.get("pendencias") or []
        if pendencias:
            st.markdown("**Resolva antes de concluir**")
            for pendencia in pendencias:
                st.warning(_sem_latex(pendencia))
        _form_concluir(ctx, cotacao, item)
        return
    if estado == EstadoItem.INCOMPLETO.value:
        st.warning(f"Faltam referências: {n} de {minimo} consideradas. "
                   "Amplie a busca, registre cotação de fornecedor ou "
                   "registre a exceção justificada.")
        precos_ui.render_excecao_do_item(cotacao, item,
                                         revisao=_revisao_vista(item))
        return
    if estado == EstadoItem.ERRO.value:
        st.error("A última busca falhou nas fontes. Pesquise de novo.")
        return
    st.info("Pesquise preços para este item, à mão ou pela cotação "
            "automática deste item.")


def _form_concluir(ctx, cotacao: dict, item: dict) -> None:
    pendencias = cesta.pendencias_do_item(item)
    with st.form(f"cot_concluir_{item['id']}"):
        justificativa = st.text_area(
            "Justificativa do revisor (obrigatória)" if pendencias
            else "Observação do revisor (opcional)", height=70)
        concluir = st.form_submit_button("Concluir item", type="primary",
                                         use_container_width=True)
    if not concluir:
        return
    try:
        cotacoes.concluir_item(ctx, str(cotacao["id"]), str(item["id"]),
                               justificativa=justificativa,
                               revisao_esperada=_revisao_vista(item))
    except cotacoes.ErroCotacao as erro:
        # validação recusou: fica no item, com o motivo
        st.error(str(erro))
        return
    # Conflito de versão e erro de banco sobem para `render_cotacoes`
    # ANTES daqui: só a conclusão confirmada avança.
    _renovar_revisoes()
    _avancar_depois_de_concluir(cotacao, item)
    st.rerun()


def _avancar_depois_de_concluir(cotacao: dict, item: dict) -> None:
    """
    Abre o próximo item pendente (pacote de 17/10/2026, G2). O estado é
    RELIDO depois da conclusão; filtro da lista e decisões ficam como
    estavam. Sem próximo, abre o painel de conclusão da cotação.
    """
    itens = cotacoes.ativos(repo.listar_itens(str(cotacao["id"])))
    proximo = cotacoes.proximo_item_para_revisao(itens, str(item["id"]))
    numero = int(item.get("numero") or 0)
    if proximo is None:
        st.session_state["cot_painel_relatorio"] = True
        st.toast(f"Item {numero:02d} concluído. Todos os itens estão "
                 "concluídos — conclua a cotação no painel abaixo.")
        return
    st.session_state[ITEM] = str(proximo["id"])
    # A página da lista acompanha o item aberto, DENTRO do filtro que o
    # servidor digitou (o filtro não é apagado).
    filtro = str(st.session_state.get("cot_filtro_itens") or "").strip().casefold()
    visiveis = [i for i in itens
                if filtro in str(i.get("descricao") or "").casefold()]
    posicao = next((k for k, i in enumerate(visiveis)
                    if str(i["id"]) == str(proximo["id"])), None)
    if posicao is not None:
        st.session_state["cot_pag_itens"] = posicao // POR_PAGINA_ITENS + 1
    st.toast(f"Item {numero:02d} concluído. Abrindo o item "
             f"{int(proximo.get('numero') or 0):02d}.")


# ---------------------------------------------------------------------------
# Relatório, conclusão e aplicação — os serviços que já existem
# ---------------------------------------------------------------------------
def _render_relatorio_e_aplicacao(ctx, cotacao: dict, itens: list[dict]) -> None:
    with st.container(border=True):
        concluir, revisar = st.columns(2)
        faltam = [i for i in itens if i.get("estado") != "complete"]
        if concluir.button("Concluir cotação", type="primary",
                           disabled=bool(faltam) or cotacao.get("estado")
                           in ("completed", "applied", "archived"),
                           help=("Todos os itens precisam estar concluídos."
                                 if faltam else "Fecha a cotação para "
                                 "aplicação ao processo.")):
            cotacoes.concluir_cotacao(ctx, str(cotacao["id"]))
            st.rerun()
        with revisar.popover("Nova revisão"):
            motivo = st.text_input("Motivo da revisão", key="cot_motivo_rev")
            if st.button("Criar revisão", key="cot_criar_rev",
                         disabled=len(motivo.strip()) < 5):
                novo = repo.revisar(str(cotacao["id"]), motivo.strip())
                _ir(ELABORAR, **{COTACAO: str(novo), ITEM: None})
                st.rerun()
        precos_ui._render_relatorios(cotacao)
        precos_ui._render_aplicacao(cotacao)
