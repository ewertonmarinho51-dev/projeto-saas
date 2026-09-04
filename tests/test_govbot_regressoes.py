"""Regressões dos contratos de evento, sessão e confirmação do GovBot."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from src import achados, blocos, corretor, fatos, governanca, govbot, llm, state
from src.ui import govbot_panel


class _Sessao(dict):
    """Mapping com os acessos por atributo usados por ``state``."""

    def __getattr__(self, nome):
        try:
            return self[nome]
        except KeyError as erro:
            raise AttributeError(nome) from erro

    def __setattr__(self, nome, valor):
        self[nome] = valor


def _sessao(**mudancas):
    sessao = _Sessao({
        "dados": {"objeto": "Aquisição de cadeiras", "justificativa": "Original"},
        "documentos": {},
        "aprovados": set(),
        "edicoes_pendentes": {},
        "etapa": 0,
        "processo_id": None,
        "_save_status": "local",
    })
    sessao.update(mudancas)
    return sessao


def _evento(**mudancas):
    evento = {
        "request_id": "regressao-evento-001",
        "event_type": "message",
        "text": "Onde estou?",
        "focus": "objeto",
        "proposal_id": None,
        "draft": {},
    }
    evento.update(mudancas)
    return evento


def _motor_indisponivel(monkeypatch):
    chamadas = []

    def falhar(*_args, **_kwargs):
        chamadas.append(True)
        raise RuntimeError("motor de IA indisponível no teste")

    monkeypatch.setattr(llm, "chamar_ia_texto", falhar)
    return chamadas


@pytest.mark.parametrize("chave", govbot.CHAVES_EVENTO)
def test_evento_exige_cada_uma_das_seis_chaves(chave):
    evento = _evento()
    evento.pop(chave)

    with pytest.raises(govbot.ErroEvento, match="ausentes"):
        govbot.parsear_evento(evento)


def test_evento_com_seis_chaves_aceita_nulos_explicitos():
    evento = govbot.parsear_evento(_evento(focus=None, proposal_id=None))

    assert evento.focus is None
    assert evento.proposal_id is None
    assert evento.draft == {}


@pytest.mark.parametrize("etapa,foco,draft", [
    (0, "objeto", {"editor_dfd": "Documento fora da etapa"}),
    (1, "editor_dfd", {"objeto": "Campo fora da etapa"}),
    (1, "editor_dfd", {"editor_etp": "Outro documento"}),
])
def test_draft_de_outra_etapa_e_rejeitado_sem_mudar_sessao(etapa, foco, draft):
    sessao = _sessao(etapa=etapa)
    bucket = govbot.obter_bucket(sessao)
    antes = copy.deepcopy(sessao)

    with pytest.raises(govbot.ErroAlvo, match="fora da tela atual"):
        govbot_panel._processar_evento(
            sessao, bucket, _evento(focus=foco, draft=draft))

    assert sessao == antes


@pytest.mark.parametrize("valor", ["", "Modelo administrativo inventado", "SRP livre"])
def test_draft_rejeita_modelo_execucao_fora_do_enum(valor):
    sessao = _sessao()
    bucket = govbot.obter_bucket(sessao)
    antes = copy.deepcopy(sessao)

    with pytest.raises(govbot.ErroEvento, match="modelo_execucao"):
        govbot_panel._processar_evento(sessao, bucket, _evento(
            focus="modelo_execucao", draft={"modelo_execucao": valor}))

    assert sessao == antes


def test_view_model_preserva_foco_entre_duas_mensagens(monkeypatch):
    sessao = _sessao()
    bucket = govbot.obter_bucket(sessao)
    _motor_indisponivel(monkeypatch)

    assert govbot_panel._processar_evento(sessao, bucket, _evento(
        request_id="regressao-foco-001",
        focus="govbot_campo_justificativa",
        draft={"justificativa": "Rascunho ainda não enviado"},
    )) is False
    primeiro = govbot_panel._view_model(sessao, bucket)
    assert primeiro["focus"] == "justificativa"

    assert govbot_panel._processar_evento(sessao, bucket, _evento(
        request_id="regressao-foco-002", focus=None,
        text="Continue a explicação",
        draft={"justificativa": "Rascunho ainda não enviado"},
    )) is False
    segundo = govbot_panel._view_model(sessao, bucket)

    assert segundo["focus"] == primeiro["focus"]
    assert bucket["_last_focus"] == "justificativa"
    assert len(segundo["messages"]) == 4
    assert sessao["dados"]["justificativa"] == "Original"


def test_troca_de_processo_limpa_editores_e_widgets_govbot(monkeypatch):
    sessao = _sessao(
        processo_id="processo-anterior", etapa=1,
        documentos={"dfd": "DFD anterior"},
        editor_dfd="Edição não enviada do processo anterior",
        editor_etp="ETP anterior",
        govbot_campo_objeto="Objeto do processo anterior",
        govbot_campo_justificativa="Justificativa do processo anterior",
        preferencia_global="preservar",
    )
    anterior = govbot.obter_bucket(sessao, "processo-anterior")
    govbot.adicionar_mensagem(anterior, "user", "Histórico do processo anterior")
    govbot.guardar_rascunho(sessao, {"editor_dfd": sessao["editor_dfd"]})
    reruns = []
    monkeypatch.setattr(state, "st", SimpleNamespace(
        session_state=sessao, rerun=lambda: reruns.append(True)))
    monkeypatch.setattr(govbot_panel, "_sessao", lambda: sessao)
    monkeypatch.setattr(govbot, "ativo", lambda: True)

    state.carregar_processo_salvo({
        "id": "processo-novo", "dados": {"objeto": "Objeto novo"},
        "documentos": {"dfd": "DFD novo"}, "aprovados": [], "etapa": 1,
    })
    novo = govbot_panel.preparar_sessao()

    assert novo is not anterior
    assert novo["messages"] == []
    assert not any(chave.startswith(("editor_", "govbot_campo_"))
                   for chave in sessao)
    assert sessao[govbot.CHAVE_RASCUNHO] == {}
    assert sessao["documentos"] == {"dfd": "DFD novo"}
    assert sessao["preferencia_global"] == "preservar"
    assert anterior["messages"][0]["text"] == "Histórico do processo anterior"
    assert reruns == [True]


def _sessao_com_alteracao(monkeypatch):
    sessao = _sessao()
    bucket = govbot.obter_bucket(sessao)
    proposta = govbot.criar_proposta_campo(
        "justificativa", "Original", "Texto revisado", "Clareza")
    govbot.aplicar_campo_escalar(
        sessao, bucket, proposta, "regressao-base-undo")
    monkeypatch.setattr(state, "autosalvar", lambda: sessao.update({
        "_save_status": "local"}))
    chamadas_motor = _motor_indisponivel(monkeypatch)
    return sessao, bucket, chamadas_motor


@pytest.mark.parametrize("pedido", [
    "Desfaça a última alteração.",
    "Desfazer a última alteração.",
])
def test_undo_textual_explicito_funciona_offline(monkeypatch, pedido):
    sessao, bucket, chamadas_motor = _sessao_com_alteracao(monkeypatch)

    assert govbot_panel._processar_evento(sessao, bucket, _evento(
        request_id="regressao-undo-textual", text=pedido,
        focus="justificativa", draft={"justificativa": "Texto revisado"},
    )) is True

    assert sessao["dados"]["justificativa"] == "Original"
    assert bucket["changes"] == []
    assert chamadas_motor == []
    assert "somente nesta sessão" in bucket["messages"][-1]["text"]


@pytest.mark.parametrize("pedido", [
    "Como desfazer a última alteração?",
    "Posso desfazer a última alteração?",
    "Não desfaça a última alteração.",
    "Não quero desfazer a última alteração.",
    "Explique sem desfazer a última alteração.",
])
def test_pergunta_ou_negacao_de_undo_nao_executa(monkeypatch, pedido):
    sessao, bucket, chamadas_motor = _sessao_com_alteracao(monkeypatch)
    alteracoes = copy.deepcopy(bucket["changes"])

    assert govbot_panel._processar_evento(sessao, bucket, _evento(
        request_id="regressao-undo-nao-confirmado", text=pedido,
        focus="justificativa", draft={"justificativa": "Texto revisado"},
    )) is False

    assert sessao["dados"]["justificativa"] == "Texto revisado"
    assert bucket["changes"] == alteracoes
    assert chamadas_motor == []


def test_primeiro_autosave_reindexa_bucket_sem_perder_historico(monkeypatch):
    sessao = _sessao()
    bucket = govbot.obter_bucket(sessao)
    raiz = sessao[govbot.CHAVE_SESSAO]
    chave_local = raiz["current_bucket"]
    UUID(chave_local.removeprefix("local:"))
    govbot.adicionar_mensagem(bucket, "user", "Histórico antes do autosave")
    proposta = govbot.criar_proposta_campo(
        "justificativa", "Original", "Texto revisado", "Clareza")
    govbot.guardar_proposta(bucket, proposta)
    contexto = govbot.montar_contexto_minimo(
        dados=sessao["dados"], foco="justificativa")
    govbot_panel._anotar_proposta(sessao, bucket, govbot.GovBotReply(
        "regressao-proposta-save", "Sugestão", "SUGGESTION", proposal=proposta,
    ), contexto, "Substitua por Texto revisado")
    chamadas_save = []

    def primeiro_save():
        chamadas_save.append(True)
        sessao["processo_id"] = "processo-criado-no-autosave"
        sessao["_save_status"] = "salvo"

    monkeypatch.setattr(state, "autosalvar", primeiro_save)
    monkeypatch.setattr(state, "invalidar_a_partir_de", lambda _origem: None)

    assert govbot_panel._processar_evento(sessao, bucket, _evento(
        request_id="regressao-aplicar-primeiro-save",
        event_type="apply_proposal", text="", focus="justificativa",
        proposal_id=proposta.proposal_id, draft={"justificativa": "Original"},
    )) is True

    chave_salva = "processo:processo-criado-no-autosave"
    assert raiz["current_bucket"] == chave_salva
    assert raiz["buckets"][chave_salva] is bucket
    assert chave_local not in raiz["buckets"]
    assert raiz["local_process_id"] is None
    assert bucket["messages"][0]["text"] == "Histórico antes do autosave"
    assert len(bucket["changes"]) == 1
    assert bucket["changes"][0]["persistence"] == "saved"
    assert bucket["form_draft"]["justificativa"] == "Texto revisado"
    assert govbot.obter_bucket(sessao, sessao["processo_id"]) is bucket
    assert chamadas_save == [True]


def test_undo_restaura_draft_de_campo_ainda_nao_canonico(monkeypatch):
    sessao = _sessao(dados={"justificativa": "Original"})
    bucket = govbot.obter_bucket(sessao)
    digitado = "texto digitado"
    aprimorado = "texto digitado com maior clareza"
    govbot.guardar_rascunho(sessao, {"objeto": digitado})
    contexto = govbot_panel._montar_contexto(
        sessao, "objeto", evidencias=False)
    assert contexto.valor_atual == digitado
    assert "objeto" not in sessao["dados"]
    proposta = govbot.criar_proposta_campo(
        "objeto", contexto.valor_atual, aprimorado, "Clareza")
    govbot.guardar_proposta(bucket, proposta)
    govbot_panel._anotar_proposta(sessao, bucket, govbot.GovBotReply(
        "regressao-proposta-draft", "Sugestão", "SUGGESTION", proposal=proposta,
    ), contexto, "Melhore o texto digitado")
    monkeypatch.setattr(state, "invalidar_a_partir_de", lambda _origem: None)
    monkeypatch.setattr(state, "autosalvar", lambda: sessao.update({
        "_save_status": "local"}))
    monkeypatch.setattr(govbot_panel, "_sessao", lambda: sessao)
    monkeypatch.setattr(govbot, "ativo", lambda: True)

    assert govbot_panel._processar_evento(sessao, bucket, _evento(
        request_id="regressao-aplicar-draft-nao-canonico",
        event_type="apply_proposal", text="", focus="objeto",
        proposal_id=proposta.proposal_id, draft={"objeto": digitado},
    )) is True
    assert sessao["dados"]["objeto"] == aprimorado

    assert govbot_panel._processar_evento(sessao, bucket, _evento(
        request_id="regressao-undo-draft-nao-canonico",
        event_type="undo", text="", focus="objeto",
        draft={"objeto": aprimorado},
    )) is True

    assert "objeto" not in sessao["dados"]
    assert sessao[govbot.CHAVE_RASCUNHO]["objeto"] == digitado
    assert bucket["form_draft"]["objeto"] == digitado
    assert bucket["_widget_hydration"]["objeto"] == digitado
    assert bucket["changes"] == []
    assert govbot_panel.preparar_sessao() is bucket
    assert sessao["govbot_campo_objeto"] == digitado


def test_prompt_recebe_historico_recente_sem_papeis_system():
    sessao = _sessao()
    bucket = govbot.obter_bucket(sessao)
    for indice in range(10):
        govbot.adicionar_mensagem(
            bucket, "user" if indice % 2 == 0 else "assistant",
            f"Mensagem anterior {indice}")
    govbot.adicionar_mensagem(bucket, "system", "SYSTEM_NAO_DEVE_IR_AO_MODELO")
    anteriores = copy.deepcopy(bucket["messages"])
    esperado = [
        {"role": item["role"], "text": item["text"]}
        for item in anteriores[-8:]
        if item["role"] in ("user", "assistant")
    ]
    contexto = govbot.montar_contexto_minimo(
        dados=sessao["dados"], foco="justificativa")
    prompts = []

    def motor(system, user, **_kwargs):
        prompts.append((system, json.loads(user)))
        return json.dumps({
            "intent": "explain_current", "response": "Resposta contextual.",
            "target": "justificativa", "payload": {}, "sources": [],
        })

    pedido = "Desenvolva a explicação anterior"
    govbot.processar_mensagem(govbot.parsear_evento(_evento(
        request_id="regressao-historico-prompt", text=pedido,
        focus="justificativa",
    )), contexto, bucket, motor)

    assert len(prompts) == 1
    system, payload = prompts[0]
    assert payload["historico"] == esperado
    assert payload["pedido"] == pedido
    assert all(item["role"] in ("user", "assistant")
               for item in payload["historico"])
    assert "SYSTEM_NAO_DEVE_IR_AO_MODELO" not in system
    assert "SYSTEM_NAO_DEVE_IR_AO_MODELO" not in json.dumps(payload)
    assert "Mensagem anterior 0" not in json.dumps(payload)
    assert all(item["text"] != pedido for item in payload["historico"])


def _fato_de_prazo(**mudancas):
    fato = governanca.novo_fato(
        None, "prazo.descricao", "Prazo de 45 dias", "texto",
        "formulario:prazo", confianca=0.9)
    fato.update(mudancas)
    return fato


@pytest.mark.parametrize("mudancas", [
    {"fonte": "inferencia:prazo", "confianca": 1.0},
    {"inferido": True},
    {"fonte": "texto_nao_validado:rascunho"},
    {"status": "disputado"},
    {"status": "substituido"},
    {"status": None},
    {"vigente": False},
    {"vigente": "false"},
    {"confianca": 0.6},
    {"confianca": float("nan")},
    {"confianca": float("inf")},
    {"fonte": None, "source_id": "formulario:prazo"},
    {"versao": None},
])
def test_fato_sem_autoridade_nao_vira_lastro_material(mudancas):
    evidencia = [_fato_de_prazo(**mudancas)]

    with pytest.raises(govbot.ErroValorMaterial):
        govbot.validar_valores_materiais("Prazo de 45 dias", fatos=evidencia)
    with pytest.raises(govbot.ErroValorMaterial):
        govbot.validar_decisao_ou_identificacao(
            "prazo", "45 dias", fatos=evidencia)


def test_fato_sem_metadados_nao_tem_proveniencia_validada():
    with pytest.raises(govbot.ErroValorMaterial):
        govbot.validar_valores_materiais(
            "Prazo de 45 dias", fatos=[{"valor": "Prazo de 45 dias"}])


def test_inferencia_real_nao_canoniza_exigencia_de_garantia():
    dados = {
        "objeto": "Avaliar alternativas de garantia contratual",
        "justificativa": "Necessidade administrativa",
    }
    extraidos = fatos.extrair_do_formulario(dados)
    inferencia = next(f for f in extraidos
                      if f["path"] == "contratacao.garantia_exigida")
    assert inferencia["fonte"] == "inferencia:requisitos"
    assert inferencia["status"] == "extraido"
    assert inferencia["confianca"] == 0.6
    assert "inferido" not in inferencia
    sessao = _sessao(dados=dados)
    bucket = govbot.obter_bucket(sessao)
    antes = copy.deepcopy(sessao)
    proposta = govbot.criar_proposta_campo(
        "justificativa", dados["justificativa"],
        "Será exigida garantia contratual.", "Clareza")

    with pytest.raises(govbot.ErroValorMaterial):
        govbot.aplicar_campo_escalar(
            sessao, bucket, proposta, "regressao-garantia-inferida",
            pedido="Melhore a justificativa", fatos=extraidos)

    assert sessao == antes
    assert bucket["changes"] == []


@pytest.mark.parametrize("status", ["extraido", "confirmado"])
def test_metrica_interna_nunca_autoriza_quantidade_administrativa(status):
    extraidos = fatos.extrair_do_formulario({"objeto": "Aquisição de notebook"})
    metrica = next(f for f in extraidos
                   if f["path"] == "objeto.categoria_evidencia")
    metrica["status"] = status
    assert metrica["valor"] == 3.0

    with pytest.raises(govbot.ErroValorMaterial):
        govbot.validar_valores_materiais(
            "Serão analisadas 3 alternativas.", pedido="Melhore a análise",
            fatos=extraidos)


@pytest.mark.parametrize("path", [
    "objeto.categoria_evidencia", "OBJETO.CATEGORIA_EVIDENCIA",
    " objeto.categoria_evidencia ",
])
def test_metrica_confirmada_nao_ganha_autoridade_por_alias_de_path(path):
    metrica = governanca.novo_fato(
        None, "objeto.categoria_evidencia", 3, "numero", "formulario:objeto",
        status="confirmado", confianca=1.0)
    metrica["path"] = path
    with pytest.raises(govbot.ErroValorMaterial):
        govbot.validar_valores_materiais("Analisar 3 alternativas", fatos=[metrica])


def test_fatos_estruturados_reais_e_confirmacao_explicita_continuam_validos():
    extraidos = fatos.extrair_do_formulario({
        "objeto": "Aquisição de cadeiras",
        "orgao": "Prefeitura de Teste",
        "prazo": "Prazo de 30 dias",
        "requisitos": "Não será exigida garantia contratual.",
        "itens": [{"descricao": "Cadeira", "quantidade": 40}],
    })
    govbot.validar_valores_materiais(
        "Entrega em trinta dias de 40 unidades.", fatos=extraidos)
    govbot.validar_valores_materiais(
        "Não será exigida garantia contratual.", fatos=extraidos)
    govbot.validar_decisao_ou_identificacao(
        "orgao", "Prefeitura de Teste", fatos=extraidos)

    confirmado = _fato_de_prazo(
        fonte="inferencia:prazo", status="confirmado", confianca=0.6)
    govbot.validar_valores_materiais("Prazo de 45 dias", fatos=[confirmado])
    govbot.validar_decisao_ou_identificacao(
        "prazo", "45 dias", fatos=[confirmado])
    garantia = governanca.novo_fato(
        None, "contratacao.garantia_exigida", True, "booleano",
        "inferencia:requisitos", status="confirmado", confianca=0.6)
    govbot.validar_valores_materiais(
        "Será exigida garantia contratual.", fatos=[garantia])


@pytest.mark.parametrize("estado_atual", [
    {"status": "disputado"},
    {"status": "substituido"},
    {"fonte": "inferencia:prazo"},
    {"vigente": False},
])
def test_fato_atual_recusado_nao_ressuscita_versao_anterior(estado_atual):
    antigo = _fato_de_prazo(status="confirmado")
    atual = _fato_de_prazo(valor="Prazo de 90 dias", versao=2, **estado_atual)

    for texto in ("Prazo de 45 dias", "Prazo de 90 dias"):
        with pytest.raises(govbot.ErroValorMaterial):
            govbot.validar_valores_materiais(texto, fatos=[antigo, atual])


def test_fatos_usam_apenas_versao_mais_nova_inequivoca():
    antigo = _fato_de_prazo(status="confirmado")
    atual = _fato_de_prazo(valor="Prazo de 90 dias", versao=2)
    with pytest.raises(govbot.ErroValorMaterial):
        govbot.validar_valores_materiais("Prazo de 45 dias", fatos=[antigo, atual])
    govbot.validar_valores_materiais("Prazo de 90 dias", fatos=[antigo, atual])

    contraditorio = _fato_de_prazo(valor="Prazo de 60 dias", versao=2)
    for texto in ("Prazo de 60 dias", "Prazo de 90 dias"):
        with pytest.raises(govbot.ErroValorMaterial):
            govbot.validar_valores_materiais(
                texto, fatos=[antigo, atual, contraditorio])


def test_versao_malformada_nao_reabilita_fato_antigo():
    antigo = _fato_de_prazo(status="confirmado")
    sem_versao = _fato_de_prazo(valor="Prazo de 90 dias", versao=None)
    with pytest.raises(govbot.ErroValorMaterial):
        govbot.validar_valores_materiais(
            "Prazo de 45 dias", fatos=[antigo, sem_versao])


def test_fontes_contextuais_nao_reintroduzem_fatos_recusados():
    extraidos = fatos.extrair_do_formulario({
        "objeto": "Avaliar garantia contratual de notebook",
        "prazo": "Prazo de 30 dias",
    })
    contexto = govbot.GovBotContext(
        None, 0, fatos_relevantes=tuple(extraidos),
        decisoes_conhecimento=({"sourceIds": [
            "inferencia:requisitos", "fato:contratacao.garantia_exigida",
            "fato:objeto.categoria_evidencia", "norma:lei-validada",
        ]},),
        achados=({"sourceIds": [
            "inferencia:objeto+itens", "fato:prazo.descricao",
        ]},),
        referencias_rag=({"source_id": "rag:referencia-validada:1"},),
    )
    fontes = govbot.fontes_validadas_do_contexto(contexto)

    assert "formulario:prazo" in fontes
    assert "fato:prazo.descricao" in fontes
    assert "norma:lei-validada" in fontes
    assert "rag:referencia-validada:1" in fontes
    assert not any(fonte.startswith("inferencia") for fonte in fontes)
    assert "fato:contratacao.garantia_exigida" not in fontes
    assert "fato:objeto.categoria_evidencia" not in fontes


@pytest.mark.parametrize("path_fato,novo_valor,permitido", [
    ("objeto.categoria_evidencia", "Serão analisadas 3 alternativas.", False),
    ("itens[0].quantidade", "Aquisição de 40 unidades.", True),
])
def test_correcao_nao_perde_proveniencia_ao_resolver_fato_em_fonte(
    monkeypatch, path_fato, novo_valor, permitido,
):
    documento = "# 1. ANÁLISE\n\nAnálise pendente."
    sessao = _sessao(
        dados={"objeto": "Aquisição de notebook", "itens": [
            {"descricao": "Notebook", "quantidade": 40},
        ]}, documentos={"dfd": documento}, etapa=1)
    bucket = govbot.obter_bucket(sessao)
    bloco = blocos.dividir_em_blocos("dfd", documento)[1]
    snapshot = blocos.snapshot_bundle(sessao["documentos"])
    source_id = f"fato:{path_fato}"
    finding = {
        "findingId": "F_PROVENIENCIA", "documentId": "dfd",
        "descricao": "Aprimorar análise", "regraViolada": "clareza",
        "resultadoEsperado": "Análise completa", "evidencia": [],
        "autoCorrectable": True, "allowedPaths": [bloco["path"]],
        "blockedPaths": [], "sourceIds": [source_id], "blockingReason": None,
    }
    relatorio = {
        "auditId": "auditoria-proveniencia", "bundleId": "bundle-proveniencia",
        "bundleVersion": 1, "bundleHash": snapshot["hash"],
        "status": "CORRECTIONS_REQUIRED", "findings": [finding],
        "summary": "teste", "model": "deterministico",
        "createdAt": "2026-09-03T00:00:00+00:00",
    }
    plano = {
        "patchPlanId": "plano-proveniencia", "bundleId": relatorio["bundleId"],
        "sourceBundleVersion": 1, "sourceBundleHash": snapshot["hash"],
        "operations": [{
            "operationId": "OP_PROVENIENCIA", "findingId": finding["findingId"],
            "documentId": "dfd", "op": "replace", "path": bloco["path"],
            "expectedOldHash": bloco["hash"], "newValue": novo_valor,
            "sourceIds": [source_id], "reason": "Clareza",
            "expectedImpact": "Análise aprimorada",
        }],
        "unresolvedFindings": [], "createdAt": "2026-09-03T00:00:00+00:00",
    }
    monkeypatch.setattr(achados, "gerar_relatorio", lambda *_a, **_k: relatorio)
    monkeypatch.setattr(corretor, "gerar_plano", lambda *_a, **_k: plano)

    if permitido:
        resposta = govbot.corrigir_achado(
            sessao, bucket, finding["findingId"], "regressao-fonte-autoritativa",
            max_proporcao_blocos=1.0)
        assert resposta.applied is True
        assert novo_valor in sessao["documentos"]["dfd"]
    else:
        antes = copy.deepcopy(sessao)
        with pytest.raises(govbot.ErroValorMaterial):
            govbot.corrigir_achado(
                sessao, bucket, finding["findingId"], "regressao-fonte-inferida",
                max_proporcao_blocos=1.0)
        assert sessao == antes
