"""
Minimizar o GovBot — o estado mora no Python.

O X sempre teve handler. O que faltava era o fechar ATRAVESSAR a
fronteira: o componente é remontado a cada rerun do Streamlit com
`data.open` vindo da sessão Python, e enquanto o fechar era só
client-side esse valor continuava `True`. A montagem seguinte reabria o
painel, e o servidor concluía que o botão estava quebrado.

Estas provas fixam a correção no lugar onde ela vale: a sessão.
"""

from __future__ import annotations

from src import govbot
from src.ui import govbot_panel


def _sessao_com_conversa():
    return {
        govbot.CHAVE_SESSAO: {
            "open": True,
            "proactive": True,
            "conversa": [{"quem": "servidor", "texto": "olá"},
                         {"quem": "govbot", "texto": "oi"}],
        }
    }


def test_minimizar_grava_fechado_na_sessao():
    sessao = _sessao_com_conversa()
    govbot_panel._ajustar_visibilidade(sessao, aberto=False)
    assert sessao[govbot.CHAVE_SESSAO]["open"] is False


def test_expandir_grava_aberto():
    sessao = _sessao_com_conversa()
    sessao[govbot.CHAVE_SESSAO]["open"] = False
    govbot_panel._ajustar_visibilidade(sessao, aberto=True)
    assert sessao[govbot.CHAVE_SESSAO]["open"] is True


def test_minimizar_nao_toca_no_historico():
    """
    O requisito é explícito: minimizar não pode perder a conversa. Como o
    histórico vive no bucket e esta função só mexe em `open`, a garantia
    é estrutural — mas fica provada, porque "estrutural" é o tipo de
    garantia que alguém desfaz sem perceber.
    """
    sessao = _sessao_com_conversa()
    antes = list(sessao[govbot.CHAVE_SESSAO]["conversa"])
    govbot_panel._ajustar_visibilidade(sessao, aberto=False)
    govbot_panel._ajustar_visibilidade(sessao, aberto=True)
    assert sessao[govbot.CHAVE_SESSAO]["conversa"] == antes


def test_minimizar_nao_reporta_trabalho_de_ia():
    """
    Devolver True faria o chamador tratar o clique no X como turno de
    conversa — reprocessando e exibindo resposta que ninguém pediu.
    """
    assert govbot_panel._ajustar_visibilidade({}, aberto=False) is False


def test_sessao_sem_raiz_nao_quebra():
    """Primeiro clique antes de qualquer conversa: a raiz ainda não existe."""
    sessao: dict = {}
    govbot_panel._ajustar_visibilidade(sessao, aberto=False)
    assert sessao[govbot.CHAVE_SESSAO]["open"] is False


def test_os_eventos_de_interface_sao_aceitos_pela_allowlist():
    """
    O frontend só emite o que está em `TIPOS_EVENTO`; fora da lista, o
    parser recusa e o clique no X viraria erro em vez de minimizar.
    """
    assert "minimizar" in govbot.TIPOS_EVENTO
    assert "expandir" in govbot.TIPOS_EVENTO


def test_o_painel_desvia_os_eventos_de_interface():
    assert govbot_panel._EVENTOS_DE_INTERFACE == ("minimizar", "expandir")


def test_o_componente_recebe_o_estado_guardado_no_python():
    """
    A ponta que fecha o ciclo: o valor gravado na sessão é o que volta
    para o componente na próxima montagem. Sem isto, minimizar duraria
    até o próximo rerun.
    """
    import inspect

    fonte = inspect.getsource(govbot_panel)
    assert 'open=bool(raiz.get("open", True))' in fonte
