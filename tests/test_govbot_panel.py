"""Provas da fronteira Streamlit entre o wizard e o núcleo GovBot."""

from __future__ import annotations

import ast
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src import govbot
from src.ui import govbot_panel


def _sessao(**mudancas):
    base = {
        "dados": {"objeto": "Aquisição de cadeiras"},
        "documentos": {},
        "aprovados": set(),
        "edicoes_pendentes": {},
        "etapa": 0,
        "processo_id": None,
        "_save_status": "local",
    }
    base.update(mudancas)
    return base


def test_preparar_com_flag_off_nao_cria_estado(monkeypatch):
    sessao = _sessao()
    inicial = set(sessao)
    monkeypatch.setattr(govbot_panel, "_sessao", lambda: sessao)
    monkeypatch.setattr(govbot, "ativo", lambda: False)

    assert govbot_panel.preparar_sessao() is None
    assert set(sessao) == inicial
    assert govbot.CHAVE_SESSAO not in sessao
    assert govbot.CHAVE_RASCUNHO not in sessao


def test_preparar_reidrata_apenas_widgets_reconhecidos(monkeypatch):
    sessao = _sessao()
    bucket = govbot.obter_bucket(sessao)
    govbot.guardar_rascunho(sessao, {
        "objeto": "Texto ainda não enviado",
        "editor_dfd": "Documento ainda não aprovado",
    })
    bucket["_widget_hydration"] = {"prazo": "30 dias"}
    monkeypatch.setattr(govbot_panel, "_sessao", lambda: sessao)
    monkeypatch.setattr(govbot, "ativo", lambda: True)

    assert govbot_panel.preparar_sessao() is bucket
    assert sessao["govbot_campo_objeto"] == "Texto ainda não enviado"
    assert sessao["govbot_campo_prazo"] == "30 dias"
    assert sessao["editor_dfd"] == "Documento ainda não aprovado"
    assert "govbot_campo_itens" not in sessao


def test_preparar_nao_sobrescreve_valor_mais_novo_do_widget(monkeypatch):
    sessao = _sessao()
    bucket = govbot.obter_bucket(sessao)
    govbot.guardar_rascunho(sessao, {"objeto": "captura anterior"})
    sessao["govbot_campo_objeto"] = "valor novo enviado pelo browser"
    monkeypatch.setattr(govbot_panel, "_sessao", lambda: sessao)
    monkeypatch.setattr(govbot, "ativo", lambda: True)

    assert govbot_panel.preparar_sessao() is bucket
    assert sessao["govbot_campo_objeto"] == \
        "valor novo enviado pelo browser"


def test_fila_de_hidratacao_explicitamente_atualiza_widget(monkeypatch):
    sessao = _sessao()
    bucket = govbot.obter_bucket(sessao)
    sessao["govbot_campo_objeto"] = "valor anterior"
    bucket["_widget_hydration"] = {"objeto": "valor aplicado"}
    monkeypatch.setattr(govbot_panel, "_sessao", lambda: sessao)
    monkeypatch.setattr(govbot, "ativo", lambda: True)

    govbot_panel.preparar_sessao()

    assert sessao["govbot_campo_objeto"] == "valor aplicado"
    assert sessao[govbot.CHAVE_RASCUNHO]["objeto"] == "valor aplicado"


def test_resolucao_de_bloco_so_escolhe_alvo_inequivoco():
    documento = (
        "# 1. OBJETO\n\nCadeiras para as unidades.\n\n"
        "# 2. JUSTIFICATIVA\n\nSubstituir mobiliário danificado."
    )
    assert govbot_panel._bloco_do_pedido(
        "dfd", documento, "Melhore a justificativa") == \
        "dfd/clausula/2/1"
    assert govbot_panel._bloco_do_pedido(
        "dfd", documento, "Melhore este documento") is None


