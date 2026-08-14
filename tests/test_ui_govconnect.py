"""Contratos regressivos da identidade visual GovConnect.

Estes testes evitam depender da estrutura interna do DOM do Streamlit. Eles
protegem os artefatos e os helpers que formam a fronteira estável do redesign:
assets oficiais derivados, tokens, acessibilidade e navegação funcional.
"""

from __future__ import annotations

import base64
import inspect
import re
import tomllib
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src import state
from src.ui import components


ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = ROOT / "assets" / "brand"
CSS_PATH = ROOT / "assets" / "govconnect.css"


@pytest.mark.parametrize(
    ("nome", "formato", "tamanho_exato", "tamanho_minimo", "quadrado"),
    [
        ("govconnect-lockup.png", "PNG", None, (300, 200), False),
        ("govconnect-symbol.png", "PNG", None, (128, 128), True),
        ("favicon-32.png", "PNG", (32, 32), None, True),
        ("apple-touch-icon.png", "PNG", (180, 180), None, True),
        ("favicon.ico", "ICO", None, (32, 32), True),
    ],
)
def test_assets_da_marca_sao_validos_e_transparentes(
    nome: str,
    formato: str,
    tamanho_exato: tuple[int, int] | None,
    tamanho_minimo: tuple[int, int] | None,
    quadrado: bool,
) -> None:
    caminho = BRAND_DIR / nome
    assert caminho.is_file() and caminho.stat().st_size > 1_000

    with Image.open(caminho) as imagem:
        assert imagem.format == formato
        if tamanho_exato:
            assert imagem.size == tamanho_exato
        if tamanho_minimo:
            assert imagem.width >= tamanho_minimo[0]
            assert imagem.height >= tamanho_minimo[1]
        if quadrado:
            assert imagem.width == imagem.height
        else:
            assert imagem.width > imagem.height
        rgba = imagem.convert("RGBA")
        assert rgba.getchannel("A").getextrema() == (0, 255)


def test_data_uri_e_icone_de_pagina_usam_os_assets_locais() -> None:
    uri = components._asset_data_uri("govconnect-symbol.png")  # noqa: SLF001
    prefixo, carga = uri.split(",", 1)
    assert prefixo == "data:image/png;base64"
    assert base64.b64decode(carga) == (BRAND_DIR / "govconnect-symbol.png").read_bytes()

    icone = components.page_icon()
    assert isinstance(icone, Image.Image)
    assert icone.size == (32, 32)
    assert icone.mode == "RGBA"


def test_tokens_centrais_correspondem_ao_design_system_aprovado() -> None:
    css = CSS_PATH.read_text(encoding="utf-8")
    bloco_raiz = re.search(r":root\s*\{(?P<conteudo>.*?)\n\}", css, re.DOTALL)
    assert bloco_raiz, "o design system deve declarar seus tokens em :root"
    tokens = dict(re.findall(
        r"--([\w-]+)\s*:\s*([^;]+);", bloco_raiz.group("conteudo")
    ))
    esperados = {
        "gc-navy": "#0B1F33",
        "gc-blue": "#164EA6",
        "gc-action": "#2563EB",
        "gc-blue-soft": "#EDF4FD",
        "gc-canvas": "#F6F8FB",
        "gc-login-panel": "#F3F7FC",
        "gc-surface": "#FFFFFF",
        "gc-text": "#172033",
        "gc-muted": "#667085",
        "gc-border": "#DFE5EC",
        "gc-success": "#0F9F8F",
        "gc-success-soft": "#EDF8F5",
        "gc-warning": "#F59E0B",
        "gc-warning-soft": "#FFF5E5",
        "gc-danger": "#DC2626",
        "gc-danger-soft": "#FEF2F2",
        "gc-sidebar-width": "264px",
        "gc-topbar-height": "66px",
    }
    assert {chave: tokens.get(chave) for chave in esperados} == esperados


def test_css_preserva_minimalismo_acessibilidade_e_responsividade() -> None:
    css = CSS_PATH.read_text(encoding="utf-8")
    assert "gradient(" not in css.lower()
    assert "@import" not in css.lower()
    assert "focus-visible" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    # 800px inclui explicitamente o viewport obrigatório de 768px e evita
    # que o layout desktop do Streamlit reserve espaço ao drawer nessa borda.
    assert "@media (max-width: 800px)" in css
    assert "min-height: 100dvh" in css
    assert "font-variant-numeric: tabular-nums" in css
    assert ".gc-step-current" in css
    assert ".gc-step-done" in css
    assert ".gc-step-error" in css
    assert ".gc-action-bar-marker" in css


