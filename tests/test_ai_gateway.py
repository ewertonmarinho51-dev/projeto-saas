"""
O gateway e a política de roteamento.

A prova que decide se esta entrega pode ser mergeada é a primeira:
**com tudo desligado, o comportamento é o de antes.** Motores na mesma
ordem, nenhuma `base_url`, nenhuma restrição. A camada entrou no caminho
que gera edital para prefeitura; se ela mudar qualquer coisa por padrão,
mudou sem ninguém decidir.

As outras medem o que a camada passa a permitir quando alguém a LIGA — e
uma em especial, `test_todo_documento_oficial_e_tarefa_critica`, existe
para o dia em que o projeto ganhar um documento novo: sem ela, o
documento nasceria classificado como "segundo plano" e poderia ser
gerado pelo modelo mais barato disponível.
"""

from __future__ import annotations

import pytest

from src import ai_gateway, roteamento
from src.config import DOCUMENTOS

DISPONIVEIS = [("openai", "k1"), ("gemini", "k2"), ("openrouter", "k3")]


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    """
    Nenhuma prova herda o ambiente de quem rodou a suíte.

    Sem isto, um `OMNIROUTE_ENABLED=true` exportado no terminal mudaria o
    resultado de metade deste arquivo — e o teste que garante o padrão
    passaria a medir outra coisa.
    """
    for var in (ai_gateway.VAR_GATEWAY, ai_gateway.VAR_BASE_URL,
                ai_gateway.VAR_ROTEAMENTO):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# 1) O PADRÃO — a prova que autoriza o merge
# ---------------------------------------------------------------------------
def test_com_tudo_desligado_nada_muda():
    assert ai_gateway.gateway_ligado() is False
    assert ai_gateway.roteamento_ligado() is False
    assert ai_gateway.motores_para("edital", DISPONIVEIS) == DISPONIVEIS
    for motor in ("openai", "gemini", "openrouter"):
        assert ai_gateway.base_url_para(motor) is None


def test_ligar_o_gateway_sem_endereco_nao_liga_nada(monkeypatch):
    """
    `OMNIROUTE_ENABLED=true` sozinho não pode mandar o cliente para lugar
    nenhum. Sem `base_url`, "ligado" significaria apontar para o vazio —
    e o SDK receberia uma string vazia como endereço.
    """
    monkeypatch.setenv(ai_gateway.VAR_GATEWAY, "true")
    assert ai_gateway.gateway_ligado() is False
    assert ai_gateway.base_url_para("openai") is None


def test_o_gemini_nunca_recebe_base_url(monkeypatch):
    """
    O Gemini tem SDK próprio e não atravessa `base_url`. Mandar o
    endereço do gateway para ele não faria nada de ERRADO — faria NADA,
    que é pior: a requisição pareceria roteada e não estaria, e a
    telemetria diria "gateway" para uma chamada que foi direto.
    """
    monkeypatch.setenv(ai_gateway.VAR_GATEWAY, "true")
    monkeypatch.setenv(ai_gateway.VAR_BASE_URL, "http://127.0.0.1:20128/v1")
    assert ai_gateway.base_url_para("openai") == "http://127.0.0.1:20128/v1"
    assert ai_gateway.base_url_para("openrouter") == "http://127.0.0.1:20128/v1"
    assert ai_gateway.base_url_para("gemini") is None


# ---------------------------------------------------------------------------
# 2) O QUE A POLÍTICA FAZ QUANDO LIGADA
# ---------------------------------------------------------------------------
def test_edital_nao_cai_para_motor_nao_homologado(monkeypatch):
    """
    O buraco que esta entrega fecha.

    A cascata de `llm.py` é irrestrita: se a OpenAI cair no meio da
    geração de um edital, a requisição desce para o motor seguinte sem
    que ninguém tenha homologado aquele modelo para documento que vira
    ato administrativo. O documento sai, o servidor assina, e a única
    pista é uma linha de registro técnico.
    """
    monkeypatch.setenv(ai_gateway.VAR_ROTEAMENTO, "true")
    assert ai_gateway.motores_para("edital", DISPONIVEIS) == [("openai", "k1")]


