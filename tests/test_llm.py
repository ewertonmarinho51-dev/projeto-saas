"""Testes da seleção de motor de IA: OpenAI (principal) → Gemini (fallback)."""

import pytest

from src import llm

DADOS = {"orgao": "Órgão X", "objeto": "Objeto Y", "justificativa": "Z"}


@pytest.fixture(autouse=True)
def sem_rag(monkeypatch):
    """Isola a seleção de motor: RAG não consulta banco nestes testes."""
    from src import rag

    monkeypatch.setattr(rag, "montar_bloco_referencias", lambda dados, doc_key: "")


def _configurar(monkeypatch, openai_key: str, gemini_key: str,
                openrouter_key: str = ""):
    """
    Fixa as TRÊS chaves. O terceiro motor entra com "" por padrão para que
    as provas antigas sigam significando exatamente o que significavam —
    e para que um `OPENROUTER_API_KEY` no ambiente de quem roda a suíte
    não mude o resultado delas.
    """
    monkeypatch.setattr(llm, "obter_openai_key", lambda: openai_key)
    monkeypatch.setattr(llm, "obter_api_key", lambda: gemini_key)
    monkeypatch.setattr(llm, "obter_openrouter_key", lambda: openrouter_key)


def test_motor_ativo(monkeypatch):
    _configurar(monkeypatch, "sk-x", "g-y")
    assert llm.motor_ativo() == "openai"
    _configurar(monkeypatch, "", "g-y")
    assert llm.motor_ativo() == "gemini"
    _configurar(monkeypatch, "", "")
    assert llm.motor_ativo() == ""


def test_openai_e_o_motor_principal(monkeypatch):
    _configurar(monkeypatch, "sk-x", "g-y")
    monkeypatch.setattr(llm, "_chamar_openai", lambda s, u, k, **kw: "DOC OPENAI")
    monkeypatch.setattr(
        llm, "_chamar_gemini",
        lambda s, u, k, **kw: pytest.fail("Gemini não deveria ser chamado"),
    )
    assert llm.gerar_documento("dfd", DADOS, None) == "DOC OPENAI"


def test_fallback_para_gemini_quando_openai_falha(monkeypatch):
    _configurar(monkeypatch, "sk-x", "g-y")

    def openai_quebrada(s, u, k, **kw):
        raise llm.ErroGeracaoIA("cota excedida")

    monkeypatch.setattr(llm, "_chamar_openai", openai_quebrada)
    monkeypatch.setattr(llm, "_chamar_gemini", lambda s, u, k, **kw: "DOC GEMINI")
    assert llm.gerar_documento("etp", DADOS, "dfd aprovado") == "DOC GEMINI"


def test_erro_propagado_sem_fallback_disponivel(monkeypatch):
    _configurar(monkeypatch, "sk-x", "")

    def openai_quebrada(s, u, k, **kw):
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

    def openai_quebrada(s, u, k, **kw):
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

    def fake_uma_chamada(cliente, modelo, s, u, *_):
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

    def fake_uma_chamada(cliente, modelo, s, u, *_):
        chamados.append(modelo)
        raise Exception("401 invalid_api_key")

    monkeypatch.setattr(llm, "_openai_uma_chamada", fake_uma_chamada)
    monkeypatch.setattr("openai.OpenAI", lambda **kw: object())
    with pytest.raises(llm.ErroGeracaoIA) as exc:
        llm._chamar_openai("s", "u", "sk-x")
    assert len(chamados) == 1  # não tentou outros modelos
    assert "chave" in str(exc.value).lower()


def test_openai_honra_tentativas_no_loop_de_retry(monkeypatch):
    """O timeout curto do auditor (tentativas=1) não pode fazer 3 retries."""
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda *_: None)  # sem backoff real
    monkeypatch.setattr(llm, "_obter_modelo_openai", lambda: "gpt-5-mini")
    monkeypatch.setattr(llm, "_modelos_openai", lambda: ["gpt-5-mini"])

    tentativas_feitas = {"n": 0}

    def cliente_lento(**_kw):
        class _Chat:
            class completions:
                @staticmethod
                def create(**_k):
                    tentativas_feitas["n"] += 1
                    raise TimeoutError("Request timed out")
        return type("C", (), {"chat": _Chat()})()

    monkeypatch.setattr("openai.OpenAI", cliente_lento)

    # tentativas=1: uma única chamada por modelo, sem os 3 retries
    with pytest.raises(llm.ErroGeracaoIA):
        llm._chamar_openai("s", "u", "sk-x", timeout=45, tentativas=1)
    assert tentativas_feitas["n"] == 1

    # controle: sem o parâmetro, mantém o padrão de 3 tentativas
    tentativas_feitas["n"] = 0
    with pytest.raises(llm.ErroGeracaoIA):
        llm._chamar_openai("s", "u", "sk-x")
    assert tentativas_feitas["n"] == llm.API_TENTATIVAS


