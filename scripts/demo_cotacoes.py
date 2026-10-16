"""
Demonstração reproduzível de Cotações — GovConnect SINTÉTICO.

    streamlit run scripts/demo_cotacoes.py --server.port 8765

Roda o app de verdade (`app.py`) com:

* banco EM MEMÓRIA (o dublê de PostgREST das provas), semeado com uma
  cotação de 10 itens fictícios — nada é lido ou gravado em Supabase;
* fontes de preço SINTÉTICAS: uma responde com preços, outra simula
  indisponibilidade (para a tela mostrar "INDISPONÍVEL"), e o item
  fictício "PARAFUSO TITANIO XQ9Z" recebe só vizinhos não comparáveis;
* flags `price_research` e `unified_quotations` ligadas; Jev DESLIGADO.

Barreira de segurança: o cliente de SERVIDOR do app é substituído por um
que levanta erro. Se algum caminho tentasse o banco real, a demo cairia
em vez de tocá-lo. Nenhuma credencial é lida.
"""

from __future__ import annotations

import os
import runpy
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ["GOVDOCS_MODO_ABERTO"] = "1"

import streamlit as st  # noqa: E402

from src import db, governanca  # noqa: E402
from src.precos import cotacoes  # noqa: E402
from src.precos.fontes import ResultadoBusca  # noqa: E402
from src.precos.modelo import Fonte, NaturezaValor, Referencia  # noqa: E402


class _SemBancoReal:
    def __getattr__(self, nome):
        raise RuntimeError("demo: acesso ao banco real bloqueado")


class FontePrecosSintetica:
    fonte = Fonte("compras_gov_precos", "Compras.gov — preços praticados",
                  "sistema_oficial")

    def pesquisar(self, consulta):
        texto = consulta.descricao.upper()
        if "XQ9Z" in texto:
            refs = [self._ref(f"viz{i}", f"PARAFUSO SEXTAVADO ZINCADO M{6 + i}",
                              "UNIDADE", Decimal("0.35") + Decimal(i) / 10)
                    for i in range(11)]
            return ResultadoBusca(fonte=self.fonte, referencias=refs)
        base = Decimal(sum(ord(c) for c in texto) % 40 + 8)
        fatores = ("0.94", "1.00", "1.03", "1.08", "0.97", "1.31")
        refs = [self._ref(f"{abs(hash(texto)) % 10000}-{i}", consulta.descricao,
                          consulta.unidade or "UNIDADE",
                          (base * Decimal(f)).quantize(Decimal("0.01")),
                          dias=20 * i)
                for i, f in enumerate(fatores)]
        refs.append(self._ref(f"{abs(hash(texto)) % 10000}-est",
                              consulta.descricao, consulta.unidade or "UNIDADE",
                              base * 2, natureza=NaturezaValor.ESTIMADO_ORIGEM))
        return ResultadoBusca(fonte=self.fonte, referencias=refs)

    def _ref(self, ident, descricao, unidade, valor, *, dias=10,
             natureza=NaturezaValor.HOMOLOGADO):
        return Referencia(
            fonte=self.fonte, id_externo=ident,
            bruto={"idCompra": ident, "valor": str(valor), "sintetico": True},
            descricao_original=descricao, unidade_original=unidade,
            quantidade_original=Decimal("50"), valor_unitario_original=valor,
            natureza_valor=natureza, orgao="Órgão sintético", uf="PA",
            fornecedor="Fornecedor sintético",
            data_compra=date.today() - timedelta(days=dias))


class FonteForaDoAr:
    fonte = Fonte("pncp", "PNCP", "sistema_oficial")

    def pesquisar(self, consulta):
        raise TimeoutError("demo: fonte simulando indisponibilidade")


ITENS = [
    ("PAPEL SULFITE A4 75G, PACOTE COM 500 FOLHAS", "PACOTE", 200),
    ("CANETA ESFEROGRÁFICA AZUL, PONTA MÉDIA 1,0 MM", "UNIDADE", 500),
    ("GRAMPEADOR DE MESA 26/6, CAPACIDADE 25 FOLHAS", "UNIDADE", 20),
    ("GRAMPO 26/6 GALVANIZADO, CAIXA COM 5000", "CAIXA", 40),
    ("PASTA SUSPENSA MARMORIZADA COM HASTE PLÁSTICA", "UNIDADE", 150),
    ("CLIPS NIQUELADO 2/0, CAIXA COM 100", "CAIXA", 60),
    ("FITA ADESIVA TRANSPARENTE 12 MM X 50 M", "ROLO", 120),
    ("MARCADOR PARA QUADRO BRANCO AZUL", "UNIDADE", 80),
    ("PARAFUSO TITANIO XQ9Z", "UNIDADE", 10),
    ("ENVELOPE PARDO A4 229 X 324 MM", "UNIDADE", 300),
]


@st.cache_resource
def _banco():
    from tests.conftest import ClientePrecosFalso

    cliente = ClientePrecosFalso()
    for tabela in ("pesquisas_preco", "pesquisa_preco_itens",
                   "pesquisa_preco_referencias", "pesquisa_preco_eventos"):
        cliente.tabelas.setdefault(tabela, [])
    return cliente


def _preparar() -> None:
    cliente = _banco()
    db.disponivel = lambda: False
    db._cliente = lambda: _SemBancoReal()
    db.cliente_do_usuario = lambda: cliente
    ligadas = {governanca.FLAG_PESQUISA_PRECOS,
               governanca.FLAG_COTACOES_UNIFICADAS}
    db.flag_ativa = lambda nome: nome in ligadas
    fontes = [FontePrecosSintetica(), FonteForaDoAr()]
    from src.ui import cotacoes_ui, precos_ui

    precos_ui._fontes = lambda: fontes
    cotacoes_ui._fontes = lambda: fontes
    st.session_state.setdefault("usuario", {
        "auth_user_id": "00000000-0000-0000-0000-00000000demo",
        "login": "servidor.demo", "nome": "Servidor de Demonstração",
        "papel": "servidor", "secretaria_id": None})
    st.session_state.setdefault("pagina", "Cotações")
    if not cliente.tabelas["pesquisas_preco"]:
        ctx = cotacoes.Contexto(auth_user_id=st.session_state["usuario"]
                                ["auth_user_id"])
        cotacao = cotacoes.criar_cotacao(ctx, {
            "nome": "Demonstração — material de expediente 2026",
            "objeto": "Aquisição de material de expediente (dados sintéticos)",
            "responsavel": "Servidor de Demonstração",
            "local_referencia": "Município Sintético/PA"},
            idempotency_key="demo")
        for descricao, unidade, quantidade in ITENS:
            cotacoes.salvar_item(ctx, str(cotacao["id"]), {
                "descricao": descricao, "unidade": unidade,
                "quantidade": quantidade})


_preparar()
runpy.run_path(str(RAIZ / "app.py"), run_name="__main__")
