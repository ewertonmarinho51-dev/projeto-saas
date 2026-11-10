"""
Canal DIRETO de Curitiba — Portal de Dados Abertos, "Itens Processo".

Primeiro canal direto de compras gerais além do Compras.gov (cotação
multiportal, 10/11/2026). A sequência inteira mora aqui:

    arquivo (CSV oficial) → normalizador → índice → adaptador
        → seleção (motor comum) → revisão/PDF (origem e canal)

**Situação: aguardando dados.** O portal (`dadosabertos.curitiba.pr.gov.br`)
respondeu HTTP 503 em 10/11/2026, inclusive pelo navegador, e a amostra de
01/11/2026 não pôde ser baixada. O mapa de colunas abaixo segue os campos
que a especificação do dono lista (órgão, processo, item, quantidade,
unidade de medida, contrato, início/fim da vigência, Valor Unitário) e
ACEITA SÓ os nomes previstos — coluna faltando é erro com o nome dela, não
palpite. `MAPEAMENTO_CONFIRMADO` fica falso até a conferência contra o
dicionário oficial e o arquivo real; sem isso, `habilitada()` é falso
mesmo com a flag ligada.

Regras de comparabilidade (não negociáveis):

* o Valor Unitário só é **contratado** quando a linha está ligada a um
  contrato VÁLIDO no recurso "Dados Básicos" — contrato existente, não
  cancelado/rescindido, com a vigência cobrindo a data-base. Sem isso a
  linha fica fora do índice, contada por motivo;
* quantidade, unidade e unitário positivos, conferidos como na fonte;
* cada referência guarda a URL do recurso, a versão (data do arquivo), o
  hash do arquivo e o identificador da linha — a evidência recuperável;
* atribuição ao órgão e ao Portal de Dados Abertos de Curitiba, com o
  aviso de uso secundário das regras de utilização do portal;
* no piloto paraense, só quando contexto comercial, geografia e perfil
  admitirem: a referência é de outra UF e o fator de geografia do matching
  a pesa como tal; a decisão de usar continua do servidor.
"""

from __future__ import annotations

import csv
import hashlib
import io
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from . import evidencia
from .fontes import Capacidade, Consulta, FontePesquisaPreco, ResultadoBusca
from .modelo import Fonte, NaturezaValor, Referencia, para_data

VERSAO_NORMALIZADOR = "2026-11-10.curitiba.1"
FONTE_CURITIBA = Fonte("curitiba_itens",
                       "Curitiba — Dados Abertos (Itens Processo)",
                       "contratacao_similar")
FLAG = "price_source_curitiba"
PORTAL = "curitiba"
URL_CONJUNTO = ("https://dadosabertos.curitiba.pr.gov.br/conjuntodado/detalhe/"
                "?chave=c64c1152-97d0-4343-b0b6-42edb5cecef2")
URL_REGRAS = "https://dadosabertos.curitiba.pr.gov.br/informacoes/regrasutilizacao/5"
AVISO_USO_SECUNDARIO = (
    "Dados do Portal de Dados Abertos da Prefeitura Municipal de Curitiba, "
    "usados de forma secundária pelo Gov Conect; a Prefeitura não se "
    "responsabiliza pelo uso nem pelas conclusões tiradas deles "
    f"(regras de utilização: {URL_REGRAS}).")

# Formato numérico DECLARADO por fonte (`evidencia.ler_decimal`): "br"
# (1.234,56) é o esperado num CSV municipal — parte do que a conferência
# do arquivo real confirma.
FORMATO_NUMERICO = "br"

# Conferido contra o dicionário oficial e o arquivo real? Enquanto não,
# o canal não liga — ver `habilitada`.
MAPEAMENTO_CONFIRMADO = False
PENDENCIA = ("portal respondeu HTTP 503 em 10/11/2026 (curl e navegador); "
             "baixar o CSV Itens Processo de 01/11/2026 e o Dados Básicos, "
             "conferir o mapa de colunas contra o dicionário oficial e "
             "validar um caso elegível (link, unidade e vigência)")

