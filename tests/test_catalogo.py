"""
Testes do catálogo de cláusulas (Fase 2 do V6): criação com papel,
workflow completo até publicar com SUPERSEDE, derivação de versão,
seed dos perfis sem publicação automática (T14), papéis bloqueando
transições e a página Governança escondida do servidor comum (T09/T24).
"""

import types

import pytest

from src import auth, catalogo, db, governanca

# ---------------------------------------------------------------------------
# banco fake (mesmo protocolo do supabase-py usado pelo db.py)
# ---------------------------------------------------------------------------
class _TabelaFake:
    def __init__(self, banco, nome):
        self.banco, self.nome = banco, nome
        self._acao, self._dados, self._filtros = "select", None, []

    def insert(self, dados):
        self._acao, self._dados = "insert", dados
        return self

    def update(self, dados):
        self._acao, self._dados = "update", dados
        return self

    def select(self, *_):
        self._acao = "select"
        return self

    def eq(self, campo, valor):
        self._filtros.append((campo, valor))
        return self

    def is_(self, campo, _valor):
        self._filtros.append((campo, None))
        return self

    def order(self, *_, **__):
        return self

    def limit(self, *_):
        return self

    def execute(self):
        if self._acao == "insert":
            registro = {**self._dados,
                        "id": f"{self.nome}-{len(self.banco)}"}
            self.banco.append(registro)
            return types.SimpleNamespace(data=[registro])
        filtrados = [r for r in self.banco if all(
            r.get(c) == v for c, v in self._filtros)]
        if self._acao == "update":
            for r in filtrados:
                r.update(self._dados)
            return types.SimpleNamespace(data=filtrados)
        return types.SimpleNamespace(data=filtrados)


@pytest.fixture
def banco(monkeypatch):
    tabelas: dict[str, list] = {}

    def table(_self, nome):
        return _TabelaFake(tabelas.setdefault(nome, []), nome)

    cliente = types.SimpleNamespace(table=types.MethodType(table, object()))
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "_cliente", lambda: cliente)
    # modo aberto = proprietario (todas as permissões)
    monkeypatch.setattr(auth, "modo_aberto", lambda: True)
    return tabelas


def _payload(titulo="DA GARANTIA"):
    return {"titulo": titulo, "comportamento": "AI_GENERATED",
            "blocos": ["Texto oficial da cláusula."],
            "tipo_documental": "tr"}


# ---------------------------------------------------------------------------
# criação → revisão → shadow → publicação (fluxo completo, T25 parcial)
# ---------------------------------------------------------------------------
def test_fluxo_completo_ate_publicar_com_supersede(banco):
    artefato, v1 = catalogo.criar_clausula("clausula.tr.garantia",
                                           _payload())
    assert v1["status"] == "DRAFT" and v1["versao"] == 1

    v1 = catalogo.transicionar(artefato, v1, "UNDER_REVIEW")
    v1 = catalogo.transicionar(artefato, v1, "APPROVED_FOR_SIMULATION")
    v1 = catalogo.transicionar(artefato, v1, "SHADOW")
    v1 = catalogo.transicionar(artefato, v1, "PUBLISHED")
    assert v1["status"] == "PUBLISHED"

    # derivar, revisar e publicar a v2: a v1 é SUPERSEDED automaticamente
    v2 = catalogo.derivar_nova_versao(artefato, v1)
    assert v2["versao"] == 2 and v2["status"] == "DRAFT"
    v2 = catalogo.transicionar(artefato, v2, "UNDER_REVIEW")
    v2 = catalogo.transicionar(artefato, v2, "APPROVED_FOR_SIMULATION")
    v2 = catalogo.transicionar(artefato, v2, "SHADOW")
    v2 = catalogo.transicionar(artefato, v2, "PUBLISHED")

    versoes = {v["versao"]: v["status"]
               for v in banco["governanca_versoes"]}
    assert versoes == {1: "SUPERSEDED", 2: "PUBLISHED"}
    # trilha de auditoria registrou tudo
    eventos = [e["tipo_evento"] for e in banco["governanca_eventos"]]
    assert "clausula_published" in eventos
    assert "clausula_versao_superada" in eventos


def test_nao_ha_atalho_de_rascunho_para_publicada(banco):
    artefato, v1 = catalogo.criar_clausula("clausula.tr.x", _payload())
    with pytest.raises(catalogo.ErroCatalogo, match="transição inválida"):
        catalogo.transicionar(artefato, v1, "PUBLISHED")


