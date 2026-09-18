"""
AIProviderGateway — a ÚNICA parte do sistema que sabe que um gateway existe.

O aplicativo fala com este módulo. Este módulo fala com o provider, ou com
um gateway compatível com a API da OpenAI (OmniRoute, LiteLLM, o que for).
Trocar um pelo outro é mexer aqui, e em nenhum outro lugar.

    Aplicação  →  ai_gateway  →  roteamento (política)
                      ↓
       [hoje]   provider direto: OpenAI · Gemini · OpenRouter
       [depois] gateway, por `base_url`

POR QUE A CAMADA EXISTE ANTES DO GATEWAY

Porque ela vale sozinha. Hoje a escolha de modelo está espalhada entre
`config.py`, `llm.py` e o painel do administrador, e nenhum dos três sabe
que tarefa está sendo executada — gerar um edital e classificar um achado
percorrem o mesmo caminho. Com a camada no lugar, a decisão passa a ter
UM endereço, e um gateway futuro vira uma variável de ambiente em vez de
uma refatoração.

O QUE ESTE MÓDULO GARANTE

**Com tudo desligado — o padrão — o comportamento é idêntico ao de
antes.** Mesmos motores, mesma ordem, mesmos modelos, mesma `base_url`
(nenhuma). Não é promessa: é o que `tests/test_ai_gateway.py` mede.

Reversão de emergência: `OMNIROUTE_ENABLED=false`. Uma variável, sem
deploy, sem migração.
"""

from __future__ import annotations

import os

from . import roteamento

# ---------------------------------------------------------------------------
# AS CHAVES DE LIGAR/DESLIGAR
#
# Lidas do AMBIENTE, e não de `config_app`, por um motivo específico: a
# tabela de configuração é editável pelo painel do administrador, e uma
# política de roteamento que um usuário autenticado consegue mudar pela
# tela não é política — é sugestão. O seu próprio requisito diz que
# resposta de usuário nunca pode alterar provider ou política.
#
# Todas nascem DESLIGADAS. Ligar é ato deliberado, feito no ambiente.
# ---------------------------------------------------------------------------
VAR_GATEWAY = "OMNIROUTE_ENABLED"
VAR_BASE_URL = "OMNIROUTE_BASE_URL"
VAR_ROTEAMENTO = "OMNIROUTE_ROUTING_ENABLED"

# Só estes motores falam a API da OpenAI. O Gemini tem SDK próprio e não
# atravessa `base_url` — mandar o `base_url` do gateway para ele não faria
# nada de errado, faria nada, que é pior: pareceria roteado e não estaria.
MOTORES_COMPATIVEIS = ("openai", "openrouter")


def _ligado(variavel: str) -> bool:
    valor = (os.environ.get(variavel) or "").strip().lower()
    return valor in ("1", "true", "sim", "on", "yes")


def gateway_ligado() -> bool:
    """O gateway só conta como ligado se houver PARA ONDE apontar."""
    return _ligado(VAR_GATEWAY) and bool(base_url_configurada())


def roteamento_ligado() -> bool:
    return _ligado(VAR_ROTEAMENTO)


def base_url_configurada() -> str:
    return (os.environ.get(VAR_BASE_URL) or "").strip()


def base_url_para(motor: str) -> str | None:
    """
    A `base_url` que o cliente daquele motor deve usar — ou `None`.

    `None` significa "fale direto com o provider", que é o caminho de
    hoje e o caminho de volta. O SDK da OpenAI trata `base_url=None`
    como o padrão dele, então esta função é segura de chamar sempre.
    """
    if not gateway_ligado() or motor not in MOTORES_COMPATIVEIS:
        return None
    return base_url_configurada()


def motores_para(rotulo: str,
                 disponiveis: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """
    A ordem de motores para esta tarefa.

    Com o roteamento desligado, devolve `disponiveis` intacto — a ordem
    que o operador configurou, que é a que o sistema sempre usou.

    Com ele ligado, o grupo da tarefa estreita a lista: uma geração de
    edital deixa de poder cair para um motor não homologado só porque o
    principal ficou indisponível.
    """
    return roteamento.motores_permitidos(rotulo, disponiveis,
                                         restringir=roteamento_ligado())


def telemetria(rotulo: str, motor: str) -> dict[str, object]:
    """
    Os campos de roteamento de uma requisição — sem conteúdo nenhum.

    Nada de prompt, nada de resposta, nada de chave. Só o suficiente para
    responder "que modelo atendeu esta tarefa, e por qual política".
    """
    return {
        **roteamento.descrever(rotulo),
        "provider": motor,
        "gateway": "omniroute" if gateway_ligado() else "direto",
        "routing_enabled": roteamento_ligado(),
    }


def estado() -> dict[str, object]:
    """
    Diagnóstico para o painel e para o registro de sessão.

    `base_url` aparece porque é endereço, não segredo. Chave de API não
    aparece aqui nem em lugar nenhum deste módulo.
    """
    return {
        "gateway_ligado": gateway_ligado(),
        "base_url": base_url_configurada() or "(nenhuma)",
        "roteamento_ligado": roteamento_ligado(),
        "motores_compativeis": list(MOTORES_COMPATIVEIS),
    }
