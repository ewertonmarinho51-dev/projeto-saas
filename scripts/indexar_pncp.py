"""
Job de bancada do índice do PNCP (piloto: Pará) — limitado e retomável.

    # medição local, sem banco: o índice fica num arquivo JSON
    python scripts/indexar_pncp.py rodar --uf PA --arquivo D:/indice_pa.json \
        --dias 30 --max-chamadas 300 --max-contratacoes 80
    python scripts/indexar_pncp.py buscar --arquivo D:/indice_pa.json \
        --termos "cimento portland" "papel sulfite a4"
    python scripts/indexar_pncp.py resumo --arquivo D:/indice_pa.json

    # no banco (0042 aplicada), com a credencial de SERVIDOR no ambiente
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \
        python scripts/indexar_pncp.py rodar --uf PA --banco --max-chamadas 500

    # agendado (serviço `indexador-pncp` do compose, perfil `indexador`):
    # uma rodada por UF a cada INDEXADOR_INTERVALO_S, orçamento separado
    # para descoberta e coleta
    python scripts/indexar_pncp.py ciclo --banco --ufs PA

`rodar` faz a descoberta (contratações atualizadas na janela) e depois a
coleta (itens e resultados homologados das pendentes), parando quando o
orçamento de chamadas acaba. Rodar de novo CONTINUA: a página da descoberta
e o último item lido de cada contratação ficam no índice.

Nada aqui liga a fonte: isso é a flag `price_source_pncp_indice`. A
credencial vem do ambiente e nunca é impressa.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src.precos import pncp_indice as indice  # noqa: E402
from src.precos.fontes import Consulta  # noqa: E402


class ArmazemSupabase:
    """O mesmo contrato de `pncp_indice.Armazem`, nas tabelas da 0042."""

    def __init__(self, cliente) -> None:
        self._c = cliente

    @staticmethod
    def _agora() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def cursor(self, uf, modalidade):
        dados = (self._c.table("precos_pncp_cursores").select("*")
                 .eq("uf", uf).eq("modalidade_id", modalidade).limit(1)
                 .execute()).data
        return dados[0] if dados else None

    def salvar_cursor(self, uf, modalidade, **campos):
        atual = self.cursor(uf, modalidade) or {}
        self._c.table("precos_pncp_cursores").upsert(
            {**atual, **campos, "uf": uf, "modalidade_id": modalidade,
             "atualizado_em": self._agora()},
            on_conflict="uf,modalidade_id").execute()

    def contratacao(self, numero_controle):
        dados = (self._c.table("precos_pncp_contratacoes").select("*")
                 .eq("numero_controle", numero_controle).limit(1)
                 .execute()).data
        return dados[0] if dados else None

    def salvar_contratacao(self, numero_controle, **campos):
        if self.contratacao(numero_controle) is None:
            self._c.table("precos_pncp_contratacoes").insert(
                {"numero_controle": numero_controle, **campos}).execute()
        else:
            (self._c.table("precos_pncp_contratacoes")
             .update({**campos, "atualizado_em": self._agora()})
             .eq("numero_controle", numero_controle).execute())

    def pendentes(self, limite):
        return (self._c.table("precos_pncp_contratacoes").select("*")
                .eq("estado", indice.PENDENTE)
                .order("tem_homologacao", desc=True)
                .order("atualizacao_global", desc=True)
                .limit(limite).execute()).data or []

    def gravar_resultados(self, linhas):
        agora = self._agora()
        # confirmado agora = vigente de novo, mesmo que uma revisita
        # anterior o tenha invalidado (o upsert só toca as colunas enviadas)
        self._c.table("precos_pncp_resultados").upsert(
            [{**linha, "coletado_em": agora, "vigente": True,
              "invalidado_em": None, "invalidado_motivo": ""}
             for linha in linhas],
            on_conflict="id_externo").execute()

    def invalidar(self, numero_controle, *, manter, itens, motivo):
        linhas = (self._c.table("precos_pncp_resultados")
                  .select("id_externo,numero_item")
                  .eq("numero_controle", numero_controle).eq("vigente", True)
                  .execute()).data or []
        alvo = [l["id_externo"] for l in linhas
                if l["id_externo"] not in manter
                and (itens is None or int(l.get("numero_item") or 0) in itens)]
        if alvo:
            (self._c.table("precos_pncp_resultados")
             .update({"vigente": False, "invalidado_em": self._agora(),
                      "invalidado_motivo": motivo})
             .in_("id_externo", alvo).execute())
        return len(alvo)

    def buscar(self, termos, *, uf=None, desde=None, ate=None, limite=50):
        return self._c.rpc("precos_pncp_buscar", {
            "p_termos": termos, "p_uf": uf,
            "p_desde": desde.isoformat() if desde else None,
            "p_ate": ate.isoformat() if ate else None,
            "p_limite": limite}).execute().data or []


def _armazem(args):
    if args.banco:
        url = os.environ.get("SUPABASE_URL")
        chave = os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not chave:
            raise SystemExit("defina SUPABASE_URL e SUPABASE_SERVICE_KEY no "
                             "ambiente (a chave não é lida de arquivo)")
        from supabase import create_client

        return ArmazemSupabase(create_client(url, chave))
    if not args.arquivo:
        raise SystemExit("informe --arquivo (índice local) ou --banco")
    return indice.ArmazemEmMemoria(args.arquivo)


def resumo(armazem: indice.ArmazemEmMemoria) -> dict:
    """Contagens do índice local: o que entrou, de onde, e o que falta."""
    estados = Counter(c.get("estado") for c in armazem.contratacoes.values())
    por_plataforma = Counter(r.get("plataforma") or "(sem nome)"
                             for r in armazem.resultados.values())
    de_fora = [r for r in armazem.resultados.values()
               if r.get("plataforma") != indice.PLATAFORMA_COMPRAS_GOV]
    return {
        "contratacoes_por_estado": dict(estados),
        "resultados_validos": len(armazem.resultados),
        "de_origem_distinta_do_compras_gov": len(de_fora),
        "com_id_de_compra_do_compras_gov": sum(
            1 for r in armazem.resultados.values() if r.get("id_compra_origem")),
        "municipios": len({(r.get("municipio"), r.get("uf"))
                           for r in armazem.resultados.values()}),
        "orgaos": len({r.get("orgao_cnpj") for r in armazem.resultados.values()}),
        "por_plataforma": dict(por_plataforma.most_common()),
        "cursores": armazem.cursores,
    }


def rodada(armazem, uf: str, *, dias: int, ate, modalidades, max_chamadas: int,
           max_contratacoes: int, pausa: float, incluir_compras_gov: bool = False,
           fracao_descoberta: float = 0.3, **rede) -> dict:
    """
    Uma rodada AGENDADA de uma UF: descoberta e coleta com orçamentos
    SEPARADOS. Com um orçamento só, uma UF grande gastava tudo na
    descoberta e a fila de contratações nunca andava.
    """
    teto_descoberta = max(1, int(max_chamadas * fracao_descoberta))
    descoberta = indice.Coletor(armazem, max_chamadas=teto_descoberta,
                                pausa_s=pausa,
                                incluir_compras_gov=incluir_compras_gov, **rede)
    descoberta.descobrir(uf, modalidades=modalidades, ate=ate, dias=dias)
    coleta = indice.Coletor(
        armazem, max_chamadas=max(1, max_chamadas - descoberta.rodada.chamadas),
        pausa_s=pausa, incluir_compras_gov=incluir_compras_gov, **rede)
    coleta.coletar(max_contratacoes)
    return {"uf": uf, "descoberta": descoberta.rodada.para_registro(),
            "coleta": coleta.rodada.para_registro()}


def ciclo(armazem, ufs: list[str], *, intervalo_s: int, uma_vez: bool,
          dormir=None, **opcoes) -> int:
    """Indexação fora da busca: uma rodada por UF, depois espera. Retoma
    sozinha (cursor e ponto de leitura moram no índice)."""
    import time

    dormir = dormir or time.sleep
    while True:
        for uf in ufs:
            try:
                relato = rodada(armazem, uf.upper(), **opcoes)
            except Exception as erro:  # noqa: BLE001 — próxima UF segue
                relato = {"uf": uf, "erro": type(erro).__name__}
            if isinstance(armazem, indice.ArmazemEmMemoria):
                armazem.persistir()
            relato["em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            print(json.dumps(relato, ensure_ascii=False), flush=True)
        if uma_vez:
            return 0
        dormir(intervalo_s)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Índice do PNCP — job de bancada")
    sub = p.add_subparsers(dest="acao", required=True)
    for nome in ("rodar", "buscar", "resumo", "ciclo"):
        s = sub.add_parser(nome)
        s.add_argument("--arquivo", type=Path)
        s.add_argument("--banco", action="store_true")
        if nome == "ciclo":
            s.add_argument("--ufs", nargs="+",
                           default=os.environ.get("INDEXADOR_UFS", "PA").split())
            s.add_argument("--dias", type=int, default=30)
            s.add_argument("--modalidades", type=int, nargs="*",
                           default=list(indice.MODALIDADES_PADRAO))
            s.add_argument("--max-chamadas", type=int, default=int(
                os.environ.get("INDEXADOR_MAX_CHAMADAS", "900")))
            s.add_argument("--max-contratacoes", type=int, default=150)
            s.add_argument("--pausa", type=float, default=0.3)
            s.add_argument("--intervalo", type=int, default=int(
                os.environ.get("INDEXADOR_INTERVALO_S", "21600")))
            s.add_argument("--uma-vez", action="store_true")
        if nome == "rodar":
            s.add_argument("--uf", default="PA")
            s.add_argument("--dias", type=int, default=30)
            s.add_argument("--ate", type=date.fromisoformat, default=None)
            s.add_argument("--modalidades", type=int, nargs="*",
                           default=list(indice.MODALIDADES_PADRAO))
            s.add_argument("--max-chamadas", type=int, default=200)
            s.add_argument("--max-contratacoes", type=int, default=50)
            s.add_argument("--pausa", type=float, default=0.2)
            s.add_argument("--incluir-compras-gov", action="store_true")
        if nome == "buscar":
            s.add_argument("--termos", nargs="+", required=True)
            s.add_argument("--uf", default=None)
            s.add_argument("--limite", type=int, default=10)
    a = p.parse_args(argv)
    armazem = _armazem(a)

    if a.acao == "ciclo":
        return ciclo(armazem, a.ufs, intervalo_s=a.intervalo, uma_vez=a.uma_vez,
                     dias=a.dias, ate=None, modalidades=a.modalidades,
                     max_chamadas=a.max_chamadas,
                     max_contratacoes=a.max_contratacoes, pausa=a.pausa)

    if a.acao == "rodar":
        coletor = indice.Coletor(armazem, max_chamadas=a.max_chamadas,
                                 pausa_s=a.pausa,
                                 incluir_compras_gov=a.incluir_compras_gov)
        try:
            coletor.descobrir(a.uf, modalidades=a.modalidades, ate=a.ate,
                              dias=a.dias)
            if not coletor.rodada.interrompida:
                coletor.coletar(a.max_contratacoes)
        finally:
            if isinstance(armazem, indice.ArmazemEmMemoria):
                armazem.persistir()
        print(json.dumps(coletor.rodada.para_registro(), ensure_ascii=False,
                         indent=1))
        return 0

    if a.acao == "buscar":
        fonte = indice.PNCPIndice(armazem.buscar)
        for termo in a.termos:
            achado = fonte.pesquisar(Consulta(descricao=termo, uf=a.uf,
                                              limite=a.limite))
            print(f"\n== {termo}: {len(achado.referencias)} referência(s)"
                  f" | {achado.desfecho.value}")
            for r in achado.referencias[:a.limite]:
                print(f"  R$ {r.valor_unitario_original} / {r.unidade_original}"
                      f" | {r.descricao_original[:70]} | {r.orgao} ({r.uf})"
                      f" | {r.data_resultado} | {r.bruto['indice']['plataforma']}"
                      f" | {r.referencia_externa}")
        return 0

    if not isinstance(armazem, indice.ArmazemEmMemoria):
        raise SystemExit("`resumo` lê o índice local; no banco, consulte as "
                         "tabelas precos_pncp_*")
    print(json.dumps(resumo(armazem), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
