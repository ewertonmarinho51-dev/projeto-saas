"""
Regeneração por cláusula — mudar o prazo não reescreve o Termo inteiro.

O DESPERDÍCIO QUE ISTO CORRIGE

Hoje, mudar UM campo do formulário chama `state.invalidar_a_partir_de
("formulario")`, que DESCARTA os cinco documentos. O servidor que
corrigir a data pretendida perde DFD, ETP, Mapa de Riscos, TR e Edital,
e precisa gerar tudo de novo: pela medição da linha de base, cerca de
60 mil tokens de entrada e 25 mil de saída — para uma alteração que
toca duas cláusulas.

A LÓGICA

  1. comparar o formulário antigo com o novo → campos alterados;
  2. `MAPA_DE_IMPACTO` diz, por documento, quais cláusulas cada campo
     alcança. É DECLARADO, cláusula por cláusula;
  3. pedir ao modelo SÓ essas cláusulas, com o resto do documento como
     contexto de coerência;
  4. substituir só elas no texto vigente, e CONFERIR que nada mais
     mudou antes de aceitar.

A DEFESA CONTRA O MODO DE FALHA

O risco é entregar um documento inconsistente: a cláusula nova diz 30
dias e a antiga, que ninguém regenerou, continua dizendo 15. Três
anteparos:

  * o mapa é conservador. Um campo alcança TODA cláusula que possa
    citá-lo, não só a "principal". `prazo` no TR alcança sete
    cláusulas, porque prazo aparece em execução, recebimento,
    pagamento e sanção;
  * campo sem mapa declarado (ou documento fora do mapa) NÃO é
    regeneração parcial: é regeneração inteira, como hoje. A ausência
    de regra nunca vira permissão;
  * a aplicação é conferida: se o modelo devolver cláusula que não foi
    pedida, faltar alguma que foi, ou a substituição tocar em cláusula
    fora do escopo, o resultado é REJEITADO e o caminho volta a ser a
    regeneração inteira. Documento pela metade não sai daqui.

Feature flag `regeneracao_parcial` (default OFF).
"""

from __future__ import annotations

import re

from . import db, perfis
from .config import CAMPOS_FORMULARIO

FLAG = "regeneracao_parcial"

_RE_CLAUSULA = re.compile(r"(?m)^#{1,3}\s*(\d{1,2})\s*[\.\-–]?\s+(.+?)\s*$")


def ativo() -> bool:
    try:
        return db.flag_ativa(FLAG)
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Que cláusulas cada campo alcança — DECLARADO, e de propósito generoso
#
# A regra de curadoria: na dúvida, INCLUIR a cláusula. Uma cláusula
# regenerada a mais custa alguns tokens; uma cláusula esquecida deixa o
# documento contradizendo a si mesmo, e isso não aparece na tela.
#
# `itens` e `objeto` NÃO estão em mapa nenhum: eles atravessam o
# documento inteiro (objeto, quantitativo, valor, execução, aceitação,
# pagamento, sanção). Mudá-los é regeneração inteira, e dizer isso aqui
# é mais honesto que um mapa com quinze cláusulas que dá no mesmo.
# ---------------------------------------------------------------------------
MAPA_DE_IMPACTO: dict[str, dict[str, tuple[int, ...]]] = {
    "dfd": {
        "orgao": (1,),
        "responsavel": (1, 9),
        "justificativa": (2, 3),
        "alinhamento": (1, 2),
        "requisitos": (5, 6),
        "modelo_execucao": (4, 6),
        "prazo": (1, 8),
        "riscos": (2, 3),
        "memorando": (2, 3, 4),
    },
    "etp": {
        "orgao": (1,),
        "responsavel": (1, 16),
        "justificativa": (2, 12),
        "alinhamento": (3,),
        "requisitos": (4, 6),
        # a modelagem é a decisão central do estudo: alcança o
        # levantamento, a solução, o parcelamento e a conclusão
        "modelo_execucao": (5, 6, 10, 15, 17),
        "prazo": (13, 15),
        "riscos": (9, 13),
        "memorando": (2, 12),
    },
    "mapa_riscos": {
        # o Mapa não segue os perfis de cláusula (é uma matriz). Sem
        # cláusula endereçável não há regeneração parcial possível, e
        # fingir que há seria recortar às cegas.
    },
    "tr": {
        "orgao": (1,),
        "responsavel": (14,),
        "justificativa": (2,),
        # a previsão no PCA é citada na fundamentação da contratação
        "alinhamento": (2,),
        "requisitos": (3, 4, 7),
        "modelo_execucao": (3, 5, 6, 17),
        # prazo atravessa execução, formalização, recebimento,
        # pagamento, liquidação e sanção — todas podem citá-lo
        "prazo": (5, 6, 7, 10, 11, 12, 15),
        "riscos": (5, 9, 14),
        "memorando": (2,),
    },
}