def test_tarefa_de_segundo_plano_usa_todos(monkeypatch):
    """O estreitamento é das críticas. Classificar achado pode usar tudo."""
    monkeypatch.setenv(ai_gateway.VAR_ROTEAMENTO, "true")
    assert ai_gateway.motores_para("rotulo-desconhecido-zz",
                                   DISPONIVEIS) == DISPONIVEIS


def test_a_politica_nunca_deixa_a_tarefa_sem_motor(monkeypatch):
    """
    Se a chave do motor homologado não estiver preenchida, a política
    devolve a lista original em vez de lista vazia.

    Política que derruba funcionalidade porque uma chave não foi
    configurada é política que alguém arranca na primeira sexta-feira.
    A recusa dura existe, é `exigir_homologado`, e é uma decisão
    separada e explícita.
    """
    monkeypatch.setenv(ai_gateway.VAR_ROTEAMENTO, "true")
    so_gemini = [("gemini", "k2")]
    assert ai_gateway.motores_para("edital", so_gemini) == so_gemini


def test_a_ordem_do_operador_e_preservada(monkeypatch):
    """
    A ordem vem do painel do administrador — motor principal, depois
    fallback. A política ESTREITA; ela não reordena, porque reordenar
    seria decidir algo que não é dela.
    """
    monkeypatch.setenv(ai_gateway.VAR_ROTEAMENTO, "true")
    invertida = [("openrouter", "k3"), ("openai", "k1"), ("gemini", "k2")]
    assert ai_gateway.motores_para("corretor", invertida) == [("openai", "k1")]


def test_exigir_homologado_recusa_e_explica():
    with pytest.raises(ValueError) as erro:
        roteamento.exigir_homologado("edital", "gemini", restringir=True)
    recado = str(erro.value)
    assert "edital" in recado and "gemini" in recado
    assert roteamento.PROCUREMENT_HIGH_ACCURACY in recado

    # Desligado, não recusa nada — mesma função, decisão do operador.
    roteamento.exigir_homologado("edital", "gemini", restringir=False)
    # Tarefa não crítica também passa.
    roteamento.exigir_homologado("classificacao", "gemini", restringir=True)


# ---------------------------------------------------------------------------
# 3) AS TABELAS PRECISAM FECHAR
# ---------------------------------------------------------------------------
def test_todo_documento_oficial_e_tarefa_critica():
    """
    A prova que existe para o dia em que alguém criar um documento novo.

    `DOCUMENTOS` é a fonte de verdade sobre o que o sistema gera. Um
    documento que entre lá e não entre em `TIPO_DO_ROTULO` cairia em
    `SEGUNDO_PLANO` — grupo CHEAP, fallback irrestrito — e poderia ser
    gerado pelo modelo mais barato disponível. Sem barulho nenhum.
    """
    faltando = [chave for chave in DOCUMENTOS
                if roteamento.tipo_da_tarefa(chave)
                != roteamento.GERACAO_DE_DOCUMENTO]
    assert faltando == [], (
        f"documento oficial fora da política de roteamento: {faltando}. "
        "Acrescente em roteamento.TIPO_DO_ROTULO antes de gerar com ele.")


def test_todo_tipo_tem_grupo_e_todo_grupo_tem_motores():
    for tipo in set(roteamento.TIPO_DO_ROTULO.values()) | {roteamento.SEGUNDO_PLANO}:
        assert tipo in roteamento.GRUPO_DO_TIPO, f"tipo sem grupo: {tipo}"
    for grupo in roteamento.GRUPO_DO_TIPO.values():
        assert roteamento.MOTORES_DO_GRUPO.get(grupo), f"grupo vazio: {grupo}"


def test_grupo_critico_nao_empresta_motor_de_grupo_permissivo():
    """
    Um grupo nunca usa modelo de outro sem política explícita. Medido
    como contenção: o conjunto homologado para documento é SUBCONJUNTO
    do permissivo, nunca o contrário.
    """
    criticos = set(roteamento.MOTORES_DO_GRUPO[
        roteamento.PROCUREMENT_HIGH_ACCURACY])
    baratos = set(roteamento.MOTORES_DO_GRUPO[roteamento.CHEAP])
    assert criticos < baratos, (
        "o grupo de documento oficial deixou de ser mais restrito que o "
        "grupo barato — a contenção virou enfeite")


