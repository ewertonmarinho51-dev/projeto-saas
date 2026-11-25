"""
Importação do SICRO — o que roda FORA do clique, na bancada ou no servidor.

    # descobre no portal do DNIT a edição da UF e competência (a "revisado",
    # se houver), baixa o 7-Zip, extrai os relatórios, valida e publica
    python -m src.precos.sicro_servico importar --uf PA --competencia 2026-07 --banco

    # o 7-Zip já baixado: diga de onde veio (o endereço é conferido)
    python -m src.precos.sicro_servico importar --uf PA --competencia 2026-07 \
        --arquivo D:/pa-07-2026.7z --url https://www.gov.br/dnit/…/pa-07-2026.7z

    # confronta TUDO o que foi lido dos XLSX com os PDFs da mesma edição
    python -m src.precos.sicro_servico conferir --uf PA --competencia 2026-07

    # consulta o que foi importado em memória (medição de bancada)
    python -m src.precos.sicro_servico buscar --uf PA --competencia 2026-07 \
        --termos "concreto usinado"

O DNIT publica em 7-Zip, que a biblioteca padrão do Python não lê. A
extração usa um extrator do sistema — `bsdtar` (o `tar.exe` do Windows 10+
é bsdtar) ou `7z` —, sem dependência nova: lista antes (número de entradas
e tamanho total com teto), extrai numa pasta vazia, e só aceita arquivo
regular com o nome de relatório da UF e competência pedidas. A imagem de
produção não traz extrator; a importação roda na bancada com `--banco`, ou
num servidor que tenha `libarchive-tools`.

Mora em `src/` pela mesma razão do SINAPI: a imagem de produção não carrega
`scripts/`. A credencial de SERVIDOR vem do ambiente (`SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`) e nunca é impressa. Nada aqui liga a consulta: isso
é a flag `referencia_custos_sicro`.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import arquivos, sicro

MAX_ENTRADAS = 40               # 24 em jul/2026
MAX_EXTRAIDO = 400_000_000      # 37 MB em jul/2026 (só XLSX); com PDF, ~70 MB
MAX_PAGINA = 5_000_000
TEMPO_EXTRACAO = 300
_RELATORIO_PDF = re.compile(
    r"^([A-Z]{2}) (\d{2})-(\d{4}) Relatório Sintético de .+\.pdf$")


class ArmazemSupabase:
    """O contrato de `sicro.Armazem`, nas tabelas da 0049."""

    def __init__(self, cliente) -> None:
        self._c = cliente

    def _versoes(self, competencia, uf):
        return (self._c.table("precos_sicro_versoes").select("*")
                .eq("competencia", competencia).eq("uf", uf))

    def versao(self, competencia, uf, sha256):
        dados = self._versoes(competencia, uf).eq("sha256", sha256).limit(1).execute().data
        return dados[0] if dados else None

    def versao_publicada(self, competencia, uf):
        dados = self._versoes(competencia, uf).eq("vigente", True).limit(1).execute().data
        return dados[0] if dados else None

    def registrar_versao(self, competencia, uf, sha256, **campos):
        self._c.table("precos_sicro_versoes").upsert(
            {**campos, "competencia": competencia, "uf": uf, "sha256": sha256},
            on_conflict="competencia,uf,sha256").execute()

    def gravar_registros(self, linhas):
        # sem a coluna `vigente`: linha nova nasce invisível (default false)
        self._c.table("precos_sicro_registros").upsert(
            linhas, on_conflict="registro_id").execute()

    def publicar(self, competencia, uf, sha256, **campos):
        registros = self._c.table("precos_sicro_registros")
        versoes = self._c.table("precos_sicro_versoes")
        # 1) o que é desta versão aparece; 2) o que ficou só na anterior some
        registros.update({"vigente": True}).eq("competencia", competencia).eq(
            "uf", uf).eq("arquivo_sha256", sha256).execute()
        registros.update({"vigente": False}).eq("competencia", competencia).eq(
            "uf", uf).neq("arquivo_sha256", sha256).execute()
        # uma vigente por (competência, UF) — índice único parcial
        versoes.update({"vigente": False}).eq("competencia", competencia).eq(
            "uf", uf).neq("sha256", sha256).execute()
        versoes.update({**campos, "estado": sicro.PUBLICADO, "vigente": True}).eq(
            "competencia", competencia).eq("uf", uf).eq("sha256", sha256).execute()

    def buscar(self, termos, *, codigo=None, uf=None, competencia=None,
               regime=None, tipo=None, limite=50):
        return self._c.rpc("precos_sicro_buscar", {
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


# ---------------------------------------------------------------------------
# Descoberta no portal do DNIT
# ---------------------------------------------------------------------------
def _links(conteudo: str) -> list[str]:
    return [html.unescape(h) for h in re.findall(r'href="([^"]+)"', conteudo)]


def pagina_da_edicao(conteudo_da_regiao: str, uf: str, competencia: str) -> str | None:
    """A página da edição na listagem da região; a "revisado" ganha da
    original. Só endereço da árvore oficial, da UF e do mês pedidos."""
    ano, mes = sicro.competencia_valida(competencia)
    nome_mes = sicro.MESES[mes - 1]
    pasta = sicro.pasta_da_uf(uf)
    alvo = re.compile(re.escape(pasta) + rf"{ano}/[a-z0-9-]+/{nome_mes}-{ano}(-revisado)?$")
    achadas = sorted({l for l in _links(conteudo_da_regiao)
                      if alvo.fullmatch(l) and sicro.url_oficial(l)},
                     key=lambda l: (not l.endswith("-revisado"), l))
    return achadas[0] if achadas else None


def arquivo_da_edicao(conteudo_da_pagina: str, pagina: str, uf: str,
                      competencia: str) -> str | None:
    """O 7-Zip linkado na página da edição, na MESMA pasta dela."""
    pasta = pagina.rsplit("/", 1)[0] + "/"
    for link in _links(conteudo_da_pagina):
        if link.startswith(pasta) and sicro.url_oficial(link) and \
                sicro.nome_do_arquivo_oficial(link.rsplit("/", 1)[-1], uf, competencia) \
                and "/" not in link[len(pasta):]:
            return link
    return None


def _ler_pagina(url: str, pasta: Path) -> str:
    destino = pasta / f"pagina-{abs(hash(url))}.html"
    arquivos.baixar(url, destino, maximo=MAX_PAGINA)
    return destino.read_text(encoding="utf-8", errors="replace")


def descobrir(uf: str, competencia: str, pasta: Path, *, ler=_ler_pagina) -> tuple[str, str]:
    """(página da edição, endereço do 7-Zip) — ou SystemExit com o motivo."""
    regiao = sicro.UFS[uf][0]
    indice = f"{sicro.URL_RELATORIOS}{regiao}/{regiao}"
    pagina = pagina_da_edicao(ler(indice, pasta), uf, competencia)
    if pagina is None:
        raise SystemExit(f"o DNIT ainda não publicou {uf} {competencia} em {indice}")
    arquivo = arquivo_da_edicao(ler(pagina, pasta), pagina, uf, competencia)
    if arquivo is None:
        raise SystemExit(f"a página {pagina} não traz o 7-Zip da edição")
    return pagina, arquivo


# ---------------------------------------------------------------------------
# Extração do 7-Zip
# ---------------------------------------------------------------------------
def extrator() -> tuple[str, str]:
    """('bsdtar' | '7z', executável). O `tar` só serve se for bsdtar."""
    candidatos = [shutil.which("bsdtar"), shutil.which("tar")]
    if os.name == "nt":
        # o do Windows primeiro: o `tar` do Git Bash é GNU e não lê 7-Zip
        candidatos.insert(0, str(Path(os.environ.get("SystemRoot", r"C:\Windows"))
                                 / "System32" / "tar.exe"))
    for caminho in candidatos:
        if caminho and Path(caminho).is_file():
            versao = subprocess.run([caminho, "--version"], capture_output=True,
                                    text=True, timeout=30).stdout
            if "bsdtar" in versao:
                return "bsdtar", caminho
    for nome in ("7z", "7za", "7zz"):
        caminho = shutil.which(nome)
        if caminho:
            return "7z", caminho
    raise SystemExit("não há extrator de 7-Zip (bsdtar ou 7z) nesta máquina")


def _listar(tipo: str, programa: str, arquivo: Path) -> tuple[int, int]:
    """(entradas, bytes descompactados) pelo índice do 7-Zip, antes de extrair."""
    if tipo == "bsdtar":
        saida = subprocess.run([programa, "-tvf", str(arquivo)], capture_output=True,
                               timeout=TEMPO_EXTRACAO, check=True).stdout.decode(
                                   "utf-8", errors="replace")
        tamanhos = [int(m.group(1)) for m in re.finditer(
            r"^\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s", saida, re.MULTILINE)]
        linhas = [l for l in saida.splitlines() if l.strip()]
        if len(tamanhos) != len(linhas):
            raise arquivos.ArquivoRecusado("listagem do 7-Zip fora do formato")
        return len(linhas), sum(tamanhos)
    saida = subprocess.run([programa, "l", "-slt", str(arquivo)], capture_output=True,
                           timeout=TEMPO_EXTRACAO, check=True).stdout.decode(
                               "utf-8", errors="replace")
    tamanhos = [int(x) for x in re.findall(r"^Size = (\d+)$", saida, re.MULTILINE)]
    return len(tamanhos), sum(tamanhos)


def extrair(arquivo: Path, pasta: Path, *, com_pdf: bool = False,
            programa: tuple[str, str] | None = None) -> Path:
    """Extrai os relatórios para `pasta` (vazia) e confere o que saiu."""
    tipo, executavel = programa or extrator()
    entradas, total = _listar(tipo, executavel, arquivo)
    if not 0 < entradas <= MAX_ENTRADAS:
        raise arquivos.ArquivoRecusado(f"{entradas} entradas no 7-Zip")
    if total > MAX_EXTRAIDO:
        raise arquivos.ArquivoRecusado(f"7-Zip descompacta {total} bytes")
    pasta.mkdir(parents=True, exist_ok=True)
    if any(pasta.iterdir()):
        raise ValueError("a pasta de extração tem de estar vazia")
    # só os SINTÉTICOS (o analítico não é lido); padrão em ASCII, que passa
    # igual pela linha de comando de qualquer sistema
    padroes = ["*Sint*tico*.xlsx"] + (["*Sint*tico*.pdf"] if com_pdf else [])
    if tipo == "bsdtar":
        # sem -P: o bsdtar recusa caminho absoluto e "..". Sem -k também não
        # sobrescreve nada: a pasta é nova
        comando = [executavel, "-xf", str(arquivo), "-C", str(pasta)]
        for p in padroes:
            comando += ["--include", p]
    else:
        comando = [executavel, "x", "-y", f"-o{pasta}", str(arquivo), *padroes]
    subprocess.run(comando, capture_output=True, timeout=TEMPO_EXTRACAO, check=True)
    for caminho in pasta.rglob("*"):
        nome = unicodedata.normalize("NFC", caminho.name)
        if caminho.is_symlink() or caminho.is_dir() or caminho.parent != pasta:
            raise arquivos.ArquivoRecusado(f"entrada inesperada no 7-Zip: {nome}")
        if not (sicro._NOME_RELATORIO.fullmatch(nome) or _RELATORIO_PDF.fullmatch(nome)):
            raise arquivos.ArquivoRecusado(f"arquivo inesperado no 7-Zip: {nome}")
    return pasta


# ---------------------------------------------------------------------------
# Conferência contra a edição em PDF
# ---------------------------------------------------------------------------
CONFRONTOS = (
    ("Composições de Custos", sicro.COMPOSICAO, sicro.SEM_DESONERACAO, -1, "valor"),
    ("Materiais", sicro.MATERIAL, sicro.NAO_SE_APLICA, -1, "valor"),
    ("Mão de Obra", sicro.MAO_DE_OBRA, sicro.SEM_DESONERACAO, -1, "valor"),
    ("Mão de Obra - com desoneração", sicro.MAO_DE_OBRA, sicro.COM_DESONERACAO, -1, "valor"),
    ("Equipamentos", sicro.EQUIPAMENTO, sicro.SEM_DESONERACAO, -2, "valor"),
    ("Equipamentos", sicro.EQUIPAMENTO, sicro.SEM_DESONERACAO, -1, "valor_improdutivo"),
    ("Equipamentos - com desoneração", sicro.EQUIPAMENTO, sicro.COM_DESONERACAO, -2, "valor"),
    ("Equipamentos - com desoneração", sicro.EQUIPAMENTO, sicro.COM_DESONERACAO, -1,
     "valor_improdutivo"),
)


def conferir(pasta: Path, *, uf: str, competencia: str) -> dict:
    """Lê os XLSX e confronta CADA valor com o PDF sintético da mesma edição."""
    import pymupdf

    ano, mes = sicro.competencia_valida(competencia)
    leitura = sicro.Leitura()
    linhas = list(sicro.ler(pasta, uf=uf, competencia=competencia, leitura=leitura))
    pdfs = {unicodedata.normalize("NFC", p.name): p for p in pasta.glob("*.pdf")}
    relato = {"leitura": {"linhas": leitura.linhas, "validas": leitura.validas,
                          "recusas": dict(leitura.recusas),
                          "por_tipo": dict(leitura.por_tipo)},
              "confrontos": [],
              "em": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    for relatorio, tipo, regime, posicao, campo in CONFRONTOS:
        nome = f"{uf} {mes:02d}-{ano} Relatório Sintético de {relatorio}.pdf"
        if nome not in pdfs:
            raise SystemExit(f"falta o PDF {nome}")
        with pymupdf.open(pdfs[nome]) as documento:
            texto = [l for pagina in documento for l in pagina.get_text().splitlines()]
        alvo = [l for l in linhas if (l["tipo"], l["regime"]) == (tipo, regime)]
        resultado = sicro.confrontar_com_pdf(
            alvo, sicro.valores_do_pdf(texto, posicao=posicao), campo=campo)
        relato["confrontos"].append({"relatorio": relatorio, "campo": campo,
                                     **resultado.para_registro()})
    return relato


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="SICRO — importação e conferência")
    sub = p.add_subparsers(dest="acao", required=True)
    for nome in ("importar", "conferir", "buscar"):
        s = sub.add_parser(nome)
        s.add_argument("--uf", default="PA")
        s.add_argument("--competencia", required=True, help="AAAA-MM")
        s.add_argument("--arquivo", type=Path, help="o 7-Zip já baixado")
        s.add_argument("--url", help="de onde o 7-Zip já baixado veio")
        if nome == "importar":
            s.add_argument("--banco", action="store_true")
        if nome == "buscar":
            s.add_argument("--termos", nargs="+", default=[])
            s.add_argument("--codigo", default=None)
            s.add_argument("--regime", default=sicro.SEM_DESONERACAO)
            s.add_argument("--limite", type=int, default=10)
    a = p.parse_args(argv)
    uf = a.uf.upper()
    if uf not in sicro.UFS:
        raise SystemExit(f"UF desconhecida: {uf}")
    sicro.competencia_valida(a.competencia)

    programa = extrator()                 # antes de baixar 26 MB
    with tempfile.TemporaryDirectory() as temporaria:
        temporaria = Path(temporaria)
        if a.arquivo:
            if not a.url or not sicro.url_oficial(a.url) or \
                    a.url.rsplit("/", 1)[-1] != a.arquivo.name:
                raise SystemExit("--arquivo pede --url oficial do DNIT com o mesmo nome")
            caminho, url = a.arquivo, a.url
        else:
            _, url = descobrir(uf, a.competencia, temporaria)
            caminho = temporaria / url.rsplit("/", 1)[-1]
            arquivos.baixar(url, caminho)
        if not sicro.nome_do_arquivo_oficial(caminho.name, uf, a.competencia):
            raise SystemExit(f"{caminho.name} não é o arquivo de {uf} {a.competencia}")
        sha = arquivos.sha256_do_arquivo(caminho)
        pasta = extrair(caminho, temporaria / "relatorios",
                        com_pdf=a.acao == "conferir", programa=programa)

        if a.acao == "conferir":
            relato = conferir(pasta, uf=uf, competencia=a.competencia)
            relato.update(arquivo=caminho.name, sha256=sha, url=url)
            print(json.dumps(relato, ensure_ascii=False, indent=1))
            return 0 if all(not c["divergentes"] and not c["ausentes_no_pdf"]
                            for c in relato["confrontos"]) else 1

        armazem = armazem_do_banco() if getattr(a, "banco", False) \
            else sicro.ArmazemEmMemoria()
        feito = sicro.importar(armazem, pasta, uf=uf, competencia=a.competencia,
                               sha256=sha, url=url, arquivo=caminho.name)
        if a.acao == "importar":
            print(json.dumps({**feito.para_registro(), "url": url},
                             ensure_ascii=False, indent=1))
            return 0 if feito.desfecho != sicro.RECUSADO else 1

        for termo in (a.termos or [""]):
            achados = sicro.consultar(armazem.buscar, termo=termo, codigo=a.codigo,
                                      uf=uf, regime=a.regime, limite=a.limite)
            print(f"\n== {termo or a.codigo}: {len(achados)}")
            for x in achados:
                print(f"  {x.rotulo_tipo} {x.codigo} | R$ {x.valor} / {x.unidade} | "
                      f"{x.descricao[:60]} | {x.rotulo_regime} | "
                      f"{x.planilha[-40:]}!{x.linha_planilha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
