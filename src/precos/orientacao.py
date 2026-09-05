"""
Orientação do GovBot na pesquisa de preços (§28).

O §28 pede que o GovBot **explique, oriente, ajude a filtrar e sugira** —
sem inventar preço nem fonte, e sem virar um segundo chatbot. Os três
exemplos que o próprio prompt dá são reveladores:

    GovBot: Encontrei apenas duas referências seguras para este item.
    GovBot: Este preço parece muito distante da mediana. Quer ver o motivo?
    GovBot: A unidade desta referência é caixa, enquanto seu item está
            em unidade.

**Nenhum deles precisa de IA.** Os três são leitura do que o motor
determinístico já calculou: a contagem da cesta, a distância da mediana,
a unidade que não pôde ser convertida. Escrever isso com modelo de
linguagem seria pagar latência, custo e risco de invenção para dizer um
número que já está na mesa.

Por isso a orientação mora aqui, separada da camada semântica: ela é
**inteiramente determinística**, roda sem credencial, e continua
funcionando quando a IA está fora do ar. A `semantica.py` cuida do que
realmente exige interpretação — sinônimos, equivalência de descrição,
prosa explicativa.

Três regras que este módulo impõe:

1. **nenhuma mensagem afirma o que não foi medido.** Cada uma nasce de um
   campo concreto, e o texto diz de onde veio;
2. **nenhuma conclui juridicamente.** Dispersão estatística vira
   "confira", nunca "inexequível" ou "irregular" — a mesma regra do §23
   que vale para a tela e para o relatório;
3. **nenhuma decide pelo servidor.** Toda mensagem termina em pergunta ou
   em sugestão de ação; a decisão continua sendo dele.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .estados import EstadoItem
from .perfil import PerfilNormativo
from .perfil import obter as obter_perfil

# Severidades. Não são decorativas: a interface ordena por elas, e o
# servidor com 210 itens precisa ver primeiro o que pode invalidar a
# pesquisa.
IMPEDE = "impede"        # a pesquisa do item não fecha assim
CONFIRA = "confira"      # há algo que pede olho humano
INFORMA = "informa"      # contexto útil, sem pendência

_ORDEM = {IMPEDE: 0, CONFIRA: 1, INFORMA: 2}

# Distância da mediana a partir da qual vale avisar. Abaixo disso o
# aviso viraria ruído: numa amostra real quase todo preço está a alguma
# distância da mediana.
DISTANCIA_NOTAVEL_PCT = Decimal("50")


@dataclass(frozen=True)
class Orientacao:
    """
    Uma mensagem do GovBot, com a origem do que ela afirma.

    `origem` não é decoração: é o campo de onde o número saiu. Sem ele a
    mensagem seria uma opinião do sistema, e o servidor não teria como
    conferir se ela procede.
    """

    severidade: str
    texto: str
    origem: str
    item_numero: int | None = None
    referencia_id: str | None = None

    @property
    def prefixo(self) -> str:
        return {IMPEDE: "⛔", CONFIRA: "⚠", INFORMA: "ℹ"}.get(
            self.severidade, "ℹ")


def _decimal(valor) -> Decimal | None:
    if valor in (None, ""):
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _ordenar(orientacoes: list[Orientacao]) -> list[Orientacao]:
    """Por severidade e, dentro dela, pela ordem da planilha."""
    return sorted(orientacoes,
                  key=lambda o: (_ORDEM.get(o.severidade, 9),
                                 o.item_numero or 0))


# ---------------------------------------------------------------------------
# Por item
# ---------------------------------------------------------------------------
def do_item(item: dict, referencias: list[dict],
            perfil: PerfilNormativo | None = None) -> list[Orientacao]:
    """
    O que o GovBot tem a dizer sobre UM item.

    Cada mensagem nasce de um campo concreto do item ou das referências —
    nunca de uma impressão sobre o conjunto.
    """
    perfil = perfil or obter_perfil(None)
    numero = int(item.get("numero") or 0)
    estado = str(item.get("estado") or "")
    saida: list[Orientacao] = []

    na_cesta = [r for r in referencias if str(r.get("status")) == "selected"]
    abaixo_do_piso = [r for r in referencias
                      if str(r.get("status")) == "manual_review"]
    sem_conversao = [r for r in referencias
                     if r.get("valor_unitario_normalizado") in (None, "")
                     and r.get("valor_unitario_original") not in (None, "")]

    # 1. A regra dos três — o exemplo literal do §28.
    if estado == EstadoItem.INCOMPLETO.value:
        saida.append(Orientacao(
            IMPEDE,
            f"Encontrei apenas {len(na_cesta)} referência(s) defensável(is) "
            f"para este item, e o perfil {perfil.nome} pede "
            f"{perfil.minimo_referencias}. Nenhum preço foi fabricado para "
            "completar a cesta — amplie a janela de datas, tente sem filtro "
            "de UF, informe o CATMAT/CATSER, ou registre a justificativa "
            "para concluir com menos.",
            origem="item.estado + cesta", item_numero=numero))
    elif na_cesta and len(na_cesta) < perfil.minimo_referencias:
        saida.append(Orientacao(
            CONFIRA,
            f"A cesta deste item tem {len(na_cesta)} referência(s), abaixo "
            f"do mínimo de {perfil.minimo_referencias} do perfil "
            f"{perfil.nome}. Se concluir assim, a justificativa precisa "
            "ficar registrada.",
            origem="cesta", item_numero=numero))

    # 2. Discrepante — o segundo exemplo do §28.
    memoria = item.get("estatisticas") or {}
    for anomalia in (memoria.get("anomalias") or []):
        distancia = _decimal(anomalia.get("distancia_da_mediana_pct"))
        quanto = (f" — está {distancia:.0f}% distante da mediana da amostra"
                  if distancia is not None else "")
        saida.append(Orientacao(
            CONFIRA,
            f"O valor {_moeda(anomalia.get('valor'))} destoa dos demais"
            f"{quanto}. A sinalização é estatística "
            f"(critério {anomalia.get('criterio', '')}) e pede conferência: "
            "ela não afirma que o preço seja inexequível nem irregular. "
            "Quer ver por quê?",
            origem="estatisticas.anomalias", item_numero=numero))

    # 3. Unidade não convertida — o terceiro exemplo do §28.
    for referencia in sem_conversao:
        original = str(referencia.get("unidade_original") or "").strip()
        do_item_ = str(item.get("unidade") or "").strip()
        saida.append(Orientacao(
            CONFIRA,
            f"A unidade desta referência é {original or '(não informada)'}, "
            f"enquanto seu item está em {do_item_ or '(não informada)'}. A "
            "fonte não informou quantos itens a embalagem contém, então o "
            "preço não foi convertido — ela ficou fora da cesta em vez de "
            "entrar com um valor adivinhado.",
            origem="referencia.valor_unitario_normalizado",
            item_numero=numero,
            referencia_id=str(referencia.get("id") or "")))

    # 4. Material disponível que o corte automático deixou de fora.
    if abaixo_do_piso and len(na_cesta) < perfil.minimo_referencias:
        saida.append(Orientacao(
            INFORMA,
            f"Há {len(abaixo_do_piso)} referência(s) abaixo do piso de "
            "comparabilidade automática. Elas não entram sozinhas, mas "
            "estão listadas e podem ser incluídas à mão, com o motivo "
            "registrado.",
            origem="referencia.status", item_numero=numero))

    # 5. Dispersão alta na própria cesta — o preço estimado é mais frágil.
    estatisticas = memoria.get("estatisticas") or {}
    cv = _decimal(estatisticas.get("coeficiente_variacao"))
    if cv is not None and cv > Decimal("0.5") and na_cesta:
        saida.append(Orientacao(
            CONFIRA,
            f"Os preços deste item variam muito entre si (coeficiente de "
            f"variação {cv:.2f}). Foi por isso que o método automático "
            "escolheu a mediana, que resiste a extremos. Vale conferir se "
            "as referências descrevem mesmo o mesmo produto.",
            origem="estatisticas.coeficiente_variacao", item_numero=numero))

    # 6. Falha de fonte no item.
    for ocorrencia in (item.get("ocorrencias") or []):
        saida.append(Orientacao(
            INFORMA,
            f"{ocorrencia}. A pesquisa seguiu nas demais fontes; você pode "
            "repetir a busca deste item mais tarde.",
            origem="item.ocorrencias", item_numero=numero))

    return _ordenar(saida)


def _moeda(valor) -> str:
    from .. import planilha

    numero = _decimal(valor)
    return "(sem valor)" if numero is None else planilha.formatar_moeda(
        float(numero))


# ---------------------------------------------------------------------------
# Da pesquisa inteira
# ---------------------------------------------------------------------------
def da_pesquisa(pesquisa: dict, itens: list[dict],
                referencias: dict[str, list[dict]] | None = None,
                ) -> list[Orientacao]:
    """
    O panorama, para quem tem 210 itens e precisa saber por onde começar.

    Aqui as mensagens são AGREGADAS de propósito: 40 avisos idênticos de
    "unidade não convertida" seriam ruído. O detalhe por item continua
    disponível em `do_item`, na tela de revisão.
    """
    perfil = obter_perfil(pesquisa.get("perfil_normativo"))
    referencias = referencias or {}
    saida: list[Orientacao] = []

    por_estado: dict[str, list[int]] = {}
    for item in itens:
        estado = str(item.get("estado") or EstadoItem.PENDENTE.value)
        por_estado.setdefault(estado, []).append(int(item.get("numero") or 0))

    incompletos = por_estado.get(EstadoItem.INCOMPLETO.value, [])
    com_erro = por_estado.get(EstadoItem.ERRO.value, [])
    por_revisar = por_estado.get(EstadoItem.EM_REVISAO.value, [])

    if incompletos:
        saida.append(Orientacao(
            IMPEDE,
            f"{len(incompletos)} item(ns) não fecharam a cesta mínima do "
            f"perfil {perfil.nome}: {_lista(incompletos)}. Eles não têm "
            "preço formado, e o valor global não os inclui.",
            origem="itens.estado"))

    if com_erro:
        saida.append(Orientacao(
            IMPEDE,
            f"{len(com_erro)} item(ns) pararam por falha técnica na "
            f"consulta: {_lista(com_erro)}. Rode a pesquisa outra vez — "
            "eles voltam para a fila automaticamente.",
            origem="itens.estado"))

    if por_revisar:
        saida.append(Orientacao(
            CONFIRA,
            f"{len(por_revisar)} item(ns) estão com o cálculo pronto e "
            f"aguardando sua confirmação: {_lista(por_revisar)}. O preço "
            "não vale antes da revisão humana.",
            origem="itens.estado"))

    discrepantes = sum(
        len((item.get("estatisticas") or {}).get("anomalias") or [])
        for item in itens)
    if discrepantes:
        saida.append(Orientacao(
            CONFIRA,
            f"{discrepantes} candidato(s) discrepante(s) foram sinalizados "
            "ao longo da pesquisa. Nenhum foi excluído automaticamente: a "
            "exclusão é sua, e fica registrada com o motivo.",
            origem="estatisticas.anomalias"))

    sem_conversao = sum(
        1 for lista in referencias.values() for r in lista
        if r.get("valor_unitario_normalizado") in (None, "")
        and r.get("valor_unitario_original") not in (None, ""))
    if sem_conversao:
        saida.append(Orientacao(
            INFORMA,
            f"{sem_conversao} referência(s) não puderam ter a unidade "
            "convertida porque a fonte não informou a capacidade da "
            "embalagem. Elas ficaram fora da cesta em vez de entrar com "
            "valor adivinhado.",
            origem="referencia.valor_unitario_normalizado"))

    if not saida and itens:
        saida.append(Orientacao(
            INFORMA,
            "Todos os itens fecharam a cesta e passaram pela revisão. A "
            "memória de cálculo está no relatório completo, com as "
            "referências descartadas e o motivo de cada exclusão.",
            origem="itens.estado"))

    return _ordenar(saida)


def _lista(numeros: list[int], limite: int = 10) -> str:
    """Numera os itens sem despejar 210 números na tela."""
    ordenados = sorted(numeros)
    mostrados = ", ".join(f"{n:02d}" for n in ordenados[:limite])
    if len(ordenados) > limite:
        mostrados += f" e mais {len(ordenados) - limite}"
    return mostrados
