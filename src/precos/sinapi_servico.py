"""
Importação do SINAPI — o que roda FORA do clique, na bancada ou no servidor.

    # baixa o arquivo oficial da competência, valida, importa e publica
    python -m src.precos.sinapi_servico importar --competencia 2026-10 --uf PA --banco
    python -m src.precos.sinapi_servico importar --competencia 2026-10 --uf PA --zip D:/sinapi.zip

    # relê uma amostra do que foi lido, célula a célula, na planilha oficial
    python -m src.precos.sinapi_servico conferir --competencia 2026-10 --uf PA --amostra 200

    # pesquisa no que foi importado em memória (medição de bancada)
    python -m src.precos.sinapi_servico buscar --competencia 2026-10 --uf PA \
        --termos "cimento portland" --tipo insumo

Mora em `src/` pela mesma razão do indexador do PNCP e do BPS: a imagem de
produção não carrega `scripts/`. A credencial de SERVIDOR vem do ambiente
(`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`) e nunca é impressa. Nada aqui abre a
consulta: isso é `fontes_externas.habilitada("sinapi")`.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import random
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import arquivos, sinapi


class ArmazemSupabase:
    """O contrato de `sinapi.Armazem`, nas tabelas da 0046."""

    def __init__(self, cliente) -> None:
        self._c = cliente

    def versao(self, competencia, uf, sha256):
        dados = (self._c.table("precos_sinapi_versoes").select("*")
                 .eq("competencia", competencia).eq("uf", uf)
                 .eq("sha256", sha256).limit(1).execute()).data
        return dados[0] if dados else None

    def versao_publicada(self, competencia, uf):
        dados = (self._c.table("precos_sinapi_versoes").select("*")
                 .eq("competencia", competencia).eq("uf", uf)
                 .eq("vigente", True).limit(1).execute()).data
        return dados[0] if dados else None

    def registrar_versao(self, competencia, uf, sha256, **campos):
        self._c.table("precos_sinapi_versoes").upsert(
            {**campos, "competencia": competencia, "uf": uf, "sha256": sha256},
            on_conflict="competencia,uf,sha256").execute()

    def gravar_registros(self, linhas):
        # sem `vigente`: linha nova nasce invisível (default false) e a que
        # já existia continua como estava até a publicação
        self._c.table("precos_sinapi_registros").upsert(
            linhas, on_conflict="registro_id").execute()

    def publicar(self, competencia, uf, sha256, **campos):
        registros = self._c.table("precos_sinapi_registros")
        versoes = self._c.table("precos_sinapi_versoes")
        # 1) o que é desta versão aparece; 2) o que ficou só na anterior some
        registros.update({"vigente": True}).eq("competencia", competencia) \
            .eq("uf", uf).eq("arquivo_sha256", sha256).execute()
        registros.update({"vigente": False}).eq("competencia", competencia) \
            .eq("uf", uf).neq("arquivo_sha256", sha256).execute()
        # uma vigente por competência e UF (índice único parcial)
        versoes.update({"vigente": False}).eq("competencia", competencia) \
            .eq("uf", uf).neq("sha256", sha256).execute()
        versoes.update({**campos, "estado": sinapi.PUBLICADO, "vigente": True}) \
            .eq("competencia", competencia).eq("uf", uf) \
            .eq("sha256", sha256).execute()

    def buscar(self, termos, *, codigo=None, uf="PA", competencia=None,
               tipo=None, regime=None, limite=50):
        return self._c.rpc("precos_sinapi_buscar", {
            "p_termos": termos, "p_codigo": codigo, "p_uf": uf,
            "p_competencia": competencia, "p_tipo": tipo, "p_regime": regime,
            "p_limite": limite}).execute().data or []


def armazem_do_banco() -> ArmazemSupabase:
    url = os.environ.get("SUPABASE_URL")
    chave = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not chave:
        raise SystemExit("defina SUPABASE_URL e SUPABASE_SERVICE_KEY no "
                         "ambiente (a chave não é lida de arquivo)")
    from supabase import create_client

    return ArmazemSupabase(create_client(url, chave))


def _abrir_com_cookies():
    """
    O site da CAIXA responde 302 em laço a quem não devolve o cookie que ele
    mesmo põe (medido em 23/11/2026). Um abridor com pote de cookies, só
    para esta sessão de download — nada é persistido.
    """
    abridor = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    return lambda requisicao: abridor.open(requisicao, timeout=arquivos.TIMEOUT_S)


def baixar(competencia: str, destino: Path, *, abrir=None,
           dormir=time.sleep) -> arquivos.Snapshot:
    """
    O arquivo oficial da competência. Em 23/11/2026 a primeira tentativa
    caiu num laço de 302 do balanceador da CAIXA e as três seguintes, com os
    mesmos cabeçalhos, responderam 200: o laço é tratado como falha
    passageira — nova tentativa com pote de cookies novo, até 3 vezes.
    """
    for tentativa in range(1, 4):
        try:
            return arquivos.baixar(
                sinapi.url_do_arquivo(competencia), destino,
                abrir=abrir or _abrir_com_cookies(), maximo=60_000_000,
                dormir=dormir)
        except urllib.error.HTTPError as erro:
            if erro.code not in (301, 302, 303, 307, 308) or tentativa == 3:
                raise
            dormir(2.0 * tentativa)
    raise RuntimeError("inalcançável")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="SINAPI — importação e conferência")
    sub = p.add_subparsers(dest="acao", required=True)
    for nome in ("importar", "conferir", "buscar"):
        s = sub.add_parser(nome)
        s.add_argument("--competencia", required=True)
        s.add_argument("--uf", default="PA")
        s.add_argument("--zip", type=Path)
        if nome == "importar":
            s.add_argument("--banco", action="store_true")
        if nome == "conferir":
            s.add_argument("--amostra", type=int, default=200)
        if nome == "buscar":
            s.add_argument("--termos", nargs="+", required=True)
            s.add_argument("--tipo", choices=sorted(sinapi.TIPOS))
            s.add_argument("--regime", default="sem_desoneracao",
                           choices=sorted(sinapi.REGIMES))
            s.add_argument("--limite", type=int, default=5)
    a = p.parse_args(argv)
    sinapi.competencia_valida(a.competencia)

    with tempfile.TemporaryDirectory() as pasta:
        modificado = None
        caminho = a.zip
        if caminho is None:
            snap = baixar(a.competencia, Path(pasta) / "sinapi.zip")
            caminho, modificado = snap.caminho, snap.last_modified

        if a.acao == "conferir":
            leitura = sinapi.Leitura()
            linhas = [sinapi.linha_do_indice(
                r, sha256=arquivos.sha256_do_arquivo(caminho),
                url=sinapi.url_do_arquivo(a.competencia))
                for r in sinapi.ler(caminho, a.competencia, (a.uf,),
                                    leitura=leitura)]
            amostra = random.Random(20261123).sample(
                linhas, min(a.amostra, len(linhas)))
            confronto = sinapi.confrontar(amostra, caminho)
            print(json.dumps({"competencia": a.competencia, "uf": a.uf,
                              "validos": leitura.validos,
                              "recusas": dict(leitura.motivos),
                              "em": datetime.now(timezone.utc).isoformat(
                                  timespec="seconds"),
                              **confronto.para_registro()},
                             ensure_ascii=False, indent=1))
            return 0 if confronto.iguais == confronto.conferidos else 1

        armazem = armazem_do_banco() if getattr(a, "banco", False) \
            else sinapi.ArmazemEmMemoria()
        feito = sinapi.importar(armazem, caminho, competencia=a.competencia,
                                uf=a.uf, last_modified=modificado)
        if a.acao == "importar":
            print(json.dumps(feito.para_registro(), ensure_ascii=False,
                             indent=1))
            return 0 if feito.desfecho != sinapi.RECUSADO else 1

        for termo in a.termos:
            achados = sinapi.consultar(
                armazem.buscar, termo=termo, uf=a.uf, competencia=a.competencia,
                tipo=a.tipo, regime=a.regime, limite=a.limite)
            print(f"\n== {termo}: {len(achados)}")
            for x in achados:
                print(f"  {x['codigo']} | {x['descricao'][:60]} | {x['unidade']}"
                      f" | R$ {x['valor']} | {x['rotulo_tipo']}, "
                      f"{x['rotulo_regime']} | {x['aba']} linha "
                      f"{x['linha_planilha']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
