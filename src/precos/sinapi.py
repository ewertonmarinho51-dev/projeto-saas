"""
SINAPI (CAIXA / IBGE) — referência de CUSTO de engenharia, em consulta própria.

O SINAPI não é preço de compra e NÃO entra na cesta da pesquisa de preços.
É o sistema que a Lei 14.133 (art. 23, § 2º, I) manda usar como parâmetro
de custo de obras e serviços de engenharia: preço mediano de INSUMO e custo
de COMPOSIÇÃO, por UF e competência, com e sem desoneração da folha. Por
isso mora numa consulta separada (`ConsultaSINAPI`), com a natureza do valor
escrita em cada linha: "custo referencial", nunca "preço praticado".

Leiaute conferido no arquivo oficial de 10/2026 (`SINAPI-2026-10-formato-xlsx.zip`,
publicado em 12/11/2026, 16.083.991 bytes, sha256 2e99cde7…): dentro do ZIP,
`SINAPI_Referência_2026_10.xlsx` com as abas

    ISD / ICD / ISE  insumos — sem desoneração / com desoneração / sem encargos
    CSD / CCD / CSE  composições — idem

Em todas, a linha 3 traz "Mês de Referência:" (`10/2026`), a 4 a data de
emissão, a 2 o título com o regime, e a 10 o cabeçalho. Insumos: Classificação,
Código, Descrição, Unidade, Origem de Preço (C = coletado, CR = coeficiente
de representatividade) e uma coluna por UF. Composições: Grupo, Código,
Descrição, Unidade e um par (Custo, %AS) por UF, com a UF na linha 9 — %AS é
a parcela do custo calculada com preço de São Paulo por falta de preço na UF.

Duas armadilhas do arquivo, e o que se faz com elas:

* o código da COMPOSIÇÃO é uma fórmula `=HYPERLINK(...,104658)` sem valor
  em cache (lido como 0 em modo valor): o código sai da própria fórmula;
* preço EM BRANCO (insumo sem coleta mínima na UF) e custo ZERADO (composição
  com algum item sem custo — a planilha diz "Custo zerado (hífen) indica que
  pelo menos um dos itens da composição não tem custo/preço") NÃO são
  referência: são recusados e contados. A CAIXA já publicou competência com
  preço zerado depois corrigido — a retificação é outro arquivo, outro
  SHA-256, e entra como VERSÃO NOVA da mesma competência.

Piloto: Pará. A importação recebe as UFs (`ufs`) e grava só elas.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterator, Protocol

from . import arquivos
from . import evidencia as ev

VERSAO_PARSER = "sinapi-2026-11-23.1"
URL_BASE = "https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/"
URL_PAGINA = ("https://www.caixa.gov.br/poder-publico/modernizacao-gestao/"
              "sinapi/Paginas/default.aspx")
NATUREZA = "custo_referencial"
UFS_PILOTO = ("PA",)

INSUMO, COMPOSICAO = "insumo", "composicao"
SEM_DESONERACAO, COM_DESONERACAO, SEM_ENCARGOS = (
    "sem_desoneracao", "com_desoneracao", "sem_encargos")
# aba → (tipo, regime, trecho obrigatório no título da linha 2)
ABAS = {
    "ISD": (INSUMO, SEM_DESONERACAO, "SEM DESONERA"),
    "ICD": (INSUMO, COM_DESONERACAO, "COM DESONERA"),
    "ISE": (INSUMO, SEM_ENCARGOS, "SEM ENCARGOS"),
    "CSD": (COMPOSICAO, SEM_DESONERACAO, "SEM DESONERA"),
    "CCD": (COMPOSICAO, COM_DESONERACAO, "COM DESONERA"),
    "CSE": (COMPOSICAO, SEM_ENCARGOS, "SEM ENCARGOS"),
}
ROTULO_REGIME = {SEM_DESONERACAO: "encargos sociais sem desoneração",
                 COM_DESONERACAO: "encargos sociais com desoneração",
                 SEM_ENCARGOS: "sem encargos sociais"}
UFS = ("AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
       "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
       "SE", "SP", "TO")
LINHA_CABECALHO = 10

SEM_PRECO = "SEM_PRECO_NA_UF"          # em branco: sem coleta mínima
PRECO_ZERADO = "PRECO_ZERADO"          # composição com item sem custo
SEM_CODIGO = "SEM_CODIGO"
VALOR_ILEGIVEL = "VALOR_ILEGIVEL"

PISO_DE_REDUCAO = Decimal("0.5")
# Medido em produção (24/11/2026): 1.000 e 250 linhas por upsert passaram dos
# 8 s de `statement_timeout` do PostgREST; 250 linhas sintéticas levaram 2,7 s
# (~10 ms por linha, com tsvector gerado e índice GIN). 50 cabe com folga.
LOTE = 50
IMPORTANDO, PUBLICADO, RECUSADO = "importando", "publicado", "recusado"

_CODIGO_NA_FORMULA = re.compile(r",\s*(\d{1,9})\s*\)\s*$")
_COMPETENCIA = re.compile(r"^(0[1-9]|1[0-2])/(\d{4})$")


class LeiauteInesperado(ValueError):
    """O arquivo não tem a forma conferida — nada é importado."""


# ---------------------------------------------------------------------------
# Endereço oficial
# ---------------------------------------------------------------------------
def url_da_competencia(competencia: str) -> str:
    """`2026-10` → o ZIP oficial do mês, montado só com dígitos."""
    ano, mes = _partes(competencia)
    return f"{URL_BASE}SINAPI-{ano:04d}-{mes:02d}-formato-xlsx.zip"


def _partes(competencia: str) -> tuple[int, int]:
    achado = re.fullmatch(r"(\d{4})-(\d{2})", str(competencia or ""))
    if not achado or not 1 <= int(achado.group(2)) <= 12:
        raise ValueError("competência no formato AAAA-MM")
    return int(achado.group(1)), int(achado.group(2))


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
@dataclass
class Leitura:
    competencia: str = ""
    data_emissao: str = ""
    linhas: int = 0                       # pares (linha da planilha × UF) lidos
    validas: int = 0
    recusadas: Counter = field(default_factory=Counter)
    por_aba: Counter = field(default_factory=Counter)


def _decimal(valor) -> Decimal | None:
    """Célula → `Decimal`. O XLSX guarda o número como texto ("302.08"); o
    openpyxl o entrega como float, e `str(float)` devolve o texto mais curto
    que reproduz o mesmo valor — o que a planilha escreveu."""
    if valor is None or valor == "" or valor == "-":
        return None
    if isinstance(valor, bool):
        raise InvalidOperation
    if isinstance(valor, (int, Decimal)):
        return Decimal(valor)
    if isinstance(valor, float):
        return Decimal(str(valor))
    texto = str(valor).strip()
    if texto in ("", "-"):
        return None
    return Decimal(texto.replace(".", "").replace(",", ".")
                   if "," in texto else texto)


def _codigo(celula) -> str | None:
    if isinstance(celula, int) and not isinstance(celula, bool) and celula > 0:
        return str(celula)
    if isinstance(celula, float) and celula.is_integer() and celula > 0:
        return str(int(celula))
    texto = str(celula or "").strip()
    if texto.isdigit() and int(texto) > 0:
        return str(int(texto))
    achado = _CODIGO_NA_FORMULA.search(texto)
    return str(int(achado.group(1))) if achado else None


def _texto(celula) -> str:
    return " ".join(str(celula or "").split())


def _competencia_da_aba(linhas: list[tuple]) -> tuple[str, str]:
    mes_ano = _texto(linhas[2][1] if len(linhas[2]) > 1 else "")
    achado = _COMPETENCIA.match(mes_ano)
    if not achado or not _texto(linhas[2][0]).startswith("Mês de Referência"):
        raise LeiauteInesperado(f"mês de referência ilegível: {mes_ano!r}")
    emissao = _texto(linhas[3][1] if len(linhas[3]) > 1 else "")
    try:
        emissao_iso = datetime.strptime(emissao, "%d/%m/%Y").date().isoformat()
    except ValueError:
        emissao_iso = ""
    return f"{achado.group(2)}-{achado.group(1)}", emissao_iso


def _colunas_das_ufs(tipo: str, cabecalho: tuple, linha_uf: tuple) -> dict[str, int]:
    """UF → coluna do valor. Insumo: a própria linha 10; composição: a 9,
    com o par (Custo, %AS) logo abaixo."""
    if tipo == INSUMO:
        mapa = {str(c).strip(): i for i, c in enumerate(cabecalho)
                if str(c or "").strip() in UFS}
    else:
        mapa = {str(c).strip(): i for i, c in enumerate(linha_uf)
                if str(c or "").strip() in UFS
                and _texto(cabecalho[i]).startswith("Custo")}
    if sorted(mapa) != sorted(UFS):
        raise LeiauteInesperado(
            f"esperadas as 27 UFs no cabeçalho; vieram {sorted(mapa)}")
    return mapa


def _conferir_cabecalho(tipo: str, cabecalho: tuple) -> None:
    esperado = (("Classificação", "Código do Insumo", "Descrição do Insumo",
                 "Unidade", "Origem de Preço") if tipo == INSUMO else
                ("Grupo", "Código da Composição", "Descrição", "Unidade"))
    lido = tuple(_texto(c) for c in cabecalho[:len(esperado)])
    if lido != esperado:
        raise LeiauteInesperado(f"cabeçalho mudou: {lido}")


def ler(caminho: Path, *, ufs=UFS_PILOTO, competencia: str | None = None,
        leitura: Leitura | None = None) -> Iterator[dict]:
    """
    As linhas VÁLIDAS do arquivo oficial, uma por (aba × código × UF).

    Confere antes de devolver qualquer coisa: ZIP seguro, uma planilha de
    referência, as seis abas, título com o regime de cada uma, cabeçalho,
    as 27 UFs e a MESMA competência em todas (e igual à pedida, se veio).
    """
    import openpyxl

    leitura = leitura if leitura is not None else Leitura()
    ufs = tuple(sorted({str(u).upper() for u in ufs}))
    if not ufs or any(u not in UFS for u in ufs):
        raise ValueError(f"UF desconhecida em {ufs}")
    arquivos.conferir_zip(caminho, extensoes=frozenset({".xlsx"}))
    with zipfile.ZipFile(caminho) as z:
        nomes = [n for n in z.namelist()
                 if n.lower().endswith(".xlsx") and "refer" in n.lower()]
        if len(nomes) != 1:
            raise LeiauteInesperado(
                f"esperada uma planilha de referência no ZIP; há {nomes}")
        conteudo = z.read(nomes[0])
    livro = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True,
                                   data_only=False)
    faltam = [a for a in ABAS if a not in livro.sheetnames]
    if faltam:
        raise LeiauteInesperado(f"faltam as abas {faltam}")
    for aba, (tipo, regime, titulo) in ABAS.items():
        planilha = livro[aba]
        topo = list(planilha.iter_rows(min_row=1, max_row=LINHA_CABECALHO,
                                       values_only=True))
        if titulo not in _texto(topo[1][0]).upper():
            raise LeiauteInesperado(
                f"a aba {aba} não é '{titulo}': {_texto(topo[1][0])!r}")
        da_aba, emissao = _competencia_da_aba(topo)
        if leitura.competencia and da_aba != leitura.competencia:
            raise LeiauteInesperado(
                f"competências diferentes no arquivo: {leitura.competencia} "
                f"e {da_aba} (aba {aba})")
        if competencia and da_aba != competencia:
            raise LeiauteInesperado(
                f"o arquivo é da competência {da_aba}, não de {competencia}")
        leitura.competencia, leitura.data_emissao = da_aba, emissao
        cabecalho, linha_uf = topo[LINHA_CABECALHO - 1], topo[LINHA_CABECALHO - 2]
        _conferir_cabecalho(tipo, cabecalho)
        colunas = _colunas_das_ufs(tipo, cabecalho, linha_uf)
        for numero, linha in enumerate(planilha.iter_rows(
                min_row=LINHA_CABECALHO + 1, values_only=True),
                start=LINHA_CABECALHO + 1):
            descricao = _texto(linha[2] if len(linha) > 2 else "")
            if not descricao:
                continue
            codigo = _codigo(linha[1])
            for uf in ufs:
                leitura.linhas += 1
                if codigo is None:
                    leitura.recusadas[SEM_CODIGO] += 1
                    continue
                coluna = colunas[uf]
                try:
                    valor = _decimal(linha[coluna] if coluna < len(linha) else None)
                except (InvalidOperation, ValueError):
                    leitura.recusadas[VALOR_ILEGIVEL] += 1
                    continue
                if valor is None:
                    leitura.recusadas[SEM_PRECO] += 1
                    continue
                if valor <= 0:
                    leitura.recusadas[PRECO_ZERADO] += 1
                    continue
                extra = {}
                if tipo == INSUMO:
                    extra["classificacao"] = _texto(linha[0]) or None
                    extra["origem_preco"] = _texto(linha[4]) or None
                else:
                    extra["classificacao"] = _texto(linha[0]) or None
                    try:
                        extra["percentual_sp"] = _decimal(
                            linha[coluna + 1] if coluna + 1 < len(linha) else None)
                    except (InvalidOperation, ValueError):
                        extra["percentual_sp"] = None
                leitura.validas += 1
                leitura.por_aba[aba] += 1
                yield {"aba": aba, "tipo": tipo, "regime": regime,
                       "codigo": codigo, "descricao": descricao,
                       "unidade": _texto(linha[3]) or None, "uf": uf,
                       "valor": valor, "linha_planilha": numero, **extra}


# ---------------------------------------------------------------------------
# Índice
# ---------------------------------------------------------------------------
def chave_da_linha(competencia: str, tipo: str, codigo: str, uf: str,
                   regime: str) -> str:
    """Identidade da referência — a mesma em qualquer versão do arquivo."""
    return f"sinapi:{competencia}:{tipo}:{codigo}:{uf}:{regime}"


def linha_do_indice(bruta: dict, *, competencia: str, sha256: str,
                    url: str) -> dict:
    from .pncp_indice import texto_de_busca

    percentual = bruta.get("percentual_sp")
    corpo = {k: (format(v, "f") if isinstance(v, Decimal) else v)
             for k, v in bruta.items()}
    return {
        "registro_id": chave_da_linha(competencia, bruta["tipo"],
                                      bruta["codigo"], bruta["uf"],
                                      bruta["regime"]),
        "competencia": competencia, "arquivo_sha256": sha256,
        "tipo": bruta["tipo"], "regime": bruta["regime"],
        "codigo": bruta["codigo"], "descricao": bruta["descricao"],
        "descricao_busca": texto_de_busca(bruta["descricao"]),
        "unidade": bruta["unidade"], "uf": bruta["uf"],
        "valor": format(bruta["valor"], "f"),
        "classificacao": bruta.get("classificacao"),
        "origem_preco": bruta.get("origem_preco"),
        "percentual_sp": None if percentual is None else format(percentual, "f"),
        "aba": bruta["aba"], "linha_planilha": bruta["linha_planilha"],
        "url_arquivo": url, "hash_linha": ev.hash_da_linha(corpo),
        "versao_parser": VERSAO_PARSER,
    }


class Armazem(Protocol):
    def versao(self, competencia: str, sha256: str) -> dict | None: ...

    def versao_publicada(self, competencia: str) -> dict | None: ...

    def registrar_versao(self, competencia: str, sha256: str, **campos) -> None: ...

    def gravar_registros(self, linhas: list[dict]) -> None: ...

    def publicar(self, competencia: str, sha256: str, **campos) -> None: ...

    def buscar(self, termos: list[str], **filtros) -> list[dict]: ...


class ArmazemEmMemoria:
    """O contrato do banco, em memória — provas e medição de bancada."""

    def __init__(self) -> None:
        self.versoes: dict[tuple[str, str], dict] = {}
        self.registros: dict[str, dict] = {}

    def versao(self, competencia, sha256):
        return self.versoes.get((competencia, sha256))

    def versao_publicada(self, competencia):
        for v in self.versoes.values():
            if v["competencia"] == competencia and v.get("vigente"):
                return v
        return None

    def registrar_versao(self, competencia, sha256, **campos):
        atual = self.versoes.get((competencia, sha256), {
            "competencia": competencia, "sha256": sha256, "vigente": False})
        self.versoes[(competencia, sha256)] = {**atual, **campos}

    def gravar_registros(self, linhas):
        for linha in linhas:
            # como no banco: linha nova nasce invisível; a que já existia
            # mantém o `vigente` até a publicação
            atual = self.registros.get(linha["registro_id"])
            self.registros[linha["registro_id"]] = {
                **linha, "vigente": bool(atual and atual.get("vigente"))}

    def publicar(self, competencia, sha256, **campos):
        for linha in self.registros.values():
            if linha["competencia"] == competencia:
                linha["vigente"] = linha["arquivo_sha256"] == sha256
        for v in self.versoes.values():
            if v["competencia"] == competencia:
                v["vigente"] = False
        self.registrar_versao(competencia, sha256, estado=PUBLICADO,
                              vigente=True, **campos)

    def buscar(self, termos, *, codigo=None, uf=None, competencia=None,
               regime=None, tipo=None, limite=50):
        vigentes = [l for l in self.registros.values() if l.get("vigente")]
        if competencia is None:
            competencias = [l["competencia"] for l in vigentes
                            if (uf is None or l["uf"] == uf.upper())]
            competencia = max(competencias, default=None)
        procurados = set(termos)
        achados = []
        for linha in vigentes:
            if linha["competencia"] != competencia:
                continue
            if uf and linha["uf"] != uf.upper():
                continue
            if regime and linha["regime"] != regime:
                continue
            if tipo and linha["tipo"] != tipo:
                continue
            if codigo:
                if linha["codigo"] != str(codigo):
                    continue
                comuns = 0
            else:
                comuns = len(procurados & set(
                    str(linha["descricao_busca"]).replace(",", " ").split()))
                if not comuns:
                    continue
            achados.append((comuns, linha["registro_id"], linha))
        achados.sort(key=lambda t: (-t[0], t[1]))
        return [linha for *_, linha in achados[:limite]]


@dataclass
class Importacao:
    competencia: str = ""
    sha256: str = ""
    data_emissao: str = ""
    ufs: tuple = ()
    desfecho: str = ""            # publicado | ja_publicado | recusado
    motivo: str = ""
    linhas: int = 0
    validas: int = 0
    recusadas: Counter = field(default_factory=Counter)
    por_aba: Counter = field(default_factory=Counter)
    validas_na_versao_anterior: int | None = None

    def para_registro(self) -> dict:
        saida = dict(vars(self))
        saida["recusadas"] = dict(self.recusadas)
        saida["por_aba"] = dict(self.por_aba)
        saida["ufs"] = list(self.ufs)
        return saida


def importar(armazem: Armazem, caminho: Path, *, url: str, ufs=UFS_PILOTO,
             competencia: str | None = None) -> Importacao:
    """
    Importa UM arquivo mensal oficial e publica a versão, ou a recusa.

    Idempotente: o mesmo arquivo (mesmo SHA-256) já publicado não é relido.
    Retificação da mesma competência é outro SHA: vira versão nova, gravada
    invisível e publicada inteira — a busca nunca vê metade de uma versão.
    Arquivo com menos da metade das referências válidas da versão publicada
    da mesma competência é recusado (o sinal do arquivo zerado ou truncado),
    e a anterior continua valendo.
    """
    if not arquivos.url_permitida(url) or not url.startswith(URL_BASE):
        raise ValueError("o arquivo do SINAPI só é aceito do endereço oficial")
    sha = arquivos.sha256_do_arquivo(caminho)
    leitura = Leitura()
    linhas: list[dict] = []
    feito = Importacao(sha256=sha, ufs=tuple(sorted({u.upper() for u in ufs})))
    for bruta in ler(caminho, ufs=ufs, competencia=competencia,
                     leitura=leitura):
        linhas.append(bruta)
    feito.competencia, feito.data_emissao = leitura.competencia, leitura.data_emissao
    feito.linhas, feito.validas = leitura.linhas, leitura.validas
    feito.recusadas, feito.por_aba = leitura.recusadas, leitura.por_aba
    if url != url_da_competencia(feito.competencia):
        raise ValueError(f"o arquivo é da competência {feito.competencia}, "
                         f"mas veio de {url}")
    if not linhas:
        feito.desfecho, feito.motivo = RECUSADO, "arquivo sem referência válida"
        return feito
    existente = armazem.versao(feito.competencia, sha)
    if existente and existente.get("estado") == PUBLICADO:
        feito.desfecho = "ja_publicado"
        return feito
    comum = dict(url=url, data_emissao=feito.data_emissao or None,
                 linhas=feito.linhas, validas=feito.validas,
                 recusadas=dict(feito.recusadas), ufs=list(feito.ufs),
                 versao_parser=VERSAO_PARSER)
    publicada = armazem.versao_publicada(feito.competencia)
    if publicada is not None:
        feito.validas_na_versao_anterior = int(publicada.get("validas") or 0)
        if feito.validas < feito.validas_na_versao_anterior * PISO_DE_REDUCAO:
            feito.desfecho, feito.motivo = RECUSADO, (
                f"{feito.validas} referências válidas contra "
                f"{feito.validas_na_versao_anterior} da versão publicada — "
                "redução acima do tolerado; a versão anterior continua valendo")
            armazem.registrar_versao(feito.competencia, sha, estado=RECUSADO,
                                     motivo=feito.motivo, **comum)
            return feito
    armazem.registrar_versao(feito.competencia, sha, estado=IMPORTANDO,
                             motivo="", **comum)
    convertidas = [linha_do_indice(b, competencia=feito.competencia,
                                   sha256=sha, url=url) for b in linhas]
    for inicio in range(0, len(convertidas), LOTE):
        armazem.gravar_registros(convertidas[inicio:inicio + LOTE])
    armazem.publicar(feito.competencia, sha, publicado_em=datetime.now(
        timezone.utc).isoformat(timespec="seconds"))
    feito.desfecho = PUBLICADO
    return feito


# ---------------------------------------------------------------------------
# Consulta própria — só lê o índice
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReferenciaDeCusto:
    """Uma linha do SINAPI como ela vai para a tela e para o relatório."""

    registro_id: str
    tipo: str                     # insumo | composicao
    codigo: str
    descricao: str
    unidade: str | None
    uf: str
    competencia: str              # AAAA-MM
    regime: str
    valor: Decimal
    classificacao: str | None
    origem_preco: str | None      # C | CR (insumo)
    percentual_sp: Decimal | None  # %AS (composição)
    aba: str
    linha_planilha: int
    url_arquivo: str
    arquivo_sha256: str
    natureza: str = NATUREZA

    @property
    def rotulo_regime(self) -> str:
        return ROTULO_REGIME.get(self.regime, self.regime)

    @property
    def identificacao(self) -> str:
        tipo = "Insumo" if self.tipo == INSUMO else "Composição"
        return f"SINAPI {tipo} {self.codigo} — {self.uf} {self.competencia[5:]}/{self.competencia[:4]}"


def referencia_da_linha(linha: dict) -> ReferenciaDeCusto | None:
    try:
        valor = Decimal(str(linha.get("valor")))
    except (InvalidOperation, ValueError):
        return None
    if valor <= 0 or not linha.get("registro_id"):
        return None
    if not str(linha.get("url_arquivo") or "").startswith(URL_BASE):
        return None
    percentual = linha.get("percentual_sp")
    try:
        percentual = None if percentual in (None, "") else Decimal(str(percentual))
    except (InvalidOperation, ValueError):
        percentual = None
    return ReferenciaDeCusto(
        registro_id=str(linha["registro_id"]), tipo=str(linha.get("tipo")),
        codigo=str(linha.get("codigo")), descricao=str(linha.get("descricao") or ""),
        unidade=linha.get("unidade"), uf=str(linha.get("uf")),
        competencia=str(linha.get("competencia")), regime=str(linha.get("regime")),
        valor=valor, classificacao=linha.get("classificacao"),
        origem_preco=linha.get("origem_preco"), percentual_sp=percentual,
        aba=str(linha.get("aba")), linha_planilha=int(linha.get("linha_planilha") or 0),
        url_arquivo=str(linha["url_arquivo"]),
        arquivo_sha256=str(linha.get("arquivo_sha256") or ""))


Buscador = Callable[..., list]


@dataclass
class ResultadoConsulta:
    referencias: list[ReferenciaDeCusto] = field(default_factory=list)
    competencia: str | None = None
    falha: str | None = None


class ConsultaSINAPI:
    """Custo referencial de engenharia — por código ou por termos."""

    def __init__(self, buscar: Buscador) -> None:
        self._buscar = buscar

    def consultar(self, *, termo: str = "", codigo: str | None = None,
                  uf: str = "PA", competencia: str | None = None,
                  regime: str | None = SEM_DESONERACAO, tipo: str | None = None,
                  limite: int = 50) -> ResultadoConsulta:
        from .compras_gov import _tokens

        resultado = ResultadoConsulta()
        codigo = str(codigo or "").strip() or None
        if codigo is not None and not (codigo.isdigit() and len(codigo) <= 9):
            resultado.falha = "código do SINAPI tem só dígitos"
            return resultado
        if competencia is not None:
            _partes(competencia)
        if regime is not None and regime not in ROTULO_REGIME:
            resultado.falha = "regime desconhecido"
            return resultado
        if tipo is not None and tipo not in (INSUMO, COMPOSICAO):
            resultado.falha = "tipo desconhecido"
            return resultado
        termos = sorted({t.lower() for t in _tokens(termo) if t.isalnum()},
                        key=lambda t: (-len(t), t))[:12]
        if not termos and codigo is None:
            return resultado
        try:
            linhas = self._buscar([] if codigo else termos, codigo=codigo,
                                  uf=uf, competencia=competencia,
                                  regime=regime, tipo=tipo, limite=limite)
        except Exception as erro:  # noqa: BLE001 — índice fora vira recado
            resultado.falha = ("a consulta ao SINAPI não respondeu agora "
                               f"({type(erro).__name__})")
            return resultado
        if not isinstance(linhas, list):
            resultado.falha = "a consulta ao SINAPI devolveu resposta inesperada"
            return resultado
        for linha in linhas:
            if isinstance(linha, dict):
                referencia = referencia_da_linha(linha)
                if referencia is not None:
                    resultado.referencias.append(referencia)
        resultado.competencia = (resultado.referencias[0].competencia
                                 if resultado.referencias else competencia)
        return resultado


# ---------------------------------------------------------------------------
# Confronto com a edição oficial em PDF — leitor independente do XLSX
# ---------------------------------------------------------------------------
_MOEDA = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$")
_COEFICIENTE = re.compile(r"^\d+,\d{7}$")
_PERCENTUAL_AS = re.compile(r"^(-|\d{1,3}(?:,\d+)?%?)$")


def _moeda_br(texto: str) -> Decimal | None:
    texto = texto.strip()
    if not _MOEDA.match(texto):
        return None
    return Decimal(texto.replace(".", "").replace(",", "."))


def valores_do_pdf(linhas: list[str], tipo: str) -> dict[str, tuple]:
    """
    Código → (sem desoneração, com desoneração), a partir do TEXTO do PDF
    oficial da UF (`SINAPI_Preco_Ref_Insumos_<UF>_<AAAAMM>.pdf` e
    `SINAPI_Custo_Ref_Composicoes_<UF>_<AAAAMM>.pdf`, dentro do
    `SINAPI-<AAAA>-<MM>-formato-pdf.zip`). Hífen = sem preço (`None`).

    * insumo: família, coeficiente (7 casas), CÓDIGO, descrição, unidade,
      origem, preço sem e preço com desoneração;
    * composição: CÓDIGO, descrição, unidade, e duas linhas "custo %AS".
    """
    saida: dict[str, tuple] = {}
    limpas = [l.strip() for l in linhas]
    for i, linha in enumerate(limpas):
        if tipo == INSUMO:
            if not (_COEFICIENTE.match(linha) and i + 1 < len(limpas)
                    and limpas[i + 1].isdigit()):
                continue
            codigo, inicio = str(int(limpas[i + 1])), i + 2
            valores = []
            for seguinte in limpas[inicio:inicio + 12]:
                if seguinte == "-" or _MOEDA.match(seguinte):
                    valores.append(_moeda_br(seguinte))
                    if len(valores) == 2:
                        break
        else:
            if not (linha.isdigit() and len(linha) <= 7 and i + 1 < len(limpas)
                    and not limpas[i + 1].isdigit()):
                continue
            codigo, valores = str(int(linha)), []
            for seguinte in limpas[i + 2:i + 14]:
                partes = seguinte.split()
                # "custo %AS": o segundo campo é hífen ou percentual — senão
                # uma linha de descrição como "- MENSALISTA" passaria por valor
                if len(partes) == 2 and (partes[0] == "-" or _MOEDA.match(partes[0])) \
                        and _PERCENTUAL_AS.match(partes[1]):
                    valores.append(_moeda_br(partes[0]))
                    if len(valores) == 2:
                        break
        if len(valores) == 2:
            saida.setdefault(codigo, tuple(valores))
    return saida


@dataclass
class ConfrontoPDF:
    conferidas: int = 0
    iguais: int = 0
    ausentes_no_pdf: list[str] = field(default_factory=list)
    divergentes: list[dict] = field(default_factory=list)

    def para_registro(self) -> dict:
        return dict(vars(self))


def confrontar_com_pdf(linhas_do_indice: list[dict],
                       pdf: dict[str, dict[str, tuple]]) -> ConfrontoPDF:
    """
    Cada linha importada (sem ou com desoneração) contra o valor do PDF
    oficial da mesma UF e tipo. `pdf[tipo][codigo] = (sem, com)`.
    O regime "sem encargos" não sai no PDF e não é conferido aqui.
    """
    posicao = {SEM_DESONERACAO: 0, COM_DESONERACAO: 1}
    feito = ConfrontoPDF()
    for linha in linhas_do_indice:
        if linha["regime"] not in posicao:
            continue
        feito.conferidas += 1
        do_pdf = pdf.get(linha["tipo"], {}).get(str(linha["codigo"]))
        if do_pdf is None:
            feito.ausentes_no_pdf.append(f"{linha['tipo']} {linha['codigo']}")
            continue
        esperado = do_pdf[posicao[linha["regime"]]]
        if esperado is not None and Decimal(str(linha["valor"])) == esperado:
            feito.iguais += 1
        else:
            feito.divergentes.append({
                "tipo": linha["tipo"], "codigo": linha["codigo"],
                "regime": linha["regime"], "importado": str(linha["valor"]),
                "pdf": None if esperado is None else format(esperado, "f")})
    return feito


def competencia_anterior(hoje: date | None = None) -> str:
    """O mês anterior a `hoje`: a competência que a CAIXA costuma ter
    publicado (outubro sai em meados de novembro)."""
    hoje = hoje or date.today()
    ano, mes = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)
    return f"{ano:04d}-{mes:02d}"
