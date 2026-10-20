"""
ETL de bancada das fontes de preço novas (TCE-RS, BPS) — sem gravar no banco.

    python scripts/etl_fontes_precos.py baixar --fonte tce_rs --destino D:/fontes
    python scripts/etl_fontes_precos.py relatorio --fonte bps --zip D:/fontes/2026_csv.zip \
        --saida relatorio_bps.json [--amostra 30] [--termos "papel a4" "caneta azul"]

`baixar` só aceita as URLs oficiais de `fontes_externas.REGISTRO`.
`relatorio` lê o ZIP em streaming e escreve, em JSON: hash, linhas
brutas, com preço, validadas, quarentena por motivo, duplicatas internas,
uma amostra aleatória (semente fixa) de evidências e, com `--termos`,
quantas linhas casam com cada termo — o ganho POSSÍVEL, não o real.

Nada aqui grava no Supabase: a tabela de evidências é proposta
(`docs/fontes-precos/0030_proposta_fontes_externas.sql`) e não foi
aplicada. Nada aqui habilita fonte.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import unicodedata
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src.precos import arquivos, dedup_fontes, etl_bps, etl_tce_rs  # noqa: E402
from src.precos.fontes_externas import REGISTRO  # noqa: E402

PARSERS = {"tce_rs": etl_tce_rs, "bps": etl_bps}
SEMENTE = 20261020


def _sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.upper())
    return "".join(c for c in t if not unicodedata.combining(c))


def relatorio(fonte: str, caminho: Path, *, amostra: int = 30,
              termos: list[str] | None = None, limite: int | None = None) -> dict:
    parser = PARSERS[fonte]
    sha = arquivos.sha256_do_arquivo(caminho)
    url = REGISTRO[fonte].downloads[0]
    leitura = parser.Leitura()
    termos = [(_sem_acento(t), t) for t in termos or []]
    por_termo = {t: Counter() for _, t in termos}
    vistas, fornecedores = set(), set()
    contagem, motivos, reservatorio = Counter(), Counter(), []
    sorteio = random.Random(SEMENTE)
    # streaming: o TCE-RS 2026 gera 452 mil evidências — nada fica em lista
    for e in parser.ler(caminho, url_snapshot=url, sha256=sha,
                        leitura=leitura, limite=limite):
        contagem["evidencias"] += 1
        chave = dedup_fontes.chave_forte(e)
        if chave in vistas:
            contagem["duplicatas_internas"] += 1
            continue
        vistas.add(chave)
        contagem["unicas"] += 1
        contagem["validadas"] += e.validada
        contagem["com_url_oficial"] += (e.url_evidencia or "").startswith("https://")
        motivos.update(e.motivos)
        if e.fornecedor_cnpj:
            fornecedores.add(e.fornecedor_cnpj)
        texto = _sem_acento(e.descricao)
        for normal, t in termos:
            if all(p in texto for p in normal.split()):
                por_termo[t]["linhas"] += 1
                por_termo[t]["validadas"] += e.validada
        # amostragem por reservatório (algoritmo R), semente fixa
        n = contagem["unicas"]
        if len(reservatorio) < amostra:
            reservatorio.append(e.para_registro())
        else:
            j = sorteio.randrange(n)
            if j < amostra:
                reservatorio[j] = e.para_registro()
    return {
        "fonte": fonte, "url": url, "arquivo": caminho.name, "sha256": sha,
        "bytes": caminho.stat().st_size, "versao_parser": parser.VERSAO_PARSER,
        "leitura": {k: (dict(v) if isinstance(v, Counter) else v)
                    for k, v in vars(leitura).items()},
        "evidencias": contagem["evidencias"],
        "duplicatas_internas": contagem["duplicatas_internas"],
        "validadas": contagem["validadas"],
        "quarentena_por_motivo": dict(motivos.most_common()),
        "com_url_oficial": contagem["com_url_oficial"],
        "fornecedores_distintos": len(fornecedores),
        "por_termo": {t: dict(c) for t, c in por_termo.items()},
        "amostra": reservatorio,
        "aviso": ("relatório de staging: nenhuma linha validada vira preço "
                  "enquanto a fonte não estiver habilitada em fontes_externas"),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = p.add_subparsers(dest="acao", required=True)
    b = sub.add_parser("baixar")
    b.add_argument("--fonte", required=True, choices=sorted(PARSERS))
    b.add_argument("--destino", required=True, type=Path)
    r = sub.add_parser("relatorio")
    r.add_argument("--fonte", required=True, choices=sorted(PARSERS))
    r.add_argument("--zip", required=True, type=Path)
    r.add_argument("--saida", type=Path)
    r.add_argument("--amostra", type=int, default=30)
    r.add_argument("--termos", nargs="*", default=[])
    a = p.parse_args(argv)
    if a.acao == "baixar":
        a.destino.mkdir(parents=True, exist_ok=True)
        url = REGISTRO[a.fonte].downloads[0]
        snap = arquivos.baixar(url, a.destino / url.rsplit("/", 1)[-1])
        print(json.dumps({"url": snap.url, "arquivo": str(snap.caminho),
                          "sha256": snap.sha256, "bytes": snap.bytes,
                          "last_modified": snap.last_modified, "etag": snap.etag},
                         ensure_ascii=False, indent=1))
        return 0
    saida = relatorio(a.fonte, a.zip, amostra=a.amostra, termos=a.termos)
    texto = json.dumps(saida, ensure_ascii=False, indent=1)
    if a.saida:
        a.saida.write_text(texto, encoding="utf-8")
        print(f"relatório em {a.saida}: {saida['evidencias']} evidências, "
              f"{saida['validadas']} validadas")
    else:
        print(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
