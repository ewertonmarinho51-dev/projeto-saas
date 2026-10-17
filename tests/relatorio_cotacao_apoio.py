"""
Cenários SINTÉTICOS do relatório de cotação (pacote de 16/10/2026,
`05_TESTES_ACEITE.md`, matriz de volume).

Os números de cada item NÃO são escritos aqui: saem do motor real —
`cesta.recalcular` e o mesmo mapeamento de `repositorio.atualizar_estimativa`
—, a partir de referências geradas com semente fixa. Assim a fixture não
tem uma segunda ideia de como se forma um preço, e o teste que confere o
relatório contra a fixture confere contra o domínio.

Nada aqui vem dos PDFs de referência: órgãos, fornecedores, pessoas e
identificadores são inventados e marcados como fictícios.
"""

from __future__ import annotations

import hashlib
import json
import random
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from src.precos import cesta, estatistica
from src.precos import repositorio as repo
from src.precos.perfil import obter as obter_perfil

CASO_210 = Path(__file__).resolve().parent / "fixtures" / "caso_210_itens.json"

FONTES = (
    ("compras_gov_precos", "Compras.gov (preços praticados)", "sistema_oficial",
     "homologado"),
    ("pncp", "PNCP", "sistema_oficial", "homologado"),
    ("compras_gov_itens", "Compras.gov (itens de contratações)",
     "contratacao_similar", "adjudicado"),
)
UFS = ("PA", "MA", "TO", "AM", "PR", "MG", "SP", "GO", "BA", "CE")
MOTIVOS_EXCLUSAO = (
    "fora da curva: valor muito acima dos demais",
    "unidade de fornecimento diferente (caixa x unidade)",
    "especificação não equivalente (gramatura menor)",
    "quantidade contratada incomparável",
)


def _hash(*partes) -> str:
    return hashlib.sha256("|".join(map(str, partes)).encode()).hexdigest()


def _dinheiro(valor: float) -> str:
    return str(Decimal(str(valor)).quantize(Decimal("0.01"),
                                           rounding=ROUND_HALF_UP))


def pesquisa_base(**extras) -> dict:
    base = {
        "id": "0f1e2d3c-sint-4b5a-9c8d-000000000001", "versao": 1,
        "nome": "Material de Expediente (cenário sintético)",
        "objeto": "Aquisição de materiais de expediente — dados fictícios "
                  "de teste, sem validade para contratação.",
        "estado": "completed", "perfil_normativo": "lei_14133",
        "data_base": "2026-10-08", "criado_em": "2026-10-08T12:00:00+00:00",
        "responsavel": "Servidor Responsável (fictício)",
        "local_referencia": "Município Exemplo/PA",
        "filtros": {"janela_dias": 180, "uf": "PA"},
        "versao_regras": estatistica.REGRAS_MEDIA_PADRAO,
    }
    base.update(extras)
    return base


def _referencia(item_id: str, n: int, valor: Decimal, rnd: random.Random, *,
                status: str, unidade: str, fonte=None, motivos=None,
                com_link: bool = True) -> dict:
    fid, fnome, ftipo, natureza = fonte or FONTES[n % len(FONTES)]
    uf = UFS[n % len(UFS)]
    dia = 1 + (n * 7) % 28
    mes = 4 + (n % 6)
    bruto: dict = {"id": f"{item_id}-{n}", "valor": str(valor)}
    if com_link and fid.startswith("compras_gov"):
        bruto.update({"idCompra": f"9{n:05d}05{n % 900 + 100}2026",
                      "codigoItemCatalogo": str(236000 + n % 900)})
    elif com_link and fid == "pncp":
        bruto["numeroControlePNCP"] = (
            f"{10000000000100 + n:014d}-1-{n % 999 + 1:06d}/2026")
    return {
        "id": f"ref-{item_id}-{n:05d}", "item_id": item_id, "status": status,
        "fonte_id": fid, "fonte_nome": fnome, "fonte_tipo": ftipo,
        "natureza_valor": natureza,
        "orgao": f"ÓRGÃO PÚBLICO EXEMPLO {n % 37 + 1:02d} (fictício)",
        "uf": uf, "municipio": f"Município Exemplo {n % 11 + 1}",
        "fornecedor": f"FORNECEDOR FICTÍCIO {n % 53 + 1:02d} LTDA",
        "data_compra": f"2026-{mes:02d}-{dia:02d}",
        "data_resultado": f"2026-{mes:02d}-{dia:02d}",
        "quantidade_original": str(rnd.choice((10, 20, 50, 100, 200, 500))),
        "unidade_original": unidade, "unidade_normalizada": unidade,
        "valor_unitario_original": str(valor),
        "valor_unitario_normalizado": str(valor),
        "score": str(Decimal(rnd.randint(55, 98)) / 100),
        "identidade": str(Decimal(rnd.randint(70, 99)) / 100),
        "circunstancias": str(Decimal(rnd.randint(60, 99)) / 100),
        "id_externo": f"EXT-{_hash(item_id, n)[:10].upper()}",
        "raw_hash": _hash("bruto", item_id, n),
        "bruto": bruto, "motivos": list(motivos or []),
        "descricao_original": "Descrição como devolvida pela fonte (fictícia)",
        "coletado_em": f"2026-10-15T{19 + n % 4:02d}:{n % 60:02d}:00+00:00",
    }


