#!/usr/bin/env python
"""
Mede um lote de cotação automática com FONTES REAIS — a régua do pacote
"cotação pronta para revisão" (26/11/2026).

Roda o caminho de produção (`cotacoes.pesquisar_em_lote`, item a item, com
a política do teto 5 e da barreira do CV ligadas) sobre o banco falso das
provas, contra as fontes públicas (Compras.gov e a busca nacional do PNCP).
Cada resposta das fontes é gravada num RECORTE em disco (`--recorte`): a
primeira execução consulta a rede; as seguintes repetem as MESMAS respostas
— é assim que duas versões do código se comparam sob as mesmas condições.
Consulta que o recorte ainda não tem (a versão nova pediu um termo novo)
vai à rede e entra no recorte; o JSON diz quantas foram.

Mede, por item e no lote: desfecho, preço proposto, quantidade na cesta,
CV exato, tempo, e as chamadas por fonte; a medida principal é "itens que
chegaram prontos sem edição humana ÷ itens importados".

Não grava em banco real, não usa credencial, não chama IA.

Uso:
    python scripts/medir_cotacao_lote.py --lote tests/fixtures/lote_cotacao_a.json \\
        --recorte "$TEMP/recorte_a.pkl" --saida docs/pesquisa-precos-2026-11/medicao/a-depois.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


class Recorte:
    """Respostas das fontes por consulta, persistidas entre execuções."""

    def __init__(self, caminho: Path):
        self.caminho = caminho
        self.dados: dict = {}
        if caminho.exists():
            self.dados = pickle.loads(caminho.read_bytes())
        self.da_rede = 0
        self.do_recorte = 0

    def salvar(self) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho.write_bytes(pickle.dumps(self.dados))


def _chave(fonte_id: str, consulta) -> str:
    campos = {k: str(v) for k, v in sorted(vars(consulta).items())}
    return hashlib.sha256(f"{fonte_id}|{json.dumps(campos, sort_keys=True)}".encode()).hexdigest()


class FonteGravada:
    """Envolve uma fonte real: responde do recorte ou consulta e grava."""

    def __init__(self, real, recorte: Recorte, offline: bool):
        self.real, self.recorte, self.offline = real, recorte, offline
        self.fonte = real.fonte
        self.chamadas = 0

    def pesquisar(self, consulta):
        chave = _chave(self.fonte.id, consulta)
        if chave in self.recorte.dados:
            self.recorte.do_recorte += 1
            return self.recorte.dados[chave]
        if self.offline:
            from src.precos.fontes import ResultadoBusca
            return ResultadoBusca(fonte=self.fonte, referencias=[],
                                  erro="fora do recorte (modo offline)")
        self.chamadas += 1
        self.recorte.da_rede += 1
        resultado = self.real.pesquisar(consulta)
        if not getattr(resultado, "erro", ""):
            self.recorte.dados[chave] = resultado      # falha não vira recorte
        return resultado


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lote", required=True)
    ap.add_argument("--recorte", required=True)
    ap.add_argument("--saida", default="")
    ap.add_argument("--offline", action="store_true",
                    help="só o recorte: consulta ausente vira falha da fonte")
    args = ap.parse_args()

    import pytest  # noqa: F401 — o banco falso das provas vive em tests/

    from src import db
    from src.precos import cotacoes, estatistica
    from src.precos import repositorio as repo
    from src.precos.compras_gov import ComprasGovAdapter
    from src.precos.pncp_nacional import PNCPNacional
    from tests.conftest import ClientePrecosFalso

    lote = json.loads(Path(args.lote).read_text(encoding="utf-8"))
    cliente = ClientePrecosFalso()
    for t in ("pesquisas_preco", "pesquisa_preco_itens", "pesquisa_preco_referencias",
              "pesquisa_preco_eventos", "pesquisa_preco_emissoes"):
        cliente.tabelas.setdefault(t, [])
    db.cliente_do_usuario = lambda: cliente
    db.flag_ativa = lambda nome: nome in {"cotacao_automatica_teto",
                                          "precos_saneamento_pre_cesta"}
    cotacoes.hoje_da_execucao = lambda: datetime.fromisoformat(lote["data_corte"]).date()

    recorte = Recorte(Path(args.recorte))
    fontes = [FonteGravada(ComprasGovAdapter(), recorte, args.offline),
              FonteGravada(PNCPNacional(), recorte, args.offline)]
    ctx = cotacoes.Contexto(auth_user_id="00000000-0000-4000-8000-000000000001",
                            secretaria_id=None)
    c = cotacoes.criar_cotacao(ctx, {"nome": lote["nome"], "data_base": lote["data_corte"],
                                     "perfil_normativo": lote.get("perfil", "lei_14133"),
                                     "filtros": lote.get("filtros", {})})
    cid = str(c["id"])
    for item in lote["itens"]:
        cotacoes.salvar_item(ctx, cid, {k: item[k] for k in ("descricao", "unidade", "quantidade")})
    ids = cotacoes.recorte_do_lote(cid, modo="automatico", fontes=fontes)

    inicio = time.monotonic()
    primeira = None
    linhas = []
    tentados: set[str] = set()
    while True:
        t0 = time.monotonic()
        resultados, restantes = cotacoes.pesquisar_em_lote(
            ctx, cid, modo="automatico", tamanho=1, item_ids=ids,
            ja_tentados=tentados, fontes=fontes)
        for r in resultados:
            item = repo.obter_item(r.item_id)
            refs = repo.listar_referencias(r.item_id)
            cesta = [l for l in refs if l["status"] == "selected"]
            pronto = cotacoes.proposta_apta(item) and r.desfecho == "pronto_para_revisao"
            if pronto and primeira is None:
                primeira = round(time.monotonic() - inicio, 1)
            barreira = r.barreira_cv or {}
            linhas.append({
                "numero": item["numero"], "descricao": item["descricao"],
                "unidade": item["unidade"], "desfecho": r.desfecho,
                "pronto": pronto, "preco": item.get("preco_estimado"),
                "na_cesta": len(cesta), "elegiveis": r.elegiveis, "brutas": r.brutas,
                "cv": barreira.get("cv_exibicao"), "segundos": round(time.monotonic() - t0, 1),
                "cesta": [{"fonte": l["fonte_id"], "id": l["id_externo"],
                           "descricao": l["descricao_original"][:120],
                           "unidade": l["unidade_original"],
                           "valor": l["valor_unitario_normalizado"],
                           "link": l.get("referencia_externa") or ""} for l in cesta],
                "fora": [{"descricao": l["descricao_original"][:90], "status": l["status"],
                          "valor": l["valor_unitario_normalizado"],
                          "motivo": (l.get("motivos") or [""])[0][:160]}
                         for l in refs if l["status"] != "selected"][:12],
            })
        if restantes == 0 or not resultados:
            break
    recorte.salvar()
    prontos = sum(1 for l in linhas if l["pronto"])
    desfechos: dict[str, int] = {}
    for l in linhas:
        desfechos[l["desfecho"]] = desfechos.get(l["desfecho"], 0) + 1
    saida = {
        "lote": lote["nome"], "data_corte": lote["data_corte"],
        "perfil": lote.get("perfil", "lei_14133"),
        "versoes": {"barreira_cv": estatistica.VERSAO_BARREIRA_CV,
                    "equivalencia": __import__("src.precos.equivalencia", fromlist=["VERSAO"]).VERSAO},
        "medido_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "itens": len(lote["itens"]), "processados": len(linhas),
        "prontos": prontos, "taxa": round(prontos / max(1, len(lote["itens"])), 3),
        "desfechos": desfechos, "primeira_proposta_s": primeira,
        "duracao_s": round(time.monotonic() - inicio, 1),
        "chamadas_rede": {f.fonte.id: f.chamadas for f in fontes},
        "recorte": {"da_rede": recorte.da_rede, "do_recorte": recorte.do_recorte},
        "por_item": linhas,
    }
    texto = json.dumps(saida, ensure_ascii=False, indent=1, default=str)
    if args.saida:
        Path(args.saida).parent.mkdir(parents=True, exist_ok=True)
        Path(args.saida).write_text(texto, encoding="utf-8")
    print(json.dumps({k: v for k, v in saida.items() if k != "por_item"},
                     ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
