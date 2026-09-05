"""
Adapter do Compras.gov.br — Dados Abertos.

Contrato verificado contra o servidor real em 04/09/2026, não deduzido da
documentação. Dois caminhos, e é a existência dos DOIS que permite ao
módulo aceitar CATMAT sem exigi-lo:

1. **com código** — `/modulo-pesquisa-preco/1_consultarMaterial`, que
   exige `tipo` (`codigoItemCatalogo`|`codigoPdm`) e `codigo`. É o
   caminho preferencial: série de preços praticados do item exato, e
   traz `capacidadeUnidadeFornecimento`, que é o único dado capaz de
   autorizar a conversão de caixa para unidade;

2. **sem código** — `/modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133`,
   que exige apenas a janela de datas e devolve, no MESMO registro, a
   descrição em texto livre, a unidade, a quantidade, o preço homologado
   e o código de catálogo quando existe. É o caminho que atende quem
   chega com código interno do município, como as planilhas reais.

Medido em 500 itens de contratações (01–07/08/2025): 100% têm descrição,
98% têm `codItemCatalogo` e 90% têm preço homologado. O corpus federal é
bem catalogado — o descasamento está do lado do usuário, e é ele que o
caminho 2 resolve.

Nenhum endpoint desta API oferece busca textual livre; a filtragem por
descrição é feita aqui, sobre o que a janela devolveu.
"""

from __future__ import annotations

import json
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from .fontes import (PAGINA_MAXIMA, PAGINA_MINIMA, Consulta,
                     FontePesquisaPreco, ResultadoBusca)
from .modelo import (Fonte, NaturezaValor, Referencia, para_data,
                     para_decimal)

BASE = "https://dadosabertos.compras.gov.br"

FONTE_PRECOS = Fonte(
    id="compras_gov_precos",
    nome="Compras.gov.br — Preços Praticados",
    tipo="sistema_oficial",
)
FONTE_ITENS = Fonte(
    id="compras_gov_itens",
    nome="Compras.gov.br — Itens de Contratações (Lei 14.133)",
    tipo="contratacao_similar",
)

# Retentativa curta e com recuo. O objetivo não é insistir até passar — é
# atravessar um 429 ou um 5xx momentâneo sem derrubar a pesquisa inteira.
TENTATIVAS = 3
RECUO_INICIAL_S = 1.0
TIMEOUT_S = 45


def _sem_acento(texto: str) -> str:
    base = unicodedata.normalize("NFKD", (texto or "").upper())
    return "".join(c for c in base if not unicodedata.combining(c))


def _tokens(texto: str) -> set[str]:
    """
    Palavras significativas de uma descrição.

    Descarta ruído de catálogo ("ESPECIFICAÇÃO", "TIPO") e tokens de 1–2
    letras, que casariam com qualquer coisa. É filtragem grosseira e
    determinística de propósito: o ranqueamento fino é da Fase 2.
    """
    ruido = {"ESPECIFICACAO", "ESPECIFICACOES", "TIPO", "MATERIAL", "COM",
             "SEM", "PARA", "DE", "DA", "DO", "EM", "OU", "E", "A", "O",
             "APLICACAO", "CARACTERISTICAS", "ADICIONAIS", "COR"}
    palavras = _sem_acento(texto).replace(",", " ").replace(";", " ").split()
    return {p.strip(".:") for p in palavras
            if len(p.strip(".:")) > 2 and p.strip(".:") not in ruido}


def _casa(procurados: set[str], do_registro: set[str]) -> bool:
    """
    Metade dos termos significativos presentes basta para ser candidato.

    Piso grosseiro e deliberado: aqui só se decide quem ENTRA na lista.
    O ranqueamento fino, que é quem de fato separa PASTA de PASTA
    CATÁLOGO, é da Fase 2 e continua determinístico.
    """
    if not procurados:
        return False
    return len(procurados & do_registro) * 2 >= len(procurados)


