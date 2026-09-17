"""
Do PDF ao item, sem adivinhação.

Este módulo é DETERMINÍSTICO de ponta a ponta: nenhuma chamada de IA,
nenhuma heurística que preencha lacuna. Foi escrito lendo os doze
arquivos reais das secretarias de Paragominas, e o que ele sabe fazer é
exatamente o que aqueles arquivos mostram.

O que os arquivos ensinaram
---------------------------
**O documento tem nome próprio.** Internamente não é "Solicitação de
Despesa": é `DOCUMENTO DE FORMALIZAÇÃO DE DEMANDA Nº`, com o órgão
codificado no cabeçalho (`05  Secret.de Planejamento e Desenvolvimento`).
Por isso a secretaria sai do CONTEÚDO, nunca do nome do arquivo — o que
também é o que o §6 do escopo exige.

**Um arquivo pode conter vários DFDs.** SEMEC traz dois; SEMS, quatro.
Não são reimpressões: para o mesmo código as quantidades divergem
(2.000 contra 10.000). São demandas distintas da mesma secretaria e
somam. Tratar o arquivo como unidade de ingestão perderia metade da
demanda do SEMEC sem deixar rastro.

**Há dois layouts de quadro.** Num deles (SEPLAN) existe coluna
`Vl. Estimado` e a quantidade vem grudada na unidade; no outro (nove
arquivos) não há coluna de valor e os dois campos ocupam linhas
separadas. O mesmo parser cobre os dois porque decide pela FORMA da
linha, não por uma configuração escolhida antes.

**Dois arquivos são imagem.** SECULT e SEMEL não têm camada de texto.
Eles não são extraídos e não são adivinhados: voltam com status próprio
para a tela dizer que não foram lidos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# ---------------------------------------------------------------------------
# Formas de linha observadas nos arquivos reais
# ---------------------------------------------------------------------------
# Código institucional: seis dígitos, com zeros à esquerda preservados
# (`018266` não é 18266 — é uma chave, não um número).
_CODIGO = re.compile(r"^\d{6}$")
# Quantidade sempre com quatro casas: `50,0000`, `1.500,0000`.
_QTD_SOZINHA = re.compile(r"^([\d.]+,\d{4})$")
_QTD_COM_UNIDADE = re.compile(r"^([\d.]+,\d{4})\s+(\S.*)$")
# Valor estimado, duas casas. Só o layout A tem.
_VALOR = re.compile(r"^([\d.]+,\d{2})$")
_NUMERO_DFD = re.compile(r"DOCUMENTO DE FORMALIZAÇÃO DE DEMANDA N[ºo°]?\s*(\d+)")
# `05  Secret.de Planejamento` — código de dois dígitos, dois espaços, nome.
_ORGAO = re.compile(r"^(\d{2})\s\s+(\S.*)$")

_ESPECIFICACAO = "Especificação:"

# Ruído que se repete em toda página e não é conteúdo.
_RUIDO = (
    "Assinado por 1 pessoa",
    "1doc.com.br",
    "Pag.:",
)

# Uma descrição não se estende indefinidamente. O limite não é estético:
# sem ele, um quadro malformado faria o parser engolir parágrafos
# inteiros de justificativa como se fossem nome de item.
_MAX_LINHAS_DESCRICAO = 6


class ErroExtracao(Exception):
    """O texto não sustenta a leitura pedida. Nunca vira valor padrão."""


@dataclass(frozen=True, slots=True)
class ItemDemanda:
    """Uma linha do quadro, como ela está no documento."""

    codigo: str
    descricao: str
    quantidade: Decimal
    unidade: str
    especificacao: str | None = None
    valor_unitario: Decimal | None = None
    ordem: int = 0
    dfd: str = ""


@dataclass(frozen=True, slots=True)
class DFD:
    """Um Documento de Formalização de Demanda e os itens dele."""

    numero: str
    orgao_codigo: str = ""
    orgao_nome: str = ""
    itens: tuple[ItemDemanda, ...] = field(default_factory=tuple)


def numero(bruto) -> Decimal:
    """
    Decimal brasileiro para `Decimal`.

    `1.500,0000` é mil e quinhentos: o ponto separa milhar e a vírgula
    separa decimal. Ler com `float()` daria 1.5, e um erro de mil vezes
    numa quantidade passa despercebido numa tabela com duzentas linhas.

    Lixo levanta erro em vez de virar zero. Zero é quantidade legítima —
    converter ilegível em zero faria "não consegui ler" virar "pediram
    nenhum", e ninguém revisaria uma linha que parece decidida.
    """
    texto = str(bruto or "").strip()
    if not texto:
        raise ErroExtracao("quantidade ausente")
    try:
        return Decimal(texto.replace(".", "").replace(",", "."))
    except InvalidOperation:
        raise ErroExtracao(f"quantidade ilegível: {texto[:40]!r}") from None


def _limpar(texto: str) -> list[str]:
    return [
        linha.strip()
        for linha in texto.splitlines()
        if linha.strip() and not any(r in linha for r in _RUIDO)
    ]


def _cabecalho(linhas: list[str]) -> tuple[str, str]:
    """
    Código e nome do órgão.

    Procura o padrão `NN  Nome` só DEPOIS do rótulo `ÓRGÃO :`, e não no
    documento inteiro: `2.119 Gestão, Operacionalização...` na dotação
    orçamentária também casaria com a forma, e a secretaria passaria a
    ser lida de um campo que fala de outra coisa.
    """
    for i, linha in enumerate(linhas):
        if not linha.startswith("ÓRGÃO"):
            continue
        for candidata in linhas[i:i + 12]:
            achado = _ORGAO.match(candidata)
            if achado:
                return achado.group(1), achado.group(2).strip()
        break
    return "", ""


def _ler_item(linhas: list[str], i: int) -> tuple[ItemDemanda | None, int]:
    """
    Lê um item a partir de um código, ou devolve None e anda uma linha.

    A decisão entre os dois layouts é tomada pela FORMA da linha de
    quantidade, não por configuração: se ela traz a unidade junto, é o
    layout com coluna de valor; se vem sozinha, a unidade é a linha
    seguinte. Um arquivo novo que misture os dois continua legível.
    """
    codigo = linhas[i]
    descricao: list[str] = []
    j = i + 1
    while j < len(linhas):
        if _QTD_SOZINHA.match(linhas[j]) or _QTD_COM_UNIDADE.match(linhas[j]):
            break
        if _CODIGO.match(linhas[j]) or len(descricao) >= _MAX_LINHAS_DESCRICAO:
            # Outro código antes da quantidade: o item anterior não tinha
            # quadro. Não se inventa quantidade para ele.
            return None, i + 1
        descricao.append(linhas[j])
        j += 1
    if j >= len(linhas):
        return None, i + 1

    juntos = _QTD_COM_UNIDADE.match(linhas[j])
    if juntos:
        quantidade, unidade = numero(juntos.group(1)), juntos.group(2).strip()
        j += 1
    else:
        sozinha = _QTD_SOZINHA.match(linhas[j])
        if not sozinha or j + 1 >= len(linhas):
            return None, i + 1
        quantidade, unidade = numero(sozinha.group(1)), linhas[j + 1].strip()
        j += 2

    valor = None
    if j < len(linhas) and _VALOR.match(linhas[j]):
        bruto = numero(linhas[j] + "00")  # duas casas viram quatro
        valor = bruto if bruto else None
        j += 1

    especificacao = None
    if j < len(linhas) and linhas[j].startswith(_ESPECIFICACAO):
        resto = linhas[j][len(_ESPECIFICACAO):].strip()
        partes = [resto] if resto else []
        j += 1
        while j < len(linhas) and not _CODIGO.match(linhas[j]) \
                and not linhas[j].startswith(_ESPECIFICACAO):
            partes.append(linhas[j])
            j += 1
        especificacao = " ".join(partes).strip() or None

    return ItemDemanda(
        codigo=codigo,
        descricao=" ".join(descricao).strip(),
        quantidade=quantidade,
        unidade=unidade,
        especificacao=especificacao,
        valor_unitario=valor,
    ), j


def extrair_do_texto(texto: str) -> tuple[DFD, ...]:
    """
    Todos os DFDs presentes no texto, na ordem em que aparecem.

    A fatia é feita pelo NÚMERO do DFD, que se repete no cabeçalho de
    cada página. É o que permite um arquivo com quatro demandas virar
    quatro registros somáveis em vez de um bloco indistinto.
    """
    linhas = _limpar(texto)
    if not linhas:
        return ()

    blocos: list[tuple[str, list[str]]] = []
    atual: str | None = None
    acumulado: list[str] = []
    for linha in linhas:
        achado = _NUMERO_DFD.search(linha)
        if achado and achado.group(1) != atual:
            if atual is not None:
                blocos.append((atual, acumulado))
                acumulado = []
            atual = achado.group(1)
        acumulado.append(linha)
    if atual is None:
        return ()
    blocos.append((atual, acumulado))

    dfds = []
    for numero_dfd, corpo in blocos:
        codigo_orgao, nome_orgao = _cabecalho(corpo)
        itens, i, ordem = [], 0, 0
        while i < len(corpo):
            if not _CODIGO.match(corpo[i]):
                i += 1
                continue
            item, i = _ler_item(corpo, i)
            if item is None:
                continue
            ordem += 1
            itens.append(ItemDemanda(
                codigo=item.codigo, descricao=item.descricao,
                quantidade=item.quantidade, unidade=item.unidade,
                especificacao=item.especificacao,
                valor_unitario=item.valor_unitario,
                ordem=ordem, dfd=numero_dfd,
            ))
        dfds.append(DFD(numero=numero_dfd, orgao_codigo=codigo_orgao,
                        orgao_nome=nome_orgao, itens=tuple(itens)))
    return tuple(dfds)


__all__ = ["DFD", "ErroExtracao", "ItemDemanda", "extrair_do_texto", "numero"]
