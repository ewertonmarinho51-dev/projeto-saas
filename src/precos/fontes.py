"""
Interface comum das fontes de pesquisa de preço.

Cada fonte oficial tem contrato próprio; nada disso pode vazar para o
motor. O que o motor conhece é `Consulta` (o que se procura) e
`Referencia` (o que se achou) — o resto é problema do adapter.

A resiliência do §37 mora aqui: falha de uma fonte NÃO derruba a
pesquisa. Um adapter que não responde devolve `ResultadoBusca` com a
ocorrência registrada, e o motor segue com as demais fontes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from .modelo import Fonte, Referencia

_log = logging.getLogger(__name__)

# A API do Compras.gov recusa página menor que 10 ou maior que 500 — não
# é preferência nossa, é o contrato dela (verificado contra o servidor).
PAGINA_MINIMA = 10
PAGINA_MAXIMA = 500


class ErroFonte(Exception):
    """Falha ao consultar uma fonte. Nunca sobe para a tela crua."""


@dataclass
class Consulta:
    """
    O que se procura. Espelha o item do processo, não a API.

    `codigo_catalogo` é OPCIONAL por decisão de produto: o módulo aceita
    CATMAT/CATSER e o usa quando pertinente, mas jamais o exige. Sem ele
    o adapter recorre ao caminho por descrição.
    """

    descricao: str
    unidade: str | None = None
    quantidade: float | None = None

    codigo_catalogo: str | None = None
    tipo_catalogo: str | None = None        # 'CATMAT' | 'CATSER'
    codigo_classe: str | None = None
    material_ou_servico: str = "M"          # 'M' | 'S'

    uf: str | None = None
    codigo_municipio: str | None = None
    data_inicial: date | None = None
    data_final: date | None = None

    limite: int = 100

    # Sinônimos propostos pela camada semântica (§8), já validados pelo
    # servidor. Eles só AMPLIAM o conjunto de candidatos — quem ranqueia
    # e quem monta a cesta continua sendo o motor determinístico. Um
    # termo ruim custa candidato irrelevante, nunca preço errado.
    termos_alternativos: tuple[str, ...] = ()

    @property
    def tem_codigo(self) -> bool:
        return bool(self.codigo_catalogo)


class Capacidade(str, Enum):
    """
    O que uma fonte é capaz de entregar.

    Sem isto o motor contava adapters: "duas fontes responderam, logo a
    pesquisa foi tecnicamente bem-sucedida". Mas responder e fornecer
    preço são coisas diferentes, e a diferença muda o que se diz ao
    servidor. Se a única fonte de PREÇO caiu e sobrou uma fonte de
    EVIDÊNCIA, a pesquisa não teve "amostra insuficiente" — ela não
    aconteceu.
    """

    PRECO = "preco"          # produz referência utilizável na cesta
    EVIDENCIA = "evidencia"  # produz contexto, link, comprovação


class Desfecho(str, Enum):
    """
    Como terminou a consulta a UMA fonte.

    Quatro estados, e cada um pede uma frase diferente na tela:

    * `COM_PRECOS` — veio material que sustenta estimativa;
    * `SEM_RESULTADO` — a fonte respondeu e não tinha nada. É informação
      sobre o MERCADO: repetir amanhã provavelmente dá o mesmo;
    * `SO_EVIDENCIA` — vieram registros, nenhum utilizável como preço
      (natureza não comparável, ou fonte que só enriquece);
    * `FALHA` — não respondeu, ou respondeu erro. É informação sobre a
      INFRAESTRUTURA: repetir mais tarde pode mudar tudo.

    Confundir os três primeiros com o último foi o defeito que este
    enum existe para tornar impossível.
    """

    COM_PRECOS = "success_with_prices"
    SEM_RESULTADO = "success_empty"
    SO_EVIDENCIA = "evidence_only"
    FALHA = "failure"


@dataclass
class ResultadoBusca:
    """
    O que a fonte devolveu — inclusive quando não devolveu nada.

    `ocorrencias` é o que permite dizer ao usuário "o PNCP não respondeu
    agora; continuamos nas demais fontes" em vez de mostrar stack trace
    (§57), e é o que vai para a observabilidade (§38).

    `falha` é campo separado por uma razão que a auditoria expôs:
    `houve_falha` era `bool(ocorrencias)`, e ocorrência serve também para
    recado que não é falha nenhuma. O PNCP registrava "sou fonte de
    enriquecimento, não de busca" e aparecia como fonte quebrada;
    enquanto isso um HTTP 503 do Compras.gov — tratado dentro do adapter,
    sem exceção — não contava como falha em lugar nenhum. Agora falha é
    um campo, escrito só por quem realmente falhou.
    """

    fonte: Fonte
    referencias: list[Referencia] = field(default_factory=list)
    ocorrencias: list[str] = field(default_factory=list)
    falha: str | None = None
    chamadas: int = 0
    total_disponivel: int | None = None

    @property
    def houve_falha(self) -> bool:
        """Falha TÉCNICA. Recado informativo não conta."""
        return self.falha is not None

    @property
    def com_preco(self) -> list[Referencia]:
        """As referências que sustentam a estimativa sozinhas."""
        return [r for r in self.referencias if r.serve_de_preco]

    @property
    def desfecho(self) -> "Desfecho":
        if self.falha is not None:
            return Desfecho.FALHA
        if self.com_preco:
            return Desfecho.COM_PRECOS
        if self.referencias:
            # Veio material — só não serve de preço. Distinguir isto de
            # "não veio nada" importa: aqui há o que mostrar ao revisor.
            return Desfecho.SO_EVIDENCIA
        return Desfecho.SEM_RESULTADO

    def registrar(self, ocorrencia: str) -> "ResultadoBusca":
        """Recado ao servidor. NÃO marca a fonte como falha."""
        self.ocorrencias.append(ocorrencia)
        _log.info("pesquisa de precos: %s", ocorrencia)
        return self

    def falhar(self, motivo: str) -> "ResultadoBusca":
        """
        A fonte não respondeu, ou respondeu erro.

        A primeira falha é a que fica: as seguintes costumam ser
        consequência dela, e a original é a que explica.
        """
        if self.falha is None:
            self.falha = motivo
        return self.registrar(motivo)


class FontePesquisaPreco:
    """
    Contrato que todo adapter implementa.

    Deliberadamente pequeno: buscar, checar saúde e se identificar. O
    enriquecimento é opcional porque nem toda fonte o oferece.

    `capacidades` é declarado pela CLASSE, não deduzido do resultado. Se
    fosse deduzido, uma fonte de preço que voltasse vazia por falha seria
    reclassificada como fonte de evidência e a falha desapareceria — que
    é justamente o apagamento que este modelo existe para impedir.
    """

    fonte: Fonte
    capacidades: frozenset = frozenset({Capacidade.PRECO})

    def pesquisar(self, consulta: Consulta) -> ResultadoBusca:
        raise NotImplementedError

    def healthcheck(self) -> bool:
        raise NotImplementedError

    def metadados_fonte(self) -> dict:
        return {"id": self.fonte.id, "nome": self.fonte.nome,
                "tipo": self.fonte.tipo,
                "capacidades": sorted(c.value for c in self.capacidades)}


def fornece_preco(fonte) -> bool:
    """
    Esta fonte é candidata a sustentar a estimativa?

    Aceita qualquer objeto para não acoplar o motor à hierarquia de
    classes — um dublê de teste declara `capacidades` e pronto. Sem a
    declaração o padrão é PREÇO: adapter antigo continua contando, e a
    omissão nunca faz uma fonte de preço sumir da conta de falhas.
    """
    return Capacidade.PRECO in getattr(
        fonte, "capacidades", frozenset({Capacidade.PRECO}))
