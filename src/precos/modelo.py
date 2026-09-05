"""
Modelo normalizado de referência de preço.

Uma REFERÊNCIA é um preço que a Administração efetivamente pagou (ou
homologou) por um item, capturado de fonte oficial. Ela é o átomo de toda
a pesquisa: é dela que saem a cesta, a estatística e a memória de
cálculo, e é ela que precisa continuar auditável meses depois.

Três regras que este módulo existe para impor:

1. **o bruto nunca é descartado.** `bruto` guarda o registro como a fonte
   o devolveu. Nenhum resumo — nem da IA, nem nosso — substitui a
   evidência;
2. **dinheiro é `Decimal`.** O núcleo do projeto (`planilha.py`) trabalha
   com `float` e arredonda no fim; aqui, onde se soma dezenas de preços
   de origens diferentes para formar um valor estimado que vira ato
   administrativo, o erro de ponto flutuante é inaceitável. A conversão
   para `float` acontece só na fronteira com `planilha`;
3. **o que não veio da fonte fica `None`.** Nunca zero, nunca "" — a
   diferença entre "a fonte informou zero" e "a fonte não informou" é
   exatamente o que decide se uma unidade pode ser convertida.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

CENTAVO = Decimal("0.01")


class StatusReferencia(str, Enum):
    """
    Situação de uma referência dentro da pesquisa.

    `REJEITADA` é diferente de apagada: a referência continua no
    histórico, com o motivo, porque exclusão silenciosa de preço coletado
    é o oposto de pesquisa auditável.
    """

    CANDIDATA = "candidate"
    SELECIONADA = "selected"
    REJEITADA = "rejected"
    ALERTA = "warning"
    REVISAO_MANUAL = "manual_review"


def para_decimal(valor: Any) -> Decimal | None:
    """
    Converte para `Decimal` sem passar por `float`.

    `Decimal(0.1)` carrega o erro binário do literal; `Decimal("0.1")`
    não. Por isso todo número vira `str` antes. Valor ausente devolve
    `None` — e não `Decimal("0")`, que mentiria dizendo que a fonte
    informou zero.
    """
    if valor is None or valor == "":
        return None
    try:
        return Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        return None


def para_data(valor: Any) -> date | None:
    """Aceita os formatos que as fontes oficiais realmente devolvem."""
    if not valor:
        return None
    texto = str(valor).strip()
    # '2025-08-01T16:53:27', '2025-08-01 00:00:00.0000000', '2025-08-01'
    texto = texto.replace("T", " ").split(" ")[0]
    try:
        ano, mes, dia = (int(p) for p in texto.split("-"))
        return date(ano, mes, dia)
    except (ValueError, TypeError):
        return None


def hash_do_bruto(bruto: dict) -> str:
    """
    Impressão digital do payload como a fonte o entregou.

    Serve para deduplicar entre páginas e, sobretudo, para provar meses
    depois que a referência guardada é a mesma que foi coletada. Usa a
    mesma disciplina de `govbot.hash_canonico`: JSON ordenado e estável.
    """
    canonico = json.dumps(bruto, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), default=str)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Fonte:
    """Identidade da origem — vai no relatório e na trilha."""

    id: str            # 'compras_gov_itens', 'compras_gov_precos', 'pncp'
    nome: str          # legível no relatório
    tipo: str          # 'sistema_oficial' | 'contratacao_similar' | 'outro'


@dataclass
class Referencia:
    """
    Uma referência de preço normalizada, com o bruto preservado.

    Os campos `*_original` guardam o que a fonte disse; os normalizados
    guardam o que o motor conseguiu derivar COM PROVA. Quando não há
    prova, o normalizado fica `None` e o motivo entra em `motivos` — é
    assim que "caixa com 100 unidades" deixa de virar preço por unidade
    por adivinhação.
    """

    fonte: Fonte
    id_externo: str
    bruto: dict = field(repr=False)

    # ---- o que a fonte disse -------------------------------------------
    descricao_original: str = ""
    unidade_original: str | None = None
    quantidade_original: Decimal | None = None
    valor_unitario_original: Decimal | None = None
    capacidade_embalagem: Decimal | None = None   # itens por embalagem

    codigo_catalogo: str | None = None
    tipo_catalogo: str | None = None              # 'CATMAT' | 'CATSER'
    codigo_pdm: str | None = None
    codigo_classe: str | None = None

    orgao: str | None = None
    uf: str | None = None
    municipio: str | None = None
    fornecedor: str | None = None
    ni_fornecedor: str | None = None
    marca: str | None = None
    criterio_julgamento: str | None = None
    modalidade: str | None = None

    data_compra: date | None = None
    data_resultado: date | None = None
    referencia_externa: str | None = None         # id/controle oficial

    # ---- o que o motor derivou COM PROVA -------------------------------
    unidade_normalizada: str | None = None
    valor_unitario_normalizado: Decimal | None = None

    status: StatusReferencia = StatusReferencia.CANDIDATA
    motivos: list[str] = field(default_factory=list)

    @property
    def raw_hash(self) -> str:
        return hash_do_bruto(self.bruto)

    @property
    def chave_dedupe(self) -> str:
        """
        Identidade de negócio da referência.

        Duas páginas da mesma consulta podem devolver o mesmo item; o
        `raw_hash` não serve para isso porque um campo de atualização
        muda entre chamadas. O par (fonte, id externo) é o que a fonte
        promete ser único.
        """
        return f"{self.fonte.id}:{self.id_externo}"

    def com_motivo(self, motivo: str) -> "Referencia":
        """Registra por que a referência está no estado em que está."""
        if motivo not in self.motivos:
            self.motivos.append(motivo)
        return self

    @property
    def tem_preco(self) -> bool:
        """Referência sem preço não é referência de preço."""
        preco = self.valor_unitario_original
        return preco is not None and preco > 0

    def para_relatorio(self) -> dict:
        """
        Projeção estável para relatório e persistência.

        Não inclui o `bruto` inteiro — inclui o hash dele. O payload
        completo é guardado à parte, com decisão própria sobre retenção
        (ver §35 do prompt do módulo).
        """
        return {
            "fonte_id": self.fonte.id,
            "fonte_nome": self.fonte.nome,
            "fonte_tipo": self.fonte.tipo,
            "id_externo": self.id_externo,
            "raw_hash": self.raw_hash,
            "descricao_original": self.descricao_original,
            "unidade_original": self.unidade_original,
            "quantidade_original": _texto_decimal(self.quantidade_original),
            "valor_unitario_original": _texto_decimal(
                self.valor_unitario_original),
            "capacidade_embalagem": _texto_decimal(self.capacidade_embalagem),
            "unidade_normalizada": self.unidade_normalizada,
            "valor_unitario_normalizado": _texto_decimal(
                self.valor_unitario_normalizado),
            "codigo_catalogo": self.codigo_catalogo,
            "tipo_catalogo": self.tipo_catalogo,
            "orgao": self.orgao,
            "uf": self.uf,
            "municipio": self.municipio,
            "fornecedor": self.fornecedor,
            "marca": self.marca,
            "data_compra": self.data_compra.isoformat()
            if self.data_compra else None,
            "data_resultado": self.data_resultado.isoformat()
            if self.data_resultado else None,
            "referencia_externa": self.referencia_externa,
            "status": self.status.value,
            "motivos": list(self.motivos),
        }


def _texto_decimal(valor: Decimal | None) -> str | None:
    """Decimal vira texto na serialização — float perderia precisão."""
    return None if valor is None else format(valor, "f")


def deduplicar(referencias: list[Referencia]) -> list[Referencia]:
    """
    Remove repetições preservando a ORDEM de chegada.

    A primeira ocorrência vence: em consultas paginadas ela veio da
    página mais recente, e trocar a referência guardada por uma cópia
    posterior mudaria o `raw_hash` sem mudar o fato.
    """
    vistas: set[str] = set()
    unicas: list[Referencia] = []
    for ref in referencias:
        if ref.chave_dedupe in vistas:
            continue
        vistas.add(ref.chave_dedupe)
        unicas.append(ref)
    return unicas


# ---------------------------------------------------------------------------
# Procedência da fonte (§55 — "source_id arbitrário é rejeitado")
#
# `Fonte` é um dataclass: qualquer código — ou qualquer payload que um
# adapter futuro monte a partir de resposta externa — pode declarar
# `Fonte("qualquer_coisa", "…", tipo="sistema_oficial")`.
#
# E o tipo NÃO é decorativo: `estatistica.selecionar_cesta` ordena por
# `perfil.prioridade_de_fontes`, com `sistema_oficial` em primeiro. Uma
# fonte inventada que se declarasse sistema oficial entraria na cesta
# à frente de uma contratação similar verdadeira, e o relatório diria
# que o preço veio de sistema oficial de preços.
#
# A allowlist é o registro do que o módulo de fato integra. Ela não
# APAGA a referência de origem desconhecida — apagar esconderia o que
# chegou. Ela REBAIXA a fonte para `outro`, a última prioridade, e
# carimba o motivo, para que a decisão apareça no relatório em vez de
# acontecer em silêncio.
#
# Por que rebaixar e não excluir: `Fonte` é construída pelos NOSSOS
# adapters, não montada a partir de payload da rede. Uma fonte fora da
# lista significa, na prática, adapter novo que ninguém registrou — erro
# de código, não ataque. Excluir faria o adapter novo produzir silêncio;
# rebaixar impede a afirmação indevida de origem oficial e deixa o
# problema visível na tela e no relatório. Silêncio é o pior dos dois.
# ---------------------------------------------------------------------------
FONTES_REGISTRADAS: dict[str, str] = {
    "compras_gov_precos": "sistema_oficial",
    "compras_gov_itens": "contratacao_similar",
    "pncp": "sistema_oficial",
}

TIPO_NAO_REGISTRADO = "outro"

MOTIVO_FONTE_DESCONHECIDA = (
    "fonte não registrada no módulo — classificada como 'outro' e sem "
    "prioridade de sistema oficial")

MOTIVO_TIPO_DIVERGENTE = (
    "a fonte declarou natureza diferente da registrada — prevalece a "
    "registrada")


def fonte_confiavel(fonte: Fonte) -> tuple[Fonte, str]:
    """
    Devolve `(fonte com a natureza REGISTRADA, motivo)`.

    Motivo vazio significa que a fonte é a registrada e nada mudou.

    A natureza nunca vem do que a fonte diz de si: vem da allowlist. É a
    diferença entre "esta referência afirma ser de sistema oficial" e
    "esta referência é de uma fonte que integramos como sistema oficial".
    """
    registrado = FONTES_REGISTRADAS.get(fonte.id)
    if registrado is None:
        return Fonte(fonte.id, fonte.nome, TIPO_NAO_REGISTRADO), \
            MOTIVO_FONTE_DESCONHECIDA
    if registrado != fonte.tipo:
        return Fonte(fonte.id, fonte.nome, registrado), MOTIVO_TIPO_DIVERGENTE
    return fonte, ""


def conferir_procedencia(referencias: list[Referencia]) -> list[Referencia]:
    """
    Aplica `fonte_confiavel` a cada referência, registrando o motivo.

    Roda no motor, entre a coleta e a normalização: é o ponto em que o
    dado externo deixa de ser "o que a fonte disse" e passa a ser o que o
    módulo aceita como procedência.
    """
    for referencia in referencias:
        fonte, motivo = fonte_confiavel(referencia.fonte)
        if motivo:
            referencia.fonte = fonte
            referencia.com_motivo(motivo)
    return referencias
