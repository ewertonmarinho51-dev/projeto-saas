"""
O bloqueio de chamadas pagas, medido pelos CAMINHOS REAIS do sistema.

§3 da auditoria: `chamadas reais às APIs de LLMs = 0`.

POR QUE ESTAS PROVAS EXISTEM SEPARADAS DO BLOQUEIO

Porque um bloqueio que ninguém testou é uma promessa. A pergunta que
importa não é "a função `instalar()` faz o que diz" — é "o sistema,
percorrido do jeito que ele percorre, consegue escapar?".

Por isso as provas abaixo não chamam `socket.getaddrinfo` à mão: elas
chamam `llm.gerar_documento`, `llm.chamar_ia_texto` e o caminho de
embedding do RAG, que são os lugares de onde o dinheiro sairia. Se
algum deles tiver um atalho que não passe pela resolução de nome, é
aqui que se descobre — e não na fatura.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sem_llm  # noqa: E402


@pytest.fixture(autouse=True)
def _guarda():
    sem_llm.zerar()
    sem_llm.instalar()
    yield
    sem_llm.remover()
    sem_llm.zerar()


# ---------------------------------------------------------------------------
# 1) O bloqueio pega, e CONTA
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("host", [
    "api.openai.com",
    "generativelanguage.googleapis.com",
    "openrouter.ai",
    "API.OpenAI.COM",              # caixa não pode escapar
    "api.openai.com.",             # ponto final de FQDN também não
])
def test_host_pago_e_bloqueado_e_contabilizado(host):
    antes = sem_llm.tentativas()
    with pytest.raises(sem_llm.ChamadaPagaBloqueada):
        socket.getaddrinfo(host, 443)
    assert sem_llm.tentativas() == antes + 1, (
        "a tentativa não foi contabilizada — o número é a evidência do §3")


def test_o_resto_da_internet_continua_alcancavel():
    """
    §3 é explícito: não desativar a conectividade necessária. Um
    bloqueio total provaria "nada foi chamado" pelo motivo errado — o
    app nem teria subido para tentar.
    """
    for host in ("supabase.co", "localhost"):
        try:
            socket.getaddrinfo(host, 443)
        except sem_llm.ChamadaPagaBloqueada:
            pytest.fail(f"{host} foi bloqueado — o Supabase é necessário")
        except socket.gaierror:
            pass  # sem DNS neste ambiente; o que importa é NÃO ser bloqueio


def test_subdominio_de_host_pago_nao_escapa():
    with pytest.raises(sem_llm.ChamadaPagaBloqueada):
        socket.getaddrinfo("eu.api.openai.com", 443)


def test_host_parecido_nao_e_bloqueado_por_engano():
    """
    `openai.com.exemplo.org` não é a OpenAI. Bloquear por substring
    derrubaria tráfego legítimo e daria à lista de negação um alcance
    que ninguém auditou.
    """
    try:
        socket.getaddrinfo("openai.com.exemplo.org", 443)
    except sem_llm.ChamadaPagaBloqueada:
        pytest.fail("casou por substring — a lista é de SUFIXO de host")
    except socket.gaierror:
        pass


# ---------------------------------------------------------------------------
# 2) OS CAMINHOS REAIS DO SISTEMA — é isto que decide
# ---------------------------------------------------------------------------
def _com_chaves(monkeypatch):
    """
    As três chaves preenchidas: força o sistema a TENTAR sair.

    As provas abaixo esperam `ChamadaPagaBloqueada`, e NÃO `Exception`.
    A primeira versão usava `Exception` — e passou aceitando um
    `TypeError` de assinatura errada como se fosse o bloqueio
    funcionando. Foi a asserção de `tentativas() > 0` que pegou: sem
    ela, a suíte estaria verde afirmando uma garantia que não tinha
    sido exercitada uma única vez.
    """
    from src import llm

    monkeypatch.setattr(llm, "obter_openai_key", lambda: "sk-teste-falso")
    monkeypatch.setattr(llm, "obter_api_key", lambda: "chave-gemini-falsa")
    monkeypatch.setattr(llm, "obter_openrouter_key", lambda: "chave-or-falsa")


def test_a_geracao_de_documento_nao_consegue_gastar(monkeypatch):
    """
    O caminho principal: DFD, ETP, TR, edital. Com as três chaves
    preenchidas o sistema percorre a cascata inteira — e cada motor
    esbarra no bloqueio.
    """
    from src import llm, rag

    _com_chaves(monkeypatch)
    monkeypatch.setattr(rag, "montar_bloco_referencias",
                        lambda dados, doc_key: "")

    # O sistema TRADUZ o bloqueio em `ErroGeracaoIA` — é o comportamento
    # correto dele. A evidência do §3 não é o tipo da exceção: é o
    # contador. Exigir o tipo exato aqui testaria a tradução, não o
    # bloqueio; exigir `Exception` aceitaria um TypeError de chamada
    # errada, que foi o engano da primeira versão.
    with pytest.raises(llm.ErroGeracaoIA):
        llm.gerar_documento("dfd", {"orgao": "X", "objeto": "Y",
                                    "justificativa": "Z"}, None)

    assert sem_llm.tentativas() > 0, (
        "a geração não tentou sair — ou o teste não exercitou o caminho, "
        "ou há um atalho que não passa pela rede")


def test_a_cascata_tenta_TODOS_os_motores_e_todos_sao_barrados(monkeypatch):
    """
    O fallback é o caminho que um mock de `_chamar_openai` NÃO cobriria:
    ele desvia o primeiro motor e deixa o segundo sair pela porta.
    """
    from src import llm, rag

    _com_chaves(monkeypatch)
    monkeypatch.setattr(rag, "montar_bloco_referencias",
                        lambda dados, doc_key: "")
    monkeypatch.delenv("OMNIROUTE_ROUTING_ENABLED", raising=False)

    with pytest.raises(llm.ErroGeracaoIA):
        llm.gerar_documento("etp", {"orgao": "X", "objeto": "Y",
                                    "justificativa": "Z"}, None)

    hosts = {t["host"].lower() for t in sem_llm.relatorio()}
    assert len(hosts) >= 2, (
        f"só um motor foi tentado ({hosts}) — o fallback não foi "
        "exercitado, então esta prova não cobre o caminho que ele abre")


def test_a_chamada_de_texto_avulsa_tambem_e_barrada(monkeypatch):
    """`chamar_ia_texto` alimenta revisão, corretor, GovBot e pareceres."""
    from src import llm

    _com_chaves(monkeypatch)
    with pytest.raises(llm.ErroGeracaoIA):
        llm.chamar_ia_texto("sistema", "usuário")
    assert sem_llm.tentativas() > 0


def test_uma_acao_do_usuario_vira_VARIAS_tentativas_de_rede(monkeypatch):
    """
    ACHADO DE CUSTO, medido e não suposto (§15, §E).

    O SDK da OpenAI reexecuta por conta própria antes de desistir, e
    `llm.py` tem a própria cascata por cima. Uma única ação do servidor
    produz mais de uma requisição — e na rodada operacional cada uma
    delas é paga.

    Esta prova fixa o número observado para que um aumento silencioso
    (alguém subindo `API_TENTATIVAS`, ou acrescentando um motor) apareça
    aqui antes de aparecer na fatura.
    """
    from src import llm

    _com_chaves(monkeypatch)
    with pytest.raises(llm.ErroGeracaoIA):
        llm.chamar_ia_texto("sistema", "usuário")

    assert sem_llm.tentativas() >= 3, (
        "menos tentativas que o esperado — confira se a retentativa do "
        "SDK foi desligada, o que muda o orçamento da próxima rodada")


def test_o_teste_de_conexao_do_painel_nao_gasta(monkeypatch):
    """
    O botão "testar conexão" do painel administrativo é uma chamada
    paga disfarçada de diagnóstico — e é fácil alguém apertá-lo durante
    uma bateria de testes.
    """
    from src import llm

    _com_chaves(monkeypatch)
    ok, _mensagem = llm.testar_conexao("openai")
    assert ok is False
    assert sem_llm.tentativas() > 0


# ---------------------------------------------------------------------------
# 3) O LIVRO NÃO PODE VAZAR SEGREDO
# ---------------------------------------------------------------------------
def test_o_livro_registra_host_e_nunca_conteudo(monkeypatch):
    """
    O livro vira anexo de relatório, e anexo de relatório circula. Só
    host, porta, caminho e horário — nunca corpo, cabeçalho ou chave.
    """
    with pytest.raises(sem_llm.ChamadaPagaBloqueada):
        socket.getaddrinfo("api.openai.com", 443)

    for evento in sem_llm.relatorio():
        assert set(evento) == {"quando", "host", "porta", "caminho"}, (
            f"o livro ganhou campo além do combinado: {set(evento)}")


def test_o_livro_guarda_o_caminho_e_JAMAIS_a_query():
    """
    O caminho separa `/v1/chat/completions` de `/v1/embeddings`, e é
    essa distinção que sustenta o achado de custo do §15: uma única
    geração de documento dispara as duas coisas.

    A QUERY fica de fora, e o motivo é concreto: o Gemini manda a chave
    em `?key=…`. Um livro que guardasse a query seria um vazamento de
    credencial com aparência de evidência de auditoria.
    """
    import httpx

    pedido = httpx.Request(
        "POST", "https://generativelanguage.googleapis.com/v1beta/models/"
                "x:generateContent?key=CHAVE-QUE-NAO-PODE-VAZAR")
    with pytest.raises(sem_llm.ChamadaPagaBloqueada):
        httpx.HTTPTransport().handle_request(pedido)

    evento = sem_llm.relatorio()[-1]
    assert evento["caminho"] == "/v1beta/models/x:generateContent"
    assert "CHAVE-QUE-NAO-PODE-VAZAR" not in json.dumps(evento)


def test_a_mensagem_do_bloqueio_tambem_nao_ecoa_a_query():
    """
    A exceção sobe para o log do app e para a tela. Fechar só o livro
    deixaria a mesma chave sair pela mensagem.
    """
    import httpx

    pedido = httpx.Request(
        "POST", "https://generativelanguage.googleapis.com/v1beta/x"
                "?key=OUTRA-CHAVE-SECRETA")
    with pytest.raises(sem_llm.ChamadaPagaBloqueada) as erro:
        httpx.HTTPTransport().handle_request(pedido)
    assert "OUTRA-CHAVE-SECRETA" not in str(erro.value)


def test_a_mensagem_de_bloqueio_nao_ecoa_chave(monkeypatch):
    from src import llm

    monkeypatch.setattr(llm, "obter_openai_key",
                        lambda: "SEGREDO-QUE-NAO-PODE-VAZAR")
    monkeypatch.setattr(llm, "obter_api_key", lambda: "")
    monkeypatch.setattr(llm, "obter_openrouter_key", lambda: "")

    with pytest.raises(Exception) as erro:
        llm.chamar_ia_texto("s", "u")
    assert "SEGREDOQUENAOPODEVAZAR" not in str(erro.value)
    assert "SEGREDOQUENAOPODEVAZAR" not in str(
        getattr(erro.value, "detalhe", ""))
