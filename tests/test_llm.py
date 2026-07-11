"""Testes da seleção de motor de IA: OpenAI (principal) → Gemini (fallback)."""

import pytest

from src import llm

DADOS = {"orgao": "Órgão X", "objeto": "Objeto Y", "justificativa": "Z"}


@pytest.fixture(autouse=True)
def sem_rag(monkeypatch):
    """Isola a seleção de motor: RAG não consulta banco nestes testes."""
    from src import rag

    monkeypatch.setattr(rag, "montar_bloco_referencias", lambda dados, doc_key: "")


def _configurar(monkeypatch, openai_key: str, gemini_key: str):
    monkeypatch.setattr(llm, "obter_openai_key", lambda: openai_key)
    monkeypatch.setattr(llm, "obter_api_key", lambda: gemini_key)


def test_motor_ativo(monkeypatch):
    _configurar(monkeypatch, "sk-x", "g-y")
    assert llm.motor_ativo() == "openai"
    _configurar(monkeypatch, "", "g-y")
    assert llm.motor_ativo() == "gemini"
    _configurar(monkeypatch, "", "")
    assert llm.motor_ativo() == ""


def test_openai_e_o_motor_principal(monkeypatch):
    _configurar(monkeypatch, "sk-x", "g-y")
    monkeypatch.setattr(llm, "_chamar_openai", lambda s, u, k: "DOC OPENAI")
    monkeypatch.setattr(
        llm, "_chamar_gemini",
        lambda s, u, k: pytest.fail("Gemini não deveria ser chamado"),
    )
    assert llm.gerar_documento("dfd", DADOS, None) == "DOC OPENAI"


def test_fallback_para_gemini_quando_openai_falha(monkeypatch):
    _configurar(monkeypatch, "sk-x", "g-y")

    def openai_quebrada(s, u, k):
        raise llm.ErroGeracaoIA("cota excedida")

    monkeypatch.setattr(llm, "_chamar_openai", openai_quebrada)
    monkeypatch.setattr(llm, "_chamar_gemini", lambda s, u, k: "DOC GEMINI")
    assert llm.gerar_documento("etp", DADOS, "dfd aprovado") == "DOC GEMINI"


def test_erro_propagado_sem_fallback_disponivel(monkeypatch):
    _configurar(monkeypatch, "sk-x", "")

    def openai_quebrada(s, u, k):
        raise llm.ErroGeracaoIA("timeout")

    monkeypatch.setattr(llm, "_chamar_openai", openai_quebrada)
    with pytest.raises(llm.ErroGeracaoIA, match="timeout"):
        llm.gerar_documento("tr", DADOS, "etp aprovado")


def test_sem_nenhuma_chave(monkeypatch):
    _configurar(monkeypatch, "", "")
    with pytest.raises(llm.ErroGeracaoIA, match="Nenhuma chave"):
        llm.gerar_documento("dfd", DADOS, None)


# ---------------------------------------------------------------------------
# Tradução de erro por motor + detalhe técnico bruto
# ---------------------------------------------------------------------------
def test_traduzir_erro_openai_aponta_openai_e_modelo():
    msg = llm._traduzir_erro(Exception("Error code: 404 - model_not_found"), "openai")
    assert "OpenAI" in msg and "OPENAI_MODEL" in msg


def test_traduzir_erro_gemini_aponta_gemini_e_chave():
    msg = llm._traduzir_erro(Exception("401 API key not valid"), "gemini")
    assert "Gemini" in msg and "GOOGLE_API_KEY" in msg


def test_traduzir_erro_quota_billing():
    msg = llm._traduzir_erro(Exception("insufficient_quota / billing"), "openai")
    assert "cota" in msg.lower() or "faturamento" in msg.lower()


