"""
Importação nacional contínua para o índice do PNCP (0042), com fila durável
(0045): partições de trabalho com lease, um líder por vez, limitador global
de requisições e checkpoint — a carga sobrevive a queda, reinício e pausa, e
não depende de sessão nenhuma.

FONTES (`precos_pncp_tarefas.fonte`)
  * ``comprasgov_lote`` — um DIA de resultados das contratações conduzidas
    no Compras.gov, pela API de Dados Abertos
    (``3_consultarResultadoItensContratacoes_PNCP_14133``): ~11 mil resultados
    por dia em ~23 páginas, contra uma chamada por item no PNCP. Medido em
    13/11/2026: 27 UFs, mas SÓ quem conduz no Compras.gov — Careaçu/MG, Dom
    Pedro/MA e Santa Helena de Goiás/GO (outras plataformas) não aparecem. É
    a fatia que o coletor antigo excluía (`fora_do_piloto`);
  * ``pncp_descoberta`` / ``pncp_contratacao`` — o restante dos publicadores,
    item a item no PNCP (próximo incremento; a fila já os comporta).

Cada linha passa pela MESMA conferência do índice
(`pncp_indice.linha_do_resultado`): só item homologado, sem julgamento por
desconto, sem pessoa física, total coerente. Mesma chave
(`controle#item#sequencial`) que o coletor do PNCP — a mesma compra vista
pelos dois caminhos conta uma vez.

Este módulo não decide preço nem cesta: só alimenta o índice.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, Protocol

from . import pncp_indice

VERSAO = "2026-11-14.pncp-integral.2"
FONTES = ("comprasgov_lote", "pncp_descoberta", "pncp_contratacao")
ESTADOS_FINAIS = ("pendente", "concluida", "parcial", "falha", "quarentena")
DADOS_ABERTOS = "https://dadosabertos.compras.gov.br/modulo-contratacoes"
PAGINA_LOTE = 500
LEASE_S = 600
CONFIRMACOES_RECUSADAS = [0]
TENTATIVAS_MAX = 6
PLATAFORMA = "Compras.gov.br"
# janela útil da cotação (IN 65/2021, art. 5º, II): o último ano vem primeiro
DIAS_RECENTES = 365


# ---------------------------------------------------------------------------
# Rede: limitador global e respostas distinguíveis
# ---------------------------------------------------------------------------
class FalhaTransitoria(Exception):
    """Timeout, 429, 5xx, JSON inválido: tentar de novo mais tarde."""

    def __init__(self, motivo: str, espera_s: float = 0.0) -> None:
        super().__init__(motivo)
        self.espera_s = espera_s


class RespostaParcial(Exception):
    """A fonte entregou menos do que declarou: nunca vira 'concluída'."""


class Limitador:
    """
    Um orçamento por host para TODO o processo: intervalo mínimo entre
    chamadas e pausa obrigatória quando a fonte pede (`Retry-After`). O
    intervalo de CADA host dobra a cada 429/5xx dele e volta devagar com
    sucesso — o 429 do PNCP não freia o Dados Abertos (medido em produção,
    14/11/2026: o PNCP recusava a 1 req/s, o Dados Abertos não).
    """

    def __init__(self, req_por_s: float = 1.0, relogio=time.monotonic,
                 dormir=time.sleep) -> None:
        self.base = 1.0 / max(0.05, req_por_s)
        self._base_host: dict[str, float] = {}
        self._intervalo: dict[str, float] = {}
        self._proxima: dict[str, float] = {}
        self._trava = threading.Lock()
        self._relogio, self._dormir = relogio, dormir

    def intervalo(self, host: str) -> float:
        base = self._base_host.get(host, self.base)
        return max(base, self._intervalo.get(host, base))

    def definir_ritmo(self, host: str, req_por_s: float) -> None:
        """Orçamento próprio do host (o Compras.gov aceita mais que o PNCP)."""
        with self._trava:
            self._base_host[host] = 1.0 / max(0.05, float(req_por_s))

    def aguardar(self, host: str) -> float:
        """Espera a vez do host; devolve quanto dormiu (métrica)."""
        with self._trava:
            agora = self._relogio()
            vez = max(agora, self._proxima.get(host, 0.0))
            self._proxima[host] = vez + self.intervalo(host)
        if vez > agora:
            self._dormir(vez - agora)
            return vez - agora
        return 0.0

    def respeitar(self, host: str, espera_s: float) -> None:
        with self._trava:
            self._proxima[host] = max(self._proxima.get(host, 0.0),
                                      self._relogio() + espera_s)
            self._intervalo[host] = min(self.intervalo(host) * 2, 60.0)

    def sucesso(self, host: str) -> None:
        with self._trava:
            self._intervalo[host] = max(self._base_host.get(host, self.base),
                                        self.intervalo(host) * 0.9)


def _abrir(url: str, timeout: float = 90.0) -> tuple[int, dict, bytes]:
    pedido = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": "GovConect-indexador/1"})
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as r:  # noqa: S310 — URL fixa
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as erro:
        return erro.code, dict(erro.headers or {}), erro.read() or b""
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as erro:
        raise FalhaTransitoria(f"rede: {type(erro).__name__}") from None


# 429/5xx/rede: o cliente tenta de novo, respeitando o Retry-After do host,
# antes de devolver a falha à tarefa — medido em 14/11/2026: sem isso uma
# contratação grande do PNCP nunca terminava (um 429 perdia tudo).
TENTATIVAS_HTTP = 3


class ClienteHttp:
    """
    Uma pista de trabalho (Compras.gov OU PNCP) — o limitador é por host e
    compartilhado; os contadores são desta pista. Mede separadamente a
    espera imposta pelo limitador e o tempo da requisição em si.
    """

    def __init__(self, limitador: Limitador, abrir: Callable = _abrir) -> None:
        self.limitador, self._abrir = limitador, abrir
        self.chamadas = 0
        self.falhas: dict[str, int] = {}
        self.espera_s = 0.0
        self.requisicao_s = 0.0

    def medida(self) -> tuple[int, float, float]:
        return self.chamadas, self.espera_s, self.requisicao_s

    def _falhou(self, motivo: str) -> None:
        self.falhas[motivo] = self.falhas.get(motivo, 0) + 1

    def json(self, url: str):
        host = urllib.parse.urlsplit(url).netloc
        erro: FalhaTransitoria | None = None
        for _ in range(TENTATIVAS_HTTP):
            self.espera_s += self.limitador.aguardar(host) or 0.0
            self.chamadas += 1
            inicio = time.monotonic()
            try:
                status, cabecalhos, corpo = self._abrir(url)
            except FalhaTransitoria as e:
                self.requisicao_s += time.monotonic() - inicio
                self._falhou("rede")
                self.limitador.respeitar(host, 5.0)
                erro = e
                continue
            self.requisicao_s += time.monotonic() - inicio
            if status == 429 or status >= 500:
                espera = _retry_after(cabecalhos) or (30.0 if status == 429 else 10.0)
                self.limitador.respeitar(host, espera)
                self._falhou(str(status))
                erro = FalhaTransitoria(f"http {status}", espera)
                continue
            if status == 204:
                self.limitador.sucesso(host)
                return None
            if status != 200:
                self._falhou(str(status))
                raise FalhaTransitoria(f"http {status}")
            try:
                dados = json.loads(corpo.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._falhou("json")
                raise FalhaTransitoria("json inválido") from None
            self.limitador.sucesso(host)
            return dados
        raise erro  # type: ignore[misc]


def _retry_after(cabecalhos: dict) -> float:
    for chave, valor in cabecalhos.items():
        if chave.lower() == "retry-after":
            try:
                return max(0.0, float(valor))
            except (TypeError, ValueError):
                return 60.0
    return 0.0


# ---------------------------------------------------------------------------
# Compras.gov em lote
# ---------------------------------------------------------------------------
def _url(rota: str, **params) -> str:
    return f"{DADOS_ABERTOS}/{rota}?{urllib.parse.urlencode(params)}"


def _pagina_valida(dados) -> tuple[list, int]:
    if not isinstance(dados, dict) or not isinstance(dados.get("resultado"), list):
        raise FalhaTransitoria("formato inesperado")
    return dados["resultado"], int(dados.get("totalRegistros") or 0)


def _chave_lote(r: dict) -> tuple:
    return (r.get("idContratacaoPNCP"), r.get("numeroItemPncp"), r.get("sequencialResultado"))


# Releituras do dia quando a paginação devolve menos únicas que o total
# declarado — medido em produção (14/11/2026): 9.599 de 9.695 no servidor,
# 9.695 de 9.695 na mesma hora fora dele. A paginação da fonte é instável;
# outra passada completa a união.
PASSADAS_DO_DIA = 3
# cabeçalhos e itens guardados entre tarefas (releitura do mesmo dia e dias
# vizinhos reaproveitam); só os campos que a conversão lê, com teto — o
# contêiner tem 256 MB
CACHE_COMPRAS = 3000
_CAMPOS_CONTRATACAO = ("numeroControlePNCP", "modalidadeIdPncp", "modalidadeNome",
                       "anoCompraPncp", "sequencialCompraPncp", "numeroCompra", "processo",
                       "srp", "dataAtualizacaoPncp", "dataPublicacaoPncp",
                       "situacaoCompraNomePncp", "orgaoEntidadeCnpj",
                       "orgaoEntidadeRazaoSocial", "orgaoEntidadeEsferaId",
                       "orgaoEntidadePoderId", "unidadeOrgaoUfSigla",
                       "unidadeOrgaoMunicipioNome", "unidadeOrgaoCodigoIbge",
                       "unidadeOrgaoNomeUnidade")
_CAMPOS_ITEM = ("numeroItemPncp", "descricaodetalhada", "descricaoResumida", "unidadeMedida",
                "quantidade", "materialOuServico", "codItemCatalogo",
                "criterioJulgamentoNome", "situacaoCompraItem", "situacaoCompraItemNome",
                "valorUnitarioEstimado")


def _guardar(cache: dict, chave: str, valor) -> None:
    if len(cache) >= CACHE_COMPRAS:
        cache.pop(next(iter(cache)))
    cache[chave] = valor


class ComprasGovLote:
    def __init__(self, http: ClienteHttp) -> None:
        self.http = http
        self._contratacoes: dict[str, dict] = {}
        self._itens: dict[str, dict[int, dict]] = {}

    def _uma_passada(self, dia: date) -> tuple[list[dict], int]:
        linhas: list[dict] = []
        pagina, total = 1, 0
        while True:
            dados = self.http.json(_url(
                "3_consultarResultadoItensContratacoes_PNCP_14133", pagina=pagina,
                tamanhoPagina=PAGINA_LOTE, dataResultadoPncpInicial=dia.isoformat(),
                dataResultadoPncpFinal=dia.isoformat()))
            resultado, declarado = _pagina_valida(dados)
            total = max(total, declarado)
            linhas.extend(resultado)
            if not resultado or int(dados.get("paginasRestantes") or 0) <= 0:
                return linhas, total
            pagina += 1

    def resultados_do_dia(self, dia: date) -> tuple[list[dict], int, int]:
        """
        (resultados únicos, total declarado, linhas recebidas). Menos únicos
        que o declarado depois de `PASSADAS_DO_DIA` passadas NÃO descarta o
        lido: quem chama grava e registra a falta (`faltantes`).
        """
        unicas: dict[tuple, dict] = {}
        recebidas, declarado = 0, 0
        for _ in range(PASSADAS_DO_DIA):
            linhas, total = self._uma_passada(dia)
            recebidas += len(linhas)
            declarado = max(declarado, total)
            for r in linhas:
                unicas.setdefault(_chave_lote(r), r)
            if len(unicas) >= declarado:
                break
        return list(unicas.values()), declarado, recebidas

    def contratacao(self, id_compra: str) -> dict:
        if id_compra not in self._contratacoes:
            dados = self.http.json(_url("1.1_consultarContratacoes_PNCP_14133_Id",
                                        tipo="idCompra", codigo=id_compra))
            bruto = dados.get("resultado") if isinstance(dados, dict) else None
            resultado = bruto if isinstance(bruto, list) else [bruto]
            if not resultado or not isinstance(resultado[0], dict):
                raise RespostaParcial(f"contratação {id_compra} ausente")
            _guardar(self._contratacoes, id_compra,
                     {k: resultado[0].get(k) for k in _CAMPOS_CONTRATACAO})
        return self._contratacoes[id_compra]

    def itens(self, id_compra: str) -> dict[int, dict]:
        if id_compra not in self._itens:
            dados = self.http.json(_url("2.1_consultarItensContratacoes_PNCP_14133_Id",
                                        tipo="idCompra", codigo=id_compra))
            resultado, total = _pagina_valida(dados)
            if len(resultado) < total:
                raise RespostaParcial(f"{len(resultado)} de {total} itens de {id_compra}")
            _guardar(self._itens, id_compra,
                     {int(i.get("numeroItemPncp") or 0): {k: i.get(k) for k in _CAMPOS_ITEM}
                      for i in resultado})
        return self._itens[id_compra]


def no_formato_do_pncp(contratacao: dict, item: dict, resultado: dict
                       ) -> tuple[dict, dict, dict]:
    """
    As três peças no formato que `pncp_indice.linha_do_resultado` lê — a
    mesma conferência do coletor do PNCP, sem caminho paralelo.
    """
    contr = {
        "numeroControlePNCP": contratacao.get("numeroControlePNCP"),
        "linkSistemaOrigem": None,
        "modalidadeId": contratacao.get("modalidadeIdPncp"),
        "modalidadeNome": contratacao.get("modalidadeNome"),
        "usuarioNome": PLATAFORMA,
        "anoCompra": contratacao.get("anoCompraPncp"),
        "sequencialCompra": contratacao.get("sequencialCompraPncp"),
        "numeroCompra": contratacao.get("numeroCompra"),
        "processo": contratacao.get("processo"),
        "srp": contratacao.get("srp"),
        "dataAtualizacaoGlobal": contratacao.get("dataAtualizacaoPncp"),
        "dataPublicacaoPncp": contratacao.get("dataPublicacaoPncp"),
        "situacaoCompraNome": contratacao.get("situacaoCompraNomePncp"),
        "orgaoEntidade": {"cnpj": contratacao.get("orgaoEntidadeCnpj"),
                          "razaoSocial": contratacao.get("orgaoEntidadeRazaoSocial"),
                          "esferaId": contratacao.get("orgaoEntidadeEsferaId"),
                          "poderId": contratacao.get("orgaoEntidadePoderId")},
        "unidadeOrgao": {"ufSigla": contratacao.get("unidadeOrgaoUfSigla"),
                         "municipioNome": contratacao.get("unidadeOrgaoMunicipioNome"),
                         "codigoIbge": contratacao.get("unidadeOrgaoCodigoIbge"),
                         "nomeUnidade": contratacao.get("unidadeOrgaoNomeUnidade")},
    }
    try:
        situacao = int(item.get("situacaoCompraItem"))
    except (TypeError, ValueError):
        situacao = None
    it = {
        "numeroItem": item.get("numeroItemPncp"),
        "descricao": item.get("descricaodetalhada") or item.get("descricaoResumida"),
        "unidadeMedida": item.get("unidadeMedida"),
        "quantidade": item.get("quantidade"),
        "materialOuServico": item.get("materialOuServico"),
        "catalogoCodigoItem": item.get("codItemCatalogo"),
        "criterioJulgamentoNome": item.get("criterioJulgamentoNome"),
        "situacaoCompraItem": situacao,
        "situacaoCompraItemNome": item.get("situacaoCompraItemNome"),
        "valorUnitarioEstimado": item.get("valorUnitarioEstimado"),
    }
    res = {
        "numeroItem": resultado.get("numeroItemPncp"),
        "sequencialResultado": resultado.get("sequencialResultado"),
        "niFornecedor": resultado.get("niFornecedor"),
        "tipoPessoa": resultado.get("tipoPessoa"),
        "nomeRazaoSocialFornecedor": resultado.get("nomeRazaoSocialFornecedor"),
        "quantidadeHomologada": resultado.get("quantidadeHomologada"),
        "valorUnitarioHomologado": resultado.get("valorUnitarioHomologado"),
        "valorTotalHomologado": resultado.get("valorTotalHomologado"),
        "percentualDesconto": resultado.get("percentualDesconto"),
        "situacaoCompraItemResultadoId": resultado.get("situacaoCompraItemResultadoId"),
        "situacaoCompraItemResultadoNome": resultado.get("situacaoCompraItemResultadoNome"),
        "dataResultado": resultado.get("dataResultadoPncp"),
        "dataCancelamento": resultado.get("dataCancelamentoPncp"),
        "moedaEstrangeira": resultado.get("moedaEstrangeiraId"),
        "porteFornecedorNome": resultado.get("porteFornecedorNome"),
    }
    return contr, it, res


@dataclass
class Totais:
    """
    O que UMA tarefa leu e fez, gravado em `precos_pncp_tarefas.totais` — a
    métrica persistente da carga. `recebidos` é o que a fonte entregou;
    `resultados`, os únicos; cada recusa tem o seu motivo; `gravadas` se
    divide em `inseridas` (linha nova no índice), `atualizadas` (mesma
    chave, conteúdo novo — correção) e `inalteradas` (já estava igual).
    Os tempos separam a espera do limitador, a requisição, a transformação,
    a validação e a gravação: o gargalo se lê aqui, não se supõe.
    """

    resultados: int = 0
    gravadas: int = 0
    recusadas: dict = field(default_factory=dict)
    contratacoes: int = 0
    chamadas: int = 0
    recebidos: int = 0
    declarados: int = 0
    faltantes: int = 0
    inseridas: int = 0
    atualizadas: int = 0
    inalteradas: int = 0
    invalidadas: int = 0
    falhas_gravacao: int = 0
    puladas_por_retomada: int = 0
    tempos: dict = field(default_factory=lambda: {
        "espera_s": 0.0, "requisicao_s": 0.0, "transformacao_s": 0.0,
        "validacao_s": 0.0, "gravacao_s": 0.0})

    def recusar(self, motivo: str, n: int = 1) -> None:
        self.recusadas[motivo] = self.recusadas.get(motivo, 0) + n

    def rede(self, http: "ClienteHttp", antes: tuple[int, float, float]) -> None:
        chamadas, espera, requisicao = http.medida()
        self.chamadas += chamadas - antes[0]
        self.tempos["espera_s"] += espera - antes[1]
        self.tempos["requisicao_s"] += requisicao - antes[2]

    def registro(self) -> dict:
        return {"resultados": self.resultados, "gravadas": self.gravadas,
                "recusadas": self.recusadas, "contratacoes": self.contratacoes,
                "chamadas": self.chamadas, "recebidos": self.recebidos,
                "declarados": self.declarados, "faltantes": self.faltantes,
                "inseridas": self.inseridas, "atualizadas": self.atualizadas,
                "inalteradas": self.inalteradas, "invalidadas": self.invalidadas,
                "falhas_gravacao": self.falhas_gravacao,
                "puladas_por_retomada": self.puladas_por_retomada,
                "tempos": {k: round(v, 3) for k, v in self.tempos.items()}}


class FalhaGravacao(FalhaTransitoria):
    """O banco recusou a gravação — nunca calada: vira erro da tarefa e
    `falhas_gravacao` nos totais."""


def gravar(armazem, linhas: list[dict], totais: Totais) -> None:
    if not linhas:
        return
    inicio = time.monotonic()
    try:
        contagem = armazem.gravar_resultados(linhas)
    except Exception as erro:  # noqa: BLE001 — qualquer recusa do banco conta e sobe
        totais.falhas_gravacao += len(linhas)
        raise FalhaGravacao(f"gravação: {type(erro).__name__}: {str(erro)[:300]}") from erro
    finally:
        totais.tempos["gravacao_s"] += time.monotonic() - inicio
    totais.gravadas += len(linhas)
    if isinstance(contagem, dict):
        totais.inseridas += int(contagem.get("inseridas") or 0)
        totais.atualizadas += int(contagem.get("atualizadas") or 0)
        totais.inalteradas += int(contagem.get("inalteradas") or 0)


def _converter(totais: Totais, contratacao: dict, item: dict, resultado: dict):
    """Transformação e validação medidas em separado."""
    inicio = time.monotonic()
    pecas = no_formato_do_pncp(contratacao, item, resultado)
    meio = time.monotonic()
    linha, motivo = pncp_indice.linha_do_resultado(*pecas)
    totais.tempos["transformacao_s"] += meio - inicio
    totais.tempos["validacao_s"] += time.monotonic() - meio
    return linha, motivo


def _id_compra(r: dict) -> str:
    return str(r.get("idCompraItem") or "")[:17] or str(r.get("idCompra") or "")


def importar_dia(lote: ComprasGovLote, armazem, dia: date, *,
                 lote_gravacao: int = 500, renovar: Callable[[], None] | None = None,
                 retomar_depois_de: str = "") -> Totais:
    """
    Um dia inteiro do Compras.gov no índice, gravando a cada
    `lote_gravacao` linhas. As contratações seguem em ordem de id: se a rede
    falhar no meio, o que foi lido já está gravado e a exceção leva
    `progresso` (`compra_feita_ate`) — a tentativa seguinte continua dali.
    Contratação sem cabeçalho ou com itens incompletos é recusada com motivo
    e conta como falta, sem derrubar o dia.
    """
    totais = Totais()
    antes = lote.http.medida()
    try:
        resultados, declarado, recebidos = lote.resultados_do_dia(dia)
    finally:
        totais.rede(lote.http, antes)
    totais.recebidos, totais.declarados = recebidos, declarado
    totais.resultados = len(resultados)
    totais.faltantes = max(0, declarado - len(resultados))
    por_compra: dict[str, list[dict]] = {}
    for r in resultados:
        por_compra.setdefault(_id_compra(r), []).append(r)
    totais.contratacoes = len(por_compra)
    pendentes: list[dict] = []
    ultima = gravada_ate = retomar_depois_de
    antes = lote.http.medida()
    try:
        for i, id_compra in enumerate(sorted(por_compra)):
            linhas = por_compra[id_compra]
            if retomar_depois_de and id_compra <= retomar_depois_de:
                totais.puladas_por_retomada += len(linhas)
                continue
            try:
                contratacao = lote.contratacao(id_compra)
                itens = lote.itens(id_compra)
            except RespostaParcial:
                totais.recusar("contratacao_incompleta_na_fonte", len(linhas))
                totais.faltantes += len(linhas)
                ultima = id_compra
                continue
            for r in linhas:
                item = itens.get(int(r.get("numeroItemPncp") or 0))
                if item is None:
                    totais.recusar("item_ausente")
                    continue
                linha, motivo = _converter(totais, contratacao, item, r)
                if linha is None:
                    totais.recusar(motivo)
                    continue
                linha["versao_coletor"] = VERSAO
                pendentes.append(linha)
            ultima = id_compra
            if len(pendentes) >= lote_gravacao:
                gravar(armazem, pendentes, totais)
                pendentes, gravada_ate = [], ultima
            if renovar and i % 20 == 19:
                renovar()
        gravar(armazem, pendentes, totais)
        pendentes, gravada_ate = [], ultima
    except FalhaTransitoria as erro:
        if pendentes and not isinstance(erro, FalhaGravacao):
            try:
                gravar(armazem, pendentes, totais)
                gravada_ate = ultima
            except FalhaGravacao:
                pass
        totais.rede(lote.http, antes)
        erro.progresso = {"compra_feita_ate": gravada_ate} if gravada_ate else {}
        erro.totais = totais.registro()
        raise
    totais.rede(lote.http, antes)
    return totais


# ---------------------------------------------------------------------------
# PNCP item a item (publicadores fora do Compras.gov)
# ---------------------------------------------------------------------------
PNCP_CONSULTA = "https://pncp.gov.br/api/consulta/v1"
PNCP_API = "https://pncp.gov.br/api/pncp/v1"
PAGINA_DESCOBERTA = 50
PAGINA_ITENS = 500
# catálogo medido em 13/11/2026 (1 a 14 respondem); código novo que apareça
# numa contratação é contado em `totais.modalidades`, nunca descartado calado
MODALIDADES = tuple(range(1, 15))


class PncpItemAItem:
    def __init__(self, http: ClienteHttp) -> None:
        self.http = http

    def pagina_de_publicacao(self, modalidade: int, dia: date, pagina: int, *,
                             rota: str = "publicacao") -> dict:
        """`rota="atualizacao"`: contratações ALTERADAS no dia (correção,
        resultado tardio) — a mesma página, outro filtro de data."""
        dados = self.http.json(
            f"{PNCP_CONSULTA}/contratacoes/{rota}?" + urllib.parse.urlencode({
                "dataInicial": dia.strftime("%Y%m%d"), "dataFinal": dia.strftime("%Y%m%d"),
                "codigoModalidadeContratacao": modalidade, "pagina": pagina,
                "tamanhoPagina": PAGINA_DESCOBERTA}))
        if dados is None:  # 204: dia sem publicação nessa modalidade
            return {"data": [], "totalRegistros": 0, "paginasRestantes": 0}
        if not isinstance(dados, dict) or not isinstance(dados.get("data"), list):
            raise FalhaTransitoria("formato inesperado na publicação")
        return dados

    def itens(self, cnpj: str, ano, sequencial) -> list[dict]:
        base = f"{PNCP_API}/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens"
        itens, pagina = [], 1
        while True:
            lote = self.http.json(f"{base}?pagina={pagina}&tamanhoPagina={PAGINA_ITENS}") or []
            if not isinstance(lote, list):
                raise FalhaTransitoria("formato inesperado nos itens")
            itens.extend(lote)
            if len(lote) < PAGINA_ITENS:
                break
            pagina += 1
        declarado = self.http.json(f"{base}/quantidade")
        if isinstance(declarado, int) and len({i.get("numeroItem") for i in itens}) < declarado:
            raise RespostaParcial(f"{len(itens)} de {declarado} itens")
        return itens

    def resultados(self, cnpj: str, ano, sequencial, numero) -> list[dict]:
        dados = self.http.json(
            f"{PNCP_API}/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{numero}/resultados")
        if dados is None:
            return []
        if not isinstance(dados, list):
            raise FalhaTransitoria("formato inesperado nos resultados")
        return dados


# Releitura SOBREPOSTA: os últimos dias são relidos todo dia mesmo quando já
# trouxeram resultado (publicação tardia, correção, a base em lote que
# atrasa 1–2 dias); depois o intervalo cresce. Reler custa o mesmo que ler.
DIAS_RELIDOS_TODO_DIA = 3


def _revisita(dia: date | None) -> timedelta | None:
    """Quando reler: diário nos últimos 3 dias, semanal no mês, a cada 60
    dias no ano; o histórico não volta (None = leitura final)."""
    idade = (date.today() - dia).days if dia else 0
    if idade < DIAS_RELIDOS_TODO_DIA:
        return timedelta(days=1)
    if idade < 30:
        return timedelta(days=7)
    if idade < DIAS_RECENTES:
        return timedelta(days=60)
    return None


def _particao_descoberta(particao: str) -> tuple[str, int, date]:
    """`6:2026-10-29` (publicação) ou `u:6:2026-10-29` (atualização)."""
    partes = particao.split(":")
    rota = "atualizacao" if partes[0] == "u" else "publicacao"
    return rota, int(partes[-2]), date.fromisoformat(partes[-1])


def executar_descoberta(tarefa: dict, *, pncp: PncpItemAItem, fila: "Fila",
                        lease_s: int = LEASE_S) -> dict:
    """
    Uma modalidade num dia: todas as páginas; cada contratação de fora do
    Compras.gov vira tarefa `pncp_contratacao` (o cabeçalho vai no
    checkpoint). Na rota de ATUALIZAÇÃO, a contratação que já estava na fila
    (lida ou esperando revisita) é reagendada para agora — é assim que a
    correção e o resultado tardio entram. Menos contratações únicas que o
    total declarado = parcial.
    """
    rota, modalidade, dia = _particao_descoberta(tarefa["particao"])
    vistas: set[str] = set()
    totais = {"contratacoes": 0, "comprasgov": 0, "enfileiradas": 0, "reagendadas": 0,
              "paginas": 0, "modalidades": {}, "chamadas": 0}
    antes = pncp.http.chamadas
    pagina, declarado = 1, 0
    while True:
        dados = pncp.pagina_de_publicacao(modalidade, dia, pagina, rota=rota)
        declarado = int(dados.get("totalRegistros") or 0)
        totais["paginas"] += 1
        novas = []
        for c in dados["data"]:
            controle = str(c.get("numeroControlePNCP") or "")
            if not controle or controle in vistas:
                continue
            vistas.add(controle)
            m = str(c.get("modalidadeId"))
            totais["modalidades"][m] = totais["modalidades"].get(m, 0) + 1
            if str(c.get("usuarioNome") or "") == PLATAFORMA:
                totais["comprasgov"] += 1   # vem em lote, pela outra fonte
                continue
            novas.append({"campanha": tarefa["campanha"], "fonte": "pncp_contratacao",
                          "particao": controle, "faixa": tarefa["faixa"],
                          "prioridade": tarefa["prioridade"],
                          "checkpoint": {"cabecalho": pncp_indice.resumo_da_contratacao(c)}})
        totais["enfileiradas"] += fila.criar(novas)
        if rota == "atualizacao" and novas:
            totais["reagendadas"] += fila.reagendar(
                tarefa["campanha"], "pncp_contratacao", [n["particao"] for n in novas])
        fila.renovar(tarefa, lease_s)
        if not dados["data"] or int(dados.get("paginasRestantes") or 0) <= 0:
            break
        pagina += 1
    totais["contratacoes"] = len(vistas)
    totais["chamadas"] = pncp.http.chamadas - antes
    if len(vistas) < declarado:
        raise RespostaParcial(f"{len(vistas)} de {declarado} contratações em {tarefa['particao']}")
    return totais


def executar_contratacao(tarefa: dict, *, pncp: PncpItemAItem, armazem,
                         renovar: Callable[[], None] | None = None,
                         lote_gravacao: int = 200) -> dict:
    """
    Todos os itens; resultado só do homologado; mesma conferência do índice.
    Grava a cada `lote_gravacao` linhas e renova o lease no caminho; se a
    rede falhar no meio, o que foi lido fica gravado e a exceção leva
    `progresso` (`item_feito_ate`) — a tentativa seguinte continua dali. Na
    leitura completa (sem retomada), resultado que sumiu da fonte é
    invalidado: correção e cancelamento tardios não ficam vigentes.
    """
    checkpoint = tarefa.get("checkpoint") or {}
    cabecalho = checkpoint.get("cabecalho") or {}
    orgao = (cabecalho.get("orgaoEntidade") or {}).get("cnpj")
    ano, sequencial = cabecalho.get("anoCompra"), cabecalho.get("sequencialCompra")
    if not (orgao and ano and sequencial):
        raise RespostaParcial("cabeçalho incompleto na tarefa")
    retomar = int(checkpoint.get("item_feito_ate") or 0)
    totais = Totais()
    antes = pncp.http.medida()
    try:
        itens = pncp.itens(orgao, ano, sequencial)
    finally:
        totais.rede(pncp.http, antes)
    itens.sort(key=lambda i: int(i.get("numeroItem") or 0))
    homologados, sem_homologacao = 0, 0
    linhas: list[dict] = []
    ids: set[str] = set()
    ultimo = feito_ate = retomar
    antes = pncp.http.medida()
    try:
        for n, item in enumerate(itens):
            numero = int(item.get("numeroItem") or 0)
            if item.get("situacaoCompraItem") != pncp_indice.SITUACAO_ITEM_HOMOLOGADO:
                sem_homologacao += 1
                continue
            homologados += 1
            if numero <= retomar:
                continue
            recebidos = pncp.resultados(orgao, ano, sequencial, numero)
            totais.recebidos += len(recebidos)
            for r in recebidos:
                inicio = time.monotonic()
                linha, motivo = pncp_indice.linha_do_resultado(cabecalho, item, r)
                totais.tempos["validacao_s"] += time.monotonic() - inicio
                if linha is None:
                    totais.recusar(motivo)
                    continue
                linha["versao_coletor"] = VERSAO
                linhas.append(linha)
                ids.add(linha["id_externo"])
            ultimo = numero
            if len(linhas) >= lote_gravacao:
                gravar(armazem, linhas, totais)
                linhas, feito_ate = [], ultimo
            if renovar and n % 20 == 19:
                renovar()
        gravar(armazem, linhas, totais)
        linhas, feito_ate = [], ultimo
    except FalhaTransitoria as erro:
        if linhas and not isinstance(erro, FalhaGravacao):
            try:
                gravar(armazem, linhas, totais)
                feito_ate = ultimo
            except FalhaGravacao:
                pass
        totais.rede(pncp.http, antes)
        erro.progresso = {"item_feito_ate": feito_ate} if feito_ate else {}
        erro.totais = {**totais.registro(), "itens": len(itens), "homologados": homologados}
        raise
    totais.rede(pncp.http, antes)
    totais.resultados = totais.recebidos - sum(totais.recusadas.values())
    if not retomar and int(checkpoint.get("leituras") or 0) > 0:
        # releitura completa: o que estava vigente e não veio agora saiu da fonte
        totais.invalidadas = armazem.invalidar(
            str(cabecalho.get("numeroControlePNCP") or tarefa["particao"]), manter=ids,
            itens=None, motivo="releitura: resultado não consta mais no PNCP")
    return {**totais.registro(), "itens": len(itens), "homologados": homologados,
            "sem_homologacao": sem_homologacao}


class Fila(Protocol):
    def liderar(self, dono: str, lease_s: int) -> bool: ...
    def reservar(self, dono: str, fontes: Iterable[str], limite: int, lease_s: int) -> list[dict]: ...
    def renovar(self, tarefa: dict, lease_s: int) -> bool: ...
    def concluir(self, tarefa: dict, estado: str, *, checkpoint=None, totais=None,
                 erro: str = "", proxima_em: datetime | None = None) -> bool: ...
    def criar(self, tarefas: list[dict]) -> int: ...
    def controle(self) -> dict: ...
    def ajustar_controle(self, **campos) -> None: ...
    def resumo(self, campanha: str | None) -> list[dict]: ...
    def reabrir(self, campanha: str | None, estados: Iterable[str], fonte: str | None) -> int: ...
    def reagendar(self, campanha: str, fonte: str, particoes: list[str]) -> int: ...


def _agora() -> datetime:
    return datetime.now(timezone.utc)


class FilaEmMemoria:
    """A mesma semântica das RPCs da 0045, para as provas."""

    def __init__(self) -> None:
        self.tarefas: list[dict] = []
        self.ctl = {"pausado": False, "motivo_pausa": "", "req_por_s": 1.0,
                    "lider": None, "lider_ate": None}
        self._trava = threading.Lock()

    def liderar(self, dono, lease_s):
        with self._trava:
            c = self.ctl
            if c["lider"] in (None, dono) or (c["lider_ate"] and c["lider_ate"] < _agora()):
                c["lider"], c["lider_ate"] = dono, _agora() + timedelta(seconds=lease_s)
                return True
            return False

    def reservar(self, dono, fontes, limite, lease_s):
        with self._trava:
            if self.ctl["pausado"]:
                return []
            agora = _agora()
            livres = [t for t in self.tarefas if t["fonte"] in fontes
                      and t["proxima_em"] <= agora
                      and (t["estado"] in ("pendente", "parcial")
                           or (t["estado"] == "em_execucao" and t["lease_ate"] < agora))]
            livres.sort(key=lambda t: (t["prioridade"], t["proxima_em"], t["id"]))
            saida = []
            for t in livres[:max(1, min(limite or 1, 100))]:
                lease = max(30, min(lease_s or 600, 3600))
                t.update(estado="em_execucao", dono=dono, token=str(uuid.uuid4()),
                         lease_ate=agora + timedelta(seconds=lease),
                         tentativas=t["tentativas"] + 1)
                saida.append(dict(t))
            return saida

    def _achar(self, tarefa):
        return next(t for t in self.tarefas if t["id"] == tarefa["id"])

    def renovar(self, tarefa, lease_s):
        with self._trava:
            t = self._achar(tarefa)
            if t["token"] != tarefa["token"] or t["estado"] != "em_execucao":
                return False
            t["lease_ate"] = _agora() + timedelta(seconds=lease_s)
            return True

    def concluir(self, tarefa, estado, *, checkpoint=None, totais=None, erro="",
                 proxima_em=None):
        with self._trava:
            t = self._achar(tarefa)
            if (t["token"] != tarefa["token"] or t["estado"] != "em_execucao"
                    or estado not in ESTADOS_FINAIS):
                return False
            t.update(estado=estado, erro=erro, dono=None, token=None, lease_ate=None,
                     proxima_em=proxima_em or _agora())
            if checkpoint is not None:
                t["checkpoint"] = checkpoint
            if totais is not None:
                t["totais"] = totais
            return True

    def criar(self, tarefas):
        with self._trava:
            chaves = {(t["campanha"], t["fonte"], t["particao"]) for t in self.tarefas}
            novas = 0
            for nova in tarefas:
                if (nova["campanha"], nova["fonte"], nova["particao"]) in chaves:
                    continue
                self.tarefas.append({"id": len(self.tarefas) + 1, "estado": "pendente",
                                     "tentativas": 0, "proxima_em": _agora(),
                                     "checkpoint": {}, "totais": {}, "erro": "",
                                     "dono": None, "token": None, "lease_ate": None,
                                     "prioridade": 100, "faixa": "recente", **nova})
                novas += 1
            return novas

    def controle(self):
        return dict(self.ctl)

    def ajustar_controle(self, **campos):
        self.ctl.update(campos)

    def resumo(self, campanha):
        return [dict(t) for t in self.tarefas if campanha in (None, t["campanha"])]

    def resumo_completo(self, campanha):
        return self.resumo(campanha)

    def reabrir_uma(self, tarefa):
        t = self._achar(tarefa)
        t.update(estado="pendente", proxima_em=_agora(), tentativas=0,
                 erro="divergência na reconciliação")

    def reagendar(self, campanha, fonte, particoes):
        alvo, n = set(particoes), 0
        with self._trava:
            for t in self.tarefas:
                if (t["campanha"], t["fonte"]) == (campanha, fonte) \
                        and t["particao"] in alvo and t["estado"] in ("concluida", "pendente"):
                    t.update(estado="pendente", proxima_em=_agora())
                    n += 1
        return n

    def reabrir(self, campanha, estados, fonte):
        n = 0
        for t in self.tarefas:
            if (campanha in (None, t["campanha"]) and t["estado"] in estados
                    and fonte in (None, t["fonte"])):
                t.update(estado="pendente", proxima_em=_agora(), erro="", tentativas=0)
                n += 1
        return n


class FilaSupabase:
    """As RPCs da 0045 pela credencial de servidor (PostgREST)."""

    def __init__(self, cliente) -> None:
        self._c = cliente

    def liderar(self, dono, lease_s):
        return bool(self._c.rpc("precos_pncp_liderar",
                                {"p_dono": dono, "p_lease_s": lease_s}).execute().data)

    def reservar(self, dono, fontes, limite, lease_s):
        return self._c.rpc("precos_pncp_reservar", {
            "p_dono": dono, "p_fontes": list(fontes), "p_limite": limite,
            "p_lease_s": lease_s}).execute().data or []

    def renovar(self, tarefa, lease_s):
        return bool(self._c.rpc("precos_pncp_renovar", {
            "p_id": tarefa["id"], "p_token": tarefa["token"],
            "p_lease_s": lease_s}).execute().data)

    def concluir(self, tarefa, estado, *, checkpoint=None, totais=None, erro="",
                 proxima_em=None):
        return bool(self._c.rpc("precos_pncp_concluir", {
            "p_id": tarefa["id"], "p_token": tarefa["token"], "p_estado": estado,
            "p_checkpoint": checkpoint, "p_totais": totais, "p_erro": erro,
            "p_proxima_em": proxima_em.isoformat() if proxima_em else None}).execute().data)

    def criar(self, tarefas):
        if not tarefas:
            return 0
        novas = 0
        for i in range(0, len(tarefas), 500):
            resposta = (self._c.table("precos_pncp_tarefas")
                        .upsert(tarefas[i:i + 500], on_conflict="campanha,fonte,particao",
                                ignore_duplicates=True).execute())
            novas += len(resposta.data or [])
        return novas

    def controle(self):
        dados = self._c.table("precos_pncp_controle").select("*").eq("id", 1).execute().data
        return dados[0] if dados else {}

    def ajustar_controle(self, **campos):
        self._c.table("precos_pncp_controle").update(
            {**campos, "atualizado_em": _agora().isoformat()}).eq("id", 1).execute()

    def resumo(self, campanha):
        saida, inicio = [], 0
        while True:  # pagina: o PostgREST corta em 1.000 linhas
            consulta = (self._c.table("precos_pncp_tarefas")
                        .select("fonte,faixa,estado,particao,tentativas,totais,erro,campanha")
                        .order("id").range(inicio, inicio + 999))
            if campanha:
                consulta = consulta.eq("campanha", campanha)
            lote = consulta.execute().data or []
            saida.extend(lote)
            if len(lote) < 1000:
                return saida
            inicio += 1000

    def resumo_completo(self, campanha):
        saida, inicio = [], 0
        while True:
            lote = (self._c.table("precos_pncp_tarefas")
                    .select("id,fonte,faixa,estado,particao,totais,checkpoint")
                    .eq("campanha", campanha).in_("fonte", ["comprasgov_lote", "pncp_descoberta"])
                    .order("id").range(inicio, inicio + 999).execute().data or [])
            saida.extend(lote)
            if len(lote) < 1000:
                return saida
            inicio += 1000

    def reabrir_uma(self, tarefa):
        (self._c.table("precos_pncp_tarefas")
         .update({"estado": "pendente", "proxima_em": _agora().isoformat(), "tentativas": 0,
                  "erro": "divergência na reconciliação"})
         .eq("id", tarefa["id"]).neq("estado", "em_execucao").execute())

    def reagendar(self, campanha, fonte, particoes):
        """Contratação ALTERADA na fonte volta para agora (lida ou à espera
        da revisita); a que está em execução ou em falha não é tocada."""
        n = 0
        for i in range(0, len(particoes), 100):
            n += len((self._c.table("precos_pncp_tarefas")
                      .update({"estado": "pendente", "proxima_em": _agora().isoformat()})
                      .eq("campanha", campanha).eq("fonte", fonte)
                      .in_("particao", particoes[i:i + 100])
                      .in_("estado", ["concluida", "pendente"]).execute()).data or [])
        return n

    def recentes(self, minutos: int) -> list[dict]:
        desde = (_agora() - timedelta(minutes=minutos)).isoformat()
        saida, inicio = [], 0
        while True:
            lote = (self._c.table("precos_pncp_tarefas")
                    .select("fonte,faixa,estado,particao,totais,erro,atualizado_em")
                    .gte("atualizado_em", desde).order("id")
                    .range(inicio, inicio + 999).execute().data or [])
            saida.extend(lote)
            if len(lote) < 1000:
                return saida
            inicio += 1000

    def reabrir(self, campanha, estados, fonte):
        consulta = (self._c.table("precos_pncp_tarefas")
                    .update({"estado": "pendente", "proxima_em": _agora().isoformat(),
                             "erro": "", "tentativas": 0})
                    .in_("estado", list(estados)))
        if campanha:
            consulta = consulta.eq("campanha", campanha)
        if fonte:
            consulta = consulta.eq("fonte", fonte)
        return len(consulta.execute().data or [])


# ---------------------------------------------------------------------------
# Plano e execução
# ---------------------------------------------------------------------------
# Orçamento por faixa. A reserva (0045) segue `prioridade`; em vez de pôr uma
# faixa inteira atrás da outra — o histórico esperaria meses e a publicação
# fresca ficava no fim (14/11/2026) —, a prioridade é a POSIÇÃO da partição
# na própria faixa vezes o passo da faixa. Ordenadas juntas, as faixas se
# intercalam: a cada 4 partições recentes, 2 de atualização e 1 histórica.
# Nenhuma faixa fica indefinidamente no fim; `urgente` (dia novo, correção
# publicada) passa na frente e é pequena por construção.
# ---------------------------------------------------------------------------
PASSO_DA_FAIXA = {"urgente": 0, "recente": 1, "atualizacao": 2, "historico": 4}
PRIORIDADE_URGENTE = -1
# Publicação com menos de 30 dias quase nunca tem resultado ainda (a
# homologação vem semanas depois) — medido em produção (14/11/2026): 1.357
# contratações de ontem na frente, 0 gravadas. É a faixa `atualizacao`:
# lida com orçamento próprio e relida até o resultado sair.
DIAS_SEM_RESULTADO = 30


def faixa_e_prioridade(idade: int, *, fonte: str) -> tuple[str, int]:
    if idade >= DIAS_RECENTES:
        return "historico", PASSO_DA_FAIXA["historico"] * (idade - DIAS_RECENTES)
    if fonte == "pncp_descoberta" and idade < DIAS_SEM_RESULTADO:
        return "atualizacao", PASSO_DA_FAIXA["atualizacao"] * idade
    return "recente", PASSO_DA_FAIXA["recente"] * idade


def prioridade_pncp(idade: int) -> int:
    return faixa_e_prioridade(idade, fonte="pncp_descoberta")[1]


def plano_comprasgov(campanha: str, *, ate: date, desde: date) -> list[dict]:
    """Um dia por tarefa, do mais recente ao mais antigo. Os últimos 365 dias
    são a faixa `recente` (a janela da cotação); o resto, `historico`,
    intercalado (ver `PASSO_DA_FAIXA`)."""
    tarefas = []
    dia = ate
    while dia >= desde:
        faixa, prioridade = faixa_e_prioridade((ate - dia).days, fonte="comprasgov_lote")
        tarefas.append({"campanha": campanha, "fonte": "comprasgov_lote",
                        "particao": dia.isoformat(), "faixa": faixa,
                        "prioridade": prioridade})
        dia -= timedelta(days=1)
    return tarefas


def plano_pncp(campanha: str, *, ate: date, desde: date,
               modalidades: Iterable[int] = MODALIDADES) -> list[dict]:
    """Uma modalidade por dia por tarefa, com a faixa pela idade."""
    tarefas = []
    dia = ate
    while dia >= desde:
        faixa, prioridade = faixa_e_prioridade((ate - dia).days, fonte="pncp_descoberta")
        for m in modalidades:
            tarefas.append({"campanha": campanha, "fonte": "pncp_descoberta",
                            "particao": f"{m}:{dia.isoformat()}", "faixa": faixa,
                            "prioridade": prioridade})
        dia -= timedelta(days=1)
    return tarefas


def plano_do_dia(campanha: str, *, hoje: date,
                 modalidades: Iterable[int] = MODALIDADES) -> list[dict]:
    """
    O que o serviço cria sozinho todo dia (idempotente): os dias que ainda
    não existiam na fila (a campanha foi planejada até uma data; o tempo
    segue), a publicação de ontem e as ATUALIZAÇÕES de ontem — correções e
    resultados tardios de contratações antigas. Faixa `urgente`.
    """
    tarefas = []
    for atraso in (1, 2):          # a base em lote atrasa 1–2 dias
        dia = hoje - timedelta(days=atraso)
        tarefas.append({"campanha": campanha, "fonte": "comprasgov_lote",
                        "particao": dia.isoformat(), "faixa": "urgente",
                        "prioridade": PRIORIDADE_URGENTE})
    ontem = (hoje - timedelta(days=1)).isoformat()
    for m in modalidades:
        for particao in (f"{m}:{ontem}", f"u:{m}:{ontem}"):
            tarefas.append({"campanha": campanha, "fonte": "pncp_descoberta",
                            "particao": particao, "faixa": "urgente",
                            "prioridade": PRIORIDADE_URGENTE})
    return tarefas


def _espera(tentativas: int) -> timedelta:
    return timedelta(minutes=min(360, 2 ** max(0, tentativas - 1) * 5))


def _dia_da_tarefa(tarefa: dict) -> date | None:
    if tarefa["fonte"] == "comprasgov_lote":
        return date.fromisoformat(tarefa["particao"])
    if tarefa["fonte"] == "pncp_descoberta":
        return _particao_descoberta(tarefa["particao"])[2]
    publicada = ((tarefa.get("checkpoint") or {}).get("cabecalho") or {}).get(
        "dataPublicacaoPncp") or ""
    return date.fromisoformat(publicada[:10]) if publicada[:10] else None


def _log(evento: dict) -> None:
    """Uma linha JSON por tarefa no stdout do contêiner (`docker logs`)."""
    print(json.dumps(evento, ensure_ascii=False, default=str), flush=True)


_RETOMADA = ("compra_feita_ate", "item_feito_ate")


def executar(tarefa: dict, *, lote: ComprasGovLote | None, armazem, fila: Fila,
             pncp: PncpItemAItem | None = None, lease_s: int = LEASE_S) -> str:
    """Executa UMA tarefa e confirma com o token. Devolve o estado gravado."""
    inicio = time.monotonic()
    checkpoint = dict(tarefa.get("checkpoint") or {})
    renovar = lambda: fila.renovar(tarefa, lease_s)  # noqa: E731
    if tarefa["fonte"] == "comprasgov_lote" and lote is not None:
        def trabalho():
            return importar_dia(lote, armazem, date.fromisoformat(tarefa["particao"]),
                                renovar=renovar,
                                retomar_depois_de=str(checkpoint.get("compra_feita_ate") or "")
                                ).registro()
    elif pncp is not None and tarefa["fonte"] == "pncp_descoberta":
        def trabalho():
            return executar_descoberta(tarefa, pncp=pncp, fila=fila, lease_s=lease_s)
    elif pncp is not None and tarefa["fonte"] == "pncp_contratacao":
        def trabalho():
            return executar_contratacao(tarefa, pncp=pncp, armazem=armazem, renovar=renovar)
    else:
        fila.concluir(tarefa, "pendente", erro="fonte sem executor neste serviço",
                      proxima_em=_agora() + timedelta(hours=6))
        return "pendente"

    def falhou(estado: str, erro: Exception, espera: timedelta) -> str:
        progresso = getattr(erro, "progresso", None)
        novo_ck = {**checkpoint, **progresso} if progresso else None
        totais = getattr(erro, "totais", None)
        fila.concluir(tarefa, estado, erro=str(erro), checkpoint=novo_ck, totais=totais,
                      proxima_em=_agora() + espera)
        _log({"evento": "tarefa", "fonte": tarefa["fonte"], "particao": tarefa["particao"],
              "estado": estado, "erro": str(erro)[:300], "progresso": progresso,
              "s": round(time.monotonic() - inicio, 1), "totais": totais})
        return estado

    try:
        totais = trabalho()
    except RespostaParcial as erro:
        estado = "falha" if tarefa["tentativas"] >= TENTATIVAS_MAX else "parcial"
        return falhou(estado, erro, _espera(tarefa["tentativas"]))
    except FalhaTransitoria as erro:
        # avançou (gravou mais que a tentativa anterior): não "gasta" a
        # fila e volta logo; sem avanço, espera crescente até `falha`
        progresso = getattr(erro, "progresso", None) or {}
        avancou = any(progresso.get(k) != checkpoint.get(k) for k in progresso)
        estado = "falha" if tarefa["tentativas"] >= TENTATIVAS_MAX and not avancou             else "pendente"
        espera = max(_espera(tarefa["tentativas"]), timedelta(seconds=erro.espera_s))
        if avancou:
            espera = timedelta(seconds=max(60.0, erro.espera_s))
        return falhou(estado, erro, espera)
    # Lida. `concluida` é final; o que precisa ser relido volta `pendente`
    # com data futura e a leitura registrada em `checkpoint.lido_em` (a 0045
    # nunca reentrega `concluida`). Contratação só é relida enquanto tiver
    # item sem homologação. O checkpoint guarda o que havia (o cabeçalho),
    # sem o marcador de retomada — a próxima leitura é completa.
    dia = _dia_da_tarefa(tarefa)
    revisita = _revisita(dia)
    erro = ""
    estado_falta = None
    if tarefa["fonte"] == "comprasgov_lote":
        if not totais.get("resultados") and dia and (date.today() - dia).days < 7:
            # a base em lote atrasa 1 a 2 dias (medido em 14/11/2026: o dia 12
            # vazio, o 11 com 8.799): dia recente lido vazio volta amanhã
            revisita = timedelta(days=1)
        if totais.get("faltantes"):
            # o lido está gravado; a falta fica registrada e o dia volta
            erro = f"faltaram {totais['faltantes']} de {totais.get('declarados')} resultados"
            estado_falta = "falha" if tarefa["tentativas"] >= TENTATIVAS_MAX else "parcial"
    if tarefa["fonte"] == "pncp_contratacao" and \
            totais.get("homologados", 0) >= totais.get("itens", 0):
        revisita = None
    estado = estado_falta or ("concluida" if revisita is None else "pendente")
    proxima = _agora() + _espera(tarefa["tentativas"]) if estado_falta else (
        _agora() + revisita if revisita else None)
    novo_ck = {k: v for k, v in checkpoint.items() if k not in _RETOMADA}
    novo_ck.update(lido_em=_agora().isoformat(), versao=VERSAO,
                   leituras=int(checkpoint.get("leituras") or 0) + 1)
    confirmado = fila.concluir(tarefa, estado, totais=totais, checkpoint=novo_ck, erro=erro,
                               proxima_em=proxima)
    _log({"evento": "tarefa", "fonte": tarefa["fonte"], "particao": tarefa["particao"],
          "estado": estado if confirmado else "confirmacao_recusada", "erro": erro,
          "s": round(time.monotonic() - inicio, 1), "totais": totais})
    if not confirmado:
        # token perdido (lease vencido e reentregue): o trabalho já está
        # gravado (upsert idempotente); só a confirmação foi recusada
        CONFIRMACOES_RECUSADAS[0] += 1
        return "confirmacao_recusada"
    return estado


PISTAS = (("comprasgov_lote",), ("pncp_contratacao", "pncp_descoberta"))


@dataclass
class Servico:
    """
    Uma PISTA de trabalho: as fontes que ela reserva (`fontes_da_pista`). O
    processo roda uma pista por host em threads separadas (`rodar_pistas`):
    o 429 do PNCP dorme a pista do PNCP e não para o Compras.gov. Um
    escritor só: todas as pistas usam o MESMO `dono`, e só o líder vigente
    (`precos_pncp_liderar`) reserva.
    """

    fila: Fila
    lote: ComprasGovLote | None
    armazem: object
    pncp: PncpItemAItem | None = None
    dono: str = field(default_factory=lambda: f"{socket.gethostname()}:{os.getpid()}")
    ocioso_s: float = 60.0
    dormir: Callable[[float], None] = time.sleep
    fontes_da_pista: tuple | None = None
    campanha: str | None = None      # com campanha, esta pista cria o plano do dia
    req_por_s: float | None = None   # orçamento próprio; None = o do controle
    _planejado_em: date | None = None

    @property
    def fontes(self) -> list[str]:
        if self.fontes_da_pista:
            return list(self.fontes_da_pista)
        return list(FONTES) if self.pncp is not None else ["comprasgov_lote"]

    def _hosts(self) -> list[str]:
        hosts = []
        if self.lote is not None:
            hosts.append(urllib.parse.urlsplit(DADOS_ABERTOS).netloc)
        if self.pncp is not None:
            hosts.append(urllib.parse.urlsplit(PNCP_API).netloc)
        return hosts

    def _http(self) -> list[ClienteHttp]:
        return [x.http for x in (self.lote, self.pncp) if x is not None]

    def planejar(self, hoje: date | None = None) -> int:
        hoje = hoje or date.today()
        if not self.campanha or self._planejado_em == hoje:
            return 0
        novas = self.fila.criar(plano_do_dia(self.campanha, hoje=hoje))
        self._planejado_em = hoje
        _log({"evento": "plano_do_dia", "campanha": self.campanha, "dia": hoje,
              "novas": novas})
        return novas

    def passo(self) -> int:
        """Um ciclo: liderar, reservar, executar. Devolve tarefas executadas."""
        if not self.fila.liderar(self.dono, LEASE_S):
            return 0
        controle = self.fila.controle()
        if controle.get("pausado"):
            return 0
        self.planejar()
        # ritmo por host: a pista com orçamento próprio (`req_por_s`) usa o
        # dela; as demais, o do controle (ajustável sem reiniciar)
        ritmo = self.req_por_s or controle.get("req_por_s")
        if ritmo:
            for host in self._hosts():
                for http in self._http():
                    http.limitador.definir_ritmo(host, float(ritmo))
        feitas = 0
        for tarefa in self.fila.reservar(self.dono, self.fontes, 1, LEASE_S):
            try:
                executar(tarefa, lote=self.lote, armazem=self.armazem, fila=self.fila,
                         pncp=self.pncp)
            except Exception as erro:  # noqa: BLE001 — a pista não morre calada
                mensagem = f"inesperado: {type(erro).__name__}: {str(erro)[:300]}"
                self.fila.concluir(tarefa, "pendente", erro=mensagem,
                                   proxima_em=_agora() + _espera(tarefa["tentativas"]))
                _log({"evento": "tarefa", "fonte": tarefa["fonte"],
                      "particao": tarefa["particao"], "estado": "pendente",
                      "erro": mensagem})
            feitas += 1
        return feitas

    def rodar(self, *, uma_vez: bool = False) -> None:
        while True:
            try:
                feitas = self.passo()
            except Exception as erro:  # noqa: BLE001 — banco fora do ar, etc.
                _log({"evento": "pista", "fontes": self.fontes,
                      "erro": f"{type(erro).__name__}: {str(erro)[:300]}"})
                feitas = 0
            if uma_vez:
                return
            if not feitas:
                self.dormir(self.ocioso_s)


def rodar_pistas(servicos: list[Servico]) -> None:
    threads = [threading.Thread(target=s.rodar, name="+".join(s.fontes), daemon=True)
               for s in servicos]
    for t in threads:
        t.start()
    _log({"evento": "inicio", "versao": VERSAO, "pistas": [s.fontes for s in servicos],
          "dono": servicos[0].dono if servicos else None})
    for t in threads:
        t.join()


def total_declarado(tarefa: dict, *, lote: ComprasGovLote, pncp: PncpItemAItem) -> int:
    """O total que a fonte declara HOJE para a partição (uma chamada)."""
    if tarefa["fonte"] == "comprasgov_lote":
        dia = tarefa["particao"]
        dados = lote.http.json(_url("3_consultarResultadoItensContratacoes_PNCP_14133",
                                    pagina=1, tamanhoPagina=10,
                                    dataResultadoPncpInicial=dia, dataResultadoPncpFinal=dia))
        return _pagina_valida(dados)[1]
    rota, modalidade, dia = _particao_descoberta(tarefa["particao"])
    return int(pncp.pagina_de_publicacao(modalidade, dia, 1, rota=rota)
               .get("totalRegistros") or 0)


def reconciliar(tarefas: list[dict], *, lote: ComprasGovLote, pncp: PncpItemAItem,
                reabrir: Callable[[dict], None]) -> dict:
    """
    Janela fechada: a partição lida tem de bater com o total que a fonte
    declara agora. Divergência volta para a fila (nunca é forçada a
    fechar); falha da fonte não muda nada e fica contada.
    """
    saida = {"conferidas": 0, "batem": 0, "divergentes": [], "sem_resposta": 0}
    chave = {"comprasgov_lote": "resultados", "pncp_descoberta": "contratacoes"}
    for t in tarefas:
        if t["fonte"] not in chave or not (t.get("checkpoint") or {}).get("lido_em")                 or t["particao"].startswith("u:"):   # atualização não tem total fixo
            continue
        saida["conferidas"] += 1
        try:
            declarado = total_declarado(t, lote=lote, pncp=pncp)
        except (FalhaTransitoria, RespostaParcial):
            saida["sem_resposta"] += 1
            continue
        lido = int((t.get("totais") or {}).get(chave[t["fonte"]]) or 0)
        if declarado == lido:
            saida["batem"] += 1
        else:
            saida["divergentes"].append({"particao": t["particao"], "fonte": t["fonte"],
                                         "lido": lido, "declarado": declarado})
            reabrir(t)
    return saida


_SOMADOS = ("resultados", "recebidos", "gravadas", "inseridas", "atualizadas",
            "inalteradas", "invalidadas", "faltantes", "falhas_gravacao", "chamadas",
            "contratacoes", "itens", "enfileiradas", "reagendadas")


def relatorio(linhas: list[dict]) -> dict:
    """Por fonte/faixa: estados e a soma do que as tarefas registraram —
    recusas por motivo e tempos por fase incluídos."""
    por: dict = {}
    for t in linhas:
        chave = f"{t['fonte']}/{t['faixa']}"
        bloco = por.setdefault(chave, {"total": 0, "estados": {}, "recusadas": {},
                                       "tempos": {}, **{k: 0 for k in _SOMADOS}})
        bloco["total"] += 1
        bloco["estados"][t["estado"]] = bloco["estados"].get(t["estado"], 0) + 1
        if (t.get("checkpoint") or {}).get("lido_em"):
            bloco["lidas"] = bloco.get("lidas", 0) + 1
        totais = t.get("totais") or {}
        for k in _SOMADOS:
            bloco[k] += int(totais.get(k) or 0)
        for motivo, n in (totais.get("recusadas") or {}).items():
            bloco["recusadas"][motivo] = bloco["recusadas"].get(motivo, 0) + int(n)
        for fase, v in (totais.get("tempos") or {}).items():
            bloco["tempos"][fase] = round(bloco["tempos"].get(fase, 0.0) + float(v), 1)
    return por


def ritmo(linhas: list[dict], minutos: int) -> dict:
    """
    O que as tarefas confirmadas na janela fizeram, por fonte, e por minuto.
    `inseridas` é linha NOVA no índice; atualização e repetição vêm à parte.
    Erros da janela ficam listados (gravação recusada não some).
    """
    saida: dict = {"janela_min": minutos, "fontes": {}}
    for t in linhas:
        bloco = saida["fontes"].setdefault(t["fonte"], {
            "tarefas": 0, "estados": {}, "recusadas": {}, "tempos": {}, "erros": {},
            **{k: 0 for k in _SOMADOS}})
        bloco["tarefas"] += 1
        bloco["estados"][t["estado"]] = bloco["estados"].get(t["estado"], 0) + 1
        totais = t.get("totais") or {}
        for k in _SOMADOS:
            bloco[k] += int(totais.get(k) or 0)
        for motivo, n in (totais.get("recusadas") or {}).items():
            bloco["recusadas"][motivo] = bloco["recusadas"].get(motivo, 0) + int(n)
        for fase, v in (totais.get("tempos") or {}).items():
            bloco["tempos"][fase] = round(bloco["tempos"].get(fase, 0.0) + float(v), 1)
        if t.get("erro"):
            chave = str(t["erro"])[:60]
            bloco["erros"][chave] = bloco["erros"].get(chave, 0) + 1
    for bloco in saida["fontes"].values():
        bloco["inseridas_por_min"] = round(bloco["inseridas"] / max(1, minutos), 2)
        bloco["atualizadas_por_min"] = round(bloco["atualizadas"] / max(1, minutos), 2)
        fases = {k: v for k, v in bloco["tempos"].items()}
        bloco["gargalo"] = max(fases, key=fases.get) if fases else None
    return saida


# ---------------------------------------------------------------------------
# CLI — roda no contêiner do worker (`python -m src.precos.pncp_integral ...`)
# ---------------------------------------------------------------------------
def _fila_do_banco():
    from .pncp_indice_servico import armazem_do_banco

    armazem = armazem_do_banco()
    return FilaSupabase(armazem._c), armazem  # noqa: SLF001 — mesmo cliente de servidor


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pncp_integral", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="acao", required=True)
    s = sub.add_parser("plan", help="cria as partições (idempotente)")
    s.add_argument("--campanha", required=True)
    s.add_argument("--desde", default="2023-01-01")
    s.add_argument("--ate", default=None, help="padrão: ontem")
    s.add_argument("--simular", action="store_true", help="só conta, não grava")
    s.add_argument("--fontes", nargs="+", default=["comprasgov_lote"],
                   choices=["comprasgov_lote", "pncp_descoberta"])
    s = sub.add_parser("run", help="serviço contínuo (líder único, lease, heartbeat)")
    s.add_argument("--uma-vez", action="store_true")
    s.add_argument("--req-por-s", type=float, default=1.0)
    s.add_argument("--campanha", default=None,
                   help="cria sozinho o plano de cada dia novo nesta campanha")
    s.add_argument("--req-por-s-lote", type=float, default=2.0,
                   help="orçamento do Compras.gov (medido sem 429 a 2 req/s, 14/11/2026); "
                        "o PNCP segue o `req_por_s` do controle")
    s = sub.add_parser("ritmo", help="o que a janela fez, por fonte e por minuto")
    s.add_argument("--minutos", type=int, default=30)
    s = sub.add_parser("status", help="relatório por fonte/faixa/estado em JSON")
    s.add_argument("--campanha", default=None)
    s = sub.add_parser("pause")
    s.add_argument("--motivo", required=True)
    sub.add_parser("resume")
    s = sub.add_parser("reconcile", help="confere totais lidos x declarados, janela fechada")
    s.add_argument("--campanha", required=True)
    s.add_argument("--desde", required=True)
    s.add_argument("--ate", required=True)
    s.add_argument("--req-por-s", type=float, default=1.0)
    s = sub.add_parser("retry-failed", help="reabre falha/quarentena/parcial (sem reset global)")
    s.add_argument("--campanha", default=None)
    s.add_argument("--fonte", default=None)
    s.add_argument("--estados", nargs="+", default=["falha"],
                   choices=["falha", "quarentena", "parcial"])
    s.add_argument("--todas", action="store_true",
                   help="obrigatório sem --campanha e sem --fonte")
    a = p.parse_args(argv)

    if a.acao == "plan":
        ate = date.fromisoformat(a.ate) if a.ate else date.today() - timedelta(days=1)
        desde = date.fromisoformat(a.desde)
        tarefas = []
        if "comprasgov_lote" in a.fontes:
            tarefas += plano_comprasgov(a.campanha, ate=ate, desde=desde)
        if "pncp_descoberta" in a.fontes:
            tarefas += plano_pncp(a.campanha, ate=ate, desde=desde)
        resumo = {"tarefas": len(tarefas),
                  "recentes": sum(t["faixa"] == "recente" for t in tarefas),
                  "atualizacao": sum(t["faixa"] == "atualizacao" for t in tarefas),
                  "historicas": sum(t["faixa"] == "historico" for t in tarefas)}
        if not a.simular:
            fila, _ = _fila_do_banco()
            resumo["novas"] = fila.criar(tarefas)
        print(json.dumps(resumo, ensure_ascii=False))
        return 0
    if a.acao == "retry-failed" and not (a.campanha or a.fonte or a.todas):
        print("recusado: sem --campanha nem --fonte reabre a fila inteira; use --todas")
        return 2
    fila, armazem = _fila_do_banco()
    if a.acao == "run":
        limitador = Limitador(a.req_por_s)
        dono = f"{socket.gethostname()}:{os.getpid()}"
        servicos = []
        for n, fontes in enumerate(PISTAS):
            # um cliente de banco por pista (threads não dividem conexão)
            fila_p, armazem_p = (fila, armazem) if n == 0 else _fila_do_banco()
            http = ClienteHttp(limitador)
            servicos.append(Servico(
                fila=fila_p, armazem=armazem_p, dono=dono, fontes_da_pista=fontes,
                lote=ComprasGovLote(http) if "comprasgov_lote" in fontes else None,
                pncp=PncpItemAItem(http) if "comprasgov_lote" not in fontes else None,
                campanha=a.campanha if n == 0 else None,
                req_por_s=a.req_por_s_lote if "comprasgov_lote" in fontes else None))
        if a.uma_vez:
            for servico in servicos:
                servico.rodar(uma_vez=True)
            return 0
        rodar_pistas(servicos)
        return 0
    if a.acao == "ritmo":
        print(json.dumps(ritmo(fila.recentes(a.minutos), a.minutos), ensure_ascii=False,
                         indent=2))
        return 0
    if a.acao == "status":
        print(json.dumps({"controle": fila.controle(),
                          "partições": relatorio(fila.resumo(a.campanha))},
                         ensure_ascii=False, default=str, indent=2))
        return 0
    if a.acao == "pause":
        fila.ajustar_controle(pausado=True, motivo_pausa=a.motivo)
        return 0
    if a.acao == "resume":
        fila.ajustar_controle(pausado=False, motivo_pausa="")
        return 0
    if a.acao == "retry-failed":
        print(json.dumps({"reabertas": fila.reabrir(a.campanha, a.estados, a.fonte)}))
        return 0
    if a.acao == "reconcile":
        http = ClienteHttp(Limitador(a.req_por_s))
        alvo = [t for t in fila.resumo_completo(a.campanha)
                if a.desde <= t["particao"].split(":")[-1] <= a.ate]
        resultado = reconciliar(alvo, lote=ComprasGovLote(http), pncp=PncpItemAItem(http),
                                reabrir=fila.reabrir_uma)
        print(json.dumps(resultado, ensure_ascii=False))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
