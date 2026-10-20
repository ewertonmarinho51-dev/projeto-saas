"""
TCE-RS / LicitaCon — leitura do ZIP anual oficial (14 CSV), em staging.

Leiaute conferido no arquivo real de 20/10/2026 (`2026.csv.zip`, 258 MB,
sha256 45ee32c1…): CSV com vírgula, UTF-8 com BOM, número com ponto
decimal, data ISO. Junção pela chave (CD_ORGAO, NR_LICITACAO,
ANO_LICITACAO, CD_TIPO_MODALIDADE), única em `licitacao.csv` (128.806
linhas, nenhuma repetida).

O que o arquivo PROVA e o que não prova:

* `item.csv` traz `VL_UNITARIO_ESTIMADO` e `VL_UNITARIO_HOMOLOGADO` em
  colunas separadas — o homologado não precisa ser deduzido de
  `item_prop.csv` (e não é: o nome da tabela de propostas não prova
  homologação);
* mas o código de resultado do item (`TP_RESULTADO_ITEM`: A, D, F, R, N
  ou vazio) não tem significado conferido — o manual de leiaute 1.4
  citado no dataset devolve 404. Há item com resultado "R" e valor
  homologado preenchido (lidocaína, PM de Novo Hamburgo, licitação
  9/2026): se "R" for revogado, aquele preço não serve. Por isso TODA
  linha sai com `TipoPreco.DESCONHECIDO` e o motivo
  `CODIGO_DESCONHECIDO` até `RESULTADO_CONFIRMADO` ser preenchido com o
  leiaute em mãos;
* `LINK_LICITACON_CIDADAO` existe em todas as licitações, mas é da
  LICITAÇÃO, não do item — vai em `atributos["nivel_da_evidencia"]`;
* não há número de controle do PNCP: a mesma compra vista também no
  PNCP não tem chave forte comum (ver `dedup_fontes`).

O diagrama oficial (`diagrama_licitacao.pdf`, 2022, sha256 c8981e5a…)
confirma as chaves — ITEM_PK = licitação + NR_LOTE + NR_ITEM — e que o
documento do ITEM é o do VENCEDOR (ITEM_PESSOAS_FK por
TP_DOCUMENTO_VENCEDOR/NR_DOCUMENTO_VENCEDOR). Não traz o domínio dos
códigos de resultado.

O cabeçalho de `item.csv` repete `TP_DOCUMENTO`/`NR_DOCUMENTO`; a
leitura é por POSIÇÃO. O documento do vencedor só segue quando é CNPJ.
`pessoas.csv`, `memcomissao.csv` e afins não são lidos.
"""

from __future__ import annotations

import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import evidencia as ev
from .arquivos import abrir_csv, conferir_zip

FONTE_ID = "tce_rs"
VERSAO_PARSER = "tce_rs-2026-10-20.1"
SEPARADOR = ","
FORMATO_NUMERO = "ponto"
CHAVE = ("CD_ORGAO", "NR_LICITACAO", "ANO_LICITACAO", "CD_TIPO_MODALIDADE")

# Código de TP_RESULTADO_ITEM → etapa do preço. VAZIO DE PROPÓSITO: só
# entra código cujo significado estiver no leiaute oficial, citado aqui.
RESULTADO_CONFIRMADO: dict[str, ev.TipoPreco] = {}

COLUNAS_LICITACAO = ("NM_ORGAO", "NR_PROCESSO", "DT_HOMOLOGACAO",
                     "LINK_LICITACON_CIDADAO", "CD_TIPO_FASE_ATUAL",
                     "TP_RESULTADO_GLOBAL", "TP_OBJETO", "BL_ORCAMENTO_SIGILOSO")


@dataclass
class Leitura:
    """O que a rodada leu — contagens para o relatório técnico."""

    sha256: str = ""
    licitacoes: int = 0
    itens: int = 0
    so_estimado: int = 0
    com_homologado: int = 0
    motivos: Counter = field(default_factory=Counter)
    resultados: Counter = field(default_factory=Counter)


def _indice(cabecalho: list[str]) -> dict[str, int]:
    """Primeira posição de cada nome; repetidos ficam em `_posicoes`."""
    indice: dict[str, int] = {}
    for i, nome in enumerate(cabecalho):
        indice.setdefault(nome, i)
    return indice


def _posicoes(cabecalho: list[str], nome: str) -> list[int]:
    return [i for i, n in enumerate(cabecalho) if n == nome]


def _licitacoes(z: zipfile.ZipFile) -> dict[tuple, dict]:
    cab, linhas = abrir_csv(z, "licitacao.csv", separador=SEPARADOR)
    ix = _indice(cab)
    faltam = [c for c in CHAVE + COLUNAS_LICITACAO if c not in ix]
    if faltam:
        raise ValueError(f"licitacao.csv mudou de leiaute: faltam {faltam}")
    saida = {}
    for r in linhas:
        saida[tuple(r[ix[c]] for c in CHAVE)] = {c: r[ix[c]] for c in
                                                 COLUNAS_LICITACAO}
    return saida


