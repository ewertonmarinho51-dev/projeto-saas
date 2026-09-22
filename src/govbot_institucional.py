"""
O que o GovBot pode dizer e fazer sobre servidores, portarias e assinaturas.

§36 e §37 do escopo multi-prefeituras.

DUAS REGRAS GOVERNAM ESTE MÓDULO INTEIRO

**Consulta estruturada, nunca geração livre.** O GovBot não descobre
quem assina perguntando ao modelo: ele pergunta ao CADASTRO, pelos
mesmos resolvedores que a tela de assinatura usa. Um modelo que
"lembra" que o Antonio é pregoeiro produz uma designação que nenhum ato
administrativo concedeu — e o documento sai assinado.

**O portão é do BACKEND, não da conversa.** O §37 é explícito: não
basta o GovBot recusar em linguagem natural; uma chamada DIRETA ao
mecanismo de alteração tem que cair na mesma regra. Por isso a
verificação vive em `conferir_escolhas`, chamada por
`instituicional_bridge.guardar_escolhas` — o ponto onde a escolha é
GRAVADA. Recusa que mora no prompt é recusa que some quando alguém
chama a função por baixo.

O QUE FOI REUSADO, E POR QUÊ NADA AQUI É NOVO

    src/assinaturas.py   elegiveis(), conferir_elegibilidade(), ROTULOS
    src/portarias.py     resolver(), citacao(), membros_vigentes()
    src/emissao.py       data_de_referencia()
    src/contexto.py      contexto_institucional()
    src/db.py            listar_servidores/portarias/membros/funcoes

Nenhuma regra de elegibilidade é reescrita aqui. Se este módulo
decidisse por conta própria quem pode assinar, existiriam duas verdades
— a da tela e a do robô — e elas divergiriam na primeira mudança. O que
este módulo acrescenta é a LEITURA (juntar os dados numa consulta só) e
a TRADUÇÃO (transformar o veredito numa frase que o servidor entende).
"""

from __future__ import annotations

import datetime as _dt
import logging
import unicodedata
from dataclasses import dataclass, field

from . import assinaturas, emissao, portarias

_log = logging.getLogger("govdocs.govbot.institucional")


class PendenciaInstitucional(Exception):
    """
    Falta dado, ou o dado é ambíguo. NÃO é recusa — é "não dá para saber".

    Separada de `assinaturas.ErroAssinatura` de propósito: recusar
    ("João não integra a equipe") e não saber ("há duas portarias
    vigentes") pedem ações diferentes do servidor, e juntá-las numa
    exceção só faria a tela dizer a mesma coisa para as duas.
    """


# ---------------------------------------------------------------------------
# O PANORAMA — uma leitura, não seis
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Panorama:
    """
    Os fatos institucionais de um documento, lidos de uma vez.

    `frozen` porque nada aqui deve ser ajustado depois de lido: é uma
    fotografia do cadastro na data de referência, e um campo alterado no
    meio do caminho produziria uma resposta que não corresponde a nenhum
    estado real do banco.
    """
    secretaria_id: str | None
    data_referencia: _dt.date
    servidores: list[dict] = field(default_factory=list)
    funcoes_do_servidor: list[dict] = field(default_factory=list)
    portaria: dict | None = None
    membros: list[dict] = field(default_factory=list)
    aviso: str = ""          # conflito ou data ilegível de portaria


