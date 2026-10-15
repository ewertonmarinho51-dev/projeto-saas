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
from src.precos.modelo import NaturezaValor
from tests.test_precos_fase4 import FONTE_OFICIAL, _FonteFalsa, _referencia

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _homologada(ident, valor):
    ref = _referencia(FONTE_OFICIAL, ident, valor)
    ref.natureza_valor = NaturezaValor.HOMOLOGADO
    return ref


def _fonte_com(n):
    return _FonteFalsa(FONTE_OFICIAL, [_homologada(f"r{i}", str(10 + i))
                                       for i in range(n)])


def _app(monkeypatch):
    from src.ui import precos_ui

    monkeypatch.setenv("GOVDOCS_MODO_ABERTO", "1")
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == repo.FLAG)
    cliente = ClientePrecosFalso()
    for tabela in ("pesquisas_preco", "pesquisa_preco_itens",
                   "pesquisa_preco_referencias", "pesquisa_preco_eventos"):
        cliente.tabelas.setdefault(tabela, [])
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: cliente)
    monkeypatch.setattr(precos_ui, "_fontes", lambda: [_fonte_com(5)])

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
    legendas = " ".join(c.value for c in at.caption)
    assert "respondeu com preços" in legendas
    assert "success_with_prices" not in legendas
    assert "01/06/2026" in legendas


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


def _consultar_com_pncp(at, entrada):
    at.text_area[0].input("PANO LIMPEZA")
    at.text_input[0].input("UNIDADE")
    campo = next(t for t in at.text_input
                 if t.label == "Contratação similar no PNCP (opcional)")
    campo.input(entrada)
    next(b for b in at.button if b.label == "Consultar preços").click().run()


def test_contratacao_do_pncp_entra_como_referencia_verificavel(monkeypatch):
    from src.precos import pncp
    from tests.test_pricebank_pncp import CONTROLE, _api

    abrir = _api()
    monkeypatch.setattr(pncp.PNCPAdapter, "_abrir_url",
                        lambda self, url: abrir(url))
    at, _ = _app(monkeypatch)
    at.run()
    _consultar_com_pncp(at, CONTROLE)
    assert not at.exception
    assert not at.error
    metricas = {m.label: m.value for m in at.metric}
    assert metricas["Sem duplicatas"] == "6", "5 do dublê + 1 do PNCP"
    links = " ".join(m.value for m in at.markdown)
    assert "pncp.gov.br/app/editais/07954480000179/2026/15836" in links


def test_contratacao_pncp_invalida_avisa_e_nao_consulta(monkeypatch):
    at, _ = _app(monkeypatch)
    at.run()
    _consultar_com_pncp(at, "http://169.254.169.254/")
    assert not at.exception
    assert any("não reconhecida" in e.value for e in at.error)
    assert not at.metric


def test_revisao_paginada_e_conclusao_com_pendencia_exige_justificativa(monkeypatch):
    """Cesta grande desenha 25 por vez; média provisória não conclui calada."""
    from src.ui import precos_ui

    at, cliente = _app(monkeypatch)
    valores = [str(10 + i % 5) for i in range(39)] + ["9000"]
    monkeypatch.setattr(precos_ui, "_fontes", lambda: [_FonteFalsa(
        FONTE_OFICIAL, [_homologada(f"r{i}", v) for i, v in enumerate(valores)])])
    at.run()
    _consultar(at)
    next(b for b in at.button if b.label == "Salvar como pesquisa").click().run()
    assert not at.exception
    assert at.session_state[precos_ui.TELA] == precos_ui.REVISAO

    detalhes = [e for e in at.expander if e.label == "Ver detalhes"]
    assert len(detalhes) == precos_ui.POR_PAGINA_REVISAO
    assert any(b.label == "Mostrar mais 15" for b in at.button)
    assert any("PROVISÓRIO" in w.value for w in at.warning)

    next(b for b in at.button if b.label == "Concluir este item").click().run()
    assert any("análise crítica" in e.value for e in at.error)
    [item] = cliente.tabelas["pesquisa_preco_itens"]
    assert item["estado"] == "review", "não concluiu sem justificativa"
