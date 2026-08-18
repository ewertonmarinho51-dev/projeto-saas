"""
Vocabulário da trilha de governança — um só, para o app e para o banco.

O problema que este módulo resolve
----------------------------------
O app emitia tipos de evento DERIVADOS DO DADO:

    f"{tipo_artefato}_rascunho_criado"     → clausula_rascunho_criado
    f"{tipo}_{novo_status.lower()}"        → politica_published
    f"proposta_{decisao.lower()}"          → proposta_accepted

O banco, na 0020, tem um vocabulário FECHADO — `artefato_criado`,
`versao_publicada`, `aprovacao_registrada`… Nenhum dos tipos do app
existe nessa lista, e a interseção entre os dois conjuntos é VAZIA.

Isso não é um detalhe de nomenclatura. Um vocabulário que depende do
dado não pode ser fechado: cada `tipo_artefato` novo inventa eventos
novos, e a matriz papel→evento — que é o que decide QUEM pode registrar
O QUÊ — passa a ter buracos que ninguém consegue enumerar. Foi assim
que a autorização acabou virando "quem tem qualquer papel pode
qualquer coisa".

A regra
-------
O TIPO DE EVENTO nomeia o ATO. O tipo de artefato é ATRIBUTO do ato e
vai no `payload`. "Criar a versão 3 de uma cláusula" e "criar a versão
3 de uma política" são o mesmo ato sobre coisas diferentes — e a
diferença fica onde diferenças ficam, nos dados, não no nome.

Este módulo é o espelho, em Python, da matriz que a 0020 grava no
banco. Ele existe para que a divergência apareça num teste, e não numa
exceção de produção depois que o ato já aconteceu.
"""

from __future__ import annotations


class EventoInvalido(ValueError):
    """Tipo de evento fora do vocabulário, ou entidade incompatível."""


# ---------------------------------------------------------------------------
# A matriz. Espelha `entidade_do_tipo_de_evento()` da 0020.
# ---------------------------------------------------------------------------
EVENTOS: dict[str, str] = {
    # ciclo do artefato
    "artefato_criado":       "artefato",
    "artefato_alterado":     "artefato",
    # ciclo da versão — é aqui que quase todo ato do Centro acontece
    "versao_criada":         "versao",
    "versao_alterada":       "versao",
    "versao_aprovada":       "versao",
    "versao_publicada":      "versao",
    "versao_superada":       "versao",
    "versao_revogada":       "versao",
    # registro formal de aprovação (linha em governanca_aprovacoes)
    "aprovacao_registrada":  "aprovacao",
    "aprovacao_revogada":    "aprovacao",
    # publicação (linha em governanca_publicacoes)
    "publicacao_registrada": "publicacao",
    # laboratório de melhorias
    "proposta_aceita":       "proposta",
    "proposta_rejeitada":    "proposta",
}

ENTIDADES: frozenset[str] = frozenset(EVENTOS.values())

# Entidade → tabela. Espelha a matriz da RPC, e existe pelo mesmo
# motivo dela: entidade desconhecida é recusada, nunca assumida.
TABELA_DA_ENTIDADE: dict[str, str] = {
    "artefato":   "governanca_artefatos",
    "versao":     "governanca_versoes",
    "aprovacao":  "governanca_aprovacoes",
    "publicacao": "governanca_publicacoes",
    "proposta":   "melhoria_propostas",
}

# `governanca_aprovacoes.entidade_tipo` guarda o tipo do objeto
# GOVERNADO — e usa o mesmo vocabulário lógico, porque é ele que a
# resolução de escopo da 0020 percorre. Gravar o nome da tabela ali
# criava aprovações sobre as quais ninguém pode registrar evento: a
# matriz tipo→tabela é fechada e recusa o que não resolve.
TIPO_DA_APROVACAO_DE_VERSAO = "versao"
TIPO_DA_APROVACAO_DE_ARTEFATO = "artefato"

