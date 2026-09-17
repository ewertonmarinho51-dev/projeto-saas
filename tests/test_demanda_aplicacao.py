"""
Da tabela consolidada para a lista canônica do processo.

§14: a consolidação alimenta o mecanismo de itens que já existe. Não
cria segunda lista. Depois de aplicar, o processo tem uma planilha
orçamentária comum — a mesma que o DFD, o ETP e o edital leem.

A decisão estrutural que este arquivo protege está em
`test_a_quantidade_por_secretaria_nao_vira_coluna_de_item`. A
quantidade de cada secretaria é informação da CONSOLIDAÇÃO, não do item:
virasse campo do item, `planilha.colunas_extra` a transformaria numa
coluna em todo documento exportado do processo — doze colunas de
secretaria dentro do edital. O módulo de pesquisa de preços já tinha
tropeçado nisso e deixou o aviso escrito em `precos/aplicacao.py`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src import planilha
from src.demanda import aplicacao, consolidacao
from src.demanda.extracao import DFD, ItemDemanda


def _origem(sigla, itens, numero="1"):
    return consolidacao.Origem(
        secretaria=sigla, arquivo=f"{sigla}.pdf",
        dfds=(DFD(numero=numero, itens=tuple(itens)),))


def _item(codigo, qtd, unidade="UNIDADE", descricao="CANETA"):
    return ItemDemanda(codigo=codigo, descricao=descricao,
                       quantidade=Decimal(str(qtd)), unidade=unidade)


def _consolidado():
    return consolidacao.consolidar([
        _origem("SEMAFI", [_item("111111", 30), _item("222222", 5, "CAIXA")]),
        _origem("SEMEC", [_item("111111", 70)]),
    ])


# ---------------------------------------------------------------------------
# A lista canônica
# ---------------------------------------------------------------------------
def test_aplicar_produz_itens_no_esquema_da_planilha():
    dados, _ = aplicacao.aplicar({}, _consolidado())

    assert dados["itens"]
    for item in dados["itens"]:
        for campo in planilha.CAMPOS_ITEM:
            assert campo in item


def test_a_quantidade_canonica_e_o_total_consolidado():
    dados, _ = aplicacao.aplicar({}, _consolidado())

    caneta = next(i for i in dados["itens"] if i["codigo"] == "111111")
    assert str(caneta["quantidade"]) == "100"


def test_a_unidade_e_a_descricao_vem_do_consolidado():
    dados, _ = aplicacao.aplicar({}, _consolidado())

    caixa = next(i for i in dados["itens"] if i["codigo"] == "222222")
    assert caixa["unidade"] == "CAIXA"
    assert caixa["descricao"]


def test_a_quantidade_por_secretaria_nao_vira_coluna_de_item():
    """
    O erro que `precos/aplicacao.py` documenta: campo de item vira
    coluna em TODO documento exportado. Doze secretarias virariam doze
    colunas dentro do edital.
    """
    dados, _ = aplicacao.aplicar({}, _consolidado())

    extras = planilha.colunas_extra(dados["itens"])
    assert not any("SEMAFI" in c or "SEMEC" in c for c in extras)
    assert not any(c.lower().startswith("qtd_") for c in extras)


def test_a_alocacao_por_secretaria_fica_na_proveniencia():
    """Não vira coluna — mas também não se perde. §14."""
    dados, _ = aplicacao.aplicar({}, _consolidado())

    prov = dados[aplicacao.CHAVE_PROVENIENCIA]
    alocacao = prov["por_item"]["111111|UNIDADE"]["por_secretaria"]
    assert alocacao == {"SEMAFI": "30", "SEMEC": "70"}


def test_a_proveniencia_guarda_de_qual_arquivo_veio_cada_parcela():
    dados, _ = aplicacao.aplicar({}, _consolidado())

    origens = dados[aplicacao.CHAVE_PROVENIENCIA]["por_item"]["111111|UNIDADE"]["origens"]
    assert {o["arquivo"] for o in origens} == {"SEMAFI.pdf", "SEMEC.pdf"}
    assert all(o["dfd"] for o in origens)


def test_o_valor_unitario_nasce_vazio():
    """
    §15: valor que veio na Solicitação de Despesa não é preço praticado
    e não pode entrar como referência. O preço é assunto do módulo de
    pesquisa, com as regras dele.
    """
    dados, _ = aplicacao.aplicar({}, _consolidado())

    assert all(str(i["valor_unitario"]).strip() in ("", "0") for i in dados["itens"])


# ---------------------------------------------------------------------------
# O que impede a aplicação
# ---------------------------------------------------------------------------
def test_conflito_de_unidade_pendente_impede_aplicar():
    """
    §12: conflitos resolvidos ou explicitamente pendentes ANTES de
    alimentar o processo. Aplicar por cima gravaria uma quantidade que
    ninguém decidiu.
    """
    com_conflito = consolidacao.consolidar([
        _origem("A", [_item("111111", 10, "CAIXA")]),
        _origem("B", [_item("111111", 10, "UNIDADE")]),
    ])

    with pytest.raises(aplicacao.ErroAplicacao) as erro:
        aplicacao.aplicar({}, com_conflito)

    assert "111111" in str(erro.value)


def test_conflito_reconhecido_pelo_servidor_libera_a_aplicacao():
    """
    Reconhecer não é resolver automaticamente: é o servidor dizendo que
    viu e decidiu manter as duas linhas separadas, cada uma na sua
    unidade. A decisão fica registrada na proveniência.
    """
    com_conflito = consolidacao.consolidar([
        _origem("A", [_item("111111", 10, "CAIXA")]),
        _origem("B", [_item("111111", 7, "UNIDADE")]),
    ])

    dados, _ = aplicacao.aplicar({}, com_conflito, conflitos_aceitos=("111111",))

    assert len(dados["itens"]) == 2
    assert dados[aplicacao.CHAVE_PROVENIENCIA]["conflitos_aceitos"] == ["111111"]


def test_conta_que_nao_fecha_impede_aplicar():
    """
    A última barreira antes de gravar. Se a aritmética não fecha, o
    problema é anterior — e gravar mesmo assim transformaria um erro de
    soma em número oficial do processo.
    """
    import dataclasses
    bom = _consolidado()
    linha = dataclasses.replace(bom.linhas[0], total=Decimal("999"))
    quebrado = dataclasses.replace(bom, linhas=(linha,) + bom.linhas[1:])

    with pytest.raises(aplicacao.ErroAplicacao):
        aplicacao.aplicar({}, quebrado)


def test_consolidado_vazio_nao_apaga_a_planilha_existente():
    """
    Aplicar nada não é aplicar zero. Sem esta recusa, um upload que
    falhou apagaria a planilha que o servidor já tinha montado à mão.
    """
    dados_atuais = {"itens": [{"codigo": "999", "descricao": "JÁ EXISTIA",
                               "unidade": "UNIDADE", "quantidade": "5",
                               "valor_unitario": ""}]}

    with pytest.raises(aplicacao.ErroAplicacao):
        aplicacao.aplicar(dados_atuais, consolidacao.Consolidado())


def test_aplicar_nao_muda_o_dicionario_recebido():
    """
    O `dados` do processo é lido pela interface inteira. Mutar no lugar
    faria a tela mostrar o novo estado antes de o salvamento confirmar.
    """
    antes = {"orgao": "X", "itens": [{"codigo": "1"}]}
    copia = dict(antes)

    aplicacao.aplicar(antes, _consolidado())

    assert antes == copia


def test_os_demais_campos_do_processo_sobrevivem():
    dados, _ = aplicacao.aplicar({"orgao": "Prefeitura", "objeto": "Expediente"},
                                 _consolidado())

    assert dados["orgao"] == "Prefeitura"
    assert dados["objeto"] == "Expediente"


# ---------------------------------------------------------------------------
# O resumo que a tela mostra
# ---------------------------------------------------------------------------
def test_o_resumo_conta_o_que_entrou():
    _, resumo = aplicacao.aplicar({}, _consolidado())

    assert resumo["itens"] == 2
    assert resumo["secretarias"] == 2
    assert resumo["ocorrencias"] == 3


def test_o_resumo_registra_os_arquivos_nao_lidos():
    consolidado = consolidacao.consolidar([
        _origem("A", [_item("111111", 10)]),
        consolidacao.Origem(secretaria="SECULT", arquivo="secult.pdf",
                            status=consolidacao.IMAGEM),
    ])

    _, resumo = aplicacao.aplicar({}, consolidado)

    assert resumo["nao_lidos"] == ["secult.pdf"]
