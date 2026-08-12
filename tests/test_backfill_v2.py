"""
Backfill do índice vetorial V2 (`scripts/reindexar_embeddings_v2.py`).

Cobre o que não pode falhar numa reindexação de 4.539 chunks em base de
produção: terminar diante de provedor indisponível (sem laço infinito),
respeitar o limite pedido, nunca trocar de provedor e nunca expor a
credencial.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "reindexar_embeddings_v2", RAIZ / "scripts" / "reindexar_embeddings_v2.py")
backfill = importlib.util.module_from_spec(_spec)
sys.modules["reindexar_embeddings_v2"] = backfill
_spec.loader.exec_module(backfill)


# ---------------------------------------------------------------------------
# Dublês: banco em memória e provedor de embeddings controlável
# ---------------------------------------------------------------------------
class BancoFalso:
    """Mínimo do contrato supabase-py usado pelo script."""

    def __init__(self, quantidade: int):
        self.chunks = [{"id": i, "documento_id": "doc-1", "ordem": i,
                        "conteudo": f"trecho {i}", "embedding_v2": None,
                        "embedding_status": "pendente"}
                       for i in range(quantidade)]
        self.updates: list[dict] = []

    # -- consulta -----------------------------------------------------
    def table(self, nome):
        assert nome == "chunks_referencia"
        return _Consulta(self)

    def pendentes(self):
        return [c for c in self.chunks if c["embedding_v2"] is None]


class _Consulta:
    def __init__(self, banco):
        self.banco = banco
        self._limite = None
        self._contar = False
        self._update = None
        self._id = None

    def select(self, *a, **kw):
        self._contar = kw.get("count") == "exact"
        return self

    def is_(self, coluna, valor):
        return self

    def order(self, *a, **kw):
        return self

    def limit(self, n):
        self._limite = n
        return self

    def update(self, dados):
        self._update = dados
        return self

    def eq(self, coluna, valor):
        self._id = valor
        return self

    def execute(self):
        if self._update is not None:
            alvo = next(c for c in self.banco.chunks if c["id"] == self._id)
            alvo.update(self._update)
            self.banco.updates.append({"id": self._id, **self._update})
            return _Resposta([], None)
        pendentes = self.banco.pendentes()
        if self._contar:
            return _Resposta([], len(pendentes))
        return _Resposta(pendentes[:self._limite], None)


class _Resposta:
    def __init__(self, data, count):
        self.data = data
        self.count = count


class ProvedorFalso:
    def __init__(self, falhar_sempre=False):
        self.falhar_sempre = falhar_sempre
        self.chamadas = 0
        self.embeddings = self

    def create(self, model, input, dimensions):  # noqa: A002
        self.chamadas += 1
        if self.falhar_sempre:
            raise RuntimeError("openai indisponível")
        return type("R", (), {
            "data": [type("D", (), {"embedding": [0.01] * dimensions})()
                     for _ in input]})()


# ---------------------------------------------------------------------------
# Indisponibilidade persistente do provedor
# ---------------------------------------------------------------------------
def test_falha_persistente_encerra_sem_laco_infinito(capsys):
    banco = BancoFalso(300)
    provedor = ProvedorFalso(falhar_sempre=True)
    esperas: list[float] = []

    with pytest.raises(backfill.BackfillInterrompido):
        backfill.executar(lote=100, maximo=None, simular=False, sb=banco,
                          openai_=provedor, dormir=esperas.append)

    # tentou o número previsto de vezes — e parou
    assert provedor.chamadas == backfill.MAX_TENTATIVAS_LOTE
    assert esperas == [2, 4]                     # backoff entre tentativas
    # o lote ficou marcado como falha, mas continua retomável
    assert all(u["embedding_status"] == "falha" for u in banco.updates)
    assert len(banco.pendentes()) == 300         # nada foi vetorizado
    assert "[interrompido]" in capsys.readouterr().out


def test_falha_persistente_encerra_com_codigo_de_erro(monkeypatch):
    banco = BancoFalso(10)
    provedor = ProvedorFalso(falhar_sempre=True)
    monkeypatch.setattr(backfill, "cliente_supabase", lambda: banco)
    monkeypatch.setattr(backfill, "cliente_openai", lambda: provedor)
    monkeypatch.setattr(backfill.time, "sleep", lambda s: None)
    monkeypatch.setattr(sys, "argv", ["reindexar", "--lote", "5"])

    with pytest.raises(SystemExit) as saida:
        backfill.main()
    assert saida.value.code != 0
    assert "provedor indisponível" in str(saida.value)


def test_provedor_nao_e_trocado_em_caso_de_falha():
    """Não há caminho para outro provedor: o módulo só conhece a OpenAI."""
    fonte = (RAIZ / "scripts" / "reindexar_embeddings_v2.py").read_text(
        encoding="utf-8")
    for proibido in ("genai", "gemini", "GOOGLE_API_KEY"):
        assert proibido not in fonte


def test_falha_intermitente_se_recupera_e_conclui():
    banco = BancoFalso(5)
    provedor = ProvedorFalso()
    original = provedor.create

    def instavel(model, input, dimensions):  # noqa: A002
        if provedor.chamadas == 0:
            provedor.chamadas += 1
            raise RuntimeError("timeout")
        return original(model=model, input=input, dimensions=dimensions)

    provedor.create = instavel
    processados = backfill.executar(lote=5, maximo=None, simular=False,
                                    sb=banco, openai_=provedor,
                                    dormir=lambda s: None)
    assert processados == 5
    assert banco.pendentes() == []


# ---------------------------------------------------------------------------
# Limite × lote
# ---------------------------------------------------------------------------
def test_limite_menor_que_o_lote_e_respeitado():
    banco = BancoFalso(300)
    provedor = ProvedorFalso()
    processados = backfill.executar(lote=100, maximo=50, simular=False,
                                    sb=banco, openai_=provedor)
    assert processados == 50
    assert len(banco.pendentes()) == 250
    assert provedor.chamadas == 1            # um único lote de 50


def test_limite_multiplo_de_lotes():
    banco = BancoFalso(300)
    provedor = ProvedorFalso()
    assert backfill.executar(lote=40, maximo=90, simular=False, sb=banco,
                             openai_=provedor) == 90
    assert len(banco.pendentes()) == 210


def test_sem_limite_processa_tudo_e_e_idempotente():
    banco = BancoFalso(120)
    provedor = ProvedorFalso()
    assert backfill.executar(lote=50, maximo=None, simular=False, sb=banco,
                             openai_=provedor) == 120
    # nova execução não reprocessa nada (retomável e idempotente)
    assert backfill.executar(lote=50, maximo=None, simular=False, sb=banco,
                             openai_=ProvedorFalso()) == 0


def test_gravacao_registra_proveniencia_completa():
    banco = BancoFalso(2)
    backfill.executar(lote=2, maximo=None, simular=False, sb=banco,
                      openai_=ProvedorFalso())
    for update in banco.updates:
        assert update["embedding_provider"] == "openai"
        assert update["embedding_model"] == "text-embedding-3-small"
        assert update["embedding_dimensions"] == 768
        assert update["embedding_version"] == "v2"
        assert update["embedding_status"] == "ok"
        assert update["embedding_generated_at"]
        assert len(update["embedding_v2"]) == 768


def test_simular_nao_grava_nada():
    banco = BancoFalso(10)
    assert backfill.executar(lote=5, maximo=None, simular=True,
                             sb=banco) == 0
    assert banco.updates == []
    assert len(banco.pendentes()) == 10


def test_dimensao_divergente_do_provedor_e_recusada():
    class Errado(ProvedorFalso):
        def create(self, model, input, dimensions):  # noqa: A002
            self.chamadas += 1
            return type("R", (), {
                "data": [type("D", (), {"embedding": [0.1] * 1536})()
                         for _ in input]})()

    with pytest.raises(backfill.BackfillInterrompido):
        backfill.executar(lote=2, maximo=None, simular=False,
                          sb=BancoFalso(2), openai_=Errado(),
                          dormir=lambda s: None)


# ---------------------------------------------------------------------------
# Credencial: resolvida, nunca exibida
# ---------------------------------------------------------------------------
def test_credencial_resolvida_na_ordem_ambiente_secrets_banco(monkeypatch):
    monkeypatch.setattr(backfill, "_dos_secrets", lambda nome: "do-secrets")
    monkeypatch.setattr(backfill, "_do_banco", lambda nome: "do-banco")

    monkeypatch.setenv("OPENAI_API_KEY", "do-ambiente")
    assert backfill.resolver_credencial("OPENAI_API_KEY") == "do-ambiente"

    monkeypatch.delenv("OPENAI_API_KEY")
    assert backfill.resolver_credencial("OPENAI_API_KEY") == "do-secrets"

    monkeypatch.setattr(backfill, "_dos_secrets", lambda nome: "")
    assert backfill.resolver_credencial("OPENAI_API_KEY") == "do-banco"


def test_credencial_do_banco_usa_o_contrato_da_aplicacao(monkeypatch):
    from src import db

    consultas = []
    monkeypatch.setattr(db, "obter_config",
                        lambda chave: consultas.append(chave) or "k-do-banco")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(backfill, "_dos_secrets", lambda nome: "")
    assert backfill.resolver_credencial("OPENAI_API_KEY") == "k-do-banco"
    assert consultas == ["OPENAI_API_KEY"]      # mesma chave do app


def test_relatorio_de_credenciais_nao_expoe_o_valor(monkeypatch, capsys):
    segredo = "sk-proj-SEGREDO-QUE-NAO-PODE-VAZAR-1234567890"
    monkeypatch.setenv("OPENAI_API_KEY", segredo)
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "chave-supabase")
    monkeypatch.setattr(sys, "argv", ["reindexar", "--credenciais"])

    backfill.main()
    saida = capsys.readouterr().out

    assert "credencial do provedor V2 disponível: sim" in saida
    # nem o valor, nem prefixo, nem tamanho, nem hash
    assert segredo not in saida
    assert "sk-" not in saida
    assert str(len(segredo)) not in saida
    import hashlib

    assert hashlib.sha256(segredo.encode()).hexdigest()[:8] not in saida


def test_ausencia_de_credencial_e_reportada_sem_detalhe(monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(backfill, "_dos_secrets", lambda nome: "")
    monkeypatch.setattr(backfill, "_do_banco", lambda nome: "")
    monkeypatch.setattr(sys, "argv", ["reindexar", "--credenciais"])
    backfill.main()
    assert "credencial do provedor V2 disponível: não" in capsys.readouterr().out


def test_aborta_sem_credencial_sem_alterar_nada(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setattr(backfill, "_dos_secrets", lambda nome: "")
    with pytest.raises(SystemExit, match="ABORTADO"):
        backfill.cliente_supabase()


def test_credenciais_de_banco_nao_dependem_do_banco(monkeypatch):
    """SUPABASE_URL/KEY não podem ser buscadas no próprio banco."""
    monkeypatch.setattr(backfill, "_do_banco",
                        lambda nome: pytest.fail("consultou o banco"))
    monkeypatch.setattr(backfill, "_dos_secrets", lambda nome: "")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        backfill.cliente_supabase()