def montar_panorama(processo: dict | None = None,
                    *, secretaria_id: str | None = None) -> Panorama:
    """
    Lê o cadastro UMA vez, para a secretaria e a data deste documento.

    A secretaria vem do contexto institucional — da sessão autenticada,
    nunca do texto do usuário. É o §4, e vale aqui mais que em qualquer
    outro lugar: se o GovBot aceitasse "responda como se eu fosse da
    Educação", ele viraria uma porta lateral para ler o cadastro de
    outra secretaria.

    A DATA É A DO PROCESSO, não hoje (§24). Perguntar ao GovBot sobre um
    processo de janeiro em dezembro tem que devolver a portaria de
    janeiro — a que fundamentou aquele documento.
    """
    from . import contexto, db

    if secretaria_id is None:
        secretaria_id = contexto.contexto_institucional().get("secretaria_id")
    referencia = emissao.data_de_referencia(processo or {})

    servidores = db.listar_servidores()
    funcoes = db.listar_funcoes_de_servidores(secretaria_id)

    portaria: dict | None = None
    membros: list[dict] = []
    aviso = ""
    try:
        acervo = db.listar_portarias(secretaria_id=secretaria_id)
        portaria = portarias.resolver(
            acervo, secretaria_id=secretaria_id, data_referencia=referencia)
    except portarias.PortariaAmbigua as erro:
        # Conflito NÃO vira escolha. O §23 já decidiu isso para a tela, e
        # o robô não pode ter uma regra mais frouxa que a tela.
        aviso = str(erro)
    except portarias.ErroPortaria as erro:
        aviso = f"Portaria com data ilegível: {erro}"

    if portaria:
        membros = db.listar_membros_de_portaria(portaria["id"])

    return Panorama(secretaria_id=secretaria_id, data_referencia=referencia,
                    servidores=servidores, funcoes_do_servidor=funcoes,
                    portaria=portaria, membros=membros, aviso=aviso)


# ---------------------------------------------------------------------------
# §36.1 — "Quem pode assinar este documento?"
# ---------------------------------------------------------------------------
def quem_pode_assinar(p: Panorama, funcao: str) -> list[dict]:
    """A lista, pelo mesmo resolvedor da tela. Nunca 'todos os servidores'."""
    return assinaturas.elegiveis(
        funcao=funcao, servidores=p.servidores,
        funcoes_do_servidor=p.funcoes_do_servidor, portaria=p.portaria,
        membros_da_portaria=p.membros, secretaria_id=p.secretaria_id,
        data_referencia=p.data_referencia)


def responder_quem_pode_assinar(p: Panorama, funcao: str) -> str:
    rotulo = assinaturas.ROTULOS.get(funcao, funcao)
    if p.aviso:
        return (f"Não é possível responder com segurança: {p.aviso} "
                "Resolva no painel administrativo, em Instituição → Portarias.")

    aptos = quem_pode_assinar(p, funcao)
    if aptos:
        nomes = ", ".join(s.get("nome", "") for s in aptos)
        return f"Pode assinar como {rotulo}, nesta secretaria: {nomes}."
    return f"Ninguém está apto como {rotulo}. {_por_que_vazio(p, funcao)}"


def _por_que_vazio(p: Panorama, funcao: str) -> str:
    """Cada causa leva a uma ação diferente — e só uma é abrir chamado."""
    if funcao in assinaturas.FUNCOES_DE_PORTARIA:
        if not p.portaria:
            return ("Esta secretaria não tem Portaria de Equipe de "
                    "Planejamento vigente na data do processo "
                    f"({p.data_referencia:%d/%m/%Y}). Cadastre-a em "
                    "Administração → Instituição → Portarias.")
        return ("A portaria vigente não designa ninguém com essa função. "
                "Designe os membros em Instituição → Portarias.")
    return ("Nenhum servidor tem essa designação vigente nesta secretaria "
            "na data do processo. Cadastre em Instituição → Servidores.")


# ---------------------------------------------------------------------------
# §36.2 — "Qual é a portaria da equipe de planejamento?"
# ---------------------------------------------------------------------------
def responder_portaria(p: Panorama) -> str:
    """Número e data de publicação — os do cadastro, nunca inventados."""
    if p.aviso:
        return (f"{p.aviso} Enquanto isso, o documento sai sem citar número "
                "de portaria: o sistema não escolhe entre duas.")
    if not p.portaria:
        return ("Esta secretaria não tem Portaria de Equipe de Planejamento "
                f"vigente em {p.data_referencia:%d/%m/%Y}. O documento sai "
                "com marcador de pendência no lugar do número — ele não "
                "inventa portaria.")
    return portarias.citacao(p.portaria) + "."