def test_editar_publicada_e_impossivel_derivar_e_o_caminho(banco):
    artefato, v1 = catalogo.criar_clausula("clausula.tr.y", _payload())
    for destino in ("UNDER_REVIEW", "APPROVED_FOR_SIMULATION",
                    "SHADOW", "PUBLISHED"):
        v1 = catalogo.transicionar(artefato, v1, destino)
    with pytest.raises(catalogo.ErroCatalogo, match="imutável"):
        catalogo.editar_rascunho(v1, artefato["chave_estavel"],
                                 _payload("HACKEADO"))


def test_rascunho_editavel_atualiza_payload_e_hash(banco):
    artefato, v1 = catalogo.criar_clausula("clausula.tr.z", _payload())
    hash_original = v1["hash"]
    atualizada = catalogo.editar_rascunho(
        v1, artefato["chave_estavel"], _payload("NOVO TÍTULO"))
    assert atualizada["payload"]["titulo"] == "NOVO TÍTULO"
    assert atualizada["hash"] != hash_original


# ---------------------------------------------------------------------------
# papéis: revisor não cria, publicador não revisa, servidor nada (T09)
# ---------------------------------------------------------------------------
def _com_papel(monkeypatch, papel):
    monkeypatch.setattr(auth, "modo_aberto", lambda: False)
    monkeypatch.setattr(auth, "usuario_logado",
                        lambda: {"papel": "usuario",
                                 "papel_governanca": papel})


def test_papeis_limitam_as_transicoes(banco, monkeypatch):
    artefato, v1 = catalogo.criar_clausula("clausula.tr.p", _payload())
    v1 = catalogo.transicionar(artefato, v1, "UNDER_REVIEW")

    _com_papel(monkeypatch, "publicador")
    with pytest.raises(catalogo.ErroCatalogo, match="papel"):
        catalogo.transicionar(artefato, v1, "APPROVED_FOR_SIMULATION")

    _com_papel(monkeypatch, "revisor_juridico")
    v1 = catalogo.transicionar(artefato, v1, "APPROVED_FOR_SIMULATION")
    v1 = catalogo.transicionar(artefato, v1, "SHADOW")
    with pytest.raises(catalogo.ErroCatalogo, match="papel"):
        catalogo.transicionar(artefato, v1, "PUBLISHED")

    _com_papel(monkeypatch, "publicador")
    v1 = catalogo.transicionar(artefato, v1, "PUBLISHED")
    assert v1["status"] == "PUBLISHED"


def test_servidor_comum_nao_cria_clausula(banco, monkeypatch):
    _com_papel(monkeypatch, None)
    with pytest.raises(catalogo.ErroCatalogo, match="papel"):
        catalogo.criar_clausula("clausula.tr.w", _payload())


# ---------------------------------------------------------------------------
# seed dos perfis: só rascunhos, idempotente (T14)
# ---------------------------------------------------------------------------
def test_seed_dos_perfis_cria_rascunhos_sem_publicar(banco):
    criadas = catalogo.semear_dos_perfis()
    assert len(criadas) > 30  # DFD 9 + ETP + TR obrigatórias
    assert all(v["status"] == "DRAFT"
               for v in banco["governanca_versoes"])
    equipe = next(i for i in catalogo.listar_com_situacao()
                  if "equipe-de-planejamento" in
                  i["artefato"]["chave_estavel"]
                  and i["artefato"]["chave_estavel"].startswith(
                      "clausula.dfd"))
    assert equipe["ultima"]["payload"]["comportamento"] == "FIXED_LOCKED"

    # reexecutar não duplica
    assert catalogo.semear_dos_perfis() == []


# ---------------------------------------------------------------------------
# página Governança invisível sem flag/papel (T24)
# ---------------------------------------------------------------------------
def test_pagina_governanca_exige_flag_e_papel(monkeypatch):
    from src.ui import governanca_ui

    monkeypatch.setattr(governanca_ui.db, "flag_ativa", lambda n: False)
    assert governanca_ui.disponivel() is False  # flag OFF

    monkeypatch.setattr(governanca_ui.db, "flag_ativa",
                        lambda n: n == governanca.FLAG_CENTRO)
    monkeypatch.setattr(auth, "modo_aberto", lambda: False)
    monkeypatch.setattr(auth, "usuario_logado",
                        lambda: {"papel": "usuario"})
    assert governanca_ui.disponivel() is False  # servidor comum

    monkeypatch.setattr(auth, "usuario_logado",
                        lambda: {"papel": "admin"})
    assert governanca_ui.disponivel() is True
