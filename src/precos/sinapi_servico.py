"""
Importação do SINAPI — o que roda FORA do clique, na bancada ou no servidor.

    # baixa o relatório mensal oficial da competência, valida, importa e
    # publica a versão (só as UFs pedidas; piloto: PA)
    python -m src.precos.sinapi_servico importar --competencia 2026-10 --ufs PA --banco
    python -m src.precos.sinapi_servico importar --zip D:/SINAPI-2026-10-formato-xlsx.zip

    # confronta o que foi lido do XLSX com a edição oficial em PDF da UF
    python -m src.precos.sinapi_servico conferir --competencia 2026-10 --ufs PA

    # consulta o que foi importado em memória (medição de bancada)
    python -m src.precos.sinapi_servico buscar --competencia 2026-10 \
        --termos "cimento portland cp ii"

Mora em `src/` pela mesma razão do indexador do PNCP e do BPS: a imagem de
produção não carrega `scripts/`. A credencial de SERVIDOR vem do ambiente
(`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`) e nunca é impressa. Nada aqui liga
a consulta: isso é a flag `referencia_custos_sinapi`.
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
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import arquivos, sinapi

# O PDF mensal tem 66 MB; o XLSX, 16 MB. O teto do baixador comum é 600 MB.
URL_PDF = "SINAPI-{ano}-{mes}-formato-pdf.zip"


class ArmazemSupabase:
    """O contrato de `sinapi.Armazem`, nas tabelas da 0046."""

    def __init__(self, cliente) -> None:
        self._c = cliente

    def versao(self, competencia, sha256):
        dados = (self._c.table("precos_sinapi_versoes").select("*")
                 .eq("competencia", competencia).eq("sha256", sha256)
                 .limit(1).execute()).data
        return dados[0] if dados else None

    def versao_publicada(self, competencia):
        dados = (self._c.table("precos_sinapi_versoes").select("*")
                 .eq("competencia", competencia).eq("vigente", True)
                 .limit(1).execute()).data
        return dados[0] if dados else None

    def registrar_versao(self, competencia, sha256, **campos):
        self._c.table("precos_sinapi_versoes").upsert(
            {**campos, "competencia": competencia, "sha256": sha256},
            on_conflict="competencia,sha256").execute()

    def gravar_registros(self, linhas):
        # sem a coluna `vigente`: linha nova nasce invisível (default false)
        # e a que já existia continua como estava até a publicação
        self._c.table("precos_sinapi_registros").upsert(
            linhas, on_conflict="registro_id").execute()

    def publicar(self, competencia, sha256, **campos):
        registros = self._c.table("precos_sinapi_registros")
        versoes = self._c.table("precos_sinapi_versoes")
        # 1) o que é desta versão aparece; 2) o que ficou só na anterior some
        registros.update({"vigente": True}).eq("competencia", competencia).eq(
            "arquivo_sha256", sha256).execute()
        registros.update({"vigente": False}).eq("competencia", competencia).neq(
            "arquivo_sha256", sha256).execute()
        # uma vigente por competência (índice único parcial): tira a antiga
        versoes.update({"vigente": False}).eq("competencia", competencia).neq(
            "sha256", sha256).execute()
        versoes.update({**campos, "estado": sinapi.PUBLICADO, "vigente": True}
                       ).eq("competencia", competencia).eq("sha256", sha256).execute()

    def buscar(self, termos, *, codigo=None, uf=None, competencia=None,
               regime=None, tipo=None, limite=50):
        return self._c.rpc("precos_sinapi_buscar", {
            "p_termos": termos, "p_codigo": codigo, "p_uf": uf,
            "p_competencia": competencia, "p_regime": regime, "p_tipo": tipo,
            "p_limite": limite}).execute().data or []


def armazem_do_banco() -> ArmazemSupabase:
    url = os.environ.get("SUPABASE_URL")
    chave = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not chave:
        raise SystemExit("defina SUPABASE_URL e SUPABASE_SERVICE_KEY no "
                         "ambiente (a chave não é lida de arquivo)")
    from supabase import create_client

    return ArmazemSupabase(create_client(url, chave))


def url_do_pdf(competencia: str) -> str:
    ano, mes = competencia.split("-")
    return sinapi.URL_BASE + URL_PDF.format(ano=ano, mes=mes)


def valores_dos_pdfs(caminho: Path, competencia: str, ufs) -> dict[str, dict]:
    """`{uf: {tipo: {codigo: (sem, com)}}}` a partir do ZIP de PDFs oficiais."""
    import pymupdf

    arquivos.conferir_zip(caminho, extensoes=frozenset({".pdf"}))
    aaaamm = competencia.replace("-", "")
    saida: dict[str, dict] = {}
    with zipfile.ZipFile(caminho) as z:
        for uf in ufs:
            saida[uf] = {}
            for tipo, nome in (
                    (sinapi.INSUMO, f"SINAPI_Preco_Ref_Insumos_{uf}_{aaaamm}.pdf"),
                    (sinapi.COMPOSICAO,
                     f"SINAPI_Custo_Ref_Composicoes_{uf}_{aaaamm}.pdf")):
                documento = pymupdf.open(stream=z.read(nome), filetype="pdf")
                linhas = [l for pagina in documento
                          for l in pagina.get_text().splitlines()]
                saida[uf][tipo] = sinapi.valores_do_pdf(linhas, tipo)
    return saida


def conferir(xlsx: Path, pdf: Path, *, competencia: str, ufs,
             amostra: int = 60) -> dict:
    """Importa em memória, confronta TUDO e uma amostra reproduzível."""
    armazem = sinapi.ArmazemEmMemoria()
    feito = sinapi.importar(armazem, xlsx, url=sinapi.url_da_competencia(
        competencia), ufs=ufs, competencia=competencia)
    do_pdf = valores_dos_pdfs(pdf, competencia, ufs)
    relato = {"importacao": feito.para_registro(), "por_uf": {},
              "em": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    for uf in ufs:
        linhas = [l for l in armazem.registros.values() if l["uf"] == uf]
        tudo = sinapi.confrontar_com_pdf(linhas, do_pdf[uf])
        sorteio = random.Random(20261123)
        conferiveis = [l for l in linhas if l["regime"] != sinapi.SEM_ENCARGOS]
        parte = sinapi.confrontar_com_pdf(
            sorteio.sample(conferiveis, min(amostra, len(conferiveis))),
            do_pdf[uf])
        relato["por_uf"][uf] = {"todas": tudo.para_registro(),
                                "amostra": parte.para_registro()}
    return relato


def _abrir_com_cookies():
    """Abridor com pote de cookies só desta sessão de download (nada é
    persistido): o site da CAIXA põe cookie e redireciona."""
    abridor = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    return lambda requisicao: abridor.open(requisicao, timeout=arquivos.TIMEOUT_S)


def _baixar(url: str, pasta: Path, nome: str, *, abrir=None,
            dormir=time.sleep) -> Path:
    """
    Em 23/11/2026 a primeira tentativa de baixar o relatório mensal caiu num
    laço de 302 do balanceador da CAIXA ("redirect error that would lead to an
    infinite loop"); as três seguintes, com os mesmos cabeçalhos, responderam
    200. `arquivos.baixar` só repete 429/5xx, então o laço é tratado aqui como
    falha passageira: nova tentativa com pote de cookies novo, até 3 vezes.
    Qualquer outro erro HTTP sobe como veio.
    """
    for tentativa in range(1, 4):
        try:
            return arquivos.baixar(url, pasta / nome,
                                   abrir=abrir or _abrir_com_cookies(),
                                   dormir=dormir).caminho
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
        s.add_argument("--competencia", default=None,
                       help="AAAA-MM; sem ela, o mês anterior ao de hoje")
        s.add_argument("--ufs", nargs="+", default=list(sinapi.UFS_PILOTO))
        s.add_argument("--zip", type=Path, help="o XLSX zipado já baixado")
        if nome == "importar":
            s.add_argument("--banco", action="store_true")
        if nome == "conferir":
            s.add_argument("--pdf", type=Path, help="o ZIP de PDFs já baixado")
            s.add_argument("--amostra", type=int, default=60)
        if nome == "buscar":
            s.add_argument("--termos", nargs="+", default=[])
            s.add_argument("--codigo", default=None)
            s.add_argument("--uf", default="PA")
            s.add_argument("--limite", type=int, default=10)
    a = p.parse_args(argv)
    competencia = a.competencia or sinapi.competencia_anterior()
    url = sinapi.url_da_competencia(competencia)
    ufs = tuple(u.upper() for u in a.ufs)

    with tempfile.TemporaryDirectory() as pasta:
        pasta = Path(pasta)
        xlsx = a.zip or _baixar(url, pasta, "sinapi.zip")
        if a.acao == "conferir":
            pdf = a.pdf or _baixar(url_do_pdf(competencia), pasta, "pdf.zip")
            relato = conferir(xlsx, pdf, competencia=competencia, ufs=ufs,
                              amostra=a.amostra)
            print(json.dumps(relato, ensure_ascii=False, indent=1))
            ok = all(not v["todas"]["divergentes"] and not v["todas"]["ausentes_no_pdf"]
                     for v in relato["por_uf"].values())
            return 0 if ok else 1

        armazem = armazem_do_banco() if getattr(a, "banco", False) \
            else sinapi.ArmazemEmMemoria()
        feito = sinapi.importar(armazem, xlsx, url=url, ufs=ufs,
                                competencia=competencia)
        if a.acao == "importar":
            print(json.dumps(feito.para_registro(), ensure_ascii=False, indent=1))
            return 0 if feito.desfecho != sinapi.RECUSADO else 1

        consulta = sinapi.ConsultaSINAPI(armazem.buscar)
        for termo in (a.termos or [""]):
            r = consulta.consultar(termo=termo, codigo=a.codigo, uf=a.uf,
                                   limite=a.limite)
            print(f"\n== {termo or a.codigo}: {len(r.referencias)} | "
                  f"competência {r.competencia} | {r.falha or 'ok'}")
            for x in r.referencias:
                print(f"  {x.tipo} {x.codigo} | R$ {x.valor} / {x.unidade} | "
                      f"{x.descricao[:70]} | {x.rotulo_regime} | {x.aba}!{x.linha_planilha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
