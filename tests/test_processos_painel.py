"""
Painel de controle de processos — interface.

A lógica de estado vive em `tests/test_processos_estado.py`, sobre
dicionários. Aqui ficam só os contratos de TELA: a aba existe para todo
servidor, ela mostra o andamento em vez de só a data, renomear grava sem
carregar o processo, e excluir pede confirmação.

O que este arquivo não tenta provar: o desenho. Asserção sobre DOM do
Streamlit quebra a cada versão e não protege nada que importe.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import db, processos

APP = str(Path(__file__).resolve().parents[1] / "app.py")

PROCESSO = {
    "id": "11111111-1111-1111-1111-111111111111",
    "nome": "",
    "orgao": "Prefeitura de Exemplo",
    "objeto": "Aquisição de material de expediente",
    "etapa": 1,
    "dados": {},
    "documentos": {"dfd": "texto do DFD"},
    "aprovados": ["dfd"],
    "criado_em": "2026-09-01T10:00:00+00:00",
    "atualizado_em": "2026-09-10T15:30:00+00:00",
}


def _abrir_painel(monkeypatch, lista=None, admin=False):
    """Servidor de verdade na aba Processos, com o banco dublado."""
    from src import auth

    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(auth, "tem_admin", lambda: True)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)
    padrao = [dict(PROCESSO)] if lista is None else [dict(p) for p in lista]
    monkeypatch.setattr(db, "listar_processos",
                        lambda limite=50, usuario_id=None: padrao)
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["usuario"] = {
        "id": "u1", "nome": "Servidor Comum", "login": "servidor",
        "papel": "admin" if admin else "usuario",
    }
    at.session_state["pagina"] = "Processos"
    return at


# ---------------------------------------------------------------------------
# A aba existe, e para todo mundo
# ---------------------------------------------------------------------------
def test_a_aba_processos_aparece_para_o_servidor_comum(monkeypatch):
    """
    Sem flag e sem ser admin. O painel substituiu o expander "Processos
    salvos"; se dependesse de flag ou de papel, tirar o expander teria
    deixado o servidor sem NENHUMA forma de retomar um processo.
    """
    at = _abrir_painel(monkeypatch)
    at.run()
    assert not at.exception
    navegacao = [r for r in at.radio if r.key == "pagina"]
    assert navegacao and "Processos" in navegacao[0].options


def test_processos_vem_logo_depois_de_novo_processo(monkeypatch):
    at = _abrir_painel(monkeypatch)
    at.run()
    opcoes = [r for r in at.radio if r.key == "pagina"][0].options
    assert opcoes[:2] == ["Novo processo", "Processos"]


def test_o_expander_de_processos_salvos_saiu_da_barra_lateral(monkeypatch):
    """
    Dois lugares para a mesma coisa é pior que um: o da barra lateral
    mostrava menos e podia divergir do painel.
    """
    at = _abrir_painel(monkeypatch)
    at.run()
    rotulos = [e.label for e in at.expander]
    assert "Processos salvos" not in rotulos


# ---------------------------------------------------------------------------
# A linha mostra andamento, não só data
# ---------------------------------------------------------------------------
def test_a_linha_mostra_status_etapa_datas_e_progresso(monkeypatch):
    """O problema que originou o painel: antes havia só a data."""
    at = _abrir_painel(monkeypatch)
    at.run()
    texto = " ".join(m.value for m in at.markdown)
    texto += " ".join(c.value for c in at.caption)

    assert "ETP" in texto                       # etapa atual
    assert "10/09/2026" in texto                # última alteração
    assert "01/09/2026" in texto                # criação
    assert "1 de 4" in texto                    # progresso, em número


def test_processo_sem_nome_mostra_orgao_e_objeto(monkeypatch):
    at = _abrir_painel(monkeypatch)
    at.run()
    texto = " ".join(m.value for m in at.markdown)
    assert "Prefeitura de Exemplo" in texto
    assert "Aquisição de material de expediente" in texto


def test_o_nome_proprio_tem_precedencia_na_tela(monkeypatch):
    at = _abrir_painel(monkeypatch,
                       lista=[{**PROCESSO, "nome": "Canetas 2027"}])
    at.run()
    texto = " ".join(m.value for m in at.markdown)
    assert "Canetas 2027" in texto


def test_lista_vazia_orienta_em_vez_de_ficar_em_branco(monkeypatch):
    at = _abrir_painel(monkeypatch, lista=[])
    at.run()
    assert not at.exception
    assert any("Novo processo" in i.value for i in at.info)


# ---------------------------------------------------------------------------
# Renomear
# ---------------------------------------------------------------------------
def test_renomear_nao_carrega_o_processo(monkeypatch):
    """
    `renomear_processo` manda SÓ o nome. Se mandasse o registro inteiro,
    como `salvar_processo` faz, renomear a partir da lista — onde nenhum
    processo está carregado — gravaria `dados` e `documentos` vazios por
    cima do conteúdo real.
    """
    enviados = {}

    def falso_update(valores):
        enviados.update(valores)
        class _Q:
            def eq(self, *_a, **_k):
                return self
            def execute(self):
                class _R:
                    data = [{"id": PROCESSO["id"]}]
                return _R()
        return _Q()

    class _Tabela:
        def update(self, valores):
            return falso_update(valores)

    monkeypatch.setattr(db, "_cliente",
                        lambda: type("C", (), {"table": lambda s, n: _Tabela()})())
    db.renomear_processo(PROCESSO["id"], "Canetas 2027")
    assert enviados == {"nome": "Canetas 2027"}


def test_nome_e_normalizado_e_limitado(monkeypatch):
    """
    120 caracteres não é regra de negócio: é o que cabe numa linha sem
    empurrar as outras colunas para fora da tela. Cortar no banco impede
    que se guarde um texto que a interface nunca mostraria inteiro.
    """
    enviados = {}

    class _Tabela:
        def update(self, valores):
            enviados.update(valores)
            class _Q:
                def eq(self, *_a, **_k):
                    return self
                def execute(self):
                    return type("R", (), {"data": []})()
            return _Q()

    monkeypatch.setattr(db, "_cliente",
                        lambda: type("C", (), {"table": lambda s, n: _Tabela()})())
    gravado = db.renomear_processo("x", "  Canetas   de   2027  ")
    assert gravado == "Canetas de 2027"
    assert enviados["nome"] == "Canetas de 2027"

    longo = db.renomear_processo("x", "A" * 200)
    assert len(longo) == 120


# ---------------------------------------------------------------------------
# Excluir
# ---------------------------------------------------------------------------
def test_excluir_pede_confirmacao_antes_de_apagar(monkeypatch):
    """
    O painel antigo apagava no primeiro clique. Um processo com quatro
    documentos aprovados não pode sumir por um clique errado numa lista.
    """
    apagados = []
    monkeypatch.setattr(db, "excluir_processo", lambda pid: apagados.append(pid))
    at = _abrir_painel(monkeypatch)
    at.run()

    excluir = [b for b in at.button if (b.key or "").startswith("excluir_")]
    assert excluir, "o botão Excluir precisa continuar existindo"
    excluir[0].click().run()

    assert apagados == [], "o primeiro clique não pode apagar"
    assert any("excluir" in w.value.lower() for w in at.warning)
    assert [b for b in at.button if (b.key or "").startswith("conf_excluir_")]


def test_a_confirmacao_apaga(monkeypatch):
    apagados = []
    monkeypatch.setattr(db, "excluir_processo", lambda pid: apagados.append(pid))
    at = _abrir_painel(monkeypatch)
    at.run()
    [b for b in at.button if (b.key or "").startswith("excluir_")][0].click().run()
    [b for b in at.button if (b.key or "").startswith("conf_excluir_")][0].click().run()
    assert apagados == [PROCESSO["id"]]


# ---------------------------------------------------------------------------
# Banco indisponível
# ---------------------------------------------------------------------------
def test_sem_banco_o_app_para_antes_da_aba(monkeypatch):
    """
    Sem banco o app mostra "Configuração necessária" e nem chega ao
    painel — a guarda é a montante, em `app.py`.

    A primeira versão desta prova esperava a mensagem do próprio painel e
    falhava: o caminho não existe. O `render_processos` mantém a checagem
    mesmo assim, como rede para quem venha a chamá-lo de outro lugar, mas
    quem protege o servidor hoje é a guarda do app — e é ela que esta
    prova fixa.
    """
    from src import auth

    # A guarda do app é `auth.precisa_configurar()`. Fixá-la é a forma
    # honesta de declarar a pré-condição "sem banco": depender de
    # `db.disponivel` sozinho fazia esta prova passar isolada e falhar na
    # suíte completa, porque o resultado dependia de estado ambiente
    # deixado por outro teste.
    monkeypatch.setattr(auth, "precisa_configurar", lambda: True)
    monkeypatch.setattr(auth, "tem_admin", lambda: True)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)
    monkeypatch.setattr(db, "disponivel", lambda: False)
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["usuario"] = {"id": "u1", "nome": "S", "login": "s",
                                   "papel": "usuario"}
    at.session_state["pagina"] = "Processos"
    at.run()

    assert not at.exception
    assert "Configuração necessária" in [s.value for s in at.subheader]
    # E nenhuma lista foi ao ar prometendo processos que não dá para ler.
    assert not [b for b in at.button if (b.key or "").startswith("abrir_")]