def test_testar_conexao_sem_chave(monkeypatch):
    _configurar(monkeypatch, "", "")
    ok, msg = llm.testar_conexao("openai")
    assert not ok and "OPENAI_API_KEY" in msg


def test_testar_conexao_ok(monkeypatch):
    _configurar(monkeypatch, "sk-x", "")
    monkeypatch.setattr(llm, "_chamar_openai", lambda s, u, k, **kw: "OK")
    ok, msg = llm.testar_conexao("openai")
    assert ok and "OpenAI" in msg


def test_params_modelo_reasoning():
    assert llm._params_modelo_openai("gpt-5-mini") == {"reasoning_effort": "low"}
    assert llm._params_modelo_openai("o3-mini") == {"reasoning_effort": "low"}
    assert llm._params_modelo_openai("gpt-4o-mini") == {}


def test_openai_resposta_vazia_troca_de_modelo(monkeypatch):
    """gpt-5-mini devolve vazio → cai para o próximo modelo, que responde."""
    monkeypatch.setattr(llm, "_obter_modelo_openai", lambda: "gpt-5-mini")
    monkeypatch.setattr(llm, "API_TENTATIVAS", 1)
    monkeypatch.setattr("openai.OpenAI", lambda **kw: object())

    chamados = []

    def fake_uma_chamada(cliente, modelo, s, u, *_):
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
        lambda c, m, s, u, *_: (_ for _ in ()).throw(
            llm._RespostaVazia("vazio")),
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
        lambda s, u, k, **kw: "## Estimativa\n\n" + planilha.MARCADOR_TABELA,
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


# ---------------------------------------------------------------------------
# Terceiro motor: OpenRouter
#
# A regra que mais importa aqui não é "o motor funciona" — é que ele NÃO
# altera quem já estava configurado. Adicionar motor gratuito ao lado de
# uma chave paga não pode rebaixar a geração em silêncio.
# ---------------------------------------------------------------------------
def test_openrouter_entra_por_ultimo_na_precedencia(monkeypatch):
    """Com as três chaves, o motor ativo continua sendo a OpenAI."""
    _configurar(monkeypatch, "sk-x", "g-y", "or-z")
    assert llm.motor_ativo() == "openai"
    assert [m for m, _ in llm.motores_disponiveis()] == [
        "openai", "gemini", "openrouter"]


def test_openrouter_e_o_motor_ativo_quando_e_a_unica_chave(monkeypatch):
    _configurar(monkeypatch, "", "", "or-z")
    assert llm.motor_ativo() == "openrouter"


def test_openrouter_nao_e_chamado_quando_a_openai_responde(monkeypatch):
    _configurar(monkeypatch, "sk-x", "g-y", "or-z")
    monkeypatch.setattr(llm, "_chamar_openai", lambda s, u, k, **kw: "DOC OPENAI")
    monkeypatch.setattr(
        llm, "_chamar_openrouter",
        lambda s, u, k, **kw: pytest.fail("OpenRouter não deveria ser chamado"))
    assert llm.gerar_documento("dfd", DADOS, None) == "DOC OPENAI"


def test_openrouter_assume_quando_os_dois_primeiros_falham(monkeypatch):
    _configurar(monkeypatch, "sk-x", "g-y", "or-z")

    def quebrada(s, u, k, **kw):
        raise llm.ErroGeracaoIA("cota excedida")

    monkeypatch.setattr(llm, "_chamar_openai", quebrada)
    monkeypatch.setattr(llm, "_chamar_gemini", quebrada)
    monkeypatch.setattr(llm, "_chamar_openrouter",
                        lambda s, u, k, **kw: "DOC OPENROUTER")
    assert llm.gerar_documento("etp", DADOS, "dfd aprovado") == "DOC OPENROUTER"


