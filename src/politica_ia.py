"""
Política de IA: qual modelo, com que teto de saída, para cada tarefa.

Até aqui havia UMA resposta para as duas perguntas, e ela era a mesma
para tudo: o modelo configurado em `OPENAI_MODEL` e
`max_completion_tokens=16384`. Um DFD de 4 mil tokens de saída e uma
resposta JSON de auditoria de 2 mil pediam o mesmo orçamento ao
provedor e corriam no mesmo modelo.

AS DUAS CLASSES DE TAREFA

  redacao      — o documento administrativo. É o produto, vira ato
                 administrativo, e é aqui que a qualidade não se
                 negocia: usa o modelo configurado como principal.
  estruturada  — auditoria, correção por patches, extração,
                 classificação, resposta curta do GovBot. A saída é
                 JSON ou texto curto com forma fixa; o que se exige é
                 obediência a um esquema, não redação. Usa o modelo
                 econômico.

A regra que governa as duas está no enunciado do trabalho e é a razão
de a política existir em vez de um `if` espalhado: *nunca sacrificar a
qualidade documental apenas para reduzir custo*. Por isso nenhum
documento da fase preparatória está na classe econômica, e mover um
para lá é uma mudança deliberada neste arquivo, visível no diff.

OS TETOS DE SAÍDA

Vêm da MEDIÇÃO das gerações reais (`docs/custo/producao.json`), não de
palpite: o teto de cada tarefa é o maior valor observado em produção
com folga. Por que folga, e não o valor observado: um teto justo demais
trunca o documento no meio da cláusula, e documento truncado é dano
muito maior que a economia.

O QUE O TETO FAZ, E O QUE ELE NÃO FAZ

Ele NÃO reduz a fatura por si só — os provedores cobram os tokens
gerados, não os reservados. O teto é guarda: impede que um modelo em
laço gere 16 mil tokens onde o documento pede 4 mil, e torna explícito
qual é o tamanho esperado de cada saída. A redução real de tokens de
saída vem do cache (que não gera nada) e da regeneração por blocos (que
gera duas cláusulas em vez de dezessete).

MODELOS DE RACIOCÍNIO

Para `gpt-5*`/`o1`/`o3`/`o4`, o teto inclui os tokens de raciocínio.
Apertar o teto nesses modelos produz resposta VAZIA, não resposta curta
— foi o que motivou o `_RespostaVazia` do `llm.py`. Por isso o teto
deles é multiplicado por `FOLGA_DE_RACIOCINIO`.
"""

from __future__ import annotations

from . import db

FLAG = "politica_de_modelo"

REDACAO = "redacao"
ESTRUTURADA = "estruturada"

# Tarefa → (classe, teto de saída). A tarefa é o mesmo rótulo que
# `registrar_geracao` grava na coluna `documento` — um só vocabulário.
TAREFAS: dict[str, tuple[str, int]] = {
    # ---- redação: o produto ----------------------------------------
    # teto = maior saída observada em produção, arredondada para cima
    # com folga (dfd 4.152 · etp 8.421 · tr 10.101)
    "dfd": (REDACAO, 6000),
    "etp": (REDACAO, 11000),
    "tr": (REDACAO, 13000),
    # sem medição: o Mapa nunca gerou em produção (era o P0 corrigido na
    # auditoria anterior). Fica no patamar do DFD, que é o documento de
    # porte parecido, e o primeiro processo real ajusta.
    "mapa_riscos": (REDACAO, 8000),
    # o edital e a ARP não passam por modelo; ficam declarados para que
    # a ausência seja escolha visível e não esquecimento
    "edital": (REDACAO, 13000),
    "arp": (REDACAO, 13000),

    # ---- estruturada: forma fixa -----------------------------------
    "auditor": (ESTRUTURADA, 4000),        # maior observado: 2.747
    "corretor": (ESTRUTURADA, 16384),      # maior observado: 14.905
    "analista_parecer": (ESTRUTURADA, 8000),
    "govbot": (ESTRUTURADA, 4000),         # maior observado: 4.923 (falha)
    "pesquisa_precos": (ESTRUTURADA, 4000),
    "semantica_precos": (ESTRUTURADA, 4000),
    "revisao": (ESTRUTURADA, 8000),
}

# Teto de quem não está na tabela. É o valor de hoje: tarefa nova não
# muda de comportamento por esquecimento — muda quando alguém a
# declarar aqui.
TETO_PADRAO = 16384

