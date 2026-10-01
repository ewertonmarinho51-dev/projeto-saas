from __future__ import annotations

import httpx
import pytest

from src.precos import jev


QUESTIONS = {
    "compare": {"type": "noul", "criteria": {"true": "sim", "false": "não"}},
    "reason": {"type": "choice", "criteria": {"same": "igual", "other": "outro"}},
    "score": {"type": "score", "criteria": ["baixo", "alto"]},
}
MODEL = "typesafe/jev-1.13"


def resposta():
    return {
        "answers": {
            "compare": {"type": "noul", "noul": 0.8},
            "reason": {"type": "choice", "confidence": 0.8,
                       "probabilities": {"same": 0.8, "other": 0.2}, "choice": "same"},
            "score": {"type": "score", "confidence": 0.8,
                      "probabilities": {"0": 0.2, "1": 0.8}, "score": 0.8,
                      "legend": {"0": "baixo", "1": "alto"}},
        },
        "model": MODEL + "-20260930", "usage": {"input_tokens": 12, "output_tokens": 3, "cost": 0.01},
        "id": "req-1", "provider": "openrouter",
    }


def test_validar_contrato_noul_choice_score_e_registro():
    resultado = jev.validar_resposta(resposta(), QUESTIONS, MODEL)
    assert resultado.model == MODEL + "-20260930"
    assert resultado.answers["compare"] == {"type": "noul", "noul": 0.8}
    assert resultado.registro()["usage"]["cost"] == 0.01


@pytest.mark.parametrize(("mudar", "erro"), [
    (lambda r: r.pop("answers"), "perguntas_incompletas"),
    (lambda r: r["answers"]["reason"].update(type="score"), "tipo_invalido"),
    (lambda r: r["answers"]["reason"]["probabilities"].update(same=0.1), "distribuicao_invalida"),
    (lambda r: r["answers"]["reason"].update(choice="inventada"), "opcao_nao_oferecida"),
    (lambda r: r["answers"]["compare"].update(confidence=0.8), "noul_invalido"),
    (lambda r: r["usage"].pop("cost"), "usage_invalido"),
    (lambda r: r.update(extra="não aceito"), "envelope_invalido"),
])
def test_validar_recusa_respostas_incompletas_e_campos_nao_contratados(mudar, erro):
    bruto = resposta()
    mudar(bruto)
    with pytest.raises(jev.ErroDecisao, match=erro):
        jev.validar_resposta(bruto, QUESTIONS, MODEL)


class FakeResponse:
    def __init__(self, status=200, body=None, json_error=False):
        self.status_code, self.body, self.json_error = status, body, json_error

    def json(self):
        if self.json_error:
            raise ValueError("não-json")
        return self.body


def test_decidir_reenvia_429_e_500_mas_nao_timeout_e_nao_vaza_chave():
    chamadas, esperas = [], []
    respostas = [FakeResponse(429), FakeResponse(500), FakeResponse(body=resposta())]

    def post(*args, **kwargs):
        chamadas.append((args, kwargs))
        return respostas.pop(0)

    resultado = jev.decidir(key="segredo", model=MODEL, state={"a": 1}, questions=QUESTIONS,
                            max_retries=2, post=post, sleep=esperas.append)
    assert resultado.tentativas == 3
    assert esperas == [1, 2]
    assert chamadas[0][0] == (jev.ENDPOINT,)
    assert chamadas[0][1]["follow_redirects"] is False
    assert chamadas[0][1]["json"] == {"model": MODEL, "state": {"a": 1}, "questions": QUESTIONS}

    with pytest.raises(jev.ErroDecisao, match="timeout_resultado_desconhecido"):
        jev.decidir(key="segredo", model=MODEL, state={}, questions=QUESTIONS,
                    post=lambda *a, **k: (_ for _ in ()).throw(httpx.TimeoutException("x")))


@pytest.mark.parametrize("resposta_http,erro", [
    (FakeResponse(401), "http_401"),
    (FakeResponse(500), "http_500"),
    (FakeResponse(json_error=True), "json_invalido"),
])
def test_decidir_recusa_http_e_json_invalidos(resposta_http, erro):
    with pytest.raises(jev.ErroDecisao, match=erro):
        jev.decidir(key="k", model=MODEL, state={}, questions=QUESTIONS,
                    max_retries=0, post=lambda *a, **k: resposta_http)
