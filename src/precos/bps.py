"""
BPS — Banco de Preços em Saúde (Ministério da Saúde) como fonte de PREÇO.

Três peças, e nenhuma roda no clique do usuário além da leitura do índice:

1. **Confronto com a API oficial** (`confrontar`). O arquivo anual traz o
   `co_seq_bps`; a API (`/economia-da-saude/bps`) só consulta por CATMAT e
   não o devolve. O confronto prova, linha a linha, que o registro do
   arquivo aparece na resposta oficial do seu CATMAT — é o que autoriza
   usar essa consulta como endereço verificável da evidência;
2. **Importação por versão** (`importar`). Cada arquivo oficial é uma
   versão (ano + SHA-256). Reimportar o mesmo arquivo não faz nada; um
   arquivo novo do mesmo ano é versão nova e só passa a valer depois de
   VALIDADO e publicado inteiro — a busca nunca vê importação pela metade,
   e arquivo que encolheu demais é recusado, não publicado;
3. **Fonte** (`BPSIndice`). Lê o índice por CATMAT (identidade) ou por
   termos da descrição, e devolve preço PAGO (praticado) por compra
   pública, com CATMAT, apresentação e unidade de fornecimento à vista.

A habilitação NÃO mora aqui: `fontes_externas.habilitada("bps")` exige a
flag, o mapeamento conferido e a licença aprovada com prova.
"""

from __future__ import annotations

import dataclasses
import json
import random
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Protocol

from . import arquivos, etl_bps
from . import evidencia as ev
from .fontes import Capacidade, Consulta, FontePesquisaPreco, ResultadoBusca
from .modelo import Fonte, NaturezaValor, Referencia

FONTE_BPS = Fonte(
    id="bps",
    nome="BPS — Banco de Preços em Saúde (Ministério da Saúde)",
    tipo="sistema_oficial",
)
URL_CONJUNTO = "https://dadosabertos.saude.gov.br/dataset/bps"
VERSAO_IMPORTADOR = "2026-11-11.bps-indice.1"

PAGINA_API = 200
MAX_PAGINAS_API = 25
TIMEOUT_S = 60
# Arquivo novo com menos da metade das linhas válidas da versão publicada
# do mesmo ano não é publicado: é o sinal de arquivo truncado ou zerado.
PISO_DE_REDUCAO = Decimal("0.5")
LOTE = 500

IMPORTANDO, PUBLICADO, RECUSADO = "importando", "publicado", "recusado"


# ---------------------------------------------------------------------------
# API oficial — só para conferir
# ---------------------------------------------------------------------------
def _abrir_url(url: str) -> str:
    requisicao = urllib.request.Request(
        url, headers={"Accept": "application/json",
                      "User-Agent": "GovDocs/pesquisa-precos"})
    with urllib.request.urlopen(requisicao, timeout=TIMEOUT_S) as resposta:
        return resposta.read().decode("utf-8")


def consultar_api(catmat: str, *, abrir_url: Callable[[str], str] = _abrir_url
                  ) -> list[dict]:
    """
    Todos os registros do CATMAT na API oficial. O preço chega como número
    JSON; `parse_float=Decimal` guarda o texto que a API escreveu, sem
    passar por `float`.
    """
    base = etl_bps.url_da_consulta(catmat)
    if base is None:
        raise ValueError("CATMAT inválido para a consulta ao BPS")
    registros: list[dict] = []
    for pagina in range(MAX_PAGINAS_API):
        corpo = abrir_url(f"{base}&limit={PAGINA_API}"
                          f"&offset={pagina * PAGINA_API}")
        lote = (json.loads(corpo, parse_float=Decimal) or {}).get("bps") or []
        registros.extend(lote)
        if len(lote) < PAGINA_API:
            break
    return registros


def _dec(valor) -> Decimal | None:
    try:
        return None if valor in (None, "") else Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None