def test_tema_streamlit_reutiliza_os_tokens_principais() -> None:
    configuracao = tomllib.loads(
        (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    )
    assert configuracao["theme"] == {
        "primaryColor": "#2563EB",
        "backgroundColor": "#F6F8FB",
        "secondaryBackgroundColor": "#FFFFFF",
        "textColor": "#172033",
        "font": "sans serif",
    }


def test_marca_completa_fica_no_login_e_shell_interno_usa_simbolo() -> None:
    fonte_login = inspect.getsource(components.render_login_brand)
    fonte_sidebar = inspect.getsource(components.render_sidebar)
    fonte_topbar = inspect.getsource(components.render_cabecalho)

    assert "govconnect-lockup.png" in fonte_login
    assert "govconnect-symbol.png" in fonte_sidebar
    assert "govconnect-symbol.png" in fonte_topbar
    assert "govconnect-lockup.png" not in fonte_sidebar + fonte_topbar
    assert "Iuan Jardel" not in fonte_sidebar


def test_cabecalhos_escapam_conteudo_e_expoem_semantica(monkeypatch) -> None:
    chamadas: list[tuple[str, bool]] = []
    subheaders: list[str] = []
    streamlit_falso = SimpleNamespace(
        markdown=lambda texto, unsafe_allow_html=False: chamadas.append(
            (texto, unsafe_allow_html)
        ),
        subheader=subheaders.append,
    )
    monkeypatch.setattr(components, "st", streamlit_falso)

    components.render_page_header(
        "Título <script>alert(1)</script>",
        "Descrição <b>não confiável</b>",
        legacy_subheader="Título legado",
    )

    html_renderizado = "\n".join(texto for texto, _ in chamadas)
    assert "<script>" not in html_renderizado
    assert "&lt;script&gt;" in html_renderizado
    assert "&lt;b&gt;não confiável&lt;/b&gt;" in html_renderizado
    assert '<header class="gc-page-header">' in html_renderizado
    assert subheaders == ["Título legado"]


@pytest.mark.parametrize(
    ("sessao", "esperado"),
    [
        ({}, ("nao_salvo", "Não salvo")),
        ({"dados": {"objeto": "x"}}, ("local", "Sessão local")),
        ({"_save_status": "salvando"}, ("salvando", "Salvando…")),
        ({"_save_status": "erro"}, ("erro", "Falha ao salvar")),
        ({"processo_id": "uuid"}, ("salvo", "Salvo")),
    ],
)
def test_status_da_topbar_reflete_estado_real(monkeypatch, sessao, esperado) -> None:
    monkeypatch.setattr(components, "st", SimpleNamespace(session_state=sessao))
    assert components._estado_salvamento() == esperado  # noqa: SLF001


def test_stepper_preserva_keys_callbacks_e_bloqueio_sequencial(monkeypatch) -> None:
    botoes: list[tuple[str, dict]] = []
    marcadores: list[str] = []

    class StreamlitFalso:
        session_state = {
            "dados": {"objeto": "Aquisição"},
            "aprovados": {"dfd"},
        }

        @staticmethod
        def columns(total, gap=None):
            assert total == 6
            assert gap == "small"
            return [nullcontext() for _ in range(total)]

        @staticmethod
        def markdown(texto, unsafe_allow_html=False):
            assert unsafe_allow_html
            marcadores.append(texto)

        @staticmethod
        def button(rotulo, **kwargs):
            botoes.append((rotulo, kwargs))

    monkeypatch.setattr(components, "st", StreamlitFalso())
    monkeypatch.setattr(state, "etapas_navegaveis", lambda: {0, 1, 2})

    components.render_stepper(2)

    assert [rotulo for rotulo, _ in botoes] == [
        "Dados da Demanda",
        "DFD",
        "ETP",
        "TR",
        "Minuta de Edital",
        "Concluído",
    ]
    assert [kwargs["key"] for _, kwargs in botoes] == [
        f"navegar_etapa_{indice}" for indice in range(6)
    ]
    assert [kwargs["disabled"] for _, kwargs in botoes] == [
        False, False, False, True, True, True
    ]
    assert all(kwargs["on_click"] is state.navegar_pelo_stepper
               for _, kwargs in botoes)
    assert [kwargs["args"] for _, kwargs in botoes] == [(i,) for i in range(6)]
    assert any("gc-step-done" in marcador for marcador in marcadores)
    assert sum("gc-step-current" in marcador for marcador in marcadores) == 1
    assert sum('aria-current="step"' in marcador for marcador in marcadores) == 1
