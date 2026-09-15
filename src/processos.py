"""
Estado de um processo, derivado — nunca armazenado em paralelo.

Status, etapa atual e progresso saem de `etapa`, `documentos` e
`aprovados`, que a 0001 já guarda e que o wizard já usa para navegar.
Guardá-los também em colunas criaria um segundo lugar onde a verdade
mora, e os dois divergiriam na primeira aprovação feita por um caminho
que esquecesse de atualizar o carimbo.

Tudo aqui é FUNÇÃO PURA sobre o dicionário do processo: nada de banco,
nada de `st.session_state`. É o que permite provar a máquina de estados
sem subir Streamlit nem PostgreSQL — e é onde os casos de canto (o
processo sem documento nenhum, o que tem ata mas não é registro de
preços) ficam visíveis em vez de escondidos dentro de uma tela.
"""

from __future__ import annotations

from datetime import datetime

from .config import DOCUMENTOS, SEQUENCIA_DOCUMENTOS, adota_srp

# ---------------------------------------------------------------------------
# Status — os nomes que o servidor lê
#
# São rótulos de tela, não chaves técnicas. Ficam aqui, e não espalhados
# pela interface, para que mudar "Em elaboração" para outra coisa seja
# uma edição num lugar só.
# ---------------------------------------------------------------------------
EM_ELABORACAO = "Em elaboração"
AGUARDANDO_PRECOS = "Aguardando pesquisa de preços"
EM_REVISAO = "Em revisão"
CONCLUIDO = "Concluído"
ARQUIVADO = "Arquivado"

# Ordem de precedência para ordenar a lista por status. Do que exige ação
# mais cedo para o que já está fechado — quem abre o painel quer ver
# primeiro o que está parado esperando por ele.
ORDEM_STATUS = (
    AGUARDANDO_PRECOS,
    EM_REVISAO,
    EM_ELABORACAO,
    CONCLUIDO,
    ARQUIVADO,
)


def documentos_do_processo(processo: dict) -> tuple[str, ...]:
    """
    Quais documentos ESTE processo precisa ter.

    Não é constante: a Ata de Registro de Preços só entra quando o
    processo adota registro de preços. Tratar os cinco como obrigatórios
    sempre faria um processo comum nunca passar de 4/5 — travado em
    "quase pronto" para sempre, sem nada que o servidor pudesse fazer.
    """
    dados = processo.get("dados") or {}
    obrigatorios = list(SEQUENCIA_DOCUMENTOS)
    if adota_srp(dados):
        if "arp" in DOCUMENTOS and "arp" not in obrigatorios:
            obrigatorios.append("arp")
    else:
        obrigatorios = [d for d in obrigatorios if d != "arp"]
    return tuple(obrigatorios)


def progresso(processo: dict) -> tuple[int, int]:
    """
    (aprovados, total) dos documentos que este processo precisa ter.

    Conta APROVADOS, não gerados. Um documento gerado e não revisado não
    é trabalho concluído — é trabalho esperando conferência humana, que
    é justamente o que o produto existe para não deixar passar.
    """
    obrigatorios = documentos_do_processo(processo)
    aprovados = set(processo.get("aprovados") or [])
    feitos = sum(1 for doc in obrigatorios if doc in aprovados)
    return feitos, len(obrigatorios)


def etapa_atual(processo: dict) -> str:
    """
    Em que o servidor está trabalhando agora, em uma frase curta.

    Prefere o PRIMEIRO documento obrigatório ainda não aprovado à etapa
    numérica: a etapa diz onde o cursor do wizard parou, e o que o
    servidor quer saber é o que falta. Os dois coincidem no caminho
    normal e divergem quando alguém volta para revisar algo anterior —
    e aí a resposta útil é a do que falta.
    """
    obrigatorios = documentos_do_processo(processo)
    aprovados = set(processo.get("aprovados") or [])
    documentos = processo.get("documentos") or {}

    for doc in obrigatorios:
        if doc in aprovados:
            continue
        sigla = DOCUMENTOS.get(doc, {}).get("sigla", doc.upper())
        if doc in documentos:
            return f"{sigla} — aguardando revisão"
        return f"{sigla} — a elaborar"
    return "Todos os documentos aprovados"


def _tem_pesquisa_de_precos_pendente(processo: dict) -> bool:
    """
    O processo está parado esperando preço?

    Lê o fato canônico gravado pelo módulo de pesquisa de preços. Com o
    módulo desligado a chave não existe, a função devolve False, e o
    status nunca menciona pesquisa de preços — a tela não promete uma
    etapa que o sistema não tem.
    """
    dados = processo.get("dados") or {}
    if dados.get("pesquisa_preco_id"):
        return False
    itens = dados.get("itens") or []
    if not itens:
        return False
    # Há itens para cotar e nenhuma pesquisa aplicada: o ETP e o TR
    # dependem do valor estimado, então é aqui que o processo para.
    aprovados = set(processo.get("aprovados") or [])
    return "dfd" in aprovados and "etp" not in aprovados


