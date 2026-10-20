"""
Navegação lenta e tela "desconfigurada" no clique (operador, 16/10/2026).

Duas causas medidas, uma prova para cada:

* IDAS AO BANCO POR CLIQUE. A pergunta "este módulo está disponível?"
  é feita de 4 a 6 vezes por execução (menu + rota), e cada uma eram duas
  consultas sem cache; as flags eram uma consulta POR CHAVE (11 no
  primeiro clique de cada minuto). VPS → Supabase mede 20–85 ms por ida.
  Agora: módulos e `config_app` em cache de 60s, limpo por quem grava.
* TELA ANTIGA POR BAIXO DA NOVA. O Streamlit redesenha por posição: na
  troca de tela, o que a nova não alcançou seguia mostrando a antiga
  até o fim da execução. `components.corpo_da_pagina` alterna o corpo
  entre duas posições a cada troca — ver o comentário lá.

Banco falso com contador; nada de rede.
"""

from __future__ import annotations

import collections
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import db
from tests import conftest

APP = str(Path(__file__).resolve().parents[1] / "app.py")
CSS = Path(__file__).resolve().parents[1] / "assets" / "govconnect.css"
USUARIO = {"auth_user_id": "u1", "login": "servidor.teste", "id": "x",
           "nome": "Servidor Teste", "papel": "servidor",
           "secretaria_id": "sec-1"}


@pytest.fixture
def banco(monkeypatch):
    """Banco falso que CONTA as idas, por tabela."""
    contagem: collections.Counter = collections.Counter()
    original = conftest.TabelaPrecosFalsa.execute

    def contado(self):
        contagem[self.nome] += 1
        return original(self)

    monkeypatch.setattr(conftest.TabelaPrecosFalsa, "execute", contado)
    cliente = conftest.ClientePrecosFalso()
    cliente.tabelas["config_app"] = [
        {"chave": "flag_price_research", "valor": "on"},
        {"chave": "flag_unified_quotations", "valor": "on"},
        {"chave": "OPENAI_MODEL", "valor": " gpt-5-mini "},
    ]
    monkeypatch.setattr(db, "_cliente", lambda: cliente)
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: cliente)
    monkeypatch.setattr(db, "disponivel", lambda: True)
    cliente.contagem = contagem
    return cliente


# ---------------------------------------------------------------------------
# Banco: uma ida por minuto, não uma por pergunta
# ---------------------------------------------------------------------------
def test_config_app_inteira_numa_ida_so(banco):
    assert db.flag_ativa("price_research") is True
    assert db.flag_ativa("unified_quotations") is True
    assert db.flag_ativa("inexistente") is False
    assert db.obter_config("OPENAI_MODEL") == "gpt-5-mini"
    assert banco.contagem["config_app"] == 1


def test_salvar_config_vale_na_hora(banco):
    assert db.flag_ativa("govbot") is False
    db.salvar_config("flag_govbot", "on")
    assert db.flag_ativa("govbot") is True


def test_modulos_consultados_uma_vez_e_limpos_ao_gravar(banco, monkeypatch):
    for _ in range(6):
        assert db.modulo_disponivel("price_research", "sec-1") is True
    assert banco.contagem["tenant_modulos"] == 1
    assert banco.contagem["secretaria_modulos"] == 1

    db.salvar_modulo_do_tenant("price_research", False)
    assert db.modulo_disponivel("price_research", "sec-1") is False

    db.salvar_modulo_do_tenant("price_research", True)
    db.salvar_modulo_da_secretaria("sec-1", "price_research", "desabilitado")
    assert db.modulo_disponivel("price_research", "sec-1") is False


def test_cache_de_modulos_e_por_prefeitura(banco, monkeypatch):
    """Sem o tenant na chave, uma prefeitura leria a decisão da outra."""
    import streamlit as st

    banco.tabelas["tenant_modulos"] = [
        {"tenant_id": "pref-a", "modulo": "price_research",
         "habilitado": False}]
    monkeypatch.setitem(st.session_state, "tenant_id", "pref-a")
    assert db.modulo_disponivel("price_research") is False
    monkeypatch.setitem(st.session_state, "tenant_id", "pref-b")
    assert db.modulo_disponivel("price_research") is True


