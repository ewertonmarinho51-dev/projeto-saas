"""
Índice de resultados homologados do PNCP — piloto da busca por descrição.

O PNCP não tem busca de item por descrição (ver `pncp.py`). O que ele tem,
nos canais oficiais, é o caminho de cima para baixo:

    /api/consulta/v1/contratacoes/publicacao    (por UF, modalidade e data)
    /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens
    /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens/{n}/resultados

Este módulo percorre esse caminho FORA do clique do usuário, num job
limitado e retomável (`Coletor`), e guarda o unitário homologado de cada
item num índice. A busca do usuário (`PNCPIndice`) só lê o índice: nenhuma
chamada externa na hora da pesquisa.

O que entra no índice é o que `pncp._referencia_do_resultado` aceita — a
MESMA conferência da consulta por contratação: resultado não cancelado,
em real, com unitário × quantidade = total — mais item HOMOLOGADO, com
descrição e unidade. O que não passa fica contado por motivo, não gravado.

Compras.gov de fora, por padrão: a contratação publicada pelo próprio
Compras.gov já chega pela fonte de preços praticados; indexá-la gastaria o
orçamento de chamadas com preço que a pesquisa já tem. O piloto existe
para trazer o que vem de OUTRAS plataformas (Portal de Compras Públicas,
BNC, Compras Pará, sistemas municipais). A fusão de `busca` continua
valendo para o que escapar: a mesma compra conta uma vez.

Pessoa física: nome e documento de fornecedor PF não são gravados.

Nada aqui conhece Supabase: o armazém é injetado (`ArmazemEmMemoria` nas
provas e na medição de bancada; o de banco mora em `scripts/indexar_pncp.py`).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Protocol

from . import evidencia, pncp
from .fontes import Capacidade, Consulta, FontePesquisaPreco, ResultadoBusca

VERSAO_COLETOR = "2026-11-10.pncp-indice.1"

# `usuarioNome` da contratação: o sistema que a publicou no PNCP.
PLATAFORMA_COMPRAS_GOV = "Compras.gov.br"
# Pregão eletrônico (6) e pregão presencial (7) — onde há disputa de preço
# por item e resultado homologado publicado. A DISPENSA (8) saiu em
# 11/11/2026: na conferência da 1ª rodada do Pará, dispensas de Tratamento
# Fora do Domicílio traziam NOME DE PACIENTE na descrição do item. Volta só
# quando houver filtro de dado pessoal na coleta. Contratação de modalidade
# fora desta lista não tem item lido, nem quando já estava na fila.
MODALIDADES_PADRAO = (6, 7)
SITUACAO_ITEM_HOMOLOGADO = 2
PAGINA_DESCOBERTA = 50
PAGINA_ITENS = 500
TENTATIVAS_POR_CONTRATACAO = 3
# A descoberta vai por DATA DE PUBLICAÇÃO. Medido em 10/11/2026 com a mesma
# consulta do Pará: `/contratacoes/publicacao` respondeu em 1 s;
# `/contratacoes/atualizacao` levou 24 s e, na tentativa seguinte, HTTP 500
# aos 51 s. Como a homologação vem depois da publicação, cada janela nova
# RECUA `REVISITA_DIAS` sobre a anterior: a contratação já vista volta para
# a fila quando o `dataAtualizacaoGlobal` dela mudou. 120 dias desde
# 11/11/2026 (eram 45): a 1ª rodada, de 30 dias, achou boa parte dos pregões
# ainda sem homologação — o resultado sai semanas depois da publicação.
ROTA_DESCOBERTA = "/contratacoes/publicacao"
REVISITA_DIAS = 120

# Estados da contratação no índice
PENDENTE = "pendente"            # descoberta (ou atualizada): falta ler itens
COLETADA = "coletada"            # todos os itens homologados lidos
SEM_RESULTADO = "sem_resultado"  # ainda sem item homologado; volta se atualizar
FORA_DO_PILOTO = "fora_do_piloto"   # publicada pelo Compras.gov
FALHA = "falha"                  # esgotou as tentativas

ITEM_NAO_HOMOLOGADO = "ITEM_NAO_HOMOLOGADO"
# julgado por maior desconto: o "unitário" publicado é percentual, não preço
CRITERIO_MAIOR_DESCONTO = "CRITERIO_MAIOR_DESCONTO_NAO_E_PRECO"
# Na revisita, o resultado indexado antes não voltou como homologado
# conferível: cancelado, revogado ou corrigido depois da coleta.
MOTIVO_REVISITA = ("não confirmado na revisita da contratação (resultado "
                   "cancelado, revogado ou corrigido no PNCP depois da "
                   "coleta)")
RESULTADO_NAO_CONFERIVEL = "RESULTADO_CANCELADO_OU_TOTAL_INCOERENTE"


# ---------------------------------------------------------------------------
# Texto de busca — o mesmo dos dois lados (coletor e consulta)
# ---------------------------------------------------------------------------
def texto_de_busca(descricao: str) -> str:
    """Sem acento e em minúsculas: "AÇÚCAR" e "acucar" são a mesma busca."""
    from .compras_gov import _sem_acento

    return " ".join(_sem_acento(descricao or "").lower().split())


def termos_da_consulta(consulta: Consulta, maximo: int = 12) -> list[str]:
    """Palavras significativas da descrição e dos sinônimos, sem acento."""
    from .compras_gov import _tokens

    termos: list[str] = []
    for texto in (consulta.descricao, *consulta.termos_alternativos):
        for palavra in sorted(_tokens(texto), key=lambda p: (-len(p), p)):
            palavra = palavra.lower()
            if palavra.isalnum() and palavra not in termos:
                termos.append(palavra)
    return termos[:maximo]


# Grupos consultados por item: a descrição e até 4 variantes. Cada grupo é
# uma chamada à RPC (o índice é local, sem rede externa).
MAX_GRUPOS = 5


def grupos_da_consulta(consulta: Consulta, maximo: int = 12) -> list[list[str]]:
    """
    Uma lista de palavras POR VARIANTE — descrição primeiro, depois cada
    termo alternativo. A lista achatada (`termos_da_consulta`) juntava tudo
    e cortava em 12 palavras ordenadas por tamanho: uma descrição longa
    ocupava as 12 vagas e o sinônimo nunca chegava ao índice.
    """
    from .compras_gov import _tokens

    grupos: list[list[str]] = []
    for texto in (consulta.descricao, *consulta.termos_alternativos):
        palavras: list[str] = []
        for palavra in sorted(_tokens(texto), key=lambda p: (-len(p), p)):
            palavra = palavra.lower()
            if palavra.isalnum() and palavra not in palavras:
                palavras.append(palavra)
        palavras = palavras[:maximo]
        if palavras and palavras not in grupos:
            grupos.append(palavras)
    return grupos[:MAX_GRUPOS]


# ---------------------------------------------------------------------------
# Linhas do índice
# ---------------------------------------------------------------------------
_CAMPOS_DA_CONTRATACAO = (
    "numeroControlePNCP", "linkSistemaOrigem", "modalidadeId", "modalidadeNome",
    "usuarioNome", "anoCompra", "sequencialCompra", "numeroCompra", "processo",
    "srp", "dataAtualizacaoGlobal", "dataPublicacaoPncp", "situacaoCompraNome")
_CAMPOS_DO_ITEM = (
    "numeroItem", "descricao", "unidadeMedida", "quantidade",
    "materialOuServico", "catalogoCodigoItem", "criterioJulgamentoNome",
    "situacaoCompraItem", "situacaoCompraItemNome", "valorUnitarioEstimado")


def resumo_da_contratacao(contratacao: dict) -> dict:
    """Só o que a referência e a evidência usam — nada de texto livre longo."""
    resumo = {k: contratacao.get(k) for k in _CAMPOS_DA_CONTRATACAO}
    orgao = contratacao.get("orgaoEntidade") or {}
    unidade = contratacao.get("unidadeOrgao") or {}
    resumo["orgaoEntidade"] = {k: orgao.get(k) for k in
                               ("cnpj", "razaoSocial", "esferaId", "poderId")}
    resumo["unidadeOrgao"] = {k: unidade.get(k) for k in
                              ("ufSigla", "municipioNome", "codigoIbge",
                               "nomeUnidade")}
    return resumo


def _sem_pessoa_fisica(resultado: dict) -> dict:
    """Fornecedor PF: nome e documento não seguem adiante (`evidencia`)."""
    if str(resultado.get("tipoPessoa") or "").upper() == "PJ" and \
            evidencia.cnpj_ou_nada("J", resultado.get("niFornecedor")):
        return dict(resultado)
    return {**resultado, "niFornecedor": None,
            "nomeRazaoSocialFornecedor": None}


def linha_do_resultado(contratacao: dict, item: dict, resultado: dict
                       ) -> tuple[dict | None, str]:
    """
    (linha do índice, "") quando o resultado prova um preço homologado;
    (None, motivo) quando não prova. Os motivos são estáveis.
    """
    if item.get("situacaoCompraItem") != SITUACAO_ITEM_HOMOLOGADO:
        return None, ITEM_NAO_HOMOLOGADO
    if pncp.julgado_por_desconto(item):
        return None, CRITERIO_MAIOR_DESCONTO
    if not str(item.get("descricao") or "").strip():
        return None, evidencia.SEM_DESCRICAO
    if not str(item.get("unidadeMedida") or "").strip():
        return None, evidencia.SEM_UNIDADE
    resultado = _sem_pessoa_fisica(resultado)
    resumo = resumo_da_contratacao(contratacao)
    item_resumido = {k: item.get(k) for k in _CAMPOS_DO_ITEM}
    referencia = pncp._referencia_do_resultado(resumo, item_resumido, resultado)
    if referencia is None:
        return None, RESULTADO_NAO_CONFERIVEL
    bruto = {"contratacao": resumo, "item": item_resumido,
             "resultado": resultado}
    return {
        "id_externo": referencia.id_externo,
        "numero_controle": resumo["numeroControlePNCP"],
        "numero_item": int(item.get("numeroItem") or 0),
        "sequencial_resultado": int(resultado.get("sequencialResultado") or 1),
        "descricao": referencia.descricao_original,
        "descricao_busca": texto_de_busca(referencia.descricao_original),
        "unidade": referencia.unidade_original,
        "quantidade": format(referencia.quantidade_original, "f"),
        "valor_unitario": format(referencia.valor_unitario_original, "f"),
        "valor_total": str(resultado.get("valorTotalHomologado")),
        "data_resultado": referencia.data_resultado.isoformat()
        if referencia.data_resultado else None,
        "uf": referencia.uf, "municipio": referencia.municipio,
        "orgao": referencia.orgao,
        "orgao_cnpj": resumo["orgaoEntidade"].get("cnpj"),
        "plataforma": resumo.get("usuarioNome"),
        "id_compra_origem": referencia.bruto.get("idCompraOrigem"),
        "fornecedor_cnpj": referencia.ni_fornecedor,
        "codigo_catalogo": referencia.codigo_catalogo,
        "bruto": bruto,
        "hash_linha": evidencia.hash_da_linha(bruto),
        "versao_coletor": VERSAO_COLETOR,
    }, ""


def referencia_da_linha(linha: dict):
    """Linha do índice → `Referencia` HOMOLOGADA, pela conferência de sempre."""
    bruto = linha.get("bruto") or {}
    referencia = pncp._referencia_do_resultado(
        bruto.get("contratacao") or {}, bruto.get("item") or {},
        bruto.get("resultado") or {})
    if referencia is None:
        return None
    referencia.bruto["indice"] = {
        "versao_coletor": linha.get("versao_coletor"),
        "coletado_em": linha.get("coletado_em"),
        "plataforma": linha.get("plataforma"),
        "hash_linha": linha.get("hash_linha")}
    return referencia


# ---------------------------------------------------------------------------
# Armazém
# ---------------------------------------------------------------------------
class Armazem(Protocol):
    def cursor(self, uf: str, modalidade: int) -> dict | None: ...

    def salvar_cursor(self, uf: str, modalidade: int, **campos) -> None: ...

    def contratacao(self, numero_controle: str) -> dict | None: ...

    def salvar_contratacao(self, numero_controle: str, **campos) -> None: ...

    def pendentes(self, limite: int) -> list[dict]: ...

    def gravar_resultados(self, linhas: list[dict]) -> None: ...

    def invalidar(self, numero_controle: str, *, manter: set[str],
                  itens: set[int] | None, motivo: str) -> int: ...

    def buscar(self, termos: list[str], *, uf: str | None, desde: date | None,
               ate: date | None, limite: int) -> list[dict]: ...


class ArmazemEmMemoria:
    """Índice em memória, opcionalmente espelhado num arquivo JSON — o
    mesmo contrato do banco, para as provas e para a medição de bancada."""

    def __init__(self, arquivo=None) -> None:
        self._arquivo = arquivo
        self.cursores: dict[str, dict] = {}
        self.contratacoes: dict[str, dict] = {}
        self.resultados: dict[str, dict] = {}
        if arquivo is not None and arquivo.exists():
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
            self.cursores = dados.get("cursores", {})
            self.contratacoes = dados.get("contratacoes", {})
            self.resultados = dados.get("resultados", {})

    def persistir(self) -> None:
        if self._arquivo is not None:
            self._arquivo.write_text(json.dumps(
                {"cursores": self.cursores, "contratacoes": self.contratacoes,
                 "resultados": self.resultados}, ensure_ascii=False),
                encoding="utf-8")

    def cursor(self, uf, modalidade):
        return self.cursores.get(f"{uf}:{modalidade}")

    def salvar_cursor(self, uf, modalidade, **campos):
        chave = f"{uf}:{modalidade}"
        self.cursores[chave] = {**self.cursores.get(chave, {}), **campos}

    def contratacao(self, numero_controle):
        return self.contratacoes.get(numero_controle)

    def salvar_contratacao(self, numero_controle, **campos):
        atual = self.contratacoes.get(numero_controle,
                                      {"numero_controle": numero_controle})
        self.contratacoes[numero_controle] = {**atual, **campos}

    def pendentes(self, limite):
        fila = [c for c in self.contratacoes.values()
                if c.get("estado") == PENDENTE]
        # quem já tem homologação publicada primeiro; depois, as mais recentes
        fila.sort(key=lambda c: str(c.get("atualizacao_global") or ""),
                  reverse=True)
        fila.sort(key=lambda c: not c.get("tem_homologacao"))   # estável
        return fila[:limite]

    def gravar_resultados(self, linhas):
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for linha in linhas:
            self.resultados[linha["id_externo"]] = {
                "coletado_em": agora, **linha, "vigente": True,
                "invalidado_em": None, "invalidado_motivo": ""}

    def invalidar(self, numero_controle, *, manter, itens, motivo):
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        feitas = 0
        for linha in self.resultados.values():
            if linha.get("numero_controle") != numero_controle \
                    or linha["id_externo"] in manter \
                    or linha.get("vigente", True) is False \
                    or (itens is not None
                        and int(linha.get("numero_item") or 0) not in itens):
                continue
            linha.update(vigente=False, invalidado_em=agora,
                         invalidado_motivo=motivo)
            feitas += 1
        return feitas

    def buscar(self, termos, *, uf=None, desde=None, ate=None, limite=50):
        procurados = set(termos)
        achados = []
        for linha in self.resultados.values():
            if linha.get("vigente", True) is False:
                continue
            if uf and (linha.get("uf") or "").upper() != uf.upper():
                continue
            data = str(linha.get("data_resultado") or "")[:10]
            if desde and (not data or data < desde.isoformat()):
                continue
            if ate and data and data > ate.isoformat():
                continue
            comuns = len(procurados & set(
                str(linha.get("descricao_busca") or "").replace(",", " ")
                .replace(";", " ").split()))
            if comuns:
                achados.append((comuns, data, linha))
        # mais termos em comum primeiro; empate, o resultado mais recente
        achados.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [linha for _, _, linha in achados[:limite]]


# ---------------------------------------------------------------------------
# Coletor — o job limitado e retomável
# ---------------------------------------------------------------------------
class OrcamentoEsgotado(Exception):
    """O limite de chamadas da rodada acabou. Não é erro: é a parada."""


@dataclass
class Rodada:
    """O que UMA execução do coletor fez — vai para o relato e para a trilha."""

    chamadas: int = 0
    paginas: int = 0
    descobertas: int = 0          # contratações vistas na descoberta
    novas: int = 0                # entraram (ou voltaram) como pendentes
    fora_do_piloto: int = 0
    contratacoes_lidas: int = 0
    itens_lidos: int = 0
    resultados: int = 0           # linhas brutas de resultado lidas
    validos: int = 0              # gravados no índice
    invalidados: int = 0          # saíram da busca na revisita
    quarentena: Counter = field(default_factory=Counter)
    falhas: list[str] = field(default_factory=list)
    interrompida: bool = False    # parou pelo orçamento; a próxima continua

    def para_registro(self) -> dict:
        saida = dict(vars(self))
        saida["quarentena"] = dict(self.quarentena)
        return saida


def _abrir_url(url: str) -> str:
    requisicao = urllib.request.Request(
        url, headers={"Accept": "application/json",
                      "User-Agent": "GovDocs/pesquisa-precos"})
    with urllib.request.urlopen(requisicao, timeout=pncp.TIMEOUT_S) as resposta:
        return resposta.read().decode("utf-8")


class Coletor:
    """
    Descobre contratações e lê os resultados homologados, dentro de um
    orçamento de chamadas. Todo o estado mora no armazém: parar no meio e
    rodar de novo continua de onde parou — página da descoberta, e item
    da contratação.
    """

    def __init__(self, armazem: Armazem, *, abrir_url: Callable[[str], str] = _abrir_url,
                 max_chamadas: int = 200, pausa_s: float = 0.2,
                 dormir: Callable[[float], None] = time.sleep,
                 incluir_compras_gov: bool = False,
                 modalidades=MODALIDADES_PADRAO) -> None:
        self.armazem = armazem
        self._modalidades = frozenset(int(m) for m in modalidades)
        self._abrir = abrir_url
        self._max = max_chamadas
        self._pausa = pausa_s
        self._dormir = dormir
        self._incluir_compras_gov = incluir_compras_gov
        self.rodada = Rodada()

    # -- rede ---------------------------------------------------------------
    def _json(self, url: str):
        """JSON da URL, com recuo em 429/5xx. Erro definitivo → `ErroFonte`."""
        from .fontes import ErroFonte

        recuo = pncp.RECUO_INICIAL_S
        for tentativa in range(1, pncp.TENTATIVAS + 1):
            if self.rodada.chamadas >= self._max:
                raise OrcamentoEsgotado
            self.rodada.chamadas += 1
            if self._pausa:
                self._dormir(self._pausa)
            try:
                corpo = self._abrir(url)
                return json.loads(corpo) if corpo.strip() else None
            except urllib.error.HTTPError as erro:
                if erro.code == 204:
                    return None
                if erro.code in (429, 500, 502, 503, 504) and \
                        tentativa < pncp.TENTATIVAS:
                    self._dormir(recuo)
                    recuo *= 2
                    continue
                raise ErroFonte(f"PNCP HTTP {erro.code}") from erro
            except (urllib.error.URLError, TimeoutError, OSError) as erro:
                if tentativa < pncp.TENTATIVAS:
                    self._dormir(recuo)
                    recuo *= 2
                    continue
                raise ErroFonte("PNCP não respondeu") from erro
            except json.JSONDecodeError as erro:
                raise ErroFonte("PNCP devolveu resposta não-JSON") from erro
        raise ErroFonte("PNCP não respondeu")

    # -- descoberta ---------------------------------------------------------
    def descobrir(self, uf: str, *, modalidades=None,
                  ate: date | None = None, dias: int = 30,
                  revisita_dias: int = REVISITA_DIAS,
                  recomecar: bool = False) -> Rodada:
        """
        Percorre as contratações publicadas da UF, modalidade a modalidade.

        Incremental: a primeira janela é `dias` para trás; depois de
        concluída, a próxima vai até `ate` e recua `revisita_dias` sobre a
        anterior, para alcançar o que foi homologado depois de publicado
        (o registro é idempotente, e só volta à fila o que mudou).
        Interrompida, retoma na página em que parou. `recomecar` ignora o
        cursor e refaz a janela inteira de `dias` — para alargar a janela de
        um índice que já existe. Sem `modalidades`, as do coletor.
        """
        from .fontes import ErroFonte

        ate = ate or date.today()
        if modalidades is None:
            modalidades = sorted(self._modalidades)
        try:
            for modalidade in modalidades:
                self._descobrir_modalidade(uf.upper(), int(modalidade), ate,
                                           dias, revisita_dias, recomecar)
        except OrcamentoEsgotado:
            self.rodada.interrompida = True
        except ErroFonte as erro:
            self.rodada.falhas.append(f"descoberta {uf}: {erro}")
        return self.rodada

    def _descobrir_modalidade(self, uf: str, modalidade: int, ate: date,
                              dias: int, revisita_dias: int,
                              recomecar: bool = False) -> None:
        cursor = None if recomecar else self.armazem.cursor(uf, modalidade)
        if cursor is None:
            inicio, fim, pagina = ate - timedelta(days=dias), ate, 1
        elif cursor.get("concluido"):
            anterior = date.fromisoformat(str(cursor["data_final"])[:10])
            if anterior >= ate:
                return                     # esta janela já foi percorrida
            inicio = anterior - timedelta(days=revisita_dias)
            fim, pagina = ate, 1
        else:
            inicio = date.fromisoformat(str(cursor["data_inicial"])[:10])
            fim = date.fromisoformat(str(cursor["data_final"])[:10])
            pagina = int(cursor.get("proxima_pagina") or 1)
        while True:
            self.armazem.salvar_cursor(
                uf, modalidade, data_inicial=inicio.isoformat(),
                data_final=fim.isoformat(), proxima_pagina=pagina,
                concluido=False)
            consulta = urllib.parse.urlencode({
                "dataInicial": inicio.strftime("%Y%m%d"),
                "dataFinal": fim.strftime("%Y%m%d"),
                "codigoModalidadeContratacao": modalidade, "uf": uf,
                "pagina": pagina, "tamanhoPagina": PAGINA_DESCOBERTA})
            dados = self._json(
                f"{pncp.BASE}{ROTA_DESCOBERTA}?{consulta}") or {}
            self.rodada.paginas += 1
            for contratacao in dados.get("data") or []:
                self._registrar_descoberta(contratacao)
            if not dados.get("data") or \
                    int(dados.get("paginasRestantes") or 0) <= 0:
                break
            pagina += 1
        self.armazem.salvar_cursor(uf, modalidade, proxima_pagina=1,
                                   concluido=True)

    def _registrar_descoberta(self, contratacao: dict) -> None:
        controle = str(contratacao.get("numeroControlePNCP") or "")
        if pncp.controle_da_entrada(controle) is None:
            return
        self.rodada.descobertas += 1
        atualizacao = str(contratacao.get("dataAtualizacaoGlobal") or "")
        anterior = self.armazem.contratacao(controle)
        if anterior and anterior.get("atualizacao_global") == atualizacao \
                and anterior.get("estado") != PENDENTE:
            return                          # já vista nesta mesma versão
        plataforma = str(contratacao.get("usuarioNome") or "")
        fora = ((plataforma == PLATAFORMA_COMPRAS_GOV
                 and not self._incluir_compras_gov)
                or not self._no_piloto(contratacao.get("modalidadeId")))
        if fora:
            self.rodada.fora_do_piloto += 1
        else:
            self.rodada.novas += 1
        unidade = contratacao.get("unidadeOrgao") or {}
        self.armazem.salvar_contratacao(
            controle, uf=unidade.get("ufSigla"),
            modalidade_id=contratacao.get("modalidadeId"),
            plataforma=plataforma, atualizacao_global=atualizacao,
            tem_homologacao=bool(contratacao.get("valorTotalHomologado")),
            estado=FORA_DO_PILOTO if fora else PENDENTE,
            tentativas=0, itens_lidos_ate=0, resultados_validos=0, erro="",
            resumo=resumo_da_contratacao(contratacao))

    def _no_piloto(self, modalidade) -> bool:
        try:
            return int(modalidade) in self._modalidades
        except (TypeError, ValueError):
            return False                    # sem modalidade: não se lê

    # -- coleta -------------------------------------------------------------
    def coletar(self, max_contratacoes: int = 50) -> Rodada:
        """
        Lê itens e resultados das contratações pendentes, até o orçamento.

        Pendente de modalidade fora do piloto (a dispensa que entrou na fila
        antes de sair da lista) vai para `FORA_DO_PILOTO` sem chamada à
        fonte e não ocupa vaga de `max_contratacoes`.
        """
        from .fontes import ErroFonte

        for contratacao in self._fila(max_contratacoes):
            controle = contratacao["numero_controle"]
            try:
                self._coletar_contratacao(contratacao)
            except OrcamentoEsgotado:
                self.rodada.interrompida = True
                break
            except ErroFonte as erro:
                tentativas = int(contratacao.get("tentativas") or 0) + 1
                self.armazem.salvar_contratacao(
                    controle, tentativas=tentativas, erro=str(erro)[:200],
                    estado=FALHA if tentativas >= TENTATIVAS_POR_CONTRATACAO
                    else PENDENTE)
                self.rodada.falhas.append(f"{controle}: {erro}")
        return self.rodada

    def _fila(self, max_contratacoes: int):
        """Pendentes do piloto, até `max_contratacoes`; as de fora saem da
        fila no caminho. Cada contratação aparece uma vez por rodada (a que
        falhou e voltou a `PENDENTE` fica para a próxima)."""
        vistas: set[str] = set()
        entregues = 0
        while entregues < max_contratacoes:
            lote = [c for c in self.armazem.pendentes(max_contratacoes - entregues
                                                      + len(vistas))
                    if c["numero_controle"] not in vistas]
            if not lote:
                return
            for contratacao in lote:
                vistas.add(contratacao["numero_controle"])
                if not self._no_piloto(contratacao.get("modalidade_id")):
                    self.rodada.fora_do_piloto += 1
                    self.armazem.salvar_contratacao(
                        contratacao["numero_controle"], estado=FORA_DO_PILOTO,
                        erro="modalidade fora do piloto")
                    continue
                entregues += 1
                yield contratacao
                if entregues >= max_contratacoes:
                    return

    def _coletar_contratacao(self, contratacao: dict) -> None:
        controle = contratacao["numero_controle"]
        cnpj, ano, seq = pncp.controle_da_entrada(controle)
        base = f"{pncp.BASE_PNCP}/orgaos/{cnpj}/compras/{ano}/{seq}/itens"
        itens: list[dict] = []
        pagina = 1
        while True:
            lote = self._json(
                f"{base}?pagina={pagina}&tamanhoPagina={PAGINA_ITENS}") or []
            itens.extend(lote)
            if len(lote) < PAGINA_ITENS:
                break
            pagina += 1
        lidos_ate = int(contratacao.get("itens_lidos_ate") or 0)
        # leitura COMPLETA (primeira, ou revisita depois de atualização):
        # no fim, o que estava no índice e não foi confirmado agora sai da
        # busca. Retomada no meio só invalida item a item — os anteriores
        # foram confirmados na rodada que parou.
        completa = lidos_ate == 0
        fila = sorted((i for i in itens if i.get("temResultado")
                       and int(i.get("numeroItem") or 0) > lidos_ate),
                      key=lambda i: int(i.get("numeroItem") or 0))
        resumo = contratacao.get("resumo") or {}
        validos = int(contratacao.get("resultados_validos") or 0)
        confirmados: set[str] = set()
        for item in fila:
            numero = int(item.get("numeroItem") or 0)
            linhas = self._json(f"{base}/{numero}/resultados") or []
            gravar = []
            for resultado in linhas:
                self.rodada.resultados += 1
                linha, motivo = linha_do_resultado(resumo, item, resultado)
                if linha is None:
                    self.rodada.quarentena[motivo] += 1
                else:
                    gravar.append(linha)
            if gravar:
                self.armazem.gravar_resultados(gravar)
            do_item = {linha["id_externo"] for linha in gravar}
            confirmados |= do_item
            self.rodada.invalidados += self.armazem.invalidar(
                controle, manter=do_item, itens={numero},
                motivo=MOTIVO_REVISITA)
            validos += len(gravar)
            self.rodada.validos += len(gravar)
            self.rodada.itens_lidos += 1
            # o ponto de retomada é o item: parar aqui não relê os anteriores
            self.armazem.salvar_contratacao(
                controle, itens_lidos_ate=numero, resultados_validos=validos)
        if completa:
            # item que perdeu o resultado (cancelado, revogado, corrigido)
            # nem entra na fila: sai da busca aqui
            self.rodada.invalidados += self.armazem.invalidar(
                controle, manter=confirmados, itens=None,
                motivo=MOTIVO_REVISITA)
        self.rodada.contratacoes_lidas += 1
        com_resultado = any(i.get("temResultado") for i in itens)
        self.armazem.salvar_contratacao(
            controle, estado=COLETADA if com_resultado else SEM_RESULTADO,
            itens=len(itens), resultados_validos=validos, erro="",
            coletada_em=datetime.now(timezone.utc).isoformat(
                timespec="seconds"))


# ---------------------------------------------------------------------------
# Fonte de preço — só lê o índice
# ---------------------------------------------------------------------------
Buscador = Callable[..., list]


class PNCPIndice(FontePesquisaPreco):
    """
    Resultados homologados do PNCP por DESCRIÇÃO, lidos do índice.

    Mesma identidade de fonte do PNCP (`pncp`): a fusão entre portais e o
    link de verificação são os da consulta por contratação. O filtro
    grosseiro é o do Compras.gov (metade dos termos); quem ranqueia e
    monta a cesta continua sendo o motor comum.
    """

    fonte = pncp.FONTE_PNCP
    capacidades = frozenset({Capacidade.PRECO, Capacidade.EVIDENCIA})

    def __init__(self, buscar: Buscador) -> None:
        self._buscar = buscar

    def pesquisar(self, consulta: Consulta) -> ResultadoBusca:
        from .compras_gov import _casa, _tokens

        resultado = ResultadoBusca(fonte=self.fonte)
        grupos = grupos_da_consulta(consulta)
        if not grupos:
            return resultado.registrar(
                "PNCP: descrição sem termo pesquisável no índice")
        # uma consulta POR VARIANTE, cada uma com o seu próprio corte de
        # relevância; a linha entra se casar com qualquer variante
        vistas: dict[str, dict] = {}
        casou: set[str] = set()
        for termos in grupos:
            try:
                resultado.chamadas += 1
                linhas = self._buscar(termos, uf=consulta.uf,
                                      desde=consulta.data_inicial,
                                      ate=consulta.data_final,
                                      limite=consulta.limite)
            except Exception as erro:  # noqa: BLE001 — índice fora não derruba a busca
                return resultado.falhar(
                    "o índice do PNCP não respondeu agora "
                    f"({type(erro).__name__}); a pesquisa continua nas "
                    "demais fontes")
            if not isinstance(linhas, list):
                return resultado.falhar("o índice do PNCP devolveu resposta "
                                        "inesperada")
            procurados = {t.upper() for t in termos}
            for linha in linhas:
                if not isinstance(linha, dict) or linha.get("vigente") is False:
                    continue
                chave = str(linha.get("id_externo") or id(linha))
                vistas.setdefault(chave, linha)
                if _casa(procurados, _tokens(str(linha.get("descricao") or ""))):
                    casou.add(chave)
        recusadas = 0
        for chave, linha in vistas.items():
            if chave not in casou:
                continue
            referencia = referencia_da_linha(linha)
            if referencia is None:
                recusadas += 1
                continue
            resultado.referencias.append(referencia)
        if recusadas:
            resultado.registrar(
                f"PNCP: {recusadas} registro(s) do índice sem preço "
                "conferível foram ignorados")
        return resultado

    def healthcheck(self) -> bool:
        try:
            return isinstance(self._buscar(["papel"], uf=None, desde=None,
                                           ate=None, limite=1), list)
        except Exception:  # noqa: BLE001
            return False