# Campos que, por si, exigem documento inteiro. Declarados para que a
# decisão seja visível no diff e não uma ausência no mapa.
CAMPOS_QUE_EXIGEM_DOCUMENTO_INTEIRO = frozenset({"objeto", "itens"})

# Nenhuma regeneração parcial vale a pena se ela tocar quase tudo: o
# prompt fica do tamanho do documento e a conferência fica mais frágil
# sem economia em troca.
PROPORCAO_MAXIMA_DE_CLAUSULAS = 0.5


def campos_alterados(antes: dict | None, depois: dict | None) -> list[str]:
    """
    Campos do formulário cujo valor mudou.

    Compara só o que o formulário define — chaves internas (`_fluxo_…`)
    não são dado do processo e não podem disparar regeneração.
    """
    antes, depois = antes or {}, depois or {}
    return sorted(campo for campo in CAMPOS_FORMULARIO
                  if antes.get(campo) != depois.get(campo))


def clausulas_afetadas(doc_key: str, campos: list[str]) -> set[int] | None:
    """
    Cláusulas a regenerar, ou None quando o documento tem de sair
    inteiro.

    None em quatro situações, todas deliberadas: campo que atravessa o
    documento (`objeto`, `itens`); documento sem mapa (`mapa_riscos`);
    campo sem regra declarada; e alteração que alcançaria metade ou
    mais das cláusulas — aí a regeneração parcial deixa de economizar.
    """
    mapa = MAPA_DE_IMPACTO.get(doc_key)
    if not mapa or not campos:
        return None
    if set(campos) & CAMPOS_QUE_EXIGEM_DOCUMENTO_INTEIRO:
        return None
    alcancadas: set[int] = set()
    for campo in campos:
        regra = mapa.get(campo)
        if regra is None:
            return None      # campo sem regra: nunca presumir que não afeta
        alcancadas.update(regra)
    if not alcancadas:
        return None
    total = len(perfis.PERFIS[doc_key]["clausulas"])
    if len(alcancadas) >= total * PROPORCAO_MAXIMA_DE_CLAUSULAS:
        return None
    return alcancadas


# ---------------------------------------------------------------------------
# Recorte e recomposição
# ---------------------------------------------------------------------------
def dividir_por_clausula(texto: str) -> dict[int, str]:
    """{número: texto completo da cláusula} — primeira ocorrência de cada."""
    achados = list(_RE_CLAUSULA.finditer(texto or ""))
    fatias: dict[int, str] = {}
    for i, m in enumerate(achados):
        numero = int(m.group(1))
        if numero in fatias:
            continue
        fim = achados[i + 1].start() if i + 1 < len(achados) else len(texto)
        fatias[numero] = texto[m.start():fim].rstrip()
    return fatias


class RecorteRejeitado(Exception):
    """A resposta parcial não passou na conferência — nada foi aplicado."""


