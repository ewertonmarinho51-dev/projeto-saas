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
from dataclasses import dataclass
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
    # "PC." não está aqui: `canonizar` tira o ponto final antes da busca,
    # e "PC" é UNIDADE — a entrada nunca era alcançada. "PAC" é como
    # portais municipais registram o pacote (visto no dossiê, J06).
    "PACOTE": ("PACOTE", ("PCT", "PAC", "PACOTE", "PACOTES")),
    "RESMA": ("RESMA", ("RM", "RESMA", "RESMAS")),
    # "EMB" é como o Compras.gov registra o papel A4 (14/10/2026: 436 de
    # 517 compras do PDM 19746), sempre com a capacidade em folhas.
    "EMBALAGEM": ("EMBALAGEM", ("EMB", "EMBALAGEM", "EMBALAGENS")),
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
    # Unidades que só casam com elas mesmas (fator 1): entram para que o
    # item de serviço ou de embalagem comum não fique sem unidade válida.
    # Siglas ambíguas ("PT": pote ou pacote? "LT": litro ou lata?) ficam
    # de fora de propósito — melhor desconhecida que convertida errado.
    "PAR": ("PAR", ("PR", "PAR", "PARES")),
    "SACO": ("SACO", ("SC", "SACO", "SACOS")),
    "FARDO": ("FARDO", ("FD", "FARDO", "FARDOS")),
    "GALAO": ("GALAO", ("GL", "GALAO", "GALOES")),
    "LATA": ("LATA", ("LATA", "LATAS")),
    "TUBO": ("TUBO", ("TB", "TUBO", "TUBOS")),
    "POTE": ("POTE", ("POTE", "POTES")),
    "BOBINA": ("BOBINA", ("BB", "BOBINA", "BOBINAS")),
    "METRO_QUADRADO": ("METRO QUADRADO", ("M2", "METRO QUADRADO",
                                          "METROS QUADRADOS")),
    "METRO_CUBICO": ("METRO CUBICO", ("M3", "METRO CUBICO",
                                      "METROS CUBICOS")),
    "SERVICO": ("SERVICO", ("SV", "SERV", "SERVICO", "SERVICOS")),
    "HORA": ("HORA", ("H", "HR", "HORA", "HORAS")),
    "DIARIA": ("DIARIA", ("DIARIA", "DIARIAS")),
    "MES": ("MES", ("MES", "MESES")),
    # serviço medido por deslocamento (frete, entrega): só casa consigo
    "VIAGEM": ("VIAGEM", ("VIAGEM", "VIAGENS")),
}

_POR_SIGLA: dict[str, str] = {}
for _canonica, (_nome, _siglas) in _CANONICAS.items():
    for _s in _siglas:
        _POR_SIGLA[_s] = _nome

# Unidades que EMBALAM outras: só elas admitem fator de embalagem. Não faz
# sentido perguntar quantas unidades há dentro de um quilograma.
EMBALAGENS = {"CAIXA", "PACOTE", "RESMA", "EMBALAGEM", "ROLO", "JOGO",
              "CARTELA",
              "ESTOJO", "BLOCO", "FRASCO", "SACO", "FARDO", "GALAO", "LATA",
              "TUBO", "POTE", "BOBINA"}

# Conversões de GRANDEZA, onde o fator é uma constante física e não
# depende de como o fornecedor embalou. Estas são seguras por definição.
# Unidades de CONTAGEM do item: a embalagem converte para elas pela
# capacidade explícita da fonte. A folha é contada como a unidade — o
# Compras.gov registra o papel em "EMB" sempre com a capacidade em folhas.
CONTAGEM = frozenset({"UNIDADE", "FOLHA"})

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
MOTIVO_ITEM_SEM_UNIDADE = (
    "a unidade do item ({unidade}) não é reconhecida — preço não "
    "comparado até o item ter unidade válida")


