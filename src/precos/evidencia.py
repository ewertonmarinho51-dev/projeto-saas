"""
Evidência de preço de fonte NOVA (arquivo oficial baixado), antes da cesta.

Pacote de expansão das fontes (20/10/2026). O que vem de um ZIP oficial
— TCE-RS/LicitaCon, BPS — não entra na pesquisa direto: vira
`Evidencia` (o que a linha prova) ou `Quarentena` (por que não prova), e
só a evidência VALIDADA chega a `Referencia`, com a natureza de
`modelo.NaturezaValor` que o resto do módulo já sabe tratar.

Regras que valem para toda fonte:

* dinheiro é `Decimal` lido do TEXTO da fonte, com a escala dela — nada
  de `float`, nada de arredondar a 2 casas no parser;
* `TipoPreco` só é HOMOLOGADO/ADJUDICADO/CONTRATADO com prova de
  significado (dicionário ou leiaute da fonte). Coluna que se chama
  "homologado" não basta enquanto o código de resultado do item não
  tiver significado conferido;
* sem prova, a linha fica em QUARENTENA com motivos estáveis — e nunca
  é promovida "por contexto";
* CPF e nome de pessoa física não seguem adiante: o fornecedor só é
  guardado quando é CNPJ.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum

from .modelo import NaturezaValor


class TipoPreco(str, Enum):
    """
    A etapa do preço — o `price_kind` do pacote, mais PRATICADO: o preço
    PAGO, que o pacote não listava e o BPS declara no dicionário.
    """

    PRATICADO = "PRATICADO"
    HOMOLOGADO = "HOMOLOGADO"
    ADJUDICADO = "ADJUDICADO"
    CONTRATADO = "CONTRATADO"
    ESTIMADO = "ESTIMADO"
    PROPOSTA = "PROPOSTA"
    DESCONHECIDO = "DESCONHECIDO"


# a ponte com o módulo: o que a cesta já distingue
NATUREZA_DO_TIPO = {
    TipoPreco.PRATICADO: NaturezaValor.PRATICADO,
    TipoPreco.HOMOLOGADO: NaturezaValor.HOMOLOGADO,
    TipoPreco.ADJUDICADO: NaturezaValor.ADJUDICADO,
    TipoPreco.CONTRATADO: NaturezaValor.CONTRATADO,
    TipoPreco.ESTIMADO: NaturezaValor.ESTIMADO_ORIGEM,
    TipoPreco.PROPOSTA: NaturezaValor.PROPOSTA,
    TipoPreco.DESCONHECIDO: NaturezaValor.OUTRO,
}
# as etapas que podem sustentar a cesta — as mesmas de
# `modelo.NATUREZAS_COMPARAVEIS`
TIPOS_DE_RESULTADO = frozenset({TipoPreco.PRATICADO, TipoPreco.HOMOLOGADO,
                                TipoPreco.ADJUDICADO, TipoPreco.CONTRATADO})

# Motivos de quarentena: estáveis (vão para o relatório técnico e testes).
SEM_DESCRICAO = "SEM_DESCRICAO"
SEM_UNIDADE = "SEM_UNIDADE"
SEM_QUANTIDADE = "SEM_QUANTIDADE"
PRECO_INVALIDO = "PRECO_UNITARIO_INVALIDO"
TOTAL_INCOERENTE = "TOTAL_DIFERE_DE_UNITARIO_X_QUANTIDADE"
TIPO_NAO_COMPROVADO = "ETAPA_DO_PRECO_NAO_COMPROVADA"
SO_ESTIMADO = "SO_VALOR_ESTIMADO"
CODIGO_DESCONHECIDO = "CODIGO_DE_RESULTADO_SEM_SIGNIFICADO_CONFIRMADO"
RESULTADO_INVALIDO = "RESULTADO_NAO_VALIDO"
COMPRA_JUDICIAL = "COMPRA_POR_ORDEM_JUDICIAL"
MODALIDADE_FORA = "MODALIDADE_SEM_DISPUTA_DE_PRECO"
SEM_EVIDENCIA = "SEM_URL_OFICIAL_DO_REGISTRO"


class ValorInvalido(ValueError):
    """Valor monetário que não se lê sem adivinhar."""


_PONTO = re.compile(r"^-?\d+(?:\.\d+)?$")
_BR = re.compile(r"^-?\d{1,3}(?:\.\d{3})+(?:,\d+)?$|^-?\d+(?:,\d+)?$")


def ler_decimal(texto, *, formato: str) -> Decimal | None:
    """
    Texto da fonte → `Decimal`, na escala que a fonte deu.

    `formato` é DECLARADO por fonte (conferido no arquivo real): "ponto"
    (`5029.73`, TCE-RS e BPS) ou "br" (`1.234,5000`). Vazio → `None`.
    Recusa `float`, `NaN`, infinito e formato ambíguo — `ValorInvalido`.
    """
    if texto is None:
        return None
    if not isinstance(texto, str):
        raise ValorInvalido("valor monetário precisa chegar como texto")
    bruto = texto.strip()
    if not bruto:
        return None
    if formato == "ponto":
        if not _PONTO.fullmatch(bruto):
            raise ValorInvalido(f"número fora do formato da fonte: {bruto!r}")
        limpo = bruto
    elif formato == "br":
        if not _BR.fullmatch(bruto):
            raise ValorInvalido(f"número fora do formato da fonte: {bruto!r}")
        limpo = bruto.replace(".", "").replace(",", ".")
    else:
        raise ValueError(f"formato desconhecido: {formato}")
    try:
        valor = Decimal(limpo)
    except InvalidOperation as exc:
        raise ValorInvalido(bruto) from exc
    if not valor.is_finite():
        raise ValorInvalido(bruto)
    return valor


def cnpj_ou_nada(tipo_documento: str | None, numero: str | None) -> str | None:
    """Só CNPJ (14 dígitos) segue adiante; CPF de pessoa física, não."""
    numero = re.sub(r"\D", "", numero or "")
    if len(numero) == 14 and (tipo_documento in (None, "", "J")):
        return numero
    return None


def hash_da_linha(campos: dict) -> str:
    texto = json.dumps(campos, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


@dataclass
class Evidencia:
    """Uma linha de fonte nova, normalizada, com o bruto e a prova."""

    fonte_id: str
    registro_id: str              # identidade estável DENTRO da fonte
    descricao: str
    unidade: str | None
    quantidade: Decimal | None
    valor_unitario: Decimal | None
    valor_total: Decimal | None
    tipo_preco: TipoPreco
    orgao: str | None = None
    orgao_cnpj: str | None = None
    uf: str | None = None
    municipio: str | None = None
    fornecedor_cnpj: str | None = None
    processo: str | None = None
    item: str | None = None
    codigo_catalogo: str | None = None
    data_resultado: str | None = None     # ISO, como a fonte deu
    resultado: str | None = None          # código cru da fonte
    url_evidencia: str | None = None      # página oficial do registro
    url_snapshot: str | None = None       # arquivo de onde a linha saiu
    sha256_snapshot: str | None = None
    versao_parser: str = ""
    atributos: dict = field(default_factory=dict)
    motivos: list[str] = field(default_factory=list)
    hash_linha: str = ""

    @property
    def validada(self) -> bool:
        return not self.motivos

    def para_registro(self) -> dict:
        saida = asdict(self)
        for chave in ("quantidade", "valor_unitario", "valor_total"):
            valor = getattr(self, chave)
            saida[chave] = None if valor is None else format(valor, "f")
        saida["tipo_preco"] = self.tipo_preco.value
        return saida


def conferir(e: Evidencia, *, tolerancia: Decimal = Decimal("0.05")) -> Evidencia:
    """Motivos objetivos de quarentena, iguais para toda fonte."""
    def marca(motivo):
        if motivo not in e.motivos:
            e.motivos.append(motivo)

    if not (e.descricao or "").strip():
        marca(SEM_DESCRICAO)
    if not (e.unidade or "").strip():
        marca(SEM_UNIDADE)
    if e.quantidade is None or e.quantidade <= 0:
        marca(SEM_QUANTIDADE)
    if e.valor_unitario is None or e.valor_unitario <= 0:
        marca(PRECO_INVALIDO)
    elif e.quantidade and e.valor_total is not None and \
            abs(e.valor_unitario * e.quantidade - e.valor_total) > tolerancia:
        marca(TOTAL_INCOERENTE)
    if e.tipo_preco not in TIPOS_DE_RESULTADO:
        marca(SO_ESTIMADO if e.tipo_preco == TipoPreco.ESTIMADO
              else TIPO_NAO_COMPROVADO)
    if not (e.url_evidencia or "").startswith("https://"):
        marca(SEM_EVIDENCIA)
    return e