def chave_de_confronto(*, instituicao, data, quantidade, unitario, fornecedor
                       ) -> tuple | None:
    """Como um registro é reconhecido DENTRO da resposta do seu CATMAT."""
    quantidade, unitario = _dec(quantidade), _dec(unitario)
    if not instituicao or not data or quantidade is None or unitario is None:
        return None
    digitos = "".join(c for c in str(fornecedor or "") if c.isdigit())
    return ("".join(c for c in str(instituicao) if c.isdigit()),
            str(data)[:10], quantidade, unitario, digitos)


def _chave_da_evidencia(e: ev.Evidencia) -> tuple | None:
    return chave_de_confronto(
        instituicao=e.orgao_cnpj, data=e.data_resultado,
        quantidade=e.quantidade, unitario=e.valor_unitario,
        fornecedor=e.fornecedor_cnpj)


def _chave_da_api(r: dict) -> tuple | None:
    return chave_de_confronto(
        instituicao=r.get("cnpjInstituicao"), data=r.get("dataCompra"),
        quantidade=r.get("quantidade"), unitario=r.get("precoUnitario"),
        fornecedor=r.get("cnpjFornecedor"))


@dataclass
class Confronto:
    """Arquivo × API oficial, sobre uma amostra de linhas."""

    conferidas: int = 0
    achadas: int = 0
    nao_achadas: list[dict] = field(default_factory=list)
    falhas: list[str] = field(default_factory=list)
    catmats: int = 0

    def para_registro(self) -> dict:
        return {"conferidas": self.conferidas, "achadas": self.achadas,
                "nao_achadas": self.nao_achadas, "falhas": self.falhas,
                "catmats_consultados": self.catmats}


def confrontar(evidencias: list[ev.Evidencia], *,
               abrir_url: Callable[[str], str] = _abrir_url) -> Confronto:
    """
    Cada evidência é procurada na resposta oficial do seu CATMAT, com
    preço, quantidade, data, instituição e fornecedor IGUAIS. Uma consulta
    por CATMAT, reaproveitada para todas as linhas dele.
    """
    confronto = Confronto()
    por_catmat: dict[str, set | None] = {}
    for e in evidencias:
        catmat = str(e.codigo_catalogo or "")
        if catmat not in por_catmat:
            try:
                por_catmat[catmat] = {_chave_da_api(r)
                                      for r in consultar_api(
                                          catmat, abrir_url=abrir_url)}
                confronto.catmats += 1
            except (ValueError, urllib.error.URLError, TimeoutError, OSError,
                    json.JSONDecodeError) as erro:
                por_catmat[catmat] = None
                confronto.falhas.append(
                    f"CATMAT {catmat or '(vazio)'}: {type(erro).__name__}")
        chaves = por_catmat[catmat]
        if chaves is None:
            continue
        confronto.conferidas += 1
        if _chave_da_evidencia(e) in chaves:
            confronto.achadas += 1
        else:
            confronto.nao_achadas.append({
                "co_seq_bps": e.registro_id, "catmat": catmat,
                "valor_unitario": None if e.valor_unitario is None
                else format(e.valor_unitario, "f"),
                "data": e.data_resultado})
    return confronto


def amostra(evidencias, tamanho: int, semente: int = 20261111) -> list:
    """Amostra aleatória reproduzível das evidências VALIDADAS."""
    validas = [e for e in evidencias if e.validada]
    sorteio = random.Random(semente)
    return validas if len(validas) <= tamanho else sorteio.sample(
        validas, tamanho)


# ---------------------------------------------------------------------------
# Índice
# ---------------------------------------------------------------------------
_DOSE_COLADA = re.compile(r"(\d)([A-Za-zµ])")


def separar_dose(texto: str) -> str:
    """
    "200mg" → "200 mg". A planilha do município escreve a dose colada; o
    CATMAT, separada ("DOSAGEM: 200 MG"). Sem isto o número da dose — o
    que distingue 200 de 400 mg — nunca casava. Vale dos dois lados: no
    texto de busca do índice e na descrição pesquisada.
    """
    return _DOSE_COLADA.sub(r"\1 \2", str(texto or ""))