# ---------------------------------------------------------------------------
# Transições de estado do catálogo → ato registrado
#
# `transicionar()` construía o tipo com `f"{tipo}_{novo_status.lower()}"`,
# o que produzia `clausula_published`, `politica_revoked` e assim por
# diante — nomes em duas línguas e dependentes do dado.
# ---------------------------------------------------------------------------
# Só os estados com AUTORIDADE atrelada ganham ato próprio — são
# exatamente os de `catalogo._PAPEL_POR_TRANSICAO`, mais o SUPERSEDED
# que a publicação provoca. Os demais (UNDER_REVIEW, DRAFT, SHADOW,
# SCHEDULED) são movimentos de fluxo sem porteiro: o ato honesto é "a
# versão mudou de estado", e QUAL estado fica no payload.
#
# Inventar oito nomes de evento para oito estados daria a impressão de
# oito decisões distintas onde há quatro.
EVENTO_DA_TRANSICAO: dict[str, str] = {
    "APPROVED_FOR_SIMULATION": "versao_aprovada",
    "PUBLISHED":               "versao_publicada",
    "REVOKED":                 "versao_revogada",
    "SUPERSEDED":              "versao_superada",
}

EVENTO_DE_TRANSICAO_SEM_PORTEIRO = "versao_alterada"

# Decisão sobre proposta do laboratório. `f"proposta_{decisao.lower()}"`
# gerava `proposta_accepted`/`proposta_rejected` — inglês misturado ao
# resto do vocabulário, e fora de qualquer matriz.
EVENTO_DA_DECISAO: dict[str, str] = {
    "ACCEPTED": "proposta_aceita",
    "REJECTED": "proposta_rejeitada",
}


def evento_da_transicao(novo_status: str) -> str:
    """
    Ato correspondente à transição. TOTAL: nunca levanta KeyError.

    A versão anterior montava o nome com f-string e por isso "nunca
    falhava" — produzia lixo em silêncio. Uma função parcial aqui
    trocaria o lixo por uma exceção no meio da publicação, o que é pior
    para quem está usando o sistema e não melhor para a trilha.
    """
    return EVENTO_DA_TRANSICAO.get(novo_status,
                                   EVENTO_DE_TRANSICAO_SEM_PORTEIRO)

# ---------------------------------------------------------------------------
# Reconciliação com o que o app emitia antes
#
# A tabela não é decorativa: é a que permite ler a trilha antiga. Os
# eventos já gravados continuam com os rótulos velhos, e quem for
# auditar precisa do dicionário. `{tipo}` é o `tipo_artefato`, que
# agora vive no payload.
# ---------------------------------------------------------------------------
VOCABULARIO_LEGADO: dict[str, str] = {
    "{tipo}_rascunho_criado":          "versao_criada",
    "{tipo}_rascunho_editado":         "versao_alterada",
    "{tipo}_versao_derivada":          "versao_criada",
    "{tipo}_versao_superada":          "versao_superada",
    "{tipo}_approved_for_simulation":  "versao_aprovada",
    "{tipo}_published":                "versao_publicada",
    "{tipo}_revoked":                  "versao_revogada",
    "proposta_accepted":               "proposta_aceita",
    "proposta_rejected":               "proposta_rejeitada",
}

# A entidade que o app declarava antes era SEMPRE o nome da tabela
# (`governanca_versoes`, `melhoria_propostas`), não o tipo lógico. A
# 0020 espera o tipo lógico, e a diferença fazia toda chamada ser
# recusada por vocabulário mesmo com papel correto.
ENTIDADE_LEGADA: dict[str, str] = {
    "governanca_artefatos":   "artefato",
    "governanca_versoes":     "versao",
    "governanca_aprovacoes":  "aprovacao",
    "governanca_publicacoes": "publicacao",
    "melhoria_propostas":     "proposta",
}


def entidade_de(tipo_evento: str) -> str:
    """Entidade exigida pelo tipo de evento. Levanta se for desconhecido."""
    try:
        return EVENTOS[tipo_evento]
    except KeyError:
        raise EventoInvalido(
            f"tipo de evento fora do vocabulário da trilha: "
            f"{tipo_evento!r}") from None


def exigir_evento_valido(tipo_evento: str, entidade_tipo: str) -> None:
    """
    Confere tipo E entidade ANTES de chamar o banco.

    A RPC confere de novo — ela é a autoridade, e uma checagem no
    cliente não substitui checagem no servidor. Esta aqui serve para
    que o erro apareça no teste, com o nome do ato, em vez de virar
    uma exceção genérica de PostgREST depois que a transição de estado
    já foi gravada.
    """
    esperada = entidade_de(tipo_evento)
    if entidade_tipo != esperada:
        raise EventoInvalido(
            f"evento {tipo_evento!r} exige entidade {esperada!r}, "
            f"recebeu {entidade_tipo!r}")
