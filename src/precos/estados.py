"""
Máquina de estados da pesquisa e do item (§42).

O prompt do módulo pediu a máquina de estados **formalmente definida**, e
há um motivo prático para ela não ser apenas uma coluna `text` com um
comentário: uma pesquisa de preços vira ato administrativo. Se um item
puder ir de `pending` direto para `complete` sem passar por busca e
revisão, o relatório dirá "concluído" sobre um item que ninguém
pesquisou — e o defeito só aparece na auditoria, meses depois.

Por isso as transições são declaradas aqui, uma a uma, e o que não está
declarado é recusado. A recusa é `TransicaoInvalida`, não um `assert`:
precisa sobreviver a `python -O` e precisa dizer o que foi tentado.

Duas fronteiras que este módulo estabelece e que valem para as fases
seguintes:

1. **estado não anda para trás para "consertar" o passado.** Uma pesquisa
   já aplicada ao processo não volta a `review` para ser reeditada — uma
   alteração manual cria uma REVISÃO NOVA (§44), e a anterior continua
   existindo com o que sustentou o ato;
2. **o estado da pesquisa é derivado do estado dos itens**, nunca
   digitado. `partial` não é uma escolha do usuário: é a constatação de
   que parte dos itens não concluiu.
"""

from __future__ import annotations

from enum import Enum


class TransicaoInvalida(ValueError):
    """
    Transição de estado que a máquina não declara.

    Erro, não aviso: gravar o estado errado é pior do que falhar, porque
    o estado errado é lido depois como se fosse verdade.
    """


class EstadoPesquisa(str, Enum):
    """
    Ciclo de vida da pesquisa.

    `PARCIAL` existe porque uma pesquisa de 210 itens quase nunca termina
    com todos os itens resolvidos: alguns não terão referência suficiente,
    e chamar isso de "concluída" seria o mesmo erro que o módulo existe
    para impedir.
    """

    RASCUNHO = "draft"
    NA_FILA = "queued"
    EXECUTANDO = "running"
    PARCIAL = "partial"
    EM_REVISAO = "review"
    CONCLUIDA = "completed"
    APLICADA = "applied"
    ARQUIVADA = "archived"
    FALHOU = "failed"


class EstadoItem(str, Enum):
    """
    Ciclo de vida do item dentro da pesquisa.

    `INCOMPLETO` é um resultado legítimo e final do ponto de vista do
    motor: a busca correu, e não havia referência bastante. Ele NÃO é
    erro — `ERRO` é falha técnica (fonte fora do ar, exceção). Confundir
    os dois faria "o mercado não tem esse item" parecer indisponibilidade
    de API, e o servidor tentaria de novo para sempre.
    """

    PENDENTE = "pending"
    BUSCANDO = "searching"
    CLASSIFICANDO = "matching"
    EM_REVISAO = "review"
    COMPLETO = "complete"
    INCOMPLETO = "incomplete"
    ERRO = "error"


