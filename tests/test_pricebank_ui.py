"""
Banco de Preços na interface — consulta → cesta → pesquisa (UI-01).

A tela roda inteira no AppTest com o banco falso dos testes de preços:
nenhuma rede, nenhum banco real. A fonte é um dublê com 5 referências.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from src import db
from src.precos import repositorio as repo
from src.precos.estados import EstadoItem
from tests.conftest import ClientePrecosFalso
from tests.test_precos_fase4 import _com_amostra

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _app(monkeypatch):
    from src.ui import precos_ui

    monkeypatch.setenv("GOVDOCS_MODO_ABERTO", "1")
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == repo.FLAG)
    cliente = ClientePrecosFalso()
    for tabela in ("pesquisas_preco", "pesquisa_preco_itens",
                   "pesquisa_preco_referencias", "pesquisa_preco_eventos"):
        cliente.tabelas.setdefault(tabela, [])
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: cliente)
    monkeypatch.setattr(precos_ui, "_fontes", lambda: [_com_amostra(5)])

    at = AppTest.from_file(APP, default_timeout=90)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["pagina"] = "Pesquisa de Preços"
    at.session_state[precos_ui.TELA] = precos_ui.BANCO
    return at, cliente


def _consultar(at):
    at.text_area[0].input("CANETA ESFEROGRAFICA AZUL")
    at.text_input[0].input("UNIDADE")
    at.text_input[1].input("100")
    botao = next(b for b in at.button if b.label == "Consultar preços")
    botao.click().run()


def test_consulta_mostra_contagens_cesta_e_media(monkeypatch):
    at, _ = _app(monkeypatch)
    at.run()
    assert not at.exception
    _consultar(at)
    assert not at.exception

    metricas = {m.label: m.value for m in at.metric}
    assert metricas["Encontradas"] == "5"
    assert metricas["Sem duplicatas"] == "5"
    assert metricas["Na cesta"].endswith("/3")
    assert "Média aritmética (método padrão)" in metricas
    assert "Mediana (diagnóstico)" in metricas


def test_salvar_cria_pesquisa_no_mesmo_dominio_e_abre_a_revisao(monkeypatch):
    from src.ui import precos_ui

    at, cliente = _app(monkeypatch)
    at.run()
    _consultar(at)
    salvar = next(b for b in at.button if b.label == "Salvar como pesquisa")
    salvar.click().run()
    assert not at.exception

    pesquisas = cliente.tabelas["pesquisas_preco"]
    itens = cliente.tabelas["pesquisa_preco_itens"]
    refs = cliente.tabelas["pesquisa_preco_referencias"]
    assert len(pesquisas) == 1 and len(itens) == 1
    assert pesquisas[0]["versao_regras"].endswith("media-aritmetica")
    assert len(refs) == 5
    assert sum(r["status"] == "selected" for r in refs) >= 3
    assert itens[0]["estado"] == EstadoItem.EM_REVISAO.value
    assert itens[0]["metodo"] == "media"
    assert at.session_state[precos_ui.TELA] == precos_ui.REVISAO
    eventos = cliente.tabelas["pesquisa_preco_eventos"]
    assert any(e["payload"].get("origem") == "banco_de_precos"
               for e in eventos)
