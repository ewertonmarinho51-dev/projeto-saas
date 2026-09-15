"""Contratos do componente local GovBot (Streamlit Components v2)."""

from __future__ import annotations

import importlib.util
import re
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "govbot"
HTML = ASSETS / "govbot.html"
CSS = ASSETS / "govbot.css"
JS = ASSETS / "govbot.js"
SVG = ASSETS / "mascot.svg"
PYTHON_ADAPTER = ROOT / "src" / "ui" / "govbot_component.py"

VISUAL_STATES = {
    "IDLE",
    "HOVER",
    "LISTENING",
    "THINKING",
    "WORKING",
    "SUGGESTION",
    "APPLYING",
    "SUCCESS",
    "ATTENTION",
    "CELEBRATE",
    "ERROR",
}
EVENT_KEYS = {
    "request_id",
    "event_type",
    "text",
    "focus",
    "proposal_id",
    "draft",
}


def _read(path: Path) -> str:
    assert path.is_file(), f"arquivo obrigatório ausente: {path}"
    return path.read_text(encoding="utf-8")


def test_pacote_visual_e_local_e_usa_um_unico_svg():
    assert {path.name for path in ASSETS.iterdir()} == {
        "govbot.html",
        "govbot.css",
        "govbot.js",
        "mascot.svg",
    }
    assert len(list(ASSETS.glob("*.svg"))) == 1
    assert not list(ASSETS.glob("*.gif"))
    assert not list(ASSETS.glob("*.png"))
    ET.parse(SVG)

    html = _read(HTML)
    adapter = _read(PYTHON_ADAPTER)
    assert "<!-- GOVBOT_MASCOT -->" in html
    assert 'st.components.v2.component(' in adapter
    assert 'isolate_styles=True' in adapter
    assert 'unsafe_allow_html' not in adapter


def test_svg_expoe_estado_e_olhos_independentes():
    svg = _read(SVG)
    javascript = _read(JS)
    css = _read(CSS)

    assert 'id="govbot-mascot"' in svg
    assert 'data-state="IDLE"' in svg
    assert 'id="govbot-left-eye"' in svg
    assert 'id="govbot-right-eye"' in svg
    assert 'data-left-eye=' in svg
    assert 'data-right-eye=' in svg
    assert "--left-eye-x" in css
    assert "--right-eye-x" in css

    for state in VISUAL_STATES:
        assert f'"{state}"' in javascript
        assert f'data-state="{state}"' in css


def test_frontend_emite_um_unico_trigger_com_evento_minimo():
    javascript = _read(JS)
    calls = re.findall(r"setTriggerValue\s*\(", javascript)
    assert len(calls) == 1
    assert 'setTriggerValue("event", {' in javascript

    trigger_block = javascript.split('setTriggerValue("event", {', 1)[1]
    trigger_block = trigger_block.split("});", 1)[0]
    present = {
        key for key in EVENT_KEYS
        if re.search(rf"\b{re.escape(key)}\s*:", trigger_block)
    }
    assert present == EVENT_KEYS
    assert 'emit("message"' in javascript
    assert 'emit("apply_proposal"' in javascript
    assert 'emit("undo"' in javascript


def test_adapter_dom_limita_foco_e_rascunho_a_widgets_reconhecidos():
    javascript = _read(JS)
    assert '[class*="st-key-govbot_campo_"]' in javascript
    assert '[class*="st-key-editor_"]' in javascript
    assert 'document.querySelectorAll(FORM_FIELD_SELECTOR)' in javascript
    assert 'document.addEventListener("focusin"' in javascript
    assert "KNOWN_FORM_FIELDS = Object.freeze" in javascript
    assert 'editor_itens_' in javascript
    assert 'key === "itens"' in javascript
    assert "PROACTIVE_COOLDOWN_MS = 90000" in javascript
    assert "sessionStorage" in javascript


def test_teclado_aria_e_abertura_nao_roubam_foco():
    html = _read(HTML)
    javascript = _read(JS)

    assert html.count('aria-live="polite"') >= 2
    assert 'aria-live="assertive"' in html
    assert 'role="log"' in html
    assert 'aria-label="Assistente GovBot"' in html
    assert 'aria-describedby="govbot-input-help"' in html

    assert 'event.key.toLowerCase() === "g"' in javascript
    assert 'event.altKey' in javascript
    assert 'event.key === "Escape"' in javascript
    assert 'event.key === "Enter"' in javascript
    assert '!event.shiftKey' in javascript
    assert 'event.key !== "Tab"' in javascript
    assert javascript.count("composer.focus(") == 1
    assert 'launcher.addEventListener("click", onLauncherClick)' in javascript


