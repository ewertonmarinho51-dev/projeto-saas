"""GovBot 1.1: recuperação pela pergunta, sem serviços ou credenciais reais."""

import copy
import json
from types import SimpleNamespace

import pytest

from src import db, govbot, llm, rag, state
from src.ui import govbot_panel as panel


BUSCAR_REFERENCIAS = rag.buscar_referencias
REFERENCIA = {
    "source_id": "rag:123", "documento_id": "norma-sintetica", "ordem": 0,
    "titulo": "Lei nº 14.133/2021 — fixture", "categoria": "lei", "tema": "srp",
    "trecho": "Art. 84. A ata de registro de preços terá vigência de um ano.",
    "similaridade": 0.9,
}


class Sessao(dict):
    def __getattr__(self, chave):
        try:
            return self[chave]
        except KeyError as erro:
            raise AttributeError(chave) from erro

    def __setattr__(self, chave, valor):
        self[chave] = valor


@pytest.fixture(autouse=True)
def sem_servicos_reais(monkeypatch):
    def proibido(*_args, **_kwargs):
        pytest.fail("teste tentou consultar serviço real")

    monkeypatch.setattr(db, "_cliente", proibido)
    monkeypatch.setattr(db, "cliente_do_usuario", proibido)
    monkeypatch.setattr(db, "disponivel", lambda: False)
    monkeypatch.setattr(db, "flag_ativa", lambda _nome: False)
    monkeypatch.setattr(llm, "chamar_ia_texto", proibido)
    monkeypatch.setattr(rag, "buscar_referencias", proibido)


def sessao(**alteracoes):
    valor = Sessao(dados={"objeto": "Aquisição de materiais de expediente"},
                   documentos={}, aprovados=set(), edicoes_pendentes={},
                   processo_id=None, etapa=0, _save_status="local")
    valor.update(alteracoes)
    return valor


def evento(texto, **alteracoes):
    valor = dict(request_id="rag-contextual-001", event_type="message", text=texto,
                 focus="objeto", proposal_id=None, draft={})
    valor.update(alteracoes)
    return valor


def motores(monkeypatch, *, refs=None, resposta=None, erro=False):
    buscas, prompts = [], []

    def buscar(consulta, **kwargs):
        buscas.append((consulta, kwargs))
        if erro:
            raise RuntimeError("segredo-da-excecao")
        return copy.deepcopy([REFERENCIA] if refs is None else refs)

    def chamar(_system, user, **_kwargs):
        prompts.append(json.loads(user.split("\n\nSua resposta anterior")[0]))
        return json.dumps(resposta or {
            "intent": "explain_current", "response": "A ata tem vigência de um ano.",
            "target": None, "payload": {}, "sources": ["rag:123"],
        }, ensure_ascii=False)

    monkeypatch.setattr(rag, "buscar_referencias", buscar)
    monkeypatch.setattr(llm, "chamar_ia_texto", chamar)
    return buscas, prompts


@pytest.mark.parametrize("pergunta", [
    "Qual o fundamento legal desta cláusula?",
    "Qual o fundamento legal do SRP?",
    "O que a legislação estabelece sobre esse prazo?",
    "Quando o SRP é recomendado?",
    "O que a nossa base diz sobre parcelamento?",
    "Existe orientação do TCU sobre isso?",
    "Essa cláusula está de acordo com nosso padrão?",
    "Qual é o fundamento dessa exigência?",
])
def test_pergunta_contextual_recupera_e_fonte_chega_ao_modelo(monkeypatch, pergunta):
    buscas, prompts = motores(monkeypatch)
    s = sessao()
    original = copy.deepcopy(s)
    bucket = govbot.obter_bucket(s)
    assert panel._processar_evento(s, bucket, evento(pergunta)) is False
    assert len(buscas) == 1
    assert buscas[0][1] == {"qtd": 6, "contextual": True}
    assert len(prompts) == 1
    ref = prompts[0]["contexto"]["referencias_rag"][0]
    assert ref["source_id"] == "rag:123"
    assert ref["documento_id"] == "norma-sintetica"
    assert ref["similaridade"] == 0.9
    assert ref["dispositivos"] == ["lei_14133_2021:84"]
    assert prompts[0]["source_allowlist"] == ["formulario:objeto", "rag:123"]
    assert all(s[k] == v for k, v in original.items())
    assert "_rag_trace" not in s
    assert bucket["changes"] == []


@pytest.mark.parametrize("texto", ["Olá GovBot.", "Obrigado", "Que legal",
                                   "Melhore este texto.", "O que preencher?",
                                   "Onde estou?", "O que está faltando?"])
def test_conversas_e_redacao_local_nao_consultam_rag(monkeypatch, texto):
    buscas, _ = motores(monkeypatch, resposta={
        "intent": "explain_current", "response": "Orientação local.",
        "target": None, "payload": {}, "sources": [],
    })
    s = sessao()
    bucket = govbot.obter_bucket(s)
    assert panel._processar_evento(s, bucket, evento(texto)) is False
    assert buscas == []
    panel._view_model(s, bucket)  # renderizar/microfrases não recupera
    assert buscas == []