def test_erro_carrega_detalhe_tecnico(monkeypatch):
    _configurar(monkeypatch, "sk-x", "")
    monkeypatch.setattr(llm, "_obter_modelo_openai", lambda: "gpt-5-mini")

    def openai_quebrada(s, u, k):
        raise llm.ErroGeracaoIA("falhou", detalhe="[OpenAI · gpt-5-mini] AuthError: 401")

    monkeypatch.setattr(llm, "_chamar_openai", openai_quebrada)
    with pytest.raises(llm.ErroGeracaoIA) as exc:
        llm.gerar_documento("dfd", DADOS, None)
    assert "gpt-5-mini" in exc.value.detalhe


# ---------------------------------------------------------------------------
# Fallback automático de modelo (model_not_found → tenta o próximo)
# ---------------------------------------------------------------------------
def test_e_erro_de_modelo_reconhece_404():
    assert llm._e_erro_de_modelo(Exception("Error code: 404 - model_not_found"))
    assert llm._e_erro_de_modelo(Exception("The model does not exist"))
    assert not llm._e_erro_de_modelo(Exception("401 invalid api key"))


def test_modelos_openai_inclui_fallback(monkeypatch):
    monkeypatch.setattr(llm, "_obter_modelo_openai", lambda: "gpt-5-mini")
    modelos = llm._modelos_openai()
    assert modelos[0] == "gpt-5-mini"
    assert "gpt-4o-mini" in modelos
    assert len(modelos) == len(set(modelos))  # sem duplicatas


def test_openai_troca_de_modelo_quando_nao_encontrado(monkeypatch):
    monkeypatch.setattr(llm, "_obter_modelo_openai", lambda: "modelo-inexistente")
    monkeypatch.setattr(llm, "API_TENTATIVAS", 1)

    chamados = []

    def fake_uma_chamada(cliente, modelo, s, u):
        chamados.append(modelo)
        if modelo == "modelo-inexistente":
            raise Exception("Error code: 404 - model_not_found")
        return "DOC OK"

    monkeypatch.setattr(llm, "_openai_uma_chamada", fake_uma_chamada)
    # OpenAI() é instanciado mas não usado pelo fake
    monkeypatch.setattr("openai.OpenAI", lambda **kw: object())
    assert llm._chamar_openai("s", "u", "sk-x") == "DOC OK"
    assert chamados[0] == "modelo-inexistente" and chamados[1] == "gpt-4o-mini"


def test_openai_nao_troca_modelo_em_erro_de_chave(monkeypatch):
    monkeypatch.setattr(llm, "_obter_modelo_openai", lambda: "gpt-5-mini")

    chamados = []

    def fake_uma_chamada(cliente, modelo, s, u):
        chamados.append(modelo)
        raise Exception("401 invalid_api_key")

    monkeypatch.setattr(llm, "_openai_uma_chamada", fake_uma_chamada)
    monkeypatch.setattr("openai.OpenAI", lambda **kw: object())
    with pytest.raises(llm.ErroGeracaoIA) as exc:
        llm._chamar_openai("s", "u", "sk-x")
    assert len(chamados) == 1  # não tentou outros modelos
    assert "chave" in str(exc.value).lower()


def test_testar_conexao_sem_chave(monkeypatch):
    _configurar(monkeypatch, "", "")
    ok, msg = llm.testar_conexao("openai")
    assert not ok and "OPENAI_API_KEY" in msg


def test_testar_conexao_ok(monkeypatch):
    _configurar(monkeypatch, "sk-x", "")
    monkeypatch.setattr(llm, "_chamar_openai", lambda s, u, k: "OK")
    ok, msg = llm.testar_conexao("openai")
    assert ok and "OpenAI" in msg


def test_params_modelo_reasoning():
    assert llm._params_modelo_openai("gpt-5-mini") == {"reasoning_effort": "minimal"}
    assert llm._params_modelo_openai("o3-mini") == {"reasoning_effort": "low"}
    assert llm._params_modelo_openai("gpt-4o-mini") == {}


