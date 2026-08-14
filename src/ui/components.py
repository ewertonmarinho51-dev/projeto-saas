"""Componentes compartilhados da interface GovConnect / GovDocs.

A camada visual continua sobre os widgets nativos do Streamlit. Os helpers
abaixo não duplicam navegação, autenticação ou persistência: apenas apresentam
os mesmos contratos funcionais com a identidade GovConnect.
"""

from __future__ import annotations

import base64
import html
from functools import lru_cache
from pathlib import Path

import streamlit as st
from PIL import Image

from .. import auth, db, state
from ..config import DOCUMENTOS, ETAPAS
from ..llm import motor_ativo

_ROOT = Path(__file__).resolve().parents[2]
_BRAND_DIR = _ROOT / "assets" / "brand"
_STYLE_PATH = _ROOT / "assets" / "govconnect.css"


@lru_cache(maxsize=None)
def _asset_data_uri(nome: str) -> str:
    caminho = _BRAND_DIR / nome
    mime = "image/png" if caminho.suffix.lower() == ".png" else "image/x-icon"
    dados = base64.b64encode(caminho.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{dados}"


def page_icon() -> Image.Image:
    """Ícone oficial do produto para ``st.set_page_config``."""
    with Image.open(_BRAND_DIR / "favicon-32.png") as imagem:
        return imagem.copy()


def aplicar_estilo() -> None:
    """Injeta o design system central, sem carregar fontes ou scripts externos."""
    st.markdown(f"<style>{_STYLE_PATH.read_text(encoding='utf-8')}</style>",
                unsafe_allow_html=True)


def render_login_brand() -> None:
    """Painel institucional usado somente nas portas de entrada."""
    logo = _asset_data_uri("govconnect-lockup.png")
    st.markdown(
        f"""
        <section class="gc-login-shell" aria-label="GovConnect">
            <img class="gc-login-logo" src="{logo}"
                 alt="GovConnect — Licitações, Estratégia, Resultados">
            <div class="gc-login-copy">
                <h1>Planejamento público, com método.</h1>
                <p>Elabore os documentos da fase preparatória em um fluxo
                seguro, rastreável e alinhado à Lei nº 14.133/2021.</p>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_login_panel_marker() -> None:
    """Marca o painel de acesso para o CSS responsivo do layout bipartido."""
    st.markdown('<span class="gc-login-panel" aria-hidden="true"></span>',
                unsafe_allow_html=True)


def _iniciais(usuario: dict | None) -> str:
    nome = str((usuario or {}).get("nome") or (usuario or {}).get("login") or "")
    partes = [parte for parte in nome.split() if parte]
    if not partes:
        return "GC"
    if len(partes) == 1:
        return partes[0][:2].upper()
    return (partes[0][0] + partes[-1][0]).upper()


def _contexto_topbar() -> tuple[str, str]:
    pagina = st.session_state.get("pagina") or "Novo processo"
    if pagina in {"Base de Conhecimento", "Administração", "Governança"}:
        return "GovDocs", str(pagina)

    etapa = int(st.session_state.get("etapa") or 0)
    if etapa == 0:
        atual = "Novo processo"
    elif 1 <= etapa <= 4:
        doc_key = state.doc_da_etapa(etapa)
        atual = DOCUMENTOS[doc_key]["sigla"]
    else:
        atual = "Processo concluído"
    return "Processos", atual


def _estado_salvamento() -> tuple[str, str]:
    estado = str(st.session_state.get("_save_status") or "")
    if estado == "salvando":
        return estado, "Salvando…"
    if estado == "erro":
        return estado, "Falha ao salvar"
    if estado == "salvo" or st.session_state.get("processo_id"):
        return "salvo", "Salvo"
    if st.session_state.get("dados"):
        return "local", "Sessão local"
    return "nao_salvo", "Não salvo"


def render_cabecalho() -> None:
    """Topbar interna com breadcrumb e status derivado do estado real."""
    origem, atual = _contexto_topbar()
    estado, rotulo_estado = _estado_salvamento()
    usuario = auth.usuario_logado()
    iniciais = _iniciais(usuario)
    simbolo = _asset_data_uri("govconnect-symbol.png")
    st.markdown(
        f"""
        <a class="gc-skip-link" href="#gc-main-content">Pular para o conteúdo</a>
        <span id="gc-main-content" class="gc-visually-hidden" tabindex="-1">Conteúdo principal</span>
        <header class="gc-topbar">
            <img class="gc-topbar-brand" src="{simbolo}"
                 alt="Símbolo GovConnect">
            <nav class="gc-breadcrumb" aria-label="Breadcrumb">
                {html.escape(origem)} &nbsp;/&nbsp;
                <strong>{html.escape(atual)}</strong>
            </nav>
            <div class="gc-topbar-meta">
                <span class="gc-save-state" data-state="{html.escape(estado)}"
                      role="status">{html.escape(rotulo_estado)}</span>
                <span class="gc-topbar-avatar" aria-label="Usuário {html.escape(iniciais)}">
                    {html.escape(iniciais)}
                </span>
            </div>
        </header>
        """,
        unsafe_allow_html=True,
    )


def render_page_header(titulo: str, descricao: str,
                       *, legacy_subheader: str | None = None) -> None:
    """Cabeçalho semântico de uma página; mantém heading nativo para testes."""
    st.markdown(
        f"""
        <header class="gc-page-header">
            <h1>{html.escape(titulo)}</h1>
            <p>{html.escape(descricao)}</p>
        </header>
        """,
        unsafe_allow_html=True,
    )
    if legacy_subheader:
        st.markdown('<span class="gc-legacy-heading-marker"></span>',
                    unsafe_allow_html=True)
        st.subheader(legacy_subheader)


def render_section_heading(titulo: str, descricao: str = "") -> None:
    detalhe = f"<p>{html.escape(descricao)}</p>" if descricao else ""
    st.markdown(
        f'<div class="gc-section-heading"><h2>{html.escape(titulo)}</h2>{detalhe}</div>',
        unsafe_allow_html=True,
    )


def render_guidance(texto: str) -> None:
    st.markdown(
        f'<aside class="gc-guidance" aria-label="Orientação">'
        f'<strong>Orientação</strong><p>{html.escape(texto)}</p></aside>',
        unsafe_allow_html=True,
    )


def render_document_skeleton(alvo, sigla: str) -> None:
    """Prévia de carregamento com a geometria aproximada de um documento."""
    alvo.markdown(
        f"""
        <section class="gc-document-skeleton" role="status" aria-live="polite"
                 aria-label="Gerando {html.escape(sigla)}">
            <span class="gc-visually-hidden">Gerando {html.escape(sigla)}…</span>
            <span class="gc-skeleton-line gc-skeleton-title"></span>
            <span class="gc-skeleton-line"></span>
            <span class="gc-skeleton-line"></span>
            <span class="gc-skeleton-line gc-skeleton-short"></span>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_stepper(etapa_atual: int) -> None:
    """Navegação entre etapas disponíveis, preservando keys e callbacks."""
    disponiveis = state.etapas_navegaveis()
    aprovados = set(st.session_state.get("aprovados") or set())
    dados = bool(st.session_state.get("dados"))
    colunas = st.columns(len(ETAPAS), gap="small")
    for i, nome in enumerate(ETAPAS):
        rotulo = nome.split(". ", 1)[-1]
        if i == etapa_atual:
            classe = "gc-step-current"
        elif i == 0 and dados:
            classe = "gc-step-done"
        elif 1 <= i <= 4 and state.doc_da_etapa(i) in aprovados:
            classe = "gc-step-done"
        elif i == 5 and i < etapa_atual:
            classe = "gc-step-done"
        else:
            classe = "gc-step-future"
        aria_current = ' aria-current="step"' if i == etapa_atual else ""
        with colunas[i]:
            st.markdown(
                f'<span class="gc-step-marker {classe}"{aria_current}></span>',
                unsafe_allow_html=True,
            )
            st.button(
                rotulo,
                key=f"navegar_etapa_{i}",
                type="secondary",
                disabled=i not in disponiveis,
                help=("Abrir esta etapa" if i in disponiveis else
                      "Conclua e aprove as etapas anteriores para acessar."),
                use_container_width=True,
                on_click=state.navegar_pelo_stepper,
                args=(i,),
            )


def render_base_legal(texto: str) -> None:
    st.markdown(f'<div class="gc-base-legal">{html.escape(texto)}</div>',
                unsafe_allow_html=True)


def render_success_banner() -> None:
    st.markdown(
        """
        <section class="gc-success-banner" role="status">
            <div>
                <h2>Dossiê validado com sucesso</h2>
                <p>Os documentos foram revisados e aprovados para emissão.</p>
            </div>
            <span class="gc-status-badge">Pronto para emissão</span>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_summary_strip(total_documentos: int, fatos_pendentes: int) -> None:
    st.markdown(
        f"""
        <section class="gc-summary-strip" aria-label="Resumo do processo">
            <div class="gc-summary-item"><strong>{total_documentos} documentos</strong></div>
            <div class="gc-summary-item" data-tone="success"><strong>Validação concluída</strong></div>
            <div class="gc-summary-item" data-tone="warning"><strong>{fatos_pendentes} fatos para confirmar</strong></div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_processos_salvos() -> None:
    """Painel de processos persistidos no Supabase (retomar / excluir)."""
    if not db.disponivel():
        st.caption("Nenhum processo salvo nesta sessão local.")
        return

    if st.session_state.processo_id:
        st.caption(f"Processo atual: {st.session_state.processo_id[:8]}…")

    usuario = auth.usuario_logado()
    filtro = None if auth.eh_admin() else (usuario or {}).get("id")
    try:
        processos = db.listar_processos(usuario_id=filtro)
    except db.ErroBanco as erro:
        st.warning(str(erro))
        return

    if not processos:
        st.caption("Nenhum processo salvo ainda.")
        return

    rotulos = {db.rotulo_processo(p): p for p in processos}
    escolha = st.selectbox(
        "Retomar processo",
        list(rotulos),
        index=None,
        placeholder="Selecione um processo…",
        help="O andamento é salvo automaticamente a cada etapa aprovada.",
    )
    col_abrir, col_excluir = st.columns(2)
    if col_abrir.button("Abrir", use_container_width=True, disabled=not escolha):
        try:
            proc = db.carregar_processo(rotulos[escolha]["id"])
            if proc:
                state.carregar_processo_salvo(proc)
            else:
                st.warning("Processo não encontrado. Pode ter sido excluído.")
        except db.ErroBanco as erro:
            st.warning(str(erro))
    if col_excluir.button("Excluir", use_container_width=True, disabled=not escolha):
        try:
            db.excluir_processo(rotulos[escolha]["id"])
            if st.session_state.processo_id == rotulos[escolha]["id"]:
                st.session_state.processo_id = None
                st.session_state["_save_status"] = "nao_salvo"
            st.rerun()
        except db.ErroBanco as erro:
            st.warning(str(erro))


def render_sidebar() -> None:
    """Shell interno compacto; não cria rotas ou ações sem implementação."""
    with st.sidebar:
        simbolo = _asset_data_uri("govconnect-symbol.png")
        st.markdown(
            f'<div class="gc-sidebar-brand"><img src="{simbolo}" '
            'alt="Símbolo GovConnect"></div>',
            unsafe_allow_html=True,
        )

        usuario = auth.usuario_logado()
        if auth.eh_admin():
            opcoes = ["Novo processo", "Base de Conhecimento", "Administração"]
            from . import governanca_ui

            if governanca_ui.disponivel():
                opcoes.append("Governança")
            if st.session_state.get("pagina") == "Assistente de Documentos":
                st.session_state.pagina = "Novo processo"
            if st.session_state.get("pagina") not in opcoes:
                st.session_state.pagina = "Novo processo"
            st.radio("Navegação", options=opcoes, key="pagina",
                     label_visibility="collapsed")
        else:
            st.markdown('<nav class="gc-sidebar-current" aria-current="page">'
                        'Novo processo</nav>', unsafe_allow_html=True)

        with st.expander("Processos salvos"):
            _render_processos_salvos()

        if usuario:
            papel = (usuario.get("cargo") or
                     ("Administrador" if usuario.get("papel") == "admin" else "Usuário"))
            st.markdown(
                f"""
                <div class="gc-profile">
                    <span class="gc-profile-avatar">{html.escape(_iniciais(usuario))}</span>
                    <div>
                        <div class="gc-profile-name">{html.escape(str(usuario.get('nome') or usuario.get('login') or 'Usuário'))}</div>
                        <div class="gc-profile-role">{html.escape(papel)}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown('<span class="gc-logout-marker"></span>',
                        unsafe_allow_html=True)
            if st.button("Sair", use_container_width=True):
                auth.sair()
                st.rerun()

        with st.expander("Ambiente"):
            motor = motor_ativo()
            if motor == "openai":
                st.caption("Motor de IA: OpenAI (principal)")
            elif motor == "gemini":
                st.caption("Motor de IA: Gemini (fallback)")
            else:
                st.caption("Motor de IA: não configurado")
            if auth.eh_admin():
                st.toggle(
                    "Modo Demonstração (sem IA)",
                    key="modo_demo",
                    help="Gera minutas-esqueleto offline, sem consumir a API.",
                )