# Campo lógico → nomes aceitos no cabeçalho (normalizados: sem acento,
# maiúsculas, espaço e pontuação viram "_").
COLUNAS_ITENS = {
    "orgao": ("ORGAO", "NOME_ORGAO", "ORGAO_SOLICITANTE"),
    "processo": ("PROCESSO", "NUMERO_PROCESSO", "NR_PROCESSO"),
    "item": ("ITEM", "NUMERO_ITEM", "NR_ITEM", "SEQUENCIA_ITEM"),
    "descricao": ("DESCRICAO", "DESCRICAO_ITEM", "OBJETO", "ESPECIFICACAO"),
    "quantidade": ("QUANTIDADE", "QTD", "QUANTIDADE_ITEM"),
    "unidade": ("UNIDADE_DE_MEDIDA", "UNIDADE_MEDIDA", "UNIDADE"),
    "contrato": ("CONTRATO", "NUMERO_CONTRATO", "NR_CONTRATO"),
    "inicio_vigencia": ("INICIO_DA_VIGENCIA", "INICIO_VIGENCIA",
                        "DATA_INICIO_VIGENCIA"),
    "fim_vigencia": ("FIM_DA_VIGENCIA", "FIM_VIGENCIA", "DATA_FIM_VIGENCIA"),
    "valor_unitario": ("VALOR_UNITARIO", "VL_UNITARIO", "VALOR_UNIT"),
}
COLUNAS_DADOS_BASICOS = {
    "contrato": ("CONTRATO", "NUMERO_CONTRATO", "NR_CONTRATO"),
    "situacao": ("SITUACAO", "ESTADO", "SITUACAO_CONTRATO", "STATUS"),
    "inicio_vigencia": ("INICIO_DA_VIGENCIA", "INICIO_VIGENCIA",
                        "DATA_INICIO_VIGENCIA"),
    "fim_vigencia": ("FIM_DA_VIGENCIA", "FIM_VIGENCIA", "DATA_FIM_VIGENCIA"),
}
SITUACOES_INVALIDAS = ("CANCEL", "RESCIN", "ANULAD", "SUSPENS", "REVOG")

SEM_CONTRATO = "SEM_CONTRATO_VINCULADO"
CONTRATO_INVALIDO = "CONTRATO_INEXISTENTE_OU_INVALIDO"
FORA_DA_VIGENCIA = "FORA_DA_VIGENCIA_NA_DATA_BASE"


class LeiauteDesconhecido(ValueError):
    """O arquivo não tem uma coluna que o normalizador exige."""


def _norm(texto) -> str:
    base = unicodedata.normalize("NFKD", str(texto or "").upper().strip())
    base = "".join(c for c in base if not unicodedata.combining(c))
    return "_".join("".join(c if c.isalnum() else " " for c in base).split())


def _decodificar(conteudo: bytes) -> str:
    for codificacao in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return conteudo.decode(codificacao)
        except UnicodeDecodeError:
            continue
    raise LeiauteDesconhecido("codificação do arquivo não reconhecida")


def ler_csv(conteudo: bytes, colunas: dict[str, tuple[str, ...]]) -> list[dict]:
    """Linhas com os campos LÓGICOS; coluna exigida faltando → erro."""
    texto = _decodificar(conteudo)
    dialeto = csv.Sniffer().sniff(texto[:4096], delimiters=";,|\t")
    leitor = csv.reader(io.StringIO(texto), dialeto)
    cabecalho = [_norm(c) for c in next(leitor, [])]
    posicao: dict[str, int] = {}
    faltam = []
    for campo, nomes in colunas.items():
        achado = next((cabecalho.index(n) for n in nomes if n in cabecalho), None)
        if achado is None:
            faltam.append(f"{campo} ({' / '.join(nomes)})")
        else:
            posicao[campo] = achado
    if faltam:
        raise LeiauteDesconhecido("colunas ausentes: " + "; ".join(faltam))
    linhas = []
    for numero, linha in enumerate(leitor, start=2):
        if not any(c.strip() for c in linha):
            continue
        registro = {campo: (linha[i].strip() if i < len(linha) else "")
                    for campo, i in posicao.items()}
        registro["_linha"] = numero
        linhas.append(registro)
    return linhas