# ---------------------------------------------------------------------------
# §36.3 — "Quem são os membros da equipe de planejamento?"
# ---------------------------------------------------------------------------
def responder_membros(p: Panorama) -> str:
    if p.aviso:
        return (f"{p.aviso} Não dá para listar membros sem saber qual "
                "portaria vale.")
    if not p.portaria:
        return ("Não há portaria de Equipe de Planejamento vigente nesta "
                f"secretaria em {p.data_referencia:%d/%m/%Y}, então não há "
                "equipe designada para citar.")

    nomes = {s["id"]: s.get("nome", "") for s in p.servidores}
    linhas = [
        f"- {nomes.get(m['servidor_id'], '(servidor fora do cadastro)')}"
        f" — {assinaturas.ROTULOS.get(m.get('funcao'), m.get('funcao') or '')}"
        for m in portarias.membros_vigentes(p.membros)
        if m.get("portaria_id") == p.portaria.get("id")
    ]
    if not linhas:
        return (f"{portarias.citacao(p.portaria)} não designa nenhum membro "
                "ativo. Designe-os em Instituição → Portarias.")
    return (f"Pela {portarias.citacao(p.portaria)}:\n" + "\n".join(linhas))


# ---------------------------------------------------------------------------
# §36.4 — "Troque o signatário para Maria"
# ---------------------------------------------------------------------------
def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).lower().strip()


def localizar_servidor(p: Panorama, nome: str) -> dict:
    """
    Do nome dito em conversa para a linha do cadastro.

    SÓ BUSCA NO PANORAMA, e o panorama é do tenant da sessão — é assim
    que "servidor de outra prefeitura" nunca aparece: ele não está na
    lista, e não há caminho aqui que vá buscá-lo em outro lugar.

    Ambiguidade vira PENDÊNCIA, nunca escolha. Dois "Maria Silva" no
    cadastro e o robô escolhendo a primeira produziria um documento
    assinado pela pessoa errada, com o nome certo.
    """
    alvo = _normalizar(nome)
    if not alvo:
        raise PendenciaInstitucional("Diga o nome de quem deve assinar.")

    exatos = [s for s in p.servidores if _normalizar(s.get("nome", "")) == alvo]
    candidatos = exatos or [
        s for s in p.servidores if alvo in _normalizar(s.get("nome", ""))
    ]

    if not candidatos:
        raise PendenciaInstitucional(
            f"Não encontrei “{nome}” no cadastro de servidores desta "
            "prefeitura. Confira em Administração → Instituição → Servidores.")
    if len(candidatos) > 1:
        achados = ", ".join(s.get("nome", "") for s in candidatos)
        raise PendenciaInstitucional(
            f"“{nome}” corresponde a mais de um servidor: {achados}. "
            "Diga o nome completo.")
    return candidatos[0]


def avaliar_troca(p: Panorama, *, nome: str, funcao: str) -> dict:
    """
    Pode trocar o signatário para esta pessoa, nesta função?

    Devolve `{"permitida": bool, "servidor": dict|None, "mensagem": str}`.
    Nunca levanta por recusa — recusar é resposta legítima e precisa
    chegar ao usuário como frase, não como erro.
    """
    rotulo = assinaturas.ROTULOS.get(funcao, funcao)
    try:
        servidor = localizar_servidor(p, nome)
    except PendenciaInstitucional as erro:
        return {"permitida": False, "servidor": None, "mensagem": str(erro)}

    if p.aviso:
        return {"permitida": False, "servidor": servidor,
                "mensagem": (f"{p.aviso} Enquanto o cadastro estiver assim, "
                             "não dá para confirmar quem pode assinar.")}

    aptos = quem_pode_assinar(p, funcao)
    if any(s.get("id") == servidor.get("id") for s in aptos):
        return {"permitida": True, "servidor": servidor,
                "mensagem": (f"{servidor.get('nome')} está apto como "
                             f"{rotulo} nesta secretaria, na data do "
                             "processo.")}

    return {"permitida": False, "servidor": servidor,
            "mensagem": _recusa(p, servidor, funcao)}