def evidencia_do_item(linha: list[str], cab: list[str], licitacao: dict | None,
                      *, sha256: str = "", url_snapshot: str = "") -> ev.Evidencia:
    """Uma linha de `item.csv` (+ a licitação) → `Evidencia` com motivos."""
    ix = _indice(cab)
    tipos, numeros = _posicoes(cab, "TP_DOCUMENTO"), _posicoes(cab, "NR_DOCUMENTO")
    chave = [linha[ix[c]] for c in CHAVE]
    lote, item = linha[ix["NR_LOTE"]], linha[ix["NR_ITEM"]]
    resultado = linha[ix["TP_RESULTADO_ITEM"]].strip()
    licitacao = licitacao or {}

    def numero(coluna):
        try:
            return ev.ler_decimal(linha[ix[coluna]], formato=FORMATO_NUMERO)
        except ev.ValorInvalido:
            return None

    fornecedor = None
    for t, n in zip(tipos, numeros):
        fornecedor = fornecedor or ev.cnpj_ou_nada(linha[t], linha[n])
    tipo = RESULTADO_CONFIRMADO.get(resultado, ev.TipoPreco.DESCONHECIDO)
    e = ev.Evidencia(
        fonte_id=FONTE_ID,
        registro_id=":".join(chave + [lote, item]),
        descricao=" ".join(linha[ix["DS_ITEM"]].split()),
        unidade=linha[ix["SG_UNIDADE_MEDIDA"]].strip() or None,
        quantidade=numero("QT_ITENS"),
        valor_unitario=numero("VL_UNITARIO_HOMOLOGADO"),
        valor_total=numero("VL_TOTAL_HOMOLOGADO"),
        tipo_preco=tipo,
        orgao=licitacao.get("NM_ORGAO") or None, uf="RS",
        fornecedor_cnpj=fornecedor,
        processo=licitacao.get("NR_PROCESSO") or None, item=item,
        data_resultado=licitacao.get("DT_HOMOLOGACAO") or None,
        resultado=resultado or None,
        url_evidencia=licitacao.get("LINK_LICITACON_CIDADAO") or None,
        url_snapshot=url_snapshot, sha256_snapshot=sha256,
        versao_parser=VERSAO_PARSER,
        atributos={"coluna_do_valor": "VL_UNITARIO_HOMOLOGADO",
                   "valor_estimado": linha[ix["VL_UNITARIO_ESTIMADO"]] or None,
                   "nivel_da_evidencia": "licitacao",
                   "fase_atual": licitacao.get("CD_TIPO_FASE_ATUAL") or None,
                   "resultado_global": licitacao.get("TP_RESULTADO_GLOBAL") or None,
                   "orcamento_sigiloso": licitacao.get("BL_ORCAMENTO_SIGILOSO") or None,
                   "modalidade": chave[3]})
    e.hash_linha = ev.hash_da_linha(dict(zip(cab, linha)))
    if not licitacao:
        e.motivos.append("LICITACAO_NAO_ENCONTRADA")
    if resultado not in RESULTADO_CONFIRMADO:
        e.motivos.append(ev.CODIGO_DESCONHECIDO)
    return ev.conferir(e)


def ler(caminho: Path, *, url_snapshot: str = "", sha256: str = "",
        leitura: Leitura | None = None, limite: int | None = None):
    """
    Gera `Evidencia` de cada item COM valor homologado positivo.

    Item só com estimado é CONTADO (`leitura.so_estimado`), não
    materializado: um milhão de linhas de orçamento não são evidência de
    preço praticado.
    """
    leitura = leitura if leitura is not None else Leitura()
    leitura.sha256 = sha256
    conferir_zip(caminho)
    with zipfile.ZipFile(caminho) as z:
        licitacoes = _licitacoes(z)
        leitura.licitacoes = len(licitacoes)
        cab, linhas = abrir_csv(z, "item.csv", separador=SEPARADOR)
        ix = _indice(cab)
        gerados = 0
        for linha in linhas:
            leitura.itens += 1
            try:
                homologado = ev.ler_decimal(linha[ix["VL_UNITARIO_HOMOLOGADO"]],
                                            formato=FORMATO_NUMERO)
            except ev.ValorInvalido:
                homologado = None
            if homologado is None or homologado <= 0:
                leitura.so_estimado += 1
                continue
            leitura.com_homologado += 1
            e = evidencia_do_item(
                linha, cab, licitacoes.get(tuple(linha[ix[c]] for c in CHAVE)),
                sha256=sha256, url_snapshot=url_snapshot)
            leitura.resultados[e.resultado or ""] += 1
            leitura.motivos.update(e.motivos)
            yield e
            gerados += 1
            if limite is not None and gerados >= limite:
                return

