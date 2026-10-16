"""
Apoio comum às provas de Cotações (G0–G6).

Montadores de linhas persistidas e de cotações sobre o banco falso de
`conftest.ClientePrecosFalso` — os mesmos dublês das provas de preços,
para que nenhum teste de Cotações tenha uma segunda ideia do que é uma
linha gravada. Nada aqui chama rede nem IA.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src import db
from src.precos import estatistica
from src.precos import repositorio as repo
from src.precos.modelo import Fonte, NaturezaValor, Referencia, hash_do_bruto
from tests.conftest import ClientePrecosFalso

FONTE_PRECOS = Fonte("compras_gov_precos", "Compras.gov — preços praticados",
                     "sistema_oficial")
FONTE_ITENS = Fonte("compras_gov_itens", "Compras.gov — itens de contratações",
                    "contratacao_similar")
FONTE_PNCP = Fonte("pncp", "PNCP", "sistema_oficial")

TABELAS = ("pesquisas_preco", "pesquisa_preco_itens",
           "pesquisa_preco_referencias", "pesquisa_preco_eventos",
           "pesquisa_preco_emissoes")


def linha(valor, status="selected", *, ident=None, natureza="homologado",
          fonte=FONTE_PRECOS, unidade="UNIDADE", motivos=None,
          coletado_em="2026-10-16T12:00:00+00:00", **extras) -> dict:
    """Uma linha de `pesquisa_preco_referencias` como o banco a devolve."""
    ident = ident or f"r-{valor}-{status}"
    bruto = {"id": ident, "valor": str(valor)}
    return {
        "id": f"id-{ident}", "item_id": extras.pop("item_id", "item-1"),
        "fonte_id": fonte.id, "fonte_nome": fonte.nome,
        "fonte_tipo": fonte.tipo, "id_externo": ident,
        "raw_hash": hash_do_bruto(bruto), "bruto": bruto,
        "descricao_original": extras.pop("descricao", "PAPEL A4"),
        "unidade_original": unidade, "unidade_normalizada": unidade,
        "valor_unitario_original": str(valor),
        "valor_unitario_normalizado": None if valor is None else str(valor),
        "natureza_valor": natureza, "status": status,
        "motivos": list(motivos or []), "orgao": "Prefeitura X", "uf": "PA",
        "data_compra": "2026-06-01", "coletado_em": coletado_em,
        "score": "0.9", **extras,
    }


def ligar_banco_falso(monkeypatch) -> ClientePrecosFalso:
    cliente = ClientePrecosFalso()
    for tabela in TABELAS:
        cliente.tabelas.setdefault(tabela, [])
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: cliente)
    return cliente


def referencia(valor: str, ident: str, *, fonte=FONTE_PRECOS,
               descricao="PAPEL SULFITE A4 75G", unidade="RESMA",
               natureza=NaturezaValor.HOMOLOGADO) -> Referencia:
    return Referencia(
        fonte=fonte, id_externo=ident, bruto={"id": ident, "valor": valor},
        descricao_original=descricao, unidade_original=unidade,
        quantidade_original=Decimal("10"),
        valor_unitario_original=Decimal(valor), natureza_valor=natureza,
        orgao="Prefeitura Y", uf="PA", data_compra=date(2026, 6, 1))


def cotacao_com_item(*, perfil_id="lei_14133", unidade="RESMA",
                     quantidade="10", nome="Cotação de teste") -> tuple[dict, dict]:
    """Cria cotação e um item pelo repositório REAL (no banco falso)."""
    pesquisa = repo.criar_pesquisa(
        nome, auth_user_id="u1", perfil_normativo=perfil_id,
        versao_regras=estatistica.REGRAS_MEDIA_PADRAO)
    [item] = repo.salvar_itens(str(pesquisa["id"]), [{
        "numero": 1, "descricao": "PAPEL SULFITE A4 75G",
        "unidade": unidade, "quantidade": quantidade}])
    return pesquisa, item
