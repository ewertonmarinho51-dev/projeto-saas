"""
Arquivo oficial de fonte nova: baixar com limites e abrir sem confiar.

Pacote de expansão das fontes (20/10/2026). Nada aqui roda no clique do
usuário: é trabalho de bancada (`scripts/etl_fontes_precos.py`). A busca
da pesquisa nunca baixa arquivo.

* `baixar` — só HTTPS, só os hosts das fontes registradas (também depois
  de redirecionar), teto de bytes, timeout, nova tentativa só para
  429/5xx e falha de rede, com recuo exponencial. Grava em arquivo
  temporário e só renomeia quando terminou, com o SHA-256 dos bytes;
* `conferir_zip` — recusa caminho absoluto ou com `..` (zip-slip), link
  simbólico, entrada cifrada, extensão inesperada, arquivo grande demais
  e taxa de compressão de bomba. Nada é extraído para o disco: as linhas
  são lidas do ZIP em streaming (`abrir_csv`).
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

HOSTS_PERMITIDOS = frozenset({"dados.tce.rs.gov.br", "s3.sa-east-1.amazonaws.com"})
# no S3, só o bucket do CKAN da Saúde
PREFIXOS_S3 = ("/ckan.saude.gov.br/",)
MAX_DOWNLOAD = 600_000_000            # o ZIP 2026 do TCE-RS tem 258 MB
MAX_ENTRADAS = 50
MAX_DESCOMPACTADO = 3_000_000_000
MAX_POR_ARQUIVO = 1_500_000_000
MAX_TAXA = 200
EXTENSOES = frozenset({".csv", ".json"})
TENTATIVAS = 3
RECUO_S = 2.0
TIMEOUT_S = 60
PEDACO = 1024 * 1024


class ArquivoRecusado(ValueError):
    """O arquivo não passa nas defesas — não é lido."""


@dataclass(frozen=True)
class Snapshot:
    url: str
    caminho: Path
    sha256: str
    bytes: int
    last_modified: str | None = None
    etag: str | None = None


def url_permitida(url: str) -> bool:
    partes = urllib.parse.urlparse(url)
    if partes.scheme != "https" or partes.username or partes.password:
        return False
    host = (partes.hostname or "").lower()
    if host not in HOSTS_PERMITIDOS:
        return False
    if host == "s3.sa-east-1.amazonaws.com":
        return partes.path.startswith(PREFIXOS_S3)
    return True


def sha256_do_arquivo(caminho: Path) -> str:
    soma = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for pedaco in iter(lambda: fh.read(PEDACO), b""):
            soma.update(pedaco)
    return soma.hexdigest()


def baixar(url: str, destino: Path, *, abrir=None, dormir=time.sleep,
           maximo: int = MAX_DOWNLOAD) -> Snapshot:
    """Baixa `url` para `destino`. Recusa host/esquema fora da lista."""
    if not url_permitida(url):
        raise ArquivoRecusado(f"URL fora das fontes registradas: {url}")
    abrir = abrir or (lambda req: urllib.request.urlopen(req, timeout=TIMEOUT_S))
    temporario = destino.with_suffix(destino.suffix + ".parcial")
    recuo = RECUO_S
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            requisicao = urllib.request.Request(
                url, headers={"User-Agent": "GovDocs/fontes-precos"})
            with abrir(requisicao) as resposta:
                final = resposta.geturl() if hasattr(resposta, "geturl") else url
                if not url_permitida(final):
                    raise ArquivoRecusado(f"redirecionou para fora: {final}")
                declarado = resposta.headers.get("Content-Length")
                if declarado and int(declarado) > maximo:
                    raise ArquivoRecusado(f"arquivo de {declarado} bytes passa "
                                          f"do teto de {maximo}")
                soma, total = hashlib.sha256(), 0
                with open(temporario, "wb") as fh:
                    for pedaco in iter(lambda: resposta.read(PEDACO), b""):
                        total += len(pedaco)
                        if total > maximo:
                            raise ArquivoRecusado("arquivo passou do teto "
                                                  "durante o download")
                        soma.update(pedaco)
                        fh.write(pedaco)
                os.replace(temporario, destino)
                return Snapshot(url, destino, soma.hexdigest(), total,
                                resposta.headers.get("Last-Modified"),
                                resposta.headers.get("ETag"))
        except ArquivoRecusado:
            Path(temporario).unlink(missing_ok=True)
            raise
        except urllib.error.HTTPError as erro:
            Path(temporario).unlink(missing_ok=True)
            if erro.code not in (429, 500, 502, 503, 504) or \
                    tentativa == TENTATIVAS:
                raise
        except (urllib.error.URLError, OSError):
            Path(temporario).unlink(missing_ok=True)
            if tentativa == TENTATIVAS:
                raise
        dormir(recuo)
        recuo *= 2
    raise RuntimeError("inalcançável")


def conferir_zip(caminho: Path) -> list[zipfile.ZipInfo]:
    """As defesas, antes de ler qualquer byte de dentro."""
    with zipfile.ZipFile(caminho) as z:
        entradas = z.infolist()
    if len(entradas) > MAX_ENTRADAS:
        raise ArquivoRecusado("entradas demais no ZIP")
    total = 0
    for info in entradas:
        nome = info.filename.replace("\\", "/")
        partes = PurePosixPath(nome)
        if partes.is_absolute() or ".." in partes.parts or ":" in nome:
            raise ArquivoRecusado(f"caminho inseguro no ZIP: {info.filename}")
        if (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
            raise ArquivoRecusado("link simbólico no ZIP")
        if info.flag_bits & 0x1:
            raise ArquivoRecusado("entrada cifrada no ZIP")
        if info.is_dir():
            continue
        if partes.suffix.lower() not in EXTENSOES:
            raise ArquivoRecusado(f"extensão inesperada: {partes.name}")
        if info.file_size > MAX_POR_ARQUIVO:
            raise ArquivoRecusado(f"arquivo grande demais: {partes.name}")
        if info.file_size and info.file_size / max(info.compress_size, 1) > MAX_TAXA:
            raise ArquivoRecusado(f"taxa de compressão suspeita: {partes.name}")
        total += info.file_size
        if total > MAX_DESCOMPACTADO:
            raise ArquivoRecusado("conteúdo descompactado grande demais")
    return entradas


def abrir_csv(z: zipfile.ZipFile, nome: str, *, separador: str):
    """(cabeçalho, leitor de listas) em streaming, UTF-8 com BOM."""
    csv.field_size_limit(10_000_000)
    fh = io.TextIOWrapper(z.open(nome), encoding="utf-8-sig", newline="")
    leitor = csv.reader(fh, delimiter=separador)
    return next(leitor, []), leitor
