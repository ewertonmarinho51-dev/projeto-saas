"""
Adapter do PNCP — Portal Nacional de Contratações Públicas.

Papel deliberadamente diferente do Compras.gov: aqui o PNCP é
**enriquecimento e comprovação**, não porta de entrada da busca.

O motivo é o contrato da API, verificado contra o servidor: a consulta
pública é navegável de cima para baixo (contratação → itens → resultados)
e exige janela de data mais modalidade. Não há busca de item por
descrição que sirva de ponto de partida para um item de planilha
municipal. Tentar usá-lo como fonte primária significaria varrer
contratações inteiras para filtrar em memória — caro e pior que o caminho
do Compras.gov, que já devolve descrição e preço no mesmo registro.

O que o PNCP dá, e que o Compras.gov não dá, é a **referência oficial
publicável**: `numeroControlePNCP` e `linkSistemaOrigem`, que transformam
uma referência de preço em evidência com endereço verificável — o que o
relatório precisa para ser auditável meses depois (§34).

INVESTIGAÇÃO DE 05/09/2026 — o PNCP pode virar fonte de PREÇO?
--------------------------------------------------------------
Foi feita a pergunta contra o servidor, não contra a documentação. O que
respondeu, e o que não respondeu:

* `/api/consulta/v1/contratacoes/atualizacao` → **200**. E o registro da
  contratação traz `valorTotalHomologado` **e** `valorTotalEstimado`,
  separados — o próprio PNCP distingue as duas naturezas, o que
  corrobora `modelo.NaturezaValor`. Mas são totais da CONTRATAÇÃO, não
  preço unitário de item: não servem de referência;
* `/api/consulta/v1/contratos` → **200**;
* `/api/consulta/v1/contratacoes/publicacao` → **500**, "Erro na
  comunicação com o banco de dados";
* `/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens` e
  `.../itens/{n}/resultados` → **502 e 503**, indisponíveis em todas as
  tentativas com recuo.

O preço unitário com natureza conhecida mora justamente nos dois últimos
endpoints, e eles não responderam. **Não dá para verificar hoje quais
campos existem, nem se `valorUnitarioHomologado` vem preenchido.**

RESSONDAGEM DE 07/09/2026 — a conclusão não mudou, um detalhe mudou
------------------------------------------------------------------
* `/contratacoes/publicacao` → **200**. O 500 de 05/09 era transitório,
  e o registro fica para que ninguém escreva no código que aquele
  endpoint "não funciona". De quebra: o servidor exige
  `tamanhoPagina >= 10` e devolve 400 com "must be greater than or equal
  to 10" abaixo disso;
* `/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens` → **502** outra
  vez, com três tentativas, recuo exponencial e 90 s de espera de
  leitura.

O endpoint que traz o preço unitário continua sem responder, em duas
sondagens separadas por dois dias. A conclusão abaixo permanece — e
permanece pelo mesmo motivo, não por inércia.

Conclusão, e ela é deliberada: o PNCP **continua declarando apenas
`Capacidade.EVIDENCIA`**. Escrever um conversor para campos que não pude
observar seria adivinhar o contrato de uma API — exatamente o tipo de
suposição que já produziu defeito neste módulo. Quando os endpoints
voltarem, o caminho está pavimentado: basta ler o campo, carimbar a
`NaturezaValor` correspondente e acrescentar `Capacidade.PRECO` aqui.
Até lá o sistema diz a verdade sobre o que encontrou.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from decimal import Decimal

from .fontes import (Capacidade, Consulta, FontePesquisaPreco,
                     ResultadoBusca)
from .modelo import Fonte, NaturezaValor, Referencia, para_data, para_decimal

BASE = "https://pncp.gov.br/api/consulta/v1"

FONTE_PNCP = Fonte(
    id="pncp",
    nome="PNCP — Portal Nacional de Contratações Públicas",
    tipo="sistema_oficial",
)

TENTATIVAS = 3
RECUO_INICIAL_S = 1.0
TIMEOUT_S = 45

# O PNCP publica a contratação numa URL estável a partir do número de
# controle (CNPJ-sequencial-numero/ano). Montar o link a partir dele é o
# que dá endereço verificável à evidência.
URL_CONTRATACAO = "https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}"


class PNCPAdapter(FontePesquisaPreco):
    """Enriquece referências com a publicação oficial correspondente."""

    fonte = FONTE_PNCP

    # Declaração honesta do que este adapter entrega HOJE. Enquanto for
    # só EVIDENCIA, o motor não o conta ao decidir se as fontes de preço
    # responderam — que é o ponto todo: o PNCP estar de pé não conserta
    # o Compras.gov estar fora.
    capacidades = frozenset({Capacidade.EVIDENCIA})

    def __init__(self, abrir_url=None) -> None:
        self._abrir = abrir_url or self._abrir_url

    def _abrir_url(self, url: str) -> str:
        requisicao = urllib.request.Request(
            url, headers={"Accept": "application/json",
                          "User-Agent": "GovDocs/pesquisa-precos"})
        with urllib.request.urlopen(requisicao, timeout=TIMEOUT_S) as resposta:
            return resposta.read().decode("utf-8")

    def _obter(self, caminho: str, parametros: dict,
               resultado: ResultadoBusca) -> dict | None:
        limpos = {k: v for k, v in parametros.items() if v not in (None, "")}
        url = f"{BASE}{caminho}?{urllib.parse.urlencode(limpos)}"
        recuo = RECUO_INICIAL_S
        for tentativa in range(1, TENTATIVAS + 1):
            try:
                resultado.chamadas += 1
                return json.loads(self._abrir(url))
            except urllib.error.HTTPError as erro:
                if erro.code == 204:      # sem conteúdo não é falha
                    return {"data": []}
                if erro.code in (429, 500, 502, 503, 504) and \
                        tentativa < TENTATIVAS:
                    time.sleep(recuo)
                    recuo *= 2
                    continue
                resultado.falhar(
                    f"o PNCP respondeu HTTP {erro.code}; a pesquisa "
                    "continua nas demais fontes")
                return None
            except (urllib.error.URLError, TimeoutError, OSError):
                if tentativa < TENTATIVAS:
                    time.sleep(recuo)
                    recuo *= 2
                    continue
                resultado.falhar(
                    "o PNCP não respondeu agora; a pesquisa continua nas "
                    "demais fontes e você pode tentar novamente")
                return None
            except json.JSONDecodeError:
                resultado.falhar("o PNCP devolveu resposta não-JSON")
                return None
        return None

    def pesquisar(self, consulta: Consulta) -> ResultadoBusca:
        """
        O PNCP não é porta de entrada — ver o docstring do módulo.

        Devolver vazio é honesto e mantém o contrato da interface;
        fingir uma busca por descrição que a API não oferece seria pior.

        O que mudou nesta rodada: isto é `registrar`, e NUNCA `falhar`.
        Antes, o recado de projeto entrava em `ocorrencias` e
        `houve_falha` era `bool(ocorrencias)` — então o PNCP aparecia
        permanentemente quebrado, e o servidor lia "uma fonte falhou" a
        cada item pesquisado. Recado não é falha, e o desfecho aqui é
        `SEM_RESULTADO`.
        """
        resultado = ResultadoBusca(fonte=self.fonte)
        return resultado.registrar(
            "o PNCP é usado para comprovação e enriquecimento das "
            "referências, não como busca inicial por descrição")

    def link_da_contratacao(self, numero_controle: str | None) -> str | None:
        """
        Referência oficial publicável a partir do número de controle.

        Formato observado nos dados reais:
        `00038166000105-1-000273/2025` → CNPJ, sequencial do órgão,
        número/ano da contratação. Formato inesperado devolve `None`: um
        link errado no relatório é pior do que link nenhum.
        """
        if not numero_controle or "/" not in numero_controle:
            return None
        try:
            esquerda, ano = numero_controle.rsplit("/", 1)
            cnpj, _seq_orgao, numero = esquerda.split("-", 2)
        except ValueError:
            return None
        if not (cnpj.isdigit() and ano.isdigit() and numero.strip("0").isdigit()):
            return None
        return URL_CONTRATACAO.format(
            cnpj=cnpj, ano=ano, sequencial=numero.lstrip("0") or numero)

    def healthcheck(self) -> bool:
        resultado = ResultadoBusca(fonte=self.fonte)
        hoje = date.today()
        dados = self._obter("/contratacoes/publicacao", {
            "dataInicial": hoje.strftime("%Y%m%d"),
            "dataFinal": hoje.strftime("%Y%m%d"),
            "codigoModalidadeContratacao": 6,
            "pagina": 1, "tamanhoPagina": 10,
        }, resultado)
        return dados is not None


# ---------------------------------------------------------------------------
# RESSONDAGEM DE 15/10/2026 — o resultado do item respondeu
# ---------------------------------------------------------------------------
# `/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens` → 200 em 0,2 s, e
# `.../itens/{n}/resultados` → 200, com `valorUnitarioHomologado`,
# `quantidadeHomologada` e `valorTotalHomologado` coerentes entre si em
# todas as amostras (21,00 × 200 = 4.200,00; 1,96 × 22.500 = 44.100,00).
# A resposta real está gravada em
# `tests/fixtures/pncp_resultados_2026-10-15.json`, com URL e horário.
#
# O que NÃO mudou: o PNCP continua sem busca de item por descrição. Então
# a busca por descrição segue no Compras.gov, e o PNCP vira fonte de
# PREÇO por outra porta — a contratação CONHECIDA. O servidor informa o
# número de controle (ou o link do edital) de uma contratação similar,
# e os itens homologados dela entram pelo MESMO pipeline: procedência,
# unidade, comparabilidade e cesta (Lei 14.133, art. 23, § 1º, II —
# contratações similares feitas pela Administração Pública).
BASE_PNCP = "https://pncp.gov.br/api/pncp/v1"
MAX_ITENS_COM_RESULTADO = 20
PAGINA_ITENS = 500

_PADRAO_CONTROLE = re.compile(r"(\d{14})-\d+-(\d+)/(\d{4})")
_PADRAO_LINK = re.compile(r"/editais/(\d{14})/(\d{4})/(\d+)")


def controle_da_entrada(texto: str) -> tuple[str, str, str] | None:
    """
    `(cnpj, ano, sequencial)` a partir do número de controle PNCP ou do
    link do edital no portal. Qualquer outra coisa → `None`. A URL da API
    é MONTADA aqui a partir de dígitos, nunca copiada da entrada: campo
    livre não vira requisição para endereço arbitrário.
    """
    texto = (texto or "").strip()
    achado = _PADRAO_CONTROLE.search(texto)
    if achado:
        cnpj, seq, ano = achado.groups()
        return cnpj, ano, str(int(seq))
    achado = _PADRAO_LINK.search(texto)
    if achado:
        cnpj, ano, seq = achado.groups()
        return cnpj, ano, str(int(seq))
    return None


def _id_compra_de_origem(link: str | None) -> str | None:
    """`...?compra=94300105905082026` → o `idCompra` do Compras.gov, que
    permite reconhecer a MESMA compra nos dois portais."""
    if not link:
        return None
    valores = urllib.parse.parse_qs(urllib.parse.urlsplit(str(link)).query)
    compra = (valores.get("compra") or [None])[0]
    return compra if compra and compra.isdigit() else None


def _total_coerente(unitario: Decimal, quantidade: Decimal | None,
                    total: Decimal | None) -> bool:
    """
    Unitário × quantidade bate com o total homologado (tolerância de um
    centavo por unidade, para arredondamento). Sem total ou quantidade
    não há como conferir — e o registro não entra.
    """
    if quantidade is None or total is None or quantidade <= 0:
        return False
    return abs(unitario * quantidade - total) <= max(
        Decimal("0.05"), quantidade * Decimal("0.01"))


class PNCPContratacao(FontePesquisaPreco):
    """
    Os resultados homologados de UMA contratação do PNCP, como fonte de
    preço. Para o item consultado, lê os resultados apenas dos itens da
    contratação que compartilham termos com a descrição (no máximo
    `MAX_ITENS_COM_RESULTADO`): uma contratação de 300 itens não vira
    300 chamadas.
    """

    fonte = FONTE_PNCP
    capacidades = frozenset({Capacidade.PRECO, Capacidade.EVIDENCIA})

    def __init__(self, entrada: str, abrir_url=None) -> None:
        self._controle = controle_da_entrada(entrada)
        self._abrir = abrir_url or PNCPAdapter()._abrir_url

    def _json(self, url: str, resultado: ResultadoBusca):
        resultado.chamadas += 1
        try:
            return json.loads(self._abrir(url))
        except urllib.error.HTTPError as erro:
            if erro.code == 204:
                return []
            resultado.falhar(f"o PNCP respondeu HTTP {erro.code}")
        except (urllib.error.URLError, TimeoutError, OSError):
            resultado.falhar("o PNCP não respondeu agora; tente novamente")
        except json.JSONDecodeError:
            resultado.falhar("o PNCP devolveu resposta não-JSON")
        return None

    def pesquisar(self, consulta: Consulta) -> ResultadoBusca:
        from .compras_gov import _tokens

        resultado = ResultadoBusca(fonte=self.fonte)
        if self._controle is None:
            return resultado.falhar(
                "número de controle PNCP não reconhecido — use o formato "
                "00000000000000-1-000000/2026 ou o link do edital")
        cnpj, ano, seq = self._controle
        caminho = f"/orgaos/{cnpj}/compras/{ano}/{seq}"
        contratacao = self._json(f"{BASE}{caminho}", resultado)
        if contratacao is None:
            return resultado
        itens = self._json(
            f"{BASE_PNCP}{caminho}/itens?pagina=1&tamanhoPagina={PAGINA_ITENS}",
            resultado)
        if itens is None:
            return resultado

        termos = _tokens(consulta.descricao)
        pontuados = sorted(
            ((len(termos & _tokens(str(i.get("descricao") or ""))), i)
             for i in itens if i.get("temResultado")),
            key=lambda par: (-par[0], int(par[1].get("numeroItem") or 0)))
        candidatos = [i for comuns, i in pontuados if comuns][
            :MAX_ITENS_COM_RESULTADO]
        if not candidatos:
            return resultado.registrar(
                "a contratação informada não tem item homologado com termos "
                "da descrição pesquisada")

        vistos: set[tuple] = set()
        for item in candidatos:
            numero = item.get("numeroItem")
            linhas = self._json(
                f"{BASE_PNCP}{caminho}/itens/{numero}/resultados", resultado)
            if linhas is None:
                return resultado
            for linha in linhas:
                referencia = _referencia_do_resultado(contratacao, item, linha)
                if referencia is None:
                    resultado.registrar(
                        f"item {numero}: resultado sem preço conferível "
                        "(cancelado, moeda estrangeira ou total incoerente)")
                    continue
                # cota principal e cota reservada: mesma descrição, mesmo
                # fornecedor e mesmo preço são UMA observação de mercado
                chave = (" ".join(referencia.descricao_original.upper().split()),
                         referencia.ni_fornecedor,
                         referencia.valor_unitario_original)
                if chave in vistos:
                    resultado.registrar(
                        f"item {numero}: mesma descrição, fornecedor e preço "
                        "de outro item da contratação (cota) — contado uma vez")
                    continue
                vistos.add(chave)
                resultado.referencias.append(referencia)
        return resultado


def _referencia_do_resultado(contratacao: dict, item: dict,
                             linha: dict) -> Referencia | None:
    """Resultado homologado do item → `Referencia` HOMOLOGADA, ou `None`."""
    if linha.get("dataCancelamento") or linha.get("moedaEstrangeira"):
        return None
    if "cancel" in str(linha.get("situacaoCompraItemResultadoNome") or "").lower():
        return None
    unitario = para_decimal(linha.get("valorUnitarioHomologado"))
    quantidade = para_decimal(linha.get("quantidadeHomologada"))
    total = para_decimal(linha.get("valorTotalHomologado"))
    if unitario is None or unitario <= 0 or not _total_coerente(
            unitario, quantidade, total):
        return None
    controle = str(contratacao.get("numeroControlePNCP") or "")
    unidade_orgao = contratacao.get("unidadeOrgao") or {}
    numero = item.get("numeroItem")
    bruto = {
        "numeroControlePNCP": controle,
        "linkSistemaOrigem": contratacao.get("linkSistemaOrigem"),
        "idCompraOrigem": _id_compra_de_origem(
            contratacao.get("linkSistemaOrigem")),
        "item": {k: item.get(k) for k in (
            "numeroItem", "descricao", "unidadeMedida", "quantidade",
            "materialOuServico", "catalogoCodigoItem",
            "criterioJulgamentoNome", "situacaoCompraItemNome")},
        "resultado": linha,
    }
    return Referencia(
        fonte=FONTE_PNCP,
        id_externo=f"{controle}#{numero}#{linha.get('sequencialResultado') or 1}",
        bruto=bruto,
        descricao_original=str(item.get("descricao") or ""),
        unidade_original=str(item.get("unidadeMedida") or "").strip() or None,
        quantidade_original=quantidade,
        valor_unitario_original=unitario,
        codigo_catalogo=str(item.get("catalogoCodigoItem") or "") or None,
        orgao=(contratacao.get("orgaoEntidade") or {}).get("razaoSocial"),
        uf=unidade_orgao.get("ufSigla"),
        municipio=unidade_orgao.get("municipioNome"),
        fornecedor=linha.get("nomeRazaoSocialFornecedor"),
        ni_fornecedor=str(linha.get("niFornecedor") or "") or None,
        criterio_julgamento=item.get("criterioJulgamentoNome"),
        modalidade=contratacao.get("modalidadeNome"),
        data_compra=para_data(linha.get("dataResultado")),
        data_resultado=para_data(linha.get("dataResultado")),
        referencia_externa=controle or None,
        # a natureza vem do CAMPO lido (`valorUnitarioHomologado`),
        # conferido contra quantidade e total — não do nome do endpoint
        natureza_valor=NaturezaValor.HOMOLOGADO,
    )


def url_de_verificacao(bruto: dict) -> str | None:
    """Link público do edital no PNCP para a referência importada."""
    controle = controle_da_entrada(str(bruto.get("numeroControlePNCP") or ""))
    if controle is None:
        return None
    cnpj, ano, seq = controle
    return URL_CONTRATACAO.format(cnpj=cnpj, ano=ano, sequencial=seq)
