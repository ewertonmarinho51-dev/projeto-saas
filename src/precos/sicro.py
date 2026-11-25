"""
SICRO (DNIT) — custo referencial de obras de infraestrutura de transportes.

Não é preço de compra: é CUSTO REFERENCIAL de engenharia, como o SINAPI, com
o mesmo fundamento (Lei 14.133, art. 23, § 2º, I, e o § 3º para sistema
alternativo). Não entra em `fontes_padrao()` nem na cesta; tem consulta
própria.

Publicação conferida em 24/11/2026: o DNIT publica, por UF e trimestre
(janeiro, abril, julho, outubro; às vezes uma edição "revisado"), uma
página em
`www.gov.br/dnit/pt-br/assuntos/planejamento-e-pesquisa/custos-referenciais/`
`sistemas-de-custos/sicro/relatorios/relatorios-sicro/<região>/<uf>/<ano>/…`
com UM arquivo 7-Zip. O do Pará de julho/2026 é `pa-07-2026.7z`, 26.174.897
bytes, sha256 3a545a7d…2592de5, com 24 relatórios em PDF e XLSX cujo nome
começa por "PA 07-2026 Relatório …".

Lidos aqui, dos XLSX sintéticos (uma aba, cabeçalho na 1ª linha):

* Composições de Custos — código de 7 dígitos, serviço, unidade, custo
  unitário. É SEM desoneração: o analítico do mesmo arquivo precifica a mão
  de obra pelo valor sem desoneração (ajudante P9801 a R$ 24,8197 em todas
  as composições; com desoneração seria R$ 23,6691);
* Materiais — código M####, preço unitário ("-" = sem preço na UF);
* Mão de Obra, sem e com desoneração — P####, custo por hora ou mês;
* Equipamentos, sem e com desoneração — E#### e A####, custo horário
  produtivo e improdutivo (as linhas A#### repetidas e IDÊNTICAS são o mesmo
  equipamento listado de novo; repetida com valor diferente é recusada);
* Origem de Preços — a sigla da UF para cada insumo (PC, PFM, PRE…), com a
  legenda do próprio relatório.

Valor zero ("preço referencial zerado") e "-" não viram custo: a linha é
recusada com motivo e contada. BDI não está incluído.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterator, Protocol

from . import arquivos

FONTE_ID = "sicro"
NOME = "SICRO — Sistema de Custos Referenciais de Obras (DNIT)"
VERSAO_PARSER = "sicro-2026-11-24.1"
NATUREZA = "custo_referencial"
URL_PAGINA = ("https://www.gov.br/dnit/pt-br/assuntos/planejamento-e-pesquisa/"
              "custos-referenciais/sistemas-de-custos/sicro/relatorios")
URL_RELATORIOS = URL_PAGINA + "/relatorios-sicro/"
UFS_PILOTO = ("PA",)
PISO_DE_REDUCAO = Decimal("0.5")
LOTE = 1000
CASAS = 4                      # o SICRO publica insumos com 4 casas

COMPOSICAO, MATERIAL, MAO_DE_OBRA, EQUIPAMENTO = (
    "composicao", "material", "mao_de_obra", "equipamento")
TIPOS = (COMPOSICAO, MATERIAL, MAO_DE_OBRA, EQUIPAMENTO)
SEM_DESONERACAO, COM_DESONERACAO, NAO_SE_APLICA = (
    "sem_desoneracao", "com_desoneracao", "nao_se_aplica")
ROTULO_REGIME = {SEM_DESONERACAO: "encargos sociais sem desoneração",
                 COM_DESONERACAO: "encargos sociais com desoneração",
                 NAO_SE_APLICA: "sem encargos sociais (material)"}
ROTULO_TIPO = {COMPOSICAO: "Composição", MATERIAL: "Material",
               MAO_DE_OBRA: "Mão de obra", EQUIPAMENTO: "Equipamento"}
PUBLICADO, RECUSADO, IMPORTANDO = "publicado", "recusado", "importando"

# UF → (região, pasta) no portal do DNIT, conferidas nas cinco páginas
# regionais em 24/11/2026
UFS = {
    "AC": ("norte", "acre"), "AM": ("norte", "amazonas"), "AP": ("norte", "amapa"),
    "PA": ("norte", "para"), "RO": ("norte", "rondonia"), "RR": ("norte", "roraima"),
    "TO": ("norte", "tocantins"), "AL": ("nordeste", "alagoas"),
    "BA": ("nordeste", "bahia"), "CE": ("nordeste", "ceara"),
    "MA": ("nordeste", "maranhao"), "PB": ("nordeste", "paraiba"),
    "PE": ("nordeste", "pernambuco"), "PI": ("nordeste", "piaui"),
    "RN": ("nordeste", "rio-grande-do-norte"), "SE": ("nordeste", "sergipe"),
    "DF": ("centro-oeste", "distrito-federal"), "GO": ("centro-oeste", "goias"),
    "MS": ("centro-oeste", "mato-grosso-do-sul"), "MT": ("centro-oeste", "mato-grosso"),
    "ES": ("sudeste", "espirito-santo"), "MG": ("sudeste", "minas-gerais"),
    "RJ": ("sudeste", "rio-de-janeiro"), "SP": ("sudeste", "sao-paulo"),
    "PR": ("sul", "parana"), "RS": ("sul", "rio-grande-do-sul"),
    "SC": ("sul", "santa-catarina"),
}
MESES = ("janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro")

# Legenda do próprio "Relatório Sintético de Origem de Preços" (jul/2026)
ORIGENS = {
    "PC": "preço coletado", "PCT": "preço coletado com tratamento",
    "PCI": "preço coletado atualizado por índice",
    "PFM": "preço com frete metodológico", "PFE": "preço de fontes externas",
    "PRE": "preço referencial estimado", "PRI": "preço referencial imputado",
    "PRZ": "preço referencial zerado", "PND": "preço não determinado",
    "PEE": "precificado por estudo específico",
    "PEI": "precificado por extrapolação ou interpolação",
    "PMP": "precificado por metodologia de parametrização",
    "PMT": "precificado por metodologia de parametrização com tratamento",
    "SCM": "salário definido por coleta de mercado",
    "SDP": "salário de fontes secundárias de dados públicos",
    "SMN": "salário substituído pelo mínimo nacional/estadual",
    "SPC": "salário definido pelo piso da categoria",
}

# Relatório → (tipo, regime, cabeçalho esperado, coluna do valor, coluna do
# improdutivo). O cabeçalho é comparado sem acento, caixa nem quebra de linha.
RELATORIOS = {
    "Composições de Custos": (
        COMPOSICAO, SEM_DESONERACAO,
        ("codigo", "descricao do servico", "unidade", "custo unitario (r$)"), 3, None),
    "Materiais": (
        MATERIAL, NAO_SE_APLICA,
        ("codigo", "descricao", "unidade", "preco unitario (r$)"), 3, None),
    "Mão de Obra": (
        MAO_DE_OBRA, SEM_DESONERACAO,
        ("codigo", "descricao", "unidade", "custo (r$)"), 3, None),
    "Mão de Obra - com desoneração": (
        MAO_DE_OBRA, COM_DESONERACAO,
        ("codigo", "descricao", "unidade", "custo (r$)"), 3, None),
    "Equipamentos": (
        EQUIPAMENTO, SEM_DESONERACAO,
        ("codigo", "descricao", "valor de aquisicao (r$)", "depreciacao (r$/h)",
         "oportunidade de capital (r$/h)", "seguros e impostos (r$/h)",
         "manutencao (r$/h)", "operacao (r$/h)", "mao de obra de operacao (r$/h)",
         "custo produtivo (r$/h)", "custo improdutivo (r$/h)"), 9, 10),
    "Equipamentos - com desoneração": (
        EQUIPAMENTO, COM_DESONERACAO,
        ("codigo", "descricao", "valor de aquisicao (r$)", "depreciacao (r$/h)",
         "oportunidade de capital (r$/h)", "seguros e impostos (r$/h)",
         "manutencao (r$/h)", "operacao (r$/h)", "mao de obra de operacao (r$/h)",
         "custo produtivo (r$/h)", "custo improdutivo (r$/h)"), 9, 10),
}
ORIGEM = "Origem de Preços do SICRO"

_CODIGO = {COMPOSICAO: re.compile(r"^\d{7}$"), MATERIAL: re.compile(r"^M\d{4}$"),
           MAO_DE_OBRA: re.compile(r"^P\d{4}$"),
           EQUIPAMENTO: re.compile(r"^[EA]\d{4}$")}
_NOME_RELATORIO = re.compile(
    r"^([A-Z]{2}) (\d{2})-(\d{4}) Relatório Sintético de (.+)\.xlsx$")
_NOME_7Z = re.compile(r"^[a-z]{2}-\d{2}-\d{4}(?:[-_][a-z0-9]+)*\.7z$")

SEM_PRECO = "SEM_PRECO_NA_UF"                 # "-" ou vazio
PRECO_ZERADO = "PRECO_ZERADO"                 # PRZ: divulgado como zero
CODIGO_INVALIDO = "CODIGO_INVALIDO"
CODIGO_REPETIDO = "CODIGO_REPETIDO_COM_VALOR_DIFERENTE"
REPETIDA_IDENTICA = "LINHA_REPETIDA_IDENTICA"
VALOR_ILEGIVEL = "VALOR_ILEGIVEL"
SEM_DESCRICAO = "SEM_DESCRICAO"


class LeiauteInesperado(ValueError):
    """O arquivo não tem a forma conferida — nada é importado."""


# ---------------------------------------------------------------------------
# Competência e endereço oficial
# ---------------------------------------------------------------------------
def competencia_valida(texto: str) -> tuple[int, int]:
    achado = re.fullmatch(r"(\d{4})-(\d{2})", str(texto or "").strip())
    if not achado or not 1 <= int(achado.group(2)) <= 12 or \
            not 2000 <= int(achado.group(1)) <= 2100:
        raise ValueError("competência no formato AAAA-MM")
    return int(achado.group(1)), int(achado.group(2))


def url_oficial(url: str) -> bool:
    """Só a árvore de relatórios do SICRO no portal do DNIT, por HTTPS."""
    url = str(url or "")
    return (url.startswith(URL_RELATORIOS) and not any(
        c in url for c in ("?", "#", "..", "%", "\\")))


def pasta_da_uf(uf: str) -> str:
    regiao, pasta = UFS[str(uf).upper()]
    return f"{URL_RELATORIOS}{regiao}/{pasta}/"


def nome_do_arquivo_oficial(nome: str, uf: str, competencia: str) -> bool:
    """`pa-07-2026.7z` (ou com sufixo, ex. `-revisado`) da UF e competência."""
    ano, mes = competencia_valida(competencia)
    nome = Path(str(nome)).name
    return bool(_NOME_7Z.fullmatch(nome)) and \
        nome.startswith(f"{uf.lower()}-{mes:02d}-{ano:04d}")


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def _normal(texto) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(texto or ""))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def _texto(valor) -> str:
    return " ".join(str(valor or "").split())


def _decimal(valor) -> Decimal | None:
    """Célula → `Decimal` exato. O openpyxl entrega o número como float, e
    `str(float)` devolve o texto mais curto que reproduz o valor gravado."""
    if valor is None or (isinstance(valor, str) and valor.strip() in ("", "-")):
        return None
    if isinstance(valor, bool):
        raise InvalidOperation
    if isinstance(valor, (int, float)):
        numero = Decimal(str(valor))
    elif isinstance(valor, str) and re.fullmatch(r"\d+(\.\d+)?", valor.strip()):
        numero = Decimal(valor.strip())
    else:
        raise InvalidOperation
    if not numero.is_finite() or numero < 0 or numero.as_tuple().exponent < -CASAS:
        raise InvalidOperation
    return numero


@dataclass
class Leitura:
    uf: str = ""
    competencia: str = ""
    linhas: int = 0
    validas: int = 0
    recusas: Counter = field(default_factory=Counter)
    por_tipo: Counter = field(default_factory=Counter)
    recusadas: list[dict] = field(default_factory=list)


def relatorios_da_pasta(pasta: Path, uf: str, competencia: str) -> dict[str, Path]:
    """Os XLSX sintéticos da pasta, por relatório. Confere que TODOS são da
    mesma UF e competência pedidas e que nenhum esperado falta."""
    ano, mes = competencia_valida(competencia)
    achados: dict[str, Path] = {}
    for caminho in sorted(Path(pasta).iterdir()):
        if caminho.is_symlink() or not caminho.is_file():
            continue
        nome = unicodedata.normalize("NFC", caminho.name)
        m = _NOME_RELATORIO.fullmatch(nome)
        if not m:
            continue
        if (m.group(1), int(m.group(2)), int(m.group(3))) != (uf, mes, ano):
            raise LeiauteInesperado(f"{nome}: não é de {uf} {mes:02d}/{ano}")
        achados[m.group(4)] = caminho
    faltam = [r for r in (*RELATORIOS, ORIGEM) if r not in achados]
    if faltam:
        raise LeiauteInesperado(f"faltam os relatórios {faltam}")
    return achados


def _abrir(caminho: Path) -> list[tuple]:
    import openpyxl

    # o XLSX também é ZIP: as defesas comuns antes de abrir. As extensões são
    # as que os relatórios de jul/2026 trazem (o logotipo é PNG; comentário,
    # VML); nada disso é executado
    arquivos.conferir_zip(caminho, extensoes=frozenset(
        {".xml", ".rels", ".bin", ".png", ".vml", ""}))
    livro = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    try:
        # a origem de preços traz a legenda numa 2ª aba; o resto, uma só
        if len(livro.worksheets) != 1 and ORIGEM not in caminho.name:
            raise LeiauteInesperado(f"{caminho.name}: esperada uma aba")
        return list(livro.worksheets[0].iter_rows(values_only=True))
    finally:
        livro.close()


def origens(caminho: Path, uf: str) -> dict[str, str]:
    """Sigla de origem do preço de cada insumo, na coluna da UF."""
    linhas = _abrir(caminho)
    for i, linha in enumerate(linhas[:20]):
        normal = [_normal(v) for v in linha]
        if normal[:3] == ["codigo", "descricao do item", "unidade do item"]:
            if uf.lower() not in normal:
                raise LeiauteInesperado(f"origem de preços sem a coluna {uf}")
            coluna = normal.index(uf.lower())
            break
    else:
        raise LeiauteInesperado("origem de preços sem cabeçalho")
    saida = {}
    for linha in linhas[i + 1:]:
        codigo = _texto(linha[0]) if linha else ""
        if re.fullmatch(r"[MPEA]\d{4}", codigo) and len(linha) > coluna:
            sigla = _texto(linha[coluna])
            if re.fullmatch(r"[A-Z]{1,4}", sigla):
                saida[codigo] = sigla
    return saida


def ler(pasta: Path, *, uf: str, competencia: str,
        leitura: Leitura | None = None) -> Iterator[dict]:
    """As linhas VÁLIDAS dos relatórios sintéticos de uma UF e competência."""
    leitura = leitura if leitura is not None else Leitura()
    uf = str(uf).upper()
    if uf not in UFS:
        raise ValueError(f"UF desconhecida: {uf}")
    leitura.uf, leitura.competencia = uf, competencia
    relatorios = relatorios_da_pasta(pasta, uf, competencia)
    origem = origens(relatorios[ORIGEM], uf)
    for relatorio, (tipo, regime, cabecalho, coluna, improdutivo) in RELATORIOS.items():
        caminho = relatorios[relatorio]
        linhas = _abrir(caminho)
        if not linhas or tuple(_normal(v) for v in linhas[0][:len(cabecalho)]) != cabecalho:
            raise LeiauteInesperado(f"{caminho.name}: cabeçalho fora do conferido: "
                                    f"{linhas[0] if linhas else None}")
        vistos: dict[str, tuple] = {}
        saida: dict[str, dict] = {}
        for numero, linha in enumerate(linhas[1:], start=2):
            if not any(v not in (None, "") for v in linha):
                continue
            leitura.linhas += 1
            codigo = _texto(linha[0])

            def recusar(motivo: str) -> None:
                leitura.recusas[motivo] += 1
                if len(leitura.recusadas) < 200:
                    leitura.recusadas.append({"relatorio": relatorio, "linha": numero,
                                              "codigo": codigo, "motivo": motivo})

            if not _CODIGO[tipo].fullmatch(codigo):
                recusar(CODIGO_INVALIDO)
                continue
            if codigo in vistos:
                if vistos[codigo] == tuple(linha):
                    recusar(REPETIDA_IDENTICA)
                    continue
                recusar(CODIGO_REPETIDO)
                saida.pop(codigo, None)
                continue
            vistos[codigo] = tuple(linha)
            descricao = _texto(linha[1])
            if not descricao:
                recusar(SEM_DESCRICAO)
                continue
            try:
                valor = _decimal(linha[coluna] if len(linha) > coluna else None)
                ocioso = None if improdutivo is None else _decimal(
                    linha[improdutivo] if len(linha) > improdutivo else None)
            except InvalidOperation:
                recusar(VALOR_ILEGIVEL)
                continue
            if valor is None:
                recusar(SEM_PRECO)
                continue
            if valor == 0:
                recusar(PRECO_ZERADO)
                continue
            saida[codigo] = {
                "tipo": tipo, "regime": regime, "codigo": codigo,
                "descricao": descricao,
                "unidade": "h" if tipo == EQUIPAMENTO else (_texto(linha[2]) or None),
                "valor": valor, "valor_improdutivo": ocioso,
                "origem_preco": None if tipo == COMPOSICAO else origem.get(codigo),
                "planilha": unicodedata.normalize("NFC", caminho.name),
                "linha_planilha": numero,
            }
        # código repetido com valor diferente já saiu inteiro: não há qual
        # das duas escolher
        for linha in saida.values():
            leitura.validas += 1
            leitura.por_tipo[f"{tipo}:{regime}"] += 1
            yield linha


def chave_da_linha(competencia: str, uf: str, tipo: str, regime: str,
                   codigo: str) -> str:
    return f"{competencia}:{uf}:{tipo}:{regime}:{codigo}"


def linha_do_indice(bruta: dict, *, competencia: str, uf: str, sha256: str,
                    url: str, arquivo: str) -> dict:
    from . import evidencia as ev
    from .pncp_indice import texto_de_busca

    chave = chave_da_linha(competencia, uf, bruta["tipo"], bruta["regime"],
                           bruta["codigo"])
    valor = format(bruta["valor"], "f")
    ocioso = None if bruta["valor_improdutivo"] is None else \
        format(bruta["valor_improdutivo"], "f")
    return {
        "registro_id": hashlib.sha256(f"{sha256}:{chave}".encode()).hexdigest()[:40],
        "chave_linha": chave, "competencia": competencia, "uf": uf,
        "arquivo_sha256": sha256, "tipo": bruta["tipo"], "regime": bruta["regime"],
        "codigo": bruta["codigo"], "descricao": bruta["descricao"],
        "descricao_busca": texto_de_busca(f"{bruta['codigo']} {bruta['descricao']}"),
        "unidade": bruta["unidade"], "valor": valor, "valor_improdutivo": ocioso,
        "origem_preco": bruta["origem_preco"], "planilha": bruta["planilha"],
        "linha_planilha": bruta["linha_planilha"], "url_arquivo": url,
        "arquivo": arquivo,
        "hash_linha": ev.hash_da_linha({"chave": chave, "valor": valor,
                                        "improdutivo": ocioso,
                                        "linha": bruta["linha_planilha"]}),
        "versao_parser": VERSAO_PARSER,
    }


# ---------------------------------------------------------------------------
# Versões
# ---------------------------------------------------------------------------
class Armazem(Protocol):
    def versao(self, competencia: str, uf: str, sha256: str) -> dict | None: ...

    def versao_publicada(self, competencia: str, uf: str) -> dict | None: ...

    def registrar_versao(self, competencia: str, uf: str, sha256: str, **campos) -> None: ...

    def gravar_registros(self, linhas: list[dict]) -> None: ...

    def publicar(self, competencia: str, uf: str, sha256: str, **campos) -> None: ...

    def buscar(self, termos: list[str], **filtros) -> list[dict]: ...


class ArmazemEmMemoria:
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
               regime=None, tipo=None, limite=50):
        vigentes = [l for l in self.registros.values()
                    if l["vigente"] and (uf is None or l["uf"] == uf)]
        alvo = competencia or max((l["competencia"] for l in vigentes), default=None)
        procurados = set(termos)
        achados = []
        for l in vigentes:
            if l["competencia"] != alvo or (tipo and l["tipo"] != tipo):
                continue
            if regime and l["regime"] not in (regime, NAO_SE_APLICA):
                continue
            if codigo:
                if l["codigo"] != codigo:
                    continue
                comuns = 0
            else:
                comuns = len(procurados & set(l["descricao_busca"].split()))
                if not comuns:
                    continue
            achados.append((comuns, l["tipo"], l["codigo"], l))
        achados.sort(key=lambda t: (-t[0], t[1], t[2]))
        return [l for *_, l in achados[:limite]]


@dataclass
class Importacao:
    competencia: str = ""
    uf: str = ""
    sha256: str = ""
    arquivo: str = ""
    desfecho: str = ""             # publicado | ja_publicado | recusado
    motivo: str = ""
    linhas: int = 0
    validas: int = 0
    recusas: Counter = field(default_factory=Counter)
    por_tipo: Counter = field(default_factory=Counter)
    validas_na_versao_anterior: int | None = None

    def para_registro(self) -> dict:
        saida = dict(vars(self))
        saida["recusas"], saida["por_tipo"] = dict(self.recusas), dict(self.por_tipo)
        return saida


def importar(armazem: Armazem, pasta: Path, *, uf: str, competencia: str,
             sha256: str, url: str, arquivo: str) -> Importacao:
    """
    Importa os relatórios JÁ EXTRAÍDOS do 7-Zip oficial (`pasta`) e publica
    a versão, ou a recusa. A versão é (competência, UF, SHA-256 do 7-Zip):
    reimportar o mesmo arquivo não faz nada; o "revisado" é versão nova,
    publicada inteira, e a anterior fica gravada.
    """
    uf = str(uf).upper()
    if not url_oficial(url):
        raise ValueError(f"endereço fora da publicação do SICRO: {url}")
    if not nome_do_arquivo_oficial(arquivo, uf, competencia):
        raise ValueError(f"{arquivo} não é o arquivo de {uf} {competencia}")
    feito = Importacao(competencia=competencia, uf=uf, sha256=sha256,
                       arquivo=Path(arquivo).name)
    existente = armazem.versao(competencia, uf, sha256)
    if existente and existente.get("estado") == PUBLICADO:
        feito.desfecho = "ja_publicado"
        return feito
    leitura = Leitura()
    brutas = list(ler(pasta, uf=uf, competencia=competencia, leitura=leitura))
    feito.linhas, feito.validas = leitura.linhas, leitura.validas
    feito.recusas, feito.por_tipo = leitura.recusas, leitura.por_tipo
    base = dict(arquivo=feito.arquivo, url=url, linhas=feito.linhas,
                validas=feito.validas, recusas=dict(feito.recusas),
                versao_parser=VERSAO_PARSER)

    def recusar(motivo: str) -> Importacao:
        feito.desfecho, feito.motivo = RECUSADO, motivo
        armazem.registrar_versao(competencia, uf, sha256, estado=RECUSADO,
                                 motivo=motivo, **base)
        return feito

    if not brutas:
        return recusar("nenhuma referência válida")
    publicada = armazem.versao_publicada(competencia, uf)
    if publicada is not None:
        feito.validas_na_versao_anterior = int(publicada.get("validas") or 0)
        if feito.validas < feito.validas_na_versao_anterior * PISO_DE_REDUCAO:
            return recusar(f"{feito.validas} referências contra "
                           f"{feito.validas_na_versao_anterior} da versão "
                           "publicada — redução acima do tolerado")
    armazem.registrar_versao(competencia, uf, sha256, estado=IMPORTANDO, motivo="",
                             recusadas=leitura.recusadas, **base)
    linhas = [linha_do_indice(b, competencia=competencia, uf=uf, sha256=sha256,
                              url=url, arquivo=feito.arquivo) for b in brutas]
    for inicio in range(0, len(linhas), LOTE):
        armazem.gravar_registros(linhas[inicio:inicio + LOTE])
    armazem.publicar(competencia, uf, sha256, publicado_em=datetime.now(
        timezone.utc).isoformat(timespec="seconds"))
    feito.desfecho = PUBLICADO
    return feito


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
@dataclass
class ReferenciaSicro:
    """Uma linha do SICRO como ela vai para a tela e para o relatório."""

    registro_id: str
    tipo: str
    codigo: str
    descricao: str
    unidade: str | None
    uf: str
    competencia: str
    regime: str
    valor: Decimal
    valor_improdutivo: Decimal | None
    origem_preco: str | None
    planilha: str
    linha_planilha: int
    url_arquivo: str
    arquivo: str
    arquivo_sha256: str
    natureza: str = NATUREZA

    @property
    def rotulo_regime(self) -> str:
        return ROTULO_REGIME.get(self.regime, self.regime)

    @property
    def rotulo_tipo(self) -> str:
        return ROTULO_TIPO.get(self.tipo, self.tipo)

    @property
    def rotulo_origem(self) -> str | None:
        if not self.origem_preco:
            return None
        return ORIGENS.get(self.origem_preco, self.origem_preco)

    @property
    def identificacao(self) -> str:
        return (f"SICRO {self.rotulo_tipo} {self.codigo} — {self.uf} "
                f"{self.competencia[5:]}/{self.competencia[:4]}")


def referencia_da_linha(linha: dict) -> ReferenciaSicro | None:
    """Linha do índice → referência; sem rastreabilidade, não chega à tela."""
    try:
        valor = Decimal(str(linha["valor"]))
        ocioso = linha.get("valor_improdutivo")
        ocioso = None if ocioso in (None, "") else Decimal(str(ocioso))
        competencia_valida(linha["competencia"])
        if not valor.is_finite() or valor <= 0 or \
                (ocioso is not None and (not ocioso.is_finite() or ocioso < 0)):
            return None
        tipo, codigo = str(linha["tipo"]), str(linha["codigo"])
        if tipo not in _CODIGO or not _CODIGO[tipo].fullmatch(codigo):
            return None
        if not url_oficial(linha["url_arquivo"]) or not linha.get("registro_id"):
            return None
        return ReferenciaSicro(
            registro_id=str(linha["registro_id"]), tipo=tipo, codigo=codigo,
            descricao=str(linha.get("descricao") or ""), unidade=linha.get("unidade"),
            uf=str(linha["uf"]), competencia=str(linha["competencia"]),
            regime=str(linha["regime"]), valor=valor, valor_improdutivo=ocioso,
            origem_preco=linha.get("origem_preco"), planilha=str(linha["planilha"]),
            linha_planilha=int(linha["linha_planilha"]),
            url_arquivo=str(linha["url_arquivo"]), arquivo=str(linha.get("arquivo") or ""),
            arquivo_sha256=str(linha.get("arquivo_sha256") or ""))
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None


def consultar(buscar: Callable[..., list], *, termo: str = "",
              codigo: str | None = None, uf: str = "PA",
              competencia: str | None = None, regime: str | None = SEM_DESONERACAO,
              tipo: str | None = None, limite: int = 50) -> list[ReferenciaSicro]:
    """Custo referencial do SICRO por código ou termos. Filtro fora da regra
    é `ValueError` e não vai ao índice; erro do índice sobe."""
    from .compras_gov import _tokens
    from .pncp_indice import texto_de_busca

    uf = str(uf or "").upper()
    if uf not in UFS:
        raise ValueError("UF desconhecida")
    codigo = str(codigo or "").strip().upper() or None
    if codigo is not None and not any(p.fullmatch(codigo) for p in _CODIGO.values()):
        raise ValueError("código do SICRO: 7 dígitos (composição) ou letra e 4 "
                         "dígitos (insumo)")
    if competencia is not None:
        competencia_valida(competencia)
    if regime is not None and regime not in (SEM_DESONERACAO, COM_DESONERACAO):
        raise ValueError("regime desconhecido")
    if tipo is not None and tipo not in TIPOS:
        raise ValueError("tipo desconhecido")
    termos = sorted({t.lower() for t in _tokens(texto_de_busca(termo)) if t.isalnum()},
                    key=lambda t: (-len(t), t))[:12]
    if not termos and codigo is None:
        return []
    linhas = buscar([] if codigo else termos, codigo=codigo, uf=uf,
                    competencia=competencia, regime=regime, tipo=tipo,
                    limite=max(1, min(int(limite), 200)))
    saida = []
    for linha in linhas or []:
        if isinstance(linha, dict):
            referencia = referencia_da_linha(linha)
            if referencia is not None:
                saida.append(referencia)
    return saida


# ---------------------------------------------------------------------------
# Confronto com a edição oficial em PDF — leitor independente do XLSX
# ---------------------------------------------------------------------------
_VALOR_PDF = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2,4}$")
# o código vem sozinho na linha, ou — nos componentes A#### de um
# equipamento composto — seguido da descrição na mesma linha
_CODIGO_PDF = re.compile(r"^(\d{7}|[MPEA]\d{4})(?:\s.*)?$")


def valores_do_pdf(linhas: list[str], *, posicao: int = -1) -> dict[str, Decimal]:
    """`{código: valor}` do relatório sintético em PDF. Os números em moeda
    entre um código e o próximo são as colunas de valor da linha; `posicao`
    escolhe qual (-1, o último: custo unitário, preço, custo da mão de obra
    ou custo IMPRODUTIVO do equipamento; -2, o produtivo). Item sem preço
    ("-") não aparece."""
    saida: dict[str, Decimal] = {}
    atual, valores = None, []
    for bruto in linhas + ["0000000"]:
        linha = bruto.strip()
        achado = _CODIGO_PDF.fullmatch(linha)
        if achado:
            if atual is not None and len(valores) >= abs(posicao):
                saida[atual] = valores[posicao]
            atual, valores = achado.group(1), []
        elif _VALOR_PDF.fullmatch(linha):
            valores.append(Decimal(linha.replace(".", "").replace(",", ".")))
    return saida


@dataclass
class ConfrontoPDF:
    conferidas: int = 0
    iguais: int = 0
    divergentes: list[dict] = field(default_factory=list)
    ausentes_no_pdf: list[str] = field(default_factory=list)

    def para_registro(self) -> dict:
        return {"conferidas": self.conferidas, "iguais": self.iguais,
                "divergentes": self.divergentes[:50],
                "ausentes_no_pdf": self.ausentes_no_pdf[:50]}


def confrontar_com_pdf(linhas_do_indice: list[dict], do_pdf: dict[str, Decimal],
                       *, campo: str = "valor") -> ConfrontoPDF:
    relato = ConfrontoPDF()
    for linha in linhas_do_indice:
        relato.conferidas += 1
        esperado = do_pdf.get(linha["codigo"])
        if esperado is None:
            relato.ausentes_no_pdf.append(linha["codigo"])
        elif Decimal(str(linha[campo])) == esperado:
            relato.iguais += 1
        else:
            relato.divergentes.append({"codigo": linha["codigo"],
                                       "xlsx": str(linha[campo]),
                                       "pdf": format(esperado, "f")})
    return relato
