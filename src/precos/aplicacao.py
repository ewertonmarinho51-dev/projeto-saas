"""
Aplicação da pesquisa ao processo (§26 e §27).

Este é o ponto em que um número deixa de ser resultado de pesquisa e
passa a ser **valor estimado da contratação** — o que vai para o DFD, o
ETP, o TR e o edital, e o que sustenta o ato administrativo. Por isso o
módulo inteiro é construído em torno de uma frase do §26: *"não alterar
documento silenciosamente"*.

Quatro regras que ele impõe, cada uma contra um jeito específico de
errar:

**1. Casamento verificado, nunca por posição cega.** A planilha do
processo pode ter sido editada depois que a pesquisa foi criada. Aplicar
por índice acertaria o item 1 e escreveria o preço da caneta no
grampeador a partir da primeira linha inserida. Aqui cada par é
CONFERIDO, e o que não confere **não é aplicado** — é devolvido como
recusa nomeada.

**2. Diff antes, sempre.** `calcular_diff` existe para a tela mostrar o
antes e o depois de cada item ANTES de qualquer escrita. Aplicar e depois
avisar seria a mesma coisa que não avisar.

**3. Proveniência fora da tabela do documento.** O §27 é explícito: DFD,
ETP e TR não reproduzem a pesquisa; consomem só o fato de que precisam.
`planilha.colunas_extra` transforma qualquer chave nova do item em COLUNA
da tabela exportada — então a memória da pesquisa **não** pode virar
campo de item. Ela vai para `dados['pesquisa_preco']`, um objeto à parte,
e o item recebe apenas o ponteiro curto no campo `fonte`, que já existe
para isso.

**4. Nada aqui escreve no banco nem na sessão.** Todas as funções são
puras: recebem dicionários, devolvem dicionários novos. Quem persiste,
invalida documentos e registra trilha é a interface — e assim a decisão
de aplicar fica visível no ponto onde é tomada.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .. import planilha
from .estados import EstadoItem

# Onde mora o objeto estruturado do §27 dentro de `dados`. NÃO é campo de
# item: `planilha.colunas_extra` viraria isso numa coluna da tabela de
# todo documento exportado.
CHAVE_PROVENIENCIA = "pesquisa_preco"

# Tolerância de comparação monetária. Um centavo — abaixo disso é ruído
# de arredondamento, não mudança de preço.
CENTAVO = Decimal("0.01")


def _decimal(valor) -> Decimal | None:
    if valor in (None, ""):
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _normalizar(texto) -> str:
    """Compara descrição sem acento, sem caixa e sem espaço repetido."""
    bruto = unicodedata.normalize("NFKD", str(texto or ""))
    sem_acento = "".join(c for c in bruto if not unicodedata.combining(c))
    return " ".join(sem_acento.upper().split())


# ---------------------------------------------------------------------------
# §27 — o objeto estruturado que o resto do sistema consome
# ---------------------------------------------------------------------------
def estimativa_estruturada(pesquisa: dict, itens: list[dict]) -> dict:
    """
    O que o processo guarda sobre a pesquisa — e nada além disso.

    Deliberadamente pequeno. A memória completa (todas as referências,
    todos os scores, todos os payloads) fica na pesquisa e no relatório;
    o processo carrega o suficiente para dizer, meses depois, de onde
    veio o preço e sob qual regra ele foi formado.

    `fontes` são os IDs das fontes efetivamente usadas — não a lista de
    tudo que foi consultado. É o que responde "este preço veio de onde?".
    """
    metodos = sorted({str(i.get("metodo") or "") for i in itens
                      if i.get("metodo")})
    concluidos = [i for i in itens
                  if str(i.get("estado")) == EstadoItem.COMPLETO.value]
    return {
        "id": str(pesquisa.get("id") or ""),
        "versao": int(pesquisa.get("versao") or 1),
        "raiz_id": str(pesquisa.get("raiz_id") or pesquisa.get("id") or ""),
        "nome": str(pesquisa.get("nome") or ""),
        "estado": str(pesquisa.get("estado") or ""),
        "perfil_normativo": str(pesquisa.get("perfil_normativo") or ""),
        "data_base": str(pesquisa.get("data_base") or ""),
        "metodologia": ", ".join(metodos) if metodos else "",
        "itens_aplicados": len(concluidos),
        "itens_totais": len(itens),
        # Quanto a PESQUISA somou, nas quantidades dela. É informativo, e
        # não serve para conferir o processo: o processo tem itens que a
        # pesquisa não cobriu e quantidades que podem ter mudado.
        "valor_global_da_pesquisa": _texto(_soma_dos_itens(concluidos)),
        # Quanto o PROCESSO passou a valer no momento da aplicação. É
        # ESTE o número que a conferência posterior compara — preenchido
        # por `aplicar`, que é quem conhece a planilha inteira.
        "valor_global_aplicado": None,
        "versao_algoritmo": str(pesquisa.get("versao_algoritmo") or ""),
        "versao_regras": str(pesquisa.get("versao_regras") or ""),
    }


def _soma_dos_itens(itens: list[dict]) -> Decimal:
    total = Decimal("0")
    for item in itens:
        valor = _decimal(item.get("preco_total"))
        if valor is not None:
            total += valor
    return total


def _texto(valor: Decimal | None) -> str | None:
    return None if valor is None else format(valor, "f")


def ponteiro_da_fonte(pesquisa: dict, item: dict) -> str:
    """
    O que vai no campo `fonte` do item — curto, porque vira célula de
    tabela em todo documento exportado.

    Diz o essencial para quem lê o documento: que o preço veio de
    pesquisa formal, por qual método, e com quantas referências. O resto
    está no relatório.
    """
    metodo = str(item.get("metodo") or "").strip()
    memoria = item.get("estatisticas") or {}
    estatisticas = memoria.get("estatisticas") or {}
    n = estatisticas.get("quantidade")
    versao = int(pesquisa.get("versao") or 1)
    # A revisão entra no ponteiro quando existe: dois documentos do mesmo
    # processo podem ter saído de revisões diferentes da mesma pesquisa,
    # e sem o número não há como saber qual sustentou qual.
    cabeca = ("Pesquisa de preços" if versao <= 1
              else f"Pesquisa de preços (rev. {versao})")
    partes = [cabeca]
    if metodo:
        partes.append(metodo)
    if n:
        partes.append(f"n={n}")
    return " · ".join(partes)


# ---------------------------------------------------------------------------
# Casamento
# ---------------------------------------------------------------------------
@dataclass
class Casamento:
    """
    Um item do processo emparelhado (ou não) com um item da pesquisa.

    `confere` é o que decide se o preço vai ser escrito. Ele existe
    separado de "encontrou" porque os dois casos exigem respostas
    diferentes: não encontrar é normal (o processo tem item que a
    pesquisa não cobriu); encontrar algo que não bate é PERIGOSO, e tem
    de parar.
    """

    posicao: int
    item_processo: dict
    item_pesquisa: dict | None = None
    confere: bool = False
    motivo: str = ""


def casar(itens_processo: list[dict],
          itens_pesquisa: list[dict]) -> list[Casamento]:
    """
    Emparelha por DESCRIÇÃO normalizada, com o código como desempate.

    Não por posição. A planilha do processo pode ter ganhado ou perdido
    linhas depois que a pesquisa foi criada, e casar por índice
    escreveria o preço de um item no item seguinte — em silêncio, e com
    aparência de correção.

    A ordem das tentativas é da evidência mais forte para a mais fraca:

    1. **código de catálogo igual** — quando os dois lados o têm, é
       identidade declarada e vence;
    2. **descrição normalizada igual** — sem acento, sem caixa, sem
       espaço repetido;
    3. nada disso: o item fica SEM par, e é dito.

    Cada item da pesquisa é consumido no máximo uma vez: duas linhas da
    planilha com a mesma descrição não podem receber o mesmo preço duas
    vezes sem que alguém veja.
    """
    disponiveis = list(itens_pesquisa or [])
    por_codigo: dict[str, dict] = {}
    por_descricao: dict[str, dict] = {}
    for item in disponiveis:
        codigo = str(item.get("codigo") or "").strip()
        if codigo and codigo not in por_codigo:
            por_codigo[codigo] = item
        chave = _normalizar(item.get("descricao"))
        if chave and chave not in por_descricao:
            por_descricao[chave] = item

    usados: set[int] = set()
    casamentos: list[Casamento] = []
    for posicao, do_processo in enumerate(itens_processo or [], start=1):
        codigo = str(do_processo.get("codigo") or "").strip()
        descricao = _normalizar(do_processo.get("descricao"))

        candidato = None
        if codigo and codigo in por_codigo:
            candidato = por_codigo[codigo]
        elif descricao and descricao in por_descricao:
            candidato = por_descricao[descricao]

        if candidato is None:
            casamentos.append(Casamento(
                posicao, do_processo, None, False,
                "não há item correspondente na pesquisa"))
            continue
        if id(candidato) in usados:
            casamentos.append(Casamento(
                posicao, do_processo, None, False,
                "o item da pesquisa que corresponderia já foi usado por "
                "outra linha da planilha"))
            continue

        problema = _conferir(do_processo, candidato)
        usados.add(id(candidato))
        casamentos.append(Casamento(
            posicao, do_processo, candidato, not problema, problema))
    return casamentos


def _conferir(do_processo: dict, da_pesquisa: dict) -> str:
    """
    O par bate? Devolve o motivo quando NÃO bate, e "" quando bate.

    Conferir a descrição mesmo depois de casar por código não é
    redundância: código igual com descrição completamente diferente é
    sinal de que alguém editou a planilha, e escrever o preço nesse caso
    seria o erro mais caro possível.
    """
    if str(da_pesquisa.get("estado")) != EstadoItem.COMPLETO.value:
        return ("o item da pesquisa não está concluído — nenhum preço "
                "sem revisão humana vai para o processo")
    if _decimal(da_pesquisa.get("preco_estimado")) is None:
        return "o item da pesquisa não tem preço formado"

    if (_normalizar(do_processo.get("descricao"))
            != _normalizar(da_pesquisa.get("descricao"))):
        return ("a descrição do item mudou na planilha depois da pesquisa "
                "— confira antes de aplicar")

    unidade_processo = _normalizar(do_processo.get("unidade"))
    unidade_pesquisa = _normalizar(da_pesquisa.get("unidade"))
    if unidade_processo and unidade_pesquisa and \
            unidade_processo != unidade_pesquisa:
        return (f"a unidade diverge: planilha em {unidade_processo}, "
                f"pesquisa em {unidade_pesquisa}")

    # Quantidade divergente NÃO impede: o preço unitário continua válido
    # e o total é recalculado pela quantidade da PLANILHA, que é a do
    # processo. Mas precisa aparecer no diff — e aparece, como aviso em
    # `calcular_diff`.
    return ""


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------
@dataclass
class Mudanca:
    """Uma linha do diff do §26 — o antes, o depois e o porquê."""

    posicao: int
    descricao: str
    unitario_atual: Decimal | None
    unitario_novo: Decimal | None
    quantidade: Decimal | None
    fonte_atual: str = ""
    fonte_nova: str = ""
    avisos: list[str] = field(default_factory=list)

    @property
    def mudou(self) -> bool:
        atual = self.unitario_atual or Decimal("0")
        novo = self.unitario_novo or Decimal("0")
        return abs(novo - atual) >= CENTAVO or self.fonte_atual != self.fonte_nova

    @property
    def total_atual(self) -> Decimal:
        return (self.unitario_atual or Decimal("0")) * \
            (self.quantidade or Decimal("0"))

    @property
    def total_novo(self) -> Decimal:
        return (self.unitario_novo or Decimal("0")) * \
            (self.quantidade or Decimal("0"))


def calcular_diff(pesquisa: dict,
                  casamentos: list[Casamento]) -> tuple[list[Mudanca],
                                                        list[str]]:
    """
    (mudanças a aplicar, recusas nomeadas).

    As recusas não são erro: são a parte da planilha que a pesquisa não
    cobre ou não confere. Elas aparecem na tela junto com as mudanças,
    porque "48 de 50 itens" é a informação que decide se vale aplicar
    agora ou terminar a pesquisa antes.
    """
    mudancas: list[Mudanca] = []
    recusas: list[str] = []
    for casamento in casamentos:
        if not casamento.confere:
            recusas.append(
                f"Item {casamento.posicao:02d} "
                f"({str(casamento.item_processo.get('descricao') or '')[:60]}): "
                f"{casamento.motivo}")
            continue

        do_processo = casamento.item_processo
        da_pesquisa = casamento.item_pesquisa or {}
        quantidade = _decimal(do_processo.get("quantidade"))
        mudanca = Mudanca(
            posicao=casamento.posicao,
            descricao=str(do_processo.get("descricao") or ""),
            unitario_atual=_decimal(do_processo.get("valor_unitario")),
            unitario_novo=_decimal(da_pesquisa.get("preco_estimado")),
            quantidade=quantidade,
            fonte_atual=str(do_processo.get(planilha.CAMPO_FONTE) or ""),
            fonte_nova=ponteiro_da_fonte(pesquisa, da_pesquisa),
        )

        quantidade_pesquisa = _decimal(da_pesquisa.get("quantidade"))
        if (quantidade is not None and quantidade_pesquisa is not None
                and quantidade != quantidade_pesquisa):
            mudanca.avisos.append(
                f"a pesquisa formou o preço para {quantidade_pesquisa:g} "
                f"unidade(s) e a planilha tem {quantidade:g} — o total "
                "será recalculado pela quantidade da planilha")
        if mudanca.fonte_atual and mudanca.fonte_atual != mudanca.fonte_nova:
            mudanca.avisos.append(
                f"a fonte informada à mão será substituída "
                f"(\"{mudanca.fonte_atual[:40]}\")")
        mudancas.append(mudanca)
    return mudancas, recusas


def valor_global_apos(dados: dict, mudancas: list[Mudanca]) -> Decimal:
    """Quanto o processo passará a valer. Usado no aviso, antes de aplicar."""
    aplicadas = {m.posicao: m for m in mudancas}
    total = Decimal("0")
    for posicao, item in enumerate(dados.get("itens") or [], start=1):
        mudanca = aplicadas.get(posicao)
        if mudanca is not None:
            total += mudanca.total_novo
            continue
        unitario = _decimal(item.get("valor_unitario")) or Decimal("0")
        quantidade = _decimal(item.get("quantidade")) or Decimal("0")
        total += unitario * quantidade
    return total


# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------
def aplicar(dados: dict, pesquisa: dict,
            itens_pesquisa: list[dict]) -> tuple[dict, list[Mudanca],
                                                 list[str]]:
    """
    Devolve `(dados novos, mudanças, recusas)` — SEM tocar no original.

    Trabalhar sobre cópia não é preciosismo: a tela mostra o diff, o
    usuário pode desistir, e um `dados` mutado no meio do caminho
    deixaria o processo alterado por uma confirmação que nunca veio.

    O total de cada item e o valor global saem de `planilha.calcular`, e
    não de conta feita aqui — dois lugares calculando dinheiro é como
    eles passam a discordar.
    """
    itens_processo = list(dados.get("itens") or [])
    casamentos = casar(itens_processo, itens_pesquisa)
    mudancas, recusas = calcular_diff(pesquisa, casamentos)

    novos_itens = [dict(item) for item in itens_processo]
    por_posicao = {m.posicao: m for m in mudancas}
    for posicao, item in enumerate(novos_itens, start=1):
        mudanca = por_posicao.get(posicao)
        if mudanca is None or mudanca.unitario_novo is None:
            continue
        item["valor_unitario"] = float(mudanca.unitario_novo)
        item[planilha.CAMPO_FONTE] = mudanca.fonte_nova

    calculados, valor_global = planilha.calcular(novos_itens)

    novos_dados = dict(dados)
    novos_dados["itens"] = calculados
    novos_dados["valor_estimado"] = valor_global
    proveniencia = estimativa_estruturada(pesquisa, itens_pesquisa)
    # O valor do PROCESSO no instante da aplicação. É a única grandeza
    # que a conferência posterior pode comparar contra `valor_estimado`;
    # o total da pesquisa é outra coisa e compará-lo daria divergência
    # em quase toda aplicação real — ver `divergencia_do_valor`.
    # Quantizado em centavos: `planilha.calcular` devolve `float`, e
    # `str(235.0)` guardaria "235.0". Valor monetário com escala variável
    # é o tipo de detalhe que passa despercebido até alguém comparar dois
    # registros como texto.
    proveniencia["valor_global_aplicado"] = _texto(
        (_decimal(valor_global) or Decimal("0")).quantize(CENTAVO))
    novos_dados[CHAVE_PROVENIENCIA] = proveniencia
    return novos_dados, mudancas, recusas


# ---------------------------------------------------------------------------
# Conferência posterior
# ---------------------------------------------------------------------------
def divergencia_do_valor(dados: dict) -> str | None:
    """
    O processo ainda vale o que a pesquisa aplicada disse?

    Depois de aplicar, nada impede o servidor de editar a planilha à mão
    — e é legítimo que edite. O que não pode é a proveniência seguir
    dizendo que aquele valor veio da pesquisa quando o valor já mudou.

    A comparação é contra `valor_global_aplicado` — o total do PROCESSO
    no instante da aplicação —, e não contra o total da pesquisa. A
    primeira versão comparava contra o total da pesquisa e teria
    disparado em quase toda aplicação real: o processo costuma ter itens
    que a pesquisa não cobriu, e as quantidades da planilha podem
    divergir das que formaram o preço. Um alerta que acende sempre é
    ignorado, e aí o caso verdadeiro passa junto.

    `None` quando não há pesquisa aplicada ou quando os dois batem.
    """
    proveniencia = dados.get(CHAVE_PROVENIENCIA) or {}
    no_momento = _decimal(proveniencia.get("valor_global_aplicado"))
    if no_momento is None:
        return None
    agora = _decimal(dados.get("valor_estimado"))
    if agora is None:
        return None
    if abs(agora - no_momento) < CENTAVO:
        return None
    return (
        f"o valor global do processo "
        f"({planilha.formatar_moeda(float(agora))}) mudou depois que a "
        f"pesquisa de preços foi aplicada "
        f"({planilha.formatar_moeda(float(no_momento))}) — a proveniência "
        "registrada já não descreve o valor atual")