def aplicar(texto_atual: str, resposta: str, pedidas: set[int]) -> str:
    """
    Substitui no texto vigente APENAS as cláusulas pedidas.

    Levanta `RecorteRejeitado` — e o chamador cai para a regeneração
    inteira — quando:
      * a resposta traz cláusula que não foi pedida (o modelo reescreveu
        o que não devia);
      * falta alguma que foi pedida (o documento ficaria com a versão
        velha de um dado que mudou);
      * o texto vigente não tem alguma das cláusulas pedidas (não há o
        que substituir);
      * o resultado perdeu ou ganhou cláusula.

    A conferência é sobre o CONJUNTO de cláusulas, e não sobre o
    tamanho do texto: um documento que mantém o número de caracteres e
    troca a cláusula errada passaria por qualquer verificação de
    tamanho.
    """
    atuais = dividir_por_clausula(texto_atual)
    novas = dividir_por_clausula(resposta)
    if not novas:
        raise RecorteRejeitado("a resposta não trouxe cláusula numerada")
    if set(novas) - pedidas:
        raise RecorteRejeitado(
            f"a resposta reescreveu cláusula fora do escopo: "
            f"{sorted(set(novas) - pedidas)}")
    if pedidas - set(novas):
        raise RecorteRejeitado(
            f"a resposta não trouxe as cláusulas {sorted(pedidas - set(novas))}")
    if pedidas - set(atuais):
        raise RecorteRejeitado(
            f"o documento vigente não tem as cláusulas "
            f"{sorted(pedidas - set(atuais))}")

    resultado = texto_atual
    # De trás para frente: substituir a cláusula 2 muda os índices da 5,
    # e fazer na ordem direta trocaria o texto no lugar errado.
    for numero in sorted(pedidas, reverse=True):
        resultado = resultado.replace(atuais[numero], novas[numero], 1)

    conferencia = dividir_por_clausula(resultado)
    if set(conferencia) != set(atuais):
        raise RecorteRejeitado(
            "a substituição alterou o conjunto de cláusulas do documento")
    intocadas = set(atuais) - pedidas
    divergentes = [n for n in intocadas if conferencia[n] != atuais[n]]
    if divergentes:
        raise RecorteRejeitado(
            f"cláusulas fora do escopo foram alteradas: {sorted(divergentes)}")
    return resultado


# ---------------------------------------------------------------------------
# O pedido ao modelo
# ---------------------------------------------------------------------------
def instrucoes_de_recorte(doc_key: str, pedidas: set[int],
                          campos: list[str], texto_atual: str) -> str:
    """
    O bloco que transforma "gere o documento" em "reescreva estas
    cláusulas".

    Manda o documento vigente como REFERÊNCIA DE COERÊNCIA — sem ele o
    modelo reescreveria as cláusulas sem saber o que o resto do
    documento afirma, e produziria exatamente a contradição que esta
    funcionalidade existe para evitar. É mais barato que regerar tudo
    porque o que se PAGA de saída cai de dezessete cláusulas para duas,
    e porque o documento entra sem as tabelas.
    """
    from . import resumo_processo

    titulos = {c["n"]: c["titulo"]
               for c in perfis.PERFIS[doc_key]["clausulas"]}
    lista = "; ".join(f"{n}. {titulos.get(n, '')}" for n in sorted(pedidas))
    rotulos = ", ".join(CAMPOS_FORMULARIO[c]["rotulo"] for c in campos
                        if c in CAMPOS_FORMULARIO)
    return (
        "\n\n=== ATUALIZAÇÃO PARCIAL — REESCREVA APENAS AS CLÁUSULAS "
        "INDICADAS ===\n"
        f"O documento abaixo já foi aprovado. Mudaram no processo: "
        f"{rotulos}.\n"
        f"Reescreva EXCLUSIVAMENTE estas cláusulas, com a MESMA numeração "
        f"e os MESMOS títulos: {lista}.\n"
        "REGRAS DESTA TAREFA:\n"
        "1. Devolva SOMENTE as cláusulas pedidas, cada uma começando pelo "
        "seu título no formato '## N. TÍTULO'. Nenhuma outra cláusula, "
        "nenhum comentário antes ou depois.\n"
        "2. O restante do documento NÃO será reescrito e continuará "
        "valendo. Escreva as cláusulas de modo COERENTE com ele — é "
        "PROIBIDO afirmar nas cláusulas novas algo que contradiga o que "
        "as demais dizem.\n"
        "3. Onde a cláusula precisar da tabela de itens, mantenha o "
        "marcador [[TABELA_ITENS]] no lugar: a tabela é injetada por "
        "código.\n"
        "4. Todas as regras do documento continuam valendo, inclusive o "
        "uso de [PREENCHER: descrição] para dado ausente.\n\n"
        "=== DOCUMENTO VIGENTE (referência de coerência; não o "
        "reescreva) ===\n"
        + resumo_processo.sem_tabelas(texto_atual))