def test_erro_propagado_e_o_do_ultimo_motor(monkeypatch):
    """
    Quando todos falham, o operador precisa do erro do ÚLTIMO: os
    anteriores ele já viu como aviso na tela. Propagar o primeiro mandaria
    conferir uma credencial que não é a que está bloqueando agora.
    """
    _configurar(monkeypatch, "sk-x", "", "or-z")
    monkeypatch.setattr(
        llm, "_chamar_openai",
        lambda s, u, k, **kw: (_ for _ in ()).throw(
            llm.ErroGeracaoIA("falha da openai")))
    monkeypatch.setattr(
        llm, "_chamar_openrouter",
        lambda s, u, k, **kw: (_ for _ in ()).throw(
            llm.ErroGeracaoIA("limite diário do openrouter")))
    with pytest.raises(llm.ErroGeracaoIA, match="limite diário do openrouter"):
        llm.gerar_documento("tr", DADOS, "etp aprovado")


def test_a_revisao_automatica_tambem_alcanca_o_openrouter(monkeypatch):
    """`chamar_ia_texto` usa a mesma cadeia — sem uma segunda ordem."""
    _configurar(monkeypatch, "", "", "or-z")
    monkeypatch.setattr(llm, "_chamar_openrouter",
                        lambda s, u, k, **kw: "REVISADO")
    assert llm.chamar_ia_texto("s", "u", finalidade="corretor") == "REVISADO"


def test_modelos_openrouter_comecam_pelo_maior_e_sao_gratuitos(monkeypatch):
    """
    O primeiro é a Nemotron Ultra, e TODOS carregam o sufixo `:free`.

    O sufixo é a diferença entre o endpoint gratuito e o pago do mesmo
    modelo. Um identificador sem ele passaria a faturar sem que nada na
    tela mudasse — por isso a prova é sobre a lista inteira, não sobre o
    primeiro item.
    """
    monkeypatch.setattr(llm, "_obter_modelo_openrouter",
                        lambda: llm.OPENROUTER_MODEL_PADRAO)
    modelos = llm._modelos_openrouter()
    assert modelos[0] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert all(m.endswith(":free") for m in modelos), modelos
    assert len(modelos) == len(set(modelos))


def test_modelo_do_openrouter_e_configuravel(monkeypatch):
    monkeypatch.setattr(llm, "_obter_modelo_openrouter", lambda: "outro/modelo")
    assert llm._modelos_openrouter()[0] == "outro/modelo"


def test_openrouter_aponta_para_a_base_certa(monkeypatch):
    """
    A base é o que distingue OpenRouter de OpenAI — o SDK é o mesmo. Sem
    ela, a chave do OpenRouter iria para a api.openai.com e voltaria 401.
    """
    capturado = {}

    def cliente_falso(**kw):
        capturado.update(kw)
        return object()

    monkeypatch.setattr("openai.OpenAI", cliente_falso)
    monkeypatch.setattr(llm, "_openai_uma_chamada",
                        lambda *a, **kw: "OK")
    assert llm._chamar_openrouter("s", "u", "or-z") == "OK"
    assert capturado["base_url"] == llm.OPENROUTER_BASE_URL
    assert capturado["api_key"] == "or-z"


def test_traduzir_erro_openrouter_aponta_a_variavel_certa():
    msg = llm._traduzir_erro(Exception("401 invalid api key"), "openrouter")
    assert "OpenRouter" in msg and "OPENROUTER_API_KEY" in msg


def test_testar_conexao_recusa_motor_desconhecido(monkeypatch):
    """
    Antes, qualquer nome diferente de 'openai' caía no Gemini. Com três
    motores isso faria um "testar OpenRouter" reportar o Gemini como se
    fosse ele — e o operador concluiria que a chave está boa.
    """
    _configurar(monkeypatch, "", "g-y", "")
    monkeypatch.setattr(llm, "_chamar_gemini",
                        lambda s, u, k, **kw: pytest.fail("não é o motor pedido"))
    ok, msg = llm.testar_conexao("motor-que-nao-existe")
    assert not ok and "desconhecido" in msg.lower()


def test_testar_conexao_do_openrouter(monkeypatch):
    _configurar(monkeypatch, "", "", "or-z")
    monkeypatch.setattr(llm, "_chamar_openrouter", lambda s, u, k, **kw: "OK")
    ok, msg = llm.testar_conexao("openrouter")
    assert ok and "OpenRouter" in msg and ":free" in msg