def _aplicar_motor(pesquisa: dict, item: dict, linhas: list[dict], *,
                   estado_concluido: str = "complete",
                   decisoes: dict | None = None) -> dict:
    """O que `atualizar_estimativa` gravaria, com o mesmo cálculo."""
    perfil = obter_perfil(pesquisa.get("perfil_normativo"))
    justificativa = None
    excecao = (decisoes or {}).get("excecao")
    if excecao:
        justificativa = cesta._texto_da_excecao(excecao)  # noqa: SLF001
    metodo = ((decisoes or {}).get("metodo") or {}).get("metodo") or \
        estatistica.METODO_AUTOMATICO
    estimativa = cesta.recalcular(
        linhas, perfil=perfil, regras=str(pesquisa.get("versao_regras") or ""),
        justificativa=justificativa, metodo=metodo)
    quantidade = Decimal(str(item["quantidade"]))
    total = estimativa.valor_total(quantidade)
    item.update({
        "metodo": (estimativa.metodo if estimativa.valor_unitario is not None
                   else None),
        "preco_estimado": (None if estimativa.valor_unitario is None
                           else format(estimativa.valor_unitario, "f")),
        "preco_total": None if total is None else format(total, "f"),
        "estatisticas": repo.estatisticas_com_decisoes(estimativa, decisoes),
        "justificativa": "\n".join(estimativa.memoria),
        "estado": estado_concluido if estimativa.concluida else "incomplete",
    })
    return item


def _item(numero: int, descricao: str, unidade: str, quantidade,
          codigo: str = "") -> dict:
    return {"id": f"item-{numero:03d}", "numero": numero,
            "descricao": descricao, "unidade": unidade,
            "quantidade": str(quantidade), "codigo": codigo,
            "tipo_catalogo": "CATMAT" if codigo else "",
            "desfechos": {"compras_gov_precos": "success_with_prices",
                          "pncp": "success_with_prices",
                          "compras_gov_itens": "success_empty"}}


def montar_item(pesquisa: dict, numero: int, descricao: str, unidade: str,
                quantidade, *, consideradas: int, excluidas: int = 0,
                candidatas: int = 0, abaixo_do_piso: int = 0,
                base: float = 25.0, dispersao: float = 0.18,
                semente: int = 0, codigo: str = "236168",
                estado_concluido: str = "complete", decisoes=None,
                com_link: bool = True, valores: list[str] | None = None
                ) -> tuple[dict, list[dict]]:
    rnd = random.Random(semente or numero * 7919)
    item = _item(numero, descricao, unidade, quantidade, codigo)
    linhas: list[dict] = []
    n = 0

    def preco() -> Decimal:
        return Decimal(_dinheiro(max(0.05, rnd.gauss(base, base * dispersao))))

    for valor in (valores or []):
        linhas.append(_referencia(item["id"], n, Decimal(valor), rnd,
                                  status="selected", unidade=unidade,
                                  com_link=com_link))
        n += 1
    for _ in range(consideradas - len(valores or [])):
        linhas.append(_referencia(item["id"], n, preco(), rnd,
                                  status="selected", unidade=unidade,
                                  com_link=com_link))
        n += 1
    for k in range(excluidas):
        linhas.append(_referencia(
            item["id"], n, preco() * Decimal("2.4"), rnd, status="rejected",
            unidade=unidade, motivos=[MOTIVOS_EXCLUSAO[k % 4]],
            com_link=com_link))
        n += 1
    for _ in range(candidatas):
        linhas.append(_referencia(item["id"], n, preco(), rnd,
                                  status="candidate", unidade=unidade,
                                  com_link=com_link))
        n += 1
    for _ in range(abaixo_do_piso):
        linhas.append(_referencia(
            item["id"], n, preco(), rnd, status="manual_review",
            unidade=unidade, motivos=["comparabilidade abaixo do piso"],
            com_link=com_link))
        n += 1
    _aplicar_motor(pesquisa, item, linhas, estado_concluido=estado_concluido,
                   decisoes=decisoes)
    return item, linhas


