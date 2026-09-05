"""
Pesquisa de preços — domínio e fontes oficiais.

Fases 1 a 3 do módulo: modelo normalizado, normalização de unidade,
adapters das fontes, matching explicável, estatística e persistência.
Ainda NÃO há UI, integração com o processo, relatórios nem camada
semântica — cada uma tem fase própria.

O que este pacote garante desde já, e que é a razão de ele existir antes
das outras fases:

- **preço é `Decimal`**, e o payload bruto da fonte é preservado ao lado
  do normalizado;
- **unidade só é convertida com fator explícito da fonte** — sem prova,
  a referência chega ao revisor na unidade original, com o motivo;
- **CATMAT/CATSER é aceito e usado quando pertinente, nunca exigido**;
- **falha de uma fonte não derruba a pesquisa** — vira ocorrência
  registrada.
"""

from .compras_gov import ComprasGovAdapter
from .estados import (EstadoItem, EstadoPesquisa, TransicaoInvalida,
                      estado_derivado, exige_nova_revisao, transitar_item,
                      transitar_pesquisa)
from .estatistica import (Anomalia, Cesta, Estatisticas, Estimativa, calcular,
                          detectar_anomalias, estimar, mediana,
                          selecionar_cesta)
from .fontes import (Capacidade, Consulta, Desfecho, ErroFonte,
                     FontePesquisaPreco, ResultadoBusca, fornece_preco)
from .matching import (Comparabilidade, Fator, comparar,
                       ordenar_por_comparabilidade)
from .modelo import (NATUREZAS_COMPARAVEIS, Fonte, NaturezaValor,
                     Referencia, StatusReferencia, deduplicar,
                     para_decimal)
from .perfil import IN_65_2021, LEI_14133, PerfilNormativo
from .pncp import PNCPAdapter
from .unidades import canonizar, comparavel, fator_de_conversao, normalizar

__all__ = [
    "ComprasGovAdapter", "PNCPAdapter",
    "Consulta", "ResultadoBusca", "FontePesquisaPreco", "ErroFonte",
    "Capacidade", "Desfecho", "fornece_preco",
    "Referencia", "Fonte", "StatusReferencia", "deduplicar", "para_decimal",
    "NaturezaValor", "NATUREZAS_COMPARAVEIS",
    "canonizar", "fator_de_conversao", "normalizar", "comparavel",
    "Comparabilidade", "Fator", "comparar", "ordenar_por_comparabilidade",
    "Estatisticas", "Estimativa", "Cesta", "Anomalia", "calcular", "mediana",
    "detectar_anomalias", "selecionar_cesta", "estimar",
    "PerfilNormativo", "LEI_14133", "IN_65_2021",
    "EstadoPesquisa", "EstadoItem", "TransicaoInvalida", "transitar_pesquisa",
    "transitar_item", "estado_derivado", "exige_nova_revisao",
]

# `repositorio` NÃO é reexportado aqui de propósito: ele importa `src.db`,
# que importa Streamlit. Como está, `import src.precos` carrega o domínio
# puro — adapters, normalização, matching e estatística rodam sem app.
# Quem precisa de persistência escreve `from src.precos import repositorio`.


def fontes_padrao() -> list[FontePesquisaPreco]:
    """
    Fontes na ordem de prioridade normativa.

    Sistema oficial primeiro (§12): o Compras.gov traz preço praticado e
    contratação similar; o PNCP entra depois, para comprovação.
    """
    return [ComprasGovAdapter(), PNCPAdapter()]
