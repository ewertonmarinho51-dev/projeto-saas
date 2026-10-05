"""OpenRouter Decisions: transporte tipado, sem regras de preço ou sessão.

Contrato: https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request
Noul é probabilidade; não possui o campo confidence de Choice/Score.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable

import httpx

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"


class ErroDecisao(ValueError):
    """Código seguro: nunca inclui corpo HTTP, state ou credencial."""


@dataclass(frozen=True)
class Resultado:
    answers: dict
    model: str
    usage: dict
    request_id: str = ""
    provider: str = ""
    tentativas: int = 1

    def registro(self) -> dict:
        return {"answers": self.answers, "model": self.model,
                "usage": self.usage, "id": self.request_id,
                "provider": self.provider}


def _numero(valor, minimo=0, maximo=1):
    if (isinstance(valor, bool) or not isinstance(valor, (int, float))
            or not math.isfinite(valor) or not minimo <= valor <= maximo):
        raise ErroDecisao("numero_invalido")
    return valor


def validar_resposta(bruto: dict, questions: dict, model: str) -> Resultado:
    if not isinstance(bruto, dict) or set(bruto) - {
            "answers", "model", "usage", "id", "provider"}:
        raise ErroDecisao("envelope_invalido")
    snapshot = bruto.get("model")
    if not isinstance(snapshot, str) or not (
            snapshot == model or snapshot.startswith(model + "-")):
        raise ErroDecisao("modelo_inesperado")
    answers = bruto.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ErroDecisao("perguntas_incompletas")
    for nome, question in questions.items():
        answer = answers[nome]
        tipo = question["type"]
        if not isinstance(answer, dict) or answer.get("type") != tipo:
            raise ErroDecisao("tipo_invalido")
        if tipo == "noul":
            if set(answer) != {"type", "noul"}:
                raise ErroDecisao("noul_invalido")
            _numero(answer["noul"])
            continue
        campos = {"type", "confidence", "probabilities", tipo}
        if tipo == "score":
            campos.add("legend")
        if set(answer) != campos:
            raise ErroDecisao("campos_invalidos")
        _numero(answer["confidence"])
        opcoes = (set(question["criteria"]) if tipo == "choice" else
                  {str(i) for i in range(len(question["criteria"]))})
        probs = answer["probabilities"]
        if not isinstance(probs, dict) or set(probs) != opcoes:
            raise ErroDecisao("distribuicao_invalida")
        valores = [_numero(v) for v in probs.values()]
        if not math.isclose(sum(valores), 1, abs_tol=0.015):
            raise ErroDecisao("distribuicao_invalida")
        if tipo == "choice":
            if not isinstance(answer[tipo], str) or answer[tipo] not in opcoes:
                raise ErroDecisao("opcao_nao_oferecida")
            if probs[answer[tipo]] < max(valores):
                raise ErroDecisao("escolha_inconsistente")
        elif tipo == "score":
            _numero(answer[tipo], maximo=len(opcoes) - 1)
            legend = {str(i): c for i, c in enumerate(question["criteria"])}
            if answer["legend"] != legend:
                raise ErroDecisao("rubrica_invalida")
            esperado = sum(int(k) * v for k, v in probs.items())
            if not math.isclose(answer[tipo], esperado, abs_tol=0.03):
                raise ErroDecisao("score_inconsistente")
        else:
            raise ErroDecisao("tipo_nao_suportado")
    usage = bruto.get("usage")
    if not isinstance(usage, dict) or set(usage) != {
            "input_tokens", "output_tokens", "cost"}:
        raise ErroDecisao("usage_invalido")
    for campo in ("input_tokens", "output_tokens"):
        if type(usage[campo]) is not int or usage[campo] < 0:
            raise ErroDecisao("tokens_invalidos")
    _numero(usage["cost"], maximo=float("inf"))
    for campo in ("id", "provider"):
        if campo in bruto and not isinstance(bruto[campo], str):
            raise ErroDecisao("metadado_invalido")
    return Resultado(answers, snapshot, usage, bruto.get("id", ""),
                     bruto.get("provider", ""))


def decidir(*, key: str, model: str, state: dict, questions: dict,
            timeout: float = 20, max_retries: int = 1,
            post: Callable | None = None, sleep: Callable = time.sleep) -> Resultado:
    if not key:
        raise ErroDecisao("credencial_ausente")
    enviar = post or httpx.post
    for tentativa in range(max_retries + 1):
        try:
            resposta = enviar(ENDPOINT, headers={"Authorization": f"Bearer {key}"},
                              json={"model": model, "state": state,
                                    "questions": questions}, timeout=timeout,
                              follow_redirects=False)
        except httpx.TimeoutException:
            # Uma requisição com timeout pode ter sido faturada. Não repetir.
            raise ErroDecisao("timeout_resultado_desconhecido") from None
        except httpx.HTTPError:
            raise ErroDecisao("falha_transporte") from None
        status = resposta.status_code
        if status == 429 or 500 <= status <= 599:
            if tentativa < max_retries:
                sleep(min(2 ** tentativa, 8))
                continue
        if status != 200:
            raise ErroDecisao(f"http_{status}")
        try:
            bruto = resposta.json()
        except (ValueError, TypeError):
            raise ErroDecisao("json_invalido") from None
        resultado = validar_resposta(bruto, questions, model)
        return Resultado(resultado.answers, resultado.model, resultado.usage,
                         resultado.request_id, resultado.provider, tentativa + 1)
    raise ErroDecisao("tentativas_esgotadas")
