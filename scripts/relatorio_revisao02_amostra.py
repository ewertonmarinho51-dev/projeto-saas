#!/usr/bin/env python
"""
Amostra REAL do Relatório de Cotação da Revisão 02 — para inspeção visual,
auditoria de links e comparação com o PDF de referência.

Os preços vêm de registros REAIS das APIs oficiais gravados nas fixtures
(`tests/fixtures/precos/compras_precos_praticados.json` e
`compras_itens_contratacoes.json`), passados pelos parsers reais dos
adaptadores (`compras_gov._referencia_de_preco_praticado`,
`_referencia_de_item_contratado`) e pelo caminho real da cotação
automática (triagem v2, teto de 15) — no banco DUBLÊ em memória. Nada é
gravado em Supabase e nada consulta rede.

Saída (`--saida`): `relatorio.docx`, `links.json` (texto impresso → URL,
para a tabela de correspondência) e `vista.json` (resumo do que foi
calculado). O PDF é feito fora daqui (o conversor da produção é o
LibreOffice; nesta máquina a conversão foi feita pelo Word e os links
carimbados por `documento_cotacao.carimbar_links`, como na produção).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--saida", required=True)
    args = parser.parse_args()
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)

    from src import db, governanca
    from src.precos import compras_gov, cotacoes, saneamento
    from src.precos import documento_cotacao as dc
    from src.precos import relatorio_view as rv
    from src.precos import repositorio as repo
    from src.precos.fontes import ResultadoBusca
    from tests import conftest

    cliente = conftest.ClientePrecosFalso()
    db.cliente_do_usuario = lambda: cliente
    db.flag_ativa = lambda nome: nome == governanca.FLAG_TETO_AUTOMATICO
    fixtures = RAIZ / "tests" / "fixtures" / "precos"
    praticados = json.loads((fixtures / "compras_precos_praticados.json")
                            .read_text(encoding="utf-8"))["resultado"]
    contratados = json.loads((fixtures / "compras_itens_contratacoes.json")
                             .read_text(encoding="utf-8"))["resultado"]

    class Fonte:
        def __init__(self, fonte, referencias):
            self.fonte, self._refs = fonte, referencias

        def pesquisar(self, consulta):
            return ResultadoBusca(fonte=self.fonte, referencias=self._refs())

    ctx = cotacoes.Contexto(auth_user_id="amostra")
    cotacao = cotacoes.criar_cotacao(ctx, {
        "nome": "Amostra Revisão 02 — instrumentos de medição",
        "objeto": "Pesquisa de preços de amostra (registros públicos reais "
                  "gravados nas fixtures; cotação montada em banco dublê)",
        "responsavel": "Equipe de homologação", "local_referencia": "Paragominas/PA",
        "perfil_normativo": "in_65_2021", "data_base": "2025-09-30"})
    cid = str(cotacao["id"])
    alicate = praticados[0]["descricaoItem"]
    i1 = cotacoes.salvar_item(ctx, cid, {"descricao": alicate,
                                         "unidade": "UNIDADE",
                                         "quantidade": "4"})
    cotacoes.pesquisar_item(
        ctx, cid, str(i1["id"]), modo="automatico",
        fontes=[Fonte(compras_gov.FONTE_PRECOS, lambda: [
            compras_gov._referencia_de_preco_praticado(b) for b in praticados])],
        triagem=saneamento.POLITICA_PADRAO)
    itens_pncp = [b for b in contratados
                  if b.get("numeroControlePNCPCompra", "").startswith("10806496")]
    i2 = cotacoes.salvar_item(ctx, cid, {
        "descricao": next(b["descricaodetalhada"] for b in itens_pncp
                         if b["descricaodetalhada"].startswith("MULTÍMETRO")),
        "unidade": "UNIDADE",
        "quantidade": "2"})
    cotacoes.pesquisar_item(
        ctx, cid, str(i2["id"]), modo="automatico",
        fontes=[Fonte(compras_gov.FONTE_ITENS, lambda: [
            compras_gov._referencia_de_item_contratado(b) for b in itens_pncp])],
        triagem=saneamento.POLITICA_PADRAO)

    # o servidor decide sobre o atípico do item 1 (mantém) e conclui
    linhas1 = repo.listar_referencias(str(i1["id"]))
    for linha in linhas1:
        if str(linha.get("status")) == "warning":
            cotacoes.manter_referencia(ctx, cid, str(i1["id"]), str(linha["id"]))
    item1 = repo.obter_item(str(i1["id"]))
    if item1["estado"] == "review":
        cotacoes.concluir_item(ctx, cid, str(i1["id"]),
                               justificativa="série conferida nas contratações "
                                             "de origem")

    pesquisa = repo.obter_pesquisa(cid)
    itens = repo.listar_itens(cid)
    refs = {str(i["id"]): repo.listar_referencias(str(i["id"])) for i in itens}
    vista = rv.projetar(pesquisa, itens, refs,
                        emitido_em=datetime.now(timezone.utc))
    (saida / "relatorio.docx").write_bytes(dc.relatorio_de_cotacao_docx(vista))
    (saida / "analitico.docx").write_bytes(dc.relatorio_analitico_docx(vista))
    (saida / "links.json").write_text(json.dumps(
        {"principal": dc.links_da_vista(vista),
         "analitico": dc.links_da_vista(vista, analitico=True)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    resumo = [{"item": i.numero, "titulo": i.titulo, "estado": i.estado,
               "usados": i.consideradas, "unitario": str(i.preco_unitario),
               "total": str(i.preco_total),
               "referencias": [{"orgao": r.orgao, "valor": str(r.valor),
                                "considerada": r.considerada,
                                "sinalizada": r.sinalizada,
                                "situacao": r.situacao,
                                "contratacao_url": r.contratacao_url,
                                "dados_url": r.dados_url}
                               for r in i.referencias]}
              for i in vista.itens]
    (saida / "vista.json").write_text(json.dumps(resumo, ensure_ascii=False,
                                                 indent=2), encoding="utf-8")
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
