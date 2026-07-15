"""
Testes da Fase 1 do Centro de Governança (pacote V6): contratos de
artefato por tipo, fluxo de estados com versão publicada imutável
(T01), edição criando nova versão, papéis e escopos (T09/servidor sem
acesso), flags default OFF (T24) e persistência com guardas.
"""

import types

import pytest

from src import auth, db, governanca

# ---------------------------------------------------------------------------
# estados e imutabilidade (T01)
# ---------------------------------------------------------------------------
def test_fluxo_de_estados_do_pacote():
    ok = governanca.transicao_artefato_valida
    assert ok("DRAFT", "UNDER_REVIEW")
    assert ok("UNDER_REVIEW", "APPROVED_FOR_SIMULATION")
    assert ok("APPROVED_FOR_SIMULATION", "SHADOW")
    assert ok("SHADOW", "SCHEDULED") and ok("SHADOW", "PUBLISHED")
    assert ok("SCHEDULED", "PUBLISHED")
    assert ok("PUBLISHED", "SUPERSEDED") and ok("PUBLISHED", "REVOKED")
    assert not ok("DRAFT", "PUBLISHED")       # sem atalho para publicar
    assert not ok("PUBLISHED", "DRAFT")       # publicada nunca volta
    assert not ok("REVOKED", "PUBLISHED")


def test_versao_publicada_imutavel_editar_deriva_nova():
    versao = governanca.nova_versao_artefato(
        "clausula", "clausula.garantia", _payload_clausula(),
        versao=2, status="PUBLISHED")
    assert not governanca.versao_artefato_editavel(versao)
    nova = governanca.derivar_versao_artefato(versao)
    assert nova["versao"] == 3 and nova["status"] == "DRAFT"
    assert nova["hash"] != versao["hash"]
    assert versao["status"] == "PUBLISHED"  # original intocada


# ---------------------------------------------------------------------------
# payloads por tipo
# ---------------------------------------------------------------------------
def _payload_clausula(**extras):
    return {"titulo": "DA GARANTIA CONTRATUAL",
            "comportamento": "FIXED_PARAMETERIZED",
            "blocos": ["A garantia será de {{percentual}}% do valor."],
            "parametros_permitidos": ["percentual"],
            "parametros_obrigatorios": ["percentual"],
            "base_legal": ["art. 96, Lei 14.133/2021"], **extras}


def test_clausula_valida_e_invalida():
    versao = governanca.nova_versao_artefato(
        "clausula", "clausula.garantia", _payload_clausula())
    assert versao["hash"] and versao["status"] == "DRAFT"

    with pytest.raises(governanca.ErroContrato, match="comportamento"):
        governanca.nova_versao_artefato(
            "clausula", "clausula.x",
            _payload_clausula(comportamento="LIVRE"))
    with pytest.raises(governanca.ErroContrato, match="parametros_perm"):
        governanca.nova_versao_artefato(
            "clausula", "clausula.x",
            _payload_clausula(parametros_permitidos=[]))
    with pytest.raises(governanca.ErroContrato,
                       match="fora dos permitidos"):
        governanca.nova_versao_artefato(
            "clausula", "clausula.x",
            _payload_clausula(parametros_obrigatorios=["prazo"]))


def test_politica_reusa_o_validador_de_condicoes_do_v5():
    payload = {
        "condicao": {"op": "ALL", "children": [
            {"field": "procedimento.srp", "operator": "EQ", "value": True},
        ]},
        "acoes": [{"type": "INCLUIR_CLAUSULA",
                   "target": "clausula.me-epp"}],
        "prioridade": 100,
    }
    versao = governanca.nova_versao_artefato(
        "politica", "politica.me-epp", payload)
    assert versao["tipo_artefato"] == "politica"

    with pytest.raises(governanca.ErroContrato, match="operador"):
        governanca.nova_versao_artefato(
            "politica", "politica.x",
            {**payload, "condicao": {"op": "XOR", "children": [{}]}})


