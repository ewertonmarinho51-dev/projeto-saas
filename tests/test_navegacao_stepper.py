"""Regressão da navegação clicável entre os documentos do wizard."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from src import state

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _dados() -> dict:
    return {"orgao": "Prefeitura", "objeto": "Aquisição de materiais"}


def _botao_etapa(at: AppTest, rotulo: str):
    encontrados = [
        botao for botao in at.button
        if rotulo.lower() in (botao.label or "").lower()
        and (botao.key or "").startswith("navegar_etapa_")
    ]
    assert encontrados, f"etapa '{rotulo}' não encontrada"
    return encontrados[0]


def _app_em_tr() -> AppTest:
    import os

    os.environ["GOVDOCS_MODO_ABERTO"] = "1"
    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["dados"] = _dados()
    at.session_state["documentos"] = {
        "dfd": "# DFD aprovado",
        "etp": "# ETP aprovado",
        "tr": "# TR em revisão",
    }
    at.session_state["aprovados"] = {"dfd", "etp"}
    at.session_state["etapa"] = 3
    at.run()
    assert not at.exception
    return at


def test_etapas_navegaveis_respeitam_a_sequencia_e_o_conteudo_salvo():
    assert state.calcular_etapas_navegaveis({}, {}, set()) == {0}
    assert state.calcular_etapas_navegaveis(_dados(), {}, set()) == {0, 1}

    docs = {"dfd": "DFD", "etp": "ETP", "tr": "TR", "edital": "Edital"}
    assert state.calcular_etapas_navegaveis(
        _dados(), docs, {"dfd"}) == {0, 1, 2}
    assert state.calcular_etapas_navegaveis(
        _dados(), docs, {"dfd", "etp"}) == {0, 1, 2, 3}
    assert state.calcular_etapas_navegaveis(
        _dados(), docs, set(docs)) == {0, 1, 2, 3, 4, 5}

    # Aprovação sem o respectivo documento salvo não libera a etapa seguinte.
    assert state.calcular_etapas_navegaveis(
        _dados(), {}, {"dfd", "etp", "tr", "edital"}) == {0, 1}


def test_stepper_abre_documentos_e_bloqueia_etapas_futuras():
    at = _app_em_tr()

    assert not _botao_etapa(at, "Dados da Demanda").disabled
    assert not _botao_etapa(at, "DFD").disabled
    assert not _botao_etapa(at, "ETP").disabled
    assert not _botao_etapa(at, "TR").disabled
    assert _botao_etapa(at, "Minuta de Edital").disabled
    assert _botao_etapa(at, "Concluído").disabled

    _botao_etapa(at, "DFD").click()
    at.run()
    assert not at.exception
    assert at.session_state["etapa"] == 1
    assert any("Documento de Formalização" in s.value for s in at.subheader)

    _botao_etapa(at, "ETP").click()
    at.run()
    assert not at.exception
    assert at.session_state["etapa"] == 2
    assert any("Estudo Técnico Preliminar" in s.value for s in at.subheader)


def test_navegar_preserva_edicao_sem_alterar_a_versao_aprovada():
    at = _app_em_tr()
    original = at.session_state["documentos"]["tr"]

    at.text_area(key="editor_tr").set_value("# TR com edição ainda não aprovada")
    _botao_etapa(at, "DFD").click()
    at.run()

    assert not at.exception
    assert at.session_state["documentos"]["tr"] == original
    assert at.session_state["edicoes_pendentes"]["tr"] == \
        "# TR com edição ainda não aprovada"

    _botao_etapa(at, "TR").click()
    at.run()
    assert not at.exception
    assert at.text_area(key="editor_tr").value == \
        "# TR com edição ainda não aprovada"
