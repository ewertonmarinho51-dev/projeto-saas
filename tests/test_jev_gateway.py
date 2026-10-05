from __future__ import annotations

import types

import pytest

from src import ai_gateway, db, governanca, llm
from src.precos import decisoes, jev, repositorio
from src.precos.modelo import hash_do_bruto


MODEL = "typesafe/jev-1.13"


def contexto():
    bruto = {"source": "official"}
    pesquisa = {"id": "p-1", "secretaria_id": "s-1", "processo_id": "proc-1", "data_base": "2026-10-01"}
    item = {"id": "i-1", "descricao": "Caneta esferográfica azul", "unidade": "UN", "codigo": "1", "tipo_catalogo": "CATMAT"}
    ref = {"id": "r-1", "id_externo": "ext-1", "fonte_id": "pncp", "fonte_tipo": "sistema_oficial",
           "bruto": bruto, "raw_hash": hash_do_bruto(bruto), "descricao_original": "Caneta azul",
           "unidade_normalizada": "UN", "valor_unitario_original": "1.20", "natureza_valor": "praticado",
           "data_compra": "2026-09-02", "codigo_catalogo": "1", "tipo_catalogo": "CATMAT"}
    return pesquisa, item, ref


def resultado():
    return jev.Resultado({}, MODEL, {"input_tokens": 7, "output_tokens": 2, "cost": 0.003},
                         request_id="req-1", provider="openrouter", tentativas=1)


def preparar_gateway(monkeypatch):
    dados = contexto()
    registros, chamadas = [], []
    monkeypatch.setattr(db, "flag_ativa", lambda n: n == governanca.FLAG_JEV_PRECOS)
    monkeypatch.setattr(db, "tenant_atual", lambda: "tenant-1")
    monkeypatch.setattr(repositorio, "contexto_decisao", lambda *ids: dados)
    monkeypatch.setattr(repositorio, "listar_referencias", lambda _: [dados[2]])
    monkeypatch.setattr(llm, "obter_openrouter_key", lambda: "test-key")
    monkeypatch.setattr(llm, "registrar_geracao", lambda *a, **k: registros.append((a, k)))
    monkeypatch.setattr(ai_gateway, "configuracao_decisao", lambda: {
        "model": MODEL, "timeout": 11, "max_retries": 2, "concurrency": 1, "failure_mode": "HUMAN_REVIEW"})
    monkeypatch.setattr(jev, "decidir", lambda **kwargs: chamadas.append(kwargs) or resultado())
    return dados, registros, chamadas


def test_gateway_reautoriza_estado_fresco_e_registra_uma_telemetria_com_custo(monkeypatch):
    dados, registros, chamadas = preparar_gateway(monkeypatch)
    state = decisoes.state_referencia(dados[1], dados[2])
    contexto_chamada = {"pesquisa_id": "p-1", "item_id": "i-1", "referencia_id": "r-1",
                        "raw_hash": dados[2]["raw_hash"], "state_hash": hash_do_bruto(state)}
    retorno = ai_gateway.decision(state=state, questions=decisoes.PERGUNTAS, contexto=contexto_chamada)
    assert retorno.model == MODEL
    assert len(chamadas) == 1
    assert chamadas[0]["model"] == MODEL and chamadas[0]["timeout"] == 11 and chamadas[0]["max_retries"] == 2
    assert len(registros) == 1
    args, kwargs = registros[0]
    assert args[:4] == ("price_research_decision", "openrouter", args[2], "ok")
    meta = kwargs["decisao"]
    assert meta["cost"] == 0.003
    assert meta["finalidades"] == list(decisoes.PERGUNTAS)
    assert meta["model_requested"] == MODEL
    assert meta["cache_hit"] is False


def test_gateway_recusa_flag_ou_hash_ou_state_antigo_antes_da_chamada(monkeypatch):
    dados, registros, chamadas = preparar_gateway(monkeypatch)
    state = decisoes.state_referencia(dados[1], dados[2])
    base = {"pesquisa_id": "p-1", "item_id": "i-1", "referencia_id": "r-1",
            "raw_hash": dados[2]["raw_hash"], "state_hash": hash_do_bruto(state)}
    monkeypatch.setattr(db, "flag_ativa", lambda _: False)
    with pytest.raises(jev.ErroDecisao, match="flag_desligada"):
        ai_gateway.decision(state=state, questions=decisoes.PERGUNTAS, contexto=base)
    assert chamadas == registros == []

    monkeypatch.setattr(db, "flag_ativa", lambda _: True)
    stale = base | {"raw_hash": "old"}
    with pytest.raises(jev.ErroDecisao, match="referencia_desatualizada"):
        ai_gateway.decision(state=state, questions=decisoes.PERGUNTAS, contexto=stale)
    with pytest.raises(jev.ErroDecisao, match="estado_ou_perguntas_desatualizados"):
        ai_gateway.decision(state={"old": True}, questions=decisoes.PERGUNTAS, contexto=base)
    assert chamadas == registros == []


def test_configuracao_fixa_modelo_e_rejeita_variaveis_fora_do_contrato(monkeypatch):
    monkeypatch.setenv("JEV_MODEL", "latest")
    with pytest.raises(ValueError, match="homologável"):
        ai_gateway.configuracao_decisao()
    monkeypatch.setenv("JEV_MODEL", MODEL)
    monkeypatch.setenv("JEV_CONCURRENCY", "0")
    with pytest.raises(ValueError, match="configuração"):
        ai_gateway.configuracao_decisao()


class Query:
    def __init__(self, rows):
        self.rows, self.filters = rows, []

    def select(self, *_): return self
    def eq(self, field, value): self.filters.append((field, value)); return self
    def limit(self, *_): return self
    def execute(self): return types.SimpleNamespace(data=self.rows)


def test_contexto_decisao_filtra_tenant_e_vinculos_em_todas_as_tabelas(monkeypatch):
    queries = []
    rows = [[{"id": "p"}], [{"id": "i"}], [{"id": "r"}]]

    class Client:
        def table(self, name):
            query = Query(rows[len(queries)])
            queries.append((name, query))
            return query

    monkeypatch.setattr(repositorio.db, "tenant_atual", lambda: "tenant-A")
    monkeypatch.setattr(repositorio, "_cliente", lambda: Client())
    assert repositorio.contexto_decisao("p", "i", "r") == ({"id": "p"}, {"id": "i"}, {"id": "r"})
    assert queries[0][1].filters == [("id", "p"), ("tenant_id", "tenant-A")]
    assert queries[1][1].filters == [("id", "i"), ("pesquisa_id", "p"), ("tenant_id", "tenant-A")]
    assert queries[2][1].filters == [("id", "r"), ("item_id", "i"), ("tenant_id", "tenant-A")]


def test_contexto_decisao_ausente_nao_devolve_link_parcial(monkeypatch):
    monkeypatch.setattr(repositorio.db, "tenant_atual", lambda: "tenant-A")
    monkeypatch.setattr(repositorio, "_cliente", lambda: types.SimpleNamespace(
        table=lambda _: Query([])))
    with pytest.raises(repositorio.SemSessao, match="indisponível"):
        repositorio.contexto_decisao("p", "i", "r")
