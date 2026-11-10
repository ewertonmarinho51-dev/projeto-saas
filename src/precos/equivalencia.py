"""
Equivalência entre o item pesquisado e o candidato que a fonte devolveu —
separar RECUPERAÇÃO de ELEGIBILIDADE.

A busca ampliada (sinônimos, siglas, variantes de unidade) existe para
trazer "papel para impressão A4 75 g, resma 500 folhas" quando o item diz
"papel sulfite A4 75 g/m², 500 folhas". Trazer não é aceitar: o candidato
só vira preço automático quando a descrição da fonte CONFIRMA os atributos
essenciais do item. Quatro classes, nesta ordem de força:

* **mesmo item** — mesmo código oficial, ou descrição fortemente semelhante
  com os atributos essenciais conferidos;
* **equivalente comprovado** — redação diferente, atributos essenciais
  (gramatura, volume, massa, concentração, contagem, formato…) iguais. Entra
  na cesta proposta como o mesmo item;
* **similar para revisão** — falta prova de um atributo essencial (a fonte
  não diz a gramatura, a caixa não diz quantas unidades). Fica com o
  servidor, com o motivo e o comparativo; nunca entra sozinho;
* **incompatível** — divergência essencial (90 g/m² contra 75 g/m², 10 L
  contra 20 L). Sai da elegibilidade.

Nada aqui chama IA nem olha preço: os atributos vêm do texto da fonte e do
item, e a régua é determinística. Item sem atributo quantificável não é
classificado (`None`): o casamento por descrição segue como sempre foi.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

VERSAO = "2026-11-10.equivalencia.1"

MESMO_ITEM = "mesmo_item"
EQUIVALENTE = "equivalente"
SIMILAR = "similar"
INCOMPATIVEL = "incompativel"

ROTULO = {MESMO_ITEM: "mesmo item", EQUIVALENTE: "equivalente comprovado",
          SIMILAR: "similar para revisão", INCOMPATIVEL: "incompatível"}

# Identidade mínima de um equivalente comprovado: atributos essenciais
# iguais valem tanto quanto uma redação "fortemente semelhante" (0,6) do
# matching — e um pouco mais, para não depender do sinônimo.
IDENTIDADE_EQUIVALENTE = Decimal("0.75")
SEMELHANCA_MESMO_ITEM = Decimal("0.8")

# unidade lida → (dimensão, fator para a unidade base da dimensão)
_UNIDADES: dict[str, tuple[str, Decimal]] = {
    "G/M2": ("gramatura", Decimal(1)), "GM2": ("gramatura", Decimal(1)),
    "G/M": ("gramatura", Decimal(1)), "GRAMATURA": ("gramatura", Decimal(1)),
    "MG/ML": ("concentracao", Decimal(1)),
    "KG": ("massa", Decimal(1000)), "G": ("massa", Decimal(1)),
    "GR": ("massa", Decimal(1)), "GRAMAS": ("massa", Decimal(1)),
    "GRAMA": ("massa", Decimal(1)), "MG": ("massa", Decimal("0.001")),
    "MCG": ("massa", Decimal("0.000001")),
    "L": ("volume", Decimal(1000)), "LT": ("volume", Decimal(1000)),
    "LTS": ("volume", Decimal(1000)), "LITRO": ("volume", Decimal(1000)),
    "LITROS": ("volume", Decimal(1000)), "ML": ("volume", Decimal(1)),
    "W": ("potencia", Decimal(1)), "V": ("tensao", Decimal(1)),
    "VOLTS": ("tensao", Decimal(1)), "%": ("percentual", Decimal(1)),
    "FOLHAS": ("folhas", Decimal(1)), "FLS": ("folhas", Decimal(1)),
    "FL": ("folhas", Decimal(1)), "FOLHA": ("folhas", Decimal(1)),
    "COMPRIMIDOS": ("doses", Decimal(1)), "CPR": ("doses", Decimal(1)),
    "CAPSULAS": ("doses", Decimal(1)), "CAPS": ("doses", Decimal(1)),
}
_SIGLAS = sorted(_UNIDADES, key=len, reverse=True)
_QUANTIFICADO = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(" + "|".join(re.escape(s) for s in _SIGLAS)
    + r")(?![\w/])")
# Só A3–A6 pelo nome: "OFÍCIO" no catálogo é TIPO de papel
# ("SULFITE/APERGAMINHADO/OFÍCIO"), não formato. A dimensão em mm também
# prova o formato (297 x 210 = A4), pela tabela de `atributos`.
_FORMATO = re.compile(r"(?<![\w])(A[3-6])(?![\w])")
# resma sem contagem declarada é, por convenção do mercado, 500 folhas
_RESMA = re.compile(r"(?<![\w])RESMAS?(?![\w])")


_RUIDO = {"DE", "DA", "DO", "DAS", "DOS", "PARA", "COM", "SEM", "EM", "E",
          "TIPO", "ESPECIFICACAO", "MATERIAL", "COR", "UNIDADE"}


def _palavras(texto) -> set[str]:
    limpo = "".join(c if c.isalnum() else " " for c in _norm(texto))
    return {p for p in limpo.split() if len(p) > 2 and not p.isdigit()
            and p not in _RUIDO}


def _nucleo(descricao: str) -> set[str]:
    """A primeira palavra significativa do item — o nome do produto
    ("PAPEL", "AGUA", "BLOCO"), que a fonte equivalente tem de repetir."""
    limpo = "".join(c if c.isalnum() else " " for c in _norm(descricao))
    for palavra in limpo.split():
        if len(palavra) > 2 and not any(ch.isdigit() for ch in palavra)                 and palavra not in _RUIDO:
            return {palavra}
    return set()


# dimensões de CONTEÚDO DA EMBALAGEM (ver `classificar`)
_EMBALAGEM = frozenset({"folhas", "doses"})


def _norm(texto) -> str:
    base = unicodedata.normalize("NFKD", str(texto or "").upper())
    base = "".join(c for c in base if not unicodedata.combining(c))
    return base.replace("²", "2").replace("³", "3")


def _formato_da_dimensao(limpo: str) -> str | None:
    from . import atributos as attr

    medida = attr._DIMENSAO.search(limpo)  # noqa: SLF001
    if not medida:
        return None
    par = attr._par(int(medida.group(1)), int(medida.group(2)))  # noqa: SLF001
    for nome, dimensao in attr.FORMATOS.items():
        if attr._mesmo_formato(par, attr._par(*dimensao)):  # noqa: SLF001
            return nome
    return None


def _numero(texto: str) -> Decimal | None:
    try:
        return Decimal(texto.replace(",", "."))
    except InvalidOperation:
        return None


def atributos(*textos) -> dict[str, frozenset]:
    """Dimensão → valores na unidade base. "75 g/m²" → {"gramatura": {75}}."""
    saida: dict[str, set] = {}
    for texto in textos:
        limpo = _norm(texto)
        for numero, sigla in _QUANTIFICADO.findall(limpo):
            valor = _numero(numero)
            if valor is None or valor <= 0:
                continue
            dimensao, fator = _UNIDADES[sigla]
            saida.setdefault(dimensao, set()).add((valor * fator).normalize())
        for formato in _FORMATO.findall(limpo):
            saida.setdefault("formato", set()).add(formato)
        formato = _formato_da_dimensao(limpo)
        if formato:
            saida.setdefault("formato", set()).add(formato)
        if _RESMA.search(limpo) and "folhas" not in saida:
            saida.setdefault("folhas", set()).add(Decimal(500))
    return {k: frozenset(v) for k, v in saida.items()}


_NOME = {"gramatura": "gramatura", "massa": "massa", "volume": "volume",
         "concentracao": "concentração", "potencia": "potência",
         "tensao": "tensão", "percentual": "percentual", "folhas": "folhas",
         "doses": "doses", "formato": "formato"}


def _texto(valor: Decimal) -> str:
    return format(valor.normalize(), "f").replace(".", ",")


def _um(dimensao: str, valor) -> str:
    if not isinstance(valor, Decimal):
        return str(valor)
    if dimensao == "volume" and valor >= 1000:
        return f"{_texto(valor / 1000)} L"
    if dimensao == "massa" and valor >= 1000:
        return f"{_texto(valor / 1000)} kg"
    unidade = {"gramatura": " g/m²", "massa": " g", "volume": " ml",
               "concentracao": " mg/ml", "potencia": " W", "tensao": " V",
               "percentual": "%", "folhas": " folhas", "doses": " un"
               }.get(dimensao, "")
    return f"{_texto(valor)}{unidade}"


def _exibir(dimensao: str, valores) -> str:
    return "/".join(_um(dimensao, v) for v in sorted(valores, key=str))


@dataclass(frozen=True)
class Equivalencia:
    classe: str
    conferidos: tuple[str, ...] = ()
    faltam: tuple[str, ...] = ()
    divergem: tuple[str, ...] = ()
    versao: str = VERSAO

    @property
    def rotulo(self) -> str:
        return ROTULO[self.classe]

    @property
    def explicacao(self) -> str:
        partes = [self.rotulo]
        if self.divergem:
            partes.append("diverge: " + "; ".join(self.divergem))
        if self.faltam:
            partes.append("a fonte não comprova: " + "; ".join(self.faltam))
        if self.conferidos:
            partes.append("conferido: " + "; ".join(self.conferidos))
        return " — ".join(partes)

    @property
    def score(self) -> Decimal:
        return {MESMO_ITEM: Decimal(1), EQUIVALENTE: Decimal("0.9"),
                SIMILAR: Decimal("0.5"), INCOMPATIVEL: Decimal(0)}[self.classe]

    def para_registro(self) -> dict:
        return {"classe": self.classe, "rotulo": self.rotulo,
                "conferidos": list(self.conferidos), "faltam": list(self.faltam),
                "divergem": list(self.divergem), "versao": self.versao}


def _cruzar(dimensao: str, do_item: frozenset, da_fonte: dict) -> tuple:
    """Gramatura e massa se confundem na redação ("75 g" no papel): o
    número igual na outra dimensão conta como a mesma medida."""
    if dimensao in da_fonte:
        return da_fonte[dimensao], dimensao
    par = {"gramatura": "massa", "massa": "gramatura"}.get(dimensao)
    if par and par in da_fonte and do_item & da_fonte[par]:
        return da_fonte[par], par
    return None, None


def classificar(descricao_item: str, descricao_fonte: str, *,
                unidade_item: str = "", unidade_fonte: str = "",
                mesmo_codigo: bool = False,
                semelhanca: Decimal = Decimal(0),
                convertida: bool = False) -> Equivalencia | None:
    """
    A classe do candidato, ou `None` quando o item não traz atributo
    quantificável (nada a comprovar além da redação).

    `semelhanca` é o fator de descrição do matching (0..1); `mesmo_codigo`,
    o código oficial igual — prova documental que prevalece sobre a redação.

    Contagem (folhas, doses) é EMBALAGEM, não especificação: quem a prova é
    a conversão de unidade (`unidades.normalizar`, fator explícito da
    fonte). `convertida` = a referência tem preço na unidade do item; aí a
    contagem está conferida, ainda que o texto da fonte não a repita ou
    traga outra (resma de 500 contra pacote de 100 se converte, não
    diverge). Sem conversão, falta prova — e a seleção já a recusa.
    """
    do_item = atributos(descricao_item, unidade_item)
    if not do_item:
        return None
    if mesmo_codigo:
        return Equivalencia(MESMO_ITEM, conferidos=("mesmo código oficial",))
    da_fonte = atributos(descricao_fonte, unidade_fonte)
    conferidos, faltam, divergem = [], [], []
    for dimensao, valores in sorted(do_item.items()):
        nome = _NOME[dimensao]
        achados, _ = _cruzar(dimensao, valores, da_fonte)
        if dimensao in _EMBALAGEM:
            if achados is not None and valores <= achados:
                conferidos.append(f"{nome} {_exibir(dimensao, valores)}")
            elif convertida:
                conferidos.append(f"{nome} {_exibir(dimensao, valores)} "
                                  "pela conversão de embalagem")
            else:
                faltam.append(f"{nome} {_exibir(dimensao, valores)}")
            continue
        if achados is None:
            faltam.append(f"{nome} {_exibir(dimensao, valores)}")
        elif valores <= achados:
            conferidos.append(f"{nome} {_exibir(dimensao, valores)}")
        elif valores & achados:
            # parte confere, parte não (dimensões com mais de um valor)
            faltam.append(f"{nome} {_exibir(dimensao, valores - achados)}")
        else:
            divergem.append(f"{nome} {_exibir(dimensao, achados)} na fonte, "
                            f"{_exibir(dimensao, valores)} no item")
    # A medida só fala do PRODUTO que a descrição nomeia: "PRODUTO
    # DIFERENTE 76X76" não é o bloco autoadesivo do item por ter a mesma
    # medida. Sem o núcleo do item na fonte e com redação pouco semelhante,
    # não há o que classificar — o matching por descrição decide (e recusa).
    mesmo_produto = _nucleo(descricao_item) <= _palavras(descricao_fonte)         or semelhanca >= Decimal("0.3")
    if not mesmo_produto:
        return None
    if divergem:
        return Equivalencia(INCOMPATIVEL, tuple(conferidos), tuple(faltam),
                            tuple(divergem))
    if faltam:
        return Equivalencia(SIMILAR, tuple(conferidos), tuple(faltam))
    # "mesmo item" é redação quase igual; "sulfite" × "para impressão" com
    # os atributos conferidos é equivalente comprovado (a mesma força na
    # cesta, rótulo honesto na revisão)
    if semelhanca >= SEMELHANCA_MESMO_ITEM:
        return Equivalencia(MESMO_ITEM, tuple(conferidos))
    # equivalente só com especificação conferida NO TEXTO da fonte; contagem
    # provada pela conversão de embalagem sozinha não fala do produto
    no_texto = [c for c in conferidos if "pela conversão" not in c]
    if not no_texto:
        return Equivalencia(SIMILAR, tuple(conferidos),
                            ("especificação essencial no texto da fonte",))
    return Equivalencia(EQUIVALENTE, tuple(conferidos))


def elegivel_automatica(classe: str | None) -> bool:
    """Pode compor a cesta proposta sem decisão de pessoa?"""
    return classe not in (SIMILAR, INCOMPATIVEL)


@dataclass
class Contagem:
    """Quantos candidatos de cada classe — o "ganho de cobertura" contra o
    "simples aumento de candidatos" da trilha."""

    por_classe: dict = field(default_factory=dict)

    def somar(self, classe: str | None) -> None:
        chave = classe or "sem_atributos"
        self.por_classe[chave] = self.por_classe.get(chave, 0) + 1
