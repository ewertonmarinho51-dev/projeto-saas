"""
Testes das Fases 9–10 do V6: proposta a partir de um único parecer sem
dados específicos (T20), mudança jurídica exigindo papel, regressão
histórica expondo diferenças (T22), gate de publicação com aprovação
segregada e rollback restaurador sem apagar nada (T23).
"""

import types

import pytest

from src import auth, catalogo, db, governanca, laboratorio, politicas

# ---------------------------------------------------------------------------
# banco fake (protocolo do supabase-py)
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
    monkeypatch.setattr(db, "flag_ativa", lambda n: True)
    monkeypatch.setattr(auth, "modo_aberto", lambda: True)
    return tabelas


def _cluster(ocorrencias=1, achados=("a1",), pareceres=("p1",)):
    return {"id": "cluster-1", "rotulo": "Garantia sem percentual",
            "categoria": "nova_versao_clausula", "gravidade_maxima": "HIGH",
            "achado_ids": list(achados), "pareceres": list(pareceres),
            "ocorrencias": ocorrencias}


# ---------------------------------------------------------------------------
# T20: um único parecer origina proposta; sem dados específicos
# ---------------------------------------------------------------------------
def test_proposta_de_um_unico_parecer_sem_dados_especificos(banco):
    proposta = laboratorio.criar_proposta(
        _cluster(ocorrencias=1), "clausula",
        "Incluir percentual de garantia. Processo 2024.001 do Sr. Fulano, "
        "CPF 123.456.789-01.",
        mudanca={"texto": "Garantia de X%. Interessado: fulano@x.gov.br",
                 "processo_id": "proc-secreto"})
    payload = proposta["proposta"]
    # anonimizado e sem dados específicos
    assert "[CPF]" in payload["descricao"]
    assert "123.456" not in payload["descricao"]
    assert "[EMAIL]" in payload["mudanca"]["texto"]
    assert "processo_id" not in payload["mudanca"]  # descartado
    # vínculo com a evidência preservado
    assert payload["evidencias"]["achado_ids"] == ["a1"]
    assert payload["evidencias"]["ocorrencias"] == 1


def test_proposta_exige_evidencia_real(banco):
    with pytest.raises(laboratorio.ErroLaboratorio, match="sem evidência"):
        laboratorio.criar_proposta(
            {"achado_ids": [], "pareceres": []}, "clausula", "sugestão")


# ---------------------------------------------------------------------------
# mudança jurídica exige papel
# ---------------------------------------------------------------------------
def test_aceitar_mudanca_juridica_exige_publicador(banco, monkeypatch):
    proposta = laboratorio.criar_proposta(_cluster(), "clausula", "x")
    monkeypatch.setattr(auth, "modo_aberto", lambda: False)
    monkeypatch.setattr(auth, "usuario_logado",
                        lambda: {"papel": "usuario",
                                 "papel_governanca": "revisor_juridico"})
    with pytest.raises(laboratorio.ErroLaboratorio, match="aprovador"):
        laboratorio.decidir_proposta(proposta, "ACCEPTED")

    # alvo não jurídico: revisor pode aceitar
    operacional = laboratorio.criar_proposta(_cluster(), "operacional", "x")
    assert laboratorio.decidir_proposta(
        operacional, "ACCEPTED")["status"] == "ACCEPTED"


# ---------------------------------------------------------------------------
# T22: regressão histórica expõe as diferenças de decisão
# ---------------------------------------------------------------------------
def _publicar(artefato, versao):
    for destino in ("UNDER_REVIEW", "APPROVED_FOR_SIMULATION", "SHADOW",
                    "PUBLISHED"):
        versao = catalogo.transicionar(artefato, versao, destino)
    return versao