def chave_estavel(e: ev.Evidencia) -> str:
    """
    Identidade da COMPRA, igual de um arquivo para o outro.

    O `co_seq_bps` não serve para isso: o mesmo registro (palivizumabe,
    SES-SP, 09/01/2026, R$ 5.029,73 × 723) saiu com 27507687 no arquivo de
    20/10/2026 e com 33224771 no de 11/11/2026 — o número é refeito a cada
    publicação. A chave é o que a compra É: CATMAT, unidade, instituição,
    data, quantidade, preço, fornecedor e processo. Duas linhas idênticas
    nesses campos são a mesma observação de preço e contam uma vez.
    """
    return "bps-" + ev.hash_da_linha({
        "catmat": e.codigo_catalogo, "unidade": (e.unidade or "").upper(),
        "instituicao": e.orgao_cnpj, "data": e.data_resultado,
        "quantidade": None if e.quantidade is None
        else format(e.quantidade.normalize(), "f"),
        "unitario": None if e.valor_unitario is None
        else format(e.valor_unitario.normalize(), "f"),
        "fornecedor": e.fornecedor_cnpj, "processo": e.processo})[:32]


def linha_do_indice(e: ev.Evidencia) -> dict:
    """Evidência VALIDADA → linha do índice, com tudo o que a tela e o
    relatório precisam para dizer de onde o preço veio."""
    from .pncp_indice import texto_de_busca

    apresentacao = " ".join(str(e.atributos.get("apresentacao") or "").split())
    return {
        "registro_id": chave_estavel(e),
        "co_seq_bps": e.registro_id,
        "ano": int(e.atributos.get("ano") or str(e.data_resultado)[:4]),
        "arquivo_sha256": e.sha256_snapshot,
        "catmat": e.codigo_catalogo,
        "descricao": e.descricao,
        "descricao_busca": texto_de_busca(
            separar_dose(f"{e.descricao} {apresentacao}")),
        "unidade": e.unidade,
        "apresentacao": apresentacao or None,
        "quantidade": format(e.quantidade, "f"),
        "valor_unitario": format(e.valor_unitario, "f"),
        "valor_total": None if e.valor_total is None
        else format(e.valor_total, "f"),
        "data_compra": e.data_resultado,
        "uf": e.uf, "municipio": e.municipio, "orgao": e.orgao,
        "orgao_cnpj": e.orgao_cnpj, "esfera": e.atributos.get("esfera"),
        "fornecedor_cnpj": e.fornecedor_cnpj,
        "modalidade": e.atributos.get("modalidade"),
        "tipo_compra": e.resultado,
        "generico": e.atributos.get("generico"),
        "registro_anvisa": e.atributos.get("registro_anvisa"),
        "processo": e.processo,
        "url_evidencia": e.url_evidencia, "url_arquivo": e.url_snapshot,
        "hash_linha": e.hash_linha, "versao_parser": e.versao_parser,
    }


class Armazem(Protocol):
    def versao(self, ano: int, sha256: str) -> dict | None: ...

    def versao_publicada(self, ano: int) -> dict | None: ...

    def registrar_versao(self, ano: int, sha256: str, **campos) -> None: ...

    def gravar_registros(self, linhas: list[dict]) -> None: ...

    def publicar(self, ano: int, sha256: str, **campos) -> None: ...

    def buscar(self, termos: list[str], *, catmat: str | None, uf: str | None,
               desde: date | None, ate: date | None, limite: int
               ) -> list[dict]: ...


