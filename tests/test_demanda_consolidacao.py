"""
Consolidação: somar só o que é comprovadamente o mesmo item.

A chave de mesclagem não foi inventada aqui. Ela está escrita na
planilha que a prefeitura já produziu à mão, na aba Resumo:
"Consolidação por código do item + unidade de medida, com
rastreabilidade". Os arquivos reais sustentam a escolha — entre as dez
secretarias legíveis há 206 códigos distintos, 179 deles compartilhados,
e zero conflitos de unidade ou de descrição.

Zero conflito NOS ARQUIVOS DE HOJE não é zero conflito sempre, e é por
isso que o caminho de conflito existe e é testado: no dia em que duas
secretarias pedirem o mesmo código em CAIXA e em UNIDADE, a soma tem de
parar, não escolher.

A prova mais importante deste arquivo é
`test_o_total_e_a_soma_e_isso_e_verificavel`: o §12 exige que o total
seja demonstrável, não plausível.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.demanda import consolidacao
from src.demanda.extracao import DFD, ItemDemanda


def _item(codigo, qtd, unidade="UNIDADE", descricao="ITEM", **kw):
    return ItemDemanda(codigo=codigo, descricao=descricao,
                       quantidade=Decimal(str(qtd)), unidade=unidade, **kw)


def _origem(sigla, itens, arquivo=None, numero="1"):
    return consolidacao.Origem(
        secretaria=sigla,
        arquivo=arquivo or f"{sigla}.pdf",
        dfds=(DFD(numero=numero, orgao_nome=sigla, itens=tuple(itens)),),
    )


# ---------------------------------------------------------------------------
# A soma
# ---------------------------------------------------------------------------
def test_duas_secretarias_mesmo_codigo_e_unidade_somam():
    r = consolidacao.consolidar([
        _origem("SEMAFI", [_item("572705", 30)]),
        _origem("SEMAGRI", [_item("572705", 20)]),
    ])

    assert len(r.linhas) == 1
    linha = r.linhas[0]
    assert linha.total == Decimal("50")
    assert linha.por_secretaria == {"SEMAFI": Decimal("30"),
                                    "SEMAGRI": Decimal("20")}


def test_tres_secretarias():
    r = consolidacao.consolidar([
        _origem("A", [_item("111111", 20)]),
        _origem("B", [_item("111111", 35)]),
        _origem("C", [_item("111111", 10)]),
    ])

    assert r.linhas[0].total == Decimal("65")


def test_item_exclusivo_de_uma_secretaria_permanece():
    r = consolidacao.consolidar([
        _origem("A", [_item("111111", 5)]),
        _origem("B", [_item("222222", 7)]),
    ])

    assert {l.codigo for l in r.linhas} == {"111111", "222222"}
    assert all(l.total > 0 for l in r.linhas)


def test_dois_dfds_da_mesma_secretaria_somam():
    """
    O caso do SEMEC e do SEMS. As quantidades divergem entre os DFDs
    (2.000 contra 10.000): são demandas distintas, não reimpressão.
    """
    origem = consolidacao.Origem(
        secretaria="SEMEC", arquivo="semec.pdf",
        dfds=(DFD(numero="20260508007", itens=(_item("000763", 2000),)),
              DFD(numero="20260508009", itens=(_item("000763", 10000),))),
    )
    r = consolidacao.consolidar([origem])

    assert r.linhas[0].total == Decimal("12000")
    assert r.linhas[0].por_secretaria == {"SEMEC": Decimal("12000")}


def test_a_ordem_das_linhas_nao_muda_a_soma():
    a = consolidacao.consolidar([
        _origem("A", [_item("111111", 5), _item("222222", 7)]),
        _origem("B", [_item("222222", 3), _item("111111", 1)]),
    ])
    b = consolidacao.consolidar([
        _origem("B", [_item("111111", 1), _item("222222", 3)]),
        _origem("A", [_item("222222", 7), _item("111111", 5)]),
    ])

    assert {l.codigo: l.total for l in a.linhas} == {l.codigo: l.total for l in b.linhas}


def test_quantidade_decimal_e_zero_sobrevivem():
    r = consolidacao.consolidar([
        _origem("A", [_item("111111", "0.5")]),
        _origem("B", [_item("111111", "0.25")]),
        _origem("C", [_item("111111", 0)]),
    ])

    assert r.linhas[0].total == Decimal("0.75")
    assert r.linhas[0].por_secretaria["C"] == Decimal("0")


# ---------------------------------------------------------------------------
# O que NÃO soma
# ---------------------------------------------------------------------------
def test_mesmo_codigo_com_unidade_diferente_nao_soma():
    """
    §9. CAIXA e UNIDADE do mesmo código não são a mesma coisa, e não há
    fator de conversão no documento. Somar daria um número que parece
    certo e não é.
    """
    r = consolidacao.consolidar([
        _origem("A", [_item("111111", 10, unidade="CAIXA")]),
        _origem("B", [_item("111111", 10, unidade="UNIDADE")]),
    ])

    assert r.conflitos, "conflito de unidade tem de aparecer"
    conflito = r.conflitos[0]
    assert conflito.codigo == "111111"
    assert set(conflito.unidades) == {"CAIXA", "UNIDADE"}
    assert not any(l.total == Decimal("20") for l in r.linhas)


def test_o_conflito_de_unidade_nao_apaga_as_quantidades():
    """
    Conflito não é descarte: as duas linhas continuam visíveis, cada uma
    com a sua unidade, para o servidor decidir. Sumir com elas seria
    trocar um número errado por uma ausência silenciosa.
    """
    r = consolidacao.consolidar([
        _origem("A", [_item("111111", 10, unidade="CAIXA")]),
        _origem("B", [_item("111111", 7, unidade="UNIDADE")]),
    ])

    totais = {(l.codigo, l.unidade): l.total for l in r.linhas}
    assert totais[("111111", "CAIXA")] == Decimal("10")
    assert totais[("111111", "UNIDADE")] == Decimal("7")


def test_descricao_diferente_no_mesmo_codigo_e_registrada_mas_nao_bloqueia():
    """
    Os arquivos reais têm variação de redação para o mesmo código — o
    catálogo institucional é a autoridade, não a digitação de cada
    secretaria. Isso vira registro de divergência, não impedimento.
    """
    r = consolidacao.consolidar([
        _origem("A", [_item("111111", 10, descricao="CANETA AZUL")]),
        _origem("B", [_item("111111", 5, descricao="CANETA ESFEROGRÁFICA AZUL")]),
    ])

    assert r.linhas[0].total == Decimal("15")
    variacoes = r.linhas[0].variacoes_descricao
    assert len(variacoes) == 2


def test_codigos_diferentes_com_descricao_parecida_nunca_fundem():
    """
    §9: nunca fundir por semelhança textual. Dois códigos distintos são
    dois itens do catálogo, por mais parecidos que sejam os nomes.
    """
    r = consolidacao.consolidar([
        _origem("A", [_item("111111", 10, descricao="CANETA AZUL")]),
        _origem("B", [_item("222222", 10, descricao="CANETA AZUL")]),
    ])

    assert len(r.linhas) == 2


def test_arquivo_reenviado_nao_soma_duas_vezes():
    """§10: mesmo arquivo, mesmo hash, entra uma vez só."""
    itens = [_item("111111", 40)]
    r = consolidacao.consolidar([
        consolidacao.Origem(secretaria="A", arquivo="a.pdf", hash_arquivo="abc",
                            dfds=(DFD(numero="1", itens=tuple(itens)),)),
        consolidacao.Origem(secretaria="A", arquivo="a-copia.pdf", hash_arquivo="abc",
                            dfds=(DFD(numero="1", itens=tuple(itens)),)),
    ])

    assert r.linhas[0].total == Decimal("40")
    assert r.duplicatas == ("a-copia.pdf",)


def test_o_mesmo_dfd_em_arquivos_diferentes_entra_uma_vez():
    """
    Hash diferente (alguém reexportou o PDF) mas o MESMO número de DFD.
    O número é a identidade do documento; o arquivo é só o invólucro.
    """
    r = consolidacao.consolidar([
        consolidacao.Origem(secretaria="A", arquivo="a.pdf", hash_arquivo="h1",
                            dfds=(DFD(numero="20260101001",
                                      itens=(_item("111111", 40),)),)),
        consolidacao.Origem(secretaria="A", arquivo="a-reexportado.pdf",
                            hash_arquivo="h2",
                            dfds=(DFD(numero="20260101001",
                                      itens=(_item("111111", 40),)),)),
    ])

    assert r.linhas[0].total == Decimal("40")


# ---------------------------------------------------------------------------
# Prova matemática e rastreabilidade — §12
# ---------------------------------------------------------------------------
def test_o_total_e_a_soma_e_isso_e_verificavel():
    """
    O §12 exige total demonstrável, não plausível. `conferir()` refaz a
    conta a partir das ORIGENS, não a partir do próprio total — senão
    estaria comparando um número consigo mesmo.
    """
    r = consolidacao.consolidar([
        _origem("A", [_item("111111", 20), _item("222222", 3)]),
        _origem("B", [_item("111111", 35)]),
        _origem("C", [_item("111111", 10)]),
    ])

    laudo = consolidacao.conferir(r)
    assert laudo.fecha
    assert laudo.divergencias == ()
    linha = next(l for l in r.linhas if l.codigo == "111111")
    assert linha.total == Decimal("65")


def test_a_conferencia_acusa_quando_o_total_nao_fecha():
    """
    Uma prova que nunca falha não prova nada. Aqui o total é corrompido
    de propósito para mostrar que `conferir()` enxerga.
    """
    r = consolidacao.consolidar([
        _origem("A", [_item("111111", 20)]),
        _origem("B", [_item("111111", 35)]),
    ])
    adulterada = r.linhas[0].__class__(
        **{**r.linhas[0].__dict__, "total": Decimal("999")}) \
        if hasattr(r.linhas[0], "__dict__") else None
    if adulterada is None:
        import dataclasses
        adulterada = dataclasses.replace(r.linhas[0], total=Decimal("999"))
    corrompido = consolidacao.Consolidado(
        linhas=(adulterada,), conflitos=r.conflitos,
        duplicatas=r.duplicatas, secretarias=r.secretarias,
        nao_lidos=r.nao_lidos)

    laudo = consolidacao.conferir(corrompido)
    assert not laudo.fecha
    assert laudo.divergencias


def test_a_conferencia_refaz_a_conta_pelas_ORIGENS_e_nao_pelo_proprio_total():
    """
    Nasceu de uma mutação que escapou.

    A prova anterior corrompia só o `total` — e a conferência a pegava
    pela soma das colunas por secretaria, não pelas origens. Trocar a
    conta das origens por `linha.total` (comparar o número consigo
    mesmo) passava na suíte inteira, e a "prova matemática" do §12
    viraria uma tautologia sem ninguém perceber.

    Aqui o total E as colunas são adulterados juntos, de forma coerente.
    Só as origens discordam — então só a conta pelas origens salva.
    """
    import dataclasses

    r = consolidacao.consolidar([
        _origem("A", [_item("111111", 20)]),
        _origem("B", [_item("111111", 35)]),
    ])
    linha = r.linhas[0]
    assert linha.total == Decimal("55")

    mentira = dataclasses.replace(
        linha,
        total=Decimal("999"),
        por_secretaria={"A": Decimal("964"), "B": Decimal("35")},
    )
    corrompido = dataclasses.replace(r, linhas=(mentira,))

    laudo = consolidacao.conferir(corrompido)
    assert not laudo.fecha
    assert any("origens" in d for d in laudo.divergencias)


def test_cada_quantidade_aponta_para_o_arquivo_e_o_dfd():
    r = consolidacao.consolidar([
        _origem("SEMS", [_item("111111", 20)], arquivo="sems.pdf", numero="20260506010"),
    ])

    origem = r.linhas[0].origens[0]
    assert origem.secretaria == "SEMS"
    assert origem.arquivo == "sems.pdf"
    assert origem.dfd == "20260506010"
    assert origem.quantidade == Decimal("20")


def test_nenhuma_linha_de_entrada_se_perde():
    """
    A contagem de ocorrências tem de bater com o que entrou. É o teste
    que pegaria um item engolido por um `continue` mal colocado.
    """
    entradas = [
        _origem("A", [_item("111111", 1), _item("222222", 2)]),
        _origem("B", [_item("111111", 3), _item("333333", 4)]),
    ]
    r = consolidacao.consolidar(entradas)

    esperado = sum(len(d.itens) for o in entradas for d in o.dfds)
    assert sum(len(l.origens) for l in r.linhas) == esperado


# ---------------------------------------------------------------------------
# Arquivos não lidos
# ---------------------------------------------------------------------------
def test_arquivo_nao_lido_aparece_e_nao_vira_zero():
    """
    SECULT e SEMEL, os PDFs de imagem. Entram na lista de não lidos; não
    entram como secretaria com quantidade zero, que faria a tabela dizer
    "essa secretaria não pediu nada".
    """
    r = consolidacao.consolidar([
        _origem("A", [_item("111111", 10)]),
        consolidacao.Origem(secretaria="SECULT", arquivo="secult.pdf",
                            dfds=(), status="imagem"),
    ])

    assert r.nao_lidos == ("secult.pdf",)
    assert "SECULT" not in r.secretarias
    assert "SECULT" not in r.linhas[0].por_secretaria


def test_consolidar_sem_nada_nao_explode():
    r = consolidacao.consolidar([])

    assert r.linhas == ()
    assert consolidacao.conferir(r).fecha