def _numero(texto: str):
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return evidencia.ler_decimal(texto, formato=FORMATO_NUMERICO)
    except Exception:  # noqa: BLE001 — número ilegível não vira preço
        return None


@dataclass(frozen=True)
class Arquivo:
    """O recurso baixado: endereço, versão (data) e hash — a evidência."""

    url: str
    versao: str
    conteudo: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.conteudo).hexdigest()


@dataclass
class Normalizacao:
    validas: list[dict] = field(default_factory=list)
    quarentena: dict[str, int] = field(default_factory=dict)

    def recusar(self, motivo: str) -> None:
        self.quarentena[motivo] = self.quarentena.get(motivo, 0) + 1


def contratos_validos(dados_basicos: list[dict], data_base: date) -> dict[str, dict]:
    """Contrato → linha, só os válidos e vigentes na data-base."""
    saida = {}
    for linha in dados_basicos:
        chave = _norm(linha.get("contrato"))
        situacao = _norm(linha.get("situacao"))
        inicio = para_data(_iso(linha.get("inicio_vigencia")))
        fim = para_data(_iso(linha.get("fim_vigencia")))
        if not chave or any(m in situacao for m in SITUACOES_INVALIDAS):
            continue
        if inicio and fim and inicio <= data_base <= fim:
            saida[chave] = linha
    return saida


def _iso(texto) -> str | None:
    """'31/12/2026' ou '2026-12-31' → '2026-12-31'."""
    texto = str(texto or "").strip()[:10]
    if len(texto) == 10 and texto[2] == "/" and texto[5] == "/":
        return f"{texto[6:10]}-{texto[3:5]}-{texto[0:2]}"
    return texto or None


def normalizar(itens: Arquivo, dados_basicos: Arquivo, *,
               data_base: date) -> Normalizacao:
    """CSV oficial → linhas do índice, só com valor CONTRATADO conferido."""
    saida = Normalizacao()
    contratos = contratos_validos(ler_csv(dados_basicos.conteudo,
                                          COLUNAS_DADOS_BASICOS), data_base)
    for linha in ler_csv(itens.conteudo, COLUNAS_ITENS):
        if not linha["descricao"]:
            saida.recusar(evidencia.SEM_DESCRICAO)
            continue
        if not linha["unidade"]:
            saida.recusar(evidencia.SEM_UNIDADE)
            continue
        quantidade = _numero(linha["quantidade"])
        unitario = _numero(linha["valor_unitario"])
        if quantidade is None or quantidade <= 0:
            saida.recusar(evidencia.SEM_QUANTIDADE)
            continue
        if unitario is None or unitario <= 0:
            saida.recusar(evidencia.PRECO_INVALIDO)
            continue
        if not linha["contrato"]:
            saida.recusar(SEM_CONTRATO)
            continue
        contrato = contratos.get(_norm(linha["contrato"]))
        if contrato is None:
            saida.recusar(CONTRATO_INVALIDO)
            continue
        inicio = para_data(_iso(linha["inicio_vigencia"]))
        fim = para_data(_iso(linha["fim_vigencia"]))
        if inicio and fim and not (inicio <= data_base <= fim):
            saida.recusar(FORA_DA_VIGENCIA)
            continue
        identificador = f"{linha['processo']}#{linha['item']}#{linha['contrato']}"
        saida.validas.append({
            "id_externo": identificador,
            "linha_arquivo": linha["_linha"],
            "orgao": linha["orgao"], "processo": linha["processo"],
            "item": linha["item"], "contrato": linha["contrato"],
            "descricao": linha["descricao"], "unidade": linha["unidade"],
            "quantidade": format(quantidade, "f"),
            "valor_unitario": format(unitario, "f"),
            "inicio_vigencia": inicio.isoformat() if inicio else None,
            "fim_vigencia": fim.isoformat() if fim else None,
            "url_recurso": itens.url, "versao_recurso": itens.versao,
            "sha256_recurso": itens.sha256,
            "url_dados_basicos": dados_basicos.url,
            "sha256_dados_basicos": dados_basicos.sha256,
            "versao_normalizador": VERSAO_NORMALIZADOR,
        })
    return saida


