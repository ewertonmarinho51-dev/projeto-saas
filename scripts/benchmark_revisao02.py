#!/usr/bin/env python
"""
Benchmark da Revisão 02 — remoção na cesta, troca de item e relatório.

Mede o MESMO roteiro, na mesma máquina, contra qualquer checkout do
repositório (`--raiz`): rodar uma vez na `main` (antes) e outra neste
branch (depois) dá o p50/p95 comparável que o 07_PERFORMANCE pede.

O que mede:

* `remover_servico` — `cotacoes.alterar_status_referencia(incluir=False)`:
  tempo e requisições ao banco por clique, em cestas de 15 e de 317
  referências (a cesta antiga, sem teto);
* `remover_tela` — o clique de remover na tela de Cotações (AppTest: o
  script inteiro do Streamlit roda de novo, como no navegador) até o fim
  do desenho no servidor. NÃO inclui o paint do navegador;
* `trocar_item` — clicar outro item da lista até o fim do desenho;
* `relatorio_docx` — o Relatório de Cotação (DOCX) de 5 e 15 itens. O
  PDF depende do LibreOffice da produção, ausente nesta máquina; o tempo
  do conversor não entra (dito no JSON).

Banco: o dublê de PostgREST das provas (`tests/conftest`), com latência
SIMULADA por requisição (`--latencia-ms`, padrão 60 ms — a mesma da prévia
local do pacote de 17/10). Fontes: dublês sem rede. Nenhuma IA.

    python scripts/benchmark_revisao02.py --raiz <checkout> --saida x.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path


def _percentil(valores: list[float], fracao: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    posicao = (len(ordenados) - 1) * fracao
    baixo = int(posicao)
    alto = min(baixo + 1, len(ordenados) - 1)
    return ordenados[baixo] + (ordenados[alto] - ordenados[baixo]) * \
        (posicao - baixo)


def _resumo(segundos: list[float], requisicoes: list[int] | None = None) -> dict:
    saida = {"n": len(segundos),
             "p50_ms": round(_percentil(segundos, 0.5) * 1000, 1),
             "p95_ms": round(_percentil(segundos, 0.95) * 1000, 1),
             "media_ms": round(statistics.fmean(segundos) * 1000, 1)
             if segundos else 0.0}
    if requisicoes is not None:
        saida["req_banco_p50"] = _percentil([float(r) for r in requisicoes], 0.5)
        saida["req_banco_max"] = max(requisicoes) if requisicoes else 0
    return saida


class Contador:
    def __init__(self):
        self.requisicoes = 0


_ESTADO: dict = {}


def _instrumentar_banco(latencia_s: float, contador: Contador) -> None:
    """Embrulha `execute` UMA vez; chamadas seguintes só trocam o ajuste."""
    from tests import conftest

    _ESTADO["latencia"], _ESTADO["contador"] = latencia_s, contador
    if "original" in _ESTADO:
        return
    _ESTADO["original"] = original = conftest.TabelaPrecosFalsa.execute

    def execute(self):
        _ESTADO["contador"].requisicoes += 1
        if _ESTADO["latencia"]:
            time.sleep(_ESTADO["latencia"])
        return original(self)

    conftest.TabelaPrecosFalsa.execute = execute


def _fonte(n_refs: int):
    from src.precos.fontes import ResultadoBusca
    from src.precos.modelo import Fonte, NaturezaValor, Referencia

    fonte_obj = Fonte("compras_gov_precos", "Compras.gov — preços praticados",
                      "sistema_oficial")

    class FonteSintetica:
        fonte = fonte_obj

        def pesquisar(self, consulta):
            refs = []
            for i in range(n_refs):
                valor = Decimal("20") + Decimal(i % 23) / 4
                refs.append(Referencia(
                    fonte=fonte_obj, id_externo=f"{consulta.descricao[:12]}-{i}",
                    bruto={"idCompra": f"{92984205000022026 + i}"},
                    descricao_original=consulta.descricao,
                    unidade_original=consulta.unidade or "UNIDADE",
                    quantidade_original=Decimal("10"),
                    valor_unitario_original=valor,
                    natureza_valor=NaturezaValor.HOMOLOGADO,
                    orgao=f"Órgão {i}", ni_fornecedor=f"F{i}", uf="PA",
                    data_compra=date.today() - timedelta(days=5 + i % 150)))
            return ResultadoBusca(fonte=self.fonte, referencias=refs)

    return FonteSintetica()


def _cotacao(itens: int, refs_por_item: int, *, teto: bool):
    """Cotação no banco dublê, itens pesquisados pela automática."""
    from src import db, governanca
    from src.precos import cotacoes

    db.flag_ativa = (lambda nome: nome == governanca.FLAG_TETO_AUTOMATICO) \
        if teto else (lambda nome: False)
    ctx = cotacoes.Contexto(auth_user_id="bench")
    c = cotacoes.criar_cotacao(ctx, {"nome": "benchmark revisão 02"})
    ids = []
    fonte = _fonte(refs_por_item)
    for n in range(itens):
        item = cotacoes.salvar_item(ctx, str(c["id"]), {
            "descricao": f"PAPEL SULFITE A4 75G ITEM {n:02d}",
            "unidade": "UNIDADE", "quantidade": "10"})
        cotacoes.pesquisar_item(ctx, str(c["id"]), str(item["id"]),
                                modo="automatico", fontes=[fonte])
        ids.append(str(item["id"]))
    return ctx, str(c["id"]), ids


def medir_remocao_servico(latencia_s: float, refs_por_item: int, *,
                          teto: bool, cliques: int) -> dict:
    from src import db
    from src.precos import cesta, cotacoes
    from src.precos import repositorio as repo
    from tests import conftest

    cliente = conftest.ClientePrecosFalso()
    db.cliente_do_usuario = lambda: cliente
    contador = Contador()
    _instrumentar_banco(0.0, contador)
    ctx, cid, ids = _cotacao(3, refs_por_item, teto=teto)
    _instrumentar_banco(latencia_s, contador)
    tempos, reqs = [], []
    feitos = 0
    while feitos < cliques:
        progrediu = False
        for iid in ids:
            dentro = cesta.consideradas(repo.listar_referencias(iid))
            if len(dentro) <= 1 or feitos >= cliques:
                continue
            antes = contador.requisicoes
            inicio = time.perf_counter()
            cotacoes.alterar_status_referencia(ctx, cid, iid,
                                               str(dentro[0]["id"]),
                                               incluir=False)
            tempos.append(time.perf_counter() - inicio)
            reqs.append(contador.requisicoes - antes)
            feitos += 1
            progrediu = True
        if not progrediu:
            break
    consideradas = len(cesta.consideradas(repo.listar_referencias(ids[0])))
    return {**_resumo(tempos, reqs), "cesta_inicial": refs_por_item
            if not teto else min(refs_por_item, 15),
            "consideradas_ao_fim_item1": consideradas}


def _apptest(raiz: Path, latencia_s: float, refs_por_item: int, itens: int):
    """A tela de Cotações no AppTest, com a cotação pronta."""
    from streamlit.testing.v1 import AppTest

    from src import db, governanca
    from src.precos import repositorio as repo
    from src.ui import cotacoes_ui, precos_ui
    from tests import conftest

    cliente = conftest.ClientePrecosFalso()
    db.cliente_do_usuario = lambda: cliente
    contador = Contador()
    _instrumentar_banco(0.0, contador)
    ctx, cid, ids = _cotacao(itens, refs_por_item, teto=True)
    ligadas = {repo.FLAG, governanca.FLAG_COTACOES_UNIFICADAS,
               governanca.FLAG_TETO_AUTOMATICO}
    db.flag_ativa = lambda nome: nome in ligadas
    os.environ["GOVDOCS_MODO_ABERTO"] = "1"
    precos_ui._fontes = lambda: [_fonte(refs_por_item)]
    cotacoes_ui._fontes = lambda: [_fonte(refs_por_item)]
    at = AppTest.from_file(str(raiz / "app.py"), default_timeout=120)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["pagina"] = "Cotações"
    at.session_state["usuario"] = {"auth_user_id": "bench", "login": "bench",
                                   "nome": "Bench", "papel": "servidor",
                                   "secretaria_id": None}
    at.session_state[cotacoes_ui.TELA] = cotacoes_ui.ELABORAR
    at.session_state[cotacoes_ui.COTACAO] = cid
    at.run()
    _instrumentar_banco(latencia_s, contador)
    return at, contador, ids


def _clicar_remover(at) -> bool:
    """Depois: um botão. Antes: popover com formulário "Retirar da cesta"."""
    for rotulo in ("Remover da cesta", "Retirar da cesta"):
        botoes = [b for b in at.button if b.label == rotulo]
        if botoes:
            botoes[0].click().run()
            return True
    return False


def medir_tela(raiz: Path, latencia_s: float, cliques: int) -> dict:
    from src.ui import cotacoes_ui

    at, contador, ids = _apptest(raiz, latencia_s, 40, itens=15)
    remocoes, req_rem = [], []
    for _ in range(cliques):
        antes = contador.requisicoes
        inicio = time.perf_counter()
        if not _clicar_remover(at):
            break
        remocoes.append(time.perf_counter() - inicio)
        req_rem.append(contador.requisicoes - antes)
        if at.exception:
            raise RuntimeError(at.exception)
    trocas, req_troca = [], []
    for n in range(cliques):
        alvo = ids[(n + 1) % len(ids)]
        botao = next((b for b in at.button
                      if b.key == f"cot_item_{alvo}"), None)
        if botao is None:
            break
        antes = contador.requisicoes
        inicio = time.perf_counter()
        botao.click().run()
        trocas.append(time.perf_counter() - inicio)
        req_troca.append(contador.requisicoes - antes)
    return {"remover_tela": _resumo(remocoes, req_rem),
            "trocar_item": _resumo(trocas, req_troca)}


def medir_relatorio(itens: int, rodadas: int) -> dict:
    """DOCX do Relatório de Cotação a partir da projeção (sem conversor)."""
    from src.precos import documento_cotacao as dc
    from src.precos import relatorio_view as rv
    from src.precos import repositorio as repo
    from src import db
    from tests import conftest

    cliente = conftest.ClientePrecosFalso()
    db.cliente_do_usuario = lambda: cliente
    _instrumentar_banco(0.0, Contador())
    _, cid, ids = _cotacao(itens, 40, teto=True)
    pesquisa = repo.obter_pesquisa(cid)
    linhas = repo.listar_itens(cid)
    refs = {i: repo.listar_referencias(i) for i in ids}
    tempos = []
    for _ in range(rodadas):
        inicio = time.perf_counter()
        vista = rv.projetar(pesquisa, linhas, refs,
                            emitido_em=datetime.now(timezone.utc))
        dc.relatorio_de_cotacao_docx(vista)
        tempos.append(time.perf_counter() - inicio)
    return _resumo(tempos)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raiz", required=True)
    parser.add_argument("--rotulo", default="")
    parser.add_argument("--latencia-ms", type=int, default=60)
    parser.add_argument("--cliques", type=int, default=20)
    parser.add_argument("--saida", required=True)
    args = parser.parse_args()
    raiz = Path(args.raiz).resolve()
    sys.path.insert(0, str(raiz))
    os.chdir(raiz)
    import logging

    logging.disable(logging.CRITICAL)
    latencia = args.latencia_ms / 1000
    resultado = {
        "rotulo": args.rotulo, "raiz": str(raiz),
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ambiente": {"python": platform.python_version(),
                     "sistema": platform.platform(),
                     "processador": platform.processor()},
        "latencia_simulada_por_requisicao_ms": args.latencia_ms,
        "observacoes": [
            "banco: dublê em memória com latência simulada por requisição",
            "tela: AppTest roda o script inteiro do Streamlit; não inclui o "
            "paint do navegador nem a rede até ele",
            "relatório: só a montagem do DOCX; a conversão em PDF usa o "
            "LibreOffice da produção, ausente nesta máquina"],
        "remover_servico_cesta_15": medir_remocao_servico(
            latencia, 40, teto=True, cliques=args.cliques),
        "remover_servico_cesta_317": medir_remocao_servico(
            latencia, 317, teto=False, cliques=args.cliques),
        **medir_tela(raiz, latencia, args.cliques),
        "relatorio_docx_5_itens": medir_relatorio(5, 5),
        "relatorio_docx_15_itens": medir_relatorio(15, 5),
    }
    Path(args.saida).write_text(json.dumps(resultado, ensure_ascii=False,
                                           indent=2), encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
