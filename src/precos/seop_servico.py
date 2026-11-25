"""
Importação SUPERVISIONADA da SEOP-PA — o que roda fora do clique.

    # 1) baixa os dois PDFs oficiais da competência, lê, confronta e grava
    #    EM CONFERÊNCIA (invisível para a consulta)
    python -m src.precos.seop_servico importar --competencia 2026-10 --banco \
        --planilha https://seop.pa.gov.br/sites/default/files/plainha_padrao_outubro_2026.pdf \
        --analitico https://seop.pa.gov.br/sites/default/files/cpus_outubro_2026.pdf

    # 2) relatório da versão em conferência: páginas, recusas, confronto
    python -m src.precos.seop_servico relatorio --competencia 2026-10 --banco

    # 3) uma PESSOA confere e publica
    python -m src.precos.seop_servico aprovar --competencia 2026-10 --banco \
        --sha <sha256 da planilha> --por "Nome de quem conferiu"

Sem `--banco`, tudo roda em memória sobre arquivos locais (`--pdf-planilha`,
`--pdf-analitico`) — é a medição de bancada. Os endereços dos PDFs vêm da
página oficial (`seop.URL_PAGINA`): a SEOP não segue padrão de nome, então
eles são informados e conferidos (`seop.url_permitida`), nunca montados.

A credencial de SERVIDOR vem do ambiente (`SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`) e nunca é impressa. Nada aqui abre a consulta: isso é
a flag `referencia_custos_seop_pa`.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from . import arquivos, seop


class ArmazemSupabase:
    """O contrato de `seop.Armazem`, nas tabelas da 0047."""

    def __init__(self, cliente) -> None:
        self._c = cliente

    def versao(self, competencia, sha256):
        dados = (self._c.table("precos_seop_versoes").select("*")
                 .eq("competencia", competencia).eq("sha256", sha256)
                 .limit(1).execute()).data
        return dados[0] if dados else None

    def versao_publicada(self, competencia):
        dados = (self._c.table("precos_seop_versoes").select("*")
                 .eq("competencia", competencia).eq("vigente", True)
                 .limit(1).execute()).data
        return dados[0] if dados else None

    def em_conferencia(self, competencia):
        return (self._c.table("precos_seop_versoes").select("*")
                .eq("competencia", competencia).eq("estado", seop.EM_CONFERENCIA)
                .order("criado_em", desc=True).execute()).data or []

    def registrar_versao(self, competencia, sha256, **campos):
        self._c.table("precos_seop_versoes").upsert(
            {**campos, "competencia": competencia, "sha256": sha256},
            on_conflict="competencia,sha256").execute()

    def gravar_registros(self, linhas):
        for inicio in range(0, len(linhas), 500):
            # sem `vigente`: nasce invisível (default false)
            self._c.table("precos_seop_registros").upsert(
                linhas[inicio:inicio + 500], on_conflict="registro_id").execute()

    def publicar(self, competencia, sha256, **campos):
        registros = self._c.table("precos_seop_registros")
        versoes = self._c.table("precos_seop_versoes")
        # quem aprovou vai junto do estado: o check da 0047 recusa
        # `publicado` sem `aprovado_por`
        registros.update({"vigente": True}).eq("competencia", competencia) \
            .eq("arquivo_sha256", sha256).execute()
        registros.update({"vigente": False}).eq("competencia", competencia) \
            .neq("arquivo_sha256", sha256).execute()
        versoes.update({"vigente": False}).eq("competencia", competencia) \
            .neq("sha256", sha256).execute()
        versoes.update({**campos, "estado": seop.PUBLICADO, "vigente": True}) \
            .eq("competencia", competencia).eq("sha256", sha256).execute()

    def buscar(self, termos, *, codigo=None, competencia=None, limite=50):
        return self._c.rpc("precos_seop_buscar", {
            "p_termos": termos, "p_codigo": codigo,
            "p_competencia": competencia, "p_limite": limite}).execute().data or []


def armazem_do_banco() -> ArmazemSupabase:
    url = os.environ.get("SUPABASE_URL")
    chave = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not chave:
        raise SystemExit("defina SUPABASE_URL e SUPABASE_SERVICE_KEY no "
                         "ambiente (a chave não é lida de arquivo)")
    from supabase import create_client

    return ArmazemSupabase(create_client(url, chave))


def _arquivo(url: str | None, local: Path | None, pasta: Path, nome: str
             ) -> Path | None:
    if local is not None:
        return local
    if url is None:
        return None
    if not seop.url_permitida(url):
        raise SystemExit("o PDF da SEOP só é aceito da pasta oficial de "
                         "seop.pa.gov.br")
    return arquivos.baixar(url, pasta / nome, maximo=80_000_000).caminho


def relatorio(versao: dict) -> dict:
    """O que a pessoa precisa ler antes de aprovar — sem as linhas em si."""
    confronto = versao.get("confronto") or {}
    return {
        "competencia": versao.get("competencia"), "sha256": versao.get("sha256"),
        "estado": versao.get("estado"), "url": versao.get("url"),
        "url_analitico": versao.get("url_analitico"),
        "cabecalho": versao.get("cabecalho"), "paginas": versao.get("paginas"),
        "lidas": versao.get("lidas"), "validas": versao.get("validas"),
        "recusas": versao.get("recusas"),
        "recusadas": (versao.get("recusadas") or [])[:50],
        "confronto": {"conferidas": confronto.get("conferidas"),
                      "iguais": confronto.get("iguais"),
                      "motivos": confronto.get("motivos"),
                      "divergentes": (confronto.get("divergentes") or [])[:50]},
        "aprovado_por": versao.get("aprovado_por"),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="SEOP-PA — importação supervisionada")
    sub = p.add_subparsers(dest="acao", required=True)
    for nome in ("importar", "relatorio", "aprovar", "buscar"):
        s = sub.add_parser(nome)
        s.add_argument("--competencia", required=True)
        s.add_argument("--banco", action="store_true")
        if nome in ("importar", "buscar"):
            s.add_argument("--planilha", help="endereço oficial do PDF")
            s.add_argument("--analitico", help="endereço oficial do PDF analítico")
            s.add_argument("--pdf-planilha", type=Path)
            s.add_argument("--pdf-analitico", type=Path)
        if nome == "aprovar":
            s.add_argument("--sha", required=True)
            s.add_argument("--por", required=True)
            s.add_argument("--aceitar-divergencias", action="store_true")
        if nome == "buscar":
            s.add_argument("--termos", nargs="+", required=True)
            s.add_argument("--limite", type=int, default=5)
    a = p.parse_args(argv)
    seop.competencia_valida(a.competencia)
    armazem = armazem_do_banco() if a.banco else seop.ArmazemEmMemoria()

    if a.acao == "relatorio":
        if not a.banco:
            raise SystemExit("`relatorio` lê a versão gravada: use --banco")
        print(json.dumps([relatorio(v) for v in armazem.em_conferencia(
            a.competencia)], ensure_ascii=False, indent=1, default=str))
        return 0
    if a.acao == "aprovar":
        if not a.banco:
            raise SystemExit("`aprovar` publica a versão gravada: use --banco")
        versao = seop.aprovar(armazem, competencia=a.competencia, sha256=a.sha,
                              por=a.por,
                              aceitar_divergencias=a.aceitar_divergencias)
        print(json.dumps(relatorio(versao), ensure_ascii=False, indent=1,
                         default=str))
        return 0

    with tempfile.TemporaryDirectory() as pasta:
        planilha = _arquivo(a.planilha, a.pdf_planilha, Path(pasta), "planilha.pdf")
        analitico = _arquivo(a.analitico, a.pdf_analitico, Path(pasta), "cpus.pdf")
        if planilha is None:
            raise SystemExit("informe --planilha (endereço) ou --pdf-planilha")
        url = a.planilha or (seop.URL_BASE + planilha.name)
        url_analitico = a.analitico or (
            seop.URL_BASE + analitico.name if analitico else None)
        feito = seop.importar(armazem, planilha, competencia=a.competencia,
                              url=url, analitico=analitico,
                              url_analitico=url_analitico)
        if a.acao == "importar":
            print(json.dumps(feito.para_registro(), ensure_ascii=False,
                             indent=1, default=str))
            return 0 if feito.desfecho != seop.RECUSADO else 1
        # buscar: só em memória, e só depois de aprovar (como na produção)
        seop.aprovar(armazem, competencia=a.competencia, sha256=feito.sha256,
                     por="medição de bancada")
        for termo in a.termos:
            achados = seop.consultar(armazem.buscar, termo=termo,
                                     competencia=a.competencia, limite=a.limite)
            print(f"\n== {termo}: {len(achados)}")
            for x in achados:
                print(f"  {x['codigo']} | {x['descricao'][:60]} | {x['unidade']}"
                      f" | R$ {x['valor']} | item {x['item']}, página {x['pagina']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