def referencia_da_linha(linha: dict) -> Referencia:
    """Linha do índice → `Referencia` CONTRATADA, com a evidência."""
    from decimal import Decimal

    bruto = {**linha, "origem_direta": {
        "portal": PORTAL, "url": linha.get("url_recurso"),
        "versao": linha.get("versao_recurso"),
        "sha256": linha.get("sha256_recurso"),
        "linha": linha.get("linha_arquivo"),
        "aviso": AVISO_USO_SECUNDARIO}}
    return Referencia(
        fonte=FONTE_CURITIBA, id_externo=str(linha["id_externo"]), bruto=bruto,
        descricao_original=str(linha.get("descricao") or ""),
        unidade_original=str(linha.get("unidade") or "") or None,
        quantidade_original=Decimal(str(linha["quantidade"])),
        valor_unitario_original=Decimal(str(linha["valor_unitario"])),
        natureza_valor=NaturezaValor.CONTRATADO,
        orgao=str(linha.get("orgao") or "") or None, uf="PR",
        municipio="Curitiba",
        data_compra=para_data(linha.get("inicio_vigencia")),
        referencia_externa=f"Processo {linha.get('processo')} · "
                           f"contrato {linha.get('contrato')}")


class IndiceEmMemoria:
    """Índice local das linhas válidas (o de banco vem com a migração,
    quando houver dado real para medir tamanho e busca)."""

    def __init__(self, linhas: list[dict] | None = None) -> None:
        self.linhas = {l["id_externo"]: l for l in (linhas or [])}

    def buscar(self, termos: list[str], *, limite: int = 50) -> list[dict]:
        procurados = {t.upper() for t in termos}
        achados = []
        for linha in self.linhas.values():
            palavras = set(_norm(linha.get("descricao")).split("_"))
            comuns = len(procurados & palavras)
            if comuns:
                achados.append((comuns, linha))
        achados.sort(key=lambda t: t[0], reverse=True)
        return [l for _, l in achados[:limite]]


def habilitada(*, flag_ativa=None) -> bool:
    """Flag `price_source_curitiba` E mapeamento confirmado no código."""
    if not MAPEAMENTO_CONFIRMADO:
        return False
    if flag_ativa is None:
        from .. import db

        flag_ativa = db.flag_ativa
    try:
        return bool(flag_ativa(FLAG))
    except Exception:  # noqa: BLE001 — leitura de flag nunca liga fonte
        return False


def _grupos(consulta: Consulta, maximo: int = 12) -> list[list[str]]:
    """Uma lista de palavras por variante (descrição e termos alternativos):
    o sinônimo não é engolido por uma descrição longa."""
    from .compras_gov import _tokens

    grupos: list[list[str]] = []
    for texto in (consulta.descricao, *consulta.termos_alternativos):
        palavras = sorted(_tokens(texto), key=lambda p: (-len(p), p))[:maximo]
        if palavras and palavras not in grupos:
            grupos.append(palavras)
    return grupos[:5]


class CuritibaDireta(FontePesquisaPreco):
    """Valores contratados de Curitiba, lidos do índice (sem rede na busca)."""

    fonte = FONTE_CURITIBA
    capacidades = frozenset({Capacidade.PRECO, Capacidade.EVIDENCIA})

    def __init__(self, buscar) -> None:
        self._buscar = buscar

    def pesquisar(self, consulta: Consulta) -> ResultadoBusca:
        from .compras_gov import _casa, _tokens

        resultado = ResultadoBusca(fonte=self.fonte)
        vistas: dict[str, dict] = {}
        for termos in _grupos(consulta):
            try:
                resultado.chamadas += 1
                linhas = self._buscar(termos, limite=consulta.limite)
            except Exception as erro:  # noqa: BLE001
                return resultado.falhar(
                    f"o índice de Curitiba não respondeu ({type(erro).__name__})")
            procurados = {t.upper() for t in termos}
            for linha in linhas or []:
                if _casa(procurados, _tokens(str(linha.get("descricao") or ""))):
                    vistas.setdefault(str(linha["id_externo"]), linha)
        resultado.referencias.extend(referencia_da_linha(l) for l in vistas.values())
        if resultado.referencias:
            resultado.registrar(AVISO_USO_SECUNDARIO)
        return resultado
