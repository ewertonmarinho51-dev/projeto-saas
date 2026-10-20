"""
G3–G5 (pacote de 17/10/2026) — layout, sidebar, carregamento, movimento
e estados.

O comportamento VISUAL foi medido no navegador (capturas e medidas em
`docs/cotacoes/ux/antes` e `docs/cotacoes/ux/depois`). Estas provas travam
o que o navegador mediu, para que uma edição de CSS não desfaça em
silêncio:

* sidebar recolhível pelo controle NATIVO: largura só quando aberta, o
  botão de recolher visível, a barra de ferramentas de pé só para o botão
  de reabrir, topbar acompanhando o estado;
* faixa de topo unidirecional, que some quando a tela já mostra progresso;
* nenhuma animação de vai e volta em carregamento, nenhum ornamento
  infinito no GovBot, reduced-motion cobrindo tudo;
* Elaborar Cotação por espaço útil (container query), cesta antes dos
  resultados no estreito;
* estados de item com palavra + ícone + tom, nunca só cor;
* skeleton com `aria-busy` e só onde há carga.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.ui import components

RAIZ = Path(__file__).resolve().parents[1]
CSS = (RAIZ / "assets" / "govconnect.css").read_text(encoding="utf-8")
LOADING = (RAIZ / "assets" / "loading" / "loading.css").read_text(
    encoding="utf-8")
GOVBOT = (RAIZ / "assets" / "govbot" / "govbot.css").read_text(
    encoding="utf-8")


def _bloco(css: str, seletor: str) -> str:
    inicio = css.index(seletor)
    return css[inicio:css.index("}", inicio)]


# ---------------------------------------------------------------------------
# G4 — sidebar e shell
# ---------------------------------------------------------------------------
def test_largura_fixa_so_com_a_sidebar_aberta():
    """Antes a largura era forçada nos DOIS estados: recolher não recolhia."""
    assert re.search(r'section\[data-testid="stSidebar"\]\s*\{[^}]*'
                     r'width:\s*var\(--gc-sidebar-width\)', CSS) is None
    aberta = _bloco(CSS, 'section[data-testid="stSidebar"][aria-expanded="true"] {')
    assert "width: var(--gc-sidebar-width) !important" in aberta
    assert "border-radius: 14px" in aberta


def test_controles_nativos_de_recolher_e_reabrir_visiveis_e_nomeados():
    cabecalho = _bloco(CSS, 'section[data-testid="stSidebar"] '
                            '[data-testid="stSidebarHeader"] {')
    assert "display: none" not in cabecalho
    barra = _bloco(CSS, '[data-testid="stToolbar"] {')
    assert "display: block !important" in barra
    assert 'content: "Recolher menu"' in CSS
    assert 'content: "Abrir menu"' in CSS
    # o resto da barra do Streamlit continua escondido
    assert '[data-testid="stMainMenu"]' in CSS


def test_topbar_acompanha_a_sidebar_recolhida():
    regra = 'body:has(section[data-testid="stSidebar"][aria-expanded="false"]) .gc-topbar'
    assert regra in CSS
    assert "left: 0" in _bloco(CSS, regra + " {")


def test_transicao_do_shell_curta_e_sem_js():
    assert "--gc-shell-ms: 200ms" in CSS
    for arquivo in (RAIZ / "src" / "ui").glob("*.py"):
        assert "stSidebarCollapseButton" not in arquivo.read_text(
            encoding="utf-8"), arquivo.name


def test_sidebar_recolhida_no_celular_por_padrao():
    app = (RAIZ / "app.py").read_text(encoding="utf-8")
    assert 'initial_sidebar_state="auto"' in app


# ---------------------------------------------------------------------------
# G5 — barra de topo e movimento
# ---------------------------------------------------------------------------
def test_faixa_de_topo_unidirecional_e_sem_loop():
    assert "gc-rerun-faixa" not in CSS
    regra = _bloco(CSS, '.stApp[data-test-script-state="running"]::before {')
    assert "infinite" not in regra
    avanco = CSS[CSS.index("@keyframes gc-rerun-avanco"):]
    avanco = avanco[:avanco.index("}\n}") + 3]
    assert "from { transform: scaleX(0); }" in avanco
    assert "to { transform: scaleX(0.9); }" in avanco      # não chega ao fim


def test_faixa_some_quando_a_tela_ja_mostra_o_andamento():
    assert re.search(r'\.stApp\[data-test-script-state="running"\]:has\('
                     r'\[data-testid="stSpinner"\],\s*\.gc-progresso-local,'
                     r'\s*\.gc-generation-overlay\)::before\s*\{\s*display: none',
                     CSS)


@pytest.mark.parametrize("css, nome", [(CSS, "govconnect"),
                                       (LOADING, "loading")],
                         ids=["govconnect", "loading"])
def test_nenhum_carregamento_vai_e_volta(css, nome):
    """O padrão 0%/100% → 50% em scaleX era o 'vai e volta'."""
    assert not re.search(r"0%,\s*100%\s*\{\s*transform:\s*scaleX", css), nome


def test_barra_de_geracao_corre_num_sentido_so():
    quadro = LOADING[LOADING.index("@keyframes gc-generation-motion"):]
    assert "translateX(-100%)" in quadro and "translateX(300%)" in quadro


def test_govbot_sem_ornamento_infinito():
    for nome in ("govbot-float", "govbot-confetti", "govbot-celebrate"):
        uso = re.search(rf"animation:\s*{nome}[^;]*;", GOVBOT).group(0)
        assert "infinite" not in uso, uso


def test_reduced_motion_cobre_faixa_e_geracao():
    reduzido = CSS.split("@media (prefers-reduced-motion: reduce)")[1]
    assert 'data-test-script-state="running"' in reduzido
    assert "@media(prefers-reduced-motion:reduce)" in LOADING


def test_rolagem_e_atalho_de_teclado_sem_animacao():
    assert "scroll-behavior: smooth" not in CSS
    assert "transition" not in _bloco(CSS, ".gc-skip-link {")


# ---------------------------------------------------------------------------
# G3 — Elaborar Cotação por espaço útil
# ---------------------------------------------------------------------------
def test_faixas_por_espaco_util_e_cesta_antes_no_estreito():
    assert "container: gc-conteudo / inline-size" in CSS
    assert "@container gc-conteudo (max-width: 1060px)" in CSS
    estreito = CSS[CSS.index("@container gc-conteudo (max-width: 720px)"):]
    cesta = estreito[estreito.index(".st-key-cot_regiao_cesta) {"):]
    assert "order: 1" in cesta[:80]


def test_regioes_nomeadas_na_tela():
    fonte = (RAIZ / "src" / "ui" / "cotacoes_ui.py").read_text(encoding="utf-8")
    for chave in ("cot_regiao_itens", "cot_regiao_busca", "cot_regiao_cesta",
                  "cot_lista_itens", "cot_acoes", "cot_resumo_cesta"):
        assert f'key="{chave}"' in fonte, chave
    assert "[1.05, 2.3, 1.35]" not in fonte


# ---------------------------------------------------------------------------
# Estados — palavra + ícone + tom
# ---------------------------------------------------------------------------
def test_sete_estados_distintos_nunca_so_cor():
    estados = components.ESTADO_ITEM
    assert set(estados) == {"pending", "searching", "matching", "review",
                            "incomplete", "complete", "error"}
    assert len({texto for texto, _, _ in estados.values()}) == 7
    assert len({icone for _, icone, _ in estados.values()}) == 7
    for estado, (texto, icone, tom) in estados.items():
        selo = components.selo_de_estado(estado)
        assert texto in selo and icone in selo and selo.startswith(f":{tom}-badge[")


def test_concluido_verde_erro_vermelho_falta_ambar():
    assert components.ESTADO_ITEM["complete"][2] == "green"
    assert components.ESTADO_ITEM["error"][2] == "red"
    assert components.ESTADO_ITEM["incomplete"][2] == "orange"


def test_skeleton_anuncia_ocupado_e_tem_forma():
    class Alvo:
        html = ""

        def markdown(self, texto, **_):
            Alvo.html = texto

    components.render_skeleton(Alvo(), "Carregando a cotação", linhas=4)
    assert 'aria-busy="true"' in Alvo.html and 'role="status"' in Alvo.html
    assert Alvo.html.count("gc-skeleton-line") == 4
    assert "Carregando a cotação" in Alvo.html