# ---------------------------------------------------------------------------
# Transições declaradas
#
# Ler como "de → conjunto de destinos". Ausência de chave = estado
# terminal. O que não está aqui não acontece.
# ---------------------------------------------------------------------------
TRANSICOES_PESQUISA: dict[EstadoPesquisa, frozenset[EstadoPesquisa]] = {
    # O rascunho pode ser abandonado sem nunca ter sido executado.
    EstadoPesquisa.RASCUNHO: frozenset({
        EstadoPesquisa.NA_FILA, EstadoPesquisa.ARQUIVADA}),
    EstadoPesquisa.NA_FILA: frozenset({
        EstadoPesquisa.EXECUTANDO, EstadoPesquisa.FALHOU,
        EstadoPesquisa.ARQUIVADA}),
    # A execução termina em três lugares diferentes, e a diferença
    # importa: PARCIAL admite nova rodada, EM_REVISAO já tem material
    # para o humano decidir, FALHOU não produziu nada aproveitável.
    EstadoPesquisa.EXECUTANDO: frozenset({
        EstadoPesquisa.PARCIAL, EstadoPesquisa.EM_REVISAO,
        EstadoPesquisa.FALHOU}),
    # PARCIAL volta para a fila: é o "pesquisar os que faltaram".
    EstadoPesquisa.PARCIAL: frozenset({
        EstadoPesquisa.NA_FILA, EstadoPesquisa.EM_REVISAO,
        EstadoPesquisa.ARQUIVADA}),
    EstadoPesquisa.EM_REVISAO: frozenset({
        EstadoPesquisa.NA_FILA, EstadoPesquisa.CONCLUIDA,
        EstadoPesquisa.ARQUIVADA}),
    # Concluída ainda pode voltar à revisão: nada foi aplicado a
    # processo nenhum, então não há ato administrativo a preservar.
    EstadoPesquisa.CONCLUIDA: frozenset({
        EstadoPesquisa.EM_REVISAO, EstadoPesquisa.APLICADA,
        EstadoPesquisa.ARQUIVADA}),
    # APLICADA não volta. O preço já entrou no processo; mexer nele é
    # uma revisão NOVA da pesquisa (ver `exige_nova_revisao`).
    EstadoPesquisa.APLICADA: frozenset({EstadoPesquisa.ARQUIVADA}),
    EstadoPesquisa.FALHOU: frozenset({
        EstadoPesquisa.NA_FILA, EstadoPesquisa.ARQUIVADA}),
    # ARQUIVADA é terminal, de propósito: reabrir uma pesquisa arquivada
    # apagaria a razão pela qual ela foi arquivada.
}

TRANSICOES_ITEM: dict[EstadoItem, frozenset[EstadoItem]] = {
    EstadoItem.PENDENTE: frozenset({EstadoItem.BUSCANDO}),
    EstadoItem.BUSCANDO: frozenset({
        EstadoItem.CLASSIFICANDO, EstadoItem.INCOMPLETO, EstadoItem.ERRO}),
    EstadoItem.CLASSIFICANDO: frozenset({
        EstadoItem.EM_REVISAO, EstadoItem.INCOMPLETO, EstadoItem.ERRO}),
    # Da revisão sai o veredito humano — inclusive "não deu", que é
    # INCOMPLETO e não COMPLETO com preço inventado.
    EstadoItem.EM_REVISAO: frozenset({
        EstadoItem.COMPLETO, EstadoItem.INCOMPLETO, EstadoItem.BUSCANDO}),
    # COMPLETO reabre para revisão (o revisor mudou de ideia) e aceita
    # nova busca (chegou fonte nova). Não vira INCOMPLETO por si só.
    EstadoItem.COMPLETO: frozenset({
        EstadoItem.EM_REVISAO, EstadoItem.BUSCANDO}),
    EstadoItem.INCOMPLETO: frozenset({
        EstadoItem.BUSCANDO, EstadoItem.EM_REVISAO}),
    EstadoItem.ERRO: frozenset({EstadoItem.BUSCANDO}),
}

# Estados em que o motor ainda tem trabalho a fazer no item.
EM_ANDAMENTO = frozenset({
    EstadoItem.PENDENTE, EstadoItem.BUSCANDO, EstadoItem.CLASSIFICANDO})

# Estados de item que impedem a pesquisa de ser CONCLUIDA.
NAO_RESOLVIDOS = frozenset({
    EstadoItem.PENDENTE, EstadoItem.BUSCANDO, EstadoItem.CLASSIFICANDO,
    EstadoItem.EM_REVISAO, EstadoItem.ERRO})

# Pesquisa fechada para edição de conteúdo. Alterar qualquer coisa aqui
# exige revisão nova.
IMUTAVEIS = frozenset({EstadoPesquisa.APLICADA, EstadoPesquisa.ARQUIVADA})


