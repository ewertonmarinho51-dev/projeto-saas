from __future__ import annotations

from copy import deepcopy

import pytest

from src import db, governanca
from src.precos import decisoes, jev
from src.precos.modelo import hash_do_bruto


def referencia():
    bruto = {"official": "evidence", "version": 1}
    return {"id": "ref-1", "id_externo": "official-1", "fonte_id": "pncp",
            "fonte_tipo": "sistema_oficial", "bruto": bruto, "raw_hash": hash_do_bruto(bruto),
            "descricao_original": "Caneta azul", "unidade_original": "UN",
            "unidade_normalizada": "UN", "capacidade_embalagem": None,
            "codigo_catalogo": "123", "tipo_catalogo": "CATMAT", "valor_unitario_original": "4.20",
            "natureza_valor": "praticado", "data_compra": "2026-09-01"}


def item():
    return {"id": "item-1", "descricao": "Caneta esferográfica azul", "unidade": "UN", "codigo": "123", "tipo_catalogo": "CATMAT"}


def pesquisa():
    return {"id": "p-1", "data_base": "2026-10-01"}


def resposta_perguntas(questions, model="typesafe/jev-1.13"):
    answers = {}
    for name, question in questions.items():
        if question["type"] == "noul":
            answers[name] = {"type": "noul", "noul": 0.8}
        elif question["type"] == "choice":
            choice = next(iter(question["criteria"]))
            answers[name] = {"type": "choice", "confidence": 0.8,
                             "probabilities": {k: 1.0 if k == choice else 0.0 for k in question["criteria"]},
                             "choice": choice}
        else:
            criteria = question["criteria"]
            answers[name] = {"type": "score", "confidence": 0.8,
                             "probabilities": {str(i): 1.0 if i == 0 else 0.0 for i in range(len(criteria))},
                             "score": 0, "legend": {str(i): value for i, value in enumerate(criteria)}}
    return jev.Resultado(answers, model, {"input_tokens": 1, "output_tokens": 1, "cost": 0.001})


class Repo:
    def __init__(self, ref=None):
        self.pesquisa, self.item, self.ref = pesquisa(), item(), ref or referencia()
        self.events, self.claims, self.cache = [], True, None

    def contexto_decisao(self, *_):
        return self.pesquisa, self.item, self.ref

    def evento_decisao(self, *_):
        return self.cache

    def registrar_evento(self, *args, **kwargs):
        self.events.append((args, kwargs))
        return {"id": "event"} if self.claims else None

    def listar_referencias(self, *_):
        return [self.ref]


@pytest.fixture(autouse=True)
def flag_ligada(monkeypatch):
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == governanca.FLAG_JEV_PRECOS)
    monkeypatch.setattr(db, "tenant_atual", lambda: "tenant-1")


def config():
    return {"model": "typesafe/jev-1.13", "failure_mode": "HUMAN_REVIEW"}


def test_state_omite_dinheiro_quantidade_e_identificadores_pessoais():
    ref = referencia() | {"valor_unitario_original": "99.99", "quantidade_original": "1000",
                          "fornecedor": "Pessoa", "ni_fornecedor": "123", "orgao": "Órgão"}
    state = decisoes.state_referencia(item(), ref)
    assert "valor_unitario_original" not in state["reference"]
    assert "quantidade_original" not in state["reference"]
    assert "fornecedor" not in state["reference"]
    assert "ni_fornecedor" not in state["reference"]
    assert "orgao" not in state["reference"]


def test_barreiras_impedem_chamada_quando_hash_desatualizado_ou_sem_preco():
    for ref in (referencia() | {"raw_hash": "velho"}, referencia() | {"valor_unitario_original": None}):
        repo, calls = Repo(ref), []
        result = decisoes.revisar_referencia("p-1", "item-1", "ref-1", repo=repo,
                                             config=config(), motor=lambda **kwargs: calls.append(kwargs))
        assert result["status"] == "manual_review"
        assert result["called"] is False
        assert calls == []
        assert len(repo.events) == 1
        args, kwargs = repo.events[0]
        assert args[1] == "busca_concluida"
        assert kwargs["idempotency_key"].startswith("jev:result:blocked:")
        assert kwargs["payload"]["called"] is False


def test_flag_desligada_nao_le_contexto_nem_chama_motor(monkeypatch):
    monkeypatch.setattr(db, "flag_ativa", lambda _: False)
    repo = Repo()
    assert decisoes.revisar_referencia("p-1", "item-1", "ref-1", repo=repo, config=config()) == {"status": "disabled"}
    assert repo.events == []


def test_identidade_exata_pula_jev_mas_nao_autoaceita():
    repo, calls = Repo(), []
    repo.item = repo.item | {"descricao": repo.ref["descricao_original"]}
    result = decisoes.revisar_referencia("p-1", "item-1", "ref-1", repo=repo,
                                         config=config(), motor=lambda **kw: calls.append(kw))
    assert result["status"] == "deterministic_match"
    assert result["called"] is False and result["automatic_acceptance"] is False
    assert calls == [] and len(repo.events) == 1
    assert repo.events[0][1]["idempotency_key"].startswith("jev:result:blocked:")