# Segunda auditoria de 18/10/2026 (N-06): 43 referências da cesta de
# Material de Expediente com fator ≥ 10× ou ≤ 0,1× — papel A4 "EMB" com
# capacidade 10 (uma caixa de 10 pacotes) lida como 10 folhas,
# normalizado a R$ 14.029,00 o pacote. Mas o fator extremo também é o da
# caixa com 10 pastas a R$ 60,00 (R$ 6,00 cada, entre pares a R$ 6,00).
# A regra: fator extremo só entra na cesta automática quando há ao menos
# 3 referências SEM conversão no item e o valor convertido fica entre 1/3
# e 3× da mediana delas. Fora disso, revisão manual, com o motivo.
FATOR_EXTREMO_ACIMA = Decimal("10")
FATOR_EXTREMO_ABAIXO = Decimal("0.1")
MINIMO_PARES_SEM_CONVERSAO = 3
FAIXA_DOS_PARES = Decimal("3")
REGRA_DO_FATOR_EXTREMO = (
    "fator ≥ 10× ou ≤ 0,1× só entra na cesta automática se houver ao menos "
    "3 referências sem conversão no item e o valor convertido ficar entre "
    "1/3 e 3× da mediana delas")
MOTIVO_FATOR_EXTREMO = (
    "[conversão extrema] {frase} — " + REGRA_DO_FATOR_EXTREMO + "; aqui, "
    "{pares}. Confira a capacidade da embalagem na fonte antes de incluir")


def _positivo(valor) -> Decimal | None:
    try:
        numero = Decimal(str(valor))
    except (ArithmeticError, ValueError, TypeError):
        return None
    return numero if numero.is_finite() and numero > 0 else None


def fator_extremo(original, normalizado) -> Decimal | None:
    """
    O fator aplicado (`original ÷ normalizado`) quando ele é extremo
    (≥ 10× ou ≤ 0,1×); `None` quando não é, ou quando não há os dois
    preços para calcular.
    """
    original, normalizado = _positivo(original), _positivo(normalizado)
    if original is None or normalizado is None:
        return None
    fator = original / normalizado
    if fator >= FATOR_EXTREMO_ACIMA or fator <= FATOR_EXTREMO_ABAIXO:
        return fator
    return None


def sem_conversao(original, normalizado) -> Decimal | None:
    """O preço, quando a referência está na unidade do item (fator 1)."""
    original, normalizado = _positivo(original), _positivo(normalizado)
    if original is None or original != normalizado:
        return None
    return normalizado


def _mediana(valores: list[Decimal]) -> Decimal:
    ordenados = sorted(valores)
    meio = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[meio]
    return (ordenados[meio - 1] + ordenados[meio]) / 2


@dataclass(frozen=True)
class ConversaoExtrema:
    """Fator extremo SEM respaldo dos pares: vai para revisão."""

    fator: Decimal
    original: Decimal
    normalizado: Decimal
    pares: int                     # referências sem conversão no item
    mediana: Decimal | None        # mediana delas (None sem pares)

    def frase(self) -> str:
        curto = self.fator.quantize(Decimal("0.000001")).normalize()
        return (f"preço convertido pelo fator "
                f"{format(curto, 'f').replace('.', ',')} (R$ {_brl(self.original)}"
                f" na unidade da fonte → R$ {_brl(self.normalizado)} na unidade "
                "do item)")

    def frase_dos_pares(self) -> str:
        if not self.pares:
            return "nenhuma referência sem conversão"
        return (f"{self.pares} sem conversão, mediana R$ "
                f"{_brl(self.mediana)}")

    def motivo(self) -> str:
        return MOTIVO_FATOR_EXTREMO.format(frase=self.frase(),
                                           pares=self.frase_dos_pares())


def _brl(valor) -> str:
    texto = f"{Decimal(str(valor)):,.2f}"
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


def conversao_extrema(original, normalizado,
                      pares_sem_conversao) -> ConversaoExtrema | None:
    """
    `None` quando a referência pode concorrer à cesta automática: fator
    comum, ou fator extremo com o valor convertido entre 1/3 e 3× da
    mediana de ao menos 3 referências sem conversão do mesmo item
    (`pares_sem_conversao`, os preços delas). Senão, o que vai no motivo.
    """
    fator = fator_extremo(original, normalizado)
    if fator is None:
        return None
    pares = [v for v in (_positivo(p) for p in pares_sem_conversao or [])
             if v is not None]
    mediana = _mediana(pares) if pares else None
    valor = _positivo(normalizado)
    if len(pares) >= MINIMO_PARES_SEM_CONVERSAO and \
            mediana / FAIXA_DOS_PARES <= valor <= mediana * FAIXA_DOS_PARES:
        return None
    return ConversaoExtrema(fator, _positivo(original), valor, len(pares),
                            mediana)