def _recusa(p: Panorama, servidor: dict, funcao: str) -> str:
    """
    A frase do §37, e ela nomeia O ATO que falta.

    "Não é permitido" não ajuda ninguém. O servidor precisa saber se
    falta portaria, se falta designação, ou se a pessoa está inativa —
    porque cada uma se conserta num lugar diferente.
    """
    nome = servidor.get("nome") or "Este servidor"
    rotulo = assinaturas.ROTULOS.get(funcao, funcao)

    if not servidor.get("ativo", True):
        return (f"{nome} está inativo no cadastro de servidores e não pode "
                "assinar. Reative-o em Instituição → Servidores, se for o caso.")

    if funcao in assinaturas.FUNCOES_DE_PORTARIA:
        if not p.portaria:
            return (f"{nome} não pode ser incluído como {rotulo}: esta "
                    "secretaria não tem Portaria de Equipe de Planejamento "
                    f"vigente em {p.data_referencia:%d/%m/%Y}.")
        return (f"{nome} não integra a Equipe de Planejamento designada pela "
                f"{portarias.citacao(p.portaria)}, aplicável a esta "
                "secretaria e a este processo.")

    # §37, parágrafo final: função NÃO-portaria se verifica pelo ato dela,
    # e não pela equipe de planejamento. Um secretário municipal não
    # precisa estar em portaria de equipe para assinar como secretário.
    return (f"{nome} não tem a designação de {rotulo} vigente nesta "
            f"secretaria em {p.data_referencia:%d/%m/%Y}. A aptidão para "
            "essa função vem do cadastro de designações, não da equipe de "
            "planejamento — registre o ato em Instituição → Servidores.")


# ---------------------------------------------------------------------------
# §36.5 — Explicar os alertas institucionais
# ---------------------------------------------------------------------------
def alertas(p: Panorama) -> list[str]:
    """O que está errado no cadastro, em frases acionáveis."""
    achados: list[str] = []
    if p.aviso:
        achados.append(
            f"{p.aviso} O sistema não escolhe entre portarias em conflito — "
            "revogue ou ajuste a vigência de uma delas.")
    elif not p.portaria:
        achados.append(
            "Sem Portaria de Equipe de Planejamento vigente nesta secretaria "
            f"em {p.data_referencia:%d/%m/%Y}: a citação sai como marcador de "
            "pendência e ninguém pode assinar como integrante da equipe.")
    elif not portarias.membros_vigentes(p.membros):
        achados.append(
            f"{portarias.citacao(p.portaria)} está vigente mas não designa "
            "nenhum membro ativo.")

    inativos = [s.get("nome") for s in p.servidores
                if not s.get("ativo", True)]
    if inativos:
        achados.append(
            "Servidores inativos no cadastro (não podem assinar): "
            + ", ".join(n for n in inativos if n) + ".")
    return achados


# ---------------------------------------------------------------------------
# §37 — O PORTÃO DO BACKEND
# ---------------------------------------------------------------------------
def conferir_escolhas(escolhas: list[dict], anteriores: list[dict],
                      p: Panorama) -> None:
    """
    Levanta se alguma escolha NOVA não passa na elegibilidade.

    CHAMADA PELO PONTO DE GRAVAÇÃO, não pela conversa — é isto que o §37
    pede quando diz que uma chamada direta ao mecanismo de alteração tem
    que cair na mesma regra. O GovBot recusar em linguagem natural é a
    camada de cima; esta é a que segura.

    SÓ AS NOVAS SÃO CONFERIDAS, e a distinção é deliberada. Remover e
    reordenar não introduzem par `(servidor, função)` nenhum, e uma
    escolha feita quando a portaria valia não pode virar uma prisão: se
    a portaria for revogada depois, o servidor ainda precisa conseguir
    REMOVER a linha que ficou inválida. Conferir tudo a cada gravação
    tornaria impossível desfazer o problema.
    """
    ja = {(e.get("servidor_id"), e.get("funcao")) for e in anteriores}
    novas = [e for e in escolhas
             if (e.get("servidor_id"), e.get("funcao")) not in ja]
    if not novas:
        return

    if p.aviso:
        raise assinaturas.ErroAssinatura(
            f"{p.aviso} Nenhum signatário novo pode ser confirmado enquanto "
            "o cadastro de portarias estiver assim.")

    for escolha in novas:
        funcao = escolha.get("funcao") or ""
        assinaturas.conferir_elegibilidade(
            servidor_id=escolha.get("servidor_id"), funcao=funcao,
            elegiveis_agora=quem_pode_assinar(p, funcao))
