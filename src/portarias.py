"""
Portaria vigente: resolução determinística por DATA DE REFERÊNCIA.

O PROBLEMA QUE ISTO RESOLVE

Um DFD de janeiro cita a Equipe de Planejamento designada pela portaria
que valia em janeiro. Se o sistema perguntar "qual a portaria ativa
hoje?", o documento reaberto em dezembro passa a citar outra portaria —
e o documento histórico mente sobre o ato que o fundamentou.

Por isso toda resolução aqui recebe uma `data_referencia` explícita.
Não há função que use `hoje` por padrão escondido: quem chama declara a
data, e a decisão de QUAL data usar está documentada em
`docs/MULTI_PREFEITURAS.md`.

O CONFLITO NÃO É RESOLVIDO POR ARBÍTRIO

Se duas portarias do mesmo tipo estiverem vigentes na mesma secretaria
na mesma data, este módulo NÃO escolhe — nem a mais recente, nem a de
número maior. Ele levanta `PortariaAmbigua`.

Escolher em silêncio seria pior que falhar: o documento sairia citando
uma portaria plausível, o servidor assinaria, e o erro só apareceria
numa auditoria do tribunal de contas. Duas portarias vigentes é um
defeito do cadastro, e cadastro com defeito se conserta no painel — não
se contorna no gerador.

Módulo PURO: recebe as portarias já lidas do banco e decide. Sem rede,
sem sessão.
"""

from __future__ import annotations

import datetime as _dt

ATIVA = "ATIVA"
RASCUNHO = "RASCUNHO"
REVOGADA = "REVOGADA"
EXPIRADA = "EXPIRADA"
FUTURA = "FUTURA"

# Só ATIVA vale. RASCUNHO ainda não é ato; REVOGADA deixou de ser;
# EXPIRADA e FUTURA são rótulos de conveniência para a tela — a
# vigência real é decidida pelas datas, abaixo.
STATUS_QUE_VIGORA = (ATIVA,)

EQUIPE_PLANEJAMENTO = "EQUIPE_PLANEJAMENTO"


class ErroPortaria(Exception):
    """Base — permite ao chamador tratar as duas como um caso só."""


class PortariaAmbigua(ErroPortaria):
    """Mais de uma portaria vigente para o mesmo tipo, secretaria e data."""


def _data(valor) -> _dt.date | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, _dt.datetime):
        return valor.date()
    if isinstance(valor, _dt.date):
        return valor
    try:
        return _dt.date.fromisoformat(str(valor)[:10])
    except ValueError:
        # Data ilegível NÃO vira "vigente desde sempre": devolver None
        # aqui faria `vigente_em` tratar a portaria como sem início, que
        # é o oposto do conservador. Quem não sabe a data não vigora.
        raise ErroPortaria(f"data ilegível na portaria: {valor!r}") from None


def vigente_em(portaria: dict, data_referencia: _dt.date) -> bool:
    """
    A portaria valia NAQUELE dia?

    Status e janela, os dois. Uma portaria pode ser revogada antes do fim
    da vigência declarada, e nenhuma conta de data descobre isso — por
    isso o status é consultado, e não derivado.
    """
    if (portaria.get("status") or "").strip().upper() not in STATUS_QUE_VIGORA:
        return False
    inicio = _data(portaria.get("data_inicio_vigencia"))
    if inicio is None or inicio > data_referencia:
        return False
    fim = _data(portaria.get("data_fim_vigencia"))
    return fim is None or fim >= data_referencia


def resolver(portarias: list[dict], *, secretaria_id: str | None,
             tipo: str = EQUIPE_PLANEJAMENTO,
             data_referencia: _dt.date) -> dict | None:
    """
    A portaria vigente, ou `None` se não houver.

    `None` é resposta legítima e comum: uma secretaria que ainda não
    cadastrou portaria não é um erro do sistema. Quem trata a ausência é
    o gerador de documento, que põe o marcador de pendência em vez de
    inventar um número (ver `src/assinaturas.py`).

    Levanta `PortariaAmbigua` quando há mais de uma. Ver o cabeçalho.
    """
    candidatas = [
        p for p in portarias
        if (p.get("tipo") or EQUIPE_PLANEJAMENTO) == tipo
        and p.get("secretaria_id") == secretaria_id
        and vigente_em(p, data_referencia)
    ]
    if not candidatas:
        return None
    if len(candidatas) > 1:
        numeros = ", ".join(
            f"{p.get('numero')}/{p.get('ano')}" for p in candidatas)
        raise PortariaAmbigua(
            f"Há mais de uma portaria vigente do tipo {tipo} nesta "
            f"secretaria em {data_referencia:%d/%m/%Y}: {numeros}. "
            "Revogue ou ajuste a vigência de uma delas no painel "
            "administrativo — o sistema não escolhe por você.")
    return candidatas[0]


def situacao(portaria: dict, data_referencia: _dt.date) -> str:
    """
    O rótulo para a tela do histórico (§54): ATIVA, FUTURA, EXPIRADA,
    REVOGADA ou RASCUNHO.

    Derivado, e não lido da coluna, porque a coluna guarda a DECISÃO
    administrativa (revogar) e a tela precisa mostrar também o efeito do
    tempo — uma portaria ATIVA cuja vigência acabou aparece como
    EXPIRADA sem que ninguém precise rodar um job noturno para atualizar
    a coluna.
    """
    declarado = (portaria.get("status") or "").strip().upper()
    if declarado in (REVOGADA, RASCUNHO):
        return declarado
    inicio = _data(portaria.get("data_inicio_vigencia"))
    if inicio and inicio > data_referencia:
        return FUTURA
    fim = _data(portaria.get("data_fim_vigencia"))
    if fim and fim < data_referencia:
        return EXPIRADA
    return ATIVA if declarado == ATIVA else declarado or RASCUNHO


def membros_vigentes(membros: list[dict]) -> list[dict]:
    """Os membros ativos da portaria, na ordem declarada."""
    return sorted(
        (m for m in membros if m.get("ativo", True)),
        key=lambda m: (m.get("ordem", 100), (m.get("nome") or "")),
    )


def citacao(portaria: dict | None) -> str:
    """
    A frase que entra no documento.

    Sem portaria, devolve o MARCADOR de pendência do projeto — nunca um
    número inventado. É a mesma convenção que o gerador já usa para dado
    faltante, e é ela que a revisão transforma em pergunta ao servidor.
    """
    if not portaria:
        return ("[PREENCHER: número e data da Portaria da Equipe de "
                "Planejamento desta secretaria]")
    numero = portaria.get("numero") or "?"
    ano = portaria.get("ano") or "?"
    publicacao = _data(portaria.get("data_publicacao"))
    if publicacao:
        meses = ("janeiro", "fevereiro", "março", "abril", "maio", "junho",
                 "julho", "agosto", "setembro", "outubro", "novembro",
                 "dezembro")
        por_extenso = (f"{publicacao.day} de {meses[publicacao.month - 1]} "
                       f"de {publicacao.year}")
        return (f"Portaria nº {numero}/{ano}, publicada em {por_extenso}")
    return f"Portaria nº {numero}/{ano}"