# ---------------------------------------------------------------------------
# 4) TELEMETRIA SEM CONTEÚDO
# ---------------------------------------------------------------------------
def test_a_telemetria_nao_carrega_conteudo_nem_chave():
    dados = ai_gateway.telemetria("edital", "openai")
    assert dados["task_type"] == roteamento.GERACAO_DE_DOCUMENTO
    assert dados["routing_policy"] == roteamento.PROCUREMENT_HIGH_ACCURACY
    assert dados["provider"] == "openai"
    assert dados["gateway"] == "direto"

    # Nada de prompt, resposta, chave ou url com credencial.
    texto = repr(dados).lower()
    for proibido in ("sk-", "prompt", "content", "api_key", "senha", "token"):
        assert proibido not in texto, f"telemetria vazou '{proibido}'"


def test_o_estado_mostra_endereco_e_nunca_chave(monkeypatch):
    monkeypatch.setenv(ai_gateway.VAR_GATEWAY, "true")
    monkeypatch.setenv(ai_gateway.VAR_BASE_URL, "http://127.0.0.1:20128/v1")
    estado = ai_gateway.estado()
    assert estado["gateway_ligado"] is True
    assert estado["base_url"] == "http://127.0.0.1:20128/v1"
    assert "api_key" not in repr(estado).lower()


# ---------------------------------------------------------------------------
# 4b) A POLÍTICA NO CAMINHO REAL — não só na função pura
#
# As provas acima medem `roteamento` e `ai_gateway` isolados. Estas duas
# atravessam `llm.gerar_documento`, que é o caminho que a tela usa, e são
# o espelho de `test_fallback_para_gemini_quando_openai_falha`
# (tests/test_llm.py): lá, SEM política, a queda da OpenAI leva ao Gemini;
# aqui, COM política, ela para.
#
# As duas versões existem de propósito. Apagar a antiga esconderia que o
# comportamento depende de uma chave, e é justamente isso que precisa
# ficar visível.
# ---------------------------------------------------------------------------
DADOS = {"orgao": "Órgão X", "objeto": "Objeto Y", "justificativa": "Z"}


@pytest.fixture
def _sem_rag(monkeypatch):
    from src import rag
    monkeypatch.setattr(rag, "montar_bloco_referencias",
                        lambda dados, doc_key: "")


def _chaves(monkeypatch, openai: str, gemini: str, openrouter: str = ""):
    from src import llm
    monkeypatch.setattr(llm, "obter_openai_key", lambda: openai)
    monkeypatch.setattr(llm, "obter_api_key", lambda: gemini)
    monkeypatch.setattr(llm, "obter_openrouter_key", lambda: openrouter)


def test_documento_oficial_nao_cai_para_o_gemini_com_a_politica_ligada(
        monkeypatch, _sem_rag):
    """
    O comportamento que esta entrega existe para produzir, medido no
    caminho real: um ETP cuja geração falha na OpenAI **não** é
    concluído pelo Gemini. A requisição morre, e morrer é o certo —
    documento oficial gerado por motor não homologado é assinado por
    agente público.
    """
    from src import llm

    monkeypatch.setenv(ai_gateway.VAR_ROTEAMENTO, "true")
    _chaves(monkeypatch, "sk-x", "g-y", "or-z")

    def openai_quebrada(s, u, k, **kw):
        raise llm.ErroGeracaoIA("cota excedida")

    monkeypatch.setattr(llm, "_chamar_openai", openai_quebrada)
    monkeypatch.setattr(
        llm, "_chamar_gemini",
        lambda s, u, k, **kw: pytest.fail(
            "Gemini atendeu um documento oficial: a política não pegou"))
    monkeypatch.setattr(
        llm, "_chamar_openrouter",
        lambda s, u, k, **kw: pytest.fail(
            "OpenRouter atendeu um documento oficial: a política não pegou"))

    with pytest.raises(llm.ErroGeracaoIA):
        llm.gerar_documento("etp", DADOS, "dfd aprovado")