def test_familia_exige_criterios_e_documentos():
    payload = {"nome": "TR para serviços contínuos",
               "documentos_suportados": ["tr"],
               "criterios": {"field": "procedimento.execucao_continuada",
                             "operator": "EQ", "value": True}}
    versao = governanca.nova_versao_artefato(
        "familia", "familia.tr-servicos-continuos", payload)
    assert versao["payload"]["nome"].startswith("TR")

    with pytest.raises(governanca.ErroContrato, match="critérios"):
        governanca.nova_versao_artefato(
            "familia", "familia.x",
            {"nome": "X", "documentos_suportados": ["tr"]})


def test_template_por_blocos_com_ids_unicos():
    payload = {"blocos": [
        {"id": "b1", "tipo": "cabecalho"},
        {"id": "b2", "tipo": "clausula_catalogo",
         "clausula": "clausula.garantia"},
        {"id": "b3", "tipo": "assinatura"},
    ]}
    versao = governanca.nova_versao_artefato(
        "template", "template.tr-base", payload)
    assert len(versao["payload"]["blocos"]) == 3

    with pytest.raises(governanca.ErroContrato, match="duplicado"):
        governanca.nova_versao_artefato(
            "template", "template.x",
            {"blocos": [{"id": "b1", "tipo": "titulo"},
                        {"id": "b1", "tipo": "rodape"}]})
    with pytest.raises(governanca.ErroContrato, match="sem cláusula"):
        governanca.nova_versao_artefato(
            "template", "template.x",
            {"blocos": [{"id": "b1", "tipo": "clausula_catalogo"}]})


# ---------------------------------------------------------------------------
# papéis e escopos (T09; servidor sem acesso)
# ---------------------------------------------------------------------------
def _com_usuario(monkeypatch, usuario):
    monkeypatch.setattr(auth, "modo_aberto", lambda: False)
    monkeypatch.setattr(auth, "usuario_logado", lambda: usuario)


def test_servidor_comum_nunca_acessa_governanca(monkeypatch):
    _com_usuario(monkeypatch, {"papel": "usuario"})
    assert auth.papel_governanca() is None
    assert not auth.acessa_centro_governanca()
    assert not auth.pode_criar_governanca()
    assert not auth.pode_publicar_governanca()


def test_admin_do_app_opera_como_admin_municipal(monkeypatch):
    _com_usuario(monkeypatch, {"papel": "admin"})
    assert auth.papel_governanca() == "admin_municipal"
    assert auth.pode_criar_governanca()
    assert not auth.governa_plataforma()  # plataforma é só global


def test_papeis_segregados(monkeypatch):
    _com_usuario(monkeypatch, {"papel": "usuario",
                               "papel_governanca": "revisor_juridico"})
    assert auth.pode_revisar_governanca()
    assert not auth.pode_criar_governanca()
    assert not auth.pode_publicar_governanca()

    _com_usuario(monkeypatch, {"papel": "usuario",
                               "papel_governanca": "publicador"})
    assert auth.pode_publicar_governanca()
    assert not auth.pode_criar_governanca()

    _com_usuario(monkeypatch, {"papel": "usuario",
                               "papel_governanca": "auditor"})
    assert auth.acessa_centro_governanca()
    assert auth.somente_auditoria()
    assert not auth.pode_publicar_governanca()

    _com_usuario(monkeypatch, {"papel": "usuario",
                               "papel_governanca": "proprietario"})
    assert auth.governa_plataforma()


# ---------------------------------------------------------------------------
# flags V6 default OFF (T24)
# ---------------------------------------------------------------------------
def test_todas_as_flags_v6_nascem_desligadas(monkeypatch):
    monkeypatch.setattr(db, "obter_config", lambda chave: "")
    assert len(governanca.FLAGS_V6) == 12
    for flag in governanca.FLAGS_V6:
        assert db.flag_ativa(flag) is False, flag


