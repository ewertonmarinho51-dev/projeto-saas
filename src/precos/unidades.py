"""
Normalização de unidade de fornecimento — determinística, e que RECUSA.

É o ponto mais perigoso de uma pesquisa de preços. "R$ 18,00 a caixa" e
"R$ 18,00 a unidade" são o mesmo número e contratações completamente
diferentes; comparar os dois sem prova do fator de embalagem produz uma
cesta que parece defensável e não é.

A regra deste módulo é uma só, e ela é conservadora de propósito:

> só converte quando o fator de embalagem está EXPLÍCITO no dado da
> fonte. Não havendo fator, a referência não é convertida nem descartada
> — ela fica com a unidade original e um motivo registrado, e quem decide
> é o revisor.

A IA pode sugerir equivalência (§13 do prompt do módulo), mas nada aqui
aceita sugestão: este arquivo só olha para dado de fonte oficial.
"""

from __future__ import annotations

import unicodedata
from decimal import Decimal

from .modelo import Referencia

# ---------------------------------------------------------------------------
# Dicionário determinístico de unidades
#
# As siglas vêm do que as fontes oficiais realmente devolvem em
# `siglaUnidadeFornecimento` / `unidadeMedida` (Compras.gov) — não de uma
# tabela inventada. Cada entrada diz para qual unidade CANÔNICA a sigla
# aponta; siglas desconhecidas continuam desconhecidas.
# ---------------------------------------------------------------------------
_CANONICAS = {
    "UNIDADE": ("UNIDADE", ("UN", "UND", "UNID", "UNIDADE", "PC", "PCA",
                            "PECA", "PÇ")),
    "CAIXA": ("CAIXA", ("CX", "CAIXA", "CAIXAS")),
    "PACOTE": ("PACOTE", ("PCT", "PACOTE", "PACOTES", "PC.")),
    "RESMA": ("RESMA", ("RM", "RESMA", "RESMAS")),
    "ROLO": ("ROLO", ("RL", "ROLO", "ROLOS")),
    "FRASCO": ("FRASCO", ("FR", "FRASCO", "FRASCOS")),
    "JOGO": ("JOGO", ("JG", "JOGO", "JOGOS", "KIT", "CONJUNTO", "CJ")),
    "CARTELA": ("CARTELA", ("CT", "CARTELA", "CARTELAS")),
    "ESTOJO": ("ESTOJO", ("ET", "ESTOJO", "ESTOJOS")),
    "BLOCO": ("BLOCO", ("BL", "BLOCO", "BLOCOS")),
    "FOLHA": ("FOLHA", ("FL", "FLS", "FOLHA", "FOLHAS")),
    "METRO": ("METRO", ("M", "MT", "METRO", "METROS")),
    "QUILOGRAMA": ("QUILOGRAMA", ("KG", "QUILO", "QUILOGRAMA", "QUILOS")),
    "GRAMA": ("GRAMA", ("G", "GR", "GRAMA", "GRAMAS")),
    "LITRO": ("LITRO", ("L", "LT", "LITRO", "LITROS")),
    "MILILITRO": ("MILILITRO", ("ML", "MILILITRO", "MILILITROS")),
}

_POR_SIGLA: dict[str, str] = {}
for _canonica, (_nome, _siglas) in _CANONICAS.items():
    for _s in _siglas:
        _POR_SIGLA[_s] = _nome

# Unidades que EMBALAM outras: só elas admitem fator de embalagem. Não faz
# sentido perguntar quantas unidades há dentro de um quilograma.
EMBALAGENS = {"CAIXA", "PACOTE", "RESMA", "ROLO", "JOGO", "CARTELA",
              "ESTOJO", "BLOCO", "FRASCO"}

# Conversões de GRANDEZA, onde o fator é uma constante física e não
# depende de como o fornecedor embalou. Estas são seguras por definição.
_FATOR_DE_GRANDEZA = {
    ("GRAMA", "QUILOGRAMA"): Decimal("0.001"),
    ("QUILOGRAMA", "GRAMA"): Decimal("1000"),
    ("MILILITRO", "LITRO"): Decimal("0.001"),
    ("LITRO", "MILILITRO"): Decimal("1000"),
}