def test_tarefa_nao_critica_continua_caindo_para_o_gemini(
        monkeypatch, _sem_rag):
    """
    O outro lado, e ele importa tanto quanto: a política estreita o que é
    crítico e **não** toca no resto. Uma chamada genérica continua com a
    cascata inteira, senão o endurecimento vira indisponibilidade.
    """
    from src import llm

    monkeypatch.setenv(ai_gateway.VAR_ROTEAMENTO, "true")
    _chaves(monkeypatch, "sk-x", "g-y")

    def openai_quebrada(s, u, k, **kw):
        raise llm.ErroGeracaoIA("cota excedida")

    monkeypatch.setattr(llm, "_chamar_openai", openai_quebrada)
    monkeypatch.setattr(llm, "_chamar_gemini", lambda s, u, k, **kw: "DO GEMINI")

    assert llm.chamar_ia_texto("s", "u",
                               finalidade="tarefa-generica-zz") == "DO GEMINI"


# ---------------------------------------------------------------------------
# 5) ONDE A POLÍTICA ESTÁ LIGADA — e onde ela NÃO está
# ---------------------------------------------------------------------------
def _devcontainer() -> dict:
    import json
    import pathlib
    import re

    bruto = (pathlib.Path(__file__).resolve().parent.parent
             / ".devcontainer" / "devcontainer.json").read_text()
    # JSONC: o arquivo tem comentários, e eles são a documentação da
    # decisão. Tirar antes de validar é mais honesto que exigir JSON puro.
    return json.loads(re.sub(r"^\s*//.*$", "", bruto, flags=re.M))


def test_o_roteamento_esta_ligado_em_desenvolvimento():
    """
    Desenvolvimento é onde a política tem que ser exercitada primeiro.

    Aqui uma geração que caia para motor não homologado FALHA em vez de
    rebaixar em silêncio — e é com o servidor ao lado que se descobre se
    a política ficou estreita demais, não em produção.
    """
    ambiente = _devcontainer().get("containerEnv") or {}
    assert ambiente.get("OMNIROUTE_ROUTING_ENABLED") == "true", (
        "o roteamento saiu do devcontainer: desenvolvimento voltou a ter "
        "fallback irrestrito para documento oficial")


def test_o_gateway_continua_desligado_em_desenvolvimento():
    """
    Ligar o roteamento é uma decisão; ligar o GATEWAY é outra.

    `OMNIROUTE_ENABLED` manda os motores compatíveis por um endereço
    externo, e não há gateway rodando. Ligá-la sem `OMNIROUTE_BASE_URL`
    não faria efeito hoje — mas deixaria a chave armada para o dia em que
    alguém preencher a base por outro motivo.
    """
    ambiente = _devcontainer().get("containerEnv") or {}
    assert "OMNIROUTE_ENABLED" not in ambiente
    assert "OMNIROUTE_BASE_URL" not in ambiente


def test_producao_nao_herda_o_roteamento_do_devcontainer():
    """
    O deploy é Streamlit Cloud: ele instala `requirements.txt` e
    `packages.txt`, e não lê `.devcontainer/`. Esta prova existe para que
    ninguém confunda "ligado em desenvolvimento" com "ligado", e para
    pegar o dia em que alguém tentar ligar em produção por um atalho.
    """
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parent.parent
    for arquivo in ("requirements.txt", "packages.txt"):
        texto = (raiz / arquivo).read_text()
        assert "OMNIROUTE" not in texto.upper(), (
            f"{arquivo} ganhou uma variável de roteamento — ele é o que "
            "o Streamlit Cloud instala, e ligar produção é ato separado")


# ---------------------------------------------------------------------------
# 6) A POLÍTICA NÃO PODE SER MUDADA PELA TELA
# ---------------------------------------------------------------------------
def test_as_chaves_vem_do_ambiente_e_nao_do_banco():
    """
    `config_app` é editável pelo painel do administrador. Uma política de
    roteamento que um usuário autenticado muda pela tela não é política —
    é sugestão. O requisito é explícito: resposta de usuário nunca pode
    alterar provider, segredo ou política de roteamento.
    """
    fonte = (
        __import__("pathlib").Path(ai_gateway.__file__).read_text())
    assert "os.environ" in fonte
    assert "obter_config" not in fonte, (
        "o gateway passou a ler a política do banco, que o painel edita")
