"""
Indexação AGENDADA do PNCP — o que o serviço `indexador-pncp` roda.

    python -m src.precos.pncp_indice_servico ciclo --banco --ufs PA

Mora em `src/` (e não em `scripts/`) porque a imagem de produção não carrega
ferramenta de desenvolvimento (`tests/test_implantacao_vps.py`): o serviço
usa a imagem do worker, e `scripts/indexar_pncp.py` é só a linha de comando
de bancada que reaproveita este módulo.

A credencial de SERVIDOR vem do ambiente do serviço (`SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`, em `/etc/govdocs/indexador.env`) e nunca é impressa.
A API e o worker não a têm.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone

from . import pncp_indice as indice


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
        alvo = [linha["id_externo"] for linha in linhas
                if linha["id_externo"] not in manter
                and (itens is None or int(linha.get("numero_item") or 0) in itens)]
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


def armazem_do_banco() -> ArmazemSupabase:
    url = os.environ.get("SUPABASE_URL")
    chave = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not chave:
        raise SystemExit("defina SUPABASE_URL e SUPABASE_SERVICE_KEY no "
                         "ambiente (a chave não é lida de arquivo)")
    from supabase import create_client

    return ArmazemSupabase(create_client(url, chave))


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


def argumentos_do_ciclo(s: argparse.ArgumentParser) -> None:
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


def rodar_ciclo(a, armazem) -> int:
    return ciclo(armazem, a.ufs, intervalo_s=a.intervalo, uma_vez=a.uma_vez,
                 dias=a.dias, ate=None, modalidades=a.modalidades,
                 max_chamadas=a.max_chamadas,
                 max_contratacoes=a.max_contratacoes, pausa=a.pausa)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Índice do PNCP — serviço agendado")
    sub = p.add_subparsers(dest="acao", required=True)
    s = sub.add_parser("ciclo")
    s.add_argument("--banco", action="store_true", required=True)
    argumentos_do_ciclo(s)
    a = p.parse_args(argv)
    return rodar_ciclo(a, armazem_do_banco())


if __name__ == "__main__":
    raise SystemExit(main())