def test_evento_de_conversa_guarda_draft_sem_mudar_dados():
    sessao = _sessao()
    bucket = govbot.obter_bucket(sessao)
    evento = {
        "request_id": "request-local-001",
        "event_type": "message",
        "text": "Onde estou?",
        "focus": "objeto",
        "proposal_id": None,
        "draft": {"objeto": "Texto digitado, ainda não enviado"},
    }

    assert govbot_panel._processar_evento(sessao, bucket, evento) is False
    assert sessao["dados"]["objeto"] == "Aquisição de cadeiras"
    assert sessao[govbot.CHAVE_RASCUNHO]["objeto"].startswith("Texto digitado")
    assert [mensagem["role"] for mensagem in bucket["messages"]] == [
        "user", "assistant"]


def test_versao_proativa_reflete_escalares_inclusive_draft():
    sessao = _sessao()
    bucket = govbot.obter_bucket(sessao)
    primeira = govbot_panel._view_model(sessao, bucket)["form_version"]
    govbot.guardar_rascunho(sessao, {"objeto": "Nova versão não enviada"})
    segunda = govbot_panel._view_model(sessao, bucket)["form_version"]

    assert primeira != segunda


def test_fonte_rag_autoriza_apenas_o_conteudo_do_source_id():
    contexto = govbot.GovBotContext(
        processo_id=None, etapa=0,
        referencias_rag=({
            "source_id": "rag:doc-1:0",
            "documento_id": "doc-1",
            "trecho": "Prazo confirmado de 45 dias.",
        },),
    )
    valores = govbot_panel._valores_de_fontes(
        contexto, ["rag:doc-1:0"])
    govbot.validar_valores_materiais(
        "Prazo de 45 dias", valores_fontes=valores)
    try:
        govbot.validar_valores_materiais(
            "Prazo de 90 dias", valores_fontes=valores)
    except govbot.ErroValorMaterial:
        pass
    else:
        raise AssertionError("source_id não pode autorizar conteúdo ausente")


def test_proposta_de_outra_etapa_nao_aparece_nem_pode_ser_aplicada():
    sessao = _sessao(etapa=1, documentos={
        "dfd": "# 1. CONTEXTO\n\nTexto do DFD.",
    })
    bucket = govbot.obter_bucket(sessao)
    proposta = govbot.criar_proposta_campo(
        "objeto", "Aquisição de cadeiras",
        "Aquisição de cadeiras ergonômicas", "clareza")
    govbot.guardar_proposta(bucket, proposta)

    assert govbot_panel._view_model(sessao, bucket)["proposals"] == []
    evento = {
        "request_id": "request-stage-001",
        "event_type": "apply_proposal",
        "text": "",
        "focus": "editor_dfd",
        "proposal_id": proposta.proposal_id,
        "draft": {"editor_dfd": sessao["documentos"]["dfd"]},
    }
    try:
        govbot_panel._processar_evento(sessao, bucket, evento)
    except govbot.ErroAlvo:
        pass
    else:
        raise AssertionError("proposta fora da etapa deveria ser rejeitada")
    assert sessao["dados"]["objeto"] == "Aquisição de cadeiras"


def test_render_do_painel_e_fragmento_e_separa_reruns_mutaveis():
    fonte = Path(govbot_panel.__file__).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    render = next(
        node for node in arvore.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "render"
    )
    assert any(ast.unparse(decorador) == "st.fragment"
               for decorador in render.decorator_list)
    assert 'st.rerun(scope="fragment")' in fonte
    assert "if mutou:\n        st.rerun()" in fonte


