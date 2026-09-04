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

    @property
    def tem_codigo(self) -> bool:
        return bool(self.codigo_catalogo)


@dataclass
class ResultadoBusca:
    """
    O que a fonte devolveu — inclusive quando não devolveu nada.

    `ocorrencias` é o que permite dizer ao usuário "o PNCP não respondeu
    agora; continuamos nas demais fontes" em vez de mostrar stack trace
    (§57), e é o que vai para a observabilidade (§38).
    """

    fonte: Fonte
    referencias: list[Referencia] = field(default_factory=list)
    ocorrencias: list[str] = field(default_factory=list)
    chamadas: int = 0
    total_disponivel: int | None = None

    @property
    def houve_falha(self) -> bool:
        return bool(self.ocorrencias)

    def registrar(self, ocorrencia: str) -> "ResultadoBusca":
        self.ocorrencias.append(ocorrencia)
        _log.info("pesquisa de precos: %s", ocorrencia)
        return self


class FontePesquisaPreco:
    """
    Contrato que todo adapter implementa.

    Deliberadamente pequeno: buscar, checar saúde e se identificar. O
    enriquecimento é opcional porque nem toda fonte o oferece.
    """

    fonte: Fonte

    def pesquisar(self, consulta: Consulta) -> ResultadoBusca:
        raise NotImplementedError

    def healthcheck(self) -> bool:
        raise NotImplementedError

    def metadados_fonte(self) -> dict:
        return {"id": self.fonte.id, "nome": self.fonte.nome,
                "tipo": self.fonte.tipo}