class ComprasGovAdapter(FontePesquisaPreco):
    """Consulta o Compras.gov e devolve referências normalizadas."""

    fonte = FONTE_ITENS

    def __init__(self, abrir_url=None) -> None:
        # injetável para que os testes rodem sobre fixtures reais sem
        # depender da internet (§48)
        self._abrir = abrir_url or self._abrir_url

    # ------------------------------------------------------------------
    # transporte
    # ------------------------------------------------------------------
    def _abrir_url(self, url: str) -> str:
        requisicao = urllib.request.Request(
            url, headers={"Accept": "application/json",
                          "User-Agent": "GovDocs/pesquisa-precos"})
        with urllib.request.urlopen(requisicao, timeout=TIMEOUT_S) as resposta:
            return resposta.read().decode("utf-8")

    def _obter(self, caminho: str, parametros: dict,
               resultado: ResultadoBusca) -> dict | None:
        """
        GET com retentativa. Devolve `None` quando desiste — e o motivo
        fica em `resultado.ocorrencias`, nunca numa exceção que sobe para
        a tela.
        """
        limpos = {k: v for k, v in parametros.items() if v not in (None, "")}
        url = f"{BASE}{caminho}?{urllib.parse.urlencode(limpos)}"
        recuo = RECUO_INICIAL_S
        for tentativa in range(1, TENTATIVAS + 1):
            try:
                resultado.chamadas += 1
                return json.loads(self._abrir(url))
            except urllib.error.HTTPError as erro:
                if erro.code in (429, 500, 502, 503, 504) and \
                        tentativa < TENTATIVAS:
                    time.sleep(recuo)
                    recuo *= 2
                    continue
                resultado.falhar(
                    f"{self.fonte.nome} respondeu HTTP {erro.code} em "
                    f"{caminho}")
                return None
            except (urllib.error.URLError, TimeoutError, OSError):
                if tentativa < TENTATIVAS:
                    time.sleep(recuo)
                    recuo *= 2
                    continue
                resultado.falhar(
                    f"{self.fonte.nome} não respondeu em {caminho}")
                return None
            except json.JSONDecodeError:
                # a API devolve texto puro em erro de validação
                resultado.falhar(
                    f"{self.fonte.nome} devolveu resposta não-JSON em "
                    f"{caminho}")
                return None
        return None

    @staticmethod
    def _tamanho_de_pagina(limite: int) -> int:
        """A API recusa fora de 10..500 — respeitar é do adapter."""
        return max(PAGINA_MINIMA, min(limite, PAGINA_MAXIMA))

    # ------------------------------------------------------------------
    # caminhos de busca
    # ------------------------------------------------------------------
    def pesquisar(self, consulta: Consulta) -> ResultadoBusca:
        """
        Usa o código quando ele existe; funciona sem ele quando não.

        Os dois caminhos somam: tendo código, o caminho por contratações
        ainda acrescenta contratações recentes que o de preços praticados
        pode não trazer.
        """
        resultado = ResultadoBusca(fonte=self.fonte)
        if consulta.tem_codigo:
            self._por_codigo(consulta, resultado)
        self._por_descricao(consulta, resultado)
        return resultado

    def _por_codigo(self, consulta: Consulta,
                    resultado: ResultadoBusca) -> None:
        """Preços praticados do item exato — o caminho mais preciso."""
        caminho = ("/modulo-pesquisa-preco/3_consultarServico"
                   if consulta.material_ou_servico == "S"
                   else "/modulo-pesquisa-preco/1_consultarMaterial")
        dados = self._obter(caminho, {
            "pagina": 1,
            "tamanhoPagina": self._tamanho_de_pagina(consulta.limite),
            "tipo": "codigoItemCatalogo",
            "codigo": consulta.codigo_catalogo,
            "estado": consulta.uf,
            "codigoMunicipio": consulta.codigo_municipio,
            "dataCompraInicio": _iso(consulta.data_inicial),
            "dataCompraFim": _iso(consulta.data_final),
        }, resultado)
        if not dados:
            return
        resultado.total_disponivel = dados.get("totalRegistros")
        for bruto in dados.get("resultado") or []:
            resultado.referencias.append(
                _referencia_de_preco_praticado(bruto))

    def _por_descricao(self, consulta: Consulta,
                       resultado: ResultadoBusca) -> None:
        """
        Caminho SEM exigência de código.

        A API não busca por texto: pede-se a janela de datas (com a
        classe, quando conhecida) e a filtragem por descrição acontece
        aqui. É por isso que a janela padrão é curta — pedir um ano
        inteiro devolveria centenas de milhares de itens para filtrar em
        memória.
        """
        fim = consulta.data_final or date.today()
        inicio = consulta.data_inicial or (fim - timedelta(days=30))
        dados = self._obter(
            "/modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133", {
                "pagina": 1,
                "tamanhoPagina": self._tamanho_de_pagina(PAGINA_MAXIMA),
                "dataInclusaoPncpInicial": _iso(inicio),
                "dataInclusaoPncpFinal": _iso(fim),
                "codItemCatalogo": consulta.codigo_catalogo,
                "codigoClasse": consulta.codigo_classe,
                "materialOuServico": consulta.material_ou_servico,
                "temResultado": "true",
            }, resultado)
        if not dados:
            return

        procurados = _tokens(consulta.descricao)
        if not procurados:
            resultado.registrar(
                "descrição do item é curta ou genérica demais para filtrar "
                "por texto — informe o CATMAT/CATSER para uma busca precisa")
            return

        # Sinônimos da camada semântica, quando houve (§8). Eles entram
        # como conjuntos ALTERNATIVOS: casar com qualquer um deles basta
        # para o registro virar candidato. Somá-los aos termos originais
        # faria o oposto do pretendido — o denominador cresceria e a
        # busca ficaria mais restrita a cada sinônimo sugerido.
        alternativos = [t for t in (_tokens(termo) for termo
                                    in consulta.termos_alternativos) if t]

        for bruto in dados.get("resultado") or []:
            texto = (bruto.get("descricaodetalhada")
                     or bruto.get("descricaoResumida") or "")
            tokens_do_registro = _tokens(texto)
            # metade dos termos significativos é um piso grosseiro e
            # deliberado: aqui só se decide quem ENTRA na lista de
            # candidatos; ranquear é trabalho da Fase 2.
            if _casa(procurados, tokens_do_registro) or any(
                    _casa(alt, tokens_do_registro) for alt in alternativos):
                resultado.referencias.append(
                    _referencia_de_item_contratado(bruto))

    def healthcheck(self) -> bool:
        resultado = ResultadoBusca(fonte=self.fonte)
        dados = self._obter("/modulo-material/1_consultarGrupoMaterial",
                            {"pagina": 1, "tamanhoPagina": PAGINA_MINIMA},
                            resultado)
        return bool(dados)


