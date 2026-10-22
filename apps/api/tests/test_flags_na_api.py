"""
As flags do painel no processo da API (0033).

Antes do P04d toda flag lia DESLIGADA aqui: o domínio procurava
`config_app` com a "credencial de servidor", que na API é só a chave
publicável (`anon`, fechado pela 0019). Agora elas vêm de
`flags_do_app()` com o token do usuário — e falha de leitura nunca vira
"desligada": vale a última leitura boa ou, sem nenhuma, o erro.
"""

import pytest

from src import db
from src.streamlit_opcional import sem_streamlit, sessao_da_requisicao


class _Rpc:
    def __init__(self, dados=None, erro=None):
        self.dados, self.erro, self.chamadas = dados, erro, []

    def rpc(self, nome, *a, **k):
        self.chamadas.append(nome)
        return self

    def execute(self):
        if self.erro:
            raise self.erro
        return type("R", (), {"data": self.dados})()


@pytest.fixture(autouse=True)
def _limpo(monkeypatch):
    monkeypatch.setattr(db, "_ULTIMAS_FLAGS", None)
    db._config_app_inteira.clear()
    monkeypatch.setattr(db, "disponivel", lambda: True)
    yield
    db._config_app_inteira.clear()


def test_a_api_roda_sem_streamlit():
    assert sem_streamlit()


def test_flags_vem_da_funcao_com_o_token_do_usuario(monkeypatch):
    cliente = _Rpc([{"chave": "flag_precos_ciencia_emissao", "valor": "on"},
                    {"chave": "OPENAI_API_KEY", "valor": "sk-nao-devia-vir"}])
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: cliente)
    with sessao_da_requisicao("token", "tenant"):
        assert db.flag_ativa("precos_ciencia_emissao") is True
        assert db.obter_config("OPENAI_API_KEY") == "", "só flags passam"
    assert cliente.chamadas == ["flags_do_app"]


def test_falha_depois_de_uma_leitura_boa_mantem_a_ultima(monkeypatch):
    bom = _Rpc([{"chave": "flag_precos_ciencia_emissao", "valor": "on"}])
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: bom)
    with sessao_da_requisicao("token", "tenant"):
        assert db.flag_ativa("precos_ciencia_emissao")
    db._config_app_inteira.clear()
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: _Rpc(erro=ConnectionError("fora")))
    with sessao_da_requisicao("token", "tenant"):
        assert db.flag_ativa("precos_ciencia_emissao"), "falha não desliga a flag"


def test_falha_sem_leitura_anterior_levanta(monkeypatch):
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: _Rpc(erro=ConnectionError("fora")))
    with sessao_da_requisicao("token", "tenant"):
        with pytest.raises(db.ErroBanco):
            db.flag_ativa("precos_ciencia_emissao")


def test_sem_sessao_levanta(monkeypatch):
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: None)
    with pytest.raises(db.ErroBanco):
        db.flag_ativa("precos_ciencia_emissao")


def test_cliente_de_servidor_na_api_e_o_do_usuario(monkeypatch):
    cliente = object()
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: cliente)
    assert db._cliente() is cliente
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: None)
    with pytest.raises(db.ErroBanco):
        db._cliente()
