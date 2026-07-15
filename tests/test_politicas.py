"""
Testes das políticas de aplicação (Fase 3 do V6): política verdadeira
aplica e falsa não (T04/T05), conflito bloqueia a publicação expondo as
duas (T06), camada derivada do escopo, simulação no motor real e
políticas publicadas entrando no motor do V5.
"""

import types

import pytest

from src import auth, catalogo, db, governanca, politicas

# ---------------------------------------------------------------------------
# banco fake (mesmo protocolo dos testes do catálogo)
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
    monkeypatch.setattr(auth, "modo_aberto", lambda: True)
    return tabelas


def _condicao_srp_bens():
    return {"op": "ALL", "children": [
        {"field": "procedimento.srp", "operator": "EQ", "value": True},
        {"field": "objeto.natureza", "operator": "EQ", "value": "BENS"},
    ]}


def _publicar(artefato, versao):
    versao = catalogo.transicionar(artefato, versao, "UNDER_REVIEW")
    versao = catalogo.transicionar(artefato, versao,
                                   "APPROVED_FOR_SIMULATION")
    versao = catalogo.transicionar(artefato, versao, "SHADOW")
    return politicas.publicar(artefato, versao)


# ---------------------------------------------------------------------------
# ponte catálogo → motor (camada pelo escopo)
# ---------------------------------------------------------------------------
def test_camada_derivada_do_escopo(banco):
    municipal, v_m = politicas.criar_politica(
        "politica.municipal", _condicao_srp_bens(),
        [{"type": "ALERTA", "mensagem": "x"}])
    plataforma, v_p = politicas.criar_politica(
        "politica.plataforma", _condicao_srp_bens(),
        [{"type": "ALERTA", "mensagem": "y"}], plataforma=True)
    assert politicas.como_regra(municipal, v_m)["camada"] == "municipio"
    assert politicas.como_regra(plataforma, v_p)["camada"] == "plataforma"


def test_apenas_publicadas_entram_no_motor(banco):
    artefato, versao = politicas.criar_politica(
        "politica.me-epp", _condicao_srp_bens(),
        [{"type": "INCLUIR_CLAUSULA", "target": "clausula.me-epp"}])
    assert politicas.regras_publicadas() == []  # rascunho não entra
    _publicar(artefato, versao)
    regras = politicas.regras_publicadas()
    assert len(regras) == 1
    assert regras[0]["chave_estavel"] == "politica.me-epp"
    assert regras[0]["status"] == "PUBLISHED"


# ---------------------------------------------------------------------------
# T04/T05: simulação — verdadeira aplica, falsa não
# ---------------------------------------------------------------------------
def test_simulacao_politica_verdadeira_e_falsa(banco):
    artefato, versao = politicas.criar_politica(
        "politica.me-epp", _condicao_srp_bens(),
        [{"type": "INCLUIR_CLAUSULA", "target": "clausula.me-epp"}])

    decisao = politicas.simular(artefato, versao, {
        "procedimento.srp": True, "objeto.natureza": "BENS"})
    assert decisao["resultado"]["clausulas_incluir"] == ["clausula.me-epp"]

    decisao = politicas.simular(artefato, versao, {
        "procedimento.srp": False, "objeto.natureza": "BENS"})
    assert decisao["resultado"]["clausulas_incluir"] == []

    # simulações persistidas com alvo e contexto
    assert len(banco["simulacoes"]) == 2
    assert banco["simulacoes"][0]["alvo"]["chave"] == "politica.me-epp"


