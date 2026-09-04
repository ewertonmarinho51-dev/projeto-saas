"""Regressões de identidade e consentimento na fronteira real do GovBot."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from src import auth, db, govbot, llm, state
from src.ui import govbot_panel


class _Sessao(dict):
    def __getattr__(self, nome):
        try:
            return self[nome]
        except KeyError as erro:
            raise AttributeError(nome) from erro

    def __setattr__(self, nome, valor):
        self[nome] = valor


def _usuario(**mudancas):
    usuario = {
        "id": "usuario-antigo", "auth_user_id": "auth-antigo",
        "login": "login-antigo", "tenant_id": "tenant-antigo",
        "secretaria_id": "secretaria-antiga", "papel": "usuario",
    }
    usuario.update(mudancas)
    return usuario


def _sessao(**mudancas):
    sessao = _Sessao({
        "usuario": _usuario(), "tenant_id": "tenant-antigo",
        "dados": {"objeto": "Aquisição de cadeiras",
                  "justificativa": "Texto original da necessidade."},
        "documentos": {}, "aprovados": set(), "edicoes_pendentes": {},
        "etapa": 0, "processo_id": None, "_save_status": "local",
        "preferencia_visual": "preservar",
    })
    sessao.update(mudancas)
    return sessao


@pytest.fixture(autouse=True)
def _sem_servicos_externos(monkeypatch):
    def proibido(*_args, **_kwargs):
        pytest.fail("regressão tentou acessar banco ou motor real")

    monkeypatch.setattr(db, "_cliente", proibido)
    monkeypatch.setattr(db, "cliente_do_usuario", proibido)
    monkeypatch.setattr(db, "salvar_processo", proibido)
    monkeypatch.setattr(llm, "chamar_ia_texto", proibido)


def _conectar_sessao(monkeypatch, sessao, *, ativo=True):
    monkeypatch.setattr(auth, "st", SimpleNamespace(session_state=sessao))
    monkeypatch.setattr(govbot_panel, "_sessao", lambda: sessao)
    monkeypatch.setattr(govbot, "ativo", lambda: ativo)


def _popular_estado_sensivel(sessao):
    segredo = "COPIA-EFEMERA-IDENTIDADE-ANTIGA"
    local = govbot.obter_bucket(sessao)
    chave_local = sessao[govbot.CHAVE_SESSAO]["current_bucket"]
    govbot.adicionar_mensagem(local, "user", segredo + " local")
    govbot.guardar_rascunho(sessao, {"objeto": segredo + " local draft"})
    salvo = govbot.obter_bucket(sessao, "processo-compartilhado")
    sessao["processo_id"] = "processo-compartilhado"
    govbot.adicionar_mensagem(salvo, "assistant", segredo + " salvo")
    salvo["changes"] = [{"snapshot": {"dados": {"objeto": segredo}}}]
    salvo["proposals"] = {"proposta-antiga": {"after": segredo}}
    salvo["results"] = {"request-antigo": {"response": segredo}}
    salvo["processed_ids"] = ["request-antigo"]
    salvo["_widget_hydration"] = {"objeto": segredo + " hydration"}
    salvo["_last_focus"] = "objeto"
    govbot.guardar_rascunho(sessao, {
        "objeto": segredo + " flat draft", "editor_dfd": segredo + " editor",
    })
    sessao.update({
        "govbot_campo_objeto": segredo + " widget",
        "editor_dfd": segredo + " widget editor",
        "edicoes_pendentes": {"dfd": segredo + " pending"},
        "_rag_trace": {"dfd": {"referencias": [{"trecho": segredo}]}},
        "_decisao_cache": {"decisao": {"justificativa": segredo}},
    })
    return sessao[govbot.CHAVE_SESSAO], local, salvo, chave_local, segredo


def _assert_copias_revogadas(sessao, raiz_antiga, local, salvo, segredo):
    assert raiz_antiga == {}
    assert local == {}
    assert salvo == {}
    assert not any(str(chave).startswith(("govbot_campo_", "editor_"))
                   for chave in sessao)
    assert "edicoes_pendentes" not in sessao
    assert "_rag_trace" not in sessao
    assert "_decisao_cache" not in sessao
    assert segredo not in json.dumps(sessao, default=list, ensure_ascii=False)
    assert sessao["preferencia_visual"] == "preservar"


def test_sair_e_entrar_reais_revogam_buckets_e_nao_reidratam_outro_usuario(
    monkeypatch,
):
    sessao = _sessao()
    raiz, local, salvo, chave_local, segredo = _popular_estado_sensivel(sessao)
    _conectar_sessao(monkeypatch, sessao)

    auth.sair()

    assert govbot.CHAVE_SESSAO not in sessao
    assert govbot.CHAVE_RASCUNHO not in sessao
    _assert_copias_revogadas(sessao, raiz, local, salvo, segredo)
    assert sessao["usuario"] is None
    assert sessao["tenant_id"] is None
    assert sessao[db.CHAVE_DA_SESSAO] == ""
    assert sessao["dados"] == sessao["documentos"] == {}

    auth.entrar(_usuario(
        id="usuario-novo", auth_user_id="auth-novo", login="login-novo",
        tenant_id="tenant-novo", secretaria_id="secretaria-nova",
        _token="token-falso-novo",
    ))
    sessao["processo_id"] = "processo-compartilhado"
    novo = govbot_panel.preparar_sessao()

    assert novo is not local and novo is not salvo
    assert novo["messages"] == novo["changes"] == []
    assert novo["proposals"] == novo["form_draft"] == {}
    assert sessao[govbot.CHAVE_RASCUNHO] == {}
    assert chave_local not in sessao[govbot.CHAVE_SESSAO]["buckets"]
    assert sessao[db.CHAVE_DA_SESSAO] == "token-falso-novo"
    assert "_token" not in sessao["usuario"]
    _assert_copias_revogadas(sessao, raiz, local, salvo, segredo)


def test_entrar_real_com_outra_identidade_invalida_estado_na_proxima_montagem(
    monkeypatch,
):
    sessao = _sessao()
    raiz, local, salvo, _chave, segredo = _popular_estado_sensivel(sessao)
    _conectar_sessao(monkeypatch, sessao)

    auth.entrar(_usuario(id="usuario-novo", auth_user_id="auth-novo"))
    novo = govbot_panel.preparar_sessao()

    assert novo["messages"] == []
    assert novo["form_draft"] == {}
    _assert_copias_revogadas(sessao, raiz, local, salvo, segredo)


@pytest.mark.parametrize("chave", [
    "id", "auth_user_id", "login", "tenant_id", "secretaria_id", "tenant_sessao",
])
def test_troca_direta_de_usuario_tenant_ou_secretaria_revoga_copias(
    monkeypatch, chave,
):
    sessao = _sessao()
    raiz, local, salvo, chave_local, segredo = _popular_estado_sensivel(sessao)
    _conectar_sessao(monkeypatch, sessao)
    if chave == "tenant_sessao":
        sessao["tenant_id"] = "tenant-direto-novo"
    else:
        sessao["usuario"][chave] = "vinculo-direto-novo"

    novo = govbot_panel.preparar_sessao()

    assert novo is not salvo and novo is not local
    assert novo["messages"] == novo["changes"] == []
    assert novo["proposals"] == novo["results"] == novo["form_draft"] == {}
    assert novo["processed_ids"] == []
    assert "_widget_hydration" not in novo
    assert sessao[govbot.CHAVE_RASCUNHO] == {}
    assert chave_local not in sessao[govbot.CHAVE_SESSAO]["buckets"]
    _assert_copias_revogadas(sessao, raiz, local, salvo, segredo)


def test_mesma_identidade_e_processo_preservam_bucket_mesmo_com_token_novo(
    monkeypatch,
):
    sessao = _sessao()
    raiz, local, salvo, chave_local, segredo = _popular_estado_sensivel(sessao)
    _conectar_sessao(monkeypatch, sessao)
    antes = copy.deepcopy(salvo)

    auth.entrar(_usuario(_token="token-falso-renovado"))
    atual = govbot.obter_bucket(sessao, "processo-compartilhado")

    assert atual is salvo
    assert sessao[govbot.CHAVE_SESSAO] is raiz
    assert raiz["buckets"][chave_local] is local
    assert atual == antes
    assert sessao[govbot.CHAVE_RASCUNHO] == antes["form_draft"]
    assert segredo in sessao["govbot_campo_objeto"]
    assert sessao["_rag_trace"] and sessao["_decisao_cache"]


def test_guardar_rascunho_apos_troca_preserva_a_captura_nova_e_revoga_a_antiga():
    sessao = _sessao()
    raiz, local, salvo, _chave, segredo = _popular_estado_sensivel(sessao)
    sessao["usuario"]["id"] = "usuario-novo"
    novo_draft = {"objeto": "Captura nova enviada por esta identidade"}

    resultado = govbot.guardar_rascunho(sessao, novo_draft)

    assert resultado == novo_draft
    assert sessao[govbot.CHAVE_RASCUNHO] == novo_draft
    assert sessao[govbot.CHAVE_SESSAO] is not raiz
    _assert_copias_revogadas(sessao, raiz, local, salvo, segredo)


def test_logout_com_flag_off_nao_cria_chaves_govbot(monkeypatch):
    sessao = _sessao()
    _conectar_sessao(monkeypatch, sessao, ativo=False)

    auth.sair()

    assert not any(str(chave).startswith("govbot") for chave in sessao)
    assert sessao["usuario"] is None
    assert sessao[db.CHAVE_DA_SESSAO] == ""
    assert govbot_panel.preparar_sessao() is None
    assert not any(str(chave).startswith("govbot") for chave in sessao)


PEDIDOS_SEM_CONFIRMACAO = [
    "Melhore e aplique a justificativa?",
    "Posso pedir que você melhore e aplique a justificativa?",
    'Explique a frase "Melhore e aplique a justificativa".',
    "“Melhore e aplique a justificativa”",
    "Melhore a frase «melhore e aplique».",
    "Melhore e aplique significa o que",
    "Melhore e aplique 'a justificativa'.",
    "Se eu confirmar, melhore e aplique a justificativa.",
    "Melhore e aplique a justificativa quando eu confirmar.",
    "Melhore o texto e aplique depois da minha confirmacao.",
    "Caso seja adequado, melhore e aplique a justificativa.",
    "Talvez melhore e aplique a justificativa.",
    "Não melhore e aplique a justificativa.",
    "Melhore a justificativa sem aplicar.",
    "Sugira uma melhoria para a justificativa.",
]


def _preparar_painel_com_modelo_controlado(monkeypatch):
    sessao = _sessao()
    bucket = govbot.obter_bucket(sessao)
    chamadas = {"modelo": [], "invalidacao": [], "save": []}
    depois = "Texto revisado da necessidade com maior clareza."

    def motor(system, user, **kwargs):
        chamadas["modelo"].append((system, json.loads(user), kwargs))
        return json.dumps({
            "intent": "suggest_field", "response": "Sugestão para revisão.",
            "target": "justificativa",
            "payload": {"value": depois, "reason": "Maior clareza."},
            "sources": [],
        })

    def salvar():
        chamadas["save"].append(True)
        sessao["_save_status"] = "local"

    monkeypatch.setattr(llm, "chamar_ia_texto", motor)
    monkeypatch.setattr(state, "invalidar_a_partir_de",
                        lambda origem: chamadas["invalidacao"].append(origem))
    monkeypatch.setattr(state, "autosalvar", salvar)
    return sessao, bucket, chamadas, depois


def _evento_mensagem(pedido):
    return {
        "request_id": "identidade-confirmacao-evento", "event_type": "message",
        "text": pedido, "focus": "justificativa", "proposal_id": None,
        "draft": {"justificativa": "Texto original da necessidade."},
    }


@pytest.mark.parametrize("pedido", PEDIDOS_SEM_CONFIRMACAO)
def test_dispatcher_real_mantem_pergunta_citacao_e_condicional_em_preview(
    monkeypatch, pedido,
):
    sessao, bucket, chamadas, depois = _preparar_painel_com_modelo_controlado(
        monkeypatch)
    dados_antes = copy.deepcopy(sessao["dados"])

    mutou = govbot_panel._processar_evento(
        sessao, bucket, _evento_mensagem(pedido))

    assert mutou is False
    assert sessao["dados"] == dados_antes
    assert bucket["changes"] == []
    assert chamadas["invalidacao"] == chamadas["save"] == []
    assert len(chamadas["modelo"]) == 1
    assert chamadas["modelo"][0][1]["pedido"] == pedido
    assert len(bucket["proposals"]) == 1
    proposta = next(iter(bucket["proposals"].values()))
    assert proposta["after"] == depois
    assert bucket["_ui_state"] == "SUGGESTION"
    assert [mensagem["role"] for mensagem in bucket["messages"]] == [
        "user", "assistant"]


def test_dispatcher_real_aplica_suggest_field_so_com_melhore_e_aplique(
    monkeypatch,
):
    sessao, bucket, chamadas, depois = _preparar_painel_com_modelo_controlado(
        monkeypatch)

    assert govbot_panel._processar_evento(sessao, bucket, _evento_mensagem(
        "Melhore e aplique a justificativa.")) is True

    assert sessao["dados"]["justificativa"] == depois
    assert len(bucket["changes"]) == 1
    assert bucket["changes"][0]["action"] == "replace_form_field"
    assert chamadas["invalidacao"] == ["formulario"]
    assert chamadas["save"] == [True]
    assert len(chamadas["modelo"]) == 1
    assert "somente nesta sessão" in bucket["messages"][-1]["text"]


FAMILIAS_DE_APLICACAO = (
    "suggest_field", "replace_form_field", "suggest_section_patch",
    "apply_section_patch", "fix_finding",
)


def _intencao(acao, *, alvo=True, valor=True):
    if acao == "fix_finding":
        target, payload = "ACHADO001", {"apply_now": True}
    elif acao in ("suggest_field", "replace_form_field"):
        target = "justificativa"
        payload = {"value": "Texto completo" if valor else ""}
    else:
        target = "dfd/clausula/1/1"
        payload = {"new_value": "Texto completo" if valor else ""}
    return govbot.GovBotIntent(acao, "Sugestão", target if alvo else None, payload)


@pytest.mark.parametrize("acao", FAMILIAS_DE_APLICACAO)
@pytest.mark.parametrize("pedido", PEDIDOS_SEM_CONFIRMACAO)
def test_guard_das_cinco_familias_rejeita_mencao_sem_autorizacao(acao, pedido):
    assert govbot.deve_aplicar_imediatamente(pedido, _intencao(acao)) is False


@pytest.mark.parametrize("acao", FAMILIAS_DE_APLICACAO)
@pytest.mark.parametrize("pedido", [
    "Melhore e aplique o texto.", "Por favor, melhore e aplique o texto.",
    "Substitua o texto e aplique.", "Corrija o texto e aplique.",
])
def test_guard_das_cinco_familias_preserva_imperativos_explicitos(acao, pedido):
    assert govbot.deve_aplicar_imediatamente(pedido, _intencao(acao)) is True


@pytest.mark.parametrize("acao", FAMILIAS_DE_APLICACAO)
def test_guard_exige_alvo_completo_em_todas_as_familias(acao):
    assert not govbot.deve_aplicar_imediatamente(
        "Melhore e aplique", _intencao(acao, alvo=False))


@pytest.mark.parametrize("acao", FAMILIAS_DE_APLICACAO[:-1])
def test_guard_exige_valor_completo_para_campo_e_bloco(acao):
    assert not govbot.deve_aplicar_imediatamente(
        "Melhore e aplique", _intencao(acao, valor=False))


@pytest.mark.parametrize("acao", [
    "explain_current", "explain_finding", "undo_last_change",
    "show_missing_information", "compare_with_previous_document",
])
def test_guard_de_aplicacao_nao_promove_intencoes_nao_mutaveis(acao):
    intent = govbot.GovBotIntent(
        acao, "Resposta", "justificativa", {"value": "Texto completo"})
    assert not govbot.deve_aplicar_imediatamente("Melhore e aplique", intent)


@pytest.mark.parametrize("pedido,esperado", [
    ("Desfaça a última alteração.", True),
    ("Como desfazer a última alteração?", False),
    ("Não desfaça a última alteração.", False),
])
def test_controles_existentes_de_undo_continuam_separados(pedido, esperado):
    intent = govbot.GovBotIntent("undo_last_change", "Desfazer")
    assert govbot.deve_desfazer_imediatamente(pedido, intent) is esperado
