"""
Somar só o que é comprovadamente o mesmo item.

A chave de mesclagem é `(código, unidade)` — e ela não foi escolhida
aqui. Está escrita na aba Resumo da planilha que a prefeitura já
produziu à mão: "Consolidação por código do item + unidade de medida,
com rastreabilidade". Os doze arquivos reais sustentam a escolha: 206
códigos distintos, 179 compartilhados entre secretarias, e nenhum caso
de mesmo código com unidade ou descrição divergente.

Nenhum conflito NOS ARQUIVOS DE HOJE não é nenhum conflito nunca. O
caminho de conflito existe e é exercitado: no dia em que duas
secretarias pedirem o mesmo código em CAIXA e em UNIDADE, a soma para —
não escolhe. Converter caixa em unidade exigiria um fator que o
documento não traz, e um total errado que parece certo é pior do que um
conflito visível.

Tudo aqui é função pura sobre estruturas. Sem banco, sem Streamlit, sem
IA: é o que permite provar a aritmética sem subir nada, e é onde o §12
— "o total é a soma, e isso é verificável" — fica demonstrável em vez
de prometido.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .extracao import DFD

# Status de leitura de um arquivo. `imagem` é o caso real de SECULT e
# SEMEL: PDF sem camada de texto. Não é erro do sistema nem ausência de
# demanda — é um arquivo que ninguém leu ainda.
LIDO = "lido"
IMAGEM = "imagem"
ILEGIVEL = "ilegivel"


@dataclass(frozen=True, slots=True)
class Origem:
    """Um arquivo recebido, com os DFDs que ele carrega."""

    secretaria: str
    arquivo: str
    dfds: tuple[DFD, ...] = ()
    hash_arquivo: str = ""
    status: str = LIDO


@dataclass(frozen=True, slots=True)
class Procedencia:
    """De onde veio UMA quantidade. É o átomo da rastreabilidade."""

    secretaria: str
    arquivo: str
    dfd: str
    quantidade: Decimal
    descricao: str = ""
    especificacao: str | None = None


@dataclass(frozen=True, slots=True)
class LinhaConsolidada:
    codigo: str
    unidade: str
    descricao: str
    total: Decimal
    por_secretaria: dict[str, Decimal] = field(default_factory=dict)
    origens: tuple[Procedencia, ...] = ()
    variacoes_descricao: tuple[str, ...] = ()
    variacoes_especificacao: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Conflito:
    """Mesmo código, unidades incompatíveis. Exige decisão humana."""

    codigo: str
    unidades: tuple[str, ...]
    secretarias: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Consolidado:
    linhas: tuple[LinhaConsolidada, ...] = ()
    conflitos: tuple[Conflito, ...] = ()
    duplicatas: tuple[str, ...] = ()
    nao_lidos: tuple[str, ...] = ()
    secretarias: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Laudo:
    """Resultado da reconferência aritmética."""

    fecha: bool
    divergencias: tuple[str, ...] = ()
    total_de_ocorrencias: int = 0


def consolidar(origens) -> Consolidado:
    """
    Agrupa por `(código, unidade)` e soma, preservando cada parcela.

    A deduplicação acontece em dois níveis, e os dois vieram dos arquivos
    reais: o mesmo ARQUIVO reenviado (hash igual) e o mesmo DFD chegando
    por arquivos diferentes (alguém reexportou o PDF). O número do DFD é
    a identidade do documento; o arquivo é o invólucro.

    O que NÃO é deduplicado: o mesmo código repetido em DFDs distintos da
    mesma secretaria. SEMEC tem dois DFDs e SEMS tem quatro, com
    quantidades diferentes para o mesmo código — são demandas separadas,
    e descartá-las como duplicata apagaria metade do pedido.
    """
    vistos_hash: set[str] = set()
    # Chaveado por (secretaria, número), não pelo número sozinho. O
    # número parece único no município, mas "parece" não basta: se duas
    # secretarias repetissem uma numeração, a segunda demanda sumiria em
    # silêncio — a perda exata que este módulo existe para impedir. O
    # duplicado real é a MESMA secretaria reenviando o MESMO documento.
    vistos_dfd: set[tuple[str, str]] = set()
    duplicatas: list[str] = []
    nao_lidos: list[str] = []
    secretarias: list[str] = []
    grupos: dict[tuple[str, str], dict] = {}
    unidades_por_codigo: dict[str, dict[str, set[str]]] = {}

    for origem in origens:
        if origem.status != LIDO or not origem.dfds:
            nao_lidos.append(origem.arquivo)
            continue
        if origem.hash_arquivo and origem.hash_arquivo in vistos_hash:
            duplicatas.append(origem.arquivo)
            continue
        if origem.hash_arquivo:
            vistos_hash.add(origem.hash_arquivo)

        contribuiu = False
        for dfd in origem.dfds:
            identidade = (origem.secretaria, dfd.numero)
            if dfd.numero and identidade in vistos_dfd:
                continue
            if dfd.numero:
                vistos_dfd.add(identidade)
            for item in dfd.itens:
                contribuiu = True
                chave = (item.codigo, item.unidade)
                grupo = grupos.setdefault(chave, {
                    "descricao": item.descricao,
                    "total": Decimal("0"),
                    "por_secretaria": {},
                    "origens": [],
                    "descricoes": [],
                    "especificacoes": [],
                })
                grupo["total"] += item.quantidade
                atual = grupo["por_secretaria"].get(origem.secretaria, Decimal("0"))
                grupo["por_secretaria"][origem.secretaria] = atual + item.quantidade
                grupo["origens"].append(Procedencia(
                    secretaria=origem.secretaria, arquivo=origem.arquivo,
                    dfd=dfd.numero, quantidade=item.quantidade,
                    descricao=item.descricao, especificacao=item.especificacao,
                ))
                if item.descricao and item.descricao not in grupo["descricoes"]:
                    grupo["descricoes"].append(item.descricao)
                if item.especificacao and item.especificacao not in grupo["especificacoes"]:
                    grupo["especificacoes"].append(item.especificacao)

                por_unidade = unidades_por_codigo.setdefault(item.codigo, {})
                por_unidade.setdefault(item.unidade, set()).add(origem.secretaria)

        if contribuiu and origem.secretaria not in secretarias:
            secretarias.append(origem.secretaria)

    linhas = tuple(
        LinhaConsolidada(
            codigo=codigo, unidade=unidade,
            descricao=dados["descricao"], total=dados["total"],
            por_secretaria=dict(dados["por_secretaria"]),
            origens=tuple(dados["origens"]),
            variacoes_descricao=tuple(dados["descricoes"]),
            variacoes_especificacao=tuple(dados["especificacoes"]),
        )
        for (codigo, unidade), dados in sorted(grupos.items())
    )

    conflitos = tuple(
        Conflito(
            codigo=codigo,
            unidades=tuple(sorted(por_unidade)),
            secretarias=tuple(sorted({s for ss in por_unidade.values() for s in ss})),
        )
        for codigo, por_unidade in sorted(unidades_por_codigo.items())
        if len(por_unidade) > 1
    )

    return Consolidado(
        linhas=linhas, conflitos=conflitos,
        duplicatas=tuple(duplicatas), nao_lidos=tuple(nao_lidos),
        secretarias=tuple(secretarias),
    )


def conferir(consolidado: Consolidado) -> Laudo:
    """
    Refaz a conta a partir das ORIGENS e compara com o total gravado.

    Reconferir somando o próprio total seria comparar um número consigo
    mesmo — sempre bate, não prova nada. Aqui a soma é reconstruída das
    parcelas individuais, que é o que o §12 chama de prova matemática.

    Confere três coisas: o total contra as origens, a soma das colunas
    por secretaria contra o total, e se alguma parcela ficou sem origem.
    """
    divergencias: list[str] = []
    ocorrencias = 0

    for linha in consolidado.linhas:
        ocorrencias += len(linha.origens)
        das_origens = sum((o.quantidade for o in linha.origens), Decimal("0"))
        if das_origens != linha.total:
            divergencias.append(
                f"{linha.codigo}/{linha.unidade}: total {linha.total} "
                f"não bate com a soma das origens {das_origens}")
        das_colunas = sum(linha.por_secretaria.values(), Decimal("0"))
        if das_colunas != linha.total:
            divergencias.append(
                f"{linha.codigo}/{linha.unidade}: total {linha.total} "
                f"não bate com a soma por secretaria {das_colunas}")
        if linha.total and not linha.origens:
            divergencias.append(
                f"{linha.codigo}/{linha.unidade}: tem total e nenhuma origem")

    return Laudo(fecha=not divergencias, divergencias=tuple(divergencias),
                 total_de_ocorrencias=ocorrencias)


def explicar(linha: LinhaConsolidada) -> str:
    """
    A conta de uma linha em texto, como o §12 pede.

    Existe para a tela e para o relatório de juntada: quem confere
    precisa ver de onde veio cada parcela sem abrir doze PDFs.
    """
    partes = [f"Item {linha.codigo} — {linha.descricao} ({linha.unidade})"]
    for secretaria, quantidade in sorted(linha.por_secretaria.items()):
        partes.append(f"  {secretaria}: {quantidade}")
    partes.append(f"  TOTAL: {linha.total}")
    return "\n".join(partes)


__all__ = [
    "Conflito", "Consolidado", "IMAGEM", "ILEGIVEL", "LIDO", "Laudo",
    "LinhaConsolidada", "Origem", "Procedencia", "conferir", "consolidar",
    "explicar",
]
