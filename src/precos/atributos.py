"""
Barreira por atributo — o preço é real, mas é do MESMO produto?

Auditoria de 18/10/2026 (C-1), em produção: preços autênticos de
produtos diferentes entravam na cesta, porque a comparabilidade mede
semelhança de texto e a triagem estatística só pega o preço destoante.
Um produto diferente com preço parecido passava:

* papel A3 (420 × 297 mm) a R$ 45,20 na cesta do papel A4;
* clipe nº 0 na cesta do clipe 2/0;
* papel offset 960 × 660 e papel texturizado colorido na cesta do sulfite;
* grampeador cirúrgico (R$ 762,00) e grampeador tipo alicate na cesta do
  grampeador de mesa;
* papel colorido na cesta do papel branco e caneta de tinta preta na
  cesta da caneta azul.

O defeito comum: o atributo que DEFINE o produto (formato, numeração,
tipo, finalidade) está escrito na descrição de catálogo da própria fonte
("TAMANHO (C X L): 420 X 297 MM", "TIPO: ALICATE") e ninguém o
confrontava com o item.

Aqui o confronto é determinístico, sem IA e sem rede, e só com o que as
duas descrições dizem:

* **contradiz** — a fonte informa o atributo e ele difere do que o item
  pede: a referência é de outro produto e NÃO entra na cesta automática
  (rejeitada, com o atributo e os dois valores no motivo);
* **ausente** — o atributo é essencial para o produto (formato do papel,
  numeração do clipe), o item o especifica e a fonte não o informa: vai
  para revisão do servidor, não para a cesta;
* nada — sem conflito, segue para a triagem e a seleção de sempre.

Regra conservadora de propósito: só se decide quando o ITEM diz o
atributo. Item que não especifica formato não rejeita papel nenhum por
formato.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

CONTRADIZ = "contradiz"
AUSENTE = "ausente"


@dataclass(frozen=True)
class Conflito:
    tipo: str          # CONTRADIZ | AUSENTE
    atributo: str
    motivo: str


def _norm(texto) -> str:
    base = unicodedata.normalize("NFKD", str(texto or "").upper())
    return "".join(c for c in base if not unicodedata.combining(c))


def _palavras(texto: str) -> set[str]:
    return set(re.findall(r"[A-Z0-9]+", texto))


# ---------------------------------------------------------------------------
# Finalidade: produto de uso especializado que o item não pede
# ---------------------------------------------------------------------------
# Radicais: CIRURGIC(O/A), ODONTOLOGIC(O), VETERINARI(O/A). Só quando o
# item NÃO os contém — "fio cirúrgico" pesquisado continua comparável.
FINALIDADES = ("CIRURGIC", "ODONTOLOG", "VETERINAR")


def _finalidade(item: str, ref: str) -> Conflito | None:
    for radical in FINALIDADES:
        if radical in ref and radical not in item:
            rotulo = {"CIRURGIC": "cirúrgico", "ODONTOLOG": "odontológico",
                      "VETERINAR": "veterinário"}[radical]
            return Conflito(CONTRADIZ, "finalidade",
                            f"produto de uso {rotulo}, que o item não pede")
    return None


# ---------------------------------------------------------------------------
# Papel: formato (dimensões) e tipo
# ---------------------------------------------------------------------------
FORMATOS = {"A3": (297, 420), "A4": (210, 297), "A5": (148, 210),
            "OFICIO": (216, 330), "CARTA": (216, 279)}
TOLERANCIA_MM = 3

# Tipos de papel de catálogo que mudam o produto. Combinações da fonte
# ("SULFITE/APERGAMINHADO/OFÍCIO") casam por qualquer palavra.
TIPOS_PAPEL = frozenset({
    "SULFITE", "APERGAMINHADO", "OFFSET", "TEXTURIZADO", "COUCHE",
    "RECICLADO", "VERGE", "KRAFT", "FOTOGRAFICO", "JORNAL", "SEDA",
    "CARTOLINA", "ADESIVO", "VEGETAL", "MANTEIGA", "CANSON", "PERGAMINHO"})

_DIMENSAO = re.compile(r"(\d{2,4})\s*(?:MM)?\s*[X×]\s*(\d{2,4})")
# Dois pontos opcionais: a fonte escreve "TAMANHO (C X L): 297 X 210" e
# também "TAMANHO (CX L) 420 X 297 MM" (registros reais de 10/2026).
_TAMANHO = re.compile(r"\bTAMANHO\b(?:\s*\([^)]*\))?\s*:?\s*([^,;]+)")
_TIPO = re.compile(r"\bTIPO\b\s*:?\s*([^,;]+)")
_COR = re.compile(r"\bCOR\b\s*:?\s*([^,;]+)")


def _par(a: int, b: int) -> tuple[int, int]:
    return (min(a, b), max(a, b))


def _formato_do_item(item: str) -> tuple[str, tuple[int, int]] | None:
    """O formato que o item pede: nome (A4...) ou dimensões explícitas."""
    palavras = _palavras(item)
    for nome, medidas in FORMATOS.items():
        if nome in palavras:
            return nome, medidas
    achado = _DIMENSAO.search(item)
    if achado:
        par = _par(int(achado.group(1)), int(achado.group(2)))
        return f"{par[0]} × {par[1]} mm", par
    return None


def _dimensao_da_referencia(ref: str) -> tuple[int, int] | None:
    """O campo TAMANHO do catálogo; sem ele, o formato dito no texto."""
    tamanho = _TAMANHO.search(ref)
    achado = _DIMENSAO.search(tamanho.group(1)) if tamanho else None
    if achado:
        return _par(int(achado.group(1)), int(achado.group(2)))
    livre = _formato_do_item(ref)
    return livre[1] if livre else None


def _mesmo_formato(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return all(abs(x - y) <= TOLERANCIA_MM for x, y in zip(a, b))


def _papel(item: str, ref: str) -> Conflito | None:
    pedido = _formato_do_item(item)
    if pedido is not None:
        nome, medidas = pedido
        da_ref = _dimensao_da_referencia(ref)
        if da_ref is None:
            return Conflito(
                AUSENTE, "formato",
                f"a fonte não informa o formato do papel; o item pede {nome}")
        if not _mesmo_formato(medidas, da_ref):
            rotulo = nome if nome in FORMATOS else "o formato indicado"
            return Conflito(
                CONTRADIZ, "formato",
                f"papel de {da_ref[1]} × {da_ref[0]} mm; o item pede {rotulo}"
                f" ({medidas[1]} × {medidas[0]} mm)")
    if {"BRANCO", "BRANCA"} & _palavras(item):
        cor = _COR.search(ref)
        if cor and "BRANC" not in cor.group(1):
            return Conflito(
                CONTRADIZ, "cor",
                f"papel de cor {cor.group(1).strip().lower()}; o item pede "
                "branco")
    pedidos = TIPOS_PAPEL & _palavras(item)
    tipo = _TIPO.search(ref)
    if pedidos and tipo:
        da_ref = TIPOS_PAPEL & _palavras(tipo.group(1))
        if da_ref and not (da_ref & pedidos):
            return Conflito(
                CONTRADIZ, "tipo",
                f"papel {'/'.join(sorted(da_ref)).lower()}; o item pede "
                f"{'/'.join(sorted(pedidos)).lower()}")
    return None


# ---------------------------------------------------------------------------
# Clipe: numeração (2/0, 4/0, 0...)
# ---------------------------------------------------------------------------
_NUMERO_CLIPE = re.compile(r"(?<![\d/])(\d{1,2}/0|\d{1,2})(?![\d/])")


def _numero_do_item(item: str) -> str | None:
    achado = re.search(r"(?<![\d/])(\d{1,2}/0)(?![\d/])", item)
    return achado.group(1) if achado else None


def _clipe(item: str, ref: str) -> Conflito | None:
    pedido = _numero_do_item(item)
    if pedido is None:
        return None
    tamanho = _TAMANHO.search(ref)
    numero = _NUMERO_CLIPE.search(tamanho.group(1)) if tamanho else None
    if numero is None:
        return Conflito(AUSENTE, "numeração",
                        f"a fonte não informa a numeração do clipe; o item "
                        f"pede {pedido}")
    if numero.group(1) != pedido:
        return Conflito(CONTRADIZ, "numeração",
                        f"clipe nº {numero.group(1)}; o item pede {pedido}")
    return None


# ---------------------------------------------------------------------------
# Grampeador: tipo (mesa, alicate...)
# ---------------------------------------------------------------------------
TIPOS_GRAMPEADOR = frozenset({"MESA", "ALICATE", "TAPECEIRO", "PISTOLA",
                              "ELETRICO", "INDUSTRIAL"})


def _grampeador(item: str, ref: str) -> Conflito | None:
    pedidos = TIPOS_GRAMPEADOR & _palavras(item)
    tipo = _TIPO.search(ref)
    if not pedidos or not tipo:
        return None
    da_ref = TIPOS_GRAMPEADOR & _palavras(tipo.group(1))
    if da_ref and not (da_ref & pedidos):
        return Conflito(CONTRADIZ, "tipo",
                        f"grampeador tipo {'/'.join(sorted(da_ref)).lower()}"
                        f"; o item pede {'/'.join(sorted(pedidos)).lower()}")
    return None


# ---------------------------------------------------------------------------
# Caneta: cor da tinta (azul, preta...)
# ---------------------------------------------------------------------------
CORES_TINTA = {"AZUL": "azul", "PRETA": "preta", "PRETO": "preta",
               "VERMELHA": "vermelha", "VERMELHO": "vermelha",
               "VERDE": "verde"}
_COR_TINTA = re.compile(r"\bCOR\s+(?:DA\s+)?TINTA\b\s*:?\s*([^,;]+)")


def _cores(texto: str) -> set[str]:
    return {CORES_TINTA[p] for p in _palavras(texto) if p in CORES_TINTA}


def _caneta(item: str, ref: str) -> Conflito | None:
    pedidas = _cores(item)
    tinta = _COR_TINTA.search(ref)
    if not pedidas or not tinta:
        return None
    da_ref = _cores(tinta.group(1))
    if da_ref and not (da_ref & pedidas):
        return Conflito(CONTRADIZ, "cor da tinta",
                        f"tinta {'/'.join(sorted(da_ref))}; o item pede "
                        f"{'/'.join(sorted(pedidas))}")
    return None


# Produto (primeira palavra da descrição de catálogo da FONTE) → regra.
# Só se aplica quando o item também nomeia o produto.
REGRAS = {"PAPEL": _papel, "CLIPE": _clipe, "CLIPES": _clipe,
          "CLIPS": _clipe, "GRAMPEADOR": _grampeador, "CANETA": _caneta}


def conflito(texto_item: str, descricao_referencia: str) -> Conflito | None:
    """O atributo da referência contradiz o item, ou falta? `None` se não."""
    item, ref = _norm(texto_item), _norm(descricao_referencia)
    if not item or not ref:
        return None
    achado = _finalidade(item, ref)
    if achado is not None:
        return achado
    primeira = (re.findall(r"[A-Z]+", ref) or [""])[0]
    regra = REGRAS.get(primeira)
    if regra is None:
        return None
    produto = primeira.rstrip("S")
    # palavra inteira: "PAPELÃO" de uma pasta não é o produto "PAPEL"
    if not ({produto, produto + "S", produto + "ES"} & _palavras(item)):
        return None
    return regra(item, ref)


def motivo(achado: Conflito) -> str:
    """Texto gravado na referência — diz o atributo e os dois valores."""
    if achado.tipo == CONTRADIZ:
        return (f"produto diferente do item ({achado.atributo}): "
                f"{achado.motivo} [barreira por atributo]")
    return (f"atributo essencial não informado ({achado.atributo}): "
            f"{achado.motivo}; requer conferência [barreira por atributo]")
