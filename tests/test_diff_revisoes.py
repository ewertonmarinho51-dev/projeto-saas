"""
Testes da Etapa 2 da correção automática: diff estrutural entre
versões, regras de preservação (escopo, bloqueio, orçamento) e
persistência idempotente do job de revisão.
"""

from src import blocos, db

DOC_V1 = """## 1. OBJETO

Aquisição de material escolar.

## 2. VIGÊNCIA

Doze meses a contar da assinatura.

## 3. VALOR

R$ 100,00 conforme planilha.
"""

DOC_V2_UMA_ALTERACAO = DOC_V1.replace("Doze meses", "Vinte e quatro meses")


def _blocos(texto):
    return blocos.dividir_em_blocos("dfd", texto)


# ---------------------------------------------------------------------------
# diff estrutural
# ---------------------------------------------------------------------------
def test_diff_detecta_somente_o_bloco_alterado():
    diff = blocos.diff_estrutural(_blocos(DOC_V1), _blocos(DOC_V2_UMA_ALTERACAO))
    assert diff["alterados"] == ["dfd/clausula/2/1"]
    assert diff["adicionados"] == [] and diff["removidos"] == []


def test_diff_detecta_bloco_adicionado_e_removido():
    v2 = DOC_V1 + "\n## 4. PRAZO\n\nEntrega em 30 dias.\n"
    diff = blocos.diff_estrutural(_blocos(DOC_V1), _blocos(v2))
    assert diff["adicionados"] == ["dfd/clausula/4/0", "dfd/clausula/4/1"]

    sem_valor = DOC_V1.split("## 3.")[0]
    diff = blocos.diff_estrutural(_blocos(DOC_V1), _blocos(sem_valor))
    assert diff["removidos"] == ["dfd/clausula/3/0", "dfd/clausula/3/1"]


def test_diff_bundle_compara_documento_a_documento():
    snap1 = blocos.snapshot_bundle({"dfd": DOC_V1}, versao=1)
    snap2 = blocos.snapshot_bundle({"dfd": DOC_V2_UMA_ALTERACAO}, versao=2)
    diff = blocos.diff_bundle(snap1, snap2)
    assert diff["de_versao"] == 1 and diff["para_versao"] == 2
    assert diff["documentos"]["dfd"]["alterados"] == ["dfd/clausula/2/1"]


# ---------------------------------------------------------------------------
# regras de preservação (qualquer violação rejeita o patch inteiro)
# ---------------------------------------------------------------------------
def test_alteracao_dentro_do_escopo_passa():
    diff = blocos.diff_estrutural(_blocos(DOC_V1), _blocos(DOC_V2_UMA_ALTERACAO))
    assert blocos.validar_diff(diff, ["dfd/clausula/2/1"], []) == []


def test_alteracao_fora_do_escopo_e_violacao():
    diff = blocos.diff_estrutural(_blocos(DOC_V1), _blocos(DOC_V2_UMA_ALTERACAO))
    violacoes = blocos.validar_diff(diff, ["dfd/clausula/3/1"], [])
    assert any("fora do escopo" in v for v in violacoes)


def test_alteracao_em_caminho_bloqueado_e_violacao():
    diff = blocos.diff_estrutural(_blocos(DOC_V1), _blocos(DOC_V2_UMA_ALTERACAO))
    violacoes = blocos.validar_diff(
        diff, ["dfd/clausula/2/1"], ["dfd/clausula/2/1"])
    assert any("bloqueado" in v for v in violacoes)


def test_orcamento_de_25_por_cento_dos_blocos():
    v2 = (DOC_V1
          .replace("material escolar", "material de expediente")
          .replace("Doze meses", "Dois anos")
          .replace("R$ 100,00", "R$ 200,00"))
    diff = blocos.diff_estrutural(_blocos(DOC_V1), _blocos(v2))
    permitidos = diff["alterados"]
    violacoes = blocos.validar_diff(diff, permitidos, [])  # 3/6 blocos = 50%
    assert any("orçamento" in v for v in violacoes)
    assert blocos.validar_diff(diff, permitidos, [],
                               max_proporcao_blocos=0.6) == []


