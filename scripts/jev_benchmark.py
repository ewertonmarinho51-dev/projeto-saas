"""Benchmark offline e auditável da triagem Jev.

Este programa nunca chama a Decisions API. Ele compara artefatos já
gravados do baseline e do Jev contra pares do dataset. Métricas e qualquer
calibração só são emitidas quando *todos* os pares do recorte possuem rótulo
humano. Assim, uma resposta do modelo não vira uma "verdade" por acidente.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

TAMANHOS_PADRAO = (1, 10, 50, 210)


class ErroBenchmark(ValueError):
    """Erro de artefato, sem tentar completar dados ausentes."""


def _hash_canonico(valor: Any) -> str:
    bruto = json.dumps(valor, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(bruto).hexdigest()


def _ler_json(caminho: Path) -> Any:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ErroBenchmark(f"artefato_json_invalido:{caminho}") from exc


def carregar_dataset(caminho: str | Path, *, verificar_proveniencia: bool = True) -> list[dict]:
    """Lê candidatos e confere o hash de cada registro de fixture, se pedido."""
    arquivo = Path(caminho)
    bruto = _ler_json(arquivo)
    candidatos = bruto.get("candidates") if isinstance(bruto, dict) else None
    if not isinstance(candidatos, list) or not candidatos:
        raise ErroBenchmark("dataset_sem_candidatos")
    ids: set[str] = set()
    for candidato in candidatos:
        if not isinstance(candidato, dict):
            raise ErroBenchmark("candidato_invalido")
        ident = candidato.get("id")
        if not isinstance(ident, str) or not ident or ident in ids:
            raise ErroBenchmark("id_de_candidato_invalido")
        ids.add(ident)
        if candidato.get("human_label") is not None and type(candidato.get("human_label")) is not bool:
            raise ErroBenchmark("rotulo_humano_invalido")
        if verificar_proveniencia:
            _verificar_lado(arquivo.parent, candidato.get("item"))
            _verificar_lado(arquivo.parent, candidato.get("reference"))
    return candidatos


def _verificar_lado(base: Path, lado: Any) -> None:
    if not isinstance(lado, dict):
        raise ErroBenchmark("proveniencia_ausente")
    origem = lado.get("source_file")
    indice = lado.get("record_index")
    esperado = lado.get("source_sha256")
    raw_hash = lado.get("raw_hash")
    if not isinstance(origem, str) or type(indice) is not int or indice < 0 or not all(
            isinstance(x, str) and x for x in (esperado, raw_hash)):
        raise ErroBenchmark("proveniencia_invalida")
    caminho = (base / origem).resolve()
    try:
        conteudo = caminho.read_bytes()
        fonte = json.loads(conteudo.decode("utf-8"))
        registros = fonte["resultado"]
        registro = registros[indice]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise ErroBenchmark("fixture_de_proveniencia_inacessivel") from exc
    if hashlib.sha256(conteudo).hexdigest() != esperado:
        raise ErroBenchmark("hash_da_fixture_diverge")
    if _hash_canonico(registro) != raw_hash:
        raise ErroBenchmark("raw_hash_do_registro_diverge")


def carregar_resultados(caminho: str | Path) -> dict[str, dict]:
    """Aceita JSON array, objeto com ``results`` ou JSONL de respostas gravadas."""
    arquivo = Path(caminho)
    texto = arquivo.read_text(encoding="utf-8")
    try:
        bruto = json.loads(texto)
        linhas = bruto.get("results") if isinstance(bruto, dict) else bruto
    except json.JSONDecodeError:
        try:
            linhas = [json.loads(linha) for linha in texto.splitlines() if linha.strip()]
        except json.JSONDecodeError as exc:
            raise ErroBenchmark(f"resultado_json_invalido:{arquivo}") from exc
    if not isinstance(linhas, list):
        raise ErroBenchmark("resultados_invalidos")
    saida: dict[str, dict] = {}
    for linha in linhas:
        if not isinstance(linha, dict) or not isinstance(linha.get("candidate_id"), str):
            raise ErroBenchmark("resultado_sem_candidate_id")
        ident = linha["candidate_id"]
        if ident in saida:
            raise ErroBenchmark("resultado_duplicado")
        decisao = linha.get("decision")
        if decisao is not None and type(decisao) is not bool:
            raise ErroBenchmark("decisao_invalida")
        saida[ident] = linha
    return saida


def _soma_exata(linhas: list[dict], campo: str) -> int | float | None:
    valores = [linha.get(campo) for linha in linhas]
    if not valores or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in valores):
        return None
    return sum(valores)


def _metricas(rotulos: list[bool | None], resultados: list[dict]) -> dict | None:
    if any(rotulo is None for rotulo in rotulos):
        return None
    decisoes = [r.get("decision") for r in resultados]
    if any(type(d) is not bool for d in decisoes):
        return None
    tp = sum(rotulo and decisao for rotulo, decisao in zip(rotulos, decisoes))
    fp = sum(not rotulo and decisao for rotulo, decisao in zip(rotulos, decisoes))
    fn = sum(rotulo and not decisao for rotulo, decisao in zip(rotulos, decisoes))
    tn = sum(not rotulo and not decisao for rotulo, decisao in zip(rotulos, decisoes))
    return {
        "precision": None if tp + fp == 0 else tp / (tp + fp),
        "recall": None if tp + fn == 0 else tp / (tp + fn),
        "false_positive": fp,
        "false_negative": fn,
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }


def resumir(candidatos: list[dict], baseline: dict[str, dict], jev: dict[str, dict], tamanho: int) -> dict:
    recorte = candidatos[:min(tamanho, len(candidatos))]
    ids = [c["id"] for c in recorte]
    base = [baseline[i] for i in ids if i in baseline]
    novo = [jev[i] for i in ids if i in jev]
    rotulos = [c["human_label"] for c in recorte]
    resumo_base = _resumo_pipeline(base, rotulos[:len(base)])
    resumo_jev = _resumo_pipeline(novo, rotulos[:len(novo)])
    completo = (len(recorte) == tamanho and not any(r is None for r in rotulos)
                and len(base) == len(recorte) and len(novo) == len(recorte))
    # Uma métrica sobre subconjunto silencioso esconde exatamente os casos
    # sem resposta. Só há precision/recall quando o recorte inteiro existe.
    if not completo:
        resumo_base["metrics"] = None
        resumo_jev["metrics"] = None
    return {
        "requested_candidates": tamanho,
        "available_candidates": len(recorte),
        "human_labels_missing": sum(r is None for r in rotulos),
        "baseline": resumo_base,
        "jev": resumo_jev,
        "metrics_available": completo and resumo_base["metrics"] is not None and resumo_jev["metrics"] is not None,
    }


def _resumo_pipeline(resultados: list[dict], rotulos: list[bool | None]) -> dict:
    return {
        "recorded_results": len(resultados),
        "calls": _soma_exata(resultados, "calls"),
        "input_tokens": _soma_exata(resultados, "input_tokens"),
        "output_tokens": _soma_exata(resultados, "output_tokens"),
        "cost": _soma_exata(resultados, "cost"),
        "latency_ms_total": _soma_exata(resultados, "latency_ms"),
        "human_review": sum(r.get("decision") is None for r in resultados) if resultados else None,
        "metrics": _metricas(rotulos, resultados),
    }


def executar(dataset: str | Path, baseline: str | Path, jev: str | Path, *, tamanhos=TAMANHOS_PADRAO) -> dict:
    candidatos = carregar_dataset(dataset)
    base = carregar_resultados(baseline)
    respostas_jev = carregar_resultados(jev)
    conhecidos = {c["id"] for c in candidatos}
    for resultados in (base, respostas_jev):
        if set(resultados) - conhecidos:
            raise ErroBenchmark("resultado_para_candidato_desconhecido")
    return {"dataset": str(dataset), "runs": [
        resumir(candidatos, base, respostas_jev, tamanho) for tamanho in tamanhos]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--baseline", required=True, help="JSON ou JSONL gravado")
    parser.add_argument("--jev", required=True, help="respostas Jev gravadas, sem rede")
    parser.add_argument("--output", help="arquivo JSON do relatório; padrão: stdout")
    args = parser.parse_args()
    try:
        relatorio = executar(args.dataset, args.baseline, args.jev)
    except ErroBenchmark as exc:
        parser.error(str(exc))
    texto = json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(texto, encoding="utf-8")
    else:
        print(texto, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
