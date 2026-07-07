"""Testes de autenticação, papéis e identidade visual nos exports."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import auth, export

APP = str(Path(__file__).resolve().parent.parent / "app.py")


# ---------------------------------------------------------------------------
# Hash de senha (puro, sem banco)
# ---------------------------------------------------------------------------
def test_hash_e_verificacao_de_senha():
    h = auth.gerar_hash_senha("Segredo123")
    assert h.startswith("pbkdf2_sha256$200000$")
    assert auth.verificar_senha("Segredo123", h)
    assert not auth.verificar_senha("errada", h)
    assert not auth.verificar_senha("Segredo123", "lixo-sem-formato")


def test_hashes_diferentes_por_salt():
    assert auth.gerar_hash_senha("x" * 8) != auth.gerar_hash_senha("x" * 8)


def test_senha_fraca_rejeitada():
    assert auth.validar_senha_forte("curta") is not None
    assert auth.validar_senha_forte("senha-adequada") is None


# ---------------------------------------------------------------------------
# Papéis / modo aberto
# ---------------------------------------------------------------------------
def test_modo_aberto_sem_banco_da_permissao_de_admin(monkeypatch):
    monkeypatch.setattr(auth.db, "disponivel", lambda: False)
    assert auth.modo_aberto()
    assert auth.eh_admin()


def test_papel_usuario_nao_eh_admin(monkeypatch):
    monkeypatch.setattr(auth.db, "disponivel", lambda: True)
    monkeypatch.setattr(
        auth, "usuario_logado", lambda: {"id": "1", "papel": "usuario"}
    )
    assert not auth.eh_admin()
    monkeypatch.setattr(
        auth, "usuario_logado", lambda: {"id": "1", "papel": "admin"}
    )
    assert auth.eh_admin()


# ---------------------------------------------------------------------------
# Gate de login na aplicação
# ---------------------------------------------------------------------------
def test_com_banco_e_sem_login_mostra_tela_de_acesso(monkeypatch):
    from src import db

    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(auth, "tem_admin", lambda: True)
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    titulos = " ".join(s.value for s in at.subheader)
    assert "Acesso ao sistema" in titulos
    # o wizard não renderizou
    assert not any("Formulário Matriz" in s.value for s in at.subheader)


def test_sem_admin_cadastrado_pede_bootstrap(monkeypatch):
    from src import db

    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(auth, "tem_admin", lambda: False)
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    titulos = " ".join(s.value for s in at.subheader)
    assert "criar administrador" in titulos


def test_usuario_comum_nao_ve_paginas_de_admin(monkeypatch):
    from src import db

    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(auth, "tem_admin", lambda: True)
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["usuario"] = {
        "id": "u1", "nome": "Servidor Comum", "login": "servidor",
        "papel": "usuario",
    }
    at.run()
    assert not at.exception
    # sem radio de navegação (sem Base de Conhecimento / Administração)
    assert not [r for r in at.radio if r.key == "pagina"]
    titulos = " ".join(s.value for s in at.subheader)
    assert "Formulário Matriz" in titulos


# ---------------------------------------------------------------------------
# Identidade visual nos arquivos exportados
# ---------------------------------------------------------------------------
def test_branding_no_pdf_e_docx():
    branding = {
        "cabecalho": "PREFEITURA DE EXEMPLO",
        "rodape": "Rua das Flores, 100",
        "marca_dagua": "MINUTA",
    }
    docs = {"dfd": "# DFD\n\nConteúdo de teste."}
    pdf = export.gerar_pdf_consolidado(docs, branding)
    assert pdf.startswith(b"%PDF")

    docx_bytes = export.gerar_docx_consolidado(docs, branding)
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
        header = zf.read("word/header1.xml").decode()
        footer = zf.read("word/footer1.xml").decode()
    assert "PREFEITURA DE EXEMPLO" in header
    assert "Rua das Flores, 100" in footer


def test_export_sem_branding_continua_funcionando():
    docs = {"dfd": "# DFD\n\nTexto."}
    assert export.gerar_pdf_consolidado(docs).startswith(b"%PDF")
    assert export.gerar_zip(docs, "pdf")[:2] == b"PK"
