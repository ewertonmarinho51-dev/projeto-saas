"""
Importação do SIGTAP — o que roda FORA do clique, na bancada ou no servidor.

    # descobre no FTP oficial a versão mais recente da competência, baixa,
    # valida e publica
    python -m src.precos.sigtap_servico importar --competencia 2026-11 --banco
    python -m src.precos.sigtap_servico importar \
        --zip D:/TabelaUnificada_202611_v2611051737.zip --banco

    # lista o que o DATASUS publicou para a competência (sem baixar)
    python -m src.precos.sigtap_servico listar --competencia 2026-11

    # consulta o que foi importado em memória (medição de bancada)
    python -m src.precos.sigtap_servico buscar --zip D:/TabelaUnificada_….zip \
        --termos "parto cesariano"

Mora em `src/` pela mesma razão do SINAPI e do BPS: a imagem de produção não
carrega `scripts/`. A credencial de SERVIDOR vem do ambiente (`SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`) e nunca é impressa. Nada aqui liga a consulta: isso
é a flag `referencia_sus_sigtap`.

O canal oficial é FTP sem criptografia. O baixador só fala com
`ftp2.datasus.gov.br`, só na pasta da Tabela Unificada, só pede arquivo com
o nome da publicação e para no teto de tamanho; a integridade do conteúdo é
conferida pelo leitor (`sigtap.ler`), não pelo transporte.
"""

from __future__ import annotations

import argparse
import ftplib
import json
import os
import tempfile
from pathlib import Path

from . import sigtap

# o de 11/2026 tem 2,1 MB; o teto é folga, não estimativa
TETO_BYTES = 50 * 1024 * 1024
TEMPO_LIMITE = 60