# Modelos de raciocínio gastam orçamento PENSANDO antes de escrever.
FOLGA_DE_RACIOCINIO = 2.5
_PREFIXOS_DE_RACIOCINIO = ("gpt-5", "o1", "o3", "o4")


def ativo() -> bool:
    try:
        return db.flag_ativa(FLAG)
    except Exception:  # noqa: BLE001
        return False


def classe(tarefa: str) -> str:
    return TAREFAS.get(tarefa, (REDACAO, TETO_PADRAO))[0]


def e_de_raciocinio(modelo: str) -> bool:
    return (modelo or "").lower().startswith(_PREFIXOS_DE_RACIOCINIO)


def teto_de_saida(tarefa: str, modelo: str = "") -> int:
    """
    `max_completion_tokens` para esta tarefa neste modelo.

    Com a flag desligada devolve o valor de sempre — rollback é desligar
    a flag, e um rollback que mudasse o teto não seria rollback.
    """
    if not ativo():
        return TETO_PADRAO
    teto = TAREFAS.get(tarefa, (REDACAO, TETO_PADRAO))[1]
    if e_de_raciocinio(modelo):
        teto = int(teto * FOLGA_DE_RACIOCINIO)
    return min(teto, TETO_PADRAO)


def modelo_economico_configurado() -> str:
    """
    Modelo da classe estruturada, do painel do administrador.

    Vazio = política de modelo inerte: a tarefa estruturada continua
    correndo no modelo principal. É o padrão, e é deliberado — trocar o
    modelo de alguém sem que essa pessoa tenha escolhido o modelo novo
    seria decidir por ela.
    """
    from . import llm

    return llm._ler_chave("OPENAI_MODEL_ECONOMICO", "")  # noqa: SLF001


def modelos_para(tarefa: str, modelos_do_motor: list[str],
                 motor: str) -> list[str]:
    """
    A lista de modelos a tentar, nesta ordem, para esta tarefa.

    Só interfere quando TODAS estas condições valem, e nessa ordem:
      1. a flag está ligada;
      2. a tarefa é da classe estruturada;
      3. o motor é o da OpenAI (o modelo econômico é identificador
         dela; mandá-lo ao Gemini pediria um modelo que não existe lá);
      4. há um modelo econômico configurado.

    Fora disso devolve a lista intacta. O modelo principal permanece na
    lista, atrás do econômico: se o econômico não existir na conta, o
    `_RespostaVazia`/`_e_erro_de_modelo` já existente cai para ele
    sozinho, e a tarefa não falha por causa de uma configuração errada.
    """
    if not ativo() or classe(tarefa) != ESTRUTURADA or motor != "openai":
        return modelos_do_motor
    economico = modelo_economico_configurado()
    if not economico:
        return modelos_do_motor
    return [economico] + [m for m in modelos_do_motor if m != economico]


# ---------------------------------------------------------------------------
# Preço — DECLARADO pelo administrador, nunca presumido pelo código
# ---------------------------------------------------------------------------
# Custo em reais exige preço, e preço de modelo muda sem avisar e varia
# por contrato. Um número embutido aqui envelheceria em silêncio e
# apareceria num relatório de economia como se fosse medido. Então o
# preço vem de `config_app`, em reais por MILHÃO de tokens:
#
#   PRECO_<MODELO>_ENTRADA / PRECO_<MODELO>_SAIDA
#
# Sem preço configurado, `custo_estimado` devolve None — e quem lê o
# registro vê "não informado" em vez de um valor inventado.
def _preco(modelo: str, direcao: str) -> float | None:
    if not modelo:
        return None
    chave = f"PRECO_{modelo.upper().replace('-', '_').replace('/', '_')}_{direcao}"
    try:
        bruto = db.obter_config(chave)
    except Exception:  # noqa: BLE001
        return None
    try:
        return float((bruto or "").replace(",", ".")) or None
    except ValueError:
        return None


def custo_estimado(modelo: str, tokens_entrada: int | None,
                   tokens_saida: int | None) -> float | None:
    """Custo em reais, ou None quando o preço não foi configurado."""
    entrada, saida = _preco(modelo, "ENTRADA"), _preco(modelo, "SAIDA")
    if entrada is None and saida is None:
        return None
    total = 0.0
    total += (tokens_entrada or 0) / 1_000_000 * (entrada or 0)
    total += (tokens_saida or 0) / 1_000_000 * (saida or 0)
    return round(total, 6)