def _juntar(pares) -> tuple[list[dict], dict[str, list[dict]]]:
    itens = [item for item, _ in pares]
    return itens, {item["id"]: linhas for item, linhas in pares}


DESCRICOES_5 = (
    ("CLIPS NIQUELADO Nº 2/0. ESPECIFICAÇÃO: clipe para papel, arame de aço "
     "galvanizado, caixa com 100 unidades.", "CAIXA", 150),
    ("PAPEL A4 BRANCO. ESPECIFICAÇÃO: papel sulfite branco, formato A4 (210 x "
     "297 mm), gramatura 75 g/m², próprio para impressão a laser e jato de "
     "tinta, pacote contendo 500 folhas.", "PACOTE", 500),
    ("PASTA ARQUIVO AZ. ESPECIFICAÇÃO: pasta registradora tipo AZ, tamanho "
     "ofício, papelão rígido revestido, lombada larga de aproximadamente 80 "
     "mm, mecanismo metálico de fixação e visor de identificação.",
     "UNIDADE", 200),
    ("GRAMPEADOR DE MESA. ESPECIFICAÇÃO: grampeador de mesa, estrutura "
     "metálica resistente, capacidade mínima de 25 folhas de papel 75 g/m², "
     "compatível com grampos 26/6, base antiderrapante.", "UNIDADE", 50),
    ("CLIPES METÁLICOS Nº 2/0. ESPECIFICAÇÃO: clipes para papel, tamanho 2/0, "
     "em arame de aço galvanizado, resistentes à oxidação, acabamento "
     "uniforme, caixa contendo 100 unidades.", "CAIXA", 150),
)
# 196 + 317 + 25 + 270 + 63 = 871 consideradas — o volume do PDF de 907
# páginas, com a regra LEGADA (mediana quando a série é dispersa).
CONSIDERADAS_5 = (196, 317, 25, 270, 63)
BASES_5 = (4.2, 29.0, 11.18, 14.06, 2.10)


