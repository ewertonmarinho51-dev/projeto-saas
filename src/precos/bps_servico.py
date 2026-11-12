"""
Importação do BPS — o que roda FORA do clique, na bancada ou no servidor.

    # baixa o arquivo oficial do ano, valida, importa e publica a versão
    python -m src.precos.bps_servico importar --banco
    python -m src.precos.bps_servico importar --zip D:/2026_csv.zip   # sem banco

    # confronta uma amostra do arquivo com a API oficial do Ministério
    python -m src.precos.bps_servico conferir --zip D:/2026_csv.zip --amostra 60

    # pesquisa no que foi importado em memória (medição de bancada)
    python -m src.precos.bps_servico buscar --zip D:/2026_csv.zip \
        --termos "dipirona sodica 500 mg comprimido"

Mora em `src/` pela mesma razão do indexador do PNCP: a imagem de produção
não carrega `scripts/`. A credencial de SERVIDOR vem do ambiente
(`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`) e nunca é impressa. Nada aqui liga
a fonte: isso é `fontes_externas.habilitada("bps")`.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import arquivos, bps, etl_bps
from .fontes import Consulta
from .fontes_externas import REGISTRO

URL_OFICIAL = REGISTRO["bps"].downloads[0]


class ArmazemSupabase:
    """O contrato de `bps.Armazem`, nas tabelas da 0044."""

    def __init__(self, cliente) -> None:
        self._c = cliente

    def versao(self, ano, sha256):
        dados = (self._c.table("precos_bps_versoes").select("*")
                 .eq("ano", ano).eq("sha256", sha256).limit(1).execute()).data
        return dados[0] if dados else None

    def versao_publicada(self, ano):
        dados = (self._c.table("precos_bps_versoes").select("*")
                 .eq("ano", ano).eq("vigente", True).limit(1).execute()).data
        return dados[0] if dados else None

    def registrar_versao(self, ano, sha256, **campos):
        self._c.table("precos_bps_versoes").upsert(
            {**campos, "ano": ano, "sha256": sha256},
            on_conflict="ano,sha256").execute()

    def gravar_registros(self, linhas):
        # sem a coluna `vigente`: linha nova nasce invisível (default false)
        # e a que já existia continua como estava até a publicação
        self._c.table("precos_bps_registros").upsert(
            linhas, on_conflict="registro_id").execute()

    def publicar(self, ano, sha256, **campos):
        registros = self._c.table("precos_bps_registros")
        versoes = self._c.table("precos_bps_versoes")
        # 1) o que é desta versão aparece; 2) o que ficou só na anterior some
        registros.update({"vigente": True}).eq("ano", ano).eq(
            "arquivo_sha256", sha256).execute()
        registros.update({"vigente": False}).eq("ano", ano).neq(
            "arquivo_sha256", sha256).execute()
        # uma vigente por ano (índice único parcial): primeiro tira a antiga
        versoes.update({"vigente": False}).eq("ano", ano).neq(
            "sha256", sha256).execute()
        versoes.update({**campos, "estado": bps.PUBLICADO, "vigente": True}
                       ).eq("ano", ano).eq("sha256", sha256).execute()

    def buscar(self, termos, *, catmat=None, uf=None, desde=None, ate=None,
               limite=50):
        return self._c.rpc("precos_bps_buscar", {
            "p_termos": termos, "p_catmat": catmat, "p_uf": uf,
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


def _arquivo(args, pasta: Path) -> tuple[Path, str | None]:
    """O ZIP informado, ou o oficial baixado agora (com as defesas de
    `arquivos.baixar`: só HTTPS, só o endereço registrado, teto de bytes)."""
    if args.zip:
        return args.zip, None
    snap = arquivos.baixar(URL_OFICIAL, pasta / "bps.zip")
    return snap.caminho, snap.last_modified


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="BPS — importação e conferência")
    sub = p.add_subparsers(dest="acao", required=True)
    for nome in ("importar", "conferir", "buscar"):
        s = sub.add_parser(nome)
        s.add_argument("--zip", type=Path)
        if nome == "importar":
            s.add_argument("--banco", action="store_true")
        if nome == "conferir":
            s.add_argument("--amostra", type=int, default=60)
        if nome == "buscar":
            s.add_argument("--termos", nargs="+", required=True)
            s.add_argument("--catmat", default=None)
            s.add_argument("--limite", type=int, default=10)
    a = p.parse_args(argv)

    with tempfile.TemporaryDirectory() as pasta:
        caminho, modificado = _arquivo(a, Path(pasta))
        if a.acao == "conferir":
            sha = arquivos.sha256_do_arquivo(caminho)
            evidencias = list(etl_bps.ler(caminho, url_snapshot=URL_OFICIAL,
                                          sha256=sha))
            confronto = bps.confrontar(bps.amostra(evidencias, a.amostra))
            print(json.dumps({"sha256": sha, "linhas": len(evidencias),
                              "em": datetime.now(timezone.utc).isoformat(
                                  timespec="seconds"),
                              **confronto.para_registro()},
                             ensure_ascii=False, indent=1))
            return 0 if confronto.achadas == confronto.conferidas \
                and not confronto.falhas else 1

        armazem = armazem_do_banco() if getattr(a, "banco", False) \
            else bps.ArmazemEmMemoria()
        feito = bps.importar(armazem, caminho, url=URL_OFICIAL,
                             last_modified=modificado)
        if a.acao == "importar":
            print(json.dumps(feito.para_registro(), ensure_ascii=False,
                             indent=1))
            return 0 if feito.desfecho != bps.RECUSADO else 1

        fonte = bps.BPSIndice(armazem.buscar)
        for termo in a.termos:
            achado = fonte.pesquisar(Consulta(
                descricao=termo, codigo_catalogo=a.catmat, limite=a.limite))
            print(f"\n== {termo}: {len(achado.referencias)} referência(s)"
                  f" | {achado.desfecho.value}")
            for r in achado.referencias[:a.limite]:
                print(f"  R$ {r.valor_unitario_original} / {r.unidade_original}"
                      f" | {r.descricao_original[:60]} | {r.orgao} ({r.uf})"
                      f" | {r.data_compra} | {r.referencia_externa}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
