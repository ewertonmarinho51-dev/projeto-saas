"""
Cache, idempotência, política de modelo e retentativa.

O FIO QUE LIGA ESTAS PROVAS

Cada uma delas guarda uma economia que só é economia enquanto não
muda o que sai. Um cache que devolve o documento errado, um teto que
trunca a cláusula, uma retentativa que deixa de tentar o que valia:
todos "reduzem o custo", e todos são defeito.
"""

from __future__ import annotations

import pytest
import streamlit as st

from src import cache_geracao, llm, politica_ia


@pytest.fixture(autouse=True)
def _flags_ligadas(monkeypatch):
    """As medidas nascem desligadas; estas provas medem o efeito delas."""
    monkeypatch.setattr(cache_geracao, "ativo", lambda: True)
    monkeypatch.setattr(politica_ia, "ativo", lambda: True)
    st.session_state.pop(cache_geracao.CHAVE_NA_SESSAO, None)
    yield
    st.session_state.pop(cache_geracao.CHAVE_NA_SESSAO, None)


# ---------------------------------------------------------------------------
# A chave do cache
# ---------------------------------------------------------------------------
def test_o_mesmo_pedido_tem_a_mesma_chave():
    a = cache_geracao.chave("openai", "gpt-5-mini", "sistema", "usuário")
    b = cache_geracao.chave("openai", "gpt-5-mini", "sistema", "usuário")
    assert a == b


@pytest.mark.parametrize("mudanca", [
    {"motor": "gemini"},
    {"modelo": "gpt-4o-mini"},
    {"system_prompt": "outro sistema"},
    {"user_prompt": "outro usuário"},
])
def test_qualquer_coisa_que_mude_a_saida_muda_a_chave(mudanca):
    """
    O modo de falha deste tipo de cache é sempre o mesmo: alguém
    acrescenta uma fonte ao prompt e esquece de somá-la à chave, e o
    sistema passa a servir documento montado com contexto velho.

    Aqui isso é impossível por construção, porque a chave é o hash dos
    PROMPTS PRONTOS — o formulário, a planilha, a cadeia aprovada e o
    RAG já estão dentro deles. Esta prova mede cada eixo.
    """
    base = {"motor": "openai", "modelo": "gpt-5-mini",
            "system_prompt": "sistema", "user_prompt": "usuário"}
    assert cache_geracao.chave(**base) != cache_geracao.chave(**{**base, **mudanca})


def test_a_versao_do_formato_invalida_o_guardado(monkeypatch):
    antes = cache_geracao.chave("openai", "m", "s", "u")
    monkeypatch.setattr(cache_geracao, "VERSAO_DO_FORMATO",
                        cache_geracao.VERSAO_DO_FORMATO + 1)
    assert cache_geracao.chave("openai", "m", "s", "u") != antes


def test_a_sessao_devolve_o_que_guardou():
    chave = cache_geracao.chave("openai", "m", "s", "u")
    assert cache_geracao.buscar(chave, None) is None
    cache_geracao.guardar(chave, None, "dfd", {"texto": "documento",
                                               "motor": "openai"})
    assert cache_geracao.buscar(chave, None)["texto"] == "documento"


def test_geracao_vazia_nunca_entra_no_cache():
    """
    Guardar "" faria todo pedido idêntico devolver vazio para sempre —
    um defeito que se auto-perpetua e que nenhuma tela acusaria.
    """
    chave = cache_geracao.chave("openai", "m", "s", "u")
    cache_geracao.guardar(chave, None, "dfd", {"texto": "   "})
    assert cache_geracao.buscar(chave, None) is None


def test_flag_desligada_nao_guarda_nem_devolve(monkeypatch):
    monkeypatch.setattr(cache_geracao, "ativo", lambda: False)
    chave = cache_geracao.chave("openai", "m", "s", "u")
    cache_geracao.guardar(chave, None, "dfd", {"texto": "documento"})
    assert cache_geracao.buscar(chave, None) is None


# ---------------------------------------------------------------------------
# Idempotência no provedor
# ---------------------------------------------------------------------------
def test_a_chave_de_idempotencia_acompanha_o_pedido():
    """
    O caso que o cache local não alcança: o provedor gerou, cobrou, e a
    resposta não chegou. Sem esta chave, a retentativa é uma segunda
    geração do mesmo documento — paga duas vezes.
    """
    a = llm._cabecalhos_de_idempotencia("s", "u", "gpt-5-mini")
    b = llm._cabecalhos_de_idempotencia("s", "u", "gpt-5-mini")
    c = llm._cabecalhos_de_idempotencia("s", "outro", "gpt-5-mini")
    assert a == b, "a repetição do MESMO pedido tem de reusar a chave"
    assert a != c, "pedidos diferentes nunca podem compartilhar a chave"
    assert a["Idempotency-Key"].startswith("govdocs-")