def cenario(nome: str) -> tuple[dict, list[dict], dict[str, list[dict]]]:
    """(pesquisa, itens, referências) do cenário pedido."""
    if nome == "vazio":
        return pesquisa_base(nome="Cotação sem itens (sintética)"), [], {}

    if nome == "sem_preco":
        p = pesquisa_base(estado="partial")
        return (p, *_juntar([montar_item(
            p, 1, "GRAMPEADOR DE MESA 26/6", "UNIDADE", 5, consideradas=0)]))

    if nome == "insuficiente":
        p = pesquisa_base(estado="partial")
        return (p, *_juntar([montar_item(
            p, 1, "METRÔNOMO DIGITAL", "UNIDADE", 2, consideradas=2,
            excluidas=1, base=100.0)]))

    if nome == "minima":
        # O golden do pacote: 22,70 · 29,00 · 25,85 → média 25,85.
        p = pesquisa_base()
        return (p, *_juntar([montar_item(
            p, 1, "PAPEL SULFITE A4 75G, RESMA COM 500 FOLHAS", "RESMA", 10,
            consideradas=3, valores=["22.70", "29.00", "25.85"])]))

    if nome == "excluida_vira_2":
        # 3 selecionadas, uma excluída depois: 2/3, item incompleto.
        p = pesquisa_base(estado="partial")
        item, linhas = montar_item(
            p, 1, "PAPEL SULFITE A4 75G, RESMA COM 500 FOLHAS", "RESMA", 10,
            consideradas=3, valores=["22.70", "29.00", "25.85"])
        linhas[1]["status"] = "rejected"
        linhas[1]["motivos"] = ["fora da curva: excluída pelo revisor"]
        _aplicar_motor(p, item, linhas)
        return p, [item], {item["id"]: linhas}

    if nome == "grande_196":
        p = pesquisa_base()
        return (p, *_juntar([montar_item(
            p, 1, DESCRICOES_5[0][0], "CAIXA", 150, consideradas=196,
            excluidas=20, base=4.2)]))

    if nome == "grande_317":
        p = pesquisa_base()
        return (p, *_juntar([montar_item(
            p, 1, DESCRICOES_5[1][0], "PACOTE", 500, consideradas=317,
            excluidas=30, base=29.0)]))

    if nome == "historico_5_871":
        # Regra LEGADA: o automático escolhe mediana em série dispersa.
        p = pesquisa_base(versao_regras=estatistica.REGRAS_LEGADAS,
                          nome="Material de Expediente (histórico sintético)")
        pares = []
        for i, ((descricao, unidade, qtd), n, base) in enumerate(
                zip(DESCRICOES_5, CONSIDERADAS_5, BASES_5), start=1):
            pares.append(montar_item(
                p, i, descricao, unidade, qtd, consideradas=n,
                excluidas=max(2, n // 12), candidatas=n * 2,
                abaixo_do_piso=n // 5, base=base, dispersao=0.35))
        return (p, *_juntar(pares))

    if nome == "processo_210":
        p = pesquisa_base(estado="partial",
                          nome="Processo amplo — 210 itens (sintético)")
        dados = json.loads(CASO_210.read_text(encoding="utf-8"))["itens"]
        pares = []
        for i, linha in enumerate(dados, start=1):
            n = (0, 1, 2, 3, 4, 5, 6, 8, 12)[i % 9]
            pares.append(montar_item(
                p, i, linha["descricao"], linha["unidade"],
                linha["quantidade"], consideradas=n, excluidas=i % 3,
                candidatas=i % 4, base=float(linha["valor_unitario"]),
                codigo=str(linha.get("codigo") or "")))
        return (p, *_juntar(pares))

    if nome == "extensa":
        p = pesquisa_base()
        descricao = ("CADEIRA GIRATÓRIA ERGONÔMICA. ESPECIFICAÇÃO: " + (
            "assento e encosto em espuma injetada de alta densidade, "
            "revestimento em tecido poliéster de alta resistência, "
            "mecanismo relax com regulagem de altura a gás classe 4, "
            "braços reguláveis em altura com apoio em poliuretano, base "
            "giratória em nylon com cinco rodízios de duplo giro; ") * 3
        ).strip()
        return (p, *_juntar([montar_item(
            p, 1, descricao, "UNIDADE", 12, consideradas=3, excluidas=1,
            base=890.0)]))

    if nome == "fontes_ausentes":
        p = pesquisa_base(estado="partial")
        pares = []
        for i, (descricao, unidade, qtd) in enumerate(DESCRICOES_5, start=1):
            item, linhas = montar_item(p, i, descricao, unidade, qtd,
                                       consideradas=0)
            item["desfechos"] = {"compras_gov_precos": "failure",
                                 "pncp": "success_empty"}
            pares.append((item, linhas))
        return (p, *_juntar(pares))

    if nome == "pendencias":
        p = pesquisa_base(estado="partial",
                          nome="Cotação com pendências (sintética)")
        pares = [
            montar_item(p, 1, DESCRICOES_5[1][0], "PACOTE", 500,
                        consideradas=5, excluidas=1, base=29.0),
            montar_item(p, 2, "GRAMPEADOR DE MESA 26/6", "UNIDADE", 5,
                        consideradas=0),
            montar_item(p, 3, "METRÔNOMO DIGITAL", "UNIDADE", 2,
                        consideradas=2, excluidas=1, base=100.0),
            montar_item(p, 4, DESCRICOES_5[2][0], "UNIDADE", 200,
                        consideradas=4, base=11.18,
                        estado_concluido="review"),
        ]
        excecao = {"texto": "mercado restrito: apenas dois fornecedores "
                            "atenderam no período", "fundamento": "mercado",
                   "fundamento_texto": "mercado restrito",
                   "base_normativa": "Lei 14.133/2021, art. 23",
                   "aprovador": "Autoridade competente (fictícia)",
                   "consideradas": 2}
        item, linhas = montar_item(
            p, 5, "TONER COMPATÍVEL HP 85A", "UNIDADE", 30, consideradas=2,
            base=80.0, decisoes={"excecao": excecao})
        pares.append((item, linhas))
        return (p, *_juntar(pares))

    raise KeyError(nome)


CENARIOS = ("vazio", "sem_preco", "insuficiente", "minima", "excluida_vira_2",
            "grande_196", "grande_317", "historico_5_871", "processo_210",
            "extensa", "fontes_ausentes", "pendencias")