def test_layout_tem_painel_drawer_e_bottom_sheet():
    css = _read(CSS).lower()
    assert "width: 300px" in css
    assert "min-width: 300px" in css
    assert "@media (min-width: 801px) and (max-width: 1024px)" in css
    assert "@media (max-width: 800px)" in css
    assert "max-height: min(74dvh, 650px)" in css
    assert ".govbot-launcher" in css
    assert "position: fixed" in css


def test_movimento_reduzido_e_pausado_quando_invisivel():
    css = _read(CSS)
    javascript = _read(JS)
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert 'matchMedia("(prefers-reduced-motion: reduce)")' in javascript
    assert "IntersectionObserver" in javascript
    assert "document.hidden" in javascript
    assert 'document.addEventListener("visibilitychange"' in javascript
    assert 'root.classList.toggle("is-paused"' in javascript


def test_renderer_e_reentrante_e_nao_duplica_timers_ou_listeners():
    javascript = _read(JS)
    assert javascript.count("let inViewport = true;") == 1
    assert javascript.count("function scheduleBlink() {") == 1
    assert "blinkTimer = globalThis.setTimeout(() => {" in javascript
    assert 'const CLEANUP_SLOT = Symbol.for("govdocs.govbot.cleanup");' in javascript
    assert 'const previousCleanup = root[CLEANUP_SLOT];' in javascript
    assert 'if (typeof previousCleanup === "function") previousCleanup();' in javascript
    assert "root[CLEANUP_SLOT] = cleanup;" in javascript
    assert "if (cleanedUp) return;" in javascript


def test_frontend_bloqueia_emissoes_concorrentes_ate_o_rerun():
    javascript = _read(JS)
    assert "let eventPending = false;" in javascript
    assert "if (eventPending) return;" in javascript
    assert "eventPending = true;" in javascript
    assert "composer.disabled = true;" in javascript
    assert "sendButton.disabled = true;" in javascript
    assert "undoButton.disabled = true;" in javascript


def test_marcador_global_e_removido_ao_fechar_e_desmontar():
    javascript = _read(JS)
    assert 'document.body.dataset.govbot = "open"' in javascript
    assert javascript.count("delete document.body.dataset.govbot") >= 2
    assert 'setOpen(savedOpen === null ? firstOpen' in javascript


def test_conteudo_dinamico_vira_texto_e_nao_markup_executavel():
    sources = "\n".join((_read(HTML), _read(JS), _read(PYTHON_ADAPTER)))
    normalized = sources.casefold()
    forbidden = (
        "innerhtml",
        "outerhtml",
        "insertadjacenthtml",
        "document.write",
        "eval(",
        "new function(",
    )
    assert [token for token in forbidden if token in normalized] == []
    assert javascript_uses_text_nodes(_read(JS))
    assert not re.search(r"\b(fetch|xmlhttprequest|websocket)\b", normalized)


def javascript_uses_text_nodes(javascript: str) -> bool:
    return javascript.count(".textContent =") >= 10


