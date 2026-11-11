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
from datetime import datetime, timedelta, timezone

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

    # -- busca por termo (0043) ---------------------------------------------
    def registrar_termos(self, nucleos):
        if not nucleos:
            return 0
        # sem sobrescrever o estado de quem já existe
        resposta = self._c.table("precos_pncp_termos").upsert(
            [{"nucleo": n} for n in nucleos], on_conflict="nucleo",
            ignore_duplicates=True).execute()
        return len(resposta.data or [])

    def termos_para_buscar(self, limite):
        # O termo novo nasce com `proxima_busca = now()` — com fração de
        # segundo — e é procurado logo em seguida. Comparar com o "agora"
        # TRUNCADO no segundo (`_agora`) o deixava de fora na própria rodada:
        # a 1ª rodada em produção (11/11/2026) registrou 229 termos e não
        # buscou nenhum. A folga de 1 minuto cobre também relógio de servidor.
        limite_vez = (datetime.now(timezone.utc) + timedelta(minutes=1)
                      ).isoformat(timespec="seconds")
        return (self._c.table("precos_pncp_termos").select("*")
                .lte("proxima_busca", limite_vez)
                .order("buscado_em", desc=False, nullsfirst=True)
                .order("proxima_busca").limit(limite).execute()).data or []

    def salvar_termo(self, nucleo, **campos):
        (self._c.table("precos_pncp_termos")
         .update({**campos, "atualizado_em": self._agora()})
         .eq("nucleo", nucleo).execute())

    def descricoes_cotadas(self, dias: int, limite: int = 2000) -> list[str]:
        """Descrições dos itens cotados nos últimos `dias` — só o texto,
        que vira núcleo de busca e nada mais (nenhum dado do processo, do
        órgão ou de quem cotou sai daqui)."""
        desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat(
            timespec="seconds")
        linhas = (self._c.table("pesquisa_preco_itens").select("descricao")
                  .gte("atualizado_em", desde).is_("removido_em", "null")
                  .order("atualizado_em", desc=True).limit(limite)
                  .execute()).data or []
        return [str(l.get("descricao") or "") for l in linhas]

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
           fracao_descoberta: float = 0.3, recomecar: bool = False,
           **rede) -> dict:
    """
    Uma rodada AGENDADA de uma UF: descoberta e coleta com orçamentos
    SEPARADOS. Com um orçamento só, uma UF grande gastava tudo na
    descoberta e a fila de contratações nunca andava. As MESMAS modalidades
    valem para as duas: a coleta não lê o que a descoberta não buscaria.
    """
    teto_descoberta = max(1, int(max_chamadas * fracao_descoberta))
    descoberta = indice.Coletor(armazem, max_chamadas=teto_descoberta,
                                pausa_s=pausa, modalidades=modalidades,
                                incluir_compras_gov=incluir_compras_gov, **rede)
    descoberta.descobrir(uf, ate=ate, dias=dias, recomecar=recomecar)
    coleta = indice.Coletor(
        armazem, max_chamadas=max(1, max_chamadas - descoberta.rodada.chamadas),
        pausa_s=pausa, modalidades=modalidades,
        incluir_compras_gov=incluir_compras_gov, **rede)
    coleta.coletar(max_contratacoes)
    return {"uf": uf, "descoberta": descoberta.rodada.para_registro(),
            "coleta": coleta.rodada.para_registro()}


NUCLEO_MIN, NUCLEO_MAX = 3, 120          # o CHECK da 0043


def nucleos_das_descricoes(descricoes) -> list[str]:
    """Núcleos distintos, na ordem em que vieram (o mais recente primeiro).
    Fora do tamanho que a 0043 aceita, o núcleo não entra: um só ("a4")
    derrubaria o registro do lote inteiro (revisão de 11/11/2026)."""
    from .pncp_nacional import nucleo

    return list(dict.fromkeys(
        n for n in (nucleo(d) for d in descricoes)
        if NUCLEO_MIN <= len(n) <= NUCLEO_MAX))