def test_trace_suficiente_evitar_nova_busca_sem_ser_sobrescrito(monkeypatch):
    buscas, prompts = motores(monkeypatch)
    trace = {"dfd": {"referencias": [REFERENCIA]}}
    s = sessao(etapa=1, _rag_trace=copy.deepcopy(trace), documentos={
        "dfd": "# 1. OBJETO\n\nTexto sintético.",
    })
    panel._processar_evento(s, govbot.obter_bucket(s), evento(
        "Qual o fundamento legal da vigência da ata?", focus="editor_dfd"))
    assert buscas == []
    assert prompts[0]["contexto"]["recuperacao_rag"] == "suficiente"
    assert s["_rag_trace"] == trace


def test_mesmo_tema_nao_torna_trace_suficiente_para_outro_prazo(monkeypatch):
    buscas, _ = motores(monkeypatch)
    contexto = govbot.GovBotContext(None, 0, referencias_rag=(REFERENCIA,))
    panel._complementar_contexto_rag(sessao(), contexto, "Qual o fundamento legal do prazo de entrega?")
    assert len(buscas) == 1


@pytest.mark.parametrize("sources,response", [
    (["rag:999"], "Conforme a fonte inventada."),
    ([], "Conforme nenhuma fonte."),
    (["rag:123"], "Prazo de entrega: 15 dias."),
    (["rag:123"], "Nos termos do art. 999."),
])
def test_fonte_inventada_ou_conclusao_sem_lastro_rejeitada(monkeypatch, sources, response):
    buscas, prompts = motores(monkeypatch, resposta={
        "intent": "explain_current", "response": response,
        "target": None, "payload": {}, "sources": sources,
    })
    s = sessao()
    bucket = govbot.obter_bucket(s)
    assert panel._processar_evento(s, bucket, evento("Qual o fundamento legal desta cláusula?")) is False
    assert len(buscas) == 1 and len(prompts) == 2  # somente uma correção
    assert response != bucket["messages"][-1]["text"]
    assert not bucket["proposals"] and not bucket["changes"]


@pytest.mark.parametrize("erro", [True, False])
def test_rag_indisponivel_nao_chama_modelo_nem_mutacao(monkeypatch, caplog, erro):
    buscas, prompts = motores(monkeypatch, refs=[], erro=erro)
    s = sessao()
    bucket = govbot.obter_bucket(s)
    assert panel._processar_evento(s, bucket, evento(
        "Melhore o fundamento legal e aplique.")) is False
    assert len(buscas) == 1 and prompts == []
    assert not bucket["changes"] and not bucket["proposals"]
    assert "referência válida" in bucket["messages"][-1]["text"]
    assert "segredo-da-excecao" not in caplog.text
    panel._processar_evento(s, bucket, evento("Onde estou?", request_id="rag-offline-002"))
    assert "foco atual" in bucket["messages"][-1]["text"]


def test_consulta_nao_serializa_planilha_historia_dados_pessoais_ou_segredos(monkeypatch, caplog):
    buscas, prompts = motores(monkeypatch)
    s = sessao(dados={
        "objeto": "Aquisição de materiais de expediente para NomePessoalSegredo cpf 123.456.789-00",
        "orgao": "OrgaoParticularSecreto", "responsavel": "PessoaSecreta",
        "itens": [{"descricao": f"item-ultrassecreto-{i}"} for i in range(210)],
    })
    bucket = govbot.obter_bucket(s)
    govbot.adicionar_mensagem(bucket, "assistant", "Prazo histórico de 15 dias.")
    with caplog.at_level("INFO", logger="govdocs.govbot.ui"):
        panel._processar_evento(s, bucket, evento(
            "Qual o fundamento legal desta planilha? NomePessoalSegredo "
            "cpf 123.456.789-00 email pessoa@example.com token abc-secret-123"))
    consulta = buscas[0][0]
    assert len(consulta) <= 500
    assert "expediente" in consulta
    for proibido in ("NomePessoalSegredo", "123.456", "pessoa", "example", "token",
                     "abc-secret", "15 dias", "ultrassecreto", "PessoaSecreta", "OrgaoParticular"):
        assert proibido.casefold() not in consulta.casefold()
    contexto_json = json.dumps(prompts[0]["contexto"])
    assert "item-ultrassecreto" not in contexto_json
    assert "15 dias" not in contexto_json
    assert "consulta" not in prompts[0]["contexto"]
    assert "NomePessoalSegredo" not in caplog.text


