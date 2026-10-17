"""
Cálculo determinístico, anomalias e formação da cesta.

Nada aqui passa por modelo de linguagem. Valor estimado vira ato
administrativo; a conta que o produz tem de ser reproduzível ao centavo,
hoje e daqui a dois anos, a partir da mesma série guardada.

Duas fronteiras que este módulo não cruza, e que valem mais que o código:

1. **outlier estatístico ≠ preço inexequível.** IQR e MAD dizem que um
   número está longe dos outros — não dizem que ele é ilegal. A
   classificação jurídica exige critério fundamentado e decisão humana
   registrada (§10). Aqui só se diz "candidato discrepante" e se mostra a
   distância da mediana;

2. **exclusão não apaga.** Referência descartada continua na série, com
   status e motivo. Pesquisa em que o preço inconveniente some não é
   auditável.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .matching import Comparabilidade
from .modelo import (CENTAVO, MOTIVO_NATUREZA_NAO_COMPARAVEL,
                     NATUREZAS_COMPARAVEIS, Referencia, StatusReferencia)
from .perfil import PerfilNormativo, PADRAO

ZERO = Decimal("0")

# Limiares de SINALIZAÇÃO estatística. Não são percentuais jurídicos —
# são as convenções clássicas de Tukey (1,5×IQR) e do MAD (3 desvios
# absolutos medianos). Ficam nomeados aqui para que o relatório possa
# dizer qual critério apontou cada candidato.
FATOR_IQR = Decimal("1.5")
FATOR_MAD = Decimal("3")
# 1,4826 torna o MAD comparável ao desvio padrão numa distribuição
# normal. Sem essa constante o corte do MAD ficaria mais severo que o
# esperado e marcaria referência boa como discrepante.
CONSISTENCIA_MAD = Decimal("1.4826")


def _ordenar(valores: list[Decimal]) -> list[Decimal]:
    return sorted(valores)


def brl(valor: Decimal | None) -> str:
    """R$ 1.234,56 a partir de Decimal, sem passar por float."""
    if valor is None:
        return "(não informado)"
    q = Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    inteiro, _, centavos = f"{abs(q):f}".partition(".")
    grupos = []
    while inteiro:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    sinal = "-" if q < 0 else ""
    return f"{sinal}R$ {'.'.join(grupos) or '0'},{(centavos + '00')[:2]}"


def pct(fracao: Decimal | None, casas: int = 2) -> str:
    """Fração (0,4823) → '48,23%' — o formato que o servidor confere."""
    if fracao is None:
        return "—"
    valor = (Decimal(fracao) * 100).quantize(
        Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    return f"{valor:f}".replace(".", ",") + "%"


def _percentil(ordenados: list[Decimal], fracao: Decimal) -> Decimal:
    """
    Percentil por interpolação linear — o mesmo método do `statistics`
    do Python e das planilhas, para que o número confira quando o
    revisor refizer a conta no Excel.
    """
    if not ordenados:
        return ZERO
    if len(ordenados) == 1:
        return ordenados[0]
    posicao = (Decimal(len(ordenados) - 1)) * fracao
    inferior = int(posicao)
    superior = min(inferior + 1, len(ordenados) - 1)
    peso = posicao - Decimal(inferior)
    return ordenados[inferior] + (ordenados[superior] - ordenados[inferior]) * peso


def mediana(valores: list[Decimal]) -> Decimal:
    return _percentil(_ordenar(valores), Decimal("0.5"))


@dataclass
class Estatisticas:
    """Série de preços resumida. Todo campo é `Decimal`."""

    quantidade: int
    menor: Decimal
    maior: Decimal
    media: Decimal
    mediana: Decimal
    amplitude: Decimal
    desvio_padrao: Decimal
    coeficiente_variacao: Decimal
    q1: Decimal
    q3: Decimal
    iqr: Decimal
    mad: Decimal
    # a soma entra na memória de cálculo da média ("soma ÷ n")
    soma: Decimal = ZERO

    def para_relatorio(self) -> dict:
        return {k: (v if isinstance(v, int) else format(v, "f"))
                for k, v in self.__dict__.items()}


def calcular(valores: list[Decimal]) -> Estatisticas | None:
    """
    Resumo estatístico da série. `None` para série vazia — não zero, que
    afirmaria que a média é zero.
    """
    limpos = [v for v in valores if v is not None]
    if not limpos:
        return None
    ordenados = _ordenar(limpos)
    n = len(ordenados)
    soma = sum(ordenados, ZERO)
    media = soma / Decimal(n)
    med = _percentil(ordenados, Decimal("0.5"))
    q1 = _percentil(ordenados, Decimal("0.25"))
    q3 = _percentil(ordenados, Decimal("0.75"))

    if n > 1:
        variancia = sum(((v - media) ** 2 for v in ordenados),
                        ZERO) / Decimal(n - 1)
        desvio = variancia.sqrt()
    else:
        desvio = ZERO

    desvios_absolutos = _ordenar([abs(v - med) for v in ordenados])
    mad = _percentil(desvios_absolutos, Decimal("0.5"))

    return Estatisticas(
        quantidade=n,
        menor=ordenados[0],
        maior=ordenados[-1],
        media=media,
        mediana=med,
        amplitude=ordenados[-1] - ordenados[0],
        desvio_padrao=desvio,
        coeficiente_variacao=(desvio / media) if media else ZERO,
        q1=q1, q3=q3, iqr=q3 - q1, mad=mad, soma=soma,
    )


@dataclass
class Anomalia:
    """
    Sinalização estatística — jamais classificação jurídica.

    `motivo` é escrito para o usuário e diz o critério e a distância. Não
    contém, e não pode conter, as palavras "inexequível" ou "ilegal".
    """

    referencia: Referencia
    valor: Decimal
    criterio: str            # 'IQR' | 'MAD'
    distancia_da_mediana_pct: Decimal
    motivo: str

    def para_relatorio(self) -> dict:
        # O percentual vai GRAVADO: o GovBot e o relatório leem do banco,
        # e sem ele a frase "está N% distante" saía sempre vazia
        # (dossiê BP, tema 2a).
        return {"valor": format(self.valor, "f"), "criterio": self.criterio,
                "motivo": self.motivo,
                "distancia_da_mediana_pct": format(
                    self.distancia_da_mediana_pct.quantize(CENTAVO), "f"),
                "fonte_id": self.referencia.fonte.id,
                "id_externo": self.referencia.id_externo}


def detectar_anomalias(referencias: list[Referencia],
                       estatisticas: Estatisticas) -> list[Anomalia]:
    """
    Aponta candidatos discrepantes por IQR e por MAD.

    Dois critérios porque eles falham em situações diferentes: o IQR
    perde sensibilidade em amostras muito pequenas, e o MAD fica cego
    quando mais da metade da amostra é do mesmo valor. Concordando os
    dois, a sinalização é forte; discordando, ainda assim se mostra.

    Série pequena (< 4) não é analisada: com três pontos, qualquer um
    parece distante e a sinalização viraria ruído.
    """
    if estatisticas.quantidade < 4:
        return []

    limite_inferior = estatisticas.q1 - FATOR_IQR * estatisticas.iqr
    limite_superior = estatisticas.q3 + FATOR_IQR * estatisticas.iqr
    corte_mad = CONSISTENCIA_MAD * FATOR_MAD * estatisticas.mad

    anomalias: list[Anomalia] = []
    for ref in referencias:
        valor = ref.valor_unitario_normalizado
        if valor is None:
            continue
        criterios = []
        if estatisticas.iqr > 0 and not (limite_inferior <= valor <= limite_superior):
            criterios.append("IQR")
        if estatisticas.mad > 0 and abs(valor - estatisticas.mediana) > corte_mad:
            criterios.append("MAD")
        if not criterios:
            continue

        if estatisticas.mediana:
            distancia = ((valor - estatisticas.mediana)
                         / estatisticas.mediana * 100)
        else:
            distancia = ZERO
        sentido = "acima" if distancia >= 0 else "abaixo"
        # A frase dá a BASE e o LIMITE, não só a distância: "mediana de
        # R$ X entre N preços; faixa IQR de R$ A a R$ B" é o que permite
        # ao revisor refazer a conta (dossiê BP, tema 2b).
        anomalias.append(Anomalia(
            referencia=ref, valor=valor, criterio="+".join(criterios),
            distancia_da_mediana_pct=distancia,
            motivo=(f"o valor está {pct(abs(distancia) / 100, 0)} {sentido} "
                    f"da mediana de {brl(estatisticas.mediana)} entre "
                    f"{estatisticas.quantidade} preços (critério "
                    f"{'+'.join(criterios)}; faixa IQR de "
                    f"{brl(limite_inferior)} a {brl(limite_superior)}). "
                    "O sistema sugere revisão."),
        ))
        ref.status = StatusReferencia.ALERTA
        ref.com_motivo(f"candidato discrepante pelo critério "
                       f"{'+'.join(criterios)}")
    return anomalias


# ---------------------------------------------------------------------------
# Critério percentual — SEPARADO do detector IQR/MAD, opcional e versionado
#
# O IQR/MAD não analisa série com menos de 4 preços, que é o caso típico
# (3 preços). O dossiê do BP observou outra regra, com limites por cotação
# (30% acima / 70% abaixo): um preço é "elevado" se passa da média dos
# OUTROS em mais de 30%; é "inexequível" se fica abaixo de 70% da média
# dos outros já SEM os elevados (9,66 / 22,70 = 42,56%, J10).
#
# Aqui ela é um critério de SINALIZAÇÃO, nunca de exclusão nem de juízo
# jurídico: os limites são parâmetro da cotação (não da Lei), vão para a
# memória com a base usada, e quem exclui é o revisor, com motivo. Sem
# limites configurados, nada é analisado — não há percentual universal.
# ---------------------------------------------------------------------------
VERSAO_CRITERIO_PERCENTUAL = "2026-10-16.media-dos-outros"


@dataclass
class MarcaPercentual:
    valor: Decimal
    marca: str          # 'elevado_sinalizado' | 'inexequivel_sinalizado' | 'valido'
    percentual: Decimal  # valor ÷ base × 100, duas casas
    base: Decimal | None  # média dos outros usada na comparação

    def para_relatorio(self) -> dict:
        return {"valor": format(self.valor, "f"), "marca": self.marca,
                "percentual": format(self.percentual, "f"),
                "base": None if self.base is None else format(self.base, "f")}


def analise_percentual(valores: list[Decimal], *, elevado_pct: Decimal,
                       inexequivel_pct: Decimal) -> list[MarcaPercentual]:
    """Marca cada preço contra a média dos outros (ver bloco acima)."""
    serie = [Decimal(v) for v in valores if v is not None]
    if len(serie) < 2:
        return []
    teto = Decimal(1) + Decimal(elevado_pct) / 100
    piso = Decimal(inexequivel_pct) / 100

    def media(lista):
        return sum(lista, ZERO) / Decimal(len(lista)) if lista else None

    elevados: set[int] = set()
    percentuais: dict[int, tuple[Decimal, Decimal]] = {}
    for i, valor in enumerate(serie):
        outros = media([v for j, v in enumerate(serie) if j != i])
        if outros and valor > outros * teto:
            elevados.add(i)
            percentuais[i] = (valor / outros * 100, outros)

    marcas = []
    for i, valor in enumerate(serie):
        if i in elevados:
            proporcao, base = percentuais[i]
            marcas.append(MarcaPercentual(
                valor, "elevado_sinalizado",
                proporcao.quantize(CENTAVO, ROUND_HALF_UP), base))
            continue
        base = media([v for j, v in enumerate(serie)
                      if j != i and j not in elevados])
        if base and valor < base * piso:
            marcas.append(MarcaPercentual(
                valor, "inexequivel_sinalizado",
                (valor / base * 100).quantize(CENTAVO, ROUND_HALF_UP), base))
        else:
            proporcao = (valor / base * 100) if base else Decimal(100)
            marcas.append(MarcaPercentual(
                valor, "valido", proporcao.quantize(CENTAVO, ROUND_HALF_UP),
                base))
    return marcas


def criterio_percentual_da(filtros: dict | None) -> tuple[Decimal, Decimal] | None:
    """(elevado %, inexequível %) configurados na cotação, ou None."""
    bruto = (filtros or {}).get("criterio_percentual") or {}
    try:
        elevado = Decimal(str(bruto["elevado"]))
        inexequivel = Decimal(str(bruto["inexequivel"]))
    except (KeyError, ArithmeticError, ValueError, TypeError):
        return None
    if not (0 < elevado <= 1000 and 0 < inexequivel < 100):
        return None
    return elevado, inexequivel


# ---------------------------------------------------------------------------
# Cesta
# ---------------------------------------------------------------------------
@dataclass
class Cesta:
    """As referências que sustentam a estimativa, e as que não entraram."""

    selecionadas: list[Referencia] = field(default_factory=list)
    descartadas: list[Referencia] = field(default_factory=list)
    motivos: list[str] = field(default_factory=list)
    # Elegíveis que ficaram FORA só pelo teto da cotação automática —
    # boas referências, disponíveis para o revisor incluir à mão. Vazia
    # quando não há teto (o comportamento histórico).
    excedentes: list[Referencia] = field(default_factory=list)
    # Retidas pela triagem pré-cesta (`saneamento`): desconsideradas ou em
    # revisão, com o motivo técnico. Ficam GRAVADAS para revisão e
    # reinclusão — nunca somem. `triagem` é o resultado completo, com as
    # métricas, para a trilha. Vazias sem a política de saneamento.
    retidas: list[Referencia] = field(default_factory=list)
    triagem: object | None = None

    @property
    def valores(self) -> list[Decimal]:
        return [r.valor_unitario_normalizado for r in self.selecionadas
                if r.valor_unitario_normalizado is not None]


# Piso de comparabilidade para entrar na cesta automática. Abaixo disso a
# referência fica disponível para o revisor incluir à mão, mas não entra
# sozinha: cesta montada com item pouco comparável é indefensável.
PISO_COMPARABILIDADE = Decimal("0.5")

# Coeficiente de variação acima do qual a série é "dispersa". É o mesmo
# corte que a regra antiga usava para trocar média por mediana; na regra
# da média ele não troca nada — marca a estimativa como provisória.
CV_DISPERSAO = Decimal("0.25")


@dataclass(frozen=True)
class PoliticaAmostraAutomatica:
    """
    Quanto a COTAÇÃO AUTOMÁTICA coleta, grava e considera por item.

    Medido em 17/10/2026: sem teto, um item com 301 candidatas por fonte
    gravava 602 referências e considerava 452 — o "301/3 considerado" da
    tela, um relatório inchado e minutos de processamento que não
    melhoram o preço. A política é uma só, para a cotação unificada e a
    rota legada, e vai VERSIONADA para a trilha de cada busca.

    * `teto` — máximo absoluto de referências que a automação põe na
      cesta de um item, contando as que já estavam lá. É teto, não meta;
    * `suficiente` — a busca para de ampliar (não consulta a próxima
      fonte) quando já há tantas candidatas elegíveis. 3 a 6 bons preços
      sustentam o método; chegar a 15 à força não melhora nada;
    * `limite_por_fonte` — quantos registros pedir a cada fonte;
    * `reserva` — elegíveis além do teto guardadas como candidatas, para o
      revisor ter alternativa sem nova consulta. O resto não é gravado: a
      trilha guarda as CONTAGENS (brutas, únicas, elegíveis), não as linhas.

    O modo MANUAL não usa esta política: o servidor pode trazer e
    escolher quantas referências a análise pedir.
    """

    # .2 (17/10/2026, medido em produção): grupo do catálogo limitado e
    # seleções ANTERIORES da automática reavaliadas sob o teto.
    versao: str = "2026-10-17.teto-15.2"
    teto: int = 15
    suficiente: int = 6
    limite_por_fonte: int = 50
    # registros por grupo do catálogo (PDM) no caminho por descrição do
    # Compras.gov; o manual continua pedindo 500
    limite_por_grupo: int = 100
    reserva: int = 10


POLITICA_AUTOMATICA = PoliticaAmostraAutomatica()


def selecionar_cesta(
    ranqueadas: list[tuple[Referencia, Comparabilidade]],
    perfil: PerfilNormativo = PADRAO,
    piso: Decimal = PISO_COMPARABILIDADE,
    teto: int | None = None,
    saneamento=None,
    texto_item: str = "",
) -> Cesta:
    """
    Monta a cesta por COMPARABILIDADE e prioridade de fonte — nunca por
    preço.

    A ordem é: fonte de maior prioridade normativa primeiro, e dentro
    dela a maior comparabilidade. "Pegue os três menores" produziria uma
    cesta falsa, barata e incomparável (§12).

    `teto` (cotação automática): só as `teto` primeiras dessa ordem entram;
    as demais elegíveis ficam CANDIDATAS em `excedentes`, com o motivo.
    `None` = sem teto, exatamente como antes.

    `saneamento` (`saneamento.PoliticaSaneamento`, flag
    `precos_saneamento_pre_cesta`): as referências que alcançam o piso de
    comparabilidade passam ANTES pela triagem do item — invalidação
    objetiva e suspeita estatística corroborada. Só as elegíveis concorrem
    à cesta; as demais ficam em `retidas`, com status e motivo técnico.
    `None` = sem triagem, exatamente como antes.
    """
    cesta = Cesta()
    prioridade = {tipo: i for i, tipo
                  in enumerate(perfil.prioridade_de_fontes)}

    if saneamento is not None:
        ranqueadas = _triagem_pre_cesta(ranqueadas, cesta, piso, saneamento,
                                        texto_item)

    elegiveis = []
    for referencia, comparabilidade in ranqueadas:
        if referencia.valor_unitario_normalizado is None:
            referencia.status = StatusReferencia.REJEITADA
            cesta.descartadas.append(referencia)
            continue
        # A natureza é conferida ANTES da comparabilidade, e a ordem
        # importa: um valor estimado pelo órgão de origem pode ser
        # perfeitamente comparável — mesmo produto, mesma unidade, mesma
        # região — e é exatamente por isso que ele passaria no piso e
        # entraria na cesta. Comparabilidade responde "é o mesmo
        # produto?"; natureza responde "este número é um preço?". Só a
        # segunda impede a estimativa da Administração de se apoiar na
        # estimativa de outra Administração.
        if referencia.natureza_valor not in NATUREZAS_COMPARAVEIS:
            referencia.status = StatusReferencia.REVISAO_MANUAL
            referencia.com_motivo(MOTIVO_NATUREZA_NAO_COMPARAVEL.format(
                rotulo=referencia.rotulo_da_natureza))
            cesta.descartadas.append(referencia)
            continue
        if comparabilidade.score < piso:
            referencia.status = StatusReferencia.REVISAO_MANUAL
            referencia.com_motivo(
                f"comparabilidade {comparabilidade.percentual}% abaixo do "
                f"piso automático — disponível para inclusão manual")
            cesta.descartadas.append(referencia)
            continue
        elegiveis.append((referencia, comparabilidade))

    elegiveis.sort(key=lambda par: (
        prioridade.get(par[0].fonte.tipo, 99), -par[1].score))

    limite = len(elegiveis) if teto is None else max(0, int(teto))
    for referencia, _ in elegiveis[:limite]:
        referencia.status = StatusReferencia.SELECIONADA
        cesta.selecionadas.append(referencia)
    for referencia, _ in elegiveis[limite:]:
        referencia.status = StatusReferencia.CANDIDATA
        # sem o número: numa reconsulta o teto que sobra é menor que o da
        # política, e "teto de 2" leria como regra diferente
        referencia.com_motivo(
            "elegível, fora da cesta automática pelo teto de referências "
            "da cotação automática — disponível para inclusão manual")
        cesta.excedentes.append(referencia)

    if not cesta.selecionadas and not cesta.excedentes:
        cesta.motivos.append(
            "nenhuma referência atingiu a comparabilidade mínima")
    return cesta


def _triagem_pre_cesta(ranqueadas, cesta: Cesta, piso: Decimal, politica,
                      texto_item: str):
    """
    Roda o motor de saneamento sobre as COMPARÁVEIS (score ≥ piso) e
    devolve só o que segue para a seleção: as elegíveis e as abaixo do
    piso (que a seleção trata como sempre tratou).
    """
    from . import saneamento

    def entra(referencia, comparabilidade) -> bool:
        # invalidação objetiva vale para qualquer referência; a estatística,
        # só para as comparáveis (o motor não mistura objetos diferentes)
        return (comparabilidade.score >= piso
                or referencia.valor_unitario_normalizado is None
                or not referencia.tem_preco)

    analisadas = [(r, c) for r, c in ranqueadas if entra(r, c)]
    triagem = saneamento.avaliar(
        [saneamento.observacao_da_referencia(r) for r, _ in analisadas],
        politica, texto_item=texto_item)
    cesta.triagem = triagem
    por_chave = triagem.por_id()
    seguem = []
    for referencia, comparabilidade in ranqueadas:
        avaliacao = (por_chave.get(referencia.chave_dedupe)
                     if entra(referencia, comparabilidade) else None)
        if avaliacao is None or avaliacao.desfecho == saneamento.ELEGIVEL:
            seguem.append((referencia, comparabilidade))
            continue
        referencia.status = StatusReferencia(
            saneamento.status_do_desfecho(avaliacao.desfecho))
        referencia.com_motivo(saneamento.motivo_da_avaliacao(
            avaliacao, triagem.versao))
        cesta.descartadas.append(referencia)
        if saneamento.retem(avaliacao):
            cesta.retidas.append(referencia)
    return seguem


# ---------------------------------------------------------------------------
# Estimativa
# ---------------------------------------------------------------------------
@dataclass
class Estimativa:
    """
    O preço estimado de um item e tudo o que o justifica.

    `status` é `CONCLUIDO` ou `INCOMPLETO`. Nunca se fabrica a terceira
    referência para "fechar" a regra dos três — a pesquisa fica
    incompleta e diz por quê.
    """

    valor_unitario: Decimal | None
    metodo: str
    status: str                       # 'CONCLUIDO' | 'INCOMPLETO'
    estatisticas: Estatisticas | None
    cesta: Cesta
    anomalias: list[Anomalia] = field(default_factory=list)
    memoria: list[str] = field(default_factory=list)
    perfil_id: str = PADRAO.id
    # O que o REVISOR precisa decidir antes de concluir o item: a média é
    # de referências "elegíveis e aprovadas", e discrepante ou série
    # dispersa ainda não aprovados tornam o número provisório.
    pendencias: list[str] = field(default_factory=list)
    # Marcas do critério percentual da cotação, quando configurado.
    marcas_percentuais: list[MarcaPercentual] = field(default_factory=list)
    criterio_percentual: tuple[Decimal, Decimal] | None = None
    # Exceção formal à regra dos três aplicada nesta estimativa.
    excecao_aplicada: bool = False

    @property
    def concluida(self) -> bool:
        return self.status == "CONCLUIDO"

    @property
    def provisoria(self) -> bool:
        """Tem valor, mas depende de análise crítica humana (ver `pendencias`)."""
        return bool(self.pendencias)

    def valor_total(self, quantidade: Decimal | None) -> Decimal | None:
        if self.valor_unitario is None or quantidade is None:
            return None
        return (self.valor_unitario * quantidade).quantize(
            CENTAVO, rounding=ROUND_HALF_UP)

    def para_relatorio(self) -> dict:
        return {
            "valor_unitario": None if self.valor_unitario is None
            else format(self.valor_unitario, "f"),
            "metodo": self.metodo,
            "status": self.status,
            "perfil": self.perfil_id,
            "estatisticas": self.estatisticas.para_relatorio()
            if self.estatisticas else None,
            # "selecionadas" é o nome histórico do campo e continua aqui
            # para ler pesquisas antigas; o número é o de CONSIDERADAS no
            # cálculo (a cesta já exclui quem não tem preço normalizado).
            "selecionadas": len(self.cesta.selecionadas),
            "consideradas": len(self.cesta.selecionadas),
            "descartadas": len(self.cesta.descartadas),
            "pendencias": list(self.pendencias),
            "anomalias": [a.para_relatorio() for a in self.anomalias],
            "marcas_percentuais": [m.para_relatorio()
                                   for m in self.marcas_percentuais],
            "criterio_percentual": None if self.criterio_percentual is None
            else {"elevado": format(self.criterio_percentual[0], "f"),
                  "inexequivel": format(self.criterio_percentual[1], "f"),
                  "versao": VERSAO_CRITERIO_PERCENTUAL},
            "excecao_aplicada": self.excecao_aplicada,
            "memoria": list(self.memoria),
        }


METODO_AUTOMATICO = "automatico"

# Versões das REGRAS de escolha do método, gravadas em
# `pesquisas_preco.versao_regras` na criação da pesquisa.
#
# * REGRAS_LEGADAS ("") — o automático escolhia média ou mediana pelo
#   coeficiente de variação. Pesquisas criadas assim continuam assim: o
#   método padrão mudar NÃO reprocessa pesquisa já feita (Banco de Preços,
#   15/10/2026).
# * REGRAS_MEDIA_PADRAO — o automático é a MÉDIA ARITMÉTICA SIMPLES dos
#   preços unitários selecionados. Mediana, CV e dispersão viram só
#   diagnóstico; discrepante gera alerta, nunca troca de método nem
#   exclusão automática.
REGRAS_LEGADAS = ""
REGRAS_MEDIA_PADRAO = "2026-10-15.media-aritmetica"


ROTULO_METODO = {"media": "média aritmética", "mediana": "mediana",
                 "menor": "menor preço"}


def _aplicar_metodo(metodo: str, e: Estatisticas) -> Decimal:
    if metodo == "media":
        return e.media
    if metodo == "menor":
        return e.menor
    return e.mediana


def estimar(cesta: Cesta, *, perfil: PerfilNormativo = PADRAO,
            metodo: str = METODO_AUTOMATICO,
            justificativa: str | None = None,
            regras: str = REGRAS_LEGADAS,
            criterio_percentual: tuple[Decimal, Decimal] | None = None
            ) -> Estimativa:
    """
    Forma o preço estimado a partir da cesta.

    `regras` diz qual política o AUTOMÁTICO segue (ver
    `REGRAS_MEDIA_PADRAO`): média aritmética simples nas pesquisas novas;
    média/mediana pelo coeficiente de variação nas criadas antes.

    Método pedido que o perfil não admite NÃO cai em outro em silêncio:
    a estimativa sai sem valor, INCOMPLETA, com o impedimento e os
    métodos admitidos na memória.

    `justificativa` é a EXCEÇÃO formal à regra dos três (perfil que
    admite, texto, fundamento e aprovação já conferidos por
    `cesta.registrar_excecao`). `criterio_percentual` é o par
    (elevado %, inexequível %) da cotação, quando configurado.
    """
    estatisticas = calcular(cesta.valores)
    memoria: list[str] = []

    if estatisticas is None:
        return Estimativa(
            valor_unitario=None, metodo=metodo, status="INCOMPLETO",
            estatisticas=None, cesta=cesta, perfil_id=perfil.id,
            criterio_percentual=criterio_percentual,
            memoria=["nenhuma referência comparável foi considerada — item "
                     "sem preço (não é preço zero)"])

    anomalias = detectar_anomalias(cesta.selecionadas, estatisticas)

    escolhido = metodo
    if metodo == METODO_AUTOMATICO and regras == REGRAS_MEDIA_PADRAO:
        escolhido = "media"
        memoria.append(
            "método padrão: média aritmética simples dos preços unitários "
            f"considerados (soma {brl(estatisticas.soma)} "
            f"÷ {estatisticas.quantidade}); mediana "
            f"{brl(estatisticas.mediana)}, desvio-padrão amostral "
            f"{brl(estatisticas.desvio_padrao)} e coeficiente de variação "
            f"{pct(estatisticas.coeficiente_variacao)} apenas como "
            "diagnóstico")
    elif metodo == METODO_AUTOMATICO:
        disperso = estatisticas.coeficiente_variacao > CV_DISPERSAO
        escolhido = "mediana" if disperso else "media"
        memoria.append(
            f"método escolhido automaticamente (regra anterior a "
            f"15/10/2026): {escolhido} — coeficiente de variação "
            f"{pct(estatisticas.coeficiente_variacao)} "
            f"({'série dispersa' if disperso else 'série homogênea'})")
    if escolhido not in perfil.metodos_permitidos:
        memoria.append(
            f"método '{escolhido}' não é admitido pelo perfil {perfil.nome}"
            f" — admitidos: {', '.join(perfil.metodos_permitidos)}. "
            "Nenhum outro método foi aplicado em seu lugar; escolha um "
            "método admitido e registre a decisão")
        return Estimativa(
            valor_unitario=None, metodo=escolhido, status="INCOMPLETO",
            estatisticas=estatisticas, cesta=cesta, anomalias=anomalias,
            memoria=memoria, perfil_id=perfil.id,
            criterio_percentual=criterio_percentual)

    valor = _aplicar_metodo(escolhido, estatisticas)
    memoria.append(
        f"{ROTULO_METODO.get(escolhido, escolhido)} de "
        f"{estatisticas.quantidade} referência(s) considerada(s) = "
        f"{brl(valor)} (valor exato {format(valor, 'f')}, arredondado ao "
        "centavo, metade para cima)")

    # Teto da mediana quando a estimativa se apoia SÓ em sistema oficial
    if perfil.teto_da_mediana_em_sistema_oficial:
        tipos = {r.fonte.tipo for r in cesta.selecionadas}
        if tipos == {"sistema_oficial"} and valor > estatisticas.mediana:
            memoria.append(
                f"{perfil.nome}: estimativa apoiada exclusivamente em "
                "sistema oficial de preços não supera a mediana da "
                f"amostra — valor ajustado de {brl(valor)} para "
                f"{brl(estatisticas.mediana)}")
            valor = estatisticas.mediana

    valor = valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)

    # Regra dos três — nunca fabricar a referência que falta
    suficiente = perfil.conclui_com(estatisticas.quantidade)
    excecao = False
    if suficiente:
        status = "CONCLUIDO"
    elif justificativa and perfil.admite_menos_com_justificativa:
        status = "CONCLUIDO"
        excecao = True
        memoria.append(
            f"EXCEÇÃO à regra dos {perfil.minimo_referencias}: concluída "
            f"com {estatisticas.quantidade} referência(s) considerada(s), "
            f"abaixo do mínimo do perfil {perfil.nome}, mediante "
            f"justificativa registrada: {justificativa}")
    else:
        status = "INCOMPLETO"
        if justificativa:
            memoria.append(
                f"o perfil {perfil.nome} não admite concluir com menos de "
                f"{perfil.minimo_referencias} referências; a justificativa "
                "foi registrada, mas não fecha o item")
        memoria.append(
            f"apenas {estatisticas.quantidade} referência(s) "
            f"considerada(s); o perfil {perfil.nome} exige "
            f"{perfil.minimo_referencias}. Amplie a consulta, tente outra "
            "fonte, informe o CATMAT/CATSER, registre cotação direta ou "
            "a exceção prevista no perfil — nenhum preço é fabricado para "
            "completar a cesta")

    if anomalias:
        memoria.append(
            f"{len(anomalias)} candidato(s) discrepante(s) sinalizado(s) "
            "para revisão; nenhum foi excluído automaticamente")

    # Análise crítica pendente — só nas regras da média. Na regra antiga a
    # dispersão já levava à mediana; na nova, a média de uma cesta com
    # discrepante NÃO DECIDIDO é provisória: medido em 15/10/2026 na
    # planilha real de 210 itens, um único registro errado da fonte levou
    # a média de uma divisória de fichário a R$ 30.002,33 (planilha:
    # R$ 14,90). Nada é excluído aqui; o revisor exclui com motivo ou
    # mantém com justificativa (IN 65/2021, art. 6º, § 3º, onde aplicável).
    pendencias: list[str] = []
    if regras == REGRAS_MEDIA_PADRAO and escolhido == "media":
        if anomalias:
            pendencias.append(
                f"{len(anomalias)} preço(s) discrepante(s) aguardam decisão: "
                "retirar da cesta ou manter com justificativa")
        if estatisticas.coeficiente_variacao > CV_DISPERSAO:
            pendencias.append(
                f"dispersão elevada (coeficiente de variação "
                f"{pct(estatisticas.coeficiente_variacao)} > "
                f"{pct(CV_DISPERSAO, 0)}): a média pode não representar o "
                "mercado; examine a cesta antes de concluir")

    marcas: list[MarcaPercentual] = []
    if criterio_percentual is not None:
        elevado, inexequivel = criterio_percentual
        marcas = analise_percentual(cesta.valores, elevado_pct=elevado,
                                    inexequivel_pct=inexequivel)
        sinalizadas = [m for m in marcas if m.marca != "valido"]
        for marca in sinalizadas:
            rotulo = ("acima do limite de elevado"
                      if marca.marca == "elevado_sinalizado"
                      else "abaixo do limite de inexequível")
            percentual = format(marca.percentual, "f").replace(".", ",")
            memoria.append(
                f"critério percentual da cotação: {brl(marca.valor)} "
                f"representa {percentual}% da média dos outros preços "
                f"({brl(marca.base)}) — {rotulo} (+{elevado}% / "
                f"{inexequivel}%); sinalizado, não excluído")
        if sinalizadas:
            pendencias.append(
                f"{len(sinalizadas)} preço(s) sinalizado(s) pelo critério "
                "percentual da cotação aguardam decisão: retirar da cesta "
                "ou manter com justificativa")

    if pendencias:
        memoria.append("valor PROVISÓRIO até a análise crítica: "
                       + "; ".join(pendencias))

    return Estimativa(
        valor_unitario=valor, metodo=escolhido, status=status,
        estatisticas=estatisticas, cesta=cesta, anomalias=anomalias,
        memoria=memoria, perfil_id=perfil.id, pendencias=pendencias,
        marcas_percentuais=marcas, criterio_percentual=criterio_percentual,
        excecao_aplicada=excecao)
