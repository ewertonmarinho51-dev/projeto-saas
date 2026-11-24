"""
SIGTAP (DATASUS) — remuneração da Tabela Unificada de procedimentos do SUS.

Não é preço de compra nem custo de obra: é o VALOR DE REMUNERAÇÃO que o SUS
paga por procedimento. Por isso não entra em `fontes_padrao()` nem na cesta;
tem consulta própria, rotulada como "remuneração da Tabela Unificada do SUS".

Publicação conferida em 24/11/2026: o DATASUS publica um ZIP por competência,
SÓ por FTP (`ftp://ftp2.datasus.gov.br/pub/sistemas/tup/downloads/`, sem HTTP
nem HTTPS no mesmo servidor), com o nome
`TabelaUnificada_AAAAMM_vAAMMDDHHMM.zip` — a competência e a versão da
geração. O de 11/2026 (`TabelaUnificada_202611_v2611051737.zip`) tem
2.173.129 bytes, sha256 06c074c3…05dad45. Dentro dele, texto de largura fixa
em ISO-8859-1, cada tabela com o seu `*_layout.txt` ao lado.

Lido aqui:

* `tb_procedimento.txt` (336 colunas; 5.068 procedimentos em 11/2026):
  código de 10 dígitos, nome, complexidade e sexo como a fonte codifica,
  VL_SH, VL_SA e VL_SP (12 dígitos, DUAS casas implícitas — conferido:
  glicose SA 000000000185 = R$ 1,85; consulta especializada R$ 10,00;
  cesariana SH R$ 395,68 + SP R$ 150,05), financiamento, rubrica e a
  competência de CADA linha;
* `rl_procedimento_modalidade.txt` + `tb_modalidade.txt`: ambulatorial,
  hospitalar, hospital dia, atenção domiciliar;
* `tb_financiamento`, `tb_rubrica`, `tb_grupo`, `tb_sub_grupo`,
  `tb_forma_organizacao`: os nomes.

Como os relatórios do próprio SIGTAP: "SA = total ambulatorial" e "total
hospitalar = SH + SP". Valor zero é dado da tabela (procedimento sem valor
unitário, ex.: atividade educativa), não recusa: a consulta o diz.

Conferências, porque o canal é FTP sem criptografia: o leiaute embutido no
ZIP tem de ser o esperado (coluna, tamanho, início e fim), TODA linha tem de
trazer a competência do nome do arquivo, cada código é único e numérico, e o
SHA-256 e a versão do nome ficam gravados.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Protocol

from . import arquivos
from . import evidencia as ev

FONTE_ID = "sigtap"
NOME = "SIGTAP — Tabela Unificada de Procedimentos do SUS (DATASUS)"
VERSAO_PARSER = "sigtap-2026-11-24.1"
URL_PAGINA = "https://wiki.datasus.gov.br/sigtap/index.php/Download"
HOST_FTP = "ftp2.datasus.gov.br"
PASTA_FTP = "/pub/sistemas/tup/downloads/"
NATUREZA = "remuneracao_sus"
ROTULO_NATUREZA = ("remuneração da Tabela Unificada do SUS (SIGTAP), não preço "
                   "de compra")
CODIFICACAO = "latin-1"
CENTAVOS = Decimal("0.01")
PISO_DE_REDUCAO = Decimal("0.5")
LOTE = 1000
MAX_ENTRADAS_ZIP = 150
PUBLICADO, RECUSADO, IMPORTANDO = "publicado", "recusado", "importando"

_NOME_DO_ARQUIVO = re.compile(r"^TabelaUnificada_(\d{4})(\d{2})_v(\d{10})\.zip$")
_CODIGO = re.compile(r"^\d{10}$")

# O leiaute que este leitor sabe ler, tabela a tabela: (coluna, início, fim).
# É conferido contra o `*_layout.txt` do próprio ZIP antes de qualquer linha.
LEIAUTES: dict[str, tuple[tuple[str, int, int], ...]] = {
    "tb_procedimento": (
        ("CO_PROCEDIMENTO", 1, 10), ("NO_PROCEDIMENTO", 11, 260),
        ("TP_COMPLEXIDADE", 261, 261), ("TP_SEXO", 262, 262),
        ("QT_MAXIMA_EXECUCAO", 263, 266), ("QT_DIAS_PERMANENCIA", 267, 270),
        ("QT_PONTOS", 271, 274), ("VL_IDADE_MINIMA", 275, 278),
        ("VL_IDADE_MAXIMA", 279, 282), ("VL_SH", 283, 294),
        ("VL_SA", 295, 306), ("VL_SP", 307, 318),
        ("CO_FINANCIAMENTO", 319, 320), ("CO_RUBRICA", 321, 326),
        ("QT_TEMPO_PERMANENCIA", 327, 330), ("DT_COMPETENCIA", 331, 336)),
    "rl_procedimento_modalidade": (
        ("CO_PROCEDIMENTO", 1, 10), ("CO_MODALIDADE", 11, 12),
        ("DT_COMPETENCIA", 13, 18)),
    "tb_modalidade": (("CO_MODALIDADE", 1, 2), ("NO_MODALIDADE", 3, 102),
                      ("DT_COMPETENCIA", 103, 108)),
    "tb_financiamento": (("CO_FINANCIAMENTO", 1, 2), ("NO_FINANCIAMENTO", 3, 102),
                         ("DT_COMPETENCIA", 103, 108)),
    "tb_rubrica": (("CO_RUBRICA", 1, 6), ("NO_RUBRICA", 7, 106),
                   ("DT_COMPETENCIA", 107, 112)),
    "tb_grupo": (("CO_GRUPO", 1, 2), ("NO_GRUPO", 3, 102),
                 ("DT_COMPETENCIA", 103, 108)),
    "tb_sub_grupo": (("CO_GRUPO", 1, 2), ("CO_SUB_GRUPO", 3, 4),
                     ("NO_SUB_GRUPO", 5, 104), ("DT_COMPETENCIA", 105, 110)),
    "tb_forma_organizacao": (
        ("CO_GRUPO", 1, 2), ("CO_SUB_GRUPO", 3, 4),
        ("CO_FORMA_ORGANIZACAO", 5, 6), ("NO_FORMA_ORGANIZACAO", 7, 106),
        ("DT_COMPETENCIA", 107, 112)),
}

SEM_COMPETENCIA = "COMPETENCIA_DA_LINHA_DIFERENTE_DO_ARQUIVO"
CODIGO_INVALIDO = "CODIGO_DE_PROCEDIMENTO_INVALIDO"
CODIGO_REPETIDO = "CODIGO_REPETIDO"
VALOR_ILEGIVEL = "VALOR_ILEGIVEL"
SEM_NOME = ev.SEM_DESCRICAO


class ArquivoInvalido(ValueError):
    """O ZIP não é a publicação esperada — não é lido adiante."""


def competencia_valida(texto: str) -> tuple[int, int]:
    achado = re.fullmatch(r"(\d{4})-(\d{2})", str(texto or "").strip())
    if not achado or not 1 <= int(achado.group(2)) <= 12 or \
            not 2000 <= int(achado.group(1)) <= 2100:
        raise ValueError("competência no formato AAAA-MM")
    return int(achado.group(1)), int(achado.group(2))


def nome_do_arquivo(nome: str) -> tuple[str, str]:
    """'TabelaUnificada_202611_v2611051737.zip' → ('2026-11', '2611051737')."""
    achado = _NOME_DO_ARQUIVO.fullmatch(Path(str(nome)).name)
    if not achado:
        raise ArquivoInvalido("o arquivo não tem o nome da publicação do "
                              "DATASUS (TabelaUnificada_AAAAMM_vNNNNNNNNNN.zip)")
    competencia = f"{achado.group(1)}-{achado.group(2)}"
    competencia_valida(competencia)
    return competencia, achado.group(3)


def url_do_arquivo(nome: str) -> str:
    """Endereço oficial do arquivo — o nome é conferido, nunca copiado solto."""
    nome_do_arquivo(nome)
    return f"ftp://{HOST_FTP}{PASTA_FTP}{Path(nome).name}"


def _texto(valor: str) -> str:
    return " ".join(str(valor or "").split())


def _centavos(bruto: str) -> Decimal | None:
    bruto = bruto.strip()
    if not bruto.isdigit():
        return None
    return (Decimal(int(bruto)) * CENTAVOS).quantize(CENTAVOS)


def _conferir_leiaute(z: zipfile.ZipFile, tabela: str) -> None:
    try:
        texto = z.read(f"{tabela}_layout.txt").decode(CODIFICACAO)
    except KeyError:
        raise ArquivoInvalido(f"o ZIP não traz o leiaute de {tabela}") from None
    linhas = [l.split(",") for l in texto.splitlines()[1:] if l.strip()]
    achado = tuple((c[0].strip(), int(c[2]), int(c[3])) for c in linhas)
    if achado != LEIAUTES[tabela]:
        raise ArquivoInvalido(f"o leiaute de {tabela} mudou: {achado}")


def _linhas(z: zipfile.ZipFile, tabela: str) -> list[str]:
    try:
        return z.read(f"{tabela}.txt").decode(CODIFICACAO).splitlines()
    except KeyError:
        raise ArquivoInvalido(f"o ZIP não traz {tabela}.txt") from None


def _campo(linha: str, inicio: int, fim: int) -> str:
    return linha[inicio - 1:fim]


def _nomes(z: zipfile.ZipFile, tabela: str, tamanho_codigo: int,
           fim_nome: int) -> dict[str, str]:
    return {l[:tamanho_codigo]: _texto(l[tamanho_codigo:fim_nome])
            for l in _linhas(z, tabela) if l.strip()}


@dataclass
class Procedimento:
    competencia: str
    codigo: str
    nome: str
    complexidade: str
    sexo: str
    valor_sa: Decimal
    valor_sh: Decimal
    valor_sp: Decimal
    financiamento: str
    rubrica: str
    modalidades: tuple[str, ...]
    grupo: str
    subgrupo: str
    forma_organizacao: str
    linha: int                 # linha de tb_procedimento.txt (1 = primeira)

    @property
    def total_ambulatorial(self) -> Decimal:
        return self.valor_sa

    @property
    def total_hospitalar(self) -> Decimal:
        return self.valor_sh + self.valor_sp

    @property
    def chave(self) -> str:
        return f"{self.competencia}:{self.codigo}"


@dataclass
class Leitura:
    competencia: str = ""
    versao_arquivo: str = ""
    linhas: int = 0
    validos: int = 0
    sem_valor: int = 0
    motivos: Counter = field(default_factory=Counter)
    recusadas: list[dict] = field(default_factory=list)


def ler(caminho: Path, competencia: str, *, nome: str | None = None,
        leitura: Leitura | None = None) -> list[Procedimento]:
    """
    Os procedimentos da Tabela Unificada de UMA competência. `nome` é o nome
    oficial do arquivo (quando `caminho` foi salvo com outro nome).
    """
    leitura = leitura if leitura is not None else Leitura()
    do_nome, versao = nome_do_arquivo(nome or caminho.name)
    if do_nome != competencia:
        raise ArquivoInvalido(f"o arquivo é da competência {do_nome}, "
                              f"esperada {competencia}")
    ano, mes = competencia_valida(competencia)
    aaaamm = f"{ano}{mes:02d}"
    leitura.competencia, leitura.versao_arquivo = competencia, versao
    # 87 entradas em 11/2026: tabelas e leiautes (.txt), LEIA_ME.TXT,
    # `versao` (sem extensão), `config.inf` ("Version=1.0.0") e o leiaute em
    # .xls. Nada disso é executado; o teto continua, mais folgado
    arquivos.conferir_zip(caminho, extensoes=frozenset({".txt", ".xls", ".inf", ""}),
                          max_entradas=MAX_ENTRADAS_ZIP)
    with zipfile.ZipFile(caminho) as z:
        for tabela in LEIAUTES:
            _conferir_leiaute(z, tabela)
        modalidade = _nomes(z, "tb_modalidade", 2, 102)
        financiamento = _nomes(z, "tb_financiamento", 2, 102)
        rubrica = _nomes(z, "tb_rubrica", 6, 106)
        grupo = _nomes(z, "tb_grupo", 2, 102)
        subgrupo = _nomes(z, "tb_sub_grupo", 4, 104)
        forma = _nomes(z, "tb_forma_organizacao", 6, 106)
        modalidades: dict[str, list[str]] = {}
        for l in _linhas(z, "rl_procedimento_modalidade"):
            if l.strip() and l[12:18] == aaaamm:
                modalidades.setdefault(l[:10], []).append(
                    modalidade.get(l[10:12], l[10:12]))
        vistos: set[str] = set()
        saida: list[Procedimento] = []
        for numero, l in enumerate(_linhas(z, "tb_procedimento"), start=1):
            if not l.strip():
                continue
            leitura.linhas += 1
            codigo = _campo(l, 1, 10)
            motivo = ""
            sa, sh, sp = (_centavos(_campo(l, 295, 306)),
                          _centavos(_campo(l, 283, 294)),
                          _centavos(_campo(l, 307, 318)))
            if _campo(l, 331, 336) != aaaamm:
                motivo = SEM_COMPETENCIA
            elif not _CODIGO.fullmatch(codigo):
                motivo = CODIGO_INVALIDO
            elif codigo in vistos:
                motivo = CODIGO_REPETIDO
            elif not _texto(_campo(l, 11, 260)):
                motivo = SEM_NOME
            elif None in (sa, sh, sp):
                motivo = VALOR_ILEGIVEL
            if motivo:
                leitura.motivos[motivo] += 1
                leitura.recusadas.append({"linha": numero, "codigo": codigo,
                                          "motivo": motivo})
                continue
            vistos.add(codigo)
            p = Procedimento(
                competencia=competencia, codigo=codigo,
                nome=_texto(_campo(l, 11, 260)),
                complexidade=_campo(l, 261, 261).strip(),
                sexo=_campo(l, 262, 262).strip(), valor_sa=sa, valor_sh=sh,
                valor_sp=sp,
                financiamento=financiamento.get(_campo(l, 319, 320),
                                                _campo(l, 319, 320)),
                rubrica=rubrica.get(_campo(l, 321, 326), "").strip(),
                modalidades=tuple(sorted(modalidades.get(codigo, []))),
                grupo=grupo.get(codigo[:2], ""), subgrupo=subgrupo.get(codigo[:4], ""),
                forma_organizacao=forma.get(codigo[:6], ""), linha=numero)
            saida.append(p)
            leitura.validos += 1
            leitura.sem_valor += p.total_ambulatorial == 0 and p.total_hospitalar == 0
    return saida


# ---------------------------------------------------------------------------
# Índice e versões
# ---------------------------------------------------------------------------
def linha_do_indice(p: Procedimento, *, sha256: str, nome_arquivo: str) -> dict:
    from .pncp_indice import texto_de_busca

    bruto = {"codigo": p.codigo, "sa": format(p.valor_sa, "f"),
             "sh": format(p.valor_sh, "f"), "sp": format(p.valor_sp, "f"),
             "linha": p.linha, "competencia": p.competencia}
    return {
        "registro_id": hashlib.sha256(
            f"{sha256}:{p.chave}".encode()).hexdigest()[:40],
        "chave_linha": p.chave, "competencia": p.competencia,
        "codigo": p.codigo, "nome": p.nome, "nome_busca": texto_de_busca(p.nome),
        "complexidade": p.complexidade or None, "sexo": p.sexo or None,
        "valor_sa": format(p.valor_sa, "f"), "valor_sh": format(p.valor_sh, "f"),
        "valor_sp": format(p.valor_sp, "f"),
        "financiamento": p.financiamento or None, "rubrica": p.rubrica or None,
        "modalidades": list(p.modalidades), "grupo": p.grupo or None,
        "subgrupo": p.subgrupo or None,
        "forma_organizacao": p.forma_organizacao or None,
        "linha_arquivo": p.linha, "arquivo_sha256": sha256,
        "arquivo": Path(nome_arquivo).name,
        "hash_linha": ev.hash_da_linha(bruto), "versao_parser": VERSAO_PARSER,
    }


class Armazem(Protocol):
    def versao(self, competencia: str, sha256: str) -> dict | None: ...

    def versao_publicada(self, competencia: str) -> dict | None: ...

    def registrar_versao(self, competencia: str, sha256: str, **campos) -> None: ...

    def gravar_registros(self, linhas: list[dict]) -> None: ...

    def publicar(self, competencia: str, sha256: str, **campos) -> None: ...

    def buscar(self, termos: list[str], **filtros) -> list[dict]: ...


class ArmazemEmMemoria:
    def __init__(self) -> None:
        self.versoes: dict[tuple[str, str], dict] = {}
        self.registros: dict[str, dict] = {}

    def versao(self, competencia, sha256):
        return self.versoes.get((competencia, sha256))

    def versao_publicada(self, competencia):
        for v in self.versoes.values():
            if v["competencia"] == competencia and v["vigente"]:
                return v
        return None

    def registrar_versao(self, competencia, sha256, **campos):
        atual = self.versoes.get((competencia, sha256), {
            "competencia": competencia, "sha256": sha256, "vigente": False})
        self.versoes[(competencia, sha256)] = {**atual, **campos}

    def gravar_registros(self, linhas):
        for linha in linhas:
            self.registros[linha["registro_id"]] = {**linha, "vigente": False}

    def publicar(self, competencia, sha256, **campos):
        for v in self.versoes.values():
            if v["competencia"] == competencia:
                v["vigente"] = False
        for linha in self.registros.values():
            if linha["competencia"] == competencia:
                linha["vigente"] = linha["arquivo_sha256"] == sha256
        self.registrar_versao(competencia, sha256, estado=PUBLICADO,
                              vigente=True, **campos)

    def buscar(self, termos, *, codigo=None, competencia=None, modalidade=None,
               limite=50):
        vigentes = [l for l in self.registros.values() if l["vigente"]]
        alvo = competencia or max((l["competencia"] for l in vigentes),
                                  default=None)
        procurados = set(termos)
        achados = []
        for linha in vigentes:
            if linha["competencia"] != alvo:
                continue
            if modalidade and modalidade not in linha["modalidades"]:
                continue
            if codigo:
                if linha["codigo"] != codigo:
                    continue
                comuns = 0
            else:
                comuns = len(procurados & set(linha["nome_busca"].split()))
                if not comuns:
                    continue
            achados.append((comuns, linha["codigo"], linha))
        achados.sort(key=lambda t: (-t[0], t[1]))
        return [linha for *_, linha in achados[:limite]]


@dataclass
class Importacao:
    competencia: str = ""
    versao_arquivo: str = ""
    sha256: str = ""
    desfecho: str = ""             # publicado | ja_publicado | recusado
    motivo: str = ""
    linhas: int = 0
    validos: int = 0
    sem_valor: int = 0
    recusas: Counter = field(default_factory=Counter)
    validos_na_versao_anterior: int | None = None

    def para_registro(self) -> dict:
        saida = dict(vars(self))
        saida["recusas"] = dict(self.recusas)
        return saida


def importar(armazem: Armazem, caminho: Path, *, competencia: str,
             nome: str | None = None) -> Importacao:
    """
    Importa UMA competência e publica a versão, ou a recusa. Idempotente
    pelo SHA-256; o DATASUS regera o arquivo da mesma competência com outra
    versão no nome (`_v…`): versão nova, publicada inteira, a anterior fica.
    """
    nome = Path(nome or caminho.name).name
    sha = arquivos.sha256_do_arquivo(caminho)
    feito = Importacao(competencia=competencia, sha256=sha)
    feito.versao_arquivo = nome_do_arquivo(nome)[1]
    existente = armazem.versao(competencia, sha)
    if existente and existente.get("estado") == PUBLICADO:
        feito.desfecho = "ja_publicado"
        return feito
    leitura = Leitura()
    procedimentos = ler(caminho, competencia, nome=nome, leitura=leitura)
    feito.linhas, feito.validos = leitura.linhas, leitura.validos
    feito.sem_valor, feito.recusas = leitura.sem_valor, leitura.motivos

    def recusar(motivo: str) -> Importacao:
        feito.desfecho, feito.motivo = RECUSADO, motivo
        armazem.registrar_versao(
            competencia, sha, estado=RECUSADO, arquivo=nome,
            versao_arquivo=feito.versao_arquivo, motivo=motivo,
            linhas=feito.linhas, validos=feito.validos,
            recusas=dict(feito.recusas), versao_parser=VERSAO_PARSER)
        return feito

    if not procedimentos:
        return recusar("nenhum procedimento válido")
    publicada = armazem.versao_publicada(competencia)
    if publicada is not None:
        feito.validos_na_versao_anterior = int(publicada.get("validos") or 0)
        if feito.validos < feito.validos_na_versao_anterior * PISO_DE_REDUCAO:
            return recusar(f"{feito.validos} procedimentos contra "
                           f"{feito.validos_na_versao_anterior} da versão "
                           "publicada — redução acima do tolerado")
    armazem.registrar_versao(
        competencia, sha, estado=IMPORTANDO, arquivo=nome,
        versao_arquivo=feito.versao_arquivo, motivo="", linhas=feito.linhas,
        validos=feito.validos, sem_valor=feito.sem_valor,
        recusas=dict(feito.recusas), recusadas=leitura.recusadas[:200],
        versao_parser=VERSAO_PARSER)
    linhas = [linha_do_indice(p, sha256=sha, nome_arquivo=nome)
              for p in procedimentos]
    for inicio in range(0, len(linhas), LOTE):
        armazem.gravar_registros(linhas[inicio:inicio + LOTE])
    armazem.publicar(competencia, sha, publicado_em=datetime.now(
        timezone.utc).isoformat(timespec="seconds"))
    feito.desfecho = PUBLICADO
    return feito


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
MODALIDADES = ("Ambulatorial", "Hospitalar", "Hospital Dia", "Atenção Domiciliar")


def consultar(buscar: Callable[..., list], *, termo: str = "",
              codigo: str | None = None, competencia: str | None = None,
              modalidade: str | None = None, limite: int = 50) -> list[dict]:
    from .compras_gov import _tokens
    from .pncp_indice import texto_de_busca

    codigo = re.sub(r"\D", "", str(codigo or "")) or None
    if codigo is not None and not _CODIGO.fullmatch(codigo):
        raise ValueError("código de procedimento do SIGTAP tem 10 dígitos")
    if competencia is not None:
        competencia_valida(competencia)
    if modalidade is not None and modalidade not in MODALIDADES:
        raise ValueError("modalidade desconhecida")
    termos = sorted({p.lower() for p in _tokens(texto_de_busca(termo))
                     if p.isalnum()}, key=lambda p: (-len(p), p))[:12]
    if not termos and codigo is None:
        return []
    linhas = buscar(termos if codigo is None else [], codigo=codigo,
                    competencia=competencia, modalidade=modalidade,
                    limite=max(1, min(int(limite), 200)))
    saida = []
    for linha in linhas or []:
        # linha que não se descreve (arquivo fora do nome oficial, valor
        # negativo ou ilegível) não chega à tela: rastreabilidade é condição
        try:
            saida.append(descrever(linha))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
    return saida


def descrever(linha: dict) -> dict:
    ano, mes = competencia_valida(linha["competencia"])
    sa, sh, sp = (Decimal(str(linha[k])) for k in ("valor_sa", "valor_sh", "valor_sp"))
    if any(not v.is_finite() or v < 0 for v in (sa, sh, sp)):
        raise ValueError("valor de remuneração fora da regra")
    codigo = str(linha["codigo"])
    if not _CODIGO.fullmatch(codigo):
        raise ValueError("código de procedimento do SIGTAP tem 10 dígitos")
    return {
        **{k: linha.get(k) for k in (
            "registro_id", "chave_linha", "competencia", "codigo", "nome",
            "complexidade", "sexo", "financiamento", "rubrica", "grupo",
            "subgrupo", "forma_organizacao", "linha_arquivo",
            "arquivo_sha256", "arquivo", "versao_parser")},
        "codigo_formatado": f"{codigo[:2]}.{codigo[2:4]}.{codigo[4:6]}."
                            f"{codigo[6:9]}-{codigo[9]}",
        "modalidades": list(linha.get("modalidades") or []),
        "valor_sa": format(sa, "f"), "valor_sh": format(sh, "f"),
        "valor_sp": format(sp, "f"),
        "total_ambulatorial": format(sa, "f"),
        "total_hospitalar": format(sh + sp, "f"),
        "sem_valor": sa == 0 and sh == 0 and sp == 0,
        "competencia_exibicao": f"{mes:02d}/{ano}",
        "natureza": NATUREZA, "rotulo_natureza": ROTULO_NATUREZA,
        "fonte": NOME, "url_fonte": URL_PAGINA,
        "url_arquivo": url_do_arquivo(linha["arquivo"]),
    }
