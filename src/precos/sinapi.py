"""
SINAPI (CAIXA / IBGE) — custo de referência de ENGENHARIA, por competência.

O SINAPI não é preço de compra. É o sistema de referência de custos de obras
e serviços de engenharia (Lei 14.133, art. 23, § 2º, I; Decreto 7.983/2013):
o preço de insumo é mediana coletada pelo IBGE e o custo de composição é
calculado pela CAIXA a partir dele. Por isso esta fonte **não entra** em
`fontes_padrao()` nem na cesta da pesquisa de preços: tem importação e
consulta próprias, e o resultado vai ao orçamento de engenharia, não à média
de contratações.

Leiaute conferido no arquivo oficial de 10/2026 (`SINAPI-2026-10-formato-xlsx.zip`,
16.083.991 bytes, sha256 2e99cde7…, publicado em 12/11/2026). Desde 2025 a
CAIXA publica UM arquivo mensal nacional; dentro dele,
`SINAPI_Referência_AAAA_MM.xlsx` traz seis abas de preço, uma coluna por UF:

    ISD / ICD / ISE  insumos      — sem desoneração / com desoneração / sem encargos
    CSD / CCD / CSE  composições  — idem

* linha 3: "Mês de Referência:" MM/AAAA — conferido contra a competência pedida;
* linhas 6–7 (com encargos): percentual de encargos sociais horista e
  mensalista por UF — gravado na versão;
* linha 9 (composições) ou 10 (insumos): as siglas das UF; linha 10: o
  cabeçalho; dados a partir da 11;
* insumo: classificação, código, descrição, unidade, origem do preço
  (C = coletado; CR = coeficiente de representatividade) e o preço por UF;
* composição: grupo, código (dentro de uma fórmula `HYPERLINK(...;código)` —
  o valor em cache é 0), descrição, unidade e, por UF, custo e %AS (parte do
  custo obtida com preço de São Paulo por indisponibilidade na UF).

Recusas (contadas por motivo, nunca gravadas):

* preço em branco — "não houve coleta mínima de preços no mês";
* preço ou custo ZERO — a CAIXA já publicou arquivos com preços zerados e
  depois corrigidos (Notas SINAPI); 2.194 composições do PA em 10/2026 vêm
  com custo 0 ("sem custo");
* código não numérico ou unidade vazia.

Retificação: a CAIXA republica o arquivo da mesma competência. O SHA-256 é a
versão: arquivo novo da mesma competência e UF é versão nova, publicada
inteira só depois de validada; a anterior continua guardada.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Protocol

from . import arquivos
from . import evidencia as ev

FONTE_ID = "sinapi"
NOME = "SINAPI — CAIXA/IBGE"
VERSAO_PARSER = "sinapi-2026-11-23.1"
URL_PAGINA = ("https://www.caixa.gov.br/poder-publico/modernizacao-gestao/"
              "sinapi/Paginas/default.aspx")
URL_NOTAS = ("https://www.caixa.gov.br/Downloads/"
             "sinapi-historico-de-encargos-e-notas/Notas_SINAPI.pdf")
NATUREZA = "custo_referencia_engenharia"
ROTULO_NATUREZA = "custo de referência de engenharia (SINAPI), não preço de compra"

ABAS = {
    "ISD": ("insumo", "sem_desoneracao"),
    "ICD": ("insumo", "com_desoneracao"),
    "ISE": ("insumo", "sem_encargos"),
    "CSD": ("composicao", "sem_desoneracao"),
    "CCD": ("composicao", "com_desoneracao"),
    "CSE": ("composicao", "sem_encargos"),
}
ROTULO_REGIME = {"sem_desoneracao": "sem desoneração",
                 "com_desoneracao": "com desoneração",
                 "sem_encargos": "sem encargos sociais"}
ROTULO_TIPO = {"insumo": "insumo", "composicao": "composição"}
UFS = ("AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
       "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
       "SE", "SP", "TO")
PRIMEIRA_LINHA = 11
ORIGENS = {"C": "coletado", "CR": "coeficiente de representatividade"}

PRECO_VAZIO = "PRECO_EM_BRANCO_SEM_COLETA_MINIMA"
PRECO_ZERO = "PRECO_OU_CUSTO_ZERO"
SEM_CODIGO = "CODIGO_NAO_NUMERICO"
SEM_UNIDADE = ev.SEM_UNIDADE
SEM_DESCRICAO = ev.SEM_DESCRICAO

# A planilha de referência tem ~14 MB descompactada; o XML de dentro dela,
# ~130 MB. Teto folgado, mas teto.
MAX_XLSX = 80_000_000
MAX_XML = 1_500_000_000
PISO_DE_REDUCAO = Decimal("0.5")
LOTE = 1000
IMPORTANDO, PUBLICADO, RECUSADO = "importando", "publicado", "recusado"


class ArquivoInvalido(ValueError):
    """O arquivo não é a publicação esperada — não é lido adiante."""


def competencia_valida(texto: str) -> tuple[int, int]:
    """'2026-10' → (2026, 10). Qualquer outra coisa é recusada."""
    achado = re.fullmatch(r"(\d{4})-(\d{2})", str(texto or "").strip())
    if not achado or not 1 <= int(achado.group(2)) <= 12 or \
            not 2000 <= int(achado.group(1)) <= 2100:
        raise ValueError("competência no formato AAAA-MM")
    return int(achado.group(1)), int(achado.group(2))


def url_do_arquivo(competencia: str) -> str:
    """Endereço oficial do arquivo mensal — montado, nunca copiado."""
    ano, mes = competencia_valida(competencia)
    return ("https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/"
            f"SINAPI-{ano}-{mes:02d}-formato-xlsx.zip")


def _decimal(valor) -> Decimal | None:
    """
    Número da célula → `Decimal`. A célula é constante numérica no XML; o
    openpyxl a entrega como `float`, e `repr` devolve o MENOR texto que
    reconstrói aquele binário — o mesmo que a CAIXA gravou (ex.: 269.08).
    Nada de `Decimal(float)`, que traria a expansão binária inteira.
    """
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):
        return None
    try:
        if isinstance(valor, float):
            return Decimal(repr(valor))
        return Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


_CODIGO_NA_FORMULA = re.compile(r"[,;]\s*(\d+)\s*\)\s*$")


def codigo_da_celula(valor) -> str | None:
    """
    O código da linha. Na composição a célula é
    `=HYPERLINK("#"&CELL(...);104658)` e o valor em cache é 0: o código é o
    último argumento da fórmula.
    """
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, (int, float)):
        inteiro = int(valor)
        return str(inteiro) if inteiro == valor and inteiro > 0 else None
    texto = str(valor).strip()
    if texto.startswith("="):
        achado = _CODIGO_NA_FORMULA.search(texto)
        return achado.group(1) if achado else None
    return texto if texto.isdigit() and int(texto) > 0 else None


def _texto(valor) -> str:
    return " ".join(str(valor or "").split())


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
@dataclass
class Registro:
    """Uma linha de UMA aba para UMA UF — o que a consulta devolve."""

    competencia: str
    uf: str
    tipo: str                 # insumo | composicao
    regime: str               # sem_desoneracao | com_desoneracao | sem_encargos
    codigo: str
    descricao: str
    unidade: str
    valor: Decimal
    classificacao: str        # classificação do insumo ou grupo da composição
    origem_preco: str | None  # insumo: C | CR
    percentual_sp: Decimal | None   # composição: %AS
    aba: str
    linha: int

    @property
    def chave(self) -> str:
        """Identidade estável da linha DENTRO da publicação mensal."""
        return f"{self.competencia}:{self.uf}:{self.tipo}:{self.regime}:{self.codigo}"


@dataclass
class Leitura:
    competencia: str = ""
    emissao: str = ""
    linhas: int = 0
    validos: int = 0
    motivos: Counter = field(default_factory=Counter)
    por_aba: dict = field(default_factory=dict)
    encargos: dict = field(default_factory=dict)


def _planilha_de_referencia(caminho: Path, competencia: str) -> bytes:
    """O XLSX de referência de dentro do ZIP mensal, com as defesas."""
    ano, mes = competencia_valida(competencia)
    with zipfile.ZipFile(caminho) as z:
        entradas = arquivos.conferir_zip(caminho, extensoes={".xlsx"})
        nomes = [i.filename for i in entradas
                 if i.filename.startswith("SINAPI_Refer")
                 and i.filename.endswith(f"_{ano}_{mes:02d}.xlsx")]
        if len(nomes) != 1:
            raise ArquivoInvalido(
                f"o ZIP não traz a planilha de referência de {mes:02d}/{ano}: "
                f"{sorted(i.filename for i in entradas)}")
        info = z.getinfo(nomes[0])
        if info.file_size > MAX_XLSX:
            raise ArquivoInvalido("planilha de referência grande demais")
        dados = z.read(nomes[0])
    # o XLSX também é um ZIP: mesma defesa contra bomba de compressão
    with zipfile.ZipFile(io.BytesIO(dados)) as x:
        total = sum(i.file_size for i in x.infolist())
        if total > MAX_XML or any(
                i.file_size / max(i.compress_size, 1) > arquivos.MAX_TAXA
                for i in x.infolist() if i.file_size > 1_000_000):
            raise ArquivoInvalido("planilha com compressão suspeita")
    return dados


def ler(caminho: Path, competencia: str, ufs: tuple[str, ...], *,
        leitura: Leitura | None = None):
    """
    Os registros VÁLIDOS das UF pedidas, aba por aba. As recusas ficam
    contadas em `leitura.motivos`.
    """
    import openpyxl

    ufs = tuple(u.upper() for u in ufs)
    if not ufs or any(u not in UFS for u in ufs):
        raise ValueError("UF fora da lista do SINAPI")
    leitura = leitura if leitura is not None else Leitura()
    ano, mes = competencia_valida(competencia)
    leitura.competencia = competencia
    livro = openpyxl.load_workbook(
        io.BytesIO(_planilha_de_referencia(caminho, competencia)),
        read_only=True, data_only=False)
    faltam = [a for a in ABAS if a not in livro.sheetnames]
    if faltam:
        raise ArquivoInvalido(f"o leiaute mudou: faltam as abas {faltam}")
    for aba, (tipo, regime) in ABAS.items():
        folha = livro[aba]
        topo = list(folha.iter_rows(min_row=1, max_row=PRIMEIRA_LINHA - 1,
                                    values_only=True))
        mes_declarado = _texto(topo[2][1])
        if mes_declarado != f"{mes:02d}/{ano}":
            raise ArquivoInvalido(
                f"{aba}: mês de referência {mes_declarado!r}, esperado "
                f"{mes:02d}/{ano}")
        leitura.emissao = leitura.emissao or _texto(topo[3][1])
        siglas = topo[8] if tipo == "composicao" else topo[9]
        colunas = {u: i for i, u in enumerate(siglas) if u in ufs}
        if set(colunas) != set(ufs):
            raise ArquivoInvalido(f"{aba}: colunas de UF ausentes "
                                  f"{sorted(set(ufs) - set(colunas))}")
        cabecalho = [_texto(c).upper() for c in topo[9]]
        esperado = ("CÓDIGO DA COMPOSIÇÃO" if tipo == "composicao"
                    else "CÓDIGO DO INSUMO")
        if len(cabecalho) < 4 or cabecalho[1] != esperado or \
                not cabecalho[3].startswith("UNIDADE"):
            raise ArquivoInvalido(f"{aba}: cabeçalho fora do leiaute: "
                                  f"{cabecalho[:5]}")
        if regime != "sem_encargos":
            for uf, coluna in colunas.items():
                leitura.encargos.setdefault(uf, {})[regime] = {
                    "horista": _texto(topo[5][coluna]),
                    "mensalista": _texto(topo[6][coluna])}
        contagem = Counter()
        for numero, linha in enumerate(
                folha.iter_rows(min_row=PRIMEIRA_LINHA, values_only=True),
                start=PRIMEIRA_LINHA):
            if len(linha) < 4 or all(c in (None, "") for c in linha[:4]):
                continue
            for uf, coluna in colunas.items():
                leitura.linhas += 1
                registro, motivo = _registro(
                    linha, numero, coluna, aba=aba, tipo=tipo, regime=regime,
                    uf=uf, competencia=competencia)
                if registro is None:
                    leitura.motivos[motivo] += 1
                    contagem[motivo] += 1
                    continue
                leitura.validos += 1
                contagem["validos"] += 1
                yield registro
        leitura.por_aba[aba] = dict(contagem)
    livro.close()


def _registro(linha, numero, coluna, *, aba, tipo, regime, uf, competencia
              ) -> tuple[Registro | None, str]:
    codigo = codigo_da_celula(linha[1])
    if codigo is None:
        return None, SEM_CODIGO
    descricao, unidade = _texto(linha[2]), _texto(linha[3]).upper()
    if not descricao:
        return None, SEM_DESCRICAO
    if not unidade:
        return None, SEM_UNIDADE
    valor = _decimal(linha[coluna] if coluna < len(linha) else None)
    if valor is None:
        return None, PRECO_VAZIO
    if valor <= 0:
        return None, PRECO_ZERO
    origem = percentual = None
    if tipo == "insumo":
        origem = _texto(linha[4]).upper() or None
    else:
        percentual = _decimal(linha[coluna + 1] if coluna + 1 < len(linha)
                              else None)
    return Registro(
        competencia=competencia, uf=uf, tipo=tipo, regime=regime,
        codigo=codigo, descricao=descricao, unidade=unidade, valor=valor,
        classificacao=_texto(linha[0]), origem_preco=origem,
        percentual_sp=percentual, aba=aba, linha=numero), ""


# ---------------------------------------------------------------------------
# Índice e versões
# ---------------------------------------------------------------------------
def linha_do_indice(r: Registro, *, sha256: str, url: str) -> dict:
    from .pncp_indice import texto_de_busca

    bruto = {"aba": r.aba, "linha": r.linha, "codigo": r.codigo,
             "valor": format(r.valor, "f"), "uf": r.uf,
             "competencia": r.competencia}
    return {
        "registro_id": hashlib.sha256(
            f"{sha256}:{r.chave}".encode()).hexdigest()[:40],
        "chave_linha": r.chave,
        "competencia": r.competencia, "uf": r.uf, "tipo": r.tipo,
        "regime": r.regime, "codigo": r.codigo, "descricao": r.descricao,
        "descricao_busca": texto_de_busca(r.descricao),
        "unidade": r.unidade, "valor": format(r.valor, "f"),
        "classificacao": r.classificacao or None,
        "origem_preco": r.origem_preco,
        "percentual_sp": None if r.percentual_sp is None
        else format(r.percentual_sp, "f"),
        "aba": r.aba, "linha_planilha": r.linha,
        "arquivo_sha256": sha256, "url_arquivo": url,
        "hash_linha": ev.hash_da_linha(bruto),
        "versao_parser": VERSAO_PARSER,
    }


class Armazem(Protocol):
    def versao(self, competencia: str, uf: str, sha256: str) -> dict | None: ...

    def versao_publicada(self, competencia: str, uf: str) -> dict | None: ...

    def registrar_versao(self, competencia: str, uf: str, sha256: str,
                         **campos) -> None: ...

    def gravar_registros(self, linhas: list[dict]) -> None: ...

    def publicar(self, competencia: str, uf: str, sha256: str,
                 **campos) -> None: ...

    def buscar(self, termos: list[str], **filtros) -> list[dict]: ...


class ArmazemEmMemoria:
    """O contrato do banco, em memória — provas e medição de bancada."""

    def __init__(self) -> None:
        self.versoes: dict[tuple[str, str, str], dict] = {}
        self.registros: dict[str, dict] = {}

    def versao(self, competencia, uf, sha256):
        return self.versoes.get((competencia, uf, sha256))

    def versao_publicada(self, competencia, uf):
        for v in self.versoes.values():
            if (v["competencia"], v["uf"]) == (competencia, uf) and v["vigente"]:
                return v
        return None

    def registrar_versao(self, competencia, uf, sha256, **campos):
        atual = self.versoes.get((competencia, uf, sha256), {
            "competencia": competencia, "uf": uf, "sha256": sha256,
            "vigente": False})
        self.versoes[(competencia, uf, sha256)] = {**atual, **campos}

    def gravar_registros(self, linhas):
        for linha in linhas:
            self.registros[linha["registro_id"]] = {**linha, "vigente": False}

    def publicar(self, competencia, uf, sha256, **campos):
        for v in self.versoes.values():
            if (v["competencia"], v["uf"]) == (competencia, uf):
                v["vigente"] = False
        for linha in self.registros.values():
            if (linha["competencia"], linha["uf"]) == (competencia, uf):
                linha["vigente"] = linha["arquivo_sha256"] == sha256
        self.registrar_versao(competencia, uf, sha256, estado=PUBLICADO,
                              vigente=True, **campos)

    def buscar(self, termos, *, codigo=None, uf=None, competencia=None,
               tipo=None, regime=None, limite=50):
        procurados = set(termos)
        achados = []
        for linha in self.registros.values():
            if not linha["vigente"]:
                continue
            if uf and linha["uf"] != uf.upper():
                continue
            if competencia and linha["competencia"] != competencia:
                continue
            if tipo and linha["tipo"] != tipo:
                continue
            if regime and linha["regime"] != regime:
                continue
            if codigo:
                if linha["codigo"] != codigo:
                    continue
                comuns = 0
            else:
                comuns = len(procurados & set(linha["descricao_busca"]
                                              .replace(",", " ").split()))
                if not comuns:
                    continue
            achados.append((comuns, linha["competencia"], linha))
        achados.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [linha for *_, linha in achados[:limite]]


@dataclass
class Importacao:
    competencia: str = ""
    uf: str = ""
    sha256: str = ""
    desfecho: str = ""            # publicado | ja_publicado | recusado
    motivo: str = ""
    linhas: int = 0
    validos: int = 0
    recusas: Counter = field(default_factory=Counter)
    por_aba: dict = field(default_factory=dict)
    encargos: dict = field(default_factory=dict)
    validos_na_versao_anterior: int | None = None

    def para_registro(self) -> dict:
        saida = dict(vars(self))
        saida["recusas"] = dict(self.recusas)
        return saida


def importar(armazem: Armazem, caminho: Path, *, competencia: str, uf: str,
             url: str | None = None, last_modified: str | None = None,
             lote: Callable[[list[dict]], None] | None = None) -> Importacao:
    """
    Importa UMA UF de UMA competência e publica a versão, ou a recusa.

    Idempotente: o mesmo arquivo (SHA-256) já publicado não é relido.
    Retificação da competência = outro SHA = versão nova; a anterior só
    deixa de valer quando a nova é publicada inteira.
    """
    url = url or url_do_arquivo(competencia)
    if not arquivos.url_permitida(url) or url != url_do_arquivo(competencia):
        raise ValueError("o arquivo do SINAPI só é aceito do endereço oficial "
                         "da competência")
    uf = uf.upper()
    sha = arquivos.sha256_do_arquivo(caminho)
    feito = Importacao(competencia=competencia, uf=uf, sha256=sha)
    existente = armazem.versao(competencia, uf, sha)
    if existente and existente.get("estado") == PUBLICADO:
        feito.desfecho = "ja_publicado"
        return feito

    leitura = Leitura()
    linhas = [linha_do_indice(r, sha256=sha, url=url)
              for r in ler(caminho, competencia, (uf,), leitura=leitura)]
    unicas = {l["chave_linha"]: l for l in linhas}
    feito.linhas, feito.validos = leitura.linhas, len(unicas)
    feito.recusas, feito.por_aba = leitura.motivos, leitura.por_aba
    feito.encargos = leitura.encargos.get(uf, {})
    if len(unicas) != len(linhas):
        feito.recusas["CHAVE_REPETIDA"] += len(linhas) - len(unicas)

    def recusar(motivo: str) -> Importacao:
        feito.desfecho, feito.motivo = RECUSADO, motivo
        armazem.registrar_versao(
            competencia, uf, sha, estado=RECUSADO, url=url, motivo=motivo,
            linhas=feito.linhas, validos=feito.validos,
            recusas=dict(feito.recusas), versao_parser=VERSAO_PARSER)
        return feito

    if not unicas:
        return recusar("nenhum registro com preço válido")
    publicada = armazem.versao_publicada(competencia, uf)
    if publicada is not None:
        feito.validos_na_versao_anterior = int(publicada.get("validos") or 0)
        if feito.validos < feito.validos_na_versao_anterior * PISO_DE_REDUCAO:
            return recusar(
                f"{feito.validos} registros válidos contra "
                f"{feito.validos_na_versao_anterior} da versão publicada — "
                "redução acima do tolerado; a versão anterior continua valendo")

    armazem.registrar_versao(
        competencia, uf, sha, estado=IMPORTANDO, url=url, motivo="",
        last_modified=last_modified, emissao=leitura.emissao,
        linhas=feito.linhas, validos=feito.validos,
        recusas=dict(feito.recusas), encargos=feito.encargos,
        versao_parser=VERSAO_PARSER)
    pendentes = list(unicas.values())
    for inicio in range(0, len(pendentes), LOTE):
        armazem.gravar_registros(pendentes[inicio:inicio + LOTE])
        if lote is not None:
            lote(pendentes[inicio:inicio + LOTE])
    armazem.publicar(competencia, uf, sha, publicado_em=datetime.now(
        timezone.utc).isoformat(timespec="seconds"))
    feito.desfecho = PUBLICADO
    return feito


# ---------------------------------------------------------------------------
# Conferência contra a edição oficial
# ---------------------------------------------------------------------------
@dataclass
class Confronto:
    conferidos: int = 0
    iguais: int = 0
    divergentes: list[dict] = field(default_factory=list)

    def para_registro(self) -> dict:
        return {"conferidos": self.conferidos, "iguais": self.iguais,
                "divergentes": self.divergentes}


def confrontar(linhas: list[dict], caminho: Path) -> Confronto:
    """
    Relê, célula a célula, as linhas indexadas na planilha oficial: mesma
    aba, mesma linha, mesmo código, mesma unidade e mesmo valor na coluna
    da UF. É a prova de que o índice reproduz a edição publicada.
    """
    import openpyxl

    confronto = Confronto()
    if not linhas:
        return confronto
    competencia = linhas[0]["competencia"]
    livro = openpyxl.load_workbook(
        io.BytesIO(_planilha_de_referencia(caminho, competencia)),
        read_only=True, data_only=False)
    por_aba: dict[str, list[dict]] = {}
    for linha in linhas:
        por_aba.setdefault(linha["aba"], []).append(linha)
    for aba, alvo in por_aba.items():
        tipo = ABAS[aba][0]
        folha = livro[aba]
        siglas = list(folha.iter_rows(min_row=9 if tipo == "composicao"
                                      else 10, max_row=9 if tipo ==
                                      "composicao" else 10,
                                      values_only=True))[0]
        coluna = {u: i for i, u in enumerate(siglas) if u in UFS}
        procuradas = {int(l["linha_planilha"]): l for l in alvo}
        for numero, celulas in enumerate(folha.iter_rows(
                min_row=PRIMEIRA_LINHA, max_row=max(procuradas),
                values_only=True), start=PRIMEIRA_LINHA):
            linha = procuradas.get(numero)
            if linha is None:
                continue
            confronto.conferidos += 1
            oficial = _decimal(celulas[coluna[linha["uf"]]])
            igual = (codigo_da_celula(celulas[1]) == linha["codigo"]
                     and _texto(celulas[3]).upper() == linha["unidade"]
                     and oficial is not None
                     and oficial == Decimal(linha["valor"]))
            if igual:
                confronto.iguais += 1
            else:
                confronto.divergentes.append({
                    "aba": aba, "linha": numero, "codigo": linha["codigo"],
                    "indice": linha["valor"],
                    "oficial": None if oficial is None else format(oficial, "f")})
    livro.close()
    return confronto


# ---------------------------------------------------------------------------
# Consulta — o que a tela e o relatório mostram
# ---------------------------------------------------------------------------
TIPOS = frozenset({"insumo", "composicao"})
REGIMES = frozenset(ABAS[a][1] for a in ABAS)


def consultar(buscar: Callable[..., list], *, termo: str = "",
              codigo: str | None = None, uf: str = "PA",
              competencia: str | None = None, tipo: str | None = None,
              regime: str | None = "sem_desoneracao", limite: int = 50
              ) -> list[dict]:
    """
    Consulta ao índice, por código (identidade) ou termos da descrição. Os
    filtros são conferidos aqui, antes da RPC; o resultado sai com a
    natureza e a origem por extenso.
    """
    from .compras_gov import _tokens
    from .pncp_indice import texto_de_busca

    codigo = str(codigo or "").strip() or None
    if codigo is not None and not codigo.isdigit():
        raise ValueError("código do SINAPI é numérico")
    if uf.upper() not in UFS:
        raise ValueError("UF fora da lista do SINAPI")
    if competencia is not None:
        competencia_valida(competencia)
    if tipo is not None and tipo not in TIPOS:
        raise ValueError("tipo: insumo ou composição")
    if regime is not None and regime not in REGIMES:
        raise ValueError("regime desconhecido")
    termos = sorted({p.lower() for p in _tokens(texto_de_busca(termo))
                     if p.isalnum()}, key=lambda p: (-len(p), p))[:12]
    if not termos and codigo is None:
        return []
    linhas = buscar(termos if codigo is None else [], codigo=codigo,
                    uf=uf.upper(), competencia=competencia, tipo=tipo,
                    regime=regime, limite=max(1, min(int(limite), 200)))
    return [descrever(l) for l in linhas or [] if isinstance(l, dict)]


def descrever(linha: dict) -> dict:
    """Linha do índice → o que se mostra, com a origem verificável."""
    ano, mes = competencia_valida(linha["competencia"])
    origem = linha.get("origem_preco")
    return {
        **{k: linha.get(k) for k in (
            "registro_id", "chave_linha", "competencia", "uf", "tipo",
            "regime", "codigo", "descricao", "unidade", "valor",
            "classificacao", "origem_preco", "percentual_sp", "aba",
            "linha_planilha", "arquivo_sha256", "url_arquivo",
            "versao_parser")},
        "competencia_exibicao": f"{mes:02d}/{ano}",
        "rotulo_tipo": ROTULO_TIPO[linha["tipo"]],
        "rotulo_regime": ROTULO_REGIME[linha["regime"]],
        "rotulo_origem": ORIGENS.get(origem or "", "") if origem else "",
        "natureza": NATUREZA, "rotulo_natureza": ROTULO_NATUREZA,
        "fonte": NOME, "url_fonte": URL_PAGINA,
        "url_verificacao": url_do_arquivo(linha["competencia"]),
    }