@pytest.mark.parametrize("documento", ["edital", "arp"])
def test_busca_nao_autoriza_patch_em_instrumento_deterministico(monkeypatch, documento):
    buscas, prompts = motores(monkeypatch, resposta={
        "intent": "apply_section_patch", "response": "Aplicando.",
        "target": f"{documento}/clausula/1/1",
        "payload": {"new_value": "Texto livre", "reason": "teste"}, "sources": ["rag:123"],
    })
    s = sessao()
    contexto = govbot.montar_contexto_minimo(
        foco=f"editor_{documento}", documento=documento)
    contexto = panel._complementar_contexto_rag(s, contexto, "Melhore o fundamento legal e aplique.")
    bucket = govbot.obter_bucket(s)
    reply = govbot.processar_mensagem(govbot.parsear_evento(evento(
        "Melhore o fundamento legal e aplique.", focus=f"editor_{documento}")), contexto, bucket)
    assert len(buscas) == 1 and len(prompts) == 2
    assert reply.proposal is None and not bucket["changes"]


def test_replay_nao_repete_busca(monkeypatch):
    buscas, _ = motores(monkeypatch)
    s = sessao()
    bucket = govbot.obter_bucket(s)
    pedido = evento("Qual o fundamento legal desta cláusula?")
    panel._processar_evento(s, bucket, pedido)
    with pytest.raises(govbot.IdentificadorRepetido):
        panel._processar_evento(s, bucket, pedido)
    assert len(buscas) == 1


def test_fontes_normalizadas_com_limites_e_ids_deterministicos():
    bruto = {"titulo": "Norma", "categoria": "lei", "conteudo": "x" * 4_000,
             "embedding": [0] * 500, "similaridade": float("nan")}
    refs = govbot._recortar_referencias([bruto, bruto, "invalido"], None)
    assert len(refs) == 1 and len(refs[0]["trecho"]) == 1_000
    assert refs == govbot._recortar_referencias([bruto], None)
    assert refs[0]["source_id"].startswith("rag:")
    assert "embedding" not in refs[0] and "similaridade" not in refs[0]


@pytest.mark.parametrize("vetorial", [True, False])
def test_busca_existente_reutiliza_rpc_embedding_piso_e_textual(monkeypatch, vetorial):
    # Exercita buscar_referencias real, com RPC e embeddings sintéticos.
    chamadas, embeddings = [], []
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "obter_config", lambda _chave: "")

    def embed(textos, para_consulta):
        embeddings.append((textos, para_consulta))
        return [[0.0, 0.1]] if vetorial else None

    def rpc(nome, params):
        chamadas.append((nome, params))
        return [{"id": "bom", "similaridade": 0.9},
                {"id": "ruim", "similaridade": 0.001}]

    monkeypatch.setattr(rag, "_gerar_embeddings", embed)
    monkeypatch.setattr(rag, "_executar_rpc", rpc)
    consulta = "fundamento vigência registro preços entrega materiais expediente"
    resultado = BUSCAR_REFERENCIAS(consulta, qtd=6, contextual=True)
    assert [r["id"] for r in resultado] == ["bom"]
    assert len(embeddings) == 1 and embeddings[0] == ([consulta], True)
    assert len(chamadas) == 1
    assert chamadas[0][0] == f"buscar_chunks_{'vetorial' if vetorial else 'textual'}"
    if not vetorial:
        assert chamadas[0][1]["consulta"] == rag.consulta_textual(consulta, maximo=16)


def test_proposta_aplicar_autosave_e_undo_sem_nova_busca(monkeypatch):
    buscas, _ = motores(monkeypatch, resposta={
        "intent": "suggest_field", "response": "Sugestão pronta.",
        "target": "justificativa", "payload": {
            "value": "Necessidade de atender às unidades administrativas.", "reason": "Clareza",
        }, "sources": [],
    })
    s = sessao(dados={"justificativa": "Necessidade de atender às unidades."},
                documentos={"dfd": "DFD sintético", "etp": "ETP sintético"},
                aprovados={"dfd"})
    monkeypatch.setattr(state, "st", SimpleNamespace(session_state=s))
    salvamentos = []

    def salvar():
        salvamentos.append(copy.deepcopy(s["dados"]))
        s["_save_status"] = "local"

    monkeypatch.setattr(state, "autosalvar", salvar)
    bucket = govbot.obter_bucket(s)
    original = copy.deepcopy(s["dados"])
    assert panel._processar_evento(s, bucket, evento(
        "Melhore esta justificativa.", focus="justificativa")) is False
    assert s["dados"] == original and salvamentos == []
    proposta = next(iter(bucket["proposals"].values()))
    assert proposta["before"] == original["justificativa"]
    assert panel._processar_evento(s, bucket, evento(
        "", event_type="apply_proposal", request_id="rag-apply-002", focus="justificativa",
        proposal_id=proposta["proposal_id"])) is True
    assert s["dados"]["justificativa"] == proposta["after"]
    assert s["documentos"] == {} and len(salvamentos) == 1
    assert panel._processar_evento(s, bucket, evento(
        "", event_type="undo", request_id="rag-undo-003", focus="justificativa")) is True
    assert s["dados"] == original and len(salvamentos) == 2
    assert s["documentos"] == {"dfd": "DFD sintético", "etp": "ETP sintético"}
    assert buscas == []