def test_aplicar_proposta_preserva_outros_drafts_e_distingue_sessao(
    monkeypatch,
):
    sessao = _sessao(
        dados={"objeto": "Aquisição de cadeiras", "riscos": "Original"},
        documentos={"dfd": "# 1. OBJETO\n\nTexto."},
    )
    bucket = govbot.obter_bucket(sessao)
    contexto = govbot.montar_contexto_minimo(
        dados=sessao["dados"], foco="objeto")
    proposta = govbot.criar_proposta_campo(
        "objeto", "Aquisição de cadeiras",
        "Aquisição de cadeiras ergonômicas", "Maior precisão",
    )
    govbot.guardar_proposta(bucket, proposta)
    resposta = govbot.GovBotReply(
        "request-proposal-1", "Sugestão pronta", "SUGGESTION",
        proposal=proposta,
    )
    govbot_panel._anotar_proposta(
        sessao, bucket, resposta, contexto,
        "Substitua por Aquisição de cadeiras ergonômicas",
    )

    monkeypatch.setattr(
        govbot_panel.state, "invalidar_a_partir_de",
        lambda _origem: sessao["documentos"].clear(),
    )
    monkeypatch.setattr(
        govbot_panel.state, "autosalvar",
        lambda: sessao.update({"_save_status": "local"}),
    )
    evento = {
        "request_id": "request-apply-001",
        "event_type": "apply_proposal",
        "text": "",
        "focus": "objeto",
        "proposal_id": proposta.proposal_id,
        "draft": {
            "objeto": "Aquisição de cadeiras",
            "riscos": "Edição ainda não enviada",
        },
    }

    assert govbot_panel._processar_evento(sessao, bucket, evento) is True
    assert sessao["dados"]["objeto"].endswith("ergonômicas")
    assert sessao[govbot.CHAVE_RASCUNHO]["riscos"].startswith("Edição")
    assert sessao[govbot.CHAVE_RASCUNHO]["objeto"].endswith("ergonômicas")
    assert "somente nesta sessão" in bucket["messages"][-1]["text"]


def test_confirmar_formulario_remove_apenas_o_draft_do_bucket(monkeypatch):
    sessao = _sessao()
    bucket = govbot.obter_bucket(sessao)
    govbot.guardar_rascunho(sessao, {"objeto": "rascunho"})
    govbot.adicionar_mensagem(bucket, "assistant", "histórico preservado")
    monkeypatch.setattr(govbot_panel, "_sessao", lambda: sessao)

    govbot_panel.confirmar_formulario()

    assert sessao[govbot.CHAVE_RASCUNHO] == {}
    assert bucket["form_draft"] == {}
    assert bucket["messages"][0]["text"] == "histórico preservado"


def test_patch_preserva_edicao_paralela_do_editor_e_continua_desfazivel(
    monkeypatch,
):
    original = (
        "# 1. OBJETO\n\nTexto original.\n\n"
        "# 2. JUSTIFICATIVA\n\nJustificativa original."
    )
    rascunho = original.replace(
        "Justificativa original.", "Justificativa editada pelo usuário.")
    sessao = _sessao(
        documentos={"dfd": original}, etapa=1,
        edicoes_pendentes={"dfd": rascunho},
    )
    bucket = govbot.obter_bucket(sessao)
    govbot.guardar_rascunho(sessao, {"editor_dfd": rascunho})
    contexto = govbot_panel._montar_contexto(
        sessao, "editor_dfd", "Melhore o objeto", evidencias=False)
    proposta = govbot.criar_proposta_bloco(
        str(contexto.bloco_em_foco), str(contexto.valor_atual),
        "Texto do objeto aprimorado.", "Maior clareza",
    )
    govbot.guardar_proposta(bucket, proposta)
    govbot_panel._anotar_proposta(
        sessao, bucket,
        govbot.GovBotReply(
            "request-patch-base", "Sugestão", "SUGGESTION",
            proposal=proposta,
        ),
        contexto, "Melhore o objeto",
    )
    monkeypatch.setattr(
        govbot_panel.state, "invalidar_a_partir_de", lambda _origem: None)
    monkeypatch.setattr(
        govbot_panel.state, "autosalvar",
        lambda: sessao.update({"_save_status": "local"}),
    )

    assert govbot_panel._processar_evento(sessao, bucket, {
        "request_id": "request-patch-001",
        "event_type": "apply_proposal",
        "text": "",
        "focus": "editor_dfd",
        "proposal_id": proposta.proposal_id,
        "draft": {"editor_dfd": rascunho},
    }) is True
    assert "objeto aprimorado" in sessao["documentos"]["dfd"]
    assert "editada pelo usuário" in sessao["edicoes_pendentes"]["dfd"]
    assert "objeto aprimorado" in sessao["edicoes_pendentes"]["dfd"]

    assert govbot_panel._processar_evento(sessao, bucket, {
        "request_id": "request-undo-001",
        "event_type": "undo",
        "text": "",
        "focus": "editor_dfd",
        "proposal_id": None,
        "draft": {"editor_dfd": sessao["edicoes_pendentes"]["dfd"]},
    }) is True
    assert sessao["documentos"]["dfd"] == original
    assert sessao["edicoes_pendentes"]["dfd"] == rascunho