MOTIVO_SEM_FATOR = (
    "unidade da referência é embalagem e a fonte não informou quantos "
    "itens ela contém — preço não convertido para a unidade do processo")
MOTIVO_DESCONHECIDA = (
    "unidade da referência não consta do dicionário de unidades — "
    "conversão não tentada")
MOTIVO_INCOMPATIVEL = (
    "unidades de grandezas diferentes e sem fator de embalagem — "
    "conversão impossível com o dado disponível")


def canonizar(sigla: str | None) -> str | None:
    """
    Sigla da fonte → unidade canônica. `None` quando não reconhecida.

    Devolver `None` em vez de chutar é o comportamento correto: unidade
    desconhecida vira recusa de conversão, não conversão errada.
    """
    if not sigla:
        return None
    texto = unicodedata.normalize("NFKD", str(sigla).strip().upper())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.rstrip(".")
    return _POR_SIGLA.get(texto)


def fator_de_conversao(origem: str | None, destino: str | None,
                       capacidade: Decimal | None) -> tuple[Decimal | None, str]:
    """
    Quantas unidades de DESTINO cabem em uma de ORIGEM.

    Devolve `(fator, motivo)`. Fator `None` significa **não converter** —
    e o motivo diz por quê, em português, para ir direto ao relatório.
    """
    o, d = canonizar(origem), canonizar(destino)
    if o is None or d is None:
        return None, MOTIVO_DESCONHECIDA
    if o == d:
        return Decimal(1), ""

    fator = _FATOR_DE_GRANDEZA.get((o, d))
    if fator is not None:
        return fator, ""

    # Embalagem → unidade: só com capacidade EXPLÍCITA e positiva.
    # `capacidadeUnidadeFornecimento` vem 0.0 quando não informada, e
    # tratar esse zero como "uma unidade" seria inventar o fator.
    if o in EMBALAGENS and d == "UNIDADE":
        if capacidade is None or capacidade <= 0:
            return None, MOTIVO_SEM_FATOR
        return capacidade, ""

    if d in EMBALAGENS and o == "UNIDADE":
        if capacidade is None or capacidade <= 0:
            return None, MOTIVO_SEM_FATOR
        return Decimal(1) / capacidade, ""

    return None, MOTIVO_INCOMPATIVEL


def normalizar(referencia: Referencia, unidade_do_processo: str | None
               ) -> Referencia:
    """
    Preenche `unidade_normalizada` e `valor_unitario_normalizado` — ou
    recusa e diz por quê.

    A referência é devolvida sempre: recusar a conversão nunca descarta o
    dado coletado. O que muda é que ela chega ao revisor com o preço na
    unidade original e o motivo visível.
    """
    if not referencia.tem_preco:
        return referencia.com_motivo("referência sem preço unitário")

    destino = canonizar(unidade_do_processo)
    if destino is None:
        # Sem unidade no item do processo não há para onde converter; o
        # preço segue válido na unidade da própria fonte.
        referencia.unidade_normalizada = canonizar(
            referencia.unidade_original)
        referencia.valor_unitario_normalizado = \
            referencia.valor_unitario_original
        return referencia.com_motivo(
            "item do processo sem unidade declarada — preço mantido na "
            "unidade da fonte")

    fator, motivo = fator_de_conversao(
        referencia.unidade_original, unidade_do_processo,
        referencia.capacidade_embalagem)

    if fator is None:
        referencia.unidade_normalizada = None
        referencia.valor_unitario_normalizado = None
        return referencia.com_motivo(motivo)

    # preço por embalagem ÷ itens por embalagem = preço por item
    referencia.unidade_normalizada = destino
    referencia.valor_unitario_normalizado = (
        referencia.valor_unitario_original / fator)
    if fator != 1:
        referencia.com_motivo(
            f"preço convertido de {canonizar(referencia.unidade_original)} "
            f"para {destino} pelo fator {format(fator, 'f')} informado pela "
            "fonte")
    return referencia


def comparavel(referencia: Referencia) -> bool:
    """
    A referência pode entrar na cesta?

    Só entra o que tem preço NA UNIDADE DO PROCESSO. Sem isso, os números
    não somam a mesma coisa — e uma média entre caixa e unidade é um
    número sem significado administrativo.
    """
    return (referencia.valor_unitario_normalizado is not None
            and referencia.valor_unitario_normalizado > 0)
