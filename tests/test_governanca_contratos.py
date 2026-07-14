"""
Testes da Fase 1 do pacote V5 (fundação observável): contratos de
domínio, hash canônico reproduzível, imutabilidade de regra publicada,
anonimização de feedback, transições de estado, flags default OFF e
persistência (append-only de decisões, isolamento por tenant).
"""

import pytest

from src import db, governanca

# ---------------------------------------------------------------------------
# hash canônico e reprodutibilidade (KQ-014)
# ---------------------------------------------------------------------------
def test_hash_canonico_estavel_e_independente_de_ordem():
    a = {"x": 1, "y": [1, 2], "z": {"b": 2, "a": 1}}
    b = {"z": {"a": 1, "b": 2}, "y": [1, 2], "x": 1}
    assert governanca.hash_canonico(a) == governanca.hash_canonico(b)
    assert governanca.hash_canonico(a) != governanca.hash_canonico(
        {**a, "x": 2})


# ---------------------------------------------------------------------------
# fatos canônicos
# ---------------------------------------------------------------------------
def test_fato_valido_com_hash():
    fato = governanca.novo_fato(
        "proc-1", "objeto.natureza", "BENS", "texto", "formulario:objeto")
    assert fato["status"] == "extraido" and fato["versao"] == 1
    assert fato["hash"]


def test_fato_sem_fonte_ou_tipo_invalido_rejeitado():
    with pytest.raises(governanca.ErroContrato, match="sem fonte"):
        governanca.novo_fato("p", "valor.total", 100, "numero", "  ")
    with pytest.raises(governanca.ErroContrato, match="tipo"):
        governanca.novo_fato("p", "valor.total", 100, "moeda", "formulario")
    with pytest.raises(governanca.ErroContrato, match="status"):
        governanca.novo_fato("p", "x", 1, "numero", "f", status="editado")


# ---------------------------------------------------------------------------
# condições estruturadas (formato compartilhado com o V6)
# ---------------------------------------------------------------------------
def test_condicao_bem_formada_passa():
    condicao = {"op": "ALL", "children": [
        {"field": "procurement.registryPrice", "operator": "EQ",
         "value": True},
        {"op": "NOT", "children": [
            {"field": "object.nature", "operator": "EQ", "value": "WORKS"},
        ]},
    ]}
    assert governanca.validar_condicao(condicao) == []


def test_condicao_malformada_lista_violacoes():
    assert governanca.validar_condicao({}) != []
    assert any("operador lógico" in e for e in governanca.validar_condicao(
        {"op": "XOR", "children": [{}]}))
    assert any("exatamente 1" in e for e in governanca.validar_condicao(
        {"op": "NOT", "children": [
            {"field": "a", "operator": "EQ", "value": 1},
            {"field": "b", "operator": "EQ", "value": 2}]}))
    assert any("sem value" in e for e in governanca.validar_condicao(
        {"field": "a", "operator": "EQ"}))
    assert governanca.validar_condicao(
        {"field": "a", "operator": "EXISTS"}) == []


# ---------------------------------------------------------------------------
# regras: validação, imutabilidade e derivação de versão
# ---------------------------------------------------------------------------
def _regra(status="DRAFT", versao=1):
    return governanca.nova_regra(
        "regra.me-epp.srp-bens", "municipio",
        {"field": "srp", "operator": "EQ", "value": True},
        [{"type": "INCLUIR_CLAUSULA", "target": "clausula.me-epp"}],
        status=status, versao=versao)


def test_regra_valida_com_hash():
    regra = _regra()
    assert regra["hash"] and regra["prioridade"] == 100


def test_regra_invalida_rejeitada():
    with pytest.raises(governanca.ErroContrato, match="camada"):
        governanca.nova_regra("r.x", "federal", {"field": "a",
                              "operator": "EQ", "value": 1},
                              [{"type": "ALERTA"}])
    with pytest.raises(governanca.ErroContrato, match="condição"):
        governanca.nova_regra("r.x", "municipio", {"op": "ALL"},
                              [{"type": "ALERTA"}])
    with pytest.raises(governanca.ErroContrato, match="sem ações"):
        governanca.nova_regra("r.x", "municipio",
                              {"field": "a", "operator": "EXISTS"}, [])
    with pytest.raises(governanca.ErroContrato, match="tipo inválido"):
        governanca.nova_regra("r.x", "municipio",
                              {"field": "a", "operator": "EXISTS"},
                              [{"type": "REESCREVER_TUDO"}])


def test_regra_publicada_e_imutavel_editar_deriva_nova_versao():
    publicada = _regra(status="PUBLISHED", versao=3)
    assert not governanca.regra_editavel(publicada)
    nova = governanca.derivar_nova_versao(publicada)
    assert nova["versao"] == 4 and nova["status"] == "DRAFT"
    assert nova["hash"] != publicada["hash"]
    assert publicada["versao"] == 3  # original intocada


# ---------------------------------------------------------------------------
# decisões reproduzíveis (KQ-014) — trilha fonte→fato→regra→decisão
# ---------------------------------------------------------------------------
def test_decisao_mesmas_entradas_mesmo_input_hash():
    regra = _regra(status="PUBLISHED")
    fato = governanca.novo_fato("p1", "srp", True, "booleano",
                                "formulario:srp")
    d1 = governanca.nova_decisao(
        "p1", "clausulas_aplicaveis", {"incluir": ["clausula.me-epp"]},
        [regra], [fato])
    d2 = governanca.nova_decisao(
        "p1", "clausulas_aplicaveis", {"incluir": ["clausula.me-epp"]},
        [regra], [fato])
    assert d1["input_hash"] == d2["input_hash"]
    assert d1["output_hash"] == d2["output_hash"]

    fato_v2 = governanca.novo_fato("p1", "srp", False, "booleano",
                                   "formulario:srp", versao=2)
    d3 = governanca.nova_decisao(
        "p1", "clausulas_aplicaveis", {"incluir": []}, [regra], [fato_v2])
    assert d3["input_hash"] != d1["input_hash"]