class ArmazemSupabase:
    """O contrato de `sigtap.Armazem`, nas tabelas da 0048."""

    def __init__(self, cliente) -> None:
        self._c = cliente

    def versao(self, competencia, sha256):
        dados = (self._c.table("precos_sigtap_versoes").select("*")
                 .eq("competencia", competencia).eq("sha256", sha256)
                 .limit(1).execute()).data
        return dados[0] if dados else None

    def versao_publicada(self, competencia):
        dados = (self._c.table("precos_sigtap_versoes").select("*")
                 .eq("competencia", competencia).eq("vigente", True)
                 .limit(1).execute()).data
        return dados[0] if dados else None

    def registrar_versao(self, competencia, sha256, **campos):
        self._c.table("precos_sigtap_versoes").upsert(
            {**campos, "competencia": competencia, "sha256": sha256},
            on_conflict="competencia,sha256").execute()

    def gravar_registros(self, linhas):
        # sem a coluna `vigente`: linha nova nasce invisível (default false)
        self._c.table("precos_sigtap_procedimentos").upsert(
            linhas, on_conflict="registro_id").execute()

    def publicar(self, competencia, sha256, **campos):
        registros = self._c.table("precos_sigtap_procedimentos")
        versoes = self._c.table("precos_sigtap_versoes")
        # 1) o que é desta versão aparece; 2) o que ficou só na anterior some
        registros.update({"vigente": True}).eq("competencia", competencia).eq(
            "arquivo_sha256", sha256).execute()
        registros.update({"vigente": False}).eq("competencia", competencia).neq(
            "arquivo_sha256", sha256).execute()
        # uma vigente por competência (índice único parcial): tira a antiga
        versoes.update({"vigente": False}).eq("competencia", competencia).neq(
            "sha256", sha256).execute()
        versoes.update({**campos, "estado": sigtap.PUBLICADO, "vigente": True}
                       ).eq("competencia", competencia).eq("sha256", sha256).execute()

    def buscar(self, termos, *, codigo=None, competencia=None, modalidade=None,
               limite=50):
        return self._c.rpc("precos_sigtap_buscar", {
            "p_termos": termos, "p_codigo": codigo,
            "p_competencia": competencia, "p_modalidade": modalidade,
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
# FTP oficial
# ---------------------------------------------------------------------------
def da_competencia(nomes, competencia: str) -> list[str]:
    """Os arquivos da competência, do mais novo ao mais velho (pela `_v…`).

    Nome fora do padrão da publicação é ignorado: o que vem da listagem
    não vira caminho sem passar por `sigtap.nome_do_arquivo`."""
    sigtap.competencia_valida(competencia)
    achados = []
    for bruto in nomes:
        nome = str(bruto).rsplit("/", 1)[-1]
        try:
            comp, versao = sigtap.nome_do_arquivo(nome)
        except (sigtap.ArquivoInvalido, ValueError):
            continue
        if comp == competencia:
            achados.append((versao, nome))
    return [nome for _, nome in sorted(achados, reverse=True)]


def _conectar(fabrica=ftplib.FTP):
    ftp = fabrica(sigtap.HOST_FTP, timeout=TEMPO_LIMITE)
    ftp.login()                       # anônimo, como o DATASUS publica
    ftp.cwd(sigtap.PASTA_FTP)
    return ftp


def listar(competencia: str, *, fabrica=ftplib.FTP) -> list[str]:
    ftp = _conectar(fabrica)
    try:
        return da_competencia(ftp.nlst(), competencia)
    finally:
        ftp.close()


def baixar(nome: str, pasta: Path, *, fabrica=ftplib.FTP,
           teto: int = TETO_BYTES) -> Path:
    """Baixa UM arquivo da publicação para `pasta`, com teto de tamanho."""
    sigtap.nome_do_arquivo(nome)              # só nome oficial, nada de caminho
    destino = Path(pasta) / Path(nome).name
    ftp = _conectar(fabrica)
    recebido = 0
    try:
        with open(destino, "wb") as saida:
            def gravar(bloco: bytes) -> None:
                nonlocal recebido
                recebido += len(bloco)
                if recebido > teto:
                    raise sigtap.ArquivoInvalido(
                        f"arquivo acima do teto de {teto} bytes")
                saida.write(bloco)

            ftp.retrbinary(f"RETR {Path(nome).name}", gravar)
    except BaseException:
        destino.unlink(missing_ok=True)
        raise
    finally:
        ftp.close()
    return destino


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="SIGTAP — importação e consulta")
    sub = p.add_subparsers(dest="acao", required=True)
    for nome in ("importar", "listar", "buscar"):
        s = sub.add_parser(nome)
        s.add_argument("--competencia", default=None, help="AAAA-MM")
        if nome != "listar":
            s.add_argument("--zip", type=Path,
                           help="o ZIP já baixado, com o nome oficial")
        if nome == "importar":
            s.add_argument("--banco", action="store_true")
        if nome == "buscar":
            s.add_argument("--termos", nargs="+", default=[])
            s.add_argument("--codigo", default=None)
            s.add_argument("--modalidade", default=None)
            s.add_argument("--limite", type=int, default=10)
    a = p.parse_args(argv)

    if a.acao == "listar":
        if not a.competencia:
            raise SystemExit("--competencia é obrigatória")
        print(json.dumps(listar(a.competencia), ensure_ascii=False, indent=1))
        return 0

    with tempfile.TemporaryDirectory() as pasta:
        if a.zip:
            caminho = a.zip
            competencia = sigtap.nome_do_arquivo(caminho.name)[0]
            if a.competencia and a.competencia != competencia:
                raise SystemExit(f"o arquivo é da competência {competencia}, "
                                 f"não de {a.competencia}")
        else:
            if not a.competencia:
                raise SystemExit("--competencia ou --zip")
            nomes = listar(a.competencia)
            if not nomes:
                raise SystemExit(f"nenhum arquivo de {a.competencia} no FTP")
            caminho = baixar(nomes[0], Path(pasta))
            competencia = a.competencia

        armazem = armazem_do_banco() if getattr(a, "banco", False) \
            else sigtap.ArmazemEmMemoria()
        feito = sigtap.importar(armazem, caminho, competencia=competencia)
        if a.acao == "importar":
            print(json.dumps({**feito.para_registro(),
                              "url": sigtap.url_do_arquivo(caminho.name)},
                             ensure_ascii=False, indent=1))
            return 0 if feito.desfecho != sigtap.RECUSADO else 1

        for termo in (a.termos or [""]):
            achados = sigtap.consultar(armazem.buscar, termo=termo,
                                       codigo=a.codigo, modalidade=a.modalidade,
                                       limite=a.limite)
            print(f"\n== {termo or a.codigo}: {len(achados)}")
            for x in achados:
                print(f"  {x['codigo_formatado']} | SA {x['total_ambulatorial']} | "
                      f"SH+SP {x['total_hospitalar']} | {x['nome'][:60]} | "
                      f"{', '.join(x['modalidades'])} | linha {x['linha_arquivo']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