class ArmazemEmMemoria:
    """O contrato do banco, em memória — provas e medição de bancada."""

    def __init__(self) -> None:
        self.versoes: dict[tuple[int, str], dict] = {}
        self.registros: dict[str, dict] = {}

    def versao(self, ano, sha256):
        return self.versoes.get((ano, sha256))

    def versao_publicada(self, ano):
        for v in self.versoes.values():
            if v["ano"] == ano and v.get("vigente"):
                return v
        return None

    def registrar_versao(self, ano, sha256, **campos):
        atual = self.versoes.get((ano, sha256), {"ano": ano, "sha256": sha256,
                                                 "vigente": False})
        self.versoes[(ano, sha256)] = {**atual, **campos}

    def gravar_registros(self, linhas):
        for linha in linhas:
            self.registros[linha["registro_id"]] = dict(linha)

    def publicar(self, ano, sha256, **campos):
        for v in self.versoes.values():
            if v["ano"] == ano:
                v["vigente"] = False
        self.registrar_versao(ano, sha256, estado=PUBLICADO, vigente=True,
                              **campos)

    def buscar(self, termos, *, catmat=None, uf=None, desde=None, ate=None,
               limite=50):
        vigentes = {v["sha256"] for v in self.versoes.values()
                    if v.get("vigente")}
        procurados = set(termos)
        achados = []
        for linha in self.registros.values():
            if linha.get("arquivo_sha256") not in vigentes:
                continue
            if uf and (linha.get("uf") or "").upper() != uf.upper():
                continue
            data = str(linha.get("data_compra") or "")[:10]
            if desde and (not data or data < desde.isoformat()):
                continue
            if ate and data and data > ate.isoformat():
                continue
            mesmo_codigo = bool(catmat) and linha.get("catmat") == catmat
            comuns = len(procurados & set(
                str(linha.get("descricao_busca") or "").replace(",", " ")
                .replace(":", " ").split()))
            if mesmo_codigo or comuns:
                achados.append((mesmo_codigo, comuns, data, linha))
        achados.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
        return [linha for *_, linha in achados[:limite]]


@dataclass
class Importacao:
    """O que UMA importação fez — vai para o relato e para a versão."""

    ano: int = 0
    sha256: str = ""
    desfecho: str = ""            # publicado | ja_publicado | recusado
    motivo: str = ""
    linhas: int = 0
    validas: int = 0
    quarentena: Counter = field(default_factory=Counter)
    # linhas idênticas na identidade da compra (`chave_estavel`): uma só
    duplicadas: int = 0
    validas_na_versao_anterior: int | None = None

    def para_registro(self) -> dict:
        saida = dict(vars(self))
        saida["quarentena"] = dict(self.quarentena)
        return saida


def importar(armazem: Armazem, caminho: Path, *, url: str,
             last_modified: str | None = None) -> Importacao:
    """
    Importa UM arquivo anual oficial e publica a versão, ou a recusa.

    Idempotente: o mesmo arquivo (mesmo SHA-256) já publicado não é lido de
    novo. Retificação do mesmo ano é outro SHA: vira versão nova, e a
    anterior só deixa de valer quando a nova é publicada inteira.
    """
    if not arquivos.url_permitida(url):
        raise ValueError("o arquivo do BPS só é aceito do endereço oficial")
    sha = arquivos.sha256_do_arquivo(caminho)
    leitura = etl_bps.Leitura()
    feito = Importacao(sha256=sha)
    linhas: list[dict] = []
    anos: set[int] = set()
    for e in etl_bps.ler(caminho, url_snapshot=url, sha256=sha,
                         leitura=leitura):
        feito.linhas += 1
        if not e.validada:
            feito.quarentena.update(e.motivos)
            continue
        linha = linha_do_indice(e)
        anos.add(linha["ano"])
        linhas.append(linha)
    unicas = {linha["registro_id"]: linha for linha in linhas}
    feito.duplicadas = len(linhas) - len(unicas)
    linhas = list(unicas.values())
    feito.validas = len(linhas)
    if len(anos) != 1:
        feito.desfecho, feito.motivo = RECUSADO, (
            "arquivo sem linha válida" if not anos
            else f"arquivo mistura anos de compra: {sorted(anos)}")
        return feito
    feito.ano = anos.pop()

    existente = armazem.versao(feito.ano, sha)
    if existente and existente.get("estado") == PUBLICADO:
        feito.desfecho = "ja_publicado"
        return feito
    publicada = armazem.versao_publicada(feito.ano)
    if publicada is not None:
        feito.validas_na_versao_anterior = int(publicada.get("validas") or 0)
        if feito.validas < feito.validas_na_versao_anterior * PISO_DE_REDUCAO:
            feito.desfecho, feito.motivo = RECUSADO, (
                f"{feito.validas} linhas válidas contra "
                f"{feito.validas_na_versao_anterior} da versão publicada — "
                "redução acima do tolerado; a versão anterior continua valendo")
            armazem.registrar_versao(
                feito.ano, sha, estado=RECUSADO, url=url, motivo=feito.motivo,
                linhas=feito.linhas, validas=feito.validas,
                quarentena=dict(feito.quarentena),
                versao_parser=etl_bps.VERSAO_PARSER)
            return feito

    armazem.registrar_versao(
        feito.ano, sha, estado=IMPORTANDO, url=url, motivo="",
        last_modified=last_modified, linhas=feito.linhas,
        validas=feito.validas, quarentena=dict(feito.quarentena),
        versao_parser=etl_bps.VERSAO_PARSER,
        versao_importador=VERSAO_IMPORTADOR)
    for inicio in range(0, len(linhas), LOTE):
        armazem.gravar_registros(linhas[inicio:inicio + LOTE])
    armazem.publicar(feito.ano, sha, publicado_em=datetime.now(
        timezone.utc).isoformat(timespec="seconds"))
    feito.desfecho = PUBLICADO
    return feito


