"""
Comparabilidade entre o item do processo e uma referência encontrada.

O score existe para **explicar**, não para esconder. Um número sozinho
("92%") não defende contratação nenhuma; o que defende é a lista de
fatores que o compõem, cada um verificável contra o dado da fonte:

    ✓ mesma unidade
    ✓ descrição fortemente semelhante
    ✓ contratação recente
    ! outro estado

Por isso cada fator é calculado e guardado separadamente, com peso
declarado. Ninguém precisa acreditar no total: dá para conferir parcela
por parcela.

Duas coisas que este módulo deliberadamente NÃO faz:

- **não chama IA.** Tudo aqui é determinístico e reproduzível meses
  depois. A IA entra na Fase 7 para sugerir sinônimos e explicar em
  linguagem natural — sempre por cima deste cálculo, nunca no lugar dele;
- **não decide preço.** Comparabilidade ordena candidatos; quem forma a
  cesta e calcula é `estatistica.py`.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .modelo import Referencia

UM = Decimal("1")
ZERO = Decimal("0")

# ---------------------------------------------------------------------------
# Duas perguntas, não uma
#
# Descrição e catálogo respondem **É O MESMO PRODUTO?**; unidade, data,
# quantidade, local e condições respondem **A CONTRATAÇÃO É COMPARÁVEL?**.
# São perguntas de natureza diferente, e misturá-las numa média só foi um
# erro que os testes pegaram: com peso, um GRAMPEADOR com unidade certa,
# data recente e mesmo estado somava mais que o piso da cesta contra um
# item de PASTA CATÁLOGO. Circunstância boa não transforma um produto em
# outro.
#
# Por isso a identidade MULTIPLICA as circunstâncias, em vez de disputar
# peso com elas: produto diferente zera o total por mais impecável que
# seja o resto.
# ---------------------------------------------------------------------------
PESOS = {
    "unidade": Decimal("0.45"),
    "temporalidade": Decimal("0.30"),
    "quantidade": Decimal("0.13"),
    "geografia": Decimal("0.08"),
    "condicoes": Decimal("0.04"),
}

# Fatores de IDENTIDADE — não entram na média ponderada; formam o
# multiplicador. Aparecem na explicação como qualquer outro fator.
FATORES_DE_IDENTIDADE = ("descricao", "catalogo")

# Meia-vida da relevância temporal: uma contratação de 12 meses atrás
# ainda informa, mas menos que a de ontem. 365 dias é o horizonte em que
# o score cai à metade.
MEIA_VIDA_DIAS = 365

_RUIDO = {
    "ESPECIFICACAO", "ESPECIFICACOES", "TIPO", "MATERIAL", "APLICACAO",
    "CARACTERISTICAS", "ADICIONAIS", "COMPONENTES", "MODELO", "COR",
    "COM", "SEM", "PARA", "DE", "DA", "DO", "DOS", "DAS", "EM", "OU",
    "E", "A", "O", "AS", "OS", "UM", "UMA", "NO", "NA",
}


def _sem_acento(texto: str) -> str:
    base = unicodedata.normalize("NFKD", (texto or "").upper())
    return "".join(c for c in base if not unicodedata.combining(c))


def tokens(texto: str) -> set[str]:
    """
    Palavras significativas de uma descrição.

    Descarta ruído de catálogo e tokens curtíssimos, que casariam com
    qualquer coisa. Números permanecem: "PASTA CATALOGO 100 ENVELOPES" e
    "PASTA CATALOGO 50 ENVELOPES" são produtos diferentes, e é o número
    que os separa.
    """
    limpo = _sem_acento(texto)
    for simbolo in ",;:/()[]-":
        limpo = limpo.replace(simbolo, " ")
    return {p.strip(".") for p in limpo.split()
            if len(p.strip(".")) > 2 and p.strip(".") not in _RUIDO}


@dataclass
class Fator:
    """Uma parcela do score, com a explicação que vai para a tela."""

    nome: str
    peso: Decimal
    score: Decimal          # 0..1
    explicacao: str
    conforme: bool = True   # False vira "!" na interface

    @property
    def contribuicao(self) -> Decimal:
        return self.peso * self.score


@dataclass
class Comparabilidade:
    """
    Resultado do casamento: total + a decomposição que o sustenta.

    `score = identidade × circunstancias`. Guardar as duas parcelas
    separadas é o que permite explicar um score baixo: "é o produto
    certo, mas a contratação é velha" e "a contratação é perfeita, mas é
    outro produto" dão notas parecidas e exigem decisões opostas.
    """

    score: Decimal                       # 0..1
    identidade: Decimal = ZERO           # é o mesmo produto?
    circunstancias: Decimal = ZERO       # a contratação é comparável?
    fatores: list[Fator] = field(default_factory=list)

    @property
    def percentual(self) -> int:
        return int((self.score * 100).to_integral_value())

    def linhas(self) -> list[str]:
        """Explicação pronta para a interface, na ordem dos pesos."""
        return [f"{'✓' if f.conforme else '!'} {f.explicacao}"
                for f in self.fatores]

    def para_relatorio(self) -> dict:
        return {
            "score": format(self.score, "f"),
            "identidade": format(self.identidade, "f"),
            "circunstancias": format(self.circunstancias, "f"),
            "percentual": self.percentual,
            "fatores": [{
                "nome": f.nome,
                "peso": format(f.peso, "f"),
                "score": format(f.score, "f"),
                "explicacao": f.explicacao,
                "conforme": f.conforme,
            } for f in self.fatores],
        }


# ---------------------------------------------------------------------------
# Fatores
# ---------------------------------------------------------------------------
def _fator_descricao(descricao_item: str, referencia: Referencia) -> Fator:
    """
    Semelhança de descrição — média de Jaccard e sobreposição.

    Nenhuma das duas serve sozinha. **Jaccard** (interseção/união) pune a
    referência oficial que descreve o mesmo produto com muito mais
    detalhe — e descrição de catálogo é sempre mais longa que a da
    planilha do município. **Sobreposição** (interseção/menor conjunto)
    faz o oposto: dá 100% para "PASTA" contra "PASTA CATÁLOGO 100
    ENVELOPES", que são produtos diferentes.

    A média das duas mantém a exigência da união sem punir o detalhe
    extra da fonte.
    """
    a, b = tokens(descricao_item), tokens(referencia.descricao_original)
    if not a or not b:
        return Fator("descricao", ZERO, ZERO,
                     "descrição insuficiente para comparar", False)
    intersecao = len(a & b)
    jaccard = Decimal(intersecao) / Decimal(len(a | b))
    sobreposicao = Decimal(intersecao) / Decimal(min(len(a), len(b)))
    score = (jaccard + sobreposicao) / 2
    if score >= Decimal("0.6"):
        texto, ok = "descrição fortemente semelhante", True
    elif score >= Decimal("0.3"):
        texto, ok = "descrição parcialmente semelhante", True
    else:
        texto, ok = "descrição pouco semelhante", False
    return Fator("descricao", ZERO, score,
                 f"{texto} ({intersecao} de {len(a | b)} termos)", ok)


def _fator_catalogo(codigo_item: str | None, classe_item: str | None,
                    referencia: Referencia) -> Fator:
    """
    Código de catálogo é a evidência mais forte de que é o mesmo produto.

    Ausência **não penaliza**: o módulo aceita CATMAT sem exigi-lo, e
    tratar "não informado" como divergência puniria justamente o usuário
    que o módulo existe para atender. Score neutro, explicação honesta.
    """
    if codigo_item and referencia.codigo_catalogo:
        if str(codigo_item) == str(referencia.codigo_catalogo):
            return Fator("catalogo", ZERO, UM,
                         f"mesmo código de catálogo ({codigo_item})", True)
        if classe_item and referencia.codigo_classe and \
                str(classe_item) == str(referencia.codigo_classe):
            return Fator("catalogo", ZERO, Decimal("0.5"),
                         "mesma classe de catálogo, item diferente", True)
        return Fator("catalogo", ZERO, ZERO,
                     "código de catálogo diferente", False)
    return Fator("catalogo", ZERO, Decimal("0.5"),
                 "sem código de catálogo para comparar", True)


def _fator_unidade(referencia: Referencia) -> Fator:
    """
    Unidade comparável é pré-requisito, não detalhe.

    Depende de `unidades.normalizar` já ter rodado: preço não convertido
    para a unidade do processo não pode entrar na cesta, e o score reflete
    isso com zero — não com penalidade parcial.
    """
    peso = PESOS["unidade"]
    if referencia.valor_unitario_normalizado is None:
        motivo = next((m for m in referencia.motivos
                       if "unidade" in m.lower()), "unidade não comparável")
        return Fator("unidade", peso, ZERO, motivo, False)
    if any("convertido" in m for m in referencia.motivos):
        return Fator("unidade", peso, Decimal("0.8"),
                     "unidade convertida com fator informado pela fonte",
                     True)
    return Fator("unidade", peso, UM, "mesma unidade", True)


def _fator_temporalidade(referencia: Referencia,
                         data_base: date | None) -> Fator:
    """
    Decaimento suave com meia-vida de um ano.

    Suave de propósito: contratação de 13 meses não vira lixo de repente,
    e um corte duro descartaria amostra útil em item de baixa rotação.
    """
    peso = PESOS["temporalidade"]
    quando = referencia.data_resultado or referencia.data_compra
    if quando is None:
        return Fator("temporalidade", peso, Decimal("0.5"),
                     "fonte não informou a data da contratação", True)
    dias = ((data_base or date.today()) - quando).days
    if dias < 0:
        dias = 0
    score = UM / (UM + Decimal(dias) / Decimal(MEIA_VIDA_DIAS))
    if dias <= 180:
        texto, ok = "contratação recente", True
    elif dias <= 730:
        texto, ok = "contratação do último biênio", True
    else:
        texto, ok = "contratação antiga", False
    meses = dias // 30
    return Fator("temporalidade", peso, score,
                 f"{texto} (há {meses} mês(es))", ok)


def _fator_quantidade(quantidade_item: Decimal | None,
                      referencia: Referencia) -> Fator:
    """
    Compara ORDEM DE GRANDEZA, não igualdade.

    Comprar 10 e comprar 10.000 são negociações diferentes; comprar 1.500
    e 1.550, não. A razão entre as duas quantidades captura isso sem punir
    diferença irrelevante.
    """
    peso = PESOS["quantidade"]
    a, b = quantidade_item, referencia.quantidade_original
    if not a or not b or a <= 0 or b <= 0:
        return Fator("quantidade", peso, Decimal("0.5"),
                     "quantidade não informada nos dois lados", True)
    razao = (a / b) if a >= b else (b / a)
    if razao <= 2:
        return Fator("quantidade", peso, UM, "quantidade comparável", True)
    if razao <= 10:
        return Fator("quantidade", peso, Decimal("0.6"),
                     "quantidade de ordem próxima", True)
    return Fator("quantidade", peso, Decimal("0.2"),
                 f"quantidade {int(razao)}x diferente", False)


def _fator_geografia(uf_item: str | None, referencia: Referencia) -> Fator:
    peso = PESOS["geografia"]
    if not uf_item or not referencia.uf:
        return Fator("geografia", peso, Decimal("0.5"),
                     "localidade não informada", True)
    if uf_item.upper() == referencia.uf.upper():
        return Fator("geografia", peso, UM, "mesmo estado", True)
    return Fator("geografia", peso, Decimal("0.4"),
                 f"outro estado ({referencia.uf})", False)


def _fator_condicoes(referencia: Referencia) -> Fator:
    """
    Critério de julgamento por MENOR PREÇO é o que torna o valor
    comparável: em julgamento por técnica e preço, o valor pago embute
    fatores que não são preço de mercado.
    """
    peso = PESOS["condicoes"]
    criterio = (referencia.criterio_julgamento or "").strip().upper()
    if not criterio:
        return Fator("condicoes", peso, Decimal("0.5"),
                     "critério de julgamento não informado", True)
    if criterio in ("V", "MENOR PREÇO", "MENOR PRECO", "1"):
        return Fator("condicoes", peso, UM,
                     "julgado por menor preço", True)
    return Fator("condicoes", peso, Decimal("0.6"),
                 f"critério de julgamento: {referencia.criterio_julgamento}",
                 True)


def comparar(referencia: Referencia, *, descricao: str,
             codigo_catalogo: str | None = None,
             codigo_classe: str | None = None,
             quantidade: Decimal | None = None,
             uf: str | None = None,
             data_base: date | None = None) -> Comparabilidade:
    """
    Score de comparabilidade e sua decomposição.

    Média ponderada dos fatores. Linear por escolha consciente: é a forma
    em que cada parcela continua legível na tela e conferível à mão —
    e auditor que não consegue refazer a conta não confia no número.
    """
    identidade_fatores = [
        _fator_descricao(descricao, referencia),
        _fator_catalogo(codigo_catalogo, codigo_classe, referencia),
    ]
    circunstancia_fatores = [
        _fator_unidade(referencia),
        _fator_temporalidade(referencia, data_base),
        _fator_quantidade(quantidade, referencia),
        _fator_geografia(uf, referencia),
        _fator_condicoes(referencia),
    ]

    descricao_fator, catalogo_fator = identidade_fatores
    # Código de catálogo é prova documental de identidade e prevalece
    # sobre a redação: mesmo código com descrições diferentes continua
    # sendo o mesmo item; código diferente derruba a identidade ainda que
    # as palavras coincidam.
    if catalogo_fator.score == UM:
        identidade = UM
    elif catalogo_fator.score == ZERO and not catalogo_fator.conforme:
        identidade = ZERO
    else:
        identidade = descricao_fator.score

    total_peso = sum((f.peso for f in circunstancia_fatores), ZERO)
    bruto = sum((f.contribuicao for f in circunstancia_fatores), ZERO)
    circunstancias = (bruto / total_peso) if total_peso else ZERO

    circunstancia_fatores.sort(key=lambda f: f.peso, reverse=True)
    return Comparabilidade(
        score=identidade * circunstancias,
        identidade=identidade,
        circunstancias=circunstancias,
        fatores=identidade_fatores + circunstancia_fatores,
    )


def ordenar_por_comparabilidade(
    referencias: list[Referencia], **criterios
) -> list[tuple[Referencia, Comparabilidade]]:
    """
    Ranqueia por comparabilidade — **não por preço**.

    Ordenar por preço produziria a cesta dos três menores, que é
    exatamente o que o §12 do prompt do módulo proíbe: barato e
    incomparável não é referência, é ruído com aparência de economia.
    """
    pares = [(r, comparar(r, **criterios)) for r in referencias]
    pares.sort(key=lambda par: par[1].score, reverse=True)
    return pares
