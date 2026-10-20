"""
Portal de Compras Públicas — adaptador DESCONECTADO.

A documentação pública fala de uma API de parceiros para processos
finalizados, com `PublicKey` concedida mediante solicitação e termo
(https://bibliotecapcp.zendesk.com/hc/pt-br/articles/4593611793690). Em
20/10/2026 não temos chave, nem a documentação dos recursos de itens e
resultados, nem o termo de reúso. Por isso este arquivo NÃO tem endpoint,
header nem payload: escrevê-los seria inventar.

O adaptador existe para ocupar o lugar no contrato (`FontePesquisaPreco`)
e para que a tela e o relatório já saibam dizer "fonte aguardando
credenciamento" em vez de não dizer nada. Ele nunca abre conexão.
Integrar de verdade só depois de: chave + documentação + exemplo real de
resposta com valor unitário homologado + `Licenca.APROVADA` em
`fontes_externas`.
"""

from __future__ import annotations

from .fontes import Consulta, FontePesquisaPreco, ResultadoBusca
from .modelo import Fonte

FONTE_PCP = Fonte(id="pcp", nome="Portal de Compras Públicas", tipo="outro")
MOTIVO_BLOQUEIO = ("Portal de Compras Públicas aguardando credenciamento "
                   "(PublicKey, documentação e termo de uso) — nenhuma "
                   "consulta feita")


class PortalComprasPublicasAdapter(FontePesquisaPreco):
    fonte = FONTE_PCP

    def pesquisar(self, consulta: Consulta) -> ResultadoBusca:
        return ResultadoBusca(fonte=self.fonte).falhar(MOTIVO_BLOQUEIO)

    def healthcheck(self) -> bool:
        return False
