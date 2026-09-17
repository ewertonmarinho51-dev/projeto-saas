"""
A tela de consolidação: existe, respeita a flag e não mente.

O contrato que mais importa aqui é o do arquivo não lido. Dos doze
documentos reais, dois são digitalizações. Se a tela os omitisse, o
servidor aplicaria ao processo uma consolidação faltando duas
secretarias sem nunca saber — e o número entraria no edital.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import auth, db, governanca

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _pdf(texto: str = "", paginas: int = 1) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for _ in range(paginas):
        pagina = doc.new_page()
        if texto:
            pagina.insert_textbox(pymupdf.Rect(40, 40, 560, 780), texto, fontsize=9)
    dados = doc.tobytes()
    doc.close()
    return dados


def _app(monkeypatch, *, flag=True, admin=False) -> AppTest:
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "flag_ativa",
                        lambda nome: flag and nome == governanca.FLAG_CONSOLIDACAO)
    monkeypatch.setattr(auth, "tem_admin", lambda: True)
    monkeypatch.setattr(auth, "precisa_configurar", lambda: False)
    monkeypatch.setattr(auth, "modo_aberto", lambda: False)
    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["usuario"] = {
        "id": "u1", "nome": "Servidor", "login": "s",
        "papel": "admin" if admin else "usuario",
        "tenant_id": "11111111-1111-1111-1111-111111111111",
    }
    return at


# ---------------------------------------------------------------------------
# Flag
# ---------------------------------------------------------------------------
def test_com_a_flag_ligada_a_aba_aparece_para_o_servidor(monkeypatch):
    at = _app(monkeypatch, flag=True)
    at.run()

    assert not at.exception
    navegacao = [r for r in at.radio if r.key == "pagina"]
    assert navegacao and "Consolidar Demandas" in navegacao[0].options


def test_com_a_flag_desligada_a_aba_nao_existe(monkeypatch):
    at = _app(monkeypatch, flag=False)
    at.run()

    assert not at.exception
    navegacao = [r for r in at.radio if r.key == "pagina"]
    assert navegacao and "Consolidar Demandas" not in navegacao[0].options


def test_a_aba_vem_antes_de_novo_processo(monkeypatch):
    """
    §4: consolidar acontece ANTES de preencher o formulário. A ordem da
    navegação é o que ensina o fluxo a quem abre o sistema pela primeira
    vez.
    """
    at = _app(monkeypatch, flag=True)
    at.run()

    opcoes = [r for r in at.radio if r.key == "pagina"][0].options
    assert opcoes.index("Consolidar Demandas") < opcoes.index("Novo processo")


def test_com_a_flag_desligada_a_rota_nao_abre(monkeypatch):
    """
    Navegação escondida não é autorização. Quem forçar a página na
    sessão volta para o começo em vez de entrar por uma porta lateral.
    """
    at = _app(monkeypatch, flag=False)
    at.session_state["pagina"] = "Consolidar Demandas"
    at.run()

    assert not at.exception
    titulos = " ".join(h.value for h in at.header) + " ".join(
        s.value for s in at.subheader)
    assert "Consolidar Demandas" not in titulos


def test_a_aba_tambem_aparece_para_o_administrador(monkeypatch):
    at = _app(monkeypatch, flag=True, admin=True)
    at.run()

    opcoes = [r for r in at.radio if r.key == "pagina"][0].options
    assert "Consolidar Demandas" in opcoes


# ---------------------------------------------------------------------------
# A tela
# ---------------------------------------------------------------------------
def test_sem_arquivo_a_tela_explica_o_que_fazer(monkeypatch):
    at = _app(monkeypatch, flag=True)
    at.session_state["pagina"] = "Consolidar Demandas"
    at.run()

    assert not at.exception
    assert at.file_uploader
    avisos = " ".join(i.value for i in at.info)
    assert "secretarias" in avisos.lower()


def test_a_tela_nao_exige_nome_de_arquivo_padronizado(monkeypatch):
    """
    §6. A orientação da tela precisa dizer isso, senão o servidor renomeia
    doze arquivos por precaução — e passa a confiar no nome.
    """
    at = _app(monkeypatch, flag=True)
    at.session_state["pagina"] = "Consolidar Demandas"
    at.run()

    avisos = " ".join(i.value for i in at.info).lower()
    assert "renomear" in avisos or "nome" in avisos


# ---------------------------------------------------------------------------
# O módulo por trás da tela
# ---------------------------------------------------------------------------
def test_disponivel_segue_a_flag(monkeypatch):
    from src.ui import demanda_ui

    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)
    assert not demanda_ui.disponivel()

    monkeypatch.setattr(db, "flag_ativa",
                        lambda nome: nome == governanca.FLAG_CONSOLIDACAO)
    assert demanda_ui.disponivel()


def test_a_flag_nasce_desligada():
    """
    §34. A etapa muda a ORIGEM da planilha do processo; ligada sem
    auditoria, colocaria uma quantidade consolidada dentro de um edital
    antes de alguém conferir a conta.

    Olha o SQL, não o texto cru do arquivo.

    A versão anterior casava `'on'` em qualquer lugar — e reprovou no dia
    em que um COMENTÁRIO do cabeçalho passou a registrar que, em
    produção, a flag foi ligada depois. O comentário estava certo e a
    migração continuava inserindo `'off'`: era falso positivo.

    Comentário não liga flag. Tirá-los antes de comparar mantém os
    dentes da prova sobre o que importa, que é o SQL executável.
    """
    from pathlib import Path

    migracoes = Path(__file__).resolve().parents[1] / "supabase" / "migrations"

    def so_o_sql(texto: str) -> str:
        return "\n".join(
            linha for linha in texto.splitlines()
            if not linha.lstrip().startswith("--")
        )

    ligada = []
    for m in migracoes.glob("*.sql"):
        sql = so_o_sql(m.read_text(encoding="utf-8"))
        if "demand_consolidation" in sql and "'on'" in sql:
            ligada.append(m.name)
    assert not ligada, ligada
