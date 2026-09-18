"""
Política de roteamento de modelos — onde a escolha de modelo MORA.

O PROBLEMA QUE ISTO RESOLVE

Hoje a escolha está espalhada: `config.py` tem as listas de fallback,
`llm.py` tem a cascata de motores, e o painel do administrador tem o
modelo configurado. Nenhum dos três sabe QUE TAREFA está sendo feita.
Gerar um edital e classificar um achado usam exatamente o mesmo caminho e
o mesmo modelo.

Pior: a cascata de fallback é irrestrita. Se a OpenAI cair no meio da
geração de um edital, a requisição desce para `gemini-1.5-flash` sem que
ninguém tenha homologado esse modelo para documento jurídico. O
documento sai, o servidor assina, e a única pista é uma linha de
registro técnico.

Esta política existe para que isso não aconteça em silêncio.

O QUE ELA NÃO FAZ

Não chama rede, não lê `st.session_state`, não conhece OmniRoute nem
provider nenhum. É tabela e função pura — dá para testar sem banco, sem
chave e sem mock. Quem executa é `ai_gateway.py`.

E ela **não muda o caminho feliz**: com a restrição desligada — o padrão
— `motores_permitidos` devolve exatamente a ordem que o sistema já usa
hoje. A política só tem efeito quando alguém a liga, e o que ela faz
quando ligada é ESTREITAR, nunca inventar um modelo que o operador não
configurou.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# TIPOS DE TAREFA
#
# Derivados do que o sistema REALMENTE faz, não de uma taxonomia genérica.
# Cada um corresponde a um `rotulo_registro` que já circula em `llm.py`.
# ---------------------------------------------------------------------------
GERACAO_DE_DOCUMENTO = "document_generation"
ANALISE_JURIDICA = "legal_analysis"
PESQUISA_DE_PRECO = "price_research"
RESPOSTA_COM_RAG = "rag_answer"
CLASSIFICACAO = "classification"
SEGUNDO_PLANO = "background"

# ---------------------------------------------------------------------------
# GRUPOS DE MODELO
#
# Um grupo NUNCA empresta modelo de outro. É essa fronteira que impede o
# fallback de rebaixar uma tarefa crítica para o que estiver disponível.
#
# `PROCUREMENT_HIGH_ACCURACY` é o grupo dos documentos que viram ato
# administrativo: DFD, ETP, TR, Mapa de Riscos, edital, ata. Aqui a
# exigência não é "o modelo escreve bem" — é que número, valor,
# quantidade, data, artigo, item e especificação saiam LITERAIS. Um
# modelo entra nesta lista depois de passar no conjunto de avaliação,
# nunca por estar disponível.
#
# Os motores listados são os que o projeto opera hoje. A lista de MODELOS
# de cada motor continua em `config.py`: este arquivo decide QUAL MOTOR
# pode atender a tarefa, e é isso que basta para fechar a porta do
# rebaixamento silencioso.
# ---------------------------------------------------------------------------
PROCUREMENT_HIGH_ACCURACY = "PROCUREMENT_HIGH_ACCURACY"
HIGH_ACCURACY = "HIGH_ACCURACY"
FAST = "FAST"
CHEAP = "CHEAP"

MOTORES_DO_GRUPO: dict[str, tuple[str, ...]] = {
    # Só a OpenAI é homologada para documento oficial hoje, e isso é uma
    # AFIRMAÇÃO DE HOMOLOGAÇÃO, não uma preferência técnica: é o motor
    # com que a suíte de documentos foi construída e conferida. Gemini e
    # OpenRouter entram aqui quando passarem no conjunto de avaliação —
    # e a entrada deles é uma decisão do operador, registrada em commit.
    PROCUREMENT_HIGH_ACCURACY: ("openai",),
    HIGH_ACCURACY: ("openai",),
    FAST: ("openai", "gemini"),
    CHEAP: ("openai", "gemini", "openrouter"),
}

# ---------------------------------------------------------------------------
# DE ROTULO A TIPO
#
# Os rótulos são os que `llm.py` já passa para `registrar_geracao`: as
# chaves de documento e as finalidades das chamadas genéricas. Rótulo
# desconhecido NÃO vira tarefa crítica por engano — vira `SEGUNDO_PLANO`,
# que é o grupo mais permissivo. Estreitar por acidente quebraria uma
# funcionalidade; a restrição só vale onde alguém a declarou.
# ---------------------------------------------------------------------------
TIPO_DO_ROTULO: dict[str, str] = {
    "dfd": GERACAO_DE_DOCUMENTO,
    "etp": GERACAO_DE_DOCUMENTO,
    "tr": GERACAO_DE_DOCUMENTO,
    "mapa_riscos": GERACAO_DE_DOCUMENTO,
    "edital": GERACAO_DE_DOCUMENTO,
    "arp": GERACAO_DE_DOCUMENTO,
    "parecer": ANALISE_JURIDICA,
    "corretor": ANALISE_JURIDICA,
    "auditor": ANALISE_JURIDICA,
    "revisao": ANALISE_JURIDICA,
    "precos": PESQUISA_DE_PRECO,
    "precos_semantica": PESQUISA_DE_PRECO,
    "govbot": RESPOSTA_COM_RAG,
    "classificacao": CLASSIFICACAO,
}

GRUPO_DO_TIPO: dict[str, str] = {
    GERACAO_DE_DOCUMENTO: PROCUREMENT_HIGH_ACCURACY,
    ANALISE_JURIDICA: HIGH_ACCURACY,
    PESQUISA_DE_PRECO: HIGH_ACCURACY,
    RESPOSTA_COM_RAG: HIGH_ACCURACY,
    CLASSIFICACAO: FAST,
    SEGUNDO_PLANO: CHEAP,
}

# Tarefas em que o fallback NÃO pode sair do grupo. Se a lista acabar, a
# geração FALHA — e falhar é a resposta certa: um edital gerado por
# modelo não homologado é pior que um edital não gerado, porque o
# primeiro é assinado.
CRITICAS = (GERACAO_DE_DOCUMENTO, ANALISE_JURIDICA, PESQUISA_DE_PRECO)


def tipo_da_tarefa(rotulo: str) -> str:
    """O tipo de uma tarefa pelo rótulo de registro. Desconhecido → segundo plano."""
    return TIPO_DO_ROTULO.get((rotulo or "").strip().lower(), SEGUNDO_PLANO)


def grupo_da_tarefa(rotulo: str) -> str:
    return GRUPO_DO_TIPO[tipo_da_tarefa(rotulo)]


def e_critica(rotulo: str) -> bool:
    return tipo_da_tarefa(rotulo) in CRITICAS


def motores_permitidos(rotulo: str,
                       disponiveis: list[tuple[str, str]],
                       *, restringir: bool) -> list[tuple[str, str]]:
    """
    Filtra `[(motor, chave)]` pelo grupo da tarefa, preservando a ORDEM.

    `restringir=False` é passagem direta, e é o padrão do sistema: a
    política não muda nada até alguém ligá-la.

    A ordem vem de `motores_disponiveis()` e é mantida de propósito —
    ela reflete a preferência do operador (motor principal, fallback), e
    reordenar aqui seria a política decidindo algo que não é dela.

    O filtro NUNCA devolve lista vazia quando havia motor disponível: se
    nenhum motor do grupo estiver configurado, devolve a lista original.
    A alternativa seria uma tarefa que para de funcionar porque a chave
    do motor homologado não está preenchida — política derrubando
    funcionalidade, que é o oposto do que ela existe para fazer. Quem
    precisa de recusa dura é `exigir_homologado`, abaixo, e essa recusa é
    uma decisão explícita.
    """
    if not restringir or not disponiveis:
        return list(disponiveis)

    permitidos = MOTORES_DO_GRUPO[grupo_da_tarefa(rotulo)]
    filtrados = [par for par in disponiveis if par[0] in permitidos]
    return filtrados or list(disponiveis)


def exigir_homologado(rotulo: str, motor: str, *, restringir: bool) -> None:
    """
    Levanta `ValueError` se o motor não pertence ao grupo de uma tarefa
    CRÍTICA. É a versão dura, para quem quiser falhar em vez de degradar.

    Separada de `motores_permitidos` de propósito: filtrar e recusar são
    decisões diferentes, e juntá-las numa função só esconderia qual das
    duas está em vigor.
    """
    if not restringir or not e_critica(rotulo):
        return
    grupo = grupo_da_tarefa(rotulo)
    if motor not in MOTORES_DO_GRUPO[grupo]:
        raise ValueError(
            f"tarefa crítica '{rotulo}' ({tipo_da_tarefa(rotulo)}) não pode "
            f"usar o motor '{motor}': o grupo {grupo} admite apenas "
            f"{', '.join(MOTORES_DO_GRUPO[grupo])}. Homologue o motor antes "
            f"de usá-lo em documento que vira ato administrativo.")


def descrever(rotulo: str) -> dict[str, object]:
    """Uma linha de telemetria por tarefa, sem conteúdo nenhum dentro."""
    return {
        "rotulo": rotulo,
        "task_type": tipo_da_tarefa(rotulo),
        "routing_policy": grupo_da_tarefa(rotulo),
        "critica": e_critica(rotulo),
        "motores_do_grupo": list(MOTORES_DO_GRUPO[grupo_da_tarefa(rotulo)]),
    }
