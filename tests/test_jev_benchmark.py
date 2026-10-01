from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import jev_benchmark


ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "docs" / "jev" / "dataset_candidatos.json"


def test_dataset_tem_proveniencia_verificavel_e_rotulos_pendentes():
    candidatos = jev_benchmark.carregar_dataset(DATASET)
    assert len(candidatos) == 5
    assert {c["human_label"] for c in candidatos} == {None}


def test_metrica_nao_e_fabricada_sem_rotulo_humano(tmp_path):
    resultados = [{"candidate_id": "wattimeter-0-1", "decision": True,
                   "calls": 1, "input_tokens": 12, "output_tokens": 3,
                   "cost": 0.01, "latency_ms": 7}]
    base = tmp_path / "base.json"
    jev = tmp_path / "jev.json"
    base.write_text(json.dumps(resultados), encoding="utf-8")
    jev.write_text(json.dumps(resultados), encoding="utf-8")
    relatorio = jev_benchmark.executar(DATASET, base, jev, tamanhos=(1,))
    rodada = relatorio["runs"][0]
    assert rodada["human_labels_missing"] == 1
    assert rodada["metrics_available"] is False
    assert rodada["baseline"]["metrics"] is None
    assert rodada["jev"]["metrics"] is None


def test_hash_de_fixture_alterado_reprova_dataset(tmp_path):
    bruto = json.loads(DATASET.read_text(encoding="utf-8"))
    bruto["candidates"][0]["item"]["source_sha256"] = "0" * 64
    arquivo = tmp_path / "dataset.json"
    arquivo.write_text(json.dumps(bruto), encoding="utf-8")
    with pytest.raises(jev_benchmark.ErroBenchmark, match="fixture"):
        jev_benchmark.carregar_dataset(arquivo)


def test_recorte_menor_nao_simula_benchmark_de_210_e_nan_nao_e_custo():
    casos = [{"id": "a", "human_label": True}]
    respostas = {"a": {"decision": True, "cost": float("nan")}}
    resumo = jev_benchmark.resumir(casos, respostas, respostas, 210)
    assert resumo["available_candidates"] == 1
    assert resumo["metrics_available"] is False
    assert resumo["jev"]["cost"] is None


def test_confusao_e_abstencao_ficam_explicitas():
    casos = [{"id": str(i), "human_label": rotulo}
             for i, rotulo in enumerate([True, True, False, False])]
    respostas = {str(i): {"decision": decisao} for i, decisao in enumerate([True, False, True, False])}
    resumo = jev_benchmark.resumir(casos, respostas, respostas, 4)
    assert resumo["jev"]["metrics"] == {
        "precision": 0.5, "recall": 0.5, "false_positive": 1,
        "false_negative": 1, "confusion_matrix": {"tp": 1, "fp": 1, "fn": 1, "tn": 1}}
    respostas["0"]["decision"] = None
    resumo = jev_benchmark.resumir(casos, respostas, respostas, 4)
    assert resumo["metrics_available"] is False
    assert resumo["jev"]["human_review"] == 1