# ---------------------------------------------------------------------------
# persistência do job de revisão (idempotência — T11/T12)
# ---------------------------------------------------------------------------
class _TabelaFake:
    def __init__(self, banco):
        self.banco = banco
        self._filtro = None
        self._pendente = None

    def insert(self, registro):
        chave = registro.get("idempotency_key", "")
        if chave and any(
            r.get("idempotency_key") == chave for r in self.banco
        ):
            raise RuntimeError("duplicate key value (revisoes_idempotencia)")
        registro = {**registro, "id": f"rev-{len(self.banco) + 1}"}
        self._pendente = ("insert", registro)
        return self

    def select(self, *_):
        self._pendente = ("select", None)
        return self

    def update(self, campos):
        self._pendente = ("update", campos)
        return self

    def eq(self, campo, valor):
        self._filtro = (campo, valor)
        return self

    def order(self, *_, **__):
        return self

    def limit(self, *_):
        return self

    def execute(self):
        acao, dados = self._pendente
        if acao == "insert":
            self.banco.append(dados)
            return type("R", (), {"data": [dados]})
        filtrados = [r for r in self.banco
                     if self._filtro is None
                     or r.get(self._filtro[0]) == self._filtro[1]]
        if acao == "update":
            for r in filtrados:
                r.update(dados)
            return type("R", (), {"data": filtrados})
        return type("R", (), {"data": filtrados})


def _com_banco_fake(monkeypatch):
    banco: list[dict] = []
    cliente = type("C", (), {"table": lambda self, nome: _TabelaFake(banco)})()
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "_cliente", lambda: cliente)
    return banco


def test_criar_revisao_persiste_snapshot_e_relatorio(monkeypatch):
    _com_banco_fake(monkeypatch)
    snap = blocos.snapshot_bundle({"dfd": DOC_V1}, versao=1)
    revisao = db.criar_revisao("proc-1", snap, {"status": "APPROVED"}, "chave-1")
    assert revisao["status"] == "REVIEW_QUEUED"
    assert revisao["bundle_hash"] == snap["hash"]
    assert revisao["snapshots"] == [snap]
    assert revisao["tenant_id"] == db.TENANT_PADRAO


def test_criar_revisao_e_idempotente_pela_chave(monkeypatch):
    banco = _com_banco_fake(monkeypatch)
    snap = blocos.snapshot_bundle({"dfd": DOC_V1}, versao=1)
    r1 = db.criar_revisao("proc-1", snap, {}, "chave-x")
    r2 = db.criar_revisao("proc-1", snap, {}, "chave-x")
    assert r1["id"] == r2["id"]
    assert len(banco) == 1


def test_corrida_na_chave_devolve_o_job_existente(monkeypatch):
    """Duas sessões inserindo ao mesmo tempo: o índice único resolve."""
    banco = _com_banco_fake(monkeypatch)
    snap = blocos.snapshot_bundle({"dfd": DOC_V1}, versao=1)
    r1 = db.criar_revisao("proc-1", snap, {}, "chave-y")

    # simula a corrida: a 2ª sessão não vê o job no select inicial, o
    # insert bate no índice único e o retry do select encontra o job
    chamadas = []

    def obter_com_corrida(chave):
        chamadas.append(chave)
        return None if len(chamadas) == 1 else r1

    monkeypatch.setattr(db, "obter_revisao_por_chave", obter_com_corrida)
    r2 = db.criar_revisao("proc-1", snap, {}, "chave-y")
    assert r2["id"] == r1["id"]
    assert len(banco) == 1 and len(chamadas) == 2


def test_atualizar_revisao_carimba_atualizado_em(monkeypatch):
    _com_banco_fake(monkeypatch)
    snap = blocos.snapshot_bundle({"dfd": DOC_V1}, versao=1)
    revisao = db.criar_revisao("proc-1", snap, {}, "")
    alterada = db.atualizar_revisao(revisao["id"], status="REVIEWING", ciclo=1)
    assert alterada["status"] == "REVIEWING" and alterada["ciclo"] == 1
    assert alterada["atualizado_em"]