def test_falha_do_banco_nao_fica_no_cache(banco, monkeypatch):
    """Exceção não entra no cache: o Supabase piscar não prende 60s."""
    original = conftest.TabelaPrecosFalsa.execute
    falhas = {"n": 1}

    def instavel(self):
        if self.nome == "tenant_modulos" and falhas["n"]:
            falhas["n"] -= 1
            raise RuntimeError("connection reset")
        return original(self)

    monkeypatch.setattr(conftest.TabelaPrecosFalsa, "execute", instavel)
    with pytest.raises(db.ErroBanco):
        db.modulos_do_tenant()
    assert db.modulos_do_tenant() == {}


# ---------------------------------------------------------------------------
# App inteiro: quantas idas um clique custa
# ---------------------------------------------------------------------------
def _app(monkeypatch, pagina):
    monkeypatch.setenv("GOVDOCS_MODO_ABERTO", "1")
    monkeypatch.setattr(db, "em_manutencao", lambda: False)
    at = AppTest.from_file(APP, default_timeout=90)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["pagina"] = pagina
    at.session_state["usuario"] = USUARIO
    return at


@pytest.mark.parametrize("pagina, teto", [
    ("Novo processo", 0),
    ("Processos", 1),        # a lista de processos
    ("Cotações", 2),         # a lista de cotações
])
def test_clique_repetido_so_le_o_que_e_da_tela(banco, monkeypatch, pagina,
                                               teto):
    """
    Antes: 4, 5 e 8 idas por clique nestas três telas, das quais 4 a 6
    só para montar o menu. Agora o menu sai do cache.
    """
    at = _app(monkeypatch, pagina)
    at.run()
    assert not at.exception, at.exception
    banco.contagem.clear()
    at.run()
    assert not at.exception, at.exception
    assert sum(banco.contagem.values()) <= teto, dict(banco.contagem)
    assert not {"config_app", "tenant_modulos",
                "secretaria_modulos"} & set(banco.contagem)


# ---------------------------------------------------------------------------
# Troca de tela: o corpo muda de posição; o clique na mesma tela, não
# ---------------------------------------------------------------------------
def test_troca_de_tela_alterna_a_posicao_do_corpo(banco, monkeypatch):
    from src.ui import components

    at = _app(monkeypatch, "Novo processo")
    at.run()
    inicial = at.session_state[components.CHAVE_POSICAO_DO_CORPO] \
        if components.CHAVE_POSICAO_DO_CORPO in at.session_state else 0

    at.run()   # mesmo lugar: nada se mexe, a rolagem fica
    mesma = at.session_state[components.CHAVE_POSICAO_DO_CORPO] \
        if components.CHAVE_POSICAO_DO_CORPO in at.session_state else 0
    assert mesma == inicial

    at.radio(key="pagina").set_value("Cotações").run()
    assert not at.exception, at.exception
    assert at.session_state[components.CHAVE_POSICAO_DO_CORPO] == 1 - inicial

    at.radio(key="pagina").set_value("Novo processo").run()
    assert at.session_state[components.CHAVE_POSICAO_DO_CORPO] == inicial


def test_chaves_de_tela_interna_batem_com_os_modulos():
    from src.ui import components, cotacoes_ui, precos_ui

    assert set(components.CHAVES_DE_TELA_INTERNA) == {
        cotacoes_ui.TELA, cotacoes_ui.COTACAO, precos_ui.TELA,
        precos_ui.PESQUISA}


def test_css_suaviza_a_espera_e_respeita_movimento_reduzido():
    css = CSS.read_text(encoding="utf-8")
    assert '[data-stale="true"]' in css
    assert 'data-test-script-state="running"' in css
    reduzido = css.split("@media (prefers-reduced-motion: reduce)")[1]
    assert 'data-test-script-state="running"' in reduzido