def unidade_valida(unidade: str | None) -> bool:
    """O item pode formar cesta com esta unidade? (dicionário canônico)"""
    return canonizar(unidade) is not None


def unidades_aceitas() -> list[str]:
    """Nomes canônicos, para a mensagem de erro e o seletor da tela."""
    return sorted({nome for nome, _ in _CANONICAS.values()})


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


def conteudo_declarado(descricao: str | None) -> Decimal | None:
    """
    Quantos itens a embalagem DO PROCESSO contém, quando a especificação
    diz ("pacote contendo 500 folhas", "caixa com 50 unidades").

    Só o que está escrito: sem a frase, `None`, e nenhuma conversão entre
    embalagens é tentada.
    """
    import re

    texto = unicodedata.normalize("NFKD", str(descricao or "").upper())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    achado = re.search(
        r"(?:CONTENDO|COM|C/)\s*(\d+(?:[.,]\d+)?)\s*"
        r"(?:FOLHAS|FLS?|UNIDADES|UNID|UND|UN|PECAS)\b", texto)
    if not achado:
        return None
    valor = Decimal(achado.group(1).replace(",", "."))
    return valor if valor > 0 else None


def fator_de_conversao(origem: str | None, destino: str | None,
                       capacidade: Decimal | None,
                       conteudo_destino: Decimal | None = None
                       ) -> tuple[Decimal | None, str]:
    """
    Quantas unidades de DESTINO cabem em uma de ORIGEM.

    Devolve `(fator, motivo)`. Fator `None` significa **não converter** —
    e o motivo diz por quê, em português, para ir direto ao relatório.

    `conteudo_destino` é quantos itens a embalagem do PROCESSO contém,
    quando a especificação declara. Com ele, embalagem converte para
    embalagem pela quantidade de dentro: EMB de 100 folhas é 1/5 de um
    pacote de 500 folhas; caixa de 12 canetas não é a caixa de 50.
    """
    o, d = canonizar(origem), canonizar(destino)
    if o is None or d is None:
        return None, MOTIVO_DESCONHECIDA
    ambos = (capacidade is not None and capacidade > 0
             and conteudo_destino is not None and conteudo_destino > 0)
    if o == d:
        if o in EMBALAGENS and ambos and capacidade != conteudo_destino:
            return capacidade / conteudo_destino, ""
        return Decimal(1), ""
    if o in EMBALAGENS and d in EMBALAGENS:
        if not ambos:
            return None, MOTIVO_SEM_FATOR
        return capacidade / conteudo_destino, ""

    fator = _FATOR_DE_GRANDEZA.get((o, d))
    if fator is not None:
        return fator, ""

    # Embalagem → unidade: só com capacidade EXPLÍCITA e positiva.
    # `capacidadeUnidadeFornecimento` vem 0.0 quando não informada, e
    # tratar esse zero como "uma unidade" seria inventar o fator.
    if o in EMBALAGENS and d in CONTAGEM:
        if capacidade is None or capacidade <= 0:
            return None, MOTIVO_SEM_FATOR
        return capacidade, ""

    if d in EMBALAGENS and o in CONTAGEM:
        if capacidade is None or capacidade <= 0:
            return None, MOTIVO_SEM_FATOR
        return Decimal(1) / capacidade, ""

    return None, MOTIVO_INCOMPATIVEL


def normalizar(referencia: Referencia, unidade_do_processo: str | None,
               conteudo_do_processo: Decimal | None = None) -> Referencia:
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
        # Sem unidade VÁLIDA no item não há para onde converter — e manter
        # o preço na unidade da fonte misturava caixa e unidade na mesma
        # média (dossiê BP, temas 10a e 11a: "Caixotes", "UNDADE" ou campo
        # vazio desligavam a normalização em silêncio). A referência fica
        # fora da cesta, com o motivo, até o item ganhar unidade válida.
        referencia.unidade_normalizada = None
        referencia.valor_unitario_normalizado = None
        return referencia.com_motivo(
            MOTIVO_ITEM_SEM_UNIDADE.format(
                unidade=str(unidade_do_processo or "").strip() or "vazia"))

    fator, motivo = fator_de_conversao(
        referencia.unidade_original, unidade_do_processo,
        referencia.capacidade_embalagem, conteudo_do_processo)

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
