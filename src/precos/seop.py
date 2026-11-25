"""
SEOP-PA (Secretaria de Estado de Obras Públicas do Pará) — custo de
referência de ENGENHARIA, publicado em PDF, com importação SUPERVISIONADA.

Como o SINAPI, não é preço de compra: não entra em `fontes_padrao()` nem na
cesta. É a tabela própria do ente, usável como sistema alternativo nas
condições do art. 23, § 3º, da Lei 14.133 — juízo do órgão, não deste código.

Publicação conferida em 23/11/2026 (`https://seop.pa.gov.br/planilha-de-custo-0`):
a SEOP só publica PDF (gerado do Excel, com texto extraível). Para outubro de
2026 são dois arquivos, de 02/10/2026:

* `plainha_padrao_outubro_2026.pdf` (48 páginas, sha256 62cfffd2…) — a
  PLANILHA PADRÃO: item, código de 6 dígitos, descrição, unidade e total. O
  cabeçalho diz "PLANILHA PADRÃO - OUTUBRO 2026 (SEM BDI) - SEM DESONERAÇÃO" e
  traz as leis sociais horista (L.S.h) e mensalista (L.S.m);
* `cpus_outubro_2026.pdf` (511 páginas, sha256 dd870425…) — as COMPOSIÇÕES
  analíticas: cada uma abre com "Composição <código> SEOP <descrição> <und>
  1,0000000 <valor> <valor>" e fecha com "Valor do BDI => 0,00".

PDF não é estruturado como planilha. Por isso a importação é supervisionada:

1. o leitor extrai cada linha com a PÁGINA de origem e recusa, contando, o que
   não fecha (código sem valor, valor zero, código repetido);
2. cada linha da planilha é confrontada com a composição de mesmo código no
   PDF analítico — mesmo código, mesma unidade e mesmo valor;
3. a versão fica EM CONFERÊNCIA, com o relatório, e só é publicada quando uma
   pessoa a APROVA (`aprovar`, com o nome de quem conferiu). Divergência não
   impede a conferência, mas impede a aprovação sem decisão explícita.
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
from typing import Callable, Protocol

from . import evidencia as ev

FONTE_ID = "seop_pa"
NOME = "SEOP-PA — Planilha Padrão (custos de engenharia)"
VERSAO_PARSER = "seop-pa-2026-11-23.1"
URL_PAGINA = "https://seop.pa.gov.br/planilha-de-custo-0"
URL_BASE = "https://seop.pa.gov.br/sites/default/files/"
NATUREZA = "custo_referencia_engenharia"
ROTULO_NATUREZA = ("custo de referência de engenharia (SEOP-PA), não preço "
                   "de compra")
MESES = ("janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro")
PISO_DE_REDUCAO = Decimal("0.5")

EM_CONFERENCIA, PUBLICADO, RECUSADO = "em_conferencia", "publicado", "recusado"

# motivos de recusa da linha (estáveis: vão para o relatório e para os testes)
VALOR_ZERO = "VALOR_ZERO"
SEM_VALOR = "SEM_VALOR_NA_LINHA"
SEM_UNIDADE = ev.SEM_UNIDADE
CODIGO_REPETIDO = "CODIGO_REPETIDO_NA_PLANILHA"
# motivos do confronto com o PDF analítico
SEM_COMPOSICAO = "SEM_COMPOSICAO_NO_ANALITICO"
VALOR_DIVERGENTE = "VALOR_DIFERENTE_DO_ANALITICO"
UNIDADE_DIVERGENTE = "UNIDADE_DIFERENTE_DO_ANALITICO"


class ArquivoInvalido(ValueError):
    """O PDF não é a publicação esperada — não é lido adiante."""


def _sem_acento(texto: str) -> str:
    base = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in base if not unicodedata.combining(c))


def competencia_valida(texto: str) -> tuple[int, int]:
    achado = re.fullmatch(r"(\d{4})-(\d{2})", str(texto or "").strip())
    if not achado or not 1 <= int(achado.group(2)) <= 12 or \
            not 2000 <= int(achado.group(1)) <= 2100:
        raise ValueError("competência no formato AAAA-MM")
    return int(achado.group(1)), int(achado.group(2))


# Os nomes de arquivo da SEOP não seguem padrão (`plainha_padrao_outubro_2026`,
# `planilha_padrao_seop_outubro_2025`, `cpus_seop_marco_2026`…): o endereço
# vem da página oficial e é conferido aqui — só o servidor da SEOP, só PDF
# da pasta de arquivos, nome só com letras, dígitos e sublinhado.
_ARQUIVO_SEOP = re.compile(
    r"^https://seop\.pa\.gov\.br/sites/default/files/[a-z0-9_]{5,120}\.pdf$")


def url_permitida(url: str) -> bool:
    return bool(_ARQUIVO_SEOP.fullmatch(str(url or "")))


def _decimal(texto: str) -> Decimal | None:
    """'2.175,00' → Decimal('2175.00'). Só o formato brasileiro do PDF."""
    try:
        return ev.ler_decimal(str(texto).strip(), formato="br")
    except (ev.ValorInvalido, InvalidOperation):
        return None


_VALOR = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$")
_ITEM = re.compile(r"^\d{1,3}(?:\.\d{1,4})+$")
_GRUPO = re.compile(r"^\d{1,3}$")
_CODIGO = re.compile(r"^[0-9]{6}$")
_CABECALHO = re.compile(
    r"PLANILHA PADR[ÃA]O\s*-\s*([A-ZÇÃÉÍÓÚ]+)\s+(\d{4})\s*\(([^)]*)\)\s*-\s*"
    r"([A-ZÇÃ ]+DESONERA[ÇC][ÃA]O)", re.IGNORECASE)
_LEIS = re.compile(r"L\.S\.(h|m)\s*\n\s*([\d.,]+)%")
# Linhas que o Excel repete no topo de toda página
_REPETIDAS = frozenset({
    "L.S.h", "L.S.m", "Item", "Código", "Descrição", "Und", "Total",
    "GOVERNO DO ESTADO DO PARÁ", "SECRETARIA DE ESTADO DE OBRAS PÚBLICAS - SEOP",
    "DIRETORIA TÉCNICA - DITEC", "COORDENADORIA DE ORÇAMENTOS E CUSTOS"})


def _limpar(texto: str) -> str:
    return " ".join(str(texto or "").split())


@dataclass
class Linha:
    """Uma linha da planilha padrão, com a página do PDF de onde veio."""

    competencia: str
    item: str
    codigo: str
    descricao: str
    unidade: str
    valor: Decimal
    grupo: str
    pagina: int

    @property
    def chave(self) -> str:
        return f"{self.competencia}:{self.codigo}"


@dataclass
class Cabecalho:
    competencia: str = ""
    bdi: str = ""                 # como a publicação diz: "SEM BDI"
    desoneracao: str = ""         # "SEM DESONERAÇÃO"
    leis_sociais: dict = field(default_factory=dict)   # {"horista": "119,42%"}


@dataclass
class Leitura:
    cabecalho: Cabecalho = field(default_factory=Cabecalho)
    paginas: int = 0
    lidas: int = 0
    validas: int = 0
    motivos: Counter = field(default_factory=Counter)
    recusadas: list[dict] = field(default_factory=list)
    por_pagina: dict = field(default_factory=dict)


def _paginas(caminho: Path) -> list[str]:
    import pymupdf

    with pymupdf.open(caminho) as documento:
        if documento.is_encrypted:
            raise ArquivoInvalido("PDF cifrado")
        return [pagina.get_text() for pagina in documento]


def _cabecalho(textos: list[str], competencia: str) -> Cabecalho:
    ano, mes = competencia_valida(competencia)
    junto = "\n".join(textos[:3])
    achado = _CABECALHO.search(junto)
    if not achado:
        raise ArquivoInvalido("o PDF não tem o cabeçalho da Planilha Padrão "
                              "da SEOP")
    nome_mes = _sem_acento(achado.group(1)).lower()
    if nome_mes not in MESES or (MESES.index(nome_mes) + 1, int(achado.group(2))) \
            != (mes, ano):
        raise ArquivoInvalido(
            f"a planilha é de {achado.group(1).lower()} de {achado.group(2)}, "
            f"esperado {MESES[mes - 1]} de {ano}")
    leis = {("horista" if s == "h" else "mensalista"): f"{v}%"
            for s, v in _LEIS.findall(junto)}
    if set(leis) != {"horista", "mensalista"}:
        raise ArquivoInvalido("o PDF não traz as leis sociais (L.S.h e L.S.m)")
    return Cabecalho(competencia=competencia, bdi=_limpar(achado.group(3)).upper(),
                     desoneracao=_limpar(achado.group(4)).upper(),
                     leis_sociais=leis)


def ler_planilha(caminho: Path, competencia: str, *,
                 leitura: Leitura | None = None,
                 textos: list[str] | None = None) -> list[Linha]:
    """
    As linhas válidas da Planilha Padrão. Cada uma é "item, código,
    descrição (uma ou mais linhas), unidade, total". O total é a última linha
    no formato monetário; a unidade, a linha imediatamente antes dele.
    """
    leitura = leitura if leitura is not None else Leitura()
    textos = textos if textos is not None else _paginas(caminho)
    leitura.paginas = len(textos)
    leitura.cabecalho = _cabecalho(textos, competencia)
    vistos: dict[str, int] = {}
    saida: list[Linha] = []
    grupo = ""
    for numero, texto in enumerate(textos, start=1):
        linhas = [_limpar(l) for l in texto.splitlines()]
        linhas = [l for l in linhas if l and l not in _REPETIDAS
                  and not l.startswith("PLANILHA PADR")
                  and not re.fullmatch(r"[\d.,]+%", l)]
        contagem = Counter()
        i = 0
        while i < len(linhas):
            atual = linhas[i]
            # cabeçalho de grupo: "1" + "SERVIÇOS PRELIMINARES:" (sem código)
            if _GRUPO.fullmatch(atual) and i + 1 < len(linhas) and \
                    not _CODIGO.fullmatch(linhas[i + 1]):
                grupo = linhas[i + 1].rstrip(":")
                i += 2
                continue
            if not (_ITEM.fullmatch(atual) and i + 1 < len(linhas)
                    and _CODIGO.fullmatch(linhas[i + 1])):
                i += 1
                continue
            item, codigo = atual, linhas[i + 1]
            j = i + 2
            corpo: list[str] = []
            while j < len(linhas) and not _VALOR.fullmatch(linhas[j]) and \
                    not (_ITEM.fullmatch(linhas[j]) and j + 1 < len(linhas)
                         and _CODIGO.fullmatch(linhas[j + 1])):
                corpo.append(linhas[j])
                j += 1
            leitura.lidas += 1
            contagem["lidas"] += 1
            motivo = ""
            if j >= len(linhas) or not _VALOR.fullmatch(linhas[j]):
                motivo = SEM_VALOR
            elif len(corpo) < 2:
                motivo = SEM_UNIDADE
            valor = _decimal(linhas[j]) if not motivo else None
            if not motivo and (valor is None or valor <= 0):
                motivo = VALOR_ZERO
            if not motivo and codigo in vistos:
                motivo = CODIGO_REPETIDO
            if motivo:
                leitura.motivos[motivo] += 1
                contagem[motivo] += 1
                leitura.recusadas.append({"pagina": numero, "item": item,
                                          "codigo": codigo, "motivo": motivo,
                                          "texto": " ".join(corpo)[:200]})
                i = j + 1 if motivo != SEM_VALOR else j
                continue
            vistos[codigo] = numero
            saida.append(Linha(
                competencia=competencia, item=item, codigo=codigo,
                descricao=" ".join(corpo[:-1]), unidade=corpo[-1],
                valor=valor, grupo=grupo, pagina=numero))
            leitura.validas += 1
            contagem["validas"] += 1
            i = j + 1
        leitura.por_pagina[numero] = dict(contagem)
    return saida


# ---------------------------------------------------------------------------
# PDF analítico: o valor de cada composição, para o confronto
# ---------------------------------------------------------------------------
_ABRE_COMPOSICAO = re.compile(r"^Composição$")


def ler_analitico(caminho: Path, *, textos: list[str] | None = None
                  ) -> dict[str, dict]:
    """
    {código: {"unidade", "valor", "pagina"}} das composições PRINCIPAIS do
    PDF analítico — a linha "Composição <código> SEOP <descrição> <und>
    1,0000000 <valor unitário> <total>" que abre cada bloco. Composições
    auxiliares (dentro dos blocos) não entram: o valor delas é o do bloco
    próprio.
    """
    textos = textos if textos is not None else _paginas(caminho)
    saida: dict[str, dict] = {}
    for numero, texto in enumerate(textos, start=1):
        linhas = [_limpar(l) for l in texto.splitlines()]
        linhas = [l for l in linhas if l]
        for i, atual in enumerate(linhas):
            if not _ABRE_COMPOSICAO.fullmatch(atual) or i + 1 >= len(linhas):
                continue
            achado = re.fullmatch(r"([0-9]{6}) SEOP", linhas[i + 1])
            if not achado:
                continue
            # descrição (1+ linhas), unidade, "1,0000000", valor, total
            for k in range(i + 2, min(i + 12, len(linhas) - 2)):
                if linhas[k] == "1,0000000" and _VALOR.fullmatch(linhas[k + 1]):
                    saida.setdefault(achado.group(1), {
                        "unidade": linhas[k - 1],
                        "valor": _decimal(linhas[k + 1]), "pagina": numero})
                    break
    return saida


@dataclass
class Confronto:
    conferidas: int = 0
    iguais: int = 0
    divergentes: list[dict] = field(default_factory=list)
    motivos: Counter = field(default_factory=Counter)

    def para_registro(self) -> dict:
        return {"conferidas": self.conferidas, "iguais": self.iguais,
                "divergentes": self.divergentes, "motivos": dict(self.motivos)}


def confrontar(linhas: list[Linha], analitico: dict[str, dict]) -> Confronto:
    """Cada linha da planilha contra a composição de mesmo código."""
    confronto = Confronto()
    for linha in linhas:
        confronto.conferidas += 1
        composicao = analitico.get(linha.codigo)
        motivo = ""
        if composicao is None:
            motivo = SEM_COMPOSICAO
        elif composicao["valor"] != linha.valor:
            motivo = VALOR_DIVERGENTE
        elif _sem_acento(composicao["unidade"]).lower() != \
                _sem_acento(linha.unidade).lower():
            motivo = UNIDADE_DIVERGENTE
        if not motivo:
            confronto.iguais += 1
            continue
        confronto.motivos[motivo] += 1
        confronto.divergentes.append({
            "codigo": linha.codigo, "item": linha.item, "pagina": linha.pagina,
            "motivo": motivo, "planilha": format(linha.valor, "f"),
            "unidade": linha.unidade,
            "analitico": None if composicao is None
            else format(composicao["valor"], "f"),
            "unidade_analitico": None if composicao is None
            else composicao["unidade"],
            "pagina_analitico": None if composicao is None
            else composicao["pagina"]})
    return confronto


# ---------------------------------------------------------------------------
# Versão supervisionada
# ---------------------------------------------------------------------------
def linha_do_indice(l: Linha, *, sha256: str, url: str, cabecalho: Cabecalho,
                    confronto: dict | None) -> dict:
    from .pncp_indice import texto_de_busca

    bruto = {"item": l.item, "codigo": l.codigo, "valor": format(l.valor, "f"),
             "pagina": l.pagina, "competencia": l.competencia}
    return {
        "registro_id": hashlib.sha256(
            f"{sha256}:{l.chave}".encode()).hexdigest()[:40],
        "chave_linha": l.chave, "competencia": l.competencia,
        "item": l.item, "codigo": l.codigo, "descricao": l.descricao,
        "descricao_busca": texto_de_busca(l.descricao),
        "unidade": l.unidade, "valor": format(l.valor, "f"),
        "grupo": l.grupo or None, "pagina": l.pagina,
        "bdi": cabecalho.bdi, "desoneracao": cabecalho.desoneracao,
        "conferencia": confronto or {},
        "arquivo_sha256": sha256, "url_arquivo": url,
        "hash_linha": ev.hash_da_linha(bruto),
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

    def buscar(self, termos, *, codigo=None, competencia=None, limite=50):
        procurados = set(termos)
        achados = []
        for linha in self.registros.values():
            if not linha["vigente"]:
                continue
            if competencia and linha["competencia"] != competencia:
                continue
            if codigo:
                if linha["codigo"] != codigo:
                    continue
                comuns = 0
            else:
                comuns = len(procurados & set(linha["descricao_busca"].split()))
                if not comuns:
                    continue
            achados.append((comuns, linha["competencia"], linha))
        achados.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [linha for *_, linha in achados[:limite]]


@dataclass
class Importacao:
    competencia: str = ""
    sha256: str = ""
    sha256_analitico: str = ""
    desfecho: str = ""          # em_conferencia | ja_importado | recusado
    motivo: str = ""
    paginas: int = 0
    lidas: int = 0
    validas: int = 0
    recusas: Counter = field(default_factory=Counter)
    cabecalho: dict = field(default_factory=dict)
    confronto: dict = field(default_factory=dict)

    def para_registro(self) -> dict:
        saida = dict(vars(self))
        saida["recusas"] = dict(self.recusas)
        return saida


def _sha(caminho: Path) -> str:
    from . import arquivos

    return arquivos.sha256_do_arquivo(caminho)


def importar(armazem: Armazem, planilha: Path, *, competencia: str, url: str,
             analitico: Path | None = None, url_analitico: str | None = None
             ) -> Importacao:
    """
    Lê a Planilha Padrão, confronta com o PDF analítico (quando dado) e grava
    a versão EM CONFERÊNCIA — invisível para a consulta até `aprovar`.
    Idempotente: o mesmo PDF já importado não é relido.
    """
    if not url_permitida(url) or (url_analitico and not url_permitida(url_analitico)):
        raise ValueError("o PDF da SEOP só é aceito da pasta oficial de "
                         "arquivos de seop.pa.gov.br")
    competencia_valida(competencia)
    sha = _sha(planilha)
    feito = Importacao(competencia=competencia, sha256=sha)
    existente = armazem.versao(competencia, sha)
    if existente and existente.get("estado") in (EM_CONFERENCIA, PUBLICADO):
        feito.desfecho = "ja_importado"
        return feito
    leitura = Leitura()
    linhas = ler_planilha(planilha, competencia, leitura=leitura)
    feito.paginas, feito.lidas, feito.validas = (leitura.paginas, leitura.lidas,
                                                 leitura.validas)
    feito.recusas = leitura.motivos
    cab = leitura.cabecalho
    feito.cabecalho = {"bdi": cab.bdi, "desoneracao": cab.desoneracao,
                       "leis_sociais": cab.leis_sociais}
    por_codigo: dict[str, dict] = {}
    if analitico is not None:
        feito.sha256_analitico = _sha(analitico)
        confronto = confrontar(linhas, ler_analitico(analitico))
        feito.confronto = confronto.para_registro()
        por_codigo = {d["codigo"]: d for d in confronto.divergentes}

    def recusar(motivo: str) -> Importacao:
        feito.desfecho, feito.motivo = RECUSADO, motivo
        armazem.registrar_versao(
            competencia, sha, estado=RECUSADO, url=url, motivo=motivo,
            lidas=feito.lidas, validas=feito.validas,
            recusas=dict(feito.recusas), versao_parser=VERSAO_PARSER)
        return feito

    if not linhas:
        return recusar("nenhuma linha com valor válido")
    publicada = armazem.versao_publicada(competencia)
    if publicada is not None and \
            feito.validas < int(publicada.get("validas") or 0) * PISO_DE_REDUCAO:
        return recusar(f"{feito.validas} linhas válidas contra "
                       f"{publicada.get('validas')} da versão publicada")
    armazem.registrar_versao(
        competencia, sha, estado=EM_CONFERENCIA, url=url,
        url_analitico=url_analitico, sha256_analitico=feito.sha256_analitico,
        motivo="", paginas=feito.paginas, lidas=feito.lidas,
        validas=feito.validas, recusas=dict(feito.recusas),
        recusadas=leitura.recusadas[:500], cabecalho=feito.cabecalho,
        confronto=feito.confronto, versao_parser=VERSAO_PARSER)
    armazem.gravar_registros([
        linha_do_indice(l, sha256=sha, url=url, cabecalho=cab,
                        confronto=por_codigo.get(l.codigo)) for l in linhas])
    feito.desfecho = EM_CONFERENCIA
    return feito


class AprovacaoRecusada(ValueError):
    """A versão não pode ser publicada — a mensagem diz o que falta."""


def aprovar(armazem: Armazem, *, competencia: str, sha256: str, por: str,
            aceitar_divergencias: bool = False) -> dict:
    """
    O ato HUMANO que publica a versão conferida. Exige quem conferiu; com
    divergência no confronto, exige também a decisão explícita de aceitá-la.
    """
    versao = armazem.versao(competencia, sha256)
    if versao is None or versao.get("estado") != EM_CONFERENCIA:
        raise AprovacaoRecusada("não há versão em conferência com esse SHA-256")
    if len(_limpar(por)) < 3:
        raise AprovacaoRecusada("identifique quem conferiu a versão")
    divergentes = len((versao.get("confronto") or {}).get("divergentes") or [])
    if not versao.get("confronto"):
        raise AprovacaoRecusada("a versão não foi confrontada com o PDF "
                                "analítico das composições")
    if divergentes and not aceitar_divergencias:
        raise AprovacaoRecusada(
            f"{divergentes} linha(s) diferem do PDF analítico: confira e "
            "aprove aceitando as divergências, ou reimporte")
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    armazem.publicar(competencia, sha256, aprovado_por=_limpar(por)[:120],
                     aprovado_em=agora, publicado_em=agora,
                     divergencias_aceitas=divergentes)
    return armazem.versao(competencia, sha256)


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
def consultar(buscar: Callable[..., list], *, termo: str = "",
              codigo: str | None = None, competencia: str | None = None,
              limite: int = 50) -> list[dict]:
    from .compras_gov import _tokens
    from .pncp_indice import texto_de_busca

    codigo = str(codigo or "").strip() or None
    if codigo is not None and not _CODIGO.fullmatch(codigo):
        raise ValueError("código da SEOP tem 6 dígitos")
    if competencia is not None:
        competencia_valida(competencia)
    termos = sorted({p.lower() for p in _tokens(texto_de_busca(termo))
                     if p.isalnum()}, key=lambda p: (-len(p), p))[:12]
    if not termos and codigo is None:
        return []
    linhas = buscar(termos if codigo is None else [], codigo=codigo,
                    competencia=competencia,
                    limite=max(1, min(int(limite), 200)))
    return [descrever(l) for l in linhas or [] if isinstance(l, dict)]


def descrever(linha: dict) -> dict:
    ano, mes = competencia_valida(linha["competencia"])
    return {
        **{k: linha.get(k) for k in (
            "registro_id", "chave_linha", "competencia", "item", "codigo",
            "descricao", "unidade", "valor", "grupo", "pagina", "bdi",
            "desoneracao", "arquivo_sha256", "url_arquivo", "versao_parser")},
        "competencia_exibicao": f"{MESES[mes - 1]}/{ano}",
        "natureza": NATUREZA, "rotulo_natureza": ROTULO_NATUREZA,
        "fonte": NOME, "url_fonte": URL_PAGINA,
        "url_verificacao": f"{linha['url_arquivo']}#page={int(linha['pagina'])}",
    }