# ---------------------------------------------------------------------------
# Teto de saída
# ---------------------------------------------------------------------------
def test_o_teto_de_cada_documento_cabe_a_maior_saida_ja_medida():
    """
    Os tetos vêm de `docs/custo/producao.json`. Um teto abaixo do que a
    produção já gerou trunca documento no meio da cláusula — dano muito
    maior que a economia, e a razão de a folga existir.
    """
    maior_saida_em_producao = {"dfd": 4152, "etp": 8421, "tr": 10101,
                               "auditor": 2747, "corretor": 14905}
    for tarefa, observado in maior_saida_em_producao.items():
        assert politica_ia.teto_de_saida(tarefa, "gpt-4o-mini") >= observado, (
            f"{tarefa}: o teto é menor que a maior saída já medida")


def test_modelo_de_raciocinio_ganha_folga():
    """
    Em gpt-5/o-series o teto inclui os tokens de RACIOCÍNIO. Apertá-lo
    produz resposta VAZIA, não resposta curta — foi o que motivou o
    `_RespostaVazia` do `llm.py`.
    """
    assert (politica_ia.teto_de_saida("dfd", "gpt-5-mini")
            > politica_ia.teto_de_saida("dfd", "gpt-4o-mini"))


def test_nenhum_teto_ultrapassa_o_de_hoje():
    for tarefa in politica_ia.TAREFAS:
        for modelo in ("gpt-4o-mini", "gpt-5-mini"):
            assert (politica_ia.teto_de_saida(tarefa, modelo)
                    <= politica_ia.TETO_PADRAO)


def test_flag_desligada_mantem_o_teto_unico(monkeypatch):
    monkeypatch.setattr(politica_ia, "ativo", lambda: False)
    assert politica_ia.teto_de_saida("auditor", "gpt-4o-mini") == 16384


# ---------------------------------------------------------------------------
# Política de modelo
# ---------------------------------------------------------------------------
def test_nenhum_documento_da_fase_preparatoria_e_economico():
    """
    A regra do enunciado: nunca sacrificar a qualidade documental por
    custo. Mover um documento para a classe econômica é uma decisão
    deliberada — e esta prova a torna visível no diff.
    """
    for doc in ("dfd", "etp", "mapa_riscos", "tr", "edital", "arp"):
        assert politica_ia.classe(doc) == politica_ia.REDACAO


def test_auditoria_e_correcao_sao_estruturadas():
    for tarefa in ("auditor", "corretor"):
        assert politica_ia.classe(tarefa) == politica_ia.ESTRUTURADA


def test_sem_modelo_economico_configurado_nada_troca(monkeypatch):
    """
    O padrão é inerte. Trocar o modelo de alguém sem que essa pessoa
    tenha escolhido o modelo novo seria decidir por ela.
    """
    monkeypatch.setattr(politica_ia, "modelo_economico_configurado",
                        lambda: "")
    assert politica_ia.modelos_para(
        "auditor", ["gpt-5-mini", "gpt-4o-mini"], "openai") == \
        ["gpt-5-mini", "gpt-4o-mini"]


def test_o_modelo_economico_entra_na_frente_sem_remover_o_principal(monkeypatch):
    """
    O principal continua na lista, atrás. Se o econômico não existir na
    conta, a troca de modelo já existente cai de volta para ele — a
    tarefa não falha por causa de uma configuração errada.
    """
    monkeypatch.setattr(politica_ia, "modelo_economico_configurado",
                        lambda: "gpt-4o-mini")
    lista = politica_ia.modelos_para("auditor", ["gpt-5-mini", "gpt-4o"],
                                     "openai")
    assert lista[0] == "gpt-4o-mini"
    assert "gpt-5-mini" in lista


def test_a_redacao_nunca_troca_de_modelo(monkeypatch):
    monkeypatch.setattr(politica_ia, "modelo_economico_configurado",
                        lambda: "gpt-4o-mini")
    assert politica_ia.modelos_para("tr", ["gpt-5-mini"], "openai") == \
        ["gpt-5-mini"]


def test_o_modelo_economico_da_openai_nao_vaza_para_outro_motor(monkeypatch):
    """`gpt-4o-mini` pedido ao Gemini é um modelo que não existe lá."""
    monkeypatch.setattr(politica_ia, "modelo_economico_configurado",
                        lambda: "gpt-4o-mini")
    assert politica_ia.modelos_para("auditor", ["gemini-2.5-flash"],
                                    "gemini") == ["gemini-2.5-flash"]


