"""
A API não carrega o Streamlit — nem direta nem transitivamente.

Gate F1 do roadmap ("sem import streamlit na API"). A prova roda num
processo LIMPO porque, no ambiente de desenvolvimento, o Streamlit está
instalado e outro teste poderia tê-lo importado antes; `sys.modules`
do processo do pytest não diria nada.
"""

import subprocess
import sys
from pathlib import Path

RAIZ_API = Path(__file__).resolve().parent.parent

_SONDA = (
    "import sys; "
    "from govconect_api.main import criar_app; "
    "from govconect_api.config import carregar; "
    "criar_app(carregar({'APP_ENV': 'test'})); "
    "proibidos = [m for m in sys.modules "
    "             if m == 'streamlit' or m.startswith('streamlit.')]; "
    "print(','.join(proibidos) or 'limpo')"
)


def test_montar_a_api_nao_importa_streamlit():
    r = subprocess.run([sys.executable, "-c", _SONDA], cwd=RAIZ_API,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "limpo"


def test_a_sonda_pegaria_o_streamlit():
    # Dente da prova: se o Streamlit estiver instalado, importá-lo tem de
    # aparecer. Sem ele instalado (CI da API), não há o que provar aqui.
    import importlib.util

    if importlib.util.find_spec("streamlit") is None:
        return
    r = subprocess.run(
        [sys.executable, "-c",
         "import streamlit, sys; print('streamlit' in sys.modules)"],
        capture_output=True, text=True, timeout=120)
    assert r.stdout.strip() == "True"