def test_openai_resposta_vazia_troca_de_modelo(monkeypatch):
    """gpt-5-mini devolve vazio → cai para o próximo modelo, que responde."""
    monkeypatch.setattr(llm, "_obter_modelo_openai", lambda: "gpt-5-mini")
    monkeypatch.setattr(llm, "API_TENTATIVAS", 1)
    monkeypatch.setattr("openai.OpenAI", lambda **kw: object())

    chamados = []

    def fake_uma_chamada(cliente, modelo, s, u):
        chamados.append(modelo)
        if modelo == "gpt-5-mini":
            raise llm._RespostaVazia("conteúdo vazio (finish_reason=length)")
        return "DOC OK"

    monkeypatch.setattr(llm, "_openai_uma_chamada", fake_uma_chamada)
    assert llm._chamar_openai("s", "u", "sk-x") == "DOC OK"
    assert chamados[0] == "gpt-5-mini" and chamados[1] == "gpt-4o-mini"


def test_openai_todos_vazios_mensagem_amigavel(monkeypatch):
    monkeypatch.setattr(llm, "_obter_modelo_openai", lambda: "gpt-5-mini")
    monkeypatch.setattr("openai.OpenAI", lambda **kw: object())
    monkeypatch.setattr(
        llm, "_openai_uma_chamada",
        lambda c, m, s, u: (_ for _ in ()).throw(llm._RespostaVazia("vazio")),
    )
    with pytest.raises(llm.ErroGeracaoIA) as exc:
        llm._chamar_openai("s", "u", "sk-x")
    assert "vazia" in str(exc.value).lower()
    # detalhe lista todos os modelos realmente tentados
    assert "gpt-4o-mini" in exc.value.detalhe and "gpt-4.1-mini" in exc.value.detalhe


def test_gerar_injeta_tabela_grande(monkeypatch):
    _configurar(monkeypatch, "sk-x", "")
    from src import planilha

    itens = [{"descricao": f"Item {i}", "unidade": "un",
              "quantidade": 2, "valor_unitario": 10.0} for i in range(30)]
    dados = {"orgao": "X", "objeto": "Y", "itens": itens}
    # IA devolve texto com a marca; a tabela real deve substituí-la
    monkeypatch.setattr(
        llm, "_chamar_openai",
        lambda s, u, k: "## Estimativa\n\n" + planilha.MARCADOR_TABELA,
    )
    saida = llm.gerar_documento("dfd", dados, None)
    assert planilha.MARCADOR_TABELA not in saida
    assert "VALOR GLOBAL" in saida and "Item 29" in saida


def test_origem_chave_prioriza_painel(monkeypatch):
    from src import db

    monkeypatch.setattr(db, "obter_config", lambda nome: "chave-do-painel")
    monkeypatch.setenv("OPENAI_API_KEY", "chave-do-env")
    assert llm.origem_chave("OPENAI_API_KEY", "openai_key_manual") == \
        "painel do administrador"


def test_origem_chave_env_e_vazia(monkeypatch):
    from src import db

    monkeypatch.setattr(db, "obter_config", lambda nome: "")
    monkeypatch.setenv("CHAVE_TESTE_X", "valor")
    assert llm.origem_chave("CHAVE_TESTE_X", "") == "variável de ambiente"
    monkeypatch.delenv("CHAVE_TESTE_X")
    assert llm.origem_chave("CHAVE_TESTE_X", "") == ""


def test_ler_chave_sidebar_vazio_nao_estoura():
    """Regressão: sidebar vazio (modelos) causava StreamlitAPIException,
    derrubando AS DUAS engines ao resolver o modelo."""
    # não deve lançar e deve cair no padrão configurado
    assert llm._obter_modelo_openai()  # gpt-5-mini (padrão)
    assert llm._obter_modelo()          # gemini-... (padrão)
    assert llm._ler_chave("QUALQUER_COISA", "") == ""
