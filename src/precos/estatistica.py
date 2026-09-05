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
        q1=q1, q3=q3, iqr=q3 - q1, mad=mad,
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
        anomalias.append(Anomalia(
            referencia=ref, valor=valor, criterio="+".join(criterios),
            distancia_da_mediana_pct=distancia,
            motivo=(f"o valor está {abs(distancia):.0f}% {sentido} da "
                    f"mediana da amostra (critério {'+'.join(criterios)}). "
                    "O sistema sugere revisão."),
        ))
        ref.status = StatusReferencia.ALERTA
        ref.com_motivo(f"candidato discrepante pelo critério "
                       f"{'+'.join(criterios)}")
    return anomalias


# ---------------------------------------------------------------------------
# Cesta
# ---------------------------------------------------------------------------
@dataclass
class Cesta:
    """As referências que sustentam a estimativa, e as que não entraram."""

    selecionadas: list[Referencia] = field(default_factory=list)
    descartadas: list[Referencia] = field(default_factory=list)
    motivos: list[str] = field(default_factory=list)

    @property
    def valores(self) -> list[Decimal]:
        return [r.valor_unitario_normalizado for r in self.selecionadas
                if r.valor_unitario_normalizado is not None]


# Piso de comparabilidade para entrar na cesta automática. Abaixo disso a
# referência fica disponível para o revisor incluir à mão, mas não entra
# sozinha: cesta montada com item pouco comparável é indefensável.
PISO_COMPARABILIDADE = Decimal("0.5")


def selecionar_cesta(
    ranqueadas: list[tuple[Referencia, Comparabilidade]],
    perfil: PerfilNormativo = PADRAO,
    piso: Decimal = PISO_COMPARABILIDADE,
) -> Cesta:
    """
    Monta a cesta por COMPARABILIDADE e prioridade de fonte — nunca por
    preço.

    A ordem é: fonte de maior prioridade normativa primeiro, e dentro
    dela a maior comparabilidade. "Pegue os três menores" produziria uma
    cesta falsa, barata e incomparável (§12).
    """
    cesta = Cesta()
    prioridade = {tipo: i for i, tipo
                  in enumerate(perfil.prioridade_de_fontes)}

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

    for referencia, _ in elegiveis:
        referencia.status = StatusReferencia.SELECIONADA
        cesta.selecionadas.append(referencia)

    if not cesta.selecionadas:
        cesta.motivos.append(
            "nenhuma referência atingiu a comparabilidade mínima")
    return cesta


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

    @property
    def concluida(self) -> bool:
        return self.status == "CONCLUIDO"

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
            "selecionadas": len(self.cesta.selecionadas),
            "descartadas": len(self.cesta.descartadas),
            "anomalias": [{
                "valor": format(a.valor, "f"),
                "criterio": a.criterio,
                "motivo": a.motivo,
            } for a in self.anomalias],
            "memoria": list(self.memoria),
        }


METODO_AUTOMATICO = "automatico"


def _aplicar_metodo(metodo: str, e: Estatisticas) -> Decimal:
    if metodo == "media":
        return e.media
    if metodo == "menor":
        return e.menor
    return e.mediana


def estimar(cesta: Cesta, *, perfil: PerfilNormativo = PADRAO,
            metodo: str = METODO_AUTOMATICO,
            justificativa: str | None = None) -> Estimativa:
    """
    Forma o preço estimado a partir da cesta.

    O método automático escolhe **mediana** quando a série é dispersa e
    **média** quando é homogênea. A razão é estatística, não jurídica: a
    mediana resiste a valores extremos, e é justamente com dispersão alta
    que os extremos distorcem a média. Com série homogênea a média usa
    toda a informação disponível.
    """
    estatisticas = calcular(cesta.valores)
    memoria: list[str] = []

    if estatisticas is None:
        return Estimativa(
            valor_unitario=None, metodo=metodo, status="INCOMPLETO",
            estatisticas=None, cesta=cesta, perfil_id=perfil.id,
            memoria=["nenhuma referência comparável foi selecionada"])

    anomalias = detectar_anomalias(cesta.selecionadas, estatisticas)

    escolhido = metodo
    if metodo == METODO_AUTOMATICO:
        disperso = estatisticas.coeficiente_variacao > Decimal("0.25")
        escolhido = "mediana" if disperso else "media"
        memoria.append(
            f"método escolhido automaticamente: {escolhido} — coeficiente "
            f"de variação {estatisticas.coeficiente_variacao:.2f} "
            f"({'série dispersa' if disperso else 'série homogênea'})")
    elif metodo not in perfil.metodos_permitidos:
        memoria.append(
            f"método '{metodo}' não é permitido pelo perfil {perfil.nome}; "
            "aplicada a mediana")
        escolhido = "mediana"

    valor = _aplicar_metodo(escolhido, estatisticas)
    memoria.append(
        f"{escolhido} de {estatisticas.quantidade} referência(s) "
        f"selecionada(s) = {valor.quantize(CENTAVO, ROUND_HALF_UP)}")

    # Teto da mediana quando a estimativa se apoia SÓ em sistema oficial
    if perfil.teto_da_mediana_em_sistema_oficial:
        tipos = {r.fonte.tipo for r in cesta.selecionadas}
        if tipos == {"sistema_oficial"} and valor > estatisticas.mediana:
            memoria.append(
                f"{perfil.nome}: estimativa apoiada exclusivamente em "
                "sistema oficial de preços não supera a mediana da "
                f"amostra — valor ajustado de "
                f"{valor.quantize(CENTAVO, ROUND_HALF_UP)} para "
                f"{estatisticas.mediana.quantize(CENTAVO, ROUND_HALF_UP)}")
            valor = estatisticas.mediana

    valor = valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)

    # Regra dos três — nunca fabricar a referência que falta
    suficiente = perfil.conclui_com(estatisticas.quantidade)
    if suficiente:
        status = "CONCLUIDO"
    elif justificativa and perfil.admite_menos_com_justificativa:
        status = "CONCLUIDO"
        memoria.append(
            f"concluída com {estatisticas.quantidade} referência(s), abaixo "
            f"do mínimo de {perfil.minimo_referencias} do perfil "
            f"{perfil.nome}, mediante justificativa registrada: "
            f"{justificativa}")
    else:
        status = "INCOMPLETO"
        memoria.append(
            f"apenas {estatisticas.quantidade} referência(s) defensável(is); "
            f"o perfil {perfil.nome} exige {perfil.minimo_referencias}. "
            "Amplie a consulta, tente outra fonte, informe o "
            "CATMAT/CATSER ou anexe cotação — nenhum preço é fabricado "
            "para completar a cesta")

    if anomalias:
        memoria.append(
            f"{len(anomalias)} candidato(s) discrepante(s) sinalizado(s) "
            "para revisão; nenhum foi excluído automaticamente")

    return Estimativa(
        valor_unitario=valor, metodo=escolhido, status=status,
        estatisticas=estatisticas, cesta=cesta, anomalias=anomalias,
        memoria=memoria, perfil_id=perfil.id)