# ---------------------------------------------------------------------------
# persistência: versão publicada protegida, trilha append-only
# ---------------------------------------------------------------------------
class _TabelaFake:
    def __init__(self, banco, nome, permitir_update=True):
        self.banco, self.nome = banco, nome
        self.permitir_update = permitir_update
        self._acao, self._dados, self._filtros = "select", None, []

    def insert(self, dados):
        self._acao, self._dados = "insert", dados
        return self

    def update(self, dados):
        if not self.permitir_update:
            raise AssertionError(f"UPDATE proibido em {self.nome}")
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
            registro = {**self._dados, "id": f"{self.nome}-{len(self.banco)}"}
            self.banco.append(registro)
            return types.SimpleNamespace(data=[registro])
        filtrados = [r for r in self.banco if all(
            r.get(c) == v for c, v in self._filtros)]
        if self._acao == "update":
            for r in filtrados:
                r.update(self._dados)
            return types.SimpleNamespace(data=filtrados)
        return types.SimpleNamespace(data=filtrados)


def _banco_fake(monkeypatch, permitir_update_em=("governanca_versoes",)):
    tabelas: dict[str, list] = {}

    def table(_self, nome):
        return _TabelaFake(tabelas.setdefault(nome, []), nome,
                           permitir_update=nome in permitir_update_em)

    cliente = types.SimpleNamespace(table=types.MethodType(table, object()))
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "_cliente", lambda: cliente)
    return tabelas


def test_versao_publicada_nao_aceita_edicao_de_payload(monkeypatch):
    tabelas = _banco_fake(monkeypatch)
    artefato = db.obter_ou_criar_artefato("clausula", "clausula.garantia")
    versao = governanca.nova_versao_artefato(
        "clausula", "clausula.garantia", _payload_clausula())
    gravada = db.criar_versao_governanca(artefato["id"], versao)

    db.atualizar_versao_governanca(gravada["id"], status="UNDER_REVIEW")
    db.atualizar_versao_governanca(gravada["id"],
                                   status="APPROVED_FOR_SIMULATION")
    db.atualizar_versao_governanca(gravada["id"], status="SHADOW")
    db.atualizar_versao_governanca(gravada["id"], status="PUBLISHED")
    with pytest.raises(db.ErroBanco, match="imutável"):
        db.atualizar_versao_governanca(
            gravada["id"], payload={"titulo": "hackeado"})
    # transição de estado continua permitida (ex.: revogar)
    db.atualizar_versao_governanca(gravada["id"], status="REVOKED")
    assert tabelas["governanca_versoes"][0]["status"] == "REVOKED"


def test_obter_ou_criar_artefato_e_idempotente(monkeypatch):
    tabelas = _banco_fake(monkeypatch)
    a1 = db.obter_ou_criar_artefato("politica", "politica.me-epp")
    a2 = db.obter_ou_criar_artefato("politica", "politica.me-epp")
    assert a1["id"] == a2["id"]
    assert len(tabelas["governanca_artefatos"]) == 1
    assert a1["tenant_id"] == db.TENANT_PADRAO

    plataforma = db.obter_ou_criar_artefato(
        "politica", "politica.me-epp", plataforma=True)
    assert plataforma["tenant_id"] is None
    assert plataforma["id"] != a1["id"]  # escopos distintos coexistem


def test_trilha_de_eventos_e_append_only(monkeypatch):
    tabelas = _banco_fake(monkeypatch, permitir_update_em=())
    db.registrar_evento_governanca(
        "versao_publicada", "governanca_versoes", None,
        {"chave": "clausula.garantia", "versao": 2})
    evento = tabelas["governanca_eventos"][0]
    assert evento["tipo_evento"] == "versao_publicada"
    assert evento["tenant_id"] == db.TENANT_PADRAO
    # a tabela fake explode em UPDATE — e a 0010 não tem policy de update