def test_regressao_historica_mostra_o_que_mudaria(banco):
    artefato, versao = politicas.criar_politica(
        "politica.me-epp",
        {"field": "procedimento.srp", "operator": "EQ", "value": True},
        [{"type": "INCLUIR_CLAUSULA", "target": "clausula.me-epp"}])
    contextos = [
        {"procedimento.srp": True},    # a candidata mudaria a decisão
        {"procedimento.srp": False},   # aqui não muda nada
    ]
    diferencas = laboratorio.regressao_historica(artefato, versao,
                                                 contextos)
    assert len(diferencas) == 1
    assert diferencas[0]["contexto"] == 0
    assert diferencas[0]["antes"]["clausulas_incluir"] == []
    assert diferencas[0]["depois"]["clausulas_incluir"] == ["clausula.me-epp"]


# ---------------------------------------------------------------------------
# gate de publicação: aprovação segregada (autor ≠ aprovador)
# ---------------------------------------------------------------------------
def test_gate_exige_aprovacao_de_outro_usuario(banco, monkeypatch):
    monkeypatch.setattr(auth, "modo_aberto", lambda: False)
    monkeypatch.setattr(auth, "usuario_logado",
                        lambda: {"id": "autor-1", "papel": "admin"})
    artefato, versao = catalogo.criar_artefato(
        "clausula", "clausula.garantia",
        {"titulo": "GARANTIA", "comportamento": "AI_GENERATED",
         "blocos": ["texto"]})
    versao = catalogo.transicionar(artefato, versao, "UNDER_REVIEW")
    versao = catalogo.transicionar(artefato, versao,
                                   "APPROVED_FOR_SIMULATION")
    versao = catalogo.transicionar(artefato, versao, "SHADOW")

    # sem aprovação registrada: o gate barra
    with pytest.raises(laboratorio.ErroLaboratorio, match="gate"):
        laboratorio.publicar_com_gate(artefato, versao)

    # o próprio autor não pode aprovar
    with pytest.raises(laboratorio.ErroLaboratorio, match="autor"):
        laboratorio.registrar_aprovacao(versao, "APROVADO")

    # outro usuário aprova → publica
    monkeypatch.setattr(auth, "usuario_logado",
                        lambda: {"id": "publicador-1", "papel": "admin"})
    laboratorio.registrar_aprovacao(versao, "APROVADO")
    publicada = laboratorio.publicar_com_gate(artefato, versao)
    assert publicada["status"] == "PUBLISHED"


# ---------------------------------------------------------------------------
# T23: rollback restaurador (nova publicação, nada apagado)
# ---------------------------------------------------------------------------
def test_rollback_restaurador_republica_o_conteudo_antigo(banco):
    artefato, v1 = catalogo.criar_artefato(
        "clausula", "clausula.garantia",
        {"titulo": "GARANTIA", "comportamento": "AI_GENERATED",
         "blocos": ["Versão original."]})
    _publicar(artefato, v1)
    v2 = catalogo.derivar_nova_versao(artefato, v1)
    v2 = catalogo.editar_rascunho(
        v2, "clausula.garantia",
        {"titulo": "GARANTIA", "comportamento": "AI_GENERATED",
         "blocos": ["Versão nova problemática."]})
    _publicar(artefato, v2)

    # rollback para o conteúdo da v1: cria a v3 e publica
    v1_atual = next(v for v in db.listar_versoes_governanca(artefato["id"])
                    if v["versao"] == 1)
    v3 = laboratorio.rollback_restaurador(artefato, v1_atual)
    assert v3["versao"] == 3
    assert v3["payload"]["blocos"] == ["Versão original."]

    versoes = {v["versao"]: v["status"]
               for v in db.listar_versoes_governanca(artefato["id"])}
    assert versoes == {1: "SUPERSEDED", 2: "SUPERSEDED", 3: "PUBLISHED"}
    # nada apagado: as três versões coexistem, release registrada
    assert len(banco["governanca_versoes"]) == 3
    releases = banco["governanca_publicacoes"]
    assert releases[-1]["reverte"] == str(v1_atual["id"])
