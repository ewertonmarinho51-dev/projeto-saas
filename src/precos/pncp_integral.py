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

VERSAO = "2026-11-13.pncp-integral.1"
FONTES = ("comprasgov_lote", "pncp_descoberta", "pncp_contratacao")
ESTADOS_FINAIS = ("pendente", "concluida", "parcial", "falha", "quarentena")
DADOS_ABERTOS = "https://dadosabertos.compras.gov.br/modulo-contratacoes"
PAGINA_LOTE = 500
LEASE_S = 600
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
    intervalo dobra a cada 429/5xx e volta devagar com sucesso.
    """

    def __init__(self, req_por_s: float = 1.0, relogio=time.monotonic,
                 dormir=time.sleep) -> None:
        self.base = 1.0 / max(0.05, req_por_s)
        self.intervalo = self.base
        self._proxima: dict[str, float] = {}
        self._trava = threading.Lock()
        self._relogio, self._dormir = relogio, dormir

    def aguardar(self, host: str) -> None:
        with self._trava:
            agora = self._relogio()
            vez = max(agora, self._proxima.get(host, 0.0))
            self._proxima[host] = vez + self.intervalo
        if vez > agora:
            self._dormir(vez - agora)

    def respeitar(self, host: str, espera_s: float) -> None:
        with self._trava:
            self._proxima[host] = max(self._proxima.get(host, 0.0),
                                      self._relogio() + espera_s)
            self.intervalo = min(self.intervalo * 2, 60.0)

    def sucesso(self) -> None:
        with self._trava:
            self.intervalo = max(self.base, self.intervalo * 0.9)


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


class ClienteHttp:
    def __init__(self, limitador: Limitador, abrir: Callable = _abrir) -> None:
        self.limitador, self._abrir = limitador, abrir
        self.chamadas = 0
        self.falhas: dict[str, int] = {}

    def json(self, url: str):
        host = urllib.parse.urlsplit(url).netloc
        self.limitador.aguardar(host)
        self.chamadas += 1
        status, cabecalhos, corpo = self._abrir(url)
        if status == 429 or status >= 500:
            espera = _retry_after(cabecalhos) or (30.0 if status == 429 else 10.0)
            self.limitador.respeitar(host, espera)
            self.falhas[str(status)] = self.falhas.get(str(status), 0) + 1
            raise FalhaTransitoria(f"http {status}", espera)
        if status == 204:
            return None
        if status != 200:
            self.falhas[str(status)] = self.falhas.get(str(status), 0) + 1
            raise FalhaTransitoria(f"http {status}")
        try:
            dados = json.loads(corpo.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self.falhas["json"] = self.falhas.get("json", 0) + 1
            raise FalhaTransitoria("json inválido") from None
        self.limitador.sucesso()
        return dados


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


class ComprasGovLote:
    def __init__(self, http: ClienteHttp) -> None:
        self.http = http
        self._contratacoes: dict[str, dict] = {}
        self._itens: dict[str, dict[int, dict]] = {}

    def resultados_do_dia(self, dia: date) -> list[dict]:
        """Todas as páginas do dia; menos que o total declarado = parcial."""
        linhas: list[dict] = []
        pagina, total = 1, None
        while True:
            dados = self.http.json(_url(
                "3_consultarResultadoItensContratacoes_PNCP_14133", pagina=pagina,
                tamanhoPagina=PAGINA_LOTE, dataResultadoPncpInicial=dia.isoformat(),
                dataResultadoPncpFinal=dia.isoformat()))
            resultado, declarado = _pagina_valida(dados)
            total = declarado if total is None else total
            linhas.extend(resultado)
            if not resultado or int(dados.get("paginasRestantes") or 0) <= 0:
                break
            pagina += 1
        unicas = {(r.get("idContratacaoPNCP"), r.get("numeroItemPncp"),
                   r.get("sequencialResultado")): r for r in linhas}
        if len(unicas) < (total or 0):
            raise RespostaParcial(f"{len(unicas)} de {total} resultados em {dia}")
        return list(unicas.values())

    def contratacao(self, id_compra: str) -> dict:
        if id_compra not in self._contratacoes:
            dados = self.http.json(_url("1.1_consultarContratacoes_PNCP_14133_Id",
                                        tipo="idCompra", codigo=id_compra))
            bruto = dados.get("resultado") if isinstance(dados, dict) else None
            resultado = bruto if isinstance(bruto, list) else [bruto]
            if not resultado or not isinstance(resultado[0], dict):
                raise FalhaTransitoria(f"contratação {id_compra} ausente")
            self._contratacoes[id_compra] = resultado[0]
        return self._contratacoes[id_compra]

    def itens(self, id_compra: str) -> dict[int, dict]:
        if id_compra not in self._itens:
            dados = self.http.json(_url("2.1_consultarItensContratacoes_PNCP_14133_Id",
                                        tipo="idCompra", codigo=id_compra))
            resultado, total = _pagina_valida(dados)
            if len(resultado) < total:
                raise RespostaParcial(f"{len(resultado)} de {total} itens de {id_compra}")
            self._itens[id_compra] = {int(i.get("numeroItemPncp") or 0): i for i in resultado}
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
    resultados: int = 0
    gravadas: int = 0
    recusadas: dict = field(default_factory=dict)
    contratacoes: int = 0
    chamadas: int = 0

    def registro(self) -> dict:
        return {"resultados": self.resultados, "gravadas": self.gravadas,
                "recusadas": self.recusadas, "contratacoes": self.contratacoes,
                "chamadas": self.chamadas}


def importar_dia(lote: ComprasGovLote, armazem, dia: date, *,
                 lote_gravacao: int = 500, renovar: Callable[[], None] | None = None
                 ) -> Totais:
    """Um dia inteiro do Compras.gov no índice. Falha transitória propaga."""
    totais = Totais()
    chamadas_antes = lote.http.chamadas
    resultados = lote.resultados_do_dia(dia)
    totais.resultados = len(resultados)
    por_compra: dict[str, list[dict]] = {}
    for r in resultados:
        id_compra = str(r.get("idCompraItem") or "")[:17] or str(r.get("idCompra") or "")
        por_compra.setdefault(id_compra, []).append(r)
    totais.contratacoes = len(por_compra)
    pendentes: list[dict] = []
    for i, (id_compra, linhas) in enumerate(por_compra.items()):
        contratacao = lote.contratacao(id_compra)
        itens = lote.itens(id_compra)
        for r in linhas:
            item = itens.get(int(r.get("numeroItemPncp") or 0))
            if item is None:
                totais.recusadas["item_ausente"] = totais.recusadas.get("item_ausente", 0) + 1
                continue
            linha, motivo = pncp_indice.linha_do_resultado(*no_formato_do_pncp(
                contratacao, item, r))
            if linha is None:
                totais.recusadas[motivo] = totais.recusadas.get(motivo, 0) + 1
                continue
            linha["versao_coletor"] = VERSAO
            pendentes.append(linha)
        if len(pendentes) >= lote_gravacao:
            armazem.gravar_resultados(pendentes)
            totais.gravadas += len(pendentes)
            pendentes = []
        if renovar and i % 50 == 49:
            renovar()
    if pendentes:
        armazem.gravar_resultados(pendentes)
        totais.gravadas += len(pendentes)
    totais.chamadas = lote.http.chamadas - chamadas_antes
    return totais


# ---------------------------------------------------------------------------
# Fila
# ---------------------------------------------------------------------------
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
            for t in livres[:max(1, limite)]:
                t.update(estado="em_execucao", dono=dono, token=str(uuid.uuid4()),
                         lease_ate=agora + timedelta(seconds=lease_s),
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

    def reabrir(self, campanha, estados, fonte):
        n = 0
        for t in self.tarefas:
            if (campanha in (None, t["campanha"]) and t["estado"] in estados
                    and fonte in (None, t["fonte"])):
                t.update(estado="pendente", proxima_em=_agora(), erro="")
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

    def reabrir(self, campanha, estados, fonte):
        consulta = (self._c.table("precos_pncp_tarefas")
                    .update({"estado": "pendente", "proxima_em": _agora().isoformat(),
                             "erro": ""})
                    .in_("estado", list(estados)))
        if campanha:
            consulta = consulta.eq("campanha", campanha)
        if fonte:
            consulta = consulta.eq("fonte", fonte)
        return len(consulta.execute().data or [])


# ---------------------------------------------------------------------------
# Plano e execução
# ---------------------------------------------------------------------------
def plano_comprasgov(campanha: str, *, ate: date, desde: date) -> list[dict]:
    """
    Um dia por tarefa, do mais recente ao mais antigo. Os últimos 365 dias
    são a faixa `recente` (a janela da cotação); o resto, `historico`.
    """
    tarefas = []
    dia = ate
    while dia >= desde:
        idade = (ate - dia).days
        recente = idade < DIAS_RECENTES
        tarefas.append({"campanha": campanha, "fonte": "comprasgov_lote",
                        "particao": dia.isoformat(),
                        "faixa": "recente" if recente else "historico",
                        "prioridade": idade if recente else 10_000 + idade})
        dia -= timedelta(days=1)
    return tarefas


def _espera(tentativas: int) -> timedelta:
    return timedelta(minutes=min(360, 2 ** max(0, tentativas - 1) * 5))


def executar(tarefa: dict, *, lote: ComprasGovLote, armazem, fila: Fila,
             lease_s: int = LEASE_S) -> str:
    """Executa UMA tarefa e confirma com o token. Devolve o estado gravado."""
    if tarefa["fonte"] != "comprasgov_lote":
        fila.concluir(tarefa, "pendente", erro="fonte ainda sem executor neste serviço",
                      proxima_em=_agora() + timedelta(hours=6))
        return "pendente"
    dia = date.fromisoformat(tarefa["particao"])
    try:
        totais = importar_dia(lote, armazem, dia,
                              renovar=lambda: fila.renovar(tarefa, lease_s))
    except RespostaParcial as erro:
        estado = "falha" if tarefa["tentativas"] >= TENTATIVAS_MAX else "parcial"
        fila.concluir(tarefa, estado, erro=str(erro),
                      proxima_em=_agora() + _espera(tarefa["tentativas"]))
        return estado
    except FalhaTransitoria as erro:
        estado = "falha" if tarefa["tentativas"] >= TENTATIVAS_MAX else "pendente"
        espera = max(_espera(tarefa["tentativas"]), timedelta(seconds=erro.espera_s))
        fila.concluir(tarefa, estado, erro=str(erro), proxima_em=_agora() + espera)
        return estado
    # concluída; dia recente volta a ser relido (resultado novo, cancelamento)
    idade = (date.today() - dia).days
    revisita = timedelta(days=1 if idade < 30 else 7 if idade < DIAS_RECENTES else 90)
    fila.concluir(tarefa, "concluida", totais=totais.registro(),
                  checkpoint={"lido_em": _agora().isoformat(), "versao": VERSAO},
                  proxima_em=_agora() + revisita)
    return "concluida"


@dataclass
class Servico:
    fila: Fila
    lote: ComprasGovLote
    armazem: object
    dono: str = field(default_factory=lambda: f"{socket.gethostname()}:{os.getpid()}")
    ocioso_s: float = 60.0
    dormir: Callable[[float], None] = time.sleep

    def passo(self) -> int:
        """Um ciclo: liderar, reservar, executar. Devolve tarefas executadas."""
        if not self.fila.liderar(self.dono, LEASE_S):
            return 0
        controle = self.fila.controle()
        if controle.get("pausado"):
            return 0
        if controle.get("req_por_s"):
            novo = 1.0 / float(controle["req_por_s"])
            self.lote.http.limitador.base = novo
        feitas = 0
        for tarefa in self.fila.reservar(self.dono, ["comprasgov_lote"], 1, LEASE_S):
            executar(tarefa, lote=self.lote, armazem=self.armazem, fila=self.fila)
            feitas += 1
        return feitas

    def rodar(self, *, uma_vez: bool = False) -> None:
        while True:
            feitas = self.passo()
            if uma_vez:
                return
            if not feitas:
                self.dormir(self.ocioso_s)


def relatorio(linhas: list[dict]) -> dict:
    por: dict = {}
    for t in linhas:
        chave = f"{t['fonte']}/{t['faixa']}"
        bloco = por.setdefault(chave, {"total": 0, "estados": {}, "resultados": 0,
                                       "gravadas": 0, "chamadas": 0})
        bloco["total"] += 1
        bloco["estados"][t["estado"]] = bloco["estados"].get(t["estado"], 0) + 1
        totais = t.get("totais") or {}
        for k in ("resultados", "gravadas", "chamadas"):
            bloco[k] += int(totais.get(k) or 0)
    return por


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
    s = sub.add_parser("run", help="serviço contínuo (líder único, lease, heartbeat)")
    s.add_argument("--uma-vez", action="store_true")
    s.add_argument("--req-por-s", type=float, default=1.0)
    s = sub.add_parser("status", help="relatório por fonte/faixa/estado em JSON")
    s.add_argument("--campanha", default=None)
    s = sub.add_parser("pause")
    s.add_argument("--motivo", required=True)
    sub.add_parser("resume")
    s = sub.add_parser("retry-failed", help="reabre falha/quarentena/parcial (sem reset global)")
    s.add_argument("--campanha", default=None)
    s.add_argument("--fonte", default=None)
    s.add_argument("--estados", nargs="+", default=["falha"])
    a = p.parse_args(argv)

    if a.acao == "plan":
        ate = date.fromisoformat(a.ate) if a.ate else date.today() - timedelta(days=1)
        tarefas = plano_comprasgov(a.campanha, ate=ate, desde=date.fromisoformat(a.desde))
        resumo = {"tarefas": len(tarefas),
                  "recentes": sum(t["faixa"] == "recente" for t in tarefas),
                  "historicas": sum(t["faixa"] == "historico" for t in tarefas)}
        if not a.simular:
            fila, _ = _fila_do_banco()
            resumo["novas"] = fila.criar(tarefas)
        print(json.dumps(resumo, ensure_ascii=False))
        return 0
    fila, armazem = _fila_do_banco()
    if a.acao == "run":
        servico = Servico(fila=fila, armazem=armazem,
                          lote=ComprasGovLote(ClienteHttp(Limitador(a.req_por_s))))
        servico.rodar(uma_vez=a.uma_vez)
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
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