# ---------------------------------------------------------------------------
# T06: conflito bloqueia a publicação e expõe as duas políticas
# ---------------------------------------------------------------------------
def test_conflito_bloqueia_publicacao(banco):
    inclui, v_inclui = politicas.criar_politica(
        "politica.inclui", _condicao_srp_bens(),
        [{"type": "INCLUIR_CLAUSULA", "target": "clausula.me-epp"}])
    _publicar(inclui, v_inclui)

    exclui, v_exclui = politicas.criar_politica(
        "politica.exclui",
        {"field": "procedimento.srp", "operator": "EQ", "value": True},
        [{"type": "EXCLUIR_CLAUSULA", "target": "clausula.me-epp"}])
    v_exclui = catalogo.transicionar(exclui, v_exclui, "UNDER_REVIEW")
    v_exclui = catalogo.transicionar(exclui, v_exclui,
                                     "APPROVED_FOR_SIMULATION")
    v_exclui = catalogo.transicionar(exclui, v_exclui, "SHADOW")
    with pytest.raises(politicas.ErroPolitica) as erro:
        politicas.publicar(exclui, v_exclui)
    assert "politica.inclui" in str(erro.value)
    assert "clausula.me-epp" in str(erro.value)
    # nada foi publicado
    assert not [v for v in banco["governanca_versoes"]
                if v["status"] == "PUBLISHED"
                and v.get("payload", {}).get("acoes", [{}])[0].get("type")
                == "EXCLUIR_CLAUSULA"]


def test_condicoes_disjuntas_nao_conflitam(banco):
    bens, v_bens = politicas.criar_politica(
        "politica.bens",
        {"field": "objeto.natureza", "operator": "EQ", "value": "BENS"},
        [{"type": "INCLUIR_CLAUSULA", "target": "clausula.x"}])
    _publicar(bens, v_bens)

    obras, v_obras = politicas.criar_politica(
        "politica.obras",
        {"field": "objeto.natureza", "operator": "EQ",
         "value": "OBRAS_ENGENHARIA"},
        [{"type": "EXCLUIR_CLAUSULA", "target": "clausula.x"}])
    v_obras = catalogo.transicionar(obras, v_obras, "UNDER_REVIEW")
    v_obras = catalogo.transicionar(obras, v_obras,
                                    "APPROVED_FOR_SIMULATION")
    v_obras = catalogo.transicionar(obras, v_obras, "SHADOW")
    publicada = politicas.publicar(obras, v_obras)  # não conflita: BENS ≠ OBRAS
    assert publicada["status"] == "PUBLISHED"


def test_prioridades_diferentes_nao_conflitam(banco):
    a, v_a = politicas.criar_politica(
        "politica.a", _condicao_srp_bens(),
        [{"type": "INCLUIR_CLAUSULA", "target": "clausula.y"}],
        prioridade=100)
    _publicar(a, v_a)
    b, v_b = politicas.criar_politica(
        "politica.b", _condicao_srp_bens(),
        [{"type": "EXCLUIR_CLAUSULA", "target": "clausula.y"}],
        prioridade=200)  # precedência explícita resolve
    v_b = catalogo.transicionar(b, v_b, "UNDER_REVIEW")
    v_b = catalogo.transicionar(b, v_b, "APPROVED_FOR_SIMULATION")
    v_b = catalogo.transicionar(b, v_b, "SHADOW")
    assert politicas.publicar(b, v_b)["status"] == "PUBLISHED"


# ---------------------------------------------------------------------------
# integração com o motor V5 (flag_visual_policy_builder)
# ---------------------------------------------------------------------------
def test_politica_publicada_age_no_motor(banco):
    from src import conhecimento, fatos

    artefato, versao = politicas.criar_politica(
        "politica.me-epp", _condicao_srp_bens(),
        [{"type": "INCLUIR_CLAUSULA", "target": "clausula.me-epp"}])
    _publicar(artefato, versao)

    lista = fatos.extrair_do_formulario({
        "objeto": "Material escolar",
        "modelo_execucao": "Sistema de Registro de Preços (SRP)",
        "valor_estimado": 100.0,
        "itens": [{"descricao": "Caneta", "quantidade": 1,
                   "valor_unitario": 100.0}],
    }, "p1")
    decisao = conhecimento.resolver(
        lista, politicas.regras_publicadas(), set(), "p1")
    assert decisao["resultado"]["clausulas_incluir"] == ["clausula.me-epp"]