def test_undo_bloqueia_edicao_posterior_ainda_nao_enviada():
    sessao = _sessao(
        dados={"justificativa": "Texto original"}, documentos={}, etapa=0,
    )
    bucket = govbot.obter_bucket(sessao)
    proposta = govbot.criar_proposta_campo(
        "justificativa", "Texto original", "Texto aplicado", "clareza")
    govbot.aplicar_campo_escalar(
        sessao, bucket, proposta, "apply-before-draft")
    govbot_panel._atualizar_widget_apos_mutacao(
        sessao, bucket, "justificativa")

    evento = {
        "request_id": "undo-after-draft-01",
        "event_type": "undo",
        "text": "",
        "focus": "justificativa",
        "proposal_id": None,
        "draft": {"justificativa": "Edição posterior não enviada"},
    }
    try:
        govbot_panel._processar_evento(sessao, bucket, evento)
    except govbot.ErroConflitoDesfazer:
        pass
    else:
        raise AssertionError("undo deveria bloquear o rascunho posterior")
    assert sessao["dados"]["justificativa"] == "Texto aplicado"
    assert sessao[govbot.CHAVE_RASCUNHO]["justificativa"].startswith("Edição")
    assert len(bucket["changes"]) == 1


def test_correcao_de_achado_hidrata_documento_e_nao_o_finding(monkeypatch):
    sessao = _sessao(
        documentos={"dfd": "# 1. CONTEXTO\n\nTexto original."}, etapa=1,
    )
    bucket = govbot.obter_bucket(sessao)
    contexto = govbot.GovBotContext(
        processo_id=None, etapa=1, documento="dfd",
        achados=({
            "findingId": "F001", "documentId": "dfd",
            "autoCorrectable": True,
        },),
    )

    def corrigir(estado, _bucket, finding_id, action_id, **_kwargs):
        estado["documentos"]["dfd"] = "# 1. CONTEXTO\n\nTexto corrigido."
        return govbot.GovBotReply(
            action_id, "Correção aplicada somente nesta sessão.", "SUCCESS",
            govbot.GovBotIntent("fix_finding", "Corrigido", finding_id),
            applied=True, saved=False,
        )

    monkeypatch.setattr(govbot, "corrigir_achado", corrigir)

    assert govbot_panel._corrigir_achado(
        sessao, bucket, contexto, "F001", "fix-panel-001") is True
    assert sessao[govbot.CHAVE_RASCUNHO]["editor_dfd"].endswith("corrigido.")
    assert "editor_F001" not in sessao[govbot.CHAVE_RASCUNHO]


def test_app_com_flag_ligada_monta_o_fragmento_sem_quebrar(monkeypatch):
    from src import db

    monkeypatch.setenv("GOVDOCS_MODO_ABERTO", "1")
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == "govbot")
    app = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app, default_timeout=60)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""

    at.run()

    assert not at.exception
    assert "govbot" in at.session_state
    assert at.session_state["govbot"]["current_bucket"].startswith("local:")


def test_app_com_flag_desligada_mantem_fluxo_sem_estado_govbot(monkeypatch):
    from src import db

    monkeypatch.setenv("GOVDOCS_MODO_ABERTO", "1")
    monkeypatch.setattr(db, "flag_ativa", lambda _nome: False)
    app = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app, default_timeout=60)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""

    at.run()

    assert not at.exception
    assert "govbot" not in at.session_state
    assert "govbot_form_draft" not in at.session_state
    assert not any(
        str(chave).startswith("govbot_campo_")
        for chave in at.session_state.filtered_state
    )