# ---------------------------------------------------------------------------
# Fonte de preço — só lê o índice
# ---------------------------------------------------------------------------
def referencia_da_linha(linha: dict) -> Referencia | None:
    unitario, quantidade = _dec(linha.get("valor_unitario")), _dec(
        linha.get("quantidade"))
    if unitario is None or unitario <= 0 or not linha.get("registro_id") \
            or linha.get("esfera") not in etl_bps.ESFERAS_PUBLICAS:
        return None
    try:
        data = date.fromisoformat(str(linha.get("data_compra"))[:10])
    except ValueError:
        data = None
    bruto = {k: linha.get(k) for k in (
        "registro_id", "co_seq_bps", "ano", "catmat", "apresentacao", "esfera",
        "tipo_compra", "generico", "registro_anvisa", "processo",
        "url_evidencia", "url_arquivo", "arquivo_sha256", "hash_linha",
        "versao_parser")}
    bruto["compra_publica"] = True
    referencia = Referencia(
        fonte=FONTE_BPS, id_externo=str(linha["registro_id"]), bruto=bruto,
        descricao_original=str(linha.get("descricao") or ""),
        unidade_original=linha.get("unidade"),
        quantidade_original=quantidade,
        valor_unitario_original=unitario,
        codigo_catalogo=linha.get("catmat"), tipo_catalogo="CATMAT",
        orgao=linha.get("orgao"), uf=linha.get("uf"),
        municipio=linha.get("municipio"),
        ni_fornecedor=linha.get("fornecedor_cnpj"),
        modalidade=linha.get("modalidade"), data_compra=data,
        referencia_externa=f"BPS {linha.get('co_seq_bps') or ''}".strip(),
        natureza_valor=NaturezaValor.PRATICADO)
    # o que o revisor precisa comparar com o item, à vista na referência
    referencia.com_motivo(
        f"BPS: CATMAT {linha.get('catmat')}, apresentação "
        f"{linha.get('apresentacao') or 'não informada'}, unidade de "
        f"fornecimento {linha.get('unidade')}; compra pública "
        f"({str(linha.get('esfera') or '').lower()}), preço pago")
    return referencia


def url_de_verificacao(bruto: dict) -> str | None:
    """A consulta oficial do CATMAT, remontada do código — nunca copiada."""
    return etl_bps.url_da_consulta((bruto or {}).get("catmat"))


Buscador = Callable[..., list]