def _iso(valor: date | None) -> str | None:
    return valor.isoformat() if valor else None


def _referencia_de_preco_praticado(bruto: dict) -> Referencia:
    """`1_consultarMaterial` → modelo normalizado."""
    return Referencia(
        fonte=FONTE_PRECOS,
        id_externo=str(bruto.get("idCompraItem")
                       or bruto.get("idItemCompra") or ""),
        bruto=bruto,
        descricao_original=(bruto.get("descricaoDetalhadaItem")
                            or bruto.get("descricaoItem") or ""),
        unidade_original=bruto.get("siglaUnidadeFornecimento"),
        quantidade_original=para_decimal(bruto.get("quantidade")),
        valor_unitario_original=para_decimal(bruto.get("precoUnitario")),
        capacidade_embalagem=para_decimal(
            bruto.get("capacidadeUnidadeFornecimento")),
        codigo_catalogo=_texto(bruto.get("codigoItemCatalogo")),
        tipo_catalogo="CATMAT",
        codigo_pdm=_texto(bruto.get("codigoPdm")),
        codigo_classe=_texto(bruto.get("codigoClasse")),
        orgao=bruto.get("nomeOrgao") or bruto.get("nomeUasg"),
        uf=bruto.get("estado"),
        municipio=bruto.get("municipio"),
        fornecedor=bruto.get("nomeFornecedor"),
        ni_fornecedor=_texto(bruto.get("niFornecedor")),
        marca=bruto.get("marca"),
        criterio_julgamento=_texto(bruto.get("criterioJulgamento")),
        modalidade=_texto(bruto.get("modalidade")),
        data_compra=para_data(bruto.get("dataCompra")),
        data_resultado=para_data(bruto.get("dataResultado")),
        referencia_externa=_texto(bruto.get("idCompra")),
        # O módulo "Preços Praticados" publica o que a Administração
        # efetivamente pagou — é o nome e o propósito do endpoint, e
        # `precoUnitario` é o valor da compra realizada. É a única
        # origem deste projeto cuja natureza não depende de qual campo
        # veio preenchido.
        natureza_valor=NaturezaValor.PRATICADO,
    )


