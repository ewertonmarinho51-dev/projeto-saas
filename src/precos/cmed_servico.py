"""
Importação da CMED — o que roda FORA do clique, na bancada ou no servidor.

    # descobre na página de preços da CMED a lista PMVG publicada, baixa,
    # valida e publica como a vigente
    python -m src.precos.cmed_servico importar --banco

    # o arquivo já baixado: diga de onde veio (o endereço é conferido)
    python -m src.precos.cmed_servico importar --arquivo D:/lista_pmvg_….xlsx \
        --url https://www.gov.br/anvisa/…/arquivos/lista_pmvg_….xlsx/@@download/file

    # confronta o PF de cada apresentação com o da lista PMC da mesma publicação
    python -m src.precos.cmed_servico conferir

    # consulta o que foi importado em memória (medição de bancada)
    python -m src.precos.cmed_servico buscar --termos "dipirona" --aliquota 19

Mora em `src/` pela mesma razão do SINAPI: a imagem de produção não carrega
`scripts/`. A credencial de SERVIDOR vem do ambiente (`SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`) e nunca é impressa. Nada aqui liga a consulta: isso
é a flag `referencia_teto_cmed`.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import tempfile
from pathlib import Path

from . import arquivos, cmed

MAX_PLANILHA = 100_000_000       # a lista PMVG de 09/11/2026 tem 13,6 MB
MAX_PAGINA = 5_000_000
_LINK = re.compile(r"^/anvisa/pt-br/assuntos/medicamentos/cmed/precos/arquivos/"
                   r"(lista_(pmvg|pmc)_(\d{8})_(\d{9})\.xlsx)/@@download/file$",
                   re.IGNORECASE)


class ArmazemSupabase:
    """O contrato de `cmed.Armazem`, nas tabelas da 0050."""

    def __init__(self, cliente) -> None:
        self._c = cliente

    def versao(self, sha256):
        dados = (self._c.table("precos_cmed_versoes").select("*")
                 .eq("sha256", sha256).limit(1).execute()).data
        return dados[0] if dados else None

    def versao_publicada(self):
        dados = (self._c.table("precos_cmed_versoes").select("*")
                 .eq("vigente", True).limit(1).execute()).data
        return dados[0] if dados else None

    def registrar_versao(self, sha256, **campos):
        self._c.table("precos_cmed_versoes").upsert(
            {**campos, "sha256": sha256}, on_conflict="sha256").execute()

    def gravar_registros(self, linhas):
        # sem a coluna `vigente`: linha nova nasce invisível (default false)
        self._c.table("precos_cmed_registros").upsert(
            linhas, on_conflict="registro_id").execute()

    def publicar(self, sha256, **campos):
        registros = self._c.table("precos_cmed_registros")
        versoes = self._c.table("precos_cmed_versoes")
        # 1) a lista nova aparece; 2) a anterior some (fica gravada)
        registros.update({"vigente": True}).eq("arquivo_sha256", sha256).execute()
        registros.update({"vigente": False}).eq("vigente", True).neq(
            "arquivo_sha256", sha256).execute()
        # uma vigente no total (índice único parcial): tira a antiga
        versoes.update({"vigente": False}).eq("vigente", True).neq(
            "sha256", sha256).execute()
        versoes.update({**campos, "estado": cmed.PUBLICADO, "vigente": True}).eq(
            "sha256", sha256).execute()

    def buscar(self, termos, *, codigo=None, limite=50):
        return self._c.rpc("precos_cmed_buscar", {
            "p_termos": termos, "p_codigo": codigo, "p_limite": limite}).execute().data or []


def armazem_do_banco() -> ArmazemSupabase:
    url = os.environ.get("SUPABASE_URL")
    chave = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not chave:
        raise SystemExit("defina SUPABASE_URL e SUPABASE_SERVICE_KEY no "
                         "ambiente (a chave não é lida de arquivo)")
    from supabase import create_client

    return ArmazemSupabase(create_client(url, chave))


def listas_da_pagina(conteudo: str) -> dict[str, str]:
    """{'pmvg': url, 'pmc': url} da página de preços — a publicação MAIS
    RECENTE de cada, pela data e hora do nome. Só link relativo à pasta
    oficial: endereço de outro host não é lido."""
    achados: dict[str, tuple[str, str]] = {}
    for bruto in re.findall(r'href="([^"]+)"', conteudo):
        link = html.unescape(bruto)
        m = _LINK.fullmatch(link)
        if not m:
            continue
        tipo, carimbo = m.group(2).lower(), m.group(3) + m.group(4)
        url = "https://www.gov.br" + link
        if tipo not in achados or carimbo > achados[tipo][0]:
            achados[tipo] = (carimbo, url)
    return {tipo: url for tipo, (_, url) in achados.items()}


def nome_da_url(url: str) -> str:
    return Path(url.removesuffix("/@@download/file")).name


def _baixar(url: str, pasta: Path) -> Path:
    destino = pasta / nome_da_url(url).lower()
    arquivos.baixar(url, destino, maximo=MAX_PLANILHA)
    return destino


def descobrir(pasta: Path) -> dict[str, str]:
    pagina = pasta / "pagina.html"
    arquivos.baixar(cmed.URL_PAGINA, pagina, maximo=MAX_PAGINA)
    listas = listas_da_pagina(pagina.read_text(encoding="utf-8", errors="replace"))
    if "pmvg" not in listas:
        raise SystemExit(f"a página {cmed.URL_PAGINA} não traz a lista PMVG")
    return listas


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="CMED — importação e conferência")
    sub = p.add_subparsers(dest="acao", required=True)
    for nome in ("importar", "conferir", "buscar"):
        s = sub.add_parser(nome)
        s.add_argument("--arquivo", type=Path, help="a lista PMVG já baixada")
        s.add_argument("--url", help="de onde a lista já baixada veio")
        if nome == "importar":
            s.add_argument("--banco", action="store_true")
        if nome == "conferir":
            s.add_argument("--pmc", type=Path, help="a lista PMC já baixada")
        if nome == "buscar":
            s.add_argument("--termos", nargs="+", default=[])
            s.add_argument("--codigo", default=None)
            s.add_argument("--aliquota", default="18", choices=cmed.ALIQUOTAS)
            s.add_argument("--limite", type=int, default=10)
    a = p.parse_args(argv)

    with tempfile.TemporaryDirectory() as temporaria:
        temporaria = Path(temporaria)
        listas: dict[str, str] = {}
        if a.arquivo:
            if not a.url or not cmed.url_oficial(a.url) or \
                    nome_da_url(a.url).lower() != a.arquivo.name.lower():
                raise SystemExit("--arquivo pede --url oficial da CMED com o mesmo nome")
            caminho, url = a.arquivo, a.url
        else:
            listas = descobrir(temporaria)
            url = listas["pmvg"]
            caminho = _baixar(url, temporaria)

        if a.acao == "conferir":
            pmc = a.pmc
            if pmc is None:
                listas = listas or descobrir(temporaria)
                if "pmc" not in listas:
                    raise SystemExit("a página não traz a lista PMC")
                if nome_da_url(listas["pmc"])[10:] != nome_da_url(url)[11:]:
                    raise SystemExit("as listas PMC e PMVG da página são de "
                                     "publicações diferentes")
                pmc = _baixar(listas["pmc"], temporaria)
            leitura = cmed.Leitura()
            brutas = list(cmed.ler(caminho, nome=nome_da_url(url), leitura=leitura))
            relato = cmed.confrontar_pf(brutas, cmed.pf_da_lista_pmc(pmc))
            saida = {"publicada_em": leitura.publicada_em, "linhas": leitura.linhas,
                     "validas": leitura.validas, "recusas": dict(leitura.recusas),
                     "pf_contra_lista_pmc": relato.para_registro(),
                     "sha256": arquivos.sha256_do_arquivo(caminho), "url": url}
            print(json.dumps(saida, ensure_ascii=False, indent=1))
            return 0 if not relato.divergentes and not relato.ausentes else 1

        armazem = armazem_do_banco() if getattr(a, "banco", False) \
            else cmed.ArmazemEmMemoria()
        feito = cmed.importar(armazem, caminho, url=url, nome=nome_da_url(url))
        if a.acao == "importar":
            print(json.dumps({**feito.para_registro(), "url": url,
                              "destino": "banco" if a.banco else
                              "memória (nada gravado; use --banco)"},
                             ensure_ascii=False, indent=1))
            return 0 if feito.desfecho != cmed.RECUSADO else 1

        for termo in (a.termos or [""]):
            achados = cmed.consultar(armazem.buscar, termo=termo, codigo=a.codigo,
                                     aliquota=a.aliquota, limite=a.limite)
            print(f"\n== {termo or a.codigo}: {len(achados)}")
            for x in achados:
                print(f"  {x.ggrem} | {x.produto} {x.apresentacao[:45]} | teto "
                      f"R$ {x.teto_governo} ({x.base_do_teto}) | PF {x.pf} | "
                      f"PMVG {x.pmvg} | isento ICMS: {x.isento_icms} | linha "
                      f"{x.linha_planilha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
