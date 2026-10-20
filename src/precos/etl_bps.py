"""
BPS — Banco de Preços em Saúde (Ministério da Saúde), arquivo anual.

Leiaute conferido no arquivo real de 20/10/2026 (`2026_csv.zip`, 0,9 MB,
sha256 60ed6b06…): um `2026.csv` com `;`, UTF-8 com BOM, número com ponto
decimal, data dd/mm/aaaa, 36 colunas, 10.609 linhas, todas da classe
"DROGAS E MEDICAMENTOS". `vl_preco_unitario × qt_medicamento ==
vl_preco_total` em todas as linhas; até 4 casas decimais. O JSON do
mesmo ano traz os preços como NÚMERO JSON (float) — por isso a fonte
lida é o CSV, que traz o texto.

Etapa do preço — conferida no dicionário oficial
`Metadados_BPS_07_04_2026.pdf` (442.345 bytes, sha256 80628073…, baixado
em 20/10/2026), verbete "Preço Unitário": "Preço pago por unidade do
item adquirido. Este valor é informado com base no valor efetivamente
negociado". É preço PRATICADO, informado pela instituição compradora.
(O mesmo dicionário diz "Cobertura Temporal: 2º semestre de 2025",
enquanto o arquivo de 2026 vai de 02/01 a 28/09/2026 — a capa está
desatualizada; as colunas são as "das planilhas de 2020-2026".)

O que o arquivo NÃO prova sozinho:

* URL oficial POR REGISTRO — não há. O rastro é o arquivo do recurso
  oficial + `co_seq_bps`;
* equivalência entre medicamentos: só o mesmo CATMAT na mesma unidade de
  fornecimento é comparável (`chave_de_equivalencia`); concentração,
  forma farmacêutica e apresentação estão no próprio CATMAT, e nada aqui
  funde catmats diferentes.

`tp_compra = JUDICIAL` (compra por ordem judicial, 607 linhas) e
`modalidade = Leilão` (11) vão para a quarentena com motivo próprio.
"""

from __future__ import annotations

import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import evidencia as ev
from .arquivos import abrir_csv, conferir_zip

FONTE_ID = "bps"
VERSAO_PARSER = "bps-2026-10-20.2"
# "Preço pago por unidade do item adquirido" (dicionário de 07/04/2026)
TIPO_PRECO = ev.TipoPreco.PRATICADO
SEPARADOR = ";"
FORMATO_NUMERO = "ponto"

COLUNAS = ("ano_compra", "cnpj_instituicao", "sg_uf", "dt_compra", "co_catmat",
           "ds_item", "tp_compra", "sg_unidade_medida", "cnpj_fornecedor",
           "qt_medicamento", "no_instituicao", "no_municipio",
           "un_medida_capacidade", "nu_processo_compra", "un_fornecimento",
           "registro_anvisa", "modalidade", "vl_capacidade",
           "vl_preco_unitario", "vl_preco_total", "co_seq_bps", "fg_generico")
MODALIDADES_FORA = frozenset({"Leilão"})


@dataclass
class Leitura:
    sha256: str = ""
    linhas: int = 0
    motivos: Counter = field(default_factory=Counter)


def _data(texto: str) -> str | None:
    t = (texto or "").strip()
    if len(t) == 10 and t[2] == "/" and t[5] == "/":
        return f"{t[6:]}-{t[3:5]}-{t[:2]}"
    return None


def chave_de_equivalencia(e: ev.Evidencia) -> tuple | None:
    """Mesmo CATMAT e mesma unidade de fornecimento — e nada mais amplo."""
    if not e.codigo_catalogo or not e.unidade:
        return None
    return (e.codigo_catalogo, e.unidade.strip().upper())


def evidencia_da_linha(r: dict, *, sha256: str = "",
                       url_snapshot: str = "") -> ev.Evidencia:
    def numero(coluna):
        try:
            return ev.ler_decimal(r.get(coluna), formato=FORMATO_NUMERO)
        except ev.ValorInvalido:
            return None

    e = ev.Evidencia(
        fonte_id=FONTE_ID, registro_id=str(r["co_seq_bps"]).strip(),
        descricao=" ".join((r.get("ds_item") or "").split()),
        unidade=(r.get("un_fornecimento") or "").strip() or None,
        quantidade=numero("qt_medicamento"),
        valor_unitario=numero("vl_preco_unitario"),
        valor_total=numero("vl_preco_total"),
        tipo_preco=TIPO_PRECO,
        orgao=(r.get("no_instituicao") or "").strip() or None,
        orgao_cnpj=ev.cnpj_ou_nada("J", r.get("cnpj_instituicao")),
        uf=(r.get("sg_uf") or "").strip() or None,
        municipio=(r.get("no_municipio") or "").strip() or None,
        fornecedor_cnpj=ev.cnpj_ou_nada("J", r.get("cnpj_fornecedor")),
        processo=(r.get("nu_processo_compra") or "").strip() or None,
        codigo_catalogo=(r.get("co_catmat") or "").strip() or None,
        data_resultado=_data(r.get("dt_compra")),
        resultado=(r.get("tp_compra") or "").strip() or None,
        url_evidencia=None, url_snapshot=url_snapshot, sha256_snapshot=sha256,
        versao_parser=VERSAO_PARSER,
        atributos={"modalidade": r.get("modalidade") or None,
                   "apresentacao": r.get("un_medida_capacidade") or None,
                   "capacidade": r.get("vl_capacidade") or None,
                   "unidade_da_capacidade": r.get("sg_unidade_medida") or None,
                   "registro_anvisa": r.get("registro_anvisa") or None,
                   "generico": r.get("fg_generico") or None})
    e.hash_linha = ev.hash_da_linha(r)
    if (r.get("tp_compra") or "").strip().upper() == "JUDICIAL":
        e.motivos.append(ev.COMPRA_JUDICIAL)
    if (r.get("modalidade") or "").strip() in MODALIDADES_FORA:
        e.motivos.append(ev.MODALIDADE_FORA)
    return ev.conferir(e)


def ler(caminho: Path, *, url_snapshot: str = "", sha256: str = "",
        leitura: Leitura | None = None, limite: int | None = None):
    leitura = leitura if leitura is not None else Leitura()
    leitura.sha256 = sha256
    entradas = conferir_zip(caminho)
    nomes = [i.filename for i in entradas if i.filename.lower().endswith(".csv")]
    if len(nomes) != 1:
        raise ValueError(f"esperado um CSV no ZIP do BPS, há {nomes}")
    with zipfile.ZipFile(caminho) as z:
        cab, linhas = abrir_csv(z, nomes[0], separador=SEPARADOR)
        faltam = [c for c in COLUNAS if c not in cab]
        if faltam:
            raise ValueError(f"o CSV do BPS mudou de leiaute: faltam {faltam}")
        for i, linha in enumerate(linhas):
            leitura.linhas += 1
            e = evidencia_da_linha(dict(zip(cab, linha)), sha256=sha256,
                                   url_snapshot=url_snapshot)
            leitura.motivos.update(e.motivos)
            yield e
            if limite is not None and i + 1 >= limite:
                return
