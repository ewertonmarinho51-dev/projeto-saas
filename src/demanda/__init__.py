"""
Consolidação de Documentos de Formalização de Demanda.

Recebe os DFDs que cada secretaria envia, extrai os itens, soma o que é
comprovadamente o mesmo item e entrega uma tabela única — com a
quantidade de cada secretaria preservada ao lado do total, e cada número
rastreável até o arquivo de onde veio.

O nome do pacote é `demanda`, e não `solicitacoes`, porque é assim que
os documentos reais se chamam: `DOCUMENTO DE FORMALIZAÇÃO DE DEMANDA`.
"""

from . import consolidacao, extracao  # noqa: F401

__all__ = ["extracao", "consolidacao"]
