"""
Saneamento das referências de UM item — antes da cesta e na emissão.

Motor ÚNICO (pacote Jev de 17/10/2026): a triagem pré-cesta da cotação
automática e a verificação de atipicidades que antecede a emissão do
relatório chamam a mesma `avaliar`. Não há segundo critério.

Duas camadas, nesta ordem:

1. **Invalidação objetiva** — valor nulo, zero ou negativo; preço sem
   conversão comprovada para a unidade do item; valor que não é preço
   praticado; a mesma linha do mesmo documento vista duas vezes. Fato
   verificável, não opinião.
2. **Suspeita estatística por item** — sobre os preços unitários
   normalizados COMPARÁVEIS daquele item, e só deles: mediana, MAD,
   z modificado (0,6745·|x − mediana| / MAD), quartis e IQR pelo mesmo
   método do resto do módulo (`estatistica.calcular`), e a razão
   x / mediana.

Quem decide é esta função, determinística e versionada
(`PoliticaSaneamento.versao`). O Jev contribui com EVIDÊNCIA (a escolha
fechada de `decisoes.MOTIVOS`), nunca com a decisão: recomendação do Jev
sozinha leva à revisão humana, jamais ao descarte. Descarte estatístico
automático exige, ao mesmo tempo:

* suspeita FORTE (razão extrema e mais um critério robusto);
* amostra mínima de preços comparáveis (`minimo_para_autoexclusao`);
* corroboração: o grupo NÃO suspeito é homogêneo e vem de pelo menos
  `minimo_origens_independentes` origens distintas;
* nenhum sinal de contexto comercial plausível (instalação, garantia,
  frete, quilometragem adicional, kit, marca premium…);
* política que o permita (`autoexclusao_estatistica`).

Faltando qualquer um, o desfecho é REVISÃO — nunca descarte por
presunção. Nada aqui apaga dado: o desfecho vira status e motivo da
referência, que continua gravada e pode voltar à cesta por ato humano.

Linguagem: "preço atípico" / "variação relevante". O motor não afirma
sobrepreço nem inexequibilidade — é sinal estatístico, não juízo.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation

from . import estatistica
from .matching import _sem_acento

# v2 (Revisão 02, 17/10/2026): descarte estatístico automático só com
# 8+ preços comparáveis; IQR só a partir de 4; suspeito de amostra
# pequena fica NA cesta, sinalizado, em vez de sumir dela; e a cesta
# formada pelo teto é reavaliada, com reposição (`recompor_cesta`).
VERSAO_POLITICA = "2026-10-17.saneamento-v2"
VERSAO_POLITICA_V1 = "2026-10-17.saneamento-v1"

# Desfechos — o "outcome" do contrato do pacote.
ELEGIVEL = "eligible"
DESCONSIDERADA = "excluded_prebasket"
REVISAO = "needs_review"

# Códigos de motivo (estáveis: vão para a trilha e para os testes).
VALOR_INVALIDO = "INVALID_VALUE"
UNIDADE_NAO_CONVERSIVEL = "UNIT_NOT_CONVERTIBLE"
NATUREZA_NAO_PRECO = "VALUE_NOT_MARKET_PRICE"
DUPLICIDADE = "DUPLICATE_SAME_ORIGIN"
EXTREMO = "STATISTICAL_EXTREME"
CORROBORADO = "INDEPENDENT_REFERENCES_CORROBORATE"
SEM_CORROBORACAO = "INSUFFICIENT_INDEPENDENT_REFERENCES"
AMOSTRA_PEQUENA = "SMALL_SAMPLE"
DISPERSAO_INCONCLUSIVA = "DISPERSION_INCONCLUSIVE"
CONTEXTO_COMERCIAL = "PLAUSIBLE_COMMERCIAL_CONTEXT"
DIVERGENCIA_JEV = "JEV_COMPARABILITY_CONCERN"
VARIACAO_RELEVANTE = "PRICE_VARIATION_REQUIRES_ATTENTION"
SINALIZADA_NA_CESTA = "FLAGGED_IN_BASKET"
# fator de conversão ≥ 10× ou ≤ 0,1× (`unidades.fator_extremo`, N-06)
FATOR_EXTREMO = "UNIT_CONVERSION_FACTOR_EXTREME"

# Rótulos que vão para `motivos` da referência — e pelos quais a tela e o
# relatório reconhecem o desfecho da triagem sem reler a trilha.
ROTULO_DESCONSIDERADA = "desconsiderada pelo Jev antes da cesta"
ROTULO_REVISAO = "requer revisão (triagem pré-cesta)"
# Na cesta, mas destoante numa amostra pequena demais para decidir: o
# preço CONTINUA no cálculo e o alerta o acompanha até alguém decidir.
ROTULO_SINALIZADA = "sinalizada para conferência (triagem)"
# Reavaliação da cesta já formada pelo teto: saiu para revisão porque
# havia outra referência elegível para o lugar dela.
SUBSTITUIDA = "REPLACED_BY_ELIGIBLE_REFERENCE"

# Escolhas do Jev (`decisoes.MOTIVOS`) por peso de evidência.
JEV_DIVERGENTE = frozenset({"different_product", "different_specification"})
JEV_DUVIDA = frozenset({"different_unit", "different_packaging",
                        "insufficient_information"})

ZERO = Decimal("0")
CONSTANTE_Z = Decimal("0.6745")
QUATRO_CASAS = Decimal("0.0001")


@dataclass(frozen=True)
class PoliticaSaneamento:
    """
    Limiares de SUSPEITA — parâmetros da triagem, não da Lei.

    Os valores padrão vêm do exemplo do pacote (`regras_precos.exemplo.yaml`)
    e são os usuais da literatura (Iglewicz–Hoaglin para o z modificado,
    Tukey para o IQR). Mudar qualquer um exige nova `versao`: a trilha de
    cada busca grava a política com que foi decidida.
    """

    versao: str = VERSAO_POLITICA
    # Revisão 02, 02_JEV_TRIAGEM: com menos de 8 comparáveis o grupo não
    # sustenta descarte só por variação (a v1 usava 5).
    minimo_para_autoexclusao: int = 8
    minimo_origens_independentes: int = 3
    z_modificado: Decimal = Decimal("3.5")
    fator_iqr: Decimal = Decimal("1.5")
    razao_alta: Decimal = Decimal("3.0")
    razao_baixa: Decimal = Decimal("0.333333")
    autoexclusao_estatistica: bool = True
    # IQR com 2 ou 3 pontos é ruído: o quartil é interpolado entre eles.
    minimo_para_iqr: int = 4
    # Suspeito de amostra pequena: True = fica NA cesta, sinalizado (o
    # alerta acompanha o preço); False = sai para revisão (a v1).
    sinalizar_na_cesta_em_amostra_pequena: bool = True
    # Distância mínima da mediana (fração) para dois critérios de
    # dispersão virarem suspeita. Medido na massa do pacote: série muito
    # apertada (grampeador, 12 preços entre R$ 11,50 e R$ 12,10) tem MAD
    # minúsculo, e z e IQR apontavam R$ 7,00, R$ 8,90 e R$ 15,29 — preços
    # a 23–40% da mediana, variação normal de mercado. Tirá-los levaria a
    # cesta para o centro, o vício que o 02_JEV proíbe ("não pegar os que
    # mais se aproximam da mediana"). Razão extrema continua bastando.
    desvio_minimo_relativo: Decimal = Decimal("0.5")

    def para_registro(self) -> dict:
        return {k: (format(v, "f") if isinstance(v, Decimal) else v)
                for k, v in asdict(self).items()}


POLITICA_PADRAO = PoliticaSaneamento()
# A política com que as buscas de 17/10/2026 (antes da Revisão 02) foram
# triadas: continua aqui para reler e reproduzir aquelas decisões.
POLITICA_V1 = PoliticaSaneamento(
    versao=VERSAO_POLITICA_V1, minimo_para_autoexclusao=5, minimo_para_iqr=0,
    sinalizar_na_cesta_em_amostra_pequena=False,
    desvio_minimo_relativo=Decimal("0"))


# Termos que, presentes na referência e AUSENTES no item, indicam
# condição comercial que pode explicar um preço distante: o motor não
# descarta, manda para revisão (regra de prudência do pacote, RF-01).
_SINAIS_COMERCIAIS = (
    ("INSTALA", "instalação"), ("MONTAGEM", "montagem"),
    ("GARANTIA", "garantia"), ("FRETE", "frete"), ("ENTREGA", "entrega"),
    ("ADICIONA", "adicional"), ("KM", "quilometragem"),
    ("MANUTEN", "manutenção"), ("SUPORTE", "suporte"),
    ("TREINAMENTO", "treinamento"), ("KIT", "kit"), ("LOTE", "lote"),
    ("COMBO", "combo"), ("ACESSORI", "acessórios"), ("PREMIUM", "premium"),
    ("IMPORTAD", "importado"), ("SOB MEDIDA", "sob medida"),
    ("PERSONALIZ", "personalização"), ("URGEN", "urgência"),
    ("ESCOPO", "escopo"), ("EXTENDID", "extensão"), ("ESTENDID", "extensão"),
)


def sinais_comerciais(texto_referencia: str, texto_item: str = "") -> list[str]:
    """Condições comerciais citadas na referência e não no item."""
    ref = " " + _sem_acento(texto_referencia) + " "
    item = " " + _sem_acento(texto_item) + " "
    saida = []
    for raiz, rotulo in _SINAIS_COMERCIAIS:
        # "KM" sozinho ou colado ao número ("500KM"), não dentro de palavra
        padrao = r"(?<![A-Z])KM(?![A-Z])" if raiz == "KM" else raiz
        if re.search(padrao, ref) and not re.search(padrao, item) \
                and rotulo not in saida:
            saida.append(rotulo)
    return saida


def _decimal(valor) -> Decimal | None:
    if valor in (None, ""):
        return None
    if isinstance(valor, Decimal):
        return valor if valor.is_finite() else None
    try:
        convertido = Decimal(str(valor).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return convertido if convertido.is_finite() else None


def _texto(valor: Decimal | None) -> str | None:
    return None if valor is None else format(valor.normalize(), "f")


@dataclass
class Observacao:
    """
    Uma cotação do item, na forma que o motor lê.

    `valor` é o preço unitário NORMALIZADO para a unidade do item (`None`
    quando a conversão não foi comprovada); `origem` identifica a
    observação independente (órgão/fornecedor/documento); `duplicidade`
    é a chave da mesma linha do mesmo documento, quando a fonte a dá.
    """

    id: str
    valor: Decimal | None
    valor_original: Decimal | None = None
    unidade: str | None = None
    origem: str = ""
    duplicidade: str | None = None
    texto: str = ""
    natureza_preco: bool = True
    # sem conversão de unidade, a falta é RECUPERÁVEL (embalagem sem
    # capacidade, unidade fora do dicionário — o revisor pode achar o
    # fator na fonte) ou não (grandezas diferentes: hora × mês)?
    unidade_recuperavel: bool = True
    jev: str = ""                 # escolha do Jev, quando consultado
    sinalizada: bool = False      # já marcada `warning` na cesta


@dataclass
class Avaliacao:
    id: str
    desfecho: str
    codigos: list[str] = field(default_factory=list)
    explicacao: str = ""
    metricas: dict[str, str | None] = field(default_factory=dict)
    valor: Decimal | None = None
    valor_original: Decimal | None = None
    suspeita: bool = False
    corroborada: bool = False

    def para_registro(self) -> dict:
        return {"id": self.id, "desfecho": self.desfecho,
                "codigos": list(self.codigos), "explicacao": self.explicacao,
                "metricas": dict(self.metricas),
                "valor_unitario_normalizado": _texto(self.valor),
                "valor_unitario_original": _texto(self.valor_original)}


@dataclass
class Triagem:
    versao: str
    avaliacoes: list[Avaliacao] = field(default_factory=list)
    serie: dict[str, str | int | None] = field(default_factory=dict)

    def por_id(self) -> dict[str, Avaliacao]:
        return {a.id: a for a in self.avaliacoes}

    def contagem(self) -> dict[str, int]:
        saida = {ELEGIVEL: 0, DESCONSIDERADA: 0, REVISAO: 0}
        for a in self.avaliacoes:
            saida[a.desfecho] += 1
        return saida

    def para_registro(self, *, so_retidas: bool = True,
                      limite: int = 60) -> dict:
        """
        Para a trilha. Por padrão só as NÃO elegíveis vão linha a linha
        (são as que pedem fundamento), até `limite`; as elegíveis e o
        excedente ficam contados.
        """
        linhas = [a.para_registro() for a in self.avaliacoes
                  if not so_retidas or a.desfecho != ELEGIVEL]
        return {"versao": self.versao, "contagem": self.contagem(),
                "serie": dict(self.serie), "avaliacoes": linhas[:limite],
                "avaliacoes_omitidas": max(0, len(linhas) - limite)}


def _metricas(valor: Decimal, est: estatistica.Estatisticas,
              politica: PoliticaSaneamento) -> tuple[dict, list[str]]:
    """As contas de UM preço contra a série do item, e os critérios atingidos."""
    criterios: list[str] = []
    razao = (valor / est.mediana) if est.mediana > 0 else None
    if est.mad > 0:
        z = CONSTANTE_Z * abs(valor - est.mediana) / est.mad
        if z > politica.z_modificado:
            criterios.append("z_modificado")
    else:
        z = None
        # MAD = 0: mais da metade da série é o MESMO preço. Não se divide
        # por zero e não se declara "tudo regular": qualquer desvio da
        # mediana é sinal, a ser corroborado pela razão.
        if valor != est.mediana:
            criterios.append("mad_zero")
    if est.iqr > 0 and est.quantidade >= politica.minimo_para_iqr:
        inferior = est.q1 - politica.fator_iqr * est.iqr
        superior = est.q3 + politica.fator_iqr * est.iqr
        if not inferior <= valor <= superior:
            criterios.append("iqr")
    if razao is not None and (razao >= politica.razao_alta
                              or razao <= politica.razao_baixa):
        criterios.append("razao")
    metricas = {
        "mediana": _texto(est.mediana), "mad": _texto(est.mad),
        "q1": _texto(est.q1), "q3": _texto(est.q3), "iqr": _texto(est.iqr),
        "z_modificado": _texto(z.quantize(QUATRO_CASAS)) if z is not None
        else None,
        "razao_mediana": _texto(razao.quantize(QUATRO_CASAS))
        if razao is not None else None,
        "n": est.quantidade,
        "criterios": ",".join(criterios) or None,
    }
    return metricas, criterios


def _suspeita(criterios: list[str], metricas: dict | None = None,
              politica: "PoliticaSaneamento | None" = None) -> bool:
    """
    Um critério isolado de dispersão é dispersão natural, não suspeita; e
    dois critérios a menos de `desvio_minimo_relativo` da mediana também
    (série apertada infla z e IQR). Razão extrema basta sozinha.
    """
    if "razao" in criterios:
        return True
    if len(criterios) < 2:
        return False
    minimo = politica.desvio_minimo_relativo if politica is not None \
        else ZERO
    razao = _decimal((metricas or {}).get("razao_mediana"))
    if minimo > 0 and razao is not None and abs(razao - 1) < minimo:
        return False
    return True


def _forte(criterios: list[str]) -> bool:
    """Razão extrema confirmada por um critério robusto."""
    return "razao" in criterios and len(criterios) >= 2


def _frase(valor: Decimal, metricas: dict) -> str:
    mediana = _decimal(metricas.get("mediana"))
    partes = [f"preço de {estatistica.brl(valor)} contra mediana de "
              f"{estatistica.brl(mediana)} entre {metricas.get('n')} preço(s) "
              "comparável(is) do item"]
    if metricas.get("razao_mediana"):
        partes.append(f"razão {metricas['razao_mediana'].replace('.', ',')}× "
                      "a mediana")
    if metricas.get("z_modificado"):
        partes.append("z modificado "
                      + metricas["z_modificado"].replace(".", ","))
    if metricas.get("criterios"):
        partes.append(f"critérios: {metricas['criterios']}")
    return "; ".join(partes)


def reavaliar_com_jev(avaliacao: Avaliacao, escolha: str,
                      politica: PoliticaSaneamento = POLITICA_PADRAO) -> Avaliacao:
    """
    Aplica a evidência do Jev a uma avaliação estatística já feita.

    O Jev classifica; o motor decide. Divergência de objeto apontada pelo
    Jev só DESCONSIDERA quando o preço já era suspeito e o grupo
    comparável corrobora — duas evidências independentes. Sozinha, leva
    à revisão humana. Dúvida de unidade/embalagem/informação: revisão.
    """
    if not escolha or escolha == "compatible" or \
            avaliacao.desfecho == DESCONSIDERADA:
        return avaliacao
    codigos = list(avaliacao.codigos)
    if DIVERGENCIA_JEV not in codigos:
        codigos.append(DIVERGENCIA_JEV)
    if escolha in JEV_DIVERGENTE and avaliacao.suspeita and \
            avaliacao.corroborada and \
            CONTEXTO_COMERCIAL not in avaliacao.codigos and \
            politica.autoexclusao_estatistica:
        if CORROBORADO not in codigos:
            codigos.append(CORROBORADO)
        return Avaliacao(
            avaliacao.id, DESCONSIDERADA, codigos,
            f"o Jev apontou objeto/especificação diferente ({escolha}) e o "
            "preço é atípico frente a referências independentes que "
            "corroboram a faixa — " + avaliacao.explicacao,
            avaliacao.metricas, avaliacao.valor, avaliacao.valor_original,
            avaliacao.suspeita, avaliacao.corroborada)
    return Avaliacao(
        avaliacao.id, REVISAO, codigos,
        f"o Jev registrou ressalva de comparabilidade ({escolha}); a "
        "recomendação sozinha não descarta preço — "
        + (avaliacao.explicacao or "confira a fonte"),
        avaliacao.metricas, avaliacao.valor, avaliacao.valor_original,
        avaliacao.suspeita, avaliacao.corroborada)


def avaliar(observacoes: list[Observacao],
            politica: PoliticaSaneamento = POLITICA_PADRAO, *,
            texto_item: str = "") -> Triagem:
    """
    Triagem das cotações de UM item. Pura: não lê banco, não chama IA.

    A mesma lista de entrada dá sempre o mesmo resultado (a ordem só
    decide qual das duplicatas fica como observação).
    """
    triagem = Triagem(versao=politica.versao)
    avaliacoes: dict[str, Avaliacao] = {}

    # 1. Invalidação objetiva
    validas: list[Observacao] = []
    vistas: dict[str, str] = {}
    for obs in observacoes:
        original = obs.valor_original if obs.valor_original is not None \
            else obs.valor
        if original is None or original <= ZERO or \
                (obs.valor is not None and obs.valor <= ZERO):
            avaliacoes[obs.id] = Avaliacao(
                obs.id, DESCONSIDERADA, [VALOR_INVALIDO],
                "valor nulo, zero, negativo ou não numérico — não é preço",
                {}, obs.valor, obs.valor_original)
            continue
        if obs.valor is None:
            if obs.unidade_recuperavel:
                # há chance de recuperar o fator na fonte: revisão antes de
                # qualquer descarte terminal (pacote, camada 1)
                avaliacoes[obs.id] = Avaliacao(
                    obs.id, REVISAO, [UNIDADE_NAO_CONVERSIVEL],
                    "sem conversão comprovada para a unidade do item — o "
                    "fator de embalagem/medida não veio da fonte; confira "
                    "no documento de origem", {}, None, obs.valor_original)
            else:
                avaliacoes[obs.id] = Avaliacao(
                    obs.id, DESCONSIDERADA, [UNIDADE_NAO_CONVERSIVEL],
                    "unidade de grandeza diferente da do item (ex.: hora × "
                    "mês) — não há conversão possível com o dado da fonte",
                    {}, None, obs.valor_original)
            continue
        if not obs.natureza_preco:
            avaliacoes[obs.id] = Avaliacao(
                obs.id, REVISAO, [NATUREZA_NAO_PRECO],
                "o valor não é preço praticado (ex.: estimativa de outro "
                "órgão)", {}, obs.valor, obs.valor_original)
            continue
        if obs.duplicidade:
            primeira = vistas.get(obs.duplicidade)
            if primeira is not None:
                avaliacoes[obs.id] = Avaliacao(
                    obs.id, DESCONSIDERADA, [DUPLICIDADE],
                    f"mesma linha do mesmo documento que {primeira} — "
                    "contada uma vez na estatística; registro preservado",
                    {}, obs.valor, obs.valor_original)
                continue
            vistas[obs.duplicidade] = obs.id
        validas.append(obs)

    # 2. Suspeita estatística — só sobre os comparáveis válidos do item
    est = estatistica.calcular([o.valor for o in validas])
    if est is not None:
        triagem.serie = {
            "n": est.quantidade, "mediana": _texto(est.mediana),
            "mad": _texto(est.mad), "q1": _texto(est.q1),
            "q3": _texto(est.q3), "iqr": _texto(est.iqr),
            "menor": _texto(est.menor), "maior": _texto(est.maior),
            "origens": len({o.origem or o.id for o in validas})}
    calculos = {}
    for obs in validas:
        calculos[obs.id] = _metricas(obs.valor, est, politica)
    suspeitas = {oid for oid, (metricas, crit) in calculos.items()
                 if _suspeita(crit, metricas, politica)}
    normais = [o for o in validas if o.id not in suspeitas]
    origens_normais = {o.origem or o.id for o in normais}
    valores_normais = [o.valor for o in normais]
    homogeneo = bool(valores_normais) and (
        max(valores_normais) / min(valores_normais) < politica.razao_alta)
    corroborada = (len(origens_normais) >= politica.minimo_origens_independentes
                   and homogeneo)
    pequena = est is not None and \
        est.quantidade < politica.minimo_para_autoexclusao
    # Com dois preços não há maioria: 10 e 80 não dizem qual está errado.
    # Com três ou quatro, a razão ainda aponta o destoante (que vai para
    # revisão); se nenhum se destaca e a série é larga, todos vão.
    inconclusiva = (pequena and len(validas) >= 2
                    and (len(validas) <= 2 or not suspeitas)
                    and max(o.valor for o in validas)
                    / min(o.valor for o in validas) >= politica.razao_alta)

    for obs in validas:
        metricas, criterios = calculos[obs.id]
        comerciais = sinais_comerciais(obs.texto, texto_item)
        if inconclusiva:
            # 1–4 preços muito distantes entre si: não há como saber qual
            # está errado. Todos para revisão; nenhum descarte.
            avaliacao = Avaliacao(
                obs.id, REVISAO, [AMOSTRA_PEQUENA, DISPERSAO_INCONCLUSIVA],
                "poucos preços e muito distantes entre si — a série não "
                "permite apontar qual está fora; " + _frase(obs.valor,
                                                           metricas),
                metricas, obs.valor, obs.valor_original)
        elif obs.id not in suspeitas:
            avaliacao = Avaliacao(obs.id, ELEGIVEL, [], "", metricas,
                                  obs.valor, obs.valor_original)
        else:
            codigos = [VARIACAO_RELEVANTE]
            if _forte(criterios):
                codigos.insert(0, EXTREMO)
            if pequena:
                desfecho, motivo = REVISAO, (
                    "amostra pequena: sinal estatístico não basta para "
                    "descartar")
                codigos.append(AMOSTRA_PEQUENA)
            elif comerciais:
                desfecho, motivo = REVISAO, (
                    "há condição comercial que pode explicar o preço ("
                    + ", ".join(comerciais) + ")")
                codigos.append(CONTEXTO_COMERCIAL)
            elif not corroborada:
                desfecho, motivo = REVISAO, (
                    "as demais referências não formam grupo independente e "
                    "homogêneo que corrobore a faixa")
                codigos.append(SEM_CORROBORACAO)
            elif _forte(criterios) and politica.autoexclusao_estatistica:
                desfecho, motivo = DESCONSIDERADA, (
                    f"preço extremo frente a {len(normais)} referências "
                    f"comparáveis de {len(origens_normais)} origens "
                    "independentes que corroboram a faixa")
                codigos.append(CORROBORADO)
            else:
                desfecho, motivo = REVISAO, "variação relevante a conferir"
            avaliacao = Avaliacao(
                obs.id, desfecho, codigos,
                motivo + "; " + _frase(obs.valor, metricas), metricas,
                obs.valor, obs.valor_original, suspeita=True,
                corroborada=corroborada and not pequena)
        if obs.jev:
            avaliacao = reavaliar_com_jev(avaliacao, obs.jev, politica)
        avaliacoes[obs.id] = avaliacao

    triagem.avaliacoes = [avaliacoes[o.id] for o in observacoes]
    return triagem


# ---------------------------------------------------------------------------
# Adaptadores — `Referencia` (antes de gravar) e linha gravada (depois)
# ---------------------------------------------------------------------------
def _origem(fonte_id: str, orgao, fornecedor, externa, id_externo) -> str:
    """
    Observação independente: o mesmo órgão comprando do mesmo fornecedor
    é UMA origem, ainda que em linhas diferentes. Sem esses dados, o
    documento de origem; sem ele, a própria referência.
    """
    if orgao or fornecedor:
        return f"{str(orgao or '').strip().casefold()}|" \
               f"{str(fornecedor or '').strip().casefold()}"
    if externa:
        return f"doc|{externa}"
    return f"{fonte_id}:{id_externo}"


def _duplicidade(externa, fornecedor, valor_original) -> str | None:
    """Mesma linha do mesmo documento: id oficial + fornecedor + valor."""
    if not externa or valor_original is None:
        return None
    return f"{externa}|{str(fornecedor or '').strip().casefold()}|" \
           f"{format(valor_original, 'f')}"


def observacao_da_referencia(referencia, chave: str | None = None) -> Observacao:
    """`modelo.Referencia` (ainda não gravada) → `Observacao`."""
    from .modelo import NATUREZAS_COMPARAVEIS

    externa = referencia.referencia_externa
    fornecedor = referencia.ni_fornecedor or referencia.fornecedor
    return Observacao(
        id=chave or referencia.chave_dedupe,
        valor=referencia.valor_unitario_normalizado,
        valor_original=referencia.valor_unitario_original,
        unidade=referencia.unidade_normalizada,
        origem=_origem(referencia.fonte.id, referencia.orgao, fornecedor,
                       externa, referencia.id_externo),
        duplicidade=_duplicidade(externa, fornecedor,
                                 referencia.valor_unitario_original),
        texto=" ".join(p for p in (referencia.descricao_original,
                                    referencia.marca or "") if p),
        natureza_preco=referencia.natureza_valor in NATUREZAS_COMPARAVEIS,
        unidade_recuperavel=not _irrecuperavel(referencia.motivos))


def observacao_da_linha(linha: dict, *, jev: str = "") -> Observacao:
    """Linha gravada (`pesquisa_preco_referencias`) → `Observacao`."""
    from .modelo import NATUREZAS_COMPARAVEIS

    externa = linha.get("referencia_externa")
    fornecedor = linha.get("ni_fornecedor") or linha.get("fornecedor")
    original = _decimal(linha.get("valor_unitario_original"))
    return Observacao(
        id=str(linha.get("id")),
        valor=_decimal(linha.get("valor_unitario_normalizado")),
        valor_original=original,
        unidade=linha.get("unidade_normalizada"),
        origem=_origem(str(linha.get("fonte_id") or ""), linha.get("orgao"),
                       fornecedor, externa, linha.get("id_externo")),
        duplicidade=_duplicidade(externa, fornecedor, original),
        texto=" ".join(str(p) for p in (linha.get("descricao_original"),
                                         linha.get("marca")) if p),
        natureza_preco=str(linha.get("natureza_valor") or "") in
        {n.value for n in NATUREZAS_COMPARAVEIS},
        unidade_recuperavel=not _irrecuperavel(linha.get("motivos")),
        jev=jev, sinalizada=str(linha.get("status")) == "warning")


# Desfechos que a seleção anterior já produzia por conta própria (sem
# unidade comprovada, valor que não é preço): ficam CONTADOS na trilha, e
# só são gravados linha a linha quando a cotação grava tudo (sem teto). O
# resto — o que pede fundamento técnico — é sempre gravado.
_SO_CONTADOS = frozenset({UNIDADE_NAO_CONVERSIVEL, NATUREZA_NAO_PRECO})


def retem(avaliacao: Avaliacao) -> bool:
    return avaliacao.desfecho != ELEGIVEL and         not set(avaliacao.codigos) <= _SO_CONTADOS


def _irrecuperavel(motivos) -> bool:
    from .unidades import MOTIVO_INCOMPATIVEL

    return any(str(m) == MOTIVO_INCOMPATIVEL for m in (motivos or []))


def motivo_da_avaliacao(avaliacao: Avaliacao, versao: str) -> str:
    """O texto que fica em `motivos` da referência retida."""
    rotulo = (ROTULO_DESCONSIDERADA if avaliacao.desfecho == DESCONSIDERADA
              else ROTULO_REVISAO)
    return (f"{rotulo}: {avaliacao.explicacao} "
            f"[{', '.join(avaliacao.codigos)}; política {versao}]")


def status_do_desfecho(desfecho: str) -> str:
    """Desfecho → status existente da referência (sem enum novo no banco)."""
    return {DESCONSIDERADA: "rejected", REVISAO: "manual_review"}.get(
        desfecho, "")


# ---------------------------------------------------------------------------
# Revisão 02 — sinalizar na cesta e recompor a cesta formada pelo teto
# ---------------------------------------------------------------------------
def fica_sinalizada_na_cesta(avaliacao: Avaliacao,
                             politica: PoliticaSaneamento = POLITICA_PADRAO
                             ) -> bool:
    """
    Suspeita só ESTATÍSTICA numa amostra pequena demais para decidir: o
    preço fica no cálculo, sinalizado, e o alerta o acompanha (02_JEV:
    "4 ≤ n < 8: não eliminar apenas por variação"). Divergência apontada
    pelo Jev, condição comercial ou falta de unidade não entram aqui:
    essas continuam fora da cesta, em revisão.
    """
    if not politica.sinalizar_na_cesta_em_amostra_pequena or \
            avaliacao.desfecho != REVISAO:
        return False
    codigos = set(avaliacao.codigos)
    return AMOSTRA_PEQUENA in codigos and not codigos & {
        DIVERGENCIA_JEV, CONTEXTO_COMERCIAL, UNIDADE_NAO_CONVERSIVEL,
        NATUREZA_NAO_PRECO}


def motivo_da_sinalizacao(avaliacao: Avaliacao, versao: str) -> str:
    return (f"{ROTULO_SINALIZADA}: {avaliacao.explicacao} "
            f"[{', '.join(avaliacao.codigos)}; política {versao}]")


def sinalizada_pela_triagem(linha: dict) -> bool:
    return str(linha.get("status")) == "warning" and \
        _tem_rotulo(linha, ROTULO_SINALIZADA)


@dataclass
class Recomposicao:
    """O que a reavaliação da cesta formada decidiu."""

    selecionadas: list
    reservas: list
    # (referência, avaliação) que saíram da cesta: desconsideradas ou
    # substituídas por outra elegível (revisão)
    saidas: list = field(default_factory=list)
    # referências que ficam NA cesta, sinalizadas (sem alternativa)
    sinalizadas: dict = field(default_factory=dict)
    rodadas: int = 0


def _distancia(avaliacao: Avaliacao) -> Decimal:
    razao = _decimal(avaliacao.metricas.get("razao_mediana"))
    if razao is None or razao <= ZERO:
        return ZERO
    return max(razao, Decimal(1) / razao)


def recompor_cesta(selecionadas: list, reservas: list,
                   politica: PoliticaSaneamento = POLITICA_PADRAO, *,
                   texto_item: str = "") -> Recomposicao:
    """
    Reavalia a cesta JÁ formada pelo teto e repõe com as próximas
    elegíveis, na ordem em que vieram (fonte e comparabilidade, nunca
    preço). 02_JEV, "Reparação da cesta e limite de 15":

    * desconsiderada na cesta (extremo corroborado, n ≥ 8) → sai, e a
      próxima elegível entra no lugar;
    * suspeita sem certeza → sai para REVISÃO só se houver outra elegível
      para o lugar; sem alternativa, fica NA cesta, sinalizada;
    * nada é apagado: quem sai leva status e motivo técnico.

    Um preço por rodada (o mais distante da mediana): tirar vários de uma
    vez mudaria a mediana sob os pés dos outros. Termina em no máximo
    len(selecionadas) + len(reservas) rodadas — cada uma consome alguém.
    """
    cesta = list(selecionadas)
    fila = list(reservas)
    resultado = Recomposicao(selecionadas=cesta, reservas=fila)
    limite = len(cesta)
    for rodada in range(len(selecionadas) + len(reservas) + 1):
        resultado.rodadas = rodada
        if not cesta:
            break
        triagem = avaliar([observacao_da_referencia(r) for r in cesta],
                          politica, texto_item=texto_item)
        por_id = triagem.por_id()
        problemas = [(r, por_id[r.chave_dedupe]) for r in cesta
                     if por_id[r.chave_dedupe].desfecho != ELEGIVEL]
        if not problemas:
            resultado.sinalizadas = {}
            break
        desconsideradas = [p for p in problemas
                           if p[1].desfecho == DESCONSIDERADA]
        alvo = (desconsideradas or
                (problemas if fila else []))
        if not alvo:
            # sem alternativa: as suspeitas ficam, sinalizadas
            resultado.sinalizadas = {r.chave_dedupe: a for r, a in problemas}
            break
        referencia, avaliacao = max(alvo, key=lambda p: _distancia(p[1]))
        cesta.remove(referencia)
        if avaliacao.desfecho == REVISAO:
            avaliacao = Avaliacao(
                avaliacao.id, REVISAO,
                list(avaliacao.codigos) + [SUBSTITUIDA],
                "fora do padrão da cesta formada, e havia outra referência "
                "elegível para o lugar — " + avaliacao.explicacao,
                avaliacao.metricas, avaliacao.valor, avaliacao.valor_original,
                avaliacao.suspeita, avaliacao.corroborada)
        resultado.saidas.append((referencia, avaliacao))
        while fila and len(cesta) < limite:
            cesta.append(fila.pop(0))
    return resultado


# ---------------------------------------------------------------------------
# Resumo por item — "X encontrados • Y incluídos • Z desconsiderados…"
# ---------------------------------------------------------------------------
def _tem_rotulo(linha: dict, rotulo: str) -> bool:
    return any(str(m).startswith(rotulo) for m in (linha.get("motivos") or []))


def desconsiderada_pelo_jev(linha: dict) -> bool:
    return str(linha.get("status")) == "rejected" and \
        _tem_rotulo(linha, ROTULO_DESCONSIDERADA)


def desconsiderada_por_analise(linha: dict) -> bool:
    """
    Desconsiderada pela triagem DEPOIS de analisada como preço do item
    (extremo corroborado, objeto divergente apontado pelo Jev) — a que
    pede fundamento na metodologia (08_COMPLIANCE, caso B). Duplicata,
    valor inválido e unidade sem conversão não chegaram a ser preço do
    item: ficam contadas, não listadas.
    """
    if not desconsiderada_pelo_jev(linha):
        return False
    texto = " ".join(str(m) for m in (linha.get("motivos") or []))
    return any(c in texto for c in (EXTREMO, CORROBORADO, DIVERGENCIA_JEV))


def em_revisao_pela_triagem(linha: dict) -> bool:
    return str(linha.get("status")) == "manual_review" and \
        _tem_rotulo(linha, ROTULO_REVISAO)


def resumo_do_item(linhas: list[dict], encontrados: int | None = None) -> dict:
    from . import cesta

    return {
        "encontrados": encontrados if encontrados is not None else len(linhas),
        "incluidos": len(cesta.consideradas(linhas)),
        "desconsiderados": sum(1 for l in linhas if desconsiderada_pelo_jev(l)),
        "revisao": sum(1 for l in linhas
                       if str(l.get("status")) == "manual_review"),
        "sinalizados": sum(1 for l in linhas if sinalizada_pela_triagem(l)),
    }


def frase_do_resumo(resumo: dict) -> str:
    frase = (f"{resumo['encontrados']} encontrado(s) • {resumo['incluidos']} "
             f"usado(s) no preço • {resumo['desconsiderados']} "
             f"desconsiderado(s) pela triagem • {resumo['revisao']} em revisão")
    if resumo.get("sinalizados"):
        frase += f" • {resumo['sinalizados']} na cesta para conferir"
    return frase


# ---------------------------------------------------------------------------
# Verificação da CESTA antes da emissão — o mesmo `avaliar`
# ---------------------------------------------------------------------------
@dataclass
class Alerta:
    item_id: str
    numero: int
    descricao: str
    referencia_id: str
    valor: str | None
    mediana: str | None
    codigos: list[str]
    mensagem: str
    origem: str = ""     # fonte e órgão, para quem confere reconhecer a cotação

    def para_registro(self) -> dict:
        return asdict(self)


def alertas_da_cesta(itens: list[dict], referencias: dict[str, list[dict]],
                     politica: PoliticaSaneamento = POLITICA_PADRAO, *,
                     pareceres: dict[str, str] | None = None
                     ) -> list[Alerta]:
    """
    Preços DA CESTA que merecem conferência antes de emitir: os que o
    motor não daria como elegíveis hoje, e os que alguém já marcou como
    sinalizados. Não muda nada — só aponta, e a emissão segue.

    `pareceres` é a escolha do Jev GRAVADA na trilha, por id da
    referência (`ciencia.pareceres_do_jev`). Segunda auditoria de
    18/10/2026 (N-03): 347 referências estavam na cesta com o Jev dizendo
    "produto/especificação diferente", e este aviso recalculava a triagem
    sem o parecer. Agora "diferente" passa pelo mesmo `reavaliar_com_jev`
    da coleta e vira alerta. A IA não tira nada da cesta: o alerta pede a
    conferência de uma pessoa antes de emitir.

    Também vira alerta o preço da cesta com fator de conversão extremo
    (N-06): as cestas formadas antes da barreira de conversão.
    """
    from . import cesta, unidades

    pareceres = pareceres or {}
    saida: list[Alerta] = []
    for item in sorted(itens, key=lambda i: int(i.get("numero") or 0)):
        linhas = cesta.consideradas(referencias.get(str(item.get("id")), []))
        if not linhas:
            continue
        triagem = avaliar(
            [observacao_da_linha(l, jev=_parecer_divergente(
                pareceres.get(str(l.get("id"))))) for l in linhas],
            politica, texto_item=str(item.get("descricao") or ""))
        por_id = triagem.por_id()
        for linha in linhas:
            avaliacao = por_id[str(linha.get("id"))]
            sinalizada = str(linha.get("status")) == "warning"
            fator = unidades.fator_extremo(
                linha.get("valor_unitario_original"),
                linha.get("valor_unitario_normalizado"))
            if avaliacao.desfecho == ELEGIVEL and not sinalizada and \
                    fator is None:
                continue
            codigos = list(avaliacao.codigos)
            if fator is not None:
                codigos.append(FATOR_EXTREMO)
            codigos = codigos or [VARIACAO_RELEVANTE]
            if sinalizada and SINALIZADA_NA_CESTA not in codigos:
                codigos.append(SINALIZADA_NA_CESTA)
            saida.append(Alerta(
                item_id=str(item.get("id")),
                numero=int(item.get("numero") or 0),
                descricao=str(item.get("descricao") or ""),
                referencia_id=str(linha.get("id")),
                valor=_texto(avaliacao.valor),
                mediana=avaliacao.metricas.get("mediana")
                or triagem.serie.get("mediana"),
                codigos=codigos,
                mensagem=_mensagem_do_alerta(
                    avaliacao, sinalizada,
                    _parecer_divergente(pareceres.get(str(linha.get("id")))),
                    fator, linha),
                origem=" · ".join(str(p) for p in (
                    linha.get("fonte_nome"), linha.get("orgao")) if p)))
    return saida


def _parecer_divergente(escolha: str | None) -> str:
    """Só "produto/especificação diferente" do Jev vira alerta na emissão."""
    return escolha if escolha in JEV_DIVERGENTE else ""


def _mensagem_do_alerta(avaliacao: Avaliacao, sinalizada: bool,
                        escolha: str = "", fator: Decimal | None = None,
                        linha: dict | None = None) -> str:
    """
    Na emissão, o preço já está NA CESTA: a frase diz a variação e as
    contas, não o desfecho que a triagem daria antes da cesta.
    """
    from . import unidades

    partes = []
    if sinalizada:
        partes.append("mantida na cesta como sinalizada por decisão "
                      "registrada")
    if escolha:
        partes.append(
            "o Jev registrou parecer de "
            + ("produto diferente" if escolha == "different_product"
               else "especificação diferente")
            + " do item — parecer da IA, não decisão: confira a fonte e "
            "decida se o preço fica na cesta")
    if fator is not None and linha is not None:
        partes.append(unidades.frase_do_fator_extremo(
            fator, linha.get("valor_unitario_original"),
            linha.get("valor_unitario_normalizado")))
    if avaliacao.metricas.get("criterios") and avaliacao.valor is not None:
        partes.append("variação relevante: " + _frase(avaliacao.valor,
                                                     avaliacao.metricas))
    elif avaliacao.explicacao and not escolha:
        partes.append(avaliacao.explicacao)
    return "; ".join(partes) or "confira antes de emitir"


def assinatura(pesquisa_id: str, revisao: str, alertas: list[Alerta],
               politica: PoliticaSaneamento = POLITICA_PADRAO) -> str:
    """
    O que a ciência vincula: a pesquisa, o identificador do resultado
    (`relatorio.identificador_da_versao`), os alertas e a política. Muda
    qualquer um — preço, cesta, regra de alerta — e a ciência anterior
    deixa de valer.
    """
    canonico = json.dumps(
        {"pesquisa": str(pesquisa_id), "revisao": revisao,
         "politica": politica.versao,
         "alertas": sorted((a.item_id, a.referencia_id, a.valor or "",
                            ",".join(sorted(a.codigos))) for a in alertas)},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()
