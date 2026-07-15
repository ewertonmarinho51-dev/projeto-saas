"""
Testes das Fases 5–6 do V6: montagem determinística de template por
blocos (cláusula fixa preservada — T10; parâmetro não autorizado
rejeitado — T11; snapshot com versões/hashes — T03) e herança
plataforma → município com override, comparação e restauração (T07/T08)
sem duplicar o catálogo.
"""

import types

import pytest

from src import auth, catalogo, db, governanca, heranca, templates_gov

# ---------------------------------------------------------------------------
# montagem de template (sem banco: cláusulas injetadas)
# ---------------------------------------------------------------------------
def _clausula(chave, comportamento="FIXED_PARAMETERIZED", blocos=None,
              permitidos=("percentual",), obrigatorios=("percentual",)):
    return governanca.nova_versao_artefato("clausula", chave, {
        "titulo": "DA GARANTIA",
        "comportamento": comportamento,
        "blocos": blocos or ["A garantia será de {{percentual}}% do valor."],
        "parametros_permitidos": list(permitidos),
        "parametros_obrigatorios": list(obrigatorios),
    }, versao=3, status="PUBLISHED")


TEMPLATE = {"blocos": [
    {"id": "b1", "tipo": "titulo", "texto": "TERMO DE REFERÊNCIA"},
    {"id": "b2", "tipo": "metadados", "campos": ["orgao.nome"]},
    {"id": "b3", "tipo": "clausula_catalogo",
     "clausula": "clausula.tr.garantia"},
    {"id": "b4", "tipo": "clausula_catalogo",
     "clausula": "clausula.tr.srp",
     "condicao": {"field": "procedimento.srp", "operator": "EQ",
                  "value": True}},
    {"id": "b5", "tipo": "tabela"},
    {"id": "b6", "tipo": "assinatura"},
]}

CLAUSULAS = {
    "clausula.tr.garantia": _clausula("clausula.tr.garantia"),
    "clausula.tr.srp": _clausula(
        "clausula.tr.srp", comportamento="FIXED_LOCKED",
        blocos=["Cláusula do SRP com texto imutável de {{tentativa}}."],
        permitidos=(), obrigatorios=()),
}


def test_montagem_com_parametro_autorizado_e_snapshot():
    resultado = templates_gov.montar(
        TEMPLATE, {"orgao.nome": "Prefeitura", "procedimento.srp": True},
        parametros={"percentual": 5}, clausulas=CLAUSULAS)
    texto = resultado["texto"]
    assert "# TERMO DE REFERÊNCIA" in texto
    assert "**orgao.nome**: Prefeitura" in texto
    assert "A garantia será de 5% do valor." in texto
    assert "[[TABELA_ITENS]]" in texto
    assert "Assinatura da autoridade" in texto
    # T03: snapshot preserva chave, versão e hash das cláusulas usadas
    assert {"chave": "clausula.tr.garantia", "versao": 3,
            "hash": CLAUSULAS["clausula.tr.garantia"]["hash"]} in \
        resultado["clausulas_usadas"]
    assert resultado["pendencias"] == []


def test_clausula_fixa_entra_literal_sem_substituicao():
    """T10: FIXED_LOCKED preservada — nem {{marcadores}} são tocados."""
    resultado = templates_gov.montar(
        TEMPLATE, {"procedimento.srp": True},
        parametros={"percentual": 5, "tentativa": "HACK"},
        clausulas=CLAUSULAS)
    assert "texto imutável de {{tentativa}}." in resultado["texto"]
    assert "HACK" not in resultado["texto"]


def test_parametro_nao_autorizado_e_rejeitado():
    """T11: cláusula usa {{prazo}} mas só 'percentual' é permitido."""
    clausulas = {"clausula.tr.garantia": _clausula(
        "clausula.tr.garantia",
        blocos=["Garantia de {{percentual}}% por {{prazo}} meses."])}
    template = {"blocos": [{"id": "b1", "tipo": "clausula_catalogo",
                            "clausula": "clausula.tr.garantia"}]}
    with pytest.raises(templates_gov.ErroTemplate, match="prazo"):
        templates_gov.montar(template, {}, {"percentual": 5, "prazo": 12},
                             clausulas=clausulas)


def test_parametro_obrigatorio_ausente_vira_pendencia():
    resultado = templates_gov.montar(
        {"blocos": [{"id": "b1", "tipo": "clausula_catalogo",
                     "clausula": "clausula.tr.garantia"}]},
        {}, {}, clausulas={"clausula.tr.garantia":
                           _clausula("clausula.tr.garantia")})
    assert resultado["pendencias"] == [{
        "tipo": "parametro_obrigatorio", "parametro": "percentual",
        "clausula": "DA GARANTIA"}]


