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
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from .fontes import (Capacidade, Consulta, FontePesquisaPreco,
                     ResultadoBusca)
from .modelo import Fonte

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