def _load_adapter(monkeypatch, result):
    registrations = []
    mounts = []

    def mount(**kwargs):
        mounts.append(kwargs)
        return result

    def component(name, **kwargs):
        registrations.append((name, kwargs))
        return mount

    streamlit_stub = types.SimpleNamespace(
        components=types.SimpleNamespace(
            v2=types.SimpleNamespace(component=component),
        )
    )
    monkeypatch.setitem(sys.modules, "streamlit", streamlit_stub)
    module_name = "_govbot_component_contract_test"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    spec = importlib.util.spec_from_file_location(module_name, PYTHON_ADAPTER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, registrations, mounts


def test_wrapper_v2_registra_uma_vez_e_retorna_so_evento(monkeypatch):
    event = {
        "request_id": "req-1",
        "event_type": "message",
        "text": "Explique este campo",
        "focus": "objeto",
        "proposal_id": None,
        "draft": {"objeto": "rascunho local"},
    }
    module, registrations, mounts = _load_adapter(
        monkeypatch, types.SimpleNamespace(event=event)
    )

    assert module.render_govbot({"state": "IDLE"}) == event
    assert module.render_govbot({"state": "SUCCESS"}, key="segundo") == event
    assert len(registrations) == 1
    name, definition = registrations[0]
    assert name == "govdocs_govbot"
    assert definition["isolate_styles"] is True
    assert 'id="govbot-mascot"' in definition["html"]
    assert "<!-- GOVBOT_MASCOT -->" not in definition["html"]
    assert len(mounts) == 2
    assert mounts[0]["key"] == "govbot"
    assert mounts[0]["width"] == "content"
    assert mounts[0]["height"] == "content"
    assert set(mounts[0]) == {
        "data", "key", "width", "height", "on_event_change"
    }


def test_wrapper_rejeita_view_model_nao_json_e_ignora_resultado_sem_evento(monkeypatch):
    module, _registrations, _mounts = _load_adapter(monkeypatch, {"event": None})
    assert module.render_govbot({"state": "IDLE"}) is None

    with pytest.raises(TypeError, match="dicionário"):
        module.render_govbot([])
    with pytest.raises(TypeError, match="serializável em JSON"):
        module.render_govbot({"invalid": object()})
    with pytest.raises(TypeError, match="serializável em JSON"):
        module.render_govbot({"invalid": float("nan")})
    with pytest.raises(ValueError, match="string não vazia"):
        module.render_govbot({}, key=" ")


# ---------------------------------------------------------------------------
# Minimizar — o X recolhe o painel e o ícone flutuante assume
#
# O defeito não era handler ausente: `closeButton.addEventListener` sempre
# existiu. Era que o fechar nunca saía do navegador. O Python guarda
# `open` e remonta o componente a cada rerun do Streamlit com esse valor;
# como ninguém avisava o servidor, `open` continuava `True` e a montagem
# seguinte reabria o painel. Para quem usa, "o X não funciona".
# ---------------------------------------------------------------------------
def test_minimizar_avisa_o_python():
    """Sem isto, o estado do painel morre no navegador a cada rerun."""
    javascript = _read(JS)
    assert 'emitUi("minimizar")' in javascript
    assert 'emitUi("expandir")' in javascript


def test_o_x_continua_ligado_ao_handler():
    javascript = _read(JS)
    assert 'closeButton.addEventListener("click", closeAndRestoreFocus)' in \
        javascript


def test_minimizar_nao_passa_pelo_caminho_de_mensagem():
    """
    `emit` marca `eventPending`, desabilita o compositor e espera resposta
    do modelo. Minimizar não pergunta nada ao GovBot — bloquear a caixa de
    texto por causa de um clique no X seria pior que o defeito original. E
    minimizar no meio de uma resposta é legítimo: não pode cancelá-la.
    """
    javascript = _read(JS)
    corpo = javascript.split("function emitUi(", 1)[1].split("\n  }", 1)[0]
    # Ignora comentários: o próprio comentário de `emitUi` explica por que
    # ela NÃO usa `eventPending`, e a primeira versão desta prova tropeçou
    # nisso — reprovava o código pelo texto que o justifica.
    codigo = "\n".join(l for l in corpo.splitlines()
                       if not l.strip().startswith("//"))
    assert "eventPending" not in codigo
    assert "composer.disabled" not in codigo


def test_o_eco_local_acompanha_o_aviso_ao_servidor():
    """
    O `setOpen(false)` local existe para o painel recolher NA HORA. Sem
    ele o clique só teria efeito depois do rerun, e pareceria engolido —
    que é justamente a queixa original.
    """
    javascript = _read(JS)
    corpo = javascript.split("function closeAndRestoreFocus(", 1)[1]
    corpo = corpo.split("\n  }", 1)[0]
    assert "setOpen(false)" in corpo
    assert 'emitUi("minimizar")' in corpo


def test_o_icone_flutuante_existe_e_flutua():
    """
    O ícone precisa ficar sobre qualquer tela e acima do conteúdo. Se
    fosse estático, minimizar esconderia o GovBot sem deixar como voltar.
    """
    css = _read(CSS)
    bloco = css.split(".govbot-launcher {", 1)[1].split("}", 1)[0]
    assert "position: fixed" in bloco
    assert "z-index" in bloco
