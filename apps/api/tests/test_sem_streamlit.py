"""
A API não carrega o Streamlit — nem direta nem transitivamente.

Gate F1 do roadmap ("sem import streamlit na API"). A prova roda num
processo LIMPO porque, no ambiente de desenvolvimento, o Streamlit está
instalado e outro teste poderia tê-lo importado antes; `sys.modules`
do processo do pytest não diria nada.
"""

import os
import subprocess
import sys
from pathlib import Path

RAIZ_API = Path(__file__).resolve().parent.parent
RAIZ_REPO = RAIZ_API.parent.parent

_SONDA = (
    "import sys; "
    "from govconect_api.main import criar_app; "
    "from govconect_api.config import carregar; "
    "criar_app(carregar({'APP_ENV': 'test', 'SUPABASE_URL': 'https://x.exemplo.co', "
    "'SUPABASE_KEY': 'chave-publicavel-de-teste'})); "
    # O caminho do worker de relatório (P04d), importado de uma vez:
    # `contexto` importava o Streamlit direto até o P04d.
    "import govconect_api.fila, src.precos.emissao, src.export, src.contexto, "
    "src.precos.documento_cotacao, src.precos.relatorio_view, src.precos.cesta; "
    # WordCraft Workspace: o dono documental e o que a aprovação importa.
    "import govconect_api.documentos_nativos, src.documentos_editor, src.wordcraft_runtime, "
    "src.qualidade, src.achados, src.consistencia, src.politicas, src.validacao; "
    # Elaboração automática: o caminho inteiro da geração, no worker.
    "import govconect_api.elaboracao, src.elaboracao, src.llm, src.rag, src.conhecimento, "
    "src.cache_geracao, src.familias, src.clausulas_deterministicas, src.templates_gov, "
    "src.mapa_riscos, src.resumo_processo, src.emissao, src.portarias; "
    "proibidos = [m for m in sys.modules "
    "             if m == 'streamlit' or m.startswith('streamlit.')]; "
    "print(','.join(proibidos) or 'limpo')"
)


def test_montar_a_api_nao_importa_streamlit():
    # A raiz do repositório entra no caminho, como no pytest.ini: é de
    # lá que vem `src.processos`, e é justamente esse import que poderia
    # arrastar o Streamlit junto.
    ambiente = {**os.environ, "PYTHONPATH": os.pathsep.join(
        [str(RAIZ_API), str(RAIZ_REPO), os.environ.get("PYTHONPATH", "")])}
    r = subprocess.run([sys.executable, "-c", _SONDA], cwd=RAIZ_API, env=ambiente,
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


# O caminho inteiro de uma chamada de IA, no substituto do Streamlit: o motor
# responde e `registrar_geracao` guarda o registro na sessão da requisição.
# Faltava `setdefault` no substituto, e a resposta já paga morria num
# AttributeError depois de o provedor responder — só em produção, porque os
# testes do GovBot injetam o motor por fora de `llm`.
_SONDA_REGISTRO = (
    "from src import db, llm; "
    "from src.streamlit_opcional import sessao_da_requisicao, st; "
    "llm.motores_disponiveis = lambda: [('openrouter', 'chave-falsa')]; "
    "llm._chamar_motor = lambda *a, **k: 'RESPOSTA'; "
    "db.obter_config = lambda chave: ''; "
    "db.registrar_geracao_bd = lambda registro: None; "
    "\nwith sessao_da_requisicao('token', 'tenant'):\n"
    "    print(llm.chamar_ia_texto('s', 'u', finalidade='govbot'))\n"
    "    print(len(st.session_state['registro_geracoes']))\n"
    "print('fora', st.session_state.setdefault('x', 'padrao'), 'x' in st.session_state)\n"
)


def test_chamada_de_ia_registra_a_geracao_sem_o_streamlit():
    ambiente = {**os.environ, "GOVDOCS_SEM_STREAMLIT": "1", "PYTHONPATH": os.pathsep.join(
        [str(RAIZ_API), str(RAIZ_REPO), os.environ.get("PYTHONPATH", "")])}
    r = subprocess.run([sys.executable, "-c", _SONDA_REGISTRO], cwd=RAIZ_API, env=ambiente,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split("\n")[:3] == ["RESPOSTA", "1", "fora padrao False"]
