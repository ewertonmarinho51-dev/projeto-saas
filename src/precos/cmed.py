"""
CMED (Anvisa) — preço máximo regulado de medicamentos, em consulta própria.

Não é preço de compra praticado: é TETO REGULATÓRIO. A CMED fixa o Preço
Fábrica (PF) e o Preço Máximo de Venda ao Governo (PMVG) de cada apresentação
registrada; a compra pública não pode pagar acima do teto aplicável. Por
isso não entra em `fontes_padrao()` nem na cesta — o preço praticado do BPS
continua sendo o da pesquisa; a CMED diz até onde ele pode ir.

Publicação conferida em 24/11/2026: a página
`www.gov.br/anvisa/pt-br/assuntos/medicamentos/cmed/precos` linka duas
planilhas da mesma publicação, `lista_pmc_…xlsx` e `lista_pmvg_…xlsx`. A de
09/11/2026 17h30 (`lista_pmvg_20261109_111901662.xlsx`, 13.617.885 bytes,
sha256 5a18ae40…9478dae) tem a aba "Cabeçalho", com a data e as regras, e a
aba "Lista PMVG": 26.694 apresentações, uma por código GGREM (15 dígitos,
único), com o PF e o PMVG em 26 colunas — sem impostos, ICMS 0% e cada
alíquota de 12% a 23%, com e sem a de Área de Livre Comércio (ALC).

A regra do teto, nas palavras do próprio cabeçalho: para os medicamentos do
Anexo I da Resolução CTE-CMED (coluna CAP = "Sim"), o PMVG resulta da
aplicação do Coeficiente de Adequação de Preços ao PF; para os demais, "o
limite nas vendas à administração pública corresponde ao PF aplicável à
respectiva alíquota". A coluna PMVG vem preenchida para TODOS (PF × 0,802…),
então quem escolhe a coluna é a regra — `teto_governo`, aqui —, não a
planilha.

O asterisco ao lado do valor ("R$ 54,23*") marca apresentação isenta de
ICMS (CONFAZ 87 ou ICMS 0% = "Sim"); conferido nas 26.694 linhas: aparece
exatamente nelas. O valor é guardado sem ele e a isenção, como campo.

Conferência independente: o PF de cada apresentação nas 26 colunas é o mesmo
na lista PMC da mesma publicação (694.044 de 694.044 valores em 09/11/2026).
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

FONTE_ID = "cmed"
NOME = "CMED — Lista de Preços de Medicamentos (Anvisa)"
VERSAO_PARSER = "cmed-2026-11-24.1"
NATUREZA = "teto_regulatorio"
ROTULO_NATUREZA = ("preço máximo regulado pela CMED (teto), não preço de "
                   "compra praticado")
URL_PAGINA = "https://www.gov.br/anvisa/pt-br/assuntos/medicamentos/cmed/precos"
PREFIXO_ARQUIVOS = URL_PAGINA + "/arquivos/"
PISO_DE_REDUCAO = Decimal("0.5")
LOTE = 1000
PUBLICADO, RECUSADO, IMPORTANDO = "publicado", "recusado", "importando"

_NOME_PMVG = re.compile(r"^lista_pmvg_(\d{8})_(\d{9})\.xlsx$", re.IGNORECASE)
_VALOR = re.compile(r"^(\d+),(\d{2})(\*?)$")
_PUBLICADA = re.compile(r"Publicada em (\d{2})/(\d{2})/(\d{4}) (\d{1,2})h(\d{2})min")

# As 26 colunas de valor, na ordem da planilha: chave guardada → rótulo
ALIQUOTAS = ("sem_impostos", "0", "12", "12_alc", "17", "17_alc", "17.5", "17.5_alc",
             "18", "18_alc", "19", "19_alc", "19.5", "19.5_alc", "20", "20_alc",
             "20.5", "20.5_alc", "21", "21_alc", "22", "22_alc", "22.5", "22.5_alc",
             "23", "23_alc")


def rotulo_aliquota(chave: str) -> str:
    if chave == "sem_impostos":
        return "sem impostos"
    numero, _, alc = chave.partition("_")
    texto = f"ICMS {numero.replace('.', ',')}%"
    return texto + " (Área de Livre Comércio)" if alc else texto


def _cabecalho_esperado() -> tuple[str, ...]:
    def colunas(prefixo: str) -> list[str]:
        saida = []
        for chave in ALIQUOTAS:
            if chave == "sem_impostos":
                saida.append(f"{prefixo} sem impostos")
            elif chave == "0":
                # assim mesmo na planilha: "PF 0%" e "PMVG 0 %"
                saida.append(f"{prefixo} 0%" if prefixo == "pf" else f"{prefixo} 0 %")
            else:
                numero, _, alc = chave.partition("_")
                saida.append(f"{prefixo} {numero.replace('.', ',')} %" + (" alc" if alc else ""))
        return saida

    return ("substancia", "cnpj", "laboratorio", "codigo ggrem", "registro", "ean 1",
            "ean 2", "ean 3", "produto", "apresentacao", "classe terapeutica",
            "tipo de produto (status do produto)", "regime de preco",
            *colunas("pf"), *colunas("pmvg"), "restricao hospitalar", "cap",
            "confaz 87", "icms 0%", "analise recursal",
            "lista de concessao de credito tributario (pis/cofins)",
            "comercializacao 2025", "tarja")


CABECALHO = _cabecalho_esperado()
COL_PF, COL_PMVG = 13, 13 + len(ALIQUOTAS)
COL_FLAGS = COL_PMVG + len(ALIQUOTAS)          # restrição hospitalar em diante

SEM_GGREM = "GGREM_INVALIDO"
GGREM_REPETIDO = "GGREM_REPETIDO"
VALOR_ILEGIVEL = "VALOR_ILEGIVEL"
SEM_APRESENTACAO = "SEM_PRODUTO_OU_APRESENTACAO"
ASTERISCO_INCOERENTE = "ASTERISCO_SEM_ISENCAO_DECLARADA"
SIM_NAO_ILEGIVEL = "SIM_NAO_ILEGIVEL"


class LeiauteInesperado(ValueError):
    """O arquivo não tem a forma conferida — nada é importado."""


def _normal(texto) -> str:
    sem = unicodedata.normalize("NFKD", str(texto or ""))
    sem = "".join(c for c in sem if not unicodedata.combining(c))
    return " ".join(sem.lower().split())


def _texto(valor) -> str:
    texto = " ".join(str(valor or "").split())
    return "" if texto in ("-", "- (*)") else texto


def nome_do_arquivo(nome: str) -> str:
    """'lista_pmvg_20261109_111901662.xlsx' → '2026-11-09' (data no nome)."""
    achado = _NOME_PMVG.fullmatch(Path(str(nome)).name)
    if not achado:
        raise LeiauteInesperado("o arquivo não tem o nome da lista PMVG da CMED "
                                "(lista_pmvg_AAAAMMDD_NNNNNNNNN.xlsx)")
    data = achado.group(1)
    datetime.strptime(data, "%Y%m%d")
    return f"{data[:4]}-{data[4:6]}-{data[6:]}"


def url_oficial(url: str) -> bool:
    """Só o arquivo da lista PMVG na pasta de preços da CMED, por HTTPS."""
    url = str(url or "")
    if not url.startswith(PREFIXO_ARQUIVOS) or any(
            c in url for c in ("?", "#", "..", "%", "\\")):
        return False
    resto = url[len(PREFIXO_ARQUIVOS):]
    nome, _, sufixo = resto.partition("/")
    return bool(_NOME_PMVG.fullmatch(nome)) and sufixo in ("", "@@download/file")


def _valor(bruto) -> tuple[Decimal, bool]:
    """'7663,54*' → (Decimal('7663.54'), True). O texto da CMED é exato."""
    achado = _VALOR.fullmatch(str(bruto or "").strip())
    if not achado:
        raise InvalidOperation
    return Decimal(f"{achado.group(1)}.{achado.group(2)}"), bool(achado.group(3))


def _sim(bruto) -> bool:
    texto = _normal(bruto)
    if texto not in ("sim", "nao"):
        raise ValueError(texto)
    return texto == "sim"


@dataclass
class Leitura:
    publicada_em: str = ""
    linhas: int = 0
    validas: int = 0
    recusas: Counter = field(default_factory=Counter)
    recusadas: list[dict] = field(default_factory=list)


def ler(caminho: Path, *, nome: str | None = None,
        leitura: Leitura | None = None) -> Iterator[dict]:
    """As apresentações VÁLIDAS da lista PMVG. Confere antes de devolver
    qualquer coisa: o nome oficial, o XLSX seguro, as duas abas, a data de
    publicação do cabeçalho igual à do nome e as 74 colunas na ordem."""
    import openpyxl

    leitura = leitura if leitura is not None else Leitura()
    data_do_nome = nome_do_arquivo(nome or caminho.name)
    arquivos.conferir_zip(caminho, extensoes=frozenset(
        {".xml", ".rels", ".bin", ".png", ".vml", ""}))
    livro = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    try:
        if [_normal(n) for n in livro.sheetnames] != ["cabecalho", "lista pmvg"]:
            raise LeiauteInesperado(f"abas fora do conferido: {livro.sheetnames}")
        topo = " ".join(_texto(l[0]) for l in livro.worksheets[0].iter_rows(
            max_row=10, values_only=True) if l)
        achado = _PUBLICADA.search(topo)
        if not achado or "PREÇOS FÁBRICA E MÁXIMOS DE VENDA AO GOVERNO" not in topo:
            raise LeiauteInesperado("cabeçalho sem a data de publicação da lista PMVG")
        dia, mes, ano, hora, minuto = achado.groups()
        if f"{ano}-{mes}-{dia}" != data_do_nome:
            raise LeiauteInesperado(f"publicada em {dia}/{mes}/{ano}, o nome diz "
                                    f"{data_do_nome}")
        leitura.publicada_em = f"{ano}-{mes}-{dia}T{int(hora):02d}:{minuto}:00-03:00"
        linhas = livro.worksheets[1].iter_rows(values_only=True)
        cabecalho = tuple(_normal(c) for c in next(linhas, ()))
        if cabecalho[:len(CABECALHO)] != CABECALHO:
            raise LeiauteInesperado(f"colunas fora do conferido: {cabecalho[:20]}…")
        vistos: set[str] = set()
        for numero, linha in enumerate(linhas, start=2):
            if not linha or not any(v not in (None, "") for v in linha):
                continue
            leitura.linhas += 1
            ggrem = _texto(linha[3])

            def recusar(motivo: str) -> None:
                leitura.recusas[motivo] += 1
                if len(leitura.recusadas) < 200:
                    leitura.recusadas.append({"linha": numero, "ggrem": ggrem,
                                              "motivo": motivo})

            if not re.fullmatch(r"\d{15}", ggrem):
                recusar(SEM_GGREM)
                continue
            if ggrem in vistos:
                recusar(GGREM_REPETIDO)
                continue
            vistos.add(ggrem)
            if not _texto(linha[8]) or not _texto(linha[9]):
                recusar(SEM_APRESENTACAO)
                continue
            try:
                pf = [_valor(linha[COL_PF + i]) for i in range(len(ALIQUOTAS))]
                pmvg = [_valor(linha[COL_PMVG + i]) for i in range(len(ALIQUOTAS))]
            except (InvalidOperation, IndexError):
                recusar(VALOR_ILEGIVEL)
                continue
            try:
                (restricao, cap, confaz87, icms0) = (
                    _sim(linha[COL_FLAGS + i]) for i in range(4))
                comercializado = _sim(linha[COL_FLAGS + 6])
            except ValueError:
                recusar(SIM_NAO_ILEGIVEL)
                continue
            # o asterisco é a marca da isenção: valor marcado sem isenção
            # declarada (ou o contrário) é linha que não se entende
            marcados = any(a for _, a in pf + pmvg)
            if marcados != (confaz87 or icms0):
                recusar(ASTERISCO_INCOERENTE)
                continue
            registro = _texto(linha[4])
            eans = [e for e in (_texto(linha[5]), _texto(linha[6]), _texto(linha[7]))
                    if re.fullmatch(r"\d{8,14}", e)]
            leitura.validas += 1
            yield {
                # registro fora da forma não derruba a linha: some só ele
                "ggrem": ggrem, "eans": eans,
                "registro": registro if re.fullmatch(r"\d{9,13}", registro) else None,
                "substancia": _texto(linha[0]), "cnpj": _texto(linha[1]) or None,
                "laboratorio": _texto(linha[2]), "produto": _texto(linha[8]),
                "apresentacao": _texto(linha[9]),
                "classe_terapeutica": _texto(linha[10]) or None,
                "tipo_produto": _texto(linha[11]) or None,
                "regime_preco": _texto(linha[12]) or None,
                "pf": {k: v for k, (v, _) in zip(ALIQUOTAS, pf)},
                "pmvg": {k: v for k, (v, _) in zip(ALIQUOTAS, pmvg)},
                "restricao_hospitalar": restricao, "cap": cap,
                "confaz87": confaz87, "icms_0": icms0,
                "analise_recursal": _texto(linha[COL_FLAGS + 4]) or None,
                "lista_credito": _texto(linha[COL_FLAGS + 5]) or None,
                "comercializado": comercializado,
                "tarja": _texto(linha[COL_FLAGS + 7]) or None,
                "linha_planilha": numero,
            }
    finally:
        livro.close()


def chave_da_linha(publicada_em: str, ggrem: str) -> str:
    return f"{publicada_em[:10]}:{ggrem}"


def linha_do_indice(bruta: dict, *, publicada_em: str, sha256: str, url: str,
                    arquivo: str) -> dict:
    from . import evidencia as ev
    from .pncp_indice import texto_de_busca

    chave = chave_da_linha(publicada_em, bruta["ggrem"])
    pf = {k: format(v, "f") for k, v in bruta["pf"].items()}
    pmvg = {k: format(v, "f") for k, v in bruta["pmvg"].items()}
    busca = " ".join((bruta["substancia"], bruta["produto"], bruta["apresentacao"],
                      bruta["laboratorio"]))
    return {
        "registro_id": hashlib.sha256(f"{sha256}:{chave}".encode()).hexdigest()[:40],
        "chave_linha": chave, "publicada_em": publicada_em, "arquivo_sha256": sha256,
        **{k: bruta[k] for k in (
            "ggrem", "registro", "eans", "substancia", "cnpj", "laboratorio",
            "produto", "apresentacao", "classe_terapeutica", "tipo_produto",
            "regime_preco", "restricao_hospitalar", "cap", "confaz87", "icms_0",
            "analise_recursal", "lista_credito", "comercializado", "tarja",
            "linha_planilha")},
        "pf": pf, "pmvg": pmvg, "descricao_busca": texto_de_busca(busca),
        "url_arquivo": url, "arquivo": Path(arquivo).name,
        "hash_linha": ev.hash_da_linha({"chave": chave, "pf": pf, "pmvg": pmvg,
                                        "cap": bruta["cap"],
                                        "linha": bruta["linha_planilha"]}),
        "versao_parser": VERSAO_PARSER,
    }


# ---------------------------------------------------------------------------
# Versões — uma publicação vigente por vez: a lista nova substitui a anterior
# ---------------------------------------------------------------------------
class Armazem(Protocol):
    def versao(self, sha256: str) -> dict | None: ...

    def versao_publicada(self) -> dict | None: ...

    def registrar_versao(self, sha256: str, **campos) -> None: ...

    def gravar_registros(self, linhas: list[dict]) -> None: ...

    def publicar(self, sha256: str, **campos) -> None: ...

    def buscar(self, termos: list[str], **filtros) -> list[dict]: ...


class ArmazemEmMemoria:
    def __init__(self) -> None:
        self.versoes: dict[str, dict] = {}
        self.registros: dict[str, dict] = {}

    def versao(self, sha256):
        return self.versoes.get(sha256)

    def versao_publicada(self):
        return next((v for v in self.versoes.values() if v["vigente"]), None)

    def registrar_versao(self, sha256, **campos):
        atual = self.versoes.get(sha256, {"sha256": sha256, "vigente": False})
        self.versoes[sha256] = {**atual, **campos}

    def gravar_registros(self, linhas):
        for linha in linhas:
            self.registros[linha["registro_id"]] = {**linha, "vigente": False}

    def publicar(self, sha256, **campos):
        for v in self.versoes.values():
            v["vigente"] = False
        for linha in self.registros.values():
            linha["vigente"] = linha["arquivo_sha256"] == sha256
        self.registrar_versao(sha256, estado=PUBLICADO, vigente=True, **campos)

    def buscar(self, termos, *, codigo=None, limite=50):
        procurados = set(termos)
        achados = []
        for l in self.registros.values():
            if not l["vigente"]:
                continue
            if codigo:
                if codigo not in (l["ggrem"], l["registro"], *l["eans"]):
                    continue
                comuns = 0
            else:
                comuns = len(procurados & set(l["descricao_busca"].split()))
                if not comuns:
                    continue
            achados.append((comuns, l["substancia"], l["ggrem"], l))
        achados.sort(key=lambda t: (-t[0], t[1], t[2]))
        return [l for *_, l in achados[:limite]]


@dataclass
class Importacao:
    publicada_em: str = ""
    sha256: str = ""
    arquivo: str = ""
    desfecho: str = ""
    motivo: str = ""
    linhas: int = 0
    validas: int = 0
    recusas: Counter = field(default_factory=Counter)
    validas_na_versao_anterior: int | None = None

    def para_registro(self) -> dict:
        saida = dict(vars(self))
        saida["recusas"] = dict(self.recusas)
        return saida


def importar(armazem: Armazem, caminho: Path, *, url: str,
             nome: str | None = None) -> Importacao:
    """Importa UMA lista PMVG e a publica como a vigente, ou a recusa.
    Idempotente pelo SHA-256; lista mais antiga que a vigente é recusada."""
    nome = Path(nome or caminho.name).name
    if not url_oficial(url) or Path(url.removesuffix("/@@download/file")).name.lower() \
            != nome.lower():
        raise ValueError(f"endereço fora da publicação da CMED: {url}")
    sha = arquivos.sha256_do_arquivo(caminho)
    feito = Importacao(sha256=sha, arquivo=nome)
    existente = armazem.versao(sha)
    if existente and existente.get("estado") == PUBLICADO:
        feito.desfecho = "ja_publicado"
        feito.publicada_em = existente.get("publicada_em", "")
        return feito
    leitura = Leitura()
    brutas = list(ler(caminho, nome=nome, leitura=leitura))
    feito.publicada_em = leitura.publicada_em
    feito.linhas, feito.validas, feito.recusas = (
        leitura.linhas, leitura.validas, leitura.recusas)
    base = dict(publicada_em=feito.publicada_em, arquivo=nome, url=url,
                linhas=feito.linhas, validas=feito.validas,
                recusas=dict(feito.recusas), versao_parser=VERSAO_PARSER)

    def recusar(motivo: str) -> Importacao:
        feito.desfecho, feito.motivo = RECUSADO, motivo
        armazem.registrar_versao(sha, estado=RECUSADO, motivo=motivo, **base)
        return feito

    if not brutas:
        return recusar("nenhuma apresentação válida")
    publicada = armazem.versao_publicada()
    if publicada is not None:
        # o banco devolve a data em UTC; a planilha, no horário de Brasília
        vigente_em = datetime.fromisoformat(str(publicada["publicada_em"]))
        if vigente_em > datetime.fromisoformat(feito.publicada_em):
            return recusar(f"lista de {feito.publicada_em[:10]} é mais antiga que a "
                           f"vigente, de {str(publicada['publicada_em'])[:10]}")
        feito.validas_na_versao_anterior = int(publicada.get("validas") or 0)
        if feito.validas < feito.validas_na_versao_anterior * PISO_DE_REDUCAO:
            return recusar(f"{feito.validas} apresentações contra "
                           f"{feito.validas_na_versao_anterior} da lista vigente — "
                           "redução acima do tolerado")
    armazem.registrar_versao(sha, estado=IMPORTANDO, motivo="",
                             recusadas=leitura.recusadas, **base)
    linhas = [linha_do_indice(b, publicada_em=feito.publicada_em, sha256=sha, url=url,
                              arquivo=nome) for b in brutas]
    for inicio in range(0, len(linhas), LOTE):
        armazem.gravar_registros(linhas[inicio:inicio + LOTE])
    armazem.publicar(sha, publicado_em=datetime.now(timezone.utc).isoformat(
        timespec="seconds"))
    feito.desfecho = PUBLICADO
    return feito


# ---------------------------------------------------------------------------
# Consulta: o teto aplicável por apresentação e alíquota
# ---------------------------------------------------------------------------
@dataclass
class TetoCmed:
    registro_id: str
    ggrem: str
    registro: str | None
    eans: list[str]
    substancia: str
    laboratorio: str
    produto: str
    apresentacao: str
    tipo_produto: str | None
    regime_preco: str | None
    tarja: str | None
    aliquota: str
    pf: Decimal                   # PF na alíquota
    pmvg: Decimal                 # PMVG na alíquota (preenchido para todos)
    cap: bool
    confaz87: bool
    icms_0: bool
    restricao_hospitalar: bool
    analise_recursal: str | None
    pf_isento: Decimal            # PF ICMS 0%
    pmvg_isento: Decimal
    publicada_em: str
    url_arquivo: str
    arquivo: str
    arquivo_sha256: str
    linha_planilha: int
    natureza: str = NATUREZA

    @property
    def teto_governo(self) -> Decimal:
        """A regra do cabeçalho da CMED: CAP → PMVG; sem CAP → PF."""
        return self.pmvg if self.cap else self.pf

    @property
    def base_do_teto(self) -> str:
        return "PMVG (CAP aplicado ao PF)" if self.cap else "PF (fora do CAP)"

    @property
    def isento_icms(self) -> bool:
        return self.confaz87 or self.icms_0

    @property
    def teto_governo_isento(self) -> Decimal:
        return self.pmvg_isento if self.cap else self.pf_isento


def teto_da_linha(linha: dict, aliquota: str) -> TetoCmed | None:
    """Linha do índice → teto; sem rastreabilidade ou valor, não chega à tela."""
    try:
        pf, pmvg = linha["pf"], linha["pmvg"]
        valores = [Decimal(str(x[k])) for x in (pf, pmvg) for k in (aliquota, "0")]
        if any(not v.is_finite() or v <= 0 for v in valores):
            return None
        if not url_oficial(linha["url_arquivo"]) or not re.fullmatch(
                r"\d{15}", str(linha["ggrem"])):
            return None
        return TetoCmed(
            registro_id=str(linha["registro_id"]), ggrem=str(linha["ggrem"]),
            registro=linha.get("registro"), eans=list(linha.get("eans") or []),
            substancia=str(linha.get("substancia") or ""),
            laboratorio=str(linha.get("laboratorio") or ""),
            produto=str(linha["produto"]), apresentacao=str(linha["apresentacao"]),
            tipo_produto=linha.get("tipo_produto"), regime_preco=linha.get("regime_preco"),
            tarja=linha.get("tarja"), aliquota=aliquota,
            pf=valores[0], pf_isento=valores[1], pmvg=valores[2], pmvg_isento=valores[3],
            cap=bool(linha["cap"]), confaz87=bool(linha["confaz87"]),
            icms_0=bool(linha["icms_0"]),
            restricao_hospitalar=bool(linha.get("restricao_hospitalar")),
            analise_recursal=linha.get("analise_recursal"),
            publicada_em=str(linha["publicada_em"]), url_arquivo=str(linha["url_arquivo"]),
            arquivo=str(linha.get("arquivo") or ""),
            arquivo_sha256=str(linha.get("arquivo_sha256") or ""),
            linha_planilha=int(linha["linha_planilha"]))
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None


def consultar(buscar: Callable[..., list], *, termo: str = "",
              codigo: str | None = None, aliquota: str = "18",
              limite: int = 50) -> list[TetoCmed]:
    """Teto CMED por termo (substância, produto, apresentação, laboratório)
    ou por código (GGREM, registro ou EAN). Filtro fora da regra é
    `ValueError` e não vai ao índice; erro do índice sobe."""
    from .compras_gov import _tokens
    from .pncp_indice import texto_de_busca

    if aliquota not in ALIQUOTAS:
        raise ValueError("alíquota desconhecida")
    codigo = re.sub(r"\D", "", str(codigo or "")) or None
    if codigo is not None and not re.fullmatch(r"\d{8,15}", codigo):
        raise ValueError("código: GGREM (15 dígitos), registro (13) ou EAN (8 a 14)")
    termos = sorted({t.lower() for t in _tokens(texto_de_busca(termo)) if t.isalnum()},
                    key=lambda t: (-len(t), t))[:12]
    if not termos and codigo is None:
        return []
    linhas = buscar([] if codigo else termos, codigo=codigo,
                    limite=max(1, min(int(limite), 200)))
    saida = []
    for linha in linhas or []:
        if isinstance(linha, dict):
            teto = teto_da_linha(linha, aliquota)
            if teto is not None:
                saida.append(teto)
    return saida


# ---------------------------------------------------------------------------
# Conferência independente: o PF da lista PMC da mesma publicação
# ---------------------------------------------------------------------------
def pf_da_lista_pmc(caminho: Path) -> dict[str, dict[str, Decimal]]:
    """`{ggrem: {alíquota: PF}}` da lista PMC — outro arquivo oficial."""
    import openpyxl

    arquivos.conferir_zip(caminho, extensoes=frozenset(
        {".xml", ".rels", ".bin", ".png", ".vml", ""}))
    livro = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    try:
        linhas = livro.worksheets[1].iter_rows(values_only=True)
        cabecalho = tuple(_normal(c) for c in next(linhas, ()))
        if cabecalho[:COL_PMVG] != CABECALHO[:COL_PMVG]:
            raise LeiauteInesperado("a lista PMC não tem as colunas de PF conferidas")
        saida = {}
        for linha in linhas:
            if linha and re.fullmatch(r"\d{15}", _texto(linha[3])):
                try:
                    saida[_texto(linha[3])] = {
                        k: _valor(linha[COL_PF + i])[0] for i, k in enumerate(ALIQUOTAS)}
                except InvalidOperation:
                    continue
        return saida
    finally:
        livro.close()


@dataclass
class Confronto:
    conferidas: int = 0
    iguais: int = 0
    divergentes: list[dict] = field(default_factory=list)
    ausentes: list[str] = field(default_factory=list)

    def para_registro(self) -> dict:
        return {"conferidas": self.conferidas, "iguais": self.iguais,
                "divergentes": self.divergentes[:50], "ausentes": self.ausentes[:50]}


def confrontar_pf(brutas: list[dict], da_pmc: dict[str, dict[str, Decimal]]) -> Confronto:
    relato = Confronto()
    for linha in brutas:
        outro = da_pmc.get(linha["ggrem"])
        if outro is None:
            relato.ausentes.append(linha["ggrem"])
            continue
        for chave in ALIQUOTAS:
            relato.conferidas += 1
            if linha["pf"][chave] == outro[chave]:
                relato.iguais += 1
            else:
                relato.divergentes.append({"ggrem": linha["ggrem"], "aliquota": chave,
                                           "pmvg": format(linha["pf"][chave], "f"),
                                           "pmc": format(outro[chave], "f")})
    return relato