def test_condicao_de_bloco_exclui_clausula():
    resultado = templates_gov.montar(
        TEMPLATE, {"procedimento.srp": False},
        parametros={"percentual": 5}, clausulas=CLAUSULAS)
    assert "SRP" not in resultado["texto"]
    assert len(resultado["clausulas_usadas"]) == 1


def test_clausula_nao_publicada_vira_pendencia():
    resultado = templates_gov.montar(
        {"blocos": [{"id": "b1", "tipo": "clausula_catalogo",
                     "clausula": "clausula.inexistente"}]},
        {}, {}, clausulas={})
    assert resultado["pendencias"][0]["tipo"] == "clausula_nao_publicada"


# ---------------------------------------------------------------------------
# herança (banco fake compartilhado com os testes do catálogo)
# ---------------------------------------------------------------------------
from tests.test_catalogo import _TabelaFake  # noqa: E402


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


def _publicar(artefato, versao):
    versao = catalogo.transicionar(artefato, versao, "UNDER_REVIEW")
    versao = catalogo.transicionar(artefato, versao,
                                   "APPROVED_FOR_SIMULATION")
    versao = catalogo.transicionar(artefato, versao, "SHADOW")
    return catalogo.transicionar(artefato, versao, "PUBLISHED")


def _payload(titulo="DA GARANTIA"):
    return {"titulo": titulo, "comportamento": "AI_GENERATED",
            "blocos": ["Texto da plataforma."], "tipo_documental": "tr"}


def test_heranca_override_e_restauracao(banco):
    # 1. plataforma publica a cláusula
    plataforma, v_p = catalogo.criar_artefato(
        "clausula", "clausula.tr.garantia", _payload(), plataforma=True)
    _publicar(plataforma, v_p)

    linha = next(l for l in heranca.visao_heranca("clausula")
                 if l["chave"] == "clausula.tr.garantia")
    assert linha["origem"] == "plataforma"
    assert not linha["tem_override"]

    # 2. município sobrescreve (rascunho derivado; plataforma intacta)
    rascunho = heranca.sobrescrever(linha)
    assert rascunho["status"] == "DRAFT"
    municipais = [a for a in banco["governanca_artefatos"]
                  if a.get("tenant_id") == db.TENANT_PADRAO]
    assert len(municipais) == 1  # só o item sobrescrito, nada duplicado

    artefato_local = municipais[0]
    versao_local = catalogo.editar_rascunho(
        rascunho, "clausula.tr.garantia",
        {**_payload(), "blocos": ["Texto ajustado pelo município."]})
    _publicar(artefato_local, versao_local)

    linha = next(l for l in heranca.visao_heranca("clausula")
                 if l["chave"] == "clausula.tr.garantia")
    assert linha["origem"] == "municipio"  # T07: específico prevalece
    assert linha["tem_override"]
    efetiva = heranca.versao_efetiva("clausula", "clausula.tr.garantia")
    assert efetiva["payload"]["blocos"] == ["Texto ajustado pelo município."]

    comparacao = heranca.comparar(linha)
    assert comparacao["iguais"] is False
    assert "blocos" in comparacao["campos_diferentes"]

    # 3. restaurar herança: revoga o override, volta a valer a plataforma
    heranca.restaurar_heranca(linha)  # T08
    linha = next(l for l in heranca.visao_heranca("clausula")
                 if l["chave"] == "clausula.tr.garantia")
    assert linha["origem"] == "plataforma"
    # histórico preservado: o override existe, revogado
    revogadas = [v for v in banco["governanca_versoes"]
                 if v["status"] == "REVOKED"]
    assert len(revogadas) == 1


def test_sobrescrever_duas_vezes_e_recusado(banco):
    plataforma, v_p = catalogo.criar_artefato(
        "clausula", "clausula.tr.x", _payload(), plataforma=True)
    _publicar(plataforma, v_p)
    linha = next(l for l in heranca.visao_heranca("clausula")
                 if l["chave"] == "clausula.tr.x")
    heranca.sobrescrever(linha)
    linha = next(l for l in heranca.visao_heranca("clausula")
                 if l["chave"] == "clausula.tr.x")
    with pytest.raises(heranca.ErroHeranca, match="já possui override"):
        heranca.sobrescrever(linha)


def test_restaurar_sem_override_e_recusado(banco):
    plataforma, v_p = catalogo.criar_artefato(
        "clausula", "clausula.tr.y", _payload(), plataforma=True)
    _publicar(plataforma, v_p)
    linha = next(l for l in heranca.visao_heranca("clausula")
                 if l["chave"] == "clausula.tr.y")
    with pytest.raises(heranca.ErroHeranca, match="não tem override"):
        heranca.restaurar_heranca(linha)
