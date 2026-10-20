"""Measure GovBot selection scope against full-document regeneration without calling a provider."""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from scripts import medir_custo, wordcraft_corpus
from src import govbot


def measure(docx: bytes, *, input_usd_per_million: Decimal | None = None) -> dict:
    blocks = wordcraft_corpus.text_blocks(docx)
    body = blocks["body"]
    if not body:
        raise ValueError("DOCX has no semantic body blocks")
    selected = max(body, key=lambda value: (len(value), value))
    full = "\n".join(body + blocks["headers"] + blocks["footers"])
    if not selected.strip() or len(full) <= len(selected):
        raise ValueError("DOCX does not distinguish selection from full document")
    target = "etp/clausula/1/11111111-1111-1111-1111-111111111111"
    request = "Melhore a clareza do trecho selecionado sem alterar dados materiais."

    def prompt(value: str) -> tuple[str, str]:
        context = govbot.GovBotContext(processo_id="synthetic-qa", etapa=0,
            documento="etp", bloco_em_foco=target, valor_atual=value)
        return govbot.montar_prompt(context, request,
            alvos_permitidos=(target,), fontes_permitidas=())

    selected_prompt = prompt(selected)
    full_prompt = prompt(full)
    selected_tokens = sum(medir_custo.tokens(part) for part in selected_prompt)
    full_tokens = sum(medir_custo.tokens(part) for part in full_prompt)
    if not 0 < selected_tokens < full_tokens:
        raise ValueError("Selection prompt did not reduce input tokens")
    avoided = full_tokens - selected_tokens
    cost = None if input_usd_per_million is None else (
        Decimal(avoided) * input_usd_per_million / Decimal(1_000_000))
    return {
        "schema": "gc-wordcraft-ai-scope-benchmark/v1",
        "status": "SYNTHETIC_TOKEN_MEASUREMENT_NO_PROVIDER_CALL",
        "tokenizer": "o200k_base (tiktoken)",
        "source_docx_sha256": hashlib.sha256(docx).hexdigest(),
        "source_body_blocks": len(body),
        "selected_chars": len(selected),
        "full_document_chars": len(full),
        "actual_provider_calls": 0,
        "hypothetical_calls": {"selection_edit": 1, "full_regeneration": 1},
        "input_tokens": {"selection_edit": selected_tokens,
            "full_regeneration": full_tokens, "avoided": avoided,
            "avoided_percent": round(avoided * 100 / full_tokens, 4)},
        "input_usd_per_million": (str(input_usd_per_million)
            if input_usd_per_million is not None else None),
        "estimated_input_cost_avoided_usd": str(cost) if cost is not None else None,
        "cost_status": "CALCULATED_FROM_EXPLICIT_INPUT_PRICE" if cost is not None
            else "NOT_CALCULATED_NO_MODEL_PRICE",
        "content_persisted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docx", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--input-usd-per-million", type=Decimal)
    args = parser.parse_args()
    destination = args.out.resolve()
    if destination.exists() or destination.suffix.lower() != ".json" or not destination.parent.is_dir():
        parser.error("Output must be a new JSON file in an existing directory")
    data = args.docx.read_bytes()
    result = measure(data, input_usd_per_million=args.input_usd_per_million)
    destination.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "actual_provider_calls": 0,
        "input_tokens_avoided": result["input_tokens"]["avoided"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