def _mesmo_principio(procurados: set[str], descricao: str) -> bool:
    """
    O nome do medicamento na linha do BPS aparece no item?

    A descrição do BPS é a do CATMAT: o nome vem ANTES da primeira vírgula
    ("DIPIRONA SÓDICA, DOSAGEM: 500 MG"); o resto são palavras de catálogo
    que todo injetável ou comprimido compartilha. Exige-se a palavra mais
    longa das duas primeiras do nome — sem isso, "100 MG/ML solução
    injetável" trazia levetiracetam para uma busca de palivizumabe.
    """
    from .compras_gov import _sem_acento

    nome = [p.strip(".:()") for p in _sem_acento(
        descricao.split(",")[0]).replace("/", " ").split()]
    nome = [p for p in nome if len(p) > 2][:2]
    if not nome or max(nome, key=len) not in procurados:
        return False
    # "AMOXICILINA, PRINCÍPIO ATIVO: ASSOCIADO À CLARITROMICINA…" é outro
    # produto: associação só casa com item que também a declare
    associado = "ASSOCIAD" in _sem_acento(descricao)
    return not associado or any(p.startswith("ASSOCIAD") for p in procurados)


class BPSIndice(FontePesquisaPreco):
    """Preço pago em compras públicas de medicamentos, lido do índice."""

    fonte = FONTE_BPS
    capacidades = frozenset({Capacidade.PRECO, Capacidade.EVIDENCIA})

    def __init__(self, buscar: Buscador) -> None:
        self._buscar = buscar

    def pesquisar(self, consulta: Consulta) -> ResultadoBusca:
        from .compras_gov import _casa, _tokens
        from .pncp_indice import termos_da_consulta

        resultado = ResultadoBusca(fonte=self.fonte)
        catmat = None
        codigo = str(consulta.codigo_catalogo or "").strip()
        if codigo.isdigit() and consulta.tipo_catalogo in (None, "", "CATMAT"):
            catmat = codigo
        termos = termos_da_consulta(dataclasses.replace(
            consulta, descricao=separar_dose(consulta.descricao),
            termos_alternativos=tuple(separar_dose(t)
                                      for t in consulta.termos_alternativos)))
        if not termos and not catmat:
            return resultado.registrar(
                "BPS: descrição sem termo pesquisável no índice")
        filtros = dict(uf=consulta.uf, desde=consulta.data_inicial,
                       ate=consulta.data_final, limite=consulta.limite)
        try:
            linhas: list = []
            if catmat:
                # com CATMAT a identidade é o código: SÓ ele, sem termos —
                # palavra de catálogo ("concentração", "solução injetável")
                # traria outro medicamento
                resultado.chamadas += 1
                linhas = self._buscar([], catmat=catmat, **filtros)
            if not catmat or (isinstance(linhas, list) and not linhas
                              and termos):
                # sem código, ou código que o BPS não conhece (código
                # interno do município): pela descrição
                catmat = None
                resultado.chamadas += 1
                linhas = self._buscar(termos, catmat=None, **filtros)
        except Exception as erro:  # noqa: BLE001 — índice fora não derruba a busca
            return resultado.falhar(
                "o índice do BPS não respondeu agora "
                f"({type(erro).__name__}); a pesquisa continua nas demais "
                "fontes")
        if not isinstance(linhas, list):
            return resultado.falhar("o índice do BPS devolveu resposta "
                                    "inesperada")
        procurados = {t.upper() for t in termos}
        for linha in linhas:
            if not isinstance(linha, dict):
                continue
            mesmo_codigo = bool(catmat) and linha.get("catmat") == catmat
            descricao = str(linha.get("descricao") or "")
            if not mesmo_codigo and not (
                    _casa(procurados, _tokens(separar_dose(descricao)))
                    and _mesmo_principio(procurados, descricao)):
                continue
            referencia = referencia_da_linha(linha)
            if referencia is not None:
                resultado.referencias.append(referencia)
                resultado.codigo_confirmado |= mesmo_codigo
        return resultado

    def healthcheck(self) -> bool:
        try:
            return isinstance(self._buscar(["dipirona"], catmat=None, uf=None,
                                           desde=None, ate=None, limite=1),
                              list)
        except Exception:  # noqa: BLE001
            return False
