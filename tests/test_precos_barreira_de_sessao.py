"""
A barreira da Pesquisa de Preços tem de dizer a verdade.

O módulo opera pelo JWT do usuário e recusa a credencial de servidor —
é o que faz o RLS ser avaliado de fato. Mas o `autenticar()` tem DOIS
caminhos: Supabase Auth (com JWT) e o login legado contra `usuarios`
(sem JWT nenhum). Quem digita o `login` em vez do e-mail entra pelo
segundo, normalmente, e chega aqui sem credencial.

A barreira dizia "Entre no sistema com sua conta para abrir o módulo"
para alguém com nome e papel na barra lateral. Tecnicamente correta,
inútil na prática: a pessoa JÁ entrou, e a frase não diz por qual porta
ela deveria ter entrado.

Aconteceu em produção, com o administrador olhando a própria tela.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import auth, db
from src.precos import repositorio as repo

APP = str(Path(__file__).resolve().parents[1] / "app.py")

VINCULADO = {
    "id": "u1", "nome": "Antonio Ewerton", "login": "ewertomarin",
    "papel": "admin", "ativo": True,
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "auth_user_id": "2f4baaaf-25ef-4b81-b9ed-3753051e18bd",
}
SEM_VINCULO = dict(VINCULADO, auth_user_id=None)


def _barreira(monkeypatch, usuario) -> AppTest:
    """Aba de preços aberta, flag ligada e SEM cliente do usuário."""
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == repo.FLAG)
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: None)
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(auth, "tem_admin", lambda: True)
    monkeypatch.setattr(auth, "precisa_configurar", lambda: False)
    monkeypatch.setattr(auth, "modo_aberto", lambda: usuario is None)

    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    if usuario is not None:
        at.session_state["usuario"] = dict(usuario)
    at.session_state["pagina"] = "Pesquisa de Preços"
    at.run()
    assert not at.exception
    return at


def _avisos(at: AppTest) -> str:
    return " ".join([i.value for i in at.info] + [w.value for w in at.warning])


# ---------------------------------------------------------------------------
# Quem já entrou não pode ser mandado entrar
# ---------------------------------------------------------------------------
def test_quem_entrou_pelo_login_antigo_e_mandado_entrar_pelo_email(monkeypatch):
    """
    O caso real: conta vinculada ao Auth, pessoa logada pelo caminho
    legado. A tela precisa dizer QUAL porta usar, não repetir "entre".
    """
    avisos = _avisos(_barreira(monkeypatch, VINCULADO)).lower()

    assert "e-mail" in avisos or "email" in avisos
    assert "sair" in avisos or "saia" in avisos


def test_a_barreira_nao_manda_entrar_quem_ja_esta_dentro(monkeypatch):
    """
    A frase antiga, exatamente. Ela é o defeito, não o remédio: aparecia
    para um administrador com nome e papel na barra lateral.
    """
    avisos = _avisos(_barreira(monkeypatch, VINCULADO)).lower()

    assert "entre no sistema com sua conta" not in avisos


def test_sem_vinculo_a_tela_manda_procurar_o_administrador(monkeypatch):
    """
    Sem `auth_user_id` não adianta sair e entrar pelo e-mail: não existe
    conta de e-mail para essa pessoa. Mandá-la tentar seria empurrá-la
    para uma porta que não abre.
    """
    avisos = _avisos(_barreira(monkeypatch, SEM_VINCULO)).lower()

    assert "administrador" in avisos
    assert "saia" not in avisos


def test_sem_ninguem_logado_continua_pedindo_login(monkeypatch):
    """
    O caso de origem não se perde: sem usuário na sessão, a barreira
    continua pedindo login — e aí "entre no sistema" é a frase certa.
    """
    avisos = _avisos(_barreira(monkeypatch, None)).lower()

    assert "entre no sistema" in avisos


def test_a_barreira_nunca_vira_lista_vazia(monkeypatch):
    """
    O contrato original da Fase 4, que nenhuma redação nova pode
    quebrar: lista vazia por falta de permissão parece que não há nada,
    quando na verdade não se pode ver.
    """
    for usuario in (VINCULADO, SEM_VINCULO, None):
        at = _barreira(monkeypatch, usuario)
        assert _avisos(at).strip(), f"barreira muda para {usuario}"
        titulos = " ".join(s.value for s in at.subheader)
        assert "Minhas pesquisas" not in titulos


def test_nenhuma_das_frases_promete_que_a_senha_e_a_mesma(monkeypatch):
    """
    Achado do Codex, e ele estava certo.

    As duas senhas são INDEPENDENTES: `criar_contas_auth.py` convida por
    `invite_user_by_email` e a pessoa define a senha dela no convite; o
    `senha_hash` legado nunca é copiado nem sincronizado. Dizer "com a
    mesma senha" manda para um segundo login falhado quem seguir a
    instrução ao pé da letra — e quem acabou de bater numa barreira é
    exatamente quem segue ao pé da letra.

    Coincidiram nas duas contas criadas à mão em produção. Coincidência
    não é garantia, e a frase estava afirmando garantia.
    """
    avisos = _avisos(_barreira(monkeypatch, VINCULADO)).lower()

    assert "mesma senha" not in avisos


# ---------------------------------------------------------------------------
# O aviso no login
#
# A barreira conserta a tela onde o problema aparece. O aviso conserta o
# momento em que o problema NASCE — o login que caiu no caminho legado
# tendo conta de e-mail disponível.
# ---------------------------------------------------------------------------
def test_entrar_sem_token_com_conta_vinculada_marca_o_aviso():
    import streamlit as st

    st.session_state.clear()
    auth.entrar(dict(VINCULADO))

    assert st.session_state.get(auth.AVISO_LOGIN_LEGADO) is True


def test_entrar_com_token_nao_marca_aviso_nenhum():
    import streamlit as st

    st.session_state.clear()
    auth.entrar(dict(VINCULADO, _token="jwt-de-verdade"))

    assert not st.session_state.get(auth.AVISO_LOGIN_LEGADO)
    assert st.session_state[db.CHAVE_DA_SESSAO] == "jwt-de-verdade"


def test_entrar_sem_vinculo_nao_marca_aviso():
    """
    Quem não tem conta de e-mail não tem o que fazer com o aviso. Avisar
    assim mesmo seria pedir uma ação impossível — e treinar a pessoa a
    ignorar avisos.
    """
    import streamlit as st

    st.session_state.clear()
    auth.entrar(dict(SEM_VINCULO))

    assert not st.session_state.get(auth.AVISO_LOGIN_LEGADO)


def test_o_aviso_aparece_uma_vez_e_some(monkeypatch):
    """
    Uma vez: o aviso é sobre um ato (o login que acabou de acontecer),
    não sobre um estado permanente. Repetido em toda tela, vira moldura
    e ninguém lê.
    """
    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(auth, "tem_admin", lambda: True)
    monkeypatch.setattr(auth, "precisa_configurar", lambda: False)
    monkeypatch.setattr(auth, "modo_aberto", lambda: False)

    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["usuario"] = dict(VINCULADO)
    at.session_state[auth.AVISO_LOGIN_LEGADO] = True
    at.session_state["pagina"] = "Novo processo"

    at.run()
    assert not at.exception
    primeira = " ".join(w.value for w in at.warning).lower()
    assert "e-mail" in primeira or "email" in primeira
    # Mesma regra do aviso da barreira: não prometer senha igual.
    assert "mesma senha" not in primeira

    at.run()
    segunda = " ".join(w.value for w in at.warning).lower()
    assert "e-mail" not in segunda and "email" not in segunda
