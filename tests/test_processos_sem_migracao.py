"""
A janela entre o deploy do código e a aplicação da 0022.

O código que lista processos pede a coluna `nome` no `select`. A 0022,
que cria a coluna, ainda não rodou em produção — e migração não se
aplica sozinha junto com o deploy. Entre um e outro existe um intervalo
real, de horas ou dias, em que a aba Processos pediria uma coluna que o
banco não tem e devolveria erro para TODO servidor.

Um painel que só funciona depois que alguém lembra de rodar SQL não é um
painel: é uma pendência com interface. Estas provas fixam o
comportamento nessa janela — a lista aparece, renomear explica por que
está indisponível em vez de falhar com referência de incidente, e nada
disso mascara um erro de banco de verdade.

O que NÃO está aqui: a 0022 em si. Ela foi ensaiada contra um PostgreSQL
local com o schema real do repositório, o que é outro tipo de prova.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import db

APP = str(Path(__file__).resolve().parents[1] / "app.py")

# A mensagem que o PostgREST devolve quando o `select` pede coluna que
# não existe. Copiada do formato real (código 42703 do PostgreSQL) em vez
# de inventada: uma detecção afinada para um texto que o servidor nunca
# manda não detecta nada em produção.
ERRO_SELECT = (
    '{"code":"42703","details":null,"hint":null,'
    '"message":"column processos.nome does not exist"}'
)
# E a do `update`, que é DIFERENTE: aqui o PostgREST nem chega ao banco,
# ele falha antes, no cache de schema. Tratar só a primeira deixaria
# renomear quebrado do jeito feio.
ERRO_UPDATE = (
    '{"code":"PGRST204",'
    '"message":"Could not find the \'nome\' column of '
    '\'processos\' in the schema cache"}'
)

LINHA_SEM_NOME = {
    "id": "11111111-1111-1111-1111-111111111111",
    "orgao": "Prefeitura de Exemplo",
    "objeto": "Aquisição de material de expediente",
    "etapa": 1,
    "dados": {},
    "documentos": {"dfd": "texto"},
    "aprovados": ["dfd"],
    "criado_em": "2026-09-01T10:00:00+00:00",
    "atualizado_em": "2026-09-10T15:30:00+00:00",
}


class _Tabela:
    def __init__(self, registro, erro_select, erro_update):
        self._registro = registro
        self._erro_select = erro_select
        self._erro_update = erro_update
        self._op = ""

    def select(self, campos):
        self._registro.setdefault("selects", []).append(campos)
        self._op = "select"
        return self

    def update(self, valores):
        self._registro.setdefault("updates", []).append(valores)
        self._op = "update"
        return self

    def eq(self, *_a):
        return self

    def order(self, *_a, **_kw):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        if self._op == "update":
            if self._erro_update:
                raise RuntimeError(self._erro_update)
            return types.SimpleNamespace(data=[{}])
        campos = self._registro["selects"][-1]
        if self._erro_select and "nome" in campos:
            raise RuntimeError(self._erro_select)
        return types.SimpleNamespace(data=[dict(LINHA_SEM_NOME)])


def _cliente(registro, *, erro_select="", erro_update=""):
    class _Cliente:
        def table(self, _nome):
            return _Tabela(registro, erro_select, erro_update)

    return _Cliente()


@pytest.fixture(autouse=True)
def _estado_limpo():
    """
    A flag de coluna ausente é global do módulo. Sem este reset, a ordem
    das provas passaria a importar — e prova cujo resultado depende da
    vizinha não prova nada.
    """
    db.esquecer_estado_da_coluna_nome()
    yield
    db.esquecer_estado_da_coluna_nome()


# ---------------------------------------------------------------------------
# A listagem
# ---------------------------------------------------------------------------
def test_a_listagem_sobrevive_a_coluna_ausente(monkeypatch):
    registro = {}
    monkeypatch.setattr(
        db, "_cliente", lambda: _cliente(registro, erro_select=ERRO_SELECT))

    lista = db.listar_processos()

    assert len(lista) == 1
    assert lista[0]["orgao"] == "Prefeitura de Exemplo"


def test_a_segunda_tentativa_nao_pede_a_coluna(monkeypatch):
    """
    A queda tem de ser a MESMA consulta sem `nome`, não uma consulta
    reduzida. O painel deriva status, etapa e progresso de `dados`,
    `documentos` e `aprovados`: perder qualquer um deles trocaria o erro
    por uma lista que mente sobre o andamento.
    """
    registro = {}
    monkeypatch.setattr(
        db, "_cliente", lambda: _cliente(registro, erro_select=ERRO_SELECT))

    db.listar_processos()

    primeiro, segundo = registro["selects"]
    assert "nome" in primeiro
    assert "nome" not in segundo
    for coluna in ("dados", "documentos", "aprovados", "etapa",
                   "criado_em", "atualizado_em"):
        assert coluna in segundo


def test_sem_a_coluna_o_app_sabe_que_ela_falta(monkeypatch):
    registro = {}
    monkeypatch.setattr(
        db, "_cliente", lambda: _cliente(registro, erro_select=ERRO_SELECT))

    db.listar_processos()

    assert db.coluna_nome_disponivel() is False


def test_quando_a_migracao_roda_o_app_volta_sozinho(monkeypatch):
    """
    Sem isto, aplicar a 0022 com o app no ar não bastaria: ele seguiria
    na consulta degradada até alguém reiniciar o serviço. O estado é
    reavaliado a cada listagem justamente para não exigir reinício.
    """
    registro = {}
    monkeypatch.setattr(
        db, "_cliente", lambda: _cliente(registro, erro_select=ERRO_SELECT))
    db.listar_processos()
    assert db.coluna_nome_disponivel() is False

    # A migração roda: o select com `nome` passa a funcionar.
    monkeypatch.setattr(db, "_cliente", lambda: _cliente({}))
    db.listar_processos()

    assert db.coluna_nome_disponivel() is True


def test_erro_de_banco_de_verdade_nao_vira_queda_silenciosa(monkeypatch):
    """
    A detecção precisa ser estreita. Se qualquer falha no `select`
    disparasse a segunda tentativa, uma queda de conexão viraria duas
    tentativas e a mesma mensagem genérica — com o dobro da espera.
    """
    registro = {}
    monkeypatch.setattr(
        db, "_cliente",
        lambda: _cliente(registro, erro_select="connection refused"))

    with pytest.raises(db.ErroBanco):
        db.listar_processos()

    assert len(registro["selects"]) == 1
    assert db.coluna_nome_disponivel() is True


def test_a_deteccao_entende_o_erro_REAL_da_biblioteca():
    """
    As provas acima usam o texto do erro. Esta usa a classe de exceção
    que o `supabase-py` realmente levanta — porque a detecção precisa
    funcionar contra o objeto que chega em produção, não contra a string
    que eu imaginei que ele produz.

    Ela também é o alarme para o dia em que a biblioteca mudar o formato:
    uma detecção presa ao texto sairia do ar em silêncio, e a aba
    Processos quebraria no cenário que ela existe para cobrir.
    """
    from postgrest.exceptions import APIError

    ausente_no_select = APIError({
        "code": "42703", "message": "column processos.nome does not exist",
        "hint": None, "details": None})
    ausente_no_update = APIError({
        "code": "PGRST204",
        "message": "Could not find the 'nome' column of 'processos' "
                   "in the schema cache",
        "hint": None, "details": None})
    outra_coisa = APIError({
        "code": "PGRST301", "message": "JWT expired",
        "hint": None, "details": None})

    assert db._e_coluna_nome_ausente(ausente_no_select)
    assert db._e_coluna_nome_ausente(ausente_no_update)
    assert not db._e_coluna_nome_ausente(outra_coisa)


def test_outra_coluna_ausente_nao_e_tratada_como_a_nossa():
    """
    `dados` sumir do banco é outro problema, e um bem pior. Se a mesma
    queda o absorvesse, o painel repetiria a consulta sem `nome` — que
    falharia de novo, agora com a mensagem genérica, escondendo qual
    coluna realmente faltou.
    """
    from postgrest.exceptions import APIError

    outra = APIError({
        "code": "42703", "message": "column processos.dados does not exist",
        "hint": None, "details": None})

    assert not db._e_coluna_nome_ausente(outra)


# ---------------------------------------------------------------------------
# Renomear
# ---------------------------------------------------------------------------
def test_renomear_sem_a_coluna_explica_o_que_falta(monkeypatch):
    """
    A mensagem genérica de banco manda o servidor "informar a referência
    ao suporte" — e o suporte é você. Aqui a causa é conhecida e tem uma
    ação associada, então a tela diz qual é.
    """
    monkeypatch.setattr(
        db, "_cliente", lambda: _cliente({}, erro_update=ERRO_UPDATE))

    with pytest.raises(db.ErroBanco) as capturado:
        db.renomear_processo("11111111-1111-1111-1111-111111111111", "Novo")

    mensagem = str(capturado.value)
    assert "0022" in mensagem
    assert "Referência:" not in mensagem


def test_renomear_normal_continua_gravando(monkeypatch):
    registro = {}
    monkeypatch.setattr(db, "_cliente", lambda: _cliente(registro))

    gravado = db.renomear_processo("11111111-1111-1111-1111-111111111111",
                                   "  Aquisição   2027  ")

    assert gravado == "Aquisição 2027"
    assert registro["updates"] == [{"nome": "Aquisição 2027"}]


# ---------------------------------------------------------------------------
# A tela
# ---------------------------------------------------------------------------
def _painel(monkeypatch, *, coluna_existe: bool):
    from src import auth

    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(auth, "tem_admin", lambda: True)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)
    monkeypatch.setattr(db, "listar_processos",
                        lambda limite=50, usuario_id=None: [dict(LINHA_SEM_NOME)])
    monkeypatch.setattr(db, "coluna_nome_disponivel", lambda: coluna_existe)
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["usuario"] = {
        "id": "u1", "nome": "Servidor", "login": "s", "papel": "usuario"}
    at.session_state["pagina"] = "Processos"
    at.run()
    return at


def test_o_painel_abre_sem_a_coluna(monkeypatch):
    at = _painel(monkeypatch, coluna_existe=False)

    assert not at.exception
    # A lista continua útil: nome cai para "órgão — objeto", e o
    # andamento não dependia da coluna nenhuma hora.
    texto = " ".join(m.value for m in at.markdown)
    assert "Prefeitura de Exemplo" in texto
    assert "Etapa atual:" in texto


def test_sem_a_coluna_nao_ha_botao_de_renomear(monkeypatch):
    """
    Oferecer o botão e falhar no clique seria pior do que não oferecer:
    o servidor digitaria um nome antes de descobrir.
    """
    at = _painel(monkeypatch, coluna_existe=False)

    assert not any((b.key or "").startswith("renomear_") for b in at.button)


def test_sem_a_coluna_a_tela_diz_por_que(monkeypatch):
    at = _painel(monkeypatch, coluna_existe=False)

    avisos = " ".join(e.value for e in at.info) + " ".join(
        w.value for w in at.warning)
    assert "renomear" in avisos.lower()


def test_com_a_coluna_o_botao_esta_la(monkeypatch):
    """
    O contrapeso das três acima: elas passariam todas num painel que
    nunca mostra Renomear para ninguém.
    """
    at = _painel(monkeypatch, coluna_existe=True)

    assert any((b.key or "").startswith("renomear_") for b in at.button)
    avisos = " ".join(e.value for e in at.info) + " ".join(
        w.value for w in at.warning)
    assert "0022" not in avisos
