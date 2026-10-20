"""
G4 — seletor: determinístico primeiro, Jev só no ambíguo, sempre como
recomendação, com teto de consultas e de custo. O Jev é um DUBLÊ: nenhuma
chamada paga (pacote, `04_SELETOR_JEV_E_CUSTOS.md`).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from src.precos import cotacoes, seletor
from src.precos import repositorio as repo
from tests.cotacoes_apoio import ligar_banco_falso, linha
from tests.test_cotacoes_g2_servico import CTX, _fonte

ITEM = {"id": "item-1", "descricao": "CANETA ESFEROGRAFICA AZUL",
        "unidade": "UNIDADE", "codigo": None, "tipo_catalogo": None}
COTACAO = {"id": "cot-1", "data_base": "2026-10-16", "filtros": {}}


class _Repo:
    def __init__(self, eventos=None):
        self.eventos = list(eventos or [])

    def listar_eventos(self, _cid, limite=200):
        return list(reversed(self.eventos))

    def registrar_evento(self, cid, tipo, **kw):
        self.eventos.append({"tipo": tipo, **kw})


def _jev(escolha="different_product", custo=0.002, cache=False):
    chamadas = []

    def consultar(cid, iid, rid, repo=None):
        chamadas.append(rid)
        if cache:
            return {"cache_hit": True, "called": False,
                    "response": {"answers": {"price_reference_mismatch":
                                             {"choice": escolha}}}}
        return {"called": True, "explicacao": "Confirme na fonte.",
                "response": {"answers": {"price_reference_mismatch":
                                         {"choice": escolha}},
                             "usage": {"cost": custo}}}
    return consultar, chamadas


def _linhas():
    return [linha("1.50", "candidate", ident="alta", score="0.92"),
            linha("1.60", "candidate", ident="amb1", score="0.55"),
            linha("1.70", "candidate", ident="amb2", score="0.40"),
            linha("1.80", "candidate", ident="baixa", score="0.10"),
            linha("1.90", "candidate", ident="est", score="0.95",
                  natureza="estimado_origem"),
            linha("2.00", "candidate", ident="cx", score="0.90",
                  unidade="CAIXA"),
            linha("9.99", "rejected", ident="humano", score="0.90")]


def test_sem_flag_nenhuma_chamada_e_ambiguo_fica_para_revisao():
    consultar, chamadas = _jev()
    r = _Repo()
    p = seletor.propor(COTACAO, ITEM, _linhas(), r, consultar=consultar,
                       ia_habilitada=False)
    por_id = {a.referencia_id: a for a in p.analises}
    assert chamadas == [] and p.chamadas_ia == 0
    assert por_id["id-alta"].decisao == seletor.COMPARAVEL
    assert por_id["id-amb1"].decisao == seletor.REVISAO
    assert por_id["id-amb1"].origem == "sem_jev"
    assert por_id["id-baixa"].decisao == seletor.INCOMPATIVEL
    assert por_id["id-est"].decisao == seletor.INCOMPATIVEL
    assert "natureza" in por_id["id-est"].motivo
    assert por_id["id-cx"].decisao == seletor.INCOMPATIVEL
    assert "id-humano" not in por_id, "decisão humana não é reanalisada"
    assert r.eventos[-1]["tipo"] == "selecao_sugerida"


def test_jev_so_no_ambiguo_e_so_recomenda():
    consultar, chamadas = _jev("compatible", custo=0.003)
    p = seletor.propor(COTACAO, ITEM, _linhas(), _Repo(), consultar=consultar,
                       ia_habilitada=True)
    assert sorted(chamadas) == ["id-amb1", "id-amb2"]
    assert p.chamadas_ia == 2 and p.custo_total == Decimal("0.006")
    amb = next(a for a in p.analises if a.referencia_id == "id-amb1")
    assert amb.recomendacao == "sugere comparável"
    assert amb.decisao == seletor.REVISAO, "sem calibração, IA não decide"
    assert p.aceite_automatico is False


def test_cache_nao_conta_como_chamada():
    consultar, _ = _jev(cache=True)
    p = seletor.propor(COTACAO, ITEM, _linhas(), _Repo(), consultar=consultar,
                       ia_habilitada=True)
    assert p.chamadas_ia == 0 and p.cache_hits == 2


def test_teto_por_item_e_por_custo_da_cotacao():
    consultar, chamadas = _jev()
    cot = {**COTACAO, "filtros": {"jev": {"max_por_item": 1}}}
    p = seletor.propor(cot, ITEM, _linhas(), _Repo(), consultar=consultar,
                       ia_habilitada=True)
    assert len(chamadas) == 1 and p.bloqueadas_por_orcamento == 1

    consultar, chamadas = _jev()
    gasto = _Repo([{"tipo": "selecao_sugerida",
                    "payload": {"chamadas_ia": 3, "custo_total": "1.00"}}])
    p = seletor.propor(COTACAO, ITEM, _linhas(), gasto, consultar=consultar,
                       ia_habilitada=True)
    assert chamadas == [] and p.bloqueadas_por_orcamento == 2


def test_ia_fora_do_ar_nao_para_nada():
    def explode(*a, **k):
        raise TimeoutError("decisions")

    p = seletor.propor(COTACAO, ITEM, _linhas(), _Repo(), consultar=explode,
                       ia_habilitada=True)
    amb = [a for a in p.analises if a.classe == "ambiguo"]
    assert amb and all(a.decisao == seletor.REVISAO for a in amb)
    assert p.chamadas_ia == 0


def test_aceite_automatico_exige_calibracao_aprovada(tmp_path, monkeypatch):
    assert seletor.aceite_automatico_permitido() is False
    arquivo = tmp_path / "calibracao.json"
    arquivo.write_text(json.dumps({"aprovado_por": "Responsável",
                                   "meta_definida_em": "2026-10-01",
                                   "rotulos_humanos": 50,
                                   "meta_atingida": True}), encoding="utf-8")
    monkeypatch.setattr(seletor, "CALIBRACAO", arquivo)
    assert seletor.aceite_automatico_permitido() is False, "amostra pequena"
    arquivo.write_text(json.dumps({"aprovado_por": "Responsável",
                                   "meta_definida_em": "2026-10-01",
                                   "rotulos_humanos": 400,
                                   "meta_atingida": True}), encoding="utf-8")
    assert seletor.aceite_automatico_permitido() is True


def test_no_fluxo_automatico_a_sugestao_nao_muda_a_cesta(monkeypatch):
    ligar_banco_falso(monkeypatch)
    cotacao = cotacoes.criar_cotacao(CTX, {"nome": "Jev",
                                           "data_base": "2026-10-16"})
    item = cotacoes.salvar_item(CTX, str(cotacao["id"]), {
        "descricao": "PAPEL SULFITE A4 75G", "unidade": "RESMA",
        "quantidade": "10"})
    consultar, chamadas = _jev("different_product")

    def seletor_teste(cot, it, linhas):
        return seletor.propor(cot, it, linhas, repo, consultar=consultar,
                              ia_habilitada=True).para_evento()

    sem = cotacoes.pesquisar_item(CTX, str(cotacao["id"]), str(item["id"]),
                                  modo="automatico", fontes=[_fonte()])
    preco_sem = repo.obter_item(str(item["id"]))["preco_estimado"]
    com = cotacoes.pesquisar_item(CTX, str(cotacao["id"]), str(item["id"]),
                                  modo="automatico", fontes=[_fonte()],
                                  seletor=seletor_teste)
    assert com.sugestao is not None
    assert repo.obter_item(str(item["id"]))["preco_estimado"] == preco_sem
    assert com.consideradas == sem.consideradas
    eventos = [e for e in repo.listar_eventos(str(cotacao["id"]))
               if e["tipo"] == "selecao_sugerida"]
    assert eventos and eventos[0]["payload"]["aceite_automatico"] is False


@pytest.mark.parametrize("ausente", ["raw_hash", "id_externo"])
def test_referencia_sem_evidencia_verificavel_e_bloqueada(ausente):
    l = linha("1.50", "candidate", ident="x", score="0.6")
    l[ausente] = "" if ausente == "id_externo" else "adulterado"
    a = seletor.classificar(ITEM, l, COTACAO)
    assert a.decisao == seletor.INCOMPATIVEL and a.origem == "deterministica"


def test_benchmark_sintetico_sem_falso_positivo_e_sem_ia():
    """Regressão do `scripts/seletor_benchmark.py` (rótulo por construção)."""
    from scripts import seletor_benchmark

    resultado = seletor_benchmark.executar()
    assert resultado["falso_positivo"] == 0
    assert resultado["matriz"]["incompativel_errado"] == 0
    assert resultado["chamadas_ia"] == 0 and resultado["jev"] is None
    assert "SINTÉTICO" in resultado["natureza_do_dataset"]
