"""
Suíte de testes end-to-end do GovDocs Wizard.

Usa o AppTest do Streamlit para dirigir a aplicação real (formulário,
geração, aprovação e exportação) em Modo Demonstração — sem depender de
chave de API nem de rede. Execução:  pytest -q
"""

import io
import zipfile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _por_rotulo(elementos, trecho: str):
    achados = [e for e in elementos if trecho.lower() in (e.label or "").lower()]
    assert achados, f"campo contendo '{trecho}' não encontrado"
    return achados[0]


def _botao(at: AppTest, trecho: str):
    achados = [b for b in at.button if trecho.lower() in (b.label or "").lower()]
    assert achados, f"botão contendo '{trecho}' não encontrado"
    return achados[0]


def _app_modo_aberto() -> AppTest:
    """AppTest hermético: sem Supabase, o app roda em modo aberto (sem login)."""
    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    return at


def _iniciar_com_formulario() -> AppTest:
    """Sobe o app em modo demo e submete o Formulário Matriz válido."""
    at = _app_modo_aberto()
    at.run()
    assert not at.exception
    [t for t in at.toggle if t.key == "modo_demo"][0].set_value(True)
    at.run()
    _por_rotulo(at.text_input, "Órgão").set_value("Prefeitura de Teste — Secretaria de Educação")
    _por_rotulo(at.text_area, "Objeto").set_value("Aquisição de 100 notebooks para laboratórios")
    _por_rotulo(at.text_area, "Justificativa").set_value("Parque tecnológico obsoleto")
    _por_rotulo(at.number_input, "Estimativa de Valor").set_value(450000.0)
    _botao(at, "Iniciar").click()
    at.run()
    assert not at.exception
    return at


def _aprovar_documento(at: AppTest) -> None:
    _botao(at, "com IA").click()
    at.run()
    assert not at.exception
    _botao(at, "Aprovar").click()
    at.run()
    assert not at.exception


def test_formulario_valida_campos_obrigatorios():
    at = _app_modo_aberto()
    at.run()
    _botao(at, "Iniciar").click()
    at.run()
    assert at.session_state["etapa"] == 0, "não deve avançar sem os obrigatórios"
    assert any("obrigatórios" in e.value for e in at.error)


def test_fluxo_completo_ate_sucesso():
    at = _iniciar_com_formulario()
    assert at.session_state["etapa"] == 1

    for etapa_esperada in (2, 3, 4, 5):
        _aprovar_documento(at)
        assert at.session_state["etapa"] == etapa_esperada

    docs = at.session_state["documentos"]
    assert set(docs) == {"dfd", "etp", "tr", "edital"}
    assert at.session_state["aprovados"] == {"dfd", "etp", "tr", "edital"}
    corpo = " ".join(m.value for m in at.markdown)
    assert "concluído" in corpo.lower()


def test_sequencia_nao_pode_ser_pulada():
    at = _iniciar_com_formulario()
    at.session_state["etapa"] = 3  # tenta pular direto para o TR
    at.run()
    assert at.session_state["etapa"] < 3, "deve voltar para a etapa pendente"


def test_edicao_invalida_documentos_seguintes():
    at = _iniciar_com_formulario()
    _aprovar_documento(at)  # DFD aprovado -> etapa 2 (ETP)
    _aprovar_documento(at)  # ETP aprovado -> etapa 3 (TR)

    # Volta duas telas até o DFD e aprova com texto alterado
    _botao(at, "Voltar").click()
    at.run()
    _botao(at, "Voltar").click()
    at.run()
    assert at.session_state["etapa"] == 1
    at.text_area(key="editor_dfd").set_value("# DFD editado manualmente")
    _botao(at, "Aprovar").click()
    at.run()

    docs = at.session_state["documentos"]
    assert docs["dfd"] == "# DFD editado manualmente"
    assert "etp" not in docs, "ETP deveria ter sido invalidado pela edição do DFD"
    assert "tr" not in docs


@pytest.fixture()
def documentos_exemplo() -> dict:
    md = (
        "# Título\n\nParágrafo com **negrito** e acentuação: ção, ã, é — travessão.\n\n"
        "## Seção\n\n- item um\n- item dois\n\n"
        "| Risco | Impacto |\n|---|---|\n| Atraso | Alto |\n"
    )
    return {k: md for k in ("dfd", "etp", "tr", "edital")}


def test_exportacao_docx_pdf_zip(documentos_exemplo):
    from src import export

    pdf = export.gerar_pdf_consolidado(documentos_exemplo)
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000

    docx = export.gerar_docx_consolidado(documentos_exemplo)
    assert docx[:2] == b"PK" and len(docx) > 3000

    for formato in ("pdf", "docx"):
        pacote = export.gerar_zip(documentos_exemplo, formato)
        nomes = zipfile.ZipFile(io.BytesIO(pacote)).namelist()
        assert len(nomes) == 4
        assert all(n.endswith(f".{formato}") for n in nomes)
