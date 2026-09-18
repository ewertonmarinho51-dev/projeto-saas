"""
Resolução de módulo: flag global × prefeitura × secretaria.

TRÊS NÍVEIS, E NENHUM DELES É UM SISTEMA NOVO

O projeto já tem feature flags em `config_app` (`db.flag_ativa`). Elas
respondem "este módulo EXISTE tecnicamente nesta versão do produto" — é
a chave do desenvolvedor, e foi assim que `pesquisa_precos`,
`demand_consolidation` e `legal_opinion_correction` entraram.

O que faltava é a camada comercial e institucional:

    flag global     → o módulo existe no produto
    tenant_modulos  → esta prefeitura contratou/habilitou
    secretaria_modulos → esta secretaria usa (ou dispensou)

A conjunção é obrigatória e a ordem importa: nível de baixo NUNCA abre o
que o de cima fechou. Uma secretaria não pode habilitar módulo que a
prefeitura não tem, e nenhuma prefeitura pode habilitar módulo que o
produto não entrega.

Este módulo é PURO: recebe os estados já lidos e devolve a decisão. Sem
banco, sem `st.session_state`, sem rede. Quem lê o banco é `db.py`; quem
decide é aqui, e por isso a decisão é testável sem nenhum mock.
"""

from __future__ import annotations

# Os três estados possíveis de `secretaria_modulos.estado`.
HERDAR = "HERDAR"
HABILITADO = "HABILITADO"
DESABILITADO = "DESABILITADO"

ESTADOS = (HERDAR, HABILITADO, DESABILITADO)


def resolver(*, flag_global: bool, no_tenant: bool,
             na_secretaria: str = HERDAR) -> bool:
    """
    A resposta final: este módulo está disponível AQUI?

    A tabela-verdade do escopo, inteira:

        tenant desligado                        → desligado, sempre
        tenant ligado + secretaria HERDAR       → ligado
        tenant ligado + secretaria HABILITADO   → ligado
        tenant ligado + secretaria DESABILITADO → desligado

    E o nível que o escopo não menciona porque já existia: com a flag
    global desligada, nada disso é consultado. Módulo que o produto não
    entrega não fica disponível porque uma prefeitura marcou uma caixa —
    seria vender o que não existe.

    `na_secretaria` desconhecido cai em HERDAR. Um estado inválido vindo
    do banco não pode ABRIR acesso; herdar é a escolha conservadora
    porque ela devolve a decisão para o nível de cima.
    """
    if not flag_global:
        return False
    if not no_tenant:
        return False
    if na_secretaria == DESABILITADO:
        return False
    return True


def explicar(*, flag_global: bool, no_tenant: bool,
             na_secretaria: str = HERDAR) -> str:
    """
    Por que o módulo está indisponível — em uma frase, para a tela.

    Existe porque "o menu não mostra" é a pior forma de indisponibilidade:
    o servidor não sabe se o sistema não tem, se a prefeitura não
    contratou, ou se a secretaria dele dispensou. Cada resposta leva a
    uma ação diferente, e só uma delas é abrir chamado.
    """
    if not flag_global:
        return "Este módulo não está disponível nesta versão do sistema."
    if not no_tenant:
        return ("Este módulo não está habilitado para a sua prefeitura. "
                "Fale com o administrador municipal.")
    if na_secretaria == DESABILITADO:
        return ("Este módulo foi desabilitado para a sua secretaria pelo "
                "administrador municipal.")
    return ""


def estado_valido(estado: str | None) -> str:
    """Normaliza o que veio do banco. Desconhecido vira HERDAR."""
    valor = (estado or "").strip().upper()
    return valor if valor in ESTADOS else HERDAR


def pode_habilitar_na_secretaria(*, no_tenant: bool, estado: str) -> bool:
    """
    A regra que o CHECK do banco não consegue expressar.

    Uma secretaria NUNCA habilita módulo proibido no tenant. Sem esta
    função, a tela deixaria o administrador marcar HABILITADO numa
    secretaria de um módulo que a prefeitura não tem — e o registro
    ficaria no banco parecendo uma concessão, até alguém ligar o módulo
    no tenant e descobrir que três secretarias já estavam "habilitadas"
    sem ninguém ter decidido isso.
    """
    return no_tenant or estado != HABILITADO