def test_cache_persistente_e_claim_concorrente_nunca_refazem_chamada():
    repo, calls = Repo(), []
    state = decisoes.state_referencia(repo.item, repo.ref)
    chave = decisoes.chave_cache("tenant-1", "p-1", "item-1", state, config()["model"])
    repo.cache = {"state_hash": hash_do_bruto(state), "response": resposta_perguntas(decisoes.PERGUNTAS).registro(),
                  "idempotency_key": "jev:result:" + chave}
    result = decisoes.revisar_referencia("p-1", "item-1", "ref-1", repo=repo, config=config(),
                                         motor=lambda **kw: calls.append(kw))
    assert result["cache_hit"] is True and result["called"] is False and calls == []

    repo.cache, repo.claims = None, False
    result = decisoes.revisar_referencia("p-1", "item-1", "ref-1", repo=repo, config=config(),
                                         motor=lambda **kw: calls.append(kw))
    assert result["status"] == "manual_review" and result["called"] is False and calls == []


def test_releitura_com_state_alterado_marca_decisao_stale_e_persiste_revisao():
    repo = Repo()

    def motor(**kwargs):
        repo.ref = deepcopy(repo.ref)
        repo.ref["descricao_original"] = "Caneta vermelha"
        return resposta_perguntas(kwargs["questions"])

    result = decisoes.revisar_referencia("p-1", "item-1", "ref-1", repo=repo, config=config(), motor=motor)
    assert result["status"] == "manual_review"
    assert result["erro"] == "decisao_desatualizada"
    assert result["automatic_acceptance"] is False
    assert len(repo.events) == 2


@pytest.mark.parametrize("alterar", [
    lambda repo: repo.ref.update(valor_unitario_original=None),
    lambda repo: repo.ref.update(natureza_valor="proposta"),
    lambda repo: repo.pesquisa.update(data_base="2028-10-01"),
])
def test_releitura_reaplica_barreiras_fora_do_state( alterar):
    repo = Repo()

    def motor(**kwargs):
        alterar(repo)
        return resposta_perguntas(kwargs["questions"])

    result = decisoes.revisar_referencia("p-1", "item-1", "ref-1", repo=repo,
                                         config=config(), motor=motor)
    assert result["erro"] == "decisao_desatualizada"
    assert result["status"] == "manual_review"


def test_analise_atual_recusa_unidade_ou_outro_candidato_mudado_sem_mudar_raw_hash():
    ref = referencia()
    state = decisoes.state_referencia(item(), ref)
    analise = {"model_requested": config()["model"], "questions_version": decisoes.VERSAO_PERGUNTAS,
               "questions_hash": hash_do_bruto(decisoes.PERGUNTAS), "state_hash": hash_do_bruto(state)}
    assert decisoes.analise_atual(analise, item(), ref, [ref], config()["model"])
    assert not decisoes.analise_atual(analise, item(), ref | {"unidade_normalizada": "CX"}, [ref], config()["model"])

    outro = referencia() | {"id": "ref-2", "id_externo": "official-2", "codigo_catalogo": "124",
                            "descricao_original": "Caneta preta"}
    catalogo_state, catalogo_questions = decisoes.preparar_catalogo(item(), [ref, outro])
    catalogo = {"model_requested": config()["model"], "questions_version": decisoes.VERSAO_PERGUNTAS,
                "questions_hash": hash_do_bruto(catalogo_questions), "state_hash": hash_do_bruto(catalogo_state),
                "finalidades": ["catalog_candidate_selection"]}
    assert decisoes.analise_atual(catalogo, item(), ref, [ref, outro], config()["model"])
    alterado = outro | {"descricao_original": "Caneta preta premium"}
    assert alterado["raw_hash"] == outro["raw_hash"]
    assert not decisoes.analise_atual(catalogo, item(), ref, [ref, alterado], config()["model"])


def test_fallback_so_usa_falha_de_transporte_e_permanece_explicativo(monkeypatch):
    from src.precos import semantica

    repo, chamadas = Repo(), []
    configuracao = config() | {"failure_mode": "LLM_FALLBACK"}
    monkeypatch.setattr(semantica, "motor_do_projeto", lambda **_: chamadas.append("motor") or "texto")

    class Proposta:
        acao, alvo = "explicar", "ref-1"
        def para_relatorio(self): return {"acao": self.acao, "alvo": self.alvo}

    monkeypatch.setattr(semantica, "chamar", lambda *a, **k: chamadas.append("chamar") or Proposta())
    falhar_stale = lambda **_: (_ for _ in ()).throw(jev.ErroDecisao("decisao_desatualizada"))
    resultado = decisoes.revisar_referencia("p-1", "item-1", "ref-1", repo=repo,
                                             config=configuracao, motor=falhar_stale)
    assert "fallback" not in resultado and chamadas == []

    falhar_http = lambda **_: (_ for _ in ()).throw(jev.ErroDecisao("http_503"))
    resultado = decisoes.revisar_referencia("p-1", "item-1", "ref-1", repo=Repo(),
                                             config=configuracao, motor=falhar_http)
    assert resultado["fallback"] == {"acao": "explicar", "alvo": "ref-1"}
    assert chamadas == ["motor", "chamar"]


def test_catalogo_recusa_candidatos_invalidos_e_choice_so_oferece_recuperados():
    with pytest.raises(jev.ErroDecisao, match="catalogo_invalido"):
        decisoes.perguntas_catalogo([{"codigo": "none", "descricao": "x"}])
    questions = decisoes.perguntas_catalogo([{"codigo": "CATMAT:1", "descricao": "Caneta"}])
    assert set(questions["catalog_candidate_selection"]["criteria"]) == {"CATMAT:1", "none"}