def _validar(atual, destino, tabela, rotulo: str):
    if atual == destino:
        # Reaplicar o mesmo estado é no-op, não erro: o repositório é
        # idempotente (§43) e uma reexecução não pode explodir.
        return destino
    permitidos = tabela.get(atual, frozenset())
    if destino not in permitidos:
        alcance = ", ".join(sorted(e.value for e in permitidos)) or "nenhum"
        raise TransicaoInvalida(
            f"{rotulo}: '{atual.value}' não vai para '{destino.value}' "
            f"(destinos declarados: {alcance})")
    return destino


def transitar_pesquisa(atual: EstadoPesquisa,
                       destino: EstadoPesquisa) -> EstadoPesquisa:
    """Aplica a transição da pesquisa ou recusa dizendo o porquê."""
    return _validar(atual, destino, TRANSICOES_PESQUISA, "pesquisa")


def transitar_item(atual: EstadoItem, destino: EstadoItem) -> EstadoItem:
    """Aplica a transição do item ou recusa dizendo o porquê."""
    return _validar(atual, destino, TRANSICOES_ITEM, "item")


def pode_transitar_pesquisa(atual: EstadoPesquisa,
                            destino: EstadoPesquisa) -> bool:
    return (atual == destino
            or destino in TRANSICOES_PESQUISA.get(atual, frozenset()))


def pode_transitar_item(atual: EstadoItem, destino: EstadoItem) -> bool:
    return (atual == destino
            or destino in TRANSICOES_ITEM.get(atual, frozenset()))


def estado_derivado(estados: list[EstadoItem]) -> EstadoPesquisa:
    """
    Estado da pesquisa a partir dos estados dos itens.

    Derivado, nunca digitado. É isto que impede uma pesquisa com dois
    itens em erro de ser marcada como concluída na mão.

    A ordem das perguntas é a ordem da severidade:

    * sem item nenhum → ainda é rascunho;
    * algum item ainda rodando → EXECUTANDO;
    * algum item por revisar → EM_REVISAO (há trabalho humano na mesa);
    * tudo resolvido, mas com incompleto ou erro → PARCIAL;
    * tudo COMPLETO → CONCLUIDA.

    `PARCIAL` vem depois de `EM_REVISAO` de propósito: enquanto houver
    item aguardando decisão humana, o que a pesquisa precisa é de revisor,
    não de nova rodada de busca.
    """
    if not estados:
        return EstadoPesquisa.RASCUNHO
    conjunto = set(estados)
    if conjunto & EM_ANDAMENTO:
        return EstadoPesquisa.EXECUTANDO
    if EstadoItem.EM_REVISAO in conjunto or EstadoItem.ERRO in conjunto:
        return EstadoPesquisa.EM_REVISAO
    if EstadoItem.INCOMPLETO in conjunto:
        return EstadoPesquisa.PARCIAL
    return EstadoPesquisa.CONCLUIDA


# ---------------------------------------------------------------------------
# Versionamento (§44)
#
# "Alterar manualmente cesta, metodologia, filtros ou preço estimado deve
# criar uma nova revisão lógica da pesquisa."
#
# A lista está aqui — e não espalhada pelas telas — porque é ela que
# define o que conta como mexer no resultado. Corrigir um erro de digitação
# no NOME da pesquisa não é revisão nova; trocar o método de média para
# mediana é, porque muda o valor que vai para o processo.
# ---------------------------------------------------------------------------
CAMPOS_QUE_VERSIONAM = frozenset({
    "cesta",             # inclusão/exclusão manual de referência
    "metodologia",       # média, mediana, menor
    "filtros",           # janela temporal, UF, fonte, piso de comparabilidade
    "preco_estimado",    # valor unitário arbitrado pelo revisor
    "perfil_normativo",  # troca de regime (Lei 14.133 ↔ IN 65)
})


def exige_nova_revisao(campos) -> bool:
    """True se alguma alteração toca o resultado e obriga revisão nova."""
    return bool(CAMPOS_QUE_VERSIONAM & set(campos))
