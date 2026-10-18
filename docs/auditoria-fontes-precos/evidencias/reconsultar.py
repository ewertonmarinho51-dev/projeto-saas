"""Reconsulta cada referência da amostra na API pública do Compras.gov.br e
compara campo a campo com o que o GovConnect gravou. Somente leitura."""
import json
import sys
import time
import urllib.parse
import urllib.request
from decimal import Decimal

BASE = "https://dadosabertos.compras.gov.br/modulo-pesquisa-preco/1_consultarMaterial"
CAMPOS = ["m", "ref", "pesq", "item", "item_unid", "status", "id_compra", "catmat",
          "id_item", "n_item", "vu", "qtd", "un", "orgao", "cnpj", "data", "mod", "uasg"]


def obter(id_compra, catmat):
    q = urllib.parse.urlencode({"pagina": 1, "tamanhoPagina": 50, "tipo": "codigoItemCatalogo",
                                "codigo": catmat, "idCompra": id_compra})
    req = urllib.request.Request(f"{BASE}?{q}", headers={"Accept": "application/json",
                                                        "User-Agent": "auditoria-govconnect"})
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except Exception as erro:  # noqa: BLE001
            ultimo = erro
            time.sleep(2 * (tentativa + 1))
    return None, {"erro": str(ultimo)}


def dec(v):
    return None if v is None else Decimal(str(v)).normalize()


def main(caminho, saida):
    linhas = [dict(zip(CAMPOS, l)) for l in json.load(open(caminho, encoding="utf-8"))]
    vistos, resultados = {}, []
    for l in linhas:
        chave = l["id_item"]
        if chave not in vistos:
            status, dados = obter(l["id_compra"], l["catmat"])
            vistos[chave] = (status, dados)
            time.sleep(0.5)
        status, dados = vistos[chave]
        achado = next((r for r in (dados.get("resultado") or [])
                       if str(r.get("idItemCompra")) == str(l["id_item"])), None)
        dif = []
        if achado:
            pares = {
                "precoUnitario": (dec(l["vu"]), dec(achado.get("precoUnitario"))),
                "quantidade": (dec(l["qtd"]), dec(achado.get("quantidade"))),
                "unidade": (l["un"], achado.get("siglaUnidadeFornecimento")),
                "cnpj": (l["cnpj"], achado.get("niFornecedor")),
                "dataCompra": (l["data"], (achado.get("dataCompra") or "")[:10]),
                "modalidade": (l["mod"], str(achado.get("modalidade"))),
                "numeroItem": (l["n_item"], str(achado.get("numeroItemCompra"))),
                "uasg": (l["uasg"], achado.get("codigoUasg")),
                "orgao": (l["orgao"], achado.get("nomeOrgao") or achado.get("nomeUasg")),
            }
            dif = [f"{k}: gravado={a!r} fonte={b!r}" for k, (a, b) in pares.items() if a != b]
        resultados.append({**l, "http": status, "localizado": bool(achado),
                           "registros_na_resposta": len(dados.get("resultado") or []),
                           "divergencias": dif,
                           "fonte": {k: achado.get(k) for k in (
                               "precoUnitario", "quantidade", "siglaUnidadeFornecimento",
                               "nomeOrgao", "nomeUasg", "nomeFornecedor", "niFornecedor",
                               "dataCompra", "dataResultado", "descricaoItem",
                               "dataHoraAtualizacaoItem")} if achado else None,
                           "erro": dados.get("erro")})
        print(f"{l['ref']} {l['id_compra']:>17} item {l['n_item']:>4} http={status} "
              f"localizado={bool(achado)} dif={len(dif)} {'; '.join(dif)[:160]}", flush=True)
    json.dump(resultados, open(saida, "w", encoding="utf-8"), ensure_ascii=False, indent=1,
              default=str)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