def _referencia_de_item_contratado(bruto: dict) -> Referencia:
    """
    `2_consultarItensContratacoes_PNCP_14133` → modelo normalizado.

    **A natureza do valor sai do campo que o preencheu**, e essa é a
    correção mais importante deste adapter.

    A versão anterior fazia `valor_unitario_original = homologado or
    estimado` e seguia adiante: quando a contratação ainda não tinha
    resultado, o `valorUnitarioEstimado` — a expectativa do órgão de
    origem — entrava como referência comum, disputava a cesta em pé de
    igualdade com preço praticado e podia formar o valor estimado da
    contratação. Havia um `motivo` registrado, mas motivo é texto: nada
    no modelo impedia o número de ser usado.

    Agora o campo escolhido carimba a natureza (`HOMOLOGADO` ou
    `ESTIMADO_ORIGEM`), e é a natureza que a cesta consulta. O valor
    estimado continua coletado, listado e auditável — o que ele não faz
    mais é entrar sozinho.
    """
    homologado = para_decimal(bruto.get("valorUnitarioResultado"))
    estimado = para_decimal(bruto.get("valorUnitarioEstimado"))
    if homologado is not None:
        natureza = NaturezaValor.HOMOLOGADO
    elif estimado is not None:
        natureza = NaturezaValor.ESTIMADO_ORIGEM
    else:
        natureza = NaturezaValor.OUTRO
    referencia = Referencia(
        fonte=FONTE_ITENS,
        id_externo=str(bruto.get("idCompraItem") or ""),
        bruto=bruto,
        descricao_original=(bruto.get("descricaodetalhada")
                            or bruto.get("descricaoResumida") or ""),
        unidade_original=bruto.get("unidadeMedida"),
        quantidade_original=para_decimal(
            bruto.get("quantidadeResultado") or bruto.get("quantidade")),
        valor_unitario_original=homologado or estimado,
        # este endpoint não informa itens por embalagem; sem esse dado a
        # conversão de embalagem para unidade fica bloqueada, por regra
        capacidade_embalagem=None,
        codigo_catalogo=_texto(bruto.get("codItemCatalogo")),
        tipo_catalogo="CATSER" if bruto.get("materialOuServico") == "S"
        else "CATMAT",
        codigo_pdm=_texto(bruto.get("codigoPdm")),
        codigo_classe=_texto(bruto.get("codigoClasse")),
        orgao=_texto(bruto.get("orgaoEntidadeCnpj")),
        fornecedor=bruto.get("nomeFornecedor"),
        ni_fornecedor=_texto(bruto.get("codFornecedor")),
        criterio_julgamento=bruto.get("criterioJulgamentoNome"),
        data_resultado=para_data(bruto.get("dataResultado")),
        data_compra=para_data(bruto.get("dataInclusaoPncp")),
        referencia_externa=_texto(bruto.get("numeroControlePNCPCompra")),
        natureza_valor=natureza,
    )
    if natureza is NaturezaValor.ESTIMADO_ORIGEM:
        referencia.com_motivo(
            "preço ESTIMADO pelo órgão de origem — a contratação ainda não "
            "tem resultado homologado")
    return referencia


def _texto(valor) -> str | None:
    """Códigos numéricos viram texto: '5436' e 5436 são o mesmo código."""
    return None if valor in (None, "") else str(valor)