# ---------------------------------------------------------------------------
# Custo: medido ou nulo, nunca presumido
# ---------------------------------------------------------------------------
def test_sem_preco_configurado_o_custo_e_nulo(monkeypatch):
    monkeypatch.setattr(politica_ia, "_preco", lambda *_: None)
    assert politica_ia.custo_estimado("gpt-5-mini", 1000, 500) is None


def test_com_preco_configurado_o_custo_e_calculado(monkeypatch):
    precos = {("gpt-5-mini", "ENTRADA"): 1.50, ("gpt-5-mini", "SAIDA"): 12.00}
    monkeypatch.setattr(politica_ia, "_preco",
                        lambda m, d: precos.get((m, d)))
    # 1.000.000 de entrada × 1,50 + 100.000 de saída × 12,00/1.000.000
    assert politica_ia.custo_estimado("gpt-5-mini", 1_000_000, 100_000) == \
        pytest.approx(1.50 + 1.20)


# ---------------------------------------------------------------------------
# Retentativa: repetir só o que pode dar outro resultado
# ---------------------------------------------------------------------------
class _Falha(Exception):
    pass


@pytest.mark.parametrize("mensagem, classe, repete", [
    ("Error code: 401 - Incorrect API key provided", llm.CLASSE_AUTENTICACAO, False),
    ("insufficient_quota: You exceeded your current quota", llm.CLASSE_CREDITO, False),
    ("invalid_request_error: context_length_exceeded", llm.CLASSE_VALIDACAO, False),
    ("Error code: 404 - The model `x` does not exist", llm.CLASSE_MODELO, False),
    ("Error code: 429 - Rate limit reached for gpt-5-mini", llm.CLASSE_LIMITE, True),
    ("Request timed out.", llm.CLASSE_REDE, True),
    ("Connection error.", llm.CLASSE_REDE, True),
])
def test_cada_falha_e_classificada_e_so_repete_o_que_vale(mensagem, classe,
                                                          repete):
    """
    Antes, QUALQUER falha que não fosse de modelo era repetida três
    vezes com espera de 2s e 4s. Chave inválida, três vezes. Crédito
    esgotado, três vezes. Nenhuma delas muda de resposta por repetição:
    o que se ganhava era três vezes o tempo de tela.
    """
    erro = _Falha(mensagem)
    assert llm.classificar_erro(erro) == classe
    assert llm.vale_retentar(erro) is repete


def test_credito_esgotado_nao_e_confundido_com_limite_de_ritmo():
    """
    `insufficient_quota` também carrega 429. Tratá-lo como limite de
    ritmo faria o sistema esperar e repetir três vezes uma conta sem
    crédito, que só volta a funcionar quando alguém pagar.
    """
    erro = _Falha("Error code: 429 - insufficient_quota, check your billing")
    assert llm.classificar_erro(erro) == llm.CLASSE_CREDITO
    assert not llm.vale_retentar(erro)


def test_resposta_vazia_troca_de_modelo_e_nao_repete():
    vazia = llm._RespostaVazia("conteúdo vazio (finish_reason=length)")
    assert llm.classificar_erro(vazia) == llm.CLASSE_VAZIA
    assert not llm.vale_retentar(vazia)
    assert llm._trocar_de_modelo(vazia)


def test_falha_desconhecida_continua_com_direito_a_retentativa():
    """
    A mutação que importa: classificar tudo que não se reconhece como
    irrecuperável tiraria a retentativa de falhas transitórias que
    ninguém catalogou ainda — e uma indisponibilidade de dois segundos
    viraria documento não gerado.
    """
    erro = _Falha("algo que ninguém previu")
    assert llm.classificar_erro(erro) == llm.CLASSE_DESCONHECIDA
    assert llm.vale_retentar(erro)


def test_toda_tarefa_registrada_tem_operacao_declarada():
    """
    `operacao` é o que separa a REDAÇÃO do trabalho sobre o que já foi
    escrito. Em produção, 65 das 90 chamadas bem-sucedidas eram de
    auditor e corretor — sem a coluna, o custo por documento não pode
    ser apurado.
    """
    for tarefa in ("dfd", "etp", "mapa_riscos", "tr"):
        assert llm._operacao_da_tarefa(tarefa) == "documento"
    assert llm._operacao_da_tarefa("auditor") == "auditoria"
    assert llm._operacao_da_tarefa("corretor") == "correcao"