def test_decisao_aponta_versoes_de_regras_e_fatos():
    regra = _regra(status="PUBLISHED", versao=2)
    fato = governanca.novo_fato("p1", "valor.total", 45000, "numero",
                                "formulario:itens", versao=3)
    decisao = governanca.nova_decisao("p1", "bloqueio", {"bloqueia": False},
                                      [regra], [fato])
    assert decisao["regras_versoes"] == [{
        "chave": "regra.me-epp.srp-bens", "versao": 2,
        "hash": regra["hash"]}]
    assert decisao["fatos_versoes"][0]["path"] == "valor.total"
    assert decisao["fatos_versoes"][0]["versao"] == 3


# ---------------------------------------------------------------------------
# aprendizado: anonimização (KQ-009) e transições (KQ-010)
# ---------------------------------------------------------------------------
def test_feedback_nasce_anonimizado():
    feedback = governanca.novo_feedback("p1", "edicao_documento", {
        "observacao": "Contato: fulano@pref.gov.br, CPF 123.456.789-01, "
                      "CNPJ 12.345.678/0001-99, fone (91) 98888-7777, "
                      "matrícula 4521.",
    })
    texto = feedback["conteudo"]["observacao"]
    assert "[EMAIL]" in texto and "[CPF]" in texto and "[CNPJ]" in texto
    assert "[TELEFONE]" in texto and "[MATRICULA]" in texto
    assert "fulano@" not in texto and "123.456" not in texto
    assert feedback["status"] == "CAPTURED"


def test_transicoes_de_feedback():
    ok = governanca.transicao_feedback_valida
    assert ok("CAPTURED", "NORMALIZED")
    assert ok("UNDER_REVIEW", "APPROVED_FOR_SHADOW")
    assert ok("SHADOW_VALIDATED", "PUBLISHED")
    assert ok("PUBLISHED", "DEPRECATED")
    assert not ok("CAPTURED", "PUBLISHED")   # nada publica sozinho
    assert not ok("NORMALIZED", "PUBLISHED")
    assert not ok("REJECTED", "UNDER_REVIEW")


# ---------------------------------------------------------------------------
# flags default OFF (KQ-012)
# ---------------------------------------------------------------------------
def test_todas_as_flags_v5_nascem_desligadas(monkeypatch):
    monkeypatch.setattr(db, "obter_config", lambda chave: "")
    for flag in governanca.FLAGS_V5:
        assert db.flag_ativa(flag) is False, flag


# ---------------------------------------------------------------------------
# persistência: decisões append-only e isolamento por tenant (KQ-011)
# ---------------------------------------------------------------------------
class _TabelaFake:
    def __init__(self, banco, nome):
        self.banco, self.nome = banco, nome
        self._acao, self._dados, self._filtros = "select", None, []

    def insert(self, dados):
        self._acao, self._dados = "insert", dados
        return self

    def update(self, dados):
        raise AssertionError(f"UPDATE proibido em {self.nome} (append-only)")

    def select(self, *_):
        return self

    def eq(self, campo, valor):
        self._filtros.append((campo, valor))
        return self

    def neq(self, campo, valor):
        self._filtros.append((campo, ("neq", valor)))
        return self

    def order(self, *_, **__):
        return self

    def limit(self, *_):
        return self

    def execute(self):
        if self._acao == "insert":
            linhas = (self._dados if isinstance(self._dados, list)
                      else [self._dados])
            self.banco.extend(linhas)
            return type("R", (), {"data": linhas})
        filtrados = [r for r in self.banco if all(
            (r.get(c) != v[1] if isinstance(v, tuple) and v[0] == "neq"
             else r.get(c) == v)
            for c, v in self._filtros)]
        return type("R", (), {"data": filtrados})


def test_decisao_persistida_com_tenant_e_sem_update(monkeypatch):
    banco: list[dict] = []
    cliente = type("C", (), {
        "table": lambda self, nome: _TabelaFake(banco, nome)})()
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "_cliente", lambda: cliente)

    decisao = governanca.nova_decisao("p1", "bloqueio", {"bloqueia": False},
                                      [], [])
    gravada = db.registrar_decisao(decisao)
    assert gravada["tenant_id"] == db.TENANT_PADRAO
    assert banco[0]["input_hash"] == decisao["input_hash"]


def test_listar_regras_filtra_tenant_alheio(monkeypatch):
    banco = [
        {"id": "1", "tenant_id": None, "status": "PUBLISHED",
         "prioridade": 10},                       # plataforma: entra
        {"id": "2", "tenant_id": db.TENANT_PADRAO, "status": "PUBLISHED",
         "prioridade": 20},                       # meu tenant: entra
        {"id": "3", "tenant_id": "outro-tenant", "status": "PUBLISHED",
         "prioridade": 30},                       # alheio: NUNCA
    ]
    cliente = type("C", (), {
        "table": lambda self, nome: _TabelaFake(banco, nome)})()
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "_cliente", lambda: cliente)

    regras = db.listar_regras()
    assert {r["id"] for r in regras} == {"1", "2"}


def test_atualizar_fato_so_permite_transicao_de_status(monkeypatch):
    monkeypatch.setattr(db, "disponivel", lambda: True)
    with pytest.raises(db.ErroBanco, match="não atualizáveis"):
        db.atualizar_fato("f1", valor=999)
