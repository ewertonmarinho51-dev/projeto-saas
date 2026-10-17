"""
Seletor de referências — determinístico primeiro, Jev só no ambíguo.

O diferencial do GovConnect (pacote, `04_SELETOR_JEV_E_CUSTOS.md`) não é
"IA que acha preço": é usar IA BARATA apenas onde a regra determinística
não decide, sobre referências REAIS já coletadas, e sempre como
recomendação para o revisor.

    linhas do item ──► barreiras (decisoes.impedimento) ──► INCOMPATÍVEL
                  └──► código + descrição idênticos ────────► COMPARÁVEL (sem IA)
                  └──► comparabilidade ≥ alta ──────────────► COMPARÁVEL (sem IA)
                  └──► abaixo do piso baixo ────────────────► INCOMPATÍVEL
                  └──► faixa cinzenta ──► Jev (com teto) ───► REVIEW_REQUIRED
                                                               + recomendação

Regras que este módulo não cruza:

* a IA nunca dá preço, nunca põe nem tira referência da cesta, nunca
  conclui item: a proposta é GRAVADA na trilha e mostrada; quem decide é
  o revisor (`cotacoes.alterar_status_referencia`);
* aceite automático por IA só existe depois de calibração aprovada
  (`aceite_automatico_permitido`) — e mesmo então este módulo não o
  executa: devolve a sugestão marcada e a decisão segue humana;
* sem flag (`jev_price_research`), sem orçamento, sem credencial ou com
  a IA fora do ar: a classificação determinística continua e o caso
  ambíguo fica REVIEW_REQUIRED. Nada para a cotação;
* custo e chamadas são CONTADOS a partir do que o gateway devolveu —
  nada é estimado.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

from . import decisoes

VERSAO_POLITICA = "2026-10-16.seletor-v1"

# Faixas da comparabilidade determinística (`matching`): acima de ALTA a
# regra decide sozinha; abaixo de BAIXA é produto diferente; no meio está
# o caso semântico, o único em que a IA vale o custo.
ALTA = Decimal("0.75")
BAIXA = Decimal("0.25")

# Tetos padrão — configuráveis por cotação em `filtros.jev`.
MAX_CONSULTAS_POR_ITEM = 5
MAX_CONSULTAS_POR_COTACAO = 60
CUSTO_MAXIMO_POR_COTACAO = Decimal("1.00")   # USD, como o gateway reporta

COMPARAVEL, INCOMPATIVEL, REVISAO = ("COMPARABLE", "INCOMPATIBLE",
                                     "REVIEW_REQUIRED")

CALIBRACAO = (Path(__file__).resolve().parents[2] / "docs" / "jev"
              / "calibracao_aprovada.json")


def aceite_automatico_permitido() -> bool:
    """
    Só com relatório de calibração APROVADO por responsável humano: meta
    de falso positivo definida ANTES, dataset rotulado por gente e métrica
    atingida. Sem o arquivo — o caso hoje — é False, e ponto.
    """
    try:
        dados = json.loads(CALIBRACAO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(dados.get("aprovado_por") and dados.get("meta_definida_em")
                and dados.get("rotulos_humanos", 0) >= 200
                and dados.get("meta_atingida") is True)


@dataclass
class Analise:
    referencia_id: str
    classe: str              # 'exato' | 'alta' | 'ambiguo' | 'baixa' | 'bloqueada'
    decisao: str             # COMPARABLE | INCOMPATIBLE | REVIEW_REQUIRED
    motivo: str
    origem: str              # 'deterministica' | 'jev' | 'cache' | 'sem_jev' | 'orcamento'
    recomendacao: str = ""   # o que o Jev sugeriu, quando sugeriu
    escolha: str = ""        # a opção FECHADA do Jev (`decisoes.MOTIVOS`)
    custo: str | None = None
    latencia_ms: int | None = None


@dataclass
class Proposta:
    item_id: str
    versao_politica: str = VERSAO_POLITICA
    analises: list[Analise] = field(default_factory=list)
    chamadas_ia: int = 0
    cache_hits: int = 0
    custo_total: Decimal = Decimal("0")
    bloqueadas_por_orcamento: int = 0
    aceite_automatico: bool = False
    duracao_ms: int = 0

    def contagem(self) -> dict[str, int]:
        saida = {COMPARAVEL: 0, INCOMPATIVEL: 0, REVISAO: 0}
        for a in self.analises:
            saida[a.decisao] += 1
        return saida

    def para_evento(self) -> dict:
        return {"item_id": self.item_id, "versao_politica": self.versao_politica,
                "contagem": self.contagem(), "chamadas_ia": self.chamadas_ia,
                "cache_hits": self.cache_hits,
                "custo_total": format(self.custo_total, "f"),
                "bloqueadas_por_orcamento": self.bloqueadas_por_orcamento,
                "aceite_automatico": self.aceite_automatico,
                "duracao_ms": self.duracao_ms,
                "analises": [asdict(a) for a in self.analises]}


def _decimal(valor) -> Decimal | None:
    try:
        return None if valor in (None, "") else Decimal(str(valor))
    except ArithmeticError:
        return None


def classificar(item: dict, linha: dict, cotacao: dict) -> Analise:
    """A parte determinística — custo zero, reproduzível."""
    rid = str(linha.get("id"))
    bloqueio = decisoes.impedimento(item, linha, cotacao)
    if bloqueio:
        return Analise(rid, "bloqueada", INCOMPATIVEL, bloqueio, "deterministica")
    if decisoes.identidade_exata(item, linha):
        return Analise(rid, "exato", COMPARAVEL,
                       "código de catálogo e descrição idênticos",
                       "deterministica")
    score = _decimal(linha.get("score")) or Decimal("0")
    if score >= ALTA:
        return Analise(rid, "alta", COMPARAVEL,
                       f"comparabilidade {score:.0%} (≥ {ALTA:.0%}), unidade e "
                       "natureza comprovadas", "deterministica")
    if score < BAIXA:
        return Analise(rid, "baixa", INCOMPATIVEL,
                       f"comparabilidade {score:.0%} (< {BAIXA:.0%}): produto "
                       "diferente", "deterministica")
    return Analise(rid, "ambiguo", REVISAO,
                   f"comparabilidade {score:.0%} na faixa de dúvida "
                   f"({BAIXA:.0%}–{ALTA:.0%})", "deterministica")


def _tetos(cotacao: dict) -> tuple[int, int, Decimal]:
    jev = (cotacao.get("filtros") or {}).get("jev") or {}
    return (int(jev.get("max_por_item") or MAX_CONSULTAS_POR_ITEM),
            int(jev.get("max_por_cotacao") or MAX_CONSULTAS_POR_COTACAO),
            _decimal(jev.get("custo_maximo")) or CUSTO_MAXIMO_POR_COTACAO)


def consumo_da_cotacao(eventos: list[dict]) -> tuple[int, Decimal]:
    """Chamadas e custo JÁ gastos, somados das propostas registradas."""
    chamadas, custo = 0, Decimal("0")
    for evento in eventos:
        if evento.get("tipo") != "selecao_sugerida":
            continue
        p = evento.get("payload") or {}
        chamadas += int(p.get("chamadas_ia") or 0)
        custo += _decimal(p.get("custo_total")) or Decimal("0")
    return chamadas, custo


def _escolha(registro: dict) -> str:
    """A opção fechada do Jev, para o motor de saneamento (evidência)."""
    resposta = (registro.get("response") or {}).get("answers") or {}
    escolha = (resposta.get("price_reference_mismatch") or {}).get("choice")
    return str(escolha) if escolha in decisoes.MOTIVOS else ""


def _recomendacao(registro: dict) -> str:
    escolha = _escolha(registro)
    if not escolha:
        return ""
    return ("sugere comparável" if escolha == "compatible"
            else f"sugere não comparável: {decisoes.MOTIVOS.get(escolha, escolha)}")


def propor(cotacao: dict, item: dict, linhas: list[dict], repositorio, *,
           consultar=None, ia_habilitada: bool | None = None) -> Proposta:
    """
    Classifica cada referência ainda não decidida pelo revisor e, no
    ambíguo e dentro do teto, consulta o Jev pelo caminho existente
    (`decisoes.revisar_referencia` → `ai_gateway.decision`). Grava a
    proposta como evento `selecao_sugerida` e a devolve. NÃO altera cesta.
    """
    from .. import db, governanca

    inicio = time.monotonic()
    if ia_habilitada is None:
        ia_habilitada = db.flag_ativa(governanca.FLAG_JEV_PRECOS)
    consultar = consultar or decisoes.revisar_referencia
    por_item, por_cotacao, teto_custo = _tetos(cotacao)
    gastas, gasto = consumo_da_cotacao(
        repositorio.listar_eventos(str(cotacao["id"]), limite=1000))
    proposta = Proposta(item_id=str(item["id"]))
    for linha in linhas:
        if str(linha.get("status")) == "rejected":
            continue   # decisão humana registrada: não se reanalisa
        analise = classificar(item, linha, cotacao)
        if analise.classe == "ambiguo":
            if not ia_habilitada:
                analise.origem = "sem_jev"
                analise.motivo += "; análise complementar desligada — revisão humana"
            elif (proposta.chamadas_ia >= por_item
                  or gastas + proposta.chamadas_ia >= por_cotacao
                  or gasto + proposta.custo_total >= teto_custo):
                analise.origem = "orcamento"
                analise.motivo += "; teto de consultas/custo atingido — revisão humana"
                proposta.bloqueadas_por_orcamento += 1
            else:
                t0 = time.monotonic()
                try:
                    registro = consultar(str(cotacao["id"]), str(item["id"]),
                                         str(linha["id"]), repo=repositorio)
                except Exception as exc:  # noqa: BLE001 — IA fora não decide nada
                    registro = {"status": "manual_review", "called": False,
                                "erro": type(exc).__name__}
                analise.latencia_ms = round((time.monotonic() - t0) * 1000)
                if registro.get("cache_hit"):
                    proposta.cache_hits += 1
                    analise.origem = "cache"
                elif registro.get("called"):
                    proposta.chamadas_ia += 1
                    analise.origem = "jev"
                    custo = _decimal(((registro.get("response") or {})
                                      .get("usage") or {}).get("cost"))
                    if custo is not None:
                        proposta.custo_total += custo
                        analise.custo = format(custo, "f")
                else:
                    analise.origem = "sem_jev"
                analise.recomendacao = _recomendacao(registro)
                analise.escolha = _escolha(registro)
                # Sem calibração aprovada, a saída da IA é RECOMENDAÇÃO:
                # a decisão continua REVIEW_REQUIRED (abstenção por padrão).
                analise.decisao = REVISAO
                analise.motivo += ("; " + str(registro.get("explicacao") or
                                              "requer revisão humana"))
        proposta.analises.append(analise)
    proposta.aceite_automatico = aceite_automatico_permitido()
    proposta.duracao_ms = round((time.monotonic() - inicio) * 1000)
    repositorio.registrar_evento(
        str(cotacao["id"]), "selecao_sugerida", item_id=str(item["id"]),
        automatico=True,
        descricao=(f"{proposta.contagem()[COMPARAVEL]} comparável(is), "
                   f"{proposta.contagem()[REVISAO]} para revisão, "
                   f"{proposta.contagem()[INCOMPATIVEL]} incompatível(is)"),
        payload=proposta.para_evento())
    return proposta


def seletor_padrao():
    """O `seletor` que `cotacoes.pesquisar_item(modo='automatico')` recebe."""
    from . import repositorio

    def _executar(cotacao, item, linhas):
        return propor(cotacao, item, linhas, repositorio).para_evento()

    return _executar


def sugestoes_do_item(eventos: list[dict], item_id: str) -> dict[str, dict]:
    """A análise mais recente de cada referência do item, para a tela."""
    saida: dict[str, dict] = {}
    for evento in eventos:   # listar_eventos vem do mais novo ao mais velho
        if evento.get("tipo") != "selecao_sugerida" or \
                str(evento.get("item_id")) != str(item_id):
            continue
        for analise in (evento.get("payload") or {}).get("analises") or []:
            saida.setdefault(str(analise.get("referencia_id")), analise)
    return saida