def rodada_por_termos(armazem, *, max_chamadas: int, max_termos: int,
                      pausa: float, modalidades=indice.MODALIDADES_PADRAO,
                      dias_itens: int = 30, hoje=None, **rede) -> dict:
    """
    Busca NACIONAL pelos itens que os usuários cotam (0043). Registra os
    núcleos novos, e busca os que estão na vez — nunca buscados primeiro.
    Termo buscado volta em `TERMO_REBUSCA_DIAS`; o que falhou, em
    `TERMO_FALHA_HORAS`; o que o orçamento interrompeu fica como estava e
    a próxima rodada o refaz.
    """
    from .fontes import ErroFonte

    agora = datetime.now(timezone.utc)
    novos = armazem.registrar_termos(nucleos_das_descricoes(
        armazem.descricoes_cotadas(dias_itens)))
    coletor = indice.Coletor(armazem, max_chamadas=max_chamadas, pausa_s=pausa,
                             modalidades=modalidades, **rede)
    termos = {"novos": novos, "buscados": 0, "falhas": 0}
    for termo in armazem.termos_para_buscar(max_termos):
        nucleo = termo["nucleo"]
        try:
            relato = coletor.indexar_termo(nucleo, hoje=hoje)
        except indice.OrcamentoEsgotado:
            coletor.rodada.interrompida = True
            break
        except ErroFonte as erro:
            termos["falhas"] += 1
            armazem.salvar_termo(
                nucleo, falhas=int(termo.get("falhas") or 0) + 1,
                erro=str(erro)[:200], proxima_busca=(agora + timedelta(
                    hours=indice.TERMO_FALHA_HORAS)).isoformat(timespec="seconds"))
            continue
        termos["buscados"] += 1
        armazem.salvar_termo(
            nucleo, buscado_em=agora.isoformat(timespec="seconds"),
            proxima_busca=(agora + timedelta(days=indice.TERMO_REBUSCA_DIAS)
                           ).isoformat(timespec="seconds"),
            contratacoes=relato["achadas"], resultados=relato["validos"],
            falhas=0, erro="")
    return {"termos": termos, "coleta": coletor.rodada.para_registro()}


def ciclo(armazem, ufs: list[str], *, intervalo_s: int, uma_vez: bool,
          dormir=None, recomecar: bool = False, termos: dict | None = None,
          **opcoes) -> int:
    """Indexação fora da busca: uma rodada por UF, depois espera. Retoma
    sozinha (cursor e ponto de leitura moram no índice). `recomecar` vale
    só para a PRIMEIRA rodada de cada UF: as seguintes continuam do cursor
    que ela deixou, inclusive quando o orçamento a interrompeu."""
    dormir = dormir or time.sleep
    while True:
        for uf in ufs:
            try:
                relato = rodada(armazem, uf.upper(), recomecar=recomecar,
                                **opcoes)
            except Exception as erro:  # noqa: BLE001 — próxima UF segue
                relato = {"uf": uf, "erro": type(erro).__name__}
            if isinstance(armazem, indice.ArmazemEmMemoria):
                armazem.persistir()
            relato["em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            print(json.dumps(relato, ensure_ascii=False), flush=True)
        if termos is not None:
            try:
                relato = {"busca_por_termo": rodada_por_termos(armazem, **termos)}
            except Exception as erro:  # noqa: BLE001 — a regional já rodou
                relato = {"busca_por_termo": {"erro": type(erro).__name__}}
            if isinstance(armazem, indice.ArmazemEmMemoria):
                armazem.persistir()
            relato["em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            print(json.dumps(relato, ensure_ascii=False), flush=True)
        if uma_vez:
            return 0
        recomecar = False
        dormir(intervalo_s)


def argumentos_do_ciclo(s: argparse.ArgumentParser) -> None:
    s.add_argument("--ufs", nargs="+",
                   default=os.environ.get("INDEXADOR_UFS", "PA").split())
    # janela da 1ª descoberta (e do --recomecar); as seguintes recuam
    # `indice.REVISITA_DIAS` sobre a anterior
    s.add_argument("--dias", type=int, default=indice.REVISITA_DIAS)
    s.add_argument("--recomecar", action="store_true",
                   help="ignora o cursor e refaz a janela de --dias")
    s.add_argument("--modalidades", type=int, nargs="*",
                   default=list(indice.MODALIDADES_PADRAO))
    s.add_argument("--max-chamadas", type=int, default=int(
        os.environ.get("INDEXADOR_MAX_CHAMADAS", "900")))
    s.add_argument("--max-contratacoes", type=int, default=150)
    s.add_argument("--pausa", type=float, default=0.3)
    s.add_argument("--intervalo", type=int, default=int(
        os.environ.get("INDEXADOR_INTERVALO_S", "21600")))
    s.add_argument("--uma-vez", action="store_true")
    # busca NACIONAL pelos itens cotados (0043): orçamento próprio, depois
    # das UFs; `--sem-termos` desliga. Medido em 11/11/2026: ~33 chamadas e
    # ~45 s por termo, ~10 resultados novos. 2.000 chamadas ≈ 60 termos em
    # ~45 min; a cada 6 h, ~240 termos/dia (565 descrições cotadas em 30 d).
    s.add_argument("--sem-termos", action="store_true")
    s.add_argument("--max-chamadas-termos", type=int, default=int(
        os.environ.get("INDEXADOR_MAX_CHAMADAS_TERMOS", "2000")))
    s.add_argument("--max-termos", type=int, default=80)


def rodar_ciclo(a, armazem) -> int:
    termos = None if a.sem_termos else {
        "max_chamadas": a.max_chamadas_termos, "max_termos": a.max_termos,
        "pausa": max(a.pausa, 0.35), "modalidades": a.modalidades}
    return ciclo(armazem, a.ufs, intervalo_s=a.intervalo, uma_vez=a.uma_vez,
                 dias=a.dias, ate=None, modalidades=a.modalidades,
                 max_chamadas=a.max_chamadas,
                 max_contratacoes=a.max_contratacoes, pausa=a.pausa,
                 recomecar=a.recomecar, termos=termos)


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