def status(processo: dict) -> str:
    """
    O status geral, em uma palavra que o servidor entenda.

    A ordem das perguntas é a ordem da precedência, e ela importa: um
    processo arquivado é arquivado mesmo que esteja incompleto, e um
    concluído é concluído mesmo que alguém tenha voltado numa etapa.
    """
    if processo.get("arquivado"):
        return ARQUIVADO

    feitos, total = progresso(processo)
    if total and feitos == total:
        return CONCLUIDO

    if _tem_pesquisa_de_precos_pendente(processo):
        return AGUARDANDO_PRECOS

    # Documento gerado e ainda não aprovado = tem texto na mesa
    # esperando olho humano.
    documentos = processo.get("documentos") or {}
    aprovados = set(processo.get("aprovados") or [])
    if any(doc in documentos and doc not in aprovados
           for doc in documentos_do_processo(processo)):
        return EM_REVISAO

    return EM_ELABORACAO


def nome_exibido(processo: dict) -> str:
    """
    O nome que aparece na lista.

    Sem nome dado pelo servidor, mostra órgão e objeto — os dados que ELE
    escreveu. Nunca um rótulo inventado: um processo chamado "Processo 3"
    não ajuda a encontrar nada, e um chamado "Aquisição de material"
    que o servidor não escreveu o faria procurar por um texto que nunca
    digitou.
    """
    nome = (processo.get("nome") or "").strip()
    if nome:
        return nome
    orgao = (processo.get("orgao") or "").strip()
    objeto = (processo.get("objeto") or "").strip()
    partes = [p for p in (orgao, objeto) if p]
    return " — ".join(partes) if partes else "Processo sem nome"


def data_legivel(valor: str | None) -> str:
    """Data ISO do banco em dd/mm/aaaa hh:mm, ou travessão se não houver."""
    if not valor:
        return "—"
    try:
        return datetime.fromisoformat(str(valor)).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        # Formato inesperado não pode derrubar a lista inteira: o painel
        # existe para mostrar processos, não para validar carimbo de data.
        return str(valor)[:16].replace("T", " ")


def resumo(processo: dict) -> dict:
    """
    Tudo o que uma linha do painel precisa, num dicionário só.

    Uma função, uma passada. A alternativa — a tela chamando cinco
    funções por linha — espalharia a ordem das chamadas por dentro do
    laço de renderização, onde ninguém a testa.
    """
    feitos, total = progresso(processo)
    return {
        "id": processo.get("id", ""),
        "nome": nome_exibido(processo),
        "nome_proprio": (processo.get("nome") or "").strip(),
        "status": status(processo),
        "etapa": etapa_atual(processo),
        "progresso": (feitos, total),
        "progresso_fracao": (feitos / total) if total else 0.0,
        "criado_em": data_legivel(processo.get("criado_em")),
        "atualizado_em": data_legivel(processo.get("atualizado_em")),
        "orgao": processo.get("orgao") or "",
        "objeto": processo.get("objeto") or "",
    }


def filtrar(processos: list[dict], busca: str = "") -> list[dict]:
    """
    Filtra por nome, órgão ou objeto.

    Busca sem acento e sem caixa, porque quem procura "aquisicao" espera
    achar "Aquisição". Exigir o acento certo transformaria a busca num
    teste de digitação.
    """
    termo = _normalizar(busca)
    if not termo:
        return list(processos)
    return [
        p for p in processos
        if termo in _normalizar(
            f"{p.get('nome') or ''} {p.get('orgao') or ''} "
            f"{p.get('objeto') or ''}")
    ]


def _normalizar(texto: str) -> str:
    """
    Minúsculas, sem acento e sem espaço nas pontas.

    O `strip` não é cosmético: sem ele, um espaço acidental colado na
    caixa de busca vira um termo "verdadeiro" que procura literalmente
    por espaços — e some com a lista inteira sem dizer por quê.
    """
    import unicodedata

    sem_acento = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(
        c for c in sem_acento if not unicodedata.combining(c)).lower().strip()


def ordenar(processos: list[dict], criterio: str = "atualizado_em") -> list[dict]:
    """
    Ordena por data (mais recente primeiro) ou por status.

    Por status usa `ORDEM_STATUS`, não ordem alfabética: alfabética
    colocaria "Aguardando pesquisa de preços" antes de "Concluído" por
    acaso, e "Arquivado" no topo — o oposto do que serve.
    """
    if criterio == "status":
        def chave(p):
            try:
                posicao = ORDEM_STATUS.index(status(p))
            except ValueError:
                posicao = len(ORDEM_STATUS)
            return (posicao, str(p.get("atualizado_em") or ""))
        return sorted(processos, key=chave)
    if criterio == "criado_em":
        return sorted(processos, key=lambda p: str(p.get("criado_em") or ""),
                      reverse=True)
    return sorted(processos, key=lambda p: str(p.get("atualizado_em") or ""),
                  reverse=True)
