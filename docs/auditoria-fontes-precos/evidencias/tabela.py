"""Gera a tabela B do relatório a partir de resultado.json (reconsulta real)."""
import json
import sys
from decimal import Decimal

PORTAL = "https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra"

# Conferidos item a item no portal Compras.gov.br em 18/10/2026 (fornecedor e valor adjudicado).
NO_PORTAL = {"12848928", "12728225", "12660435", "12978349", "12977646", "12989072"}

PESQ = {"aquisição de": "aquisição (17/10)", "Fornecimento": "Fornecimento (18/10)",
        "Material de ": "Material de Expediente (08/10)"}

# Adequação ao item pesquisado — avaliação SEPARADA da autenticidade.
ADEQ = {
    "12728225": "INADEQUADA — papel A3 (420×297) na cesta de papel A4",
    "13021849": "INADEQUADA — papel A4 \"cor: colorido\" na cesta de papel branco",
    "12677983": "inadequada (já rejeitada) — offset 210×148, preço por folha",
    "12977596": "DUVIDOSA — clipe tamanho 0; o item pede 2/0",
    "11731063": "inadequada (em revisão) — grampeador cirúrgico",
    "12841884": "inadequada (já rejeitada) — grampeador cirúrgico",
    "12905112": "inadequada (já rejeitada) — clipe 4/0, inexigibilidade",
    "12809472": "DUVIDOSA — caneta de metal personalizada (sinalizada)",
    "12913394": "DUVIDOSA — caneta avulsa R$ 0,49 convertida para caixa de 50 (R$ 24,50) pela capacidade da fonte",
    "12660435": "INADEQUADA — papel offset 960×660 mm (sinalizado, mas dentro da cesta)",
    "12728156": "INADEQUADA — papel texturizado colorido; convertido de 50 folhas para pacote (R$ 4,60)",
    "12977646": "adequada com conversão — caixa com 20 (fonte) → R$ 11,18 por unidade",
    "12848928": "INADEQUADA — grampeador cirúrgico na cesta de grampeador de mesa",
    "12729225": "DUVIDOSA — grampeador tipo alicate na cesta de grampeador de mesa",
}


def moeda(v):
    q = Decimal(str(v)).quantize(Decimal("0.0001"))
    s = f"{q:,.4f}".rstrip("0").rstrip(".") if q != q.to_integral() else f"{q:,.2f}"
    if "." in s and len(s.split(".")[1]) < 2:
        s += "0"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def main(caminho):
    linhas = json.load(open(caminho, encoding="utf-8"))
    vistos = {}
    for x in linhas:
        vistos.setdefault(x["id_item"], []).append(x)
    print("| Nº | Registro (idItemCompra) | Onde aparece no GovConnect | Contratação (link original) | Valor no GovConnect | Valor na fonte | Divergências | Autenticidade | Adequação ao item | Evidência |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for n, (id_item, grupo) in enumerate(vistos.items(), start=1):
        x = grupo[0]
        f = x["fonte"]
        compra17 = str(x["id_compra"]).zfill(17)
        link = f"[{compra17} · item {x['n_item']}]({PORTAL}/item/{x['n_item']}?compra={compra17})"
        onde = "; ".join(f"{PESQ.get(g['pesq'], g['pesq'])} item {g['item']} ({g['status']})" for g in grupo)
        div = "; ".join(sum((g["divergencias"] for g in grupo), [])) or "nenhuma (9 campos)"
        extra = " · idCompra com 16 dígitos na fonte: relatório sem link" if len(str(x["id_compra"])) == 16 else ""
        evid = ("API Dados Abertos (18/10) + portal, item a item" if id_item in NO_PORTAL
                else "API Dados Abertos (18/10)")
        aut = "VERIFICADA" if x["localizado"] and not x["divergencias"] else "PARCIALMENTE VERIFICADA"
        print(f"| {n} | {id_item} | {onde} | {link}{extra} | {moeda(x['vu'])} / {x['un'] or 's/ unid.'} "
              f"| {moeda(f['precoUnitario'])} / {f['siglaUnidadeFornecimento'] or 's/ unid.'} | {div} "
              f"| {aut} | {ADEQ.get(id_item, 'adequada')} | {evid} |")


if __name__ == "__main__":
    main(sys.argv[1])
