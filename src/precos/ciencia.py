"""
Ciência de alertas antes da emissão do relatório (pacote Jev, RF-03).

Preço atípico na cesta NÃO trava o relatório. O que o servidor exige é
CIÊNCIA — um ato registrado, vinculado ao que a pessoa viu:

    preparar ──► sem alerta nem pendência ─────────────► emite direto
             └─► com alerta/pendência ─► aviso na tela
                                          ├─ Voltar e revisar: nada muda
                                          └─ Estou ciente: registrar
                                                 (revalida o snapshot)
    gerar documento ──► exigir(): ciência DESTA assinatura, DESTE usuário?
                          └─ não ──► CienciaNecessaria (o botão sozinho,
                                     ou outra aba, não emite)

A assinatura junta a pesquisa, o identificador do resultado
(`relatorio.identificador_da_versao`, que muda com qualquer preço, status
ou cesta), os alertas do motor único (`saneamento.alertas_da_cesta`), as
pendências nominais impeditivas e a versão da política. Mudou qualquer
um: a ciência anterior não vale, e o aviso volta.

O registro é um evento da trilha do tipo `pesquisa_revisada` — tipo que
o CHECK da tabela de eventos já aceita (sem migração) e que nenhum outro
fluxo usa —, com `payload.ato = "ciencia_de_alertas_na_emissao"`. O
gatilho do banco confere que `ator` é quem está autenticado: ciência de
outro usuário não se forja. A chave de idempotência é a assinatura + o
ator: duplo clique grava uma vez.

Isto NÃO é aprovação administrativa do preço: é a declaração de que quem
emitiu viu os alertas. O documento diz isso com essas palavras.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import relatorio, saneamento
from .perfil import obter as obter_perfil

TIPO_EVENTO = "pesquisa_revisada"
ATO = "ciencia_de_alertas_na_emissao"


class ErroDeCiencia(RuntimeError):
    """Falha técnica ao registrar — não é bloqueio por preço."""


@dataclass
class Preparo:
    """O que o servidor responde ao "quero emitir"."""

    pesquisa_id: str
    revisao: str
    alertas: list[saneamento.Alerta] = field(default_factory=list)
    pendencias: list[dict] = field(default_factory=list)
    assinatura: str = ""
    politica: str = saneamento.VERSAO_POLITICA

    @property
    def requer_ciencia(self) -> bool:
        return bool(self.alertas or self.pendencias)

    @property
    def itens_com_alerta(self) -> list[int]:
        return sorted({a.numero for a in self.alertas})

    def para_registro(self) -> dict:
        return {"ato": ATO, "assinatura": self.assinatura,
                "revisao": self.revisao, "politica": self.politica,
                "alertas": [a.para_registro() for a in self.alertas],
                "pendencias": [{"item_id": p.get("item_id"),
                                "numero": p.get("numero"),
                                "deficiencias": list(p.get("deficiencias")
                                                     or [])}
                               for p in self.pendencias]}


class CienciaNecessaria(Exception):
    """Há alertas e não há ciência válida para ESTA versão da cesta."""

    def __init__(self, preparo: Preparo):
        super().__init__("a emissão requer a ciência dos alertas exibidos")
        self.preparo = preparo


class CienciaDesatualizada(CienciaNecessaria):
    """A cesta mudou entre o aviso e a confirmação: novo aviso."""


def pareceres_do_jev(pesquisa_id: str, repositorio) -> dict[str, str]:
    """
    A escolha MAIS RECENTE do Jev para cada referência da pesquisa, como
    está gravada na trilha (`decisoes.revisar_referencia`). Entra nos
    alertas da emissão (N-03 da segunda auditoria de 18/10/2026).

    O aviso, a confirmação e a exigência do servidor leem daqui — a mesma
    leitura nos três, senão as assinaturas não batem. Repositório sem a
    leitura (dublê de teste antigo): nenhum parecer.
    """
    from .decisoes import MOTIVOS

    ler = getattr(repositorio, "pareceres_jev", None)
    if ler is None or not pesquisa_id:
        return {}
    saida: dict[str, str] = {}
    for linha in ler(pesquisa_id) or []:   # do mais novo ao mais velho
        rid = str(linha.get("referencia_id") or "")
        escolha = str(linha.get("escolha") or "")
        if rid and escolha in MOTIVOS:
            saida.setdefault(rid, escolha)
    return saida


def preparar(pesquisa: dict, itens: list[dict],
             referencias: dict[str, list[dict]],
             politica: saneamento.PoliticaSaneamento = saneamento.POLITICA_PADRAO,
             *, pareceres: dict[str, str] | None = None) -> Preparo:
    pesquisa_id = str(pesquisa.get("id") or "")
    revisao = relatorio.identificador_da_versao(pesquisa, itens, referencias)
    alertas = saneamento.alertas_da_cesta(itens, referencias, politica,
                                          pareceres=pareceres)
    pendencias = [p for p in relatorio.pendencias_nominais(
        itens, referencias, obter_perfil(pesquisa.get("perfil_normativo")))
        if p.get("impede")]
    base = saneamento.assinatura(pesquisa_id, revisao, alertas, politica)
    chave = base + "|" + ",".join(sorted(
        f"{p.get('item_id')}:{';'.join(p.get('deficiencias') or [])}"
        for p in pendencias))
    return Preparo(pesquisa_id=pesquisa_id, revisao=revisao, alertas=alertas,
                   pendencias=pendencias,
                   assinatura=hashlib.sha256(chave.encode("utf-8")).hexdigest(),
                   politica=politica.versao)


def localizar(pesquisa_id: str, assinatura: str, ator: str | None,
              repositorio) -> dict | None:
    """A ciência desta assinatura, dada por ESTE ator, se houver."""
    for evento in repositorio.listar_eventos(pesquisa_id, limite=500):
        if evento.get("tipo") != TIPO_EVENTO:
            continue
        payload = evento.get("payload") or {}
        if payload.get("ato") == ATO and \
                payload.get("assinatura") == assinatura and \
                str(evento.get("ator") or "") == str(ator or ""):
            return evento
    return None


def registrar(pesquisa: dict, preparo: Preparo, *, ator: str | None,
              repositorio, recarregar) -> dict:
    """
    "Estou ciente": revalida contra o servidor e grava.

    `recarregar()` devolve (itens, referências) RELIDOS agora. Se a cesta
    mudou desde o aviso, nada é gravado: sobe `CienciaDesatualizada` com
    o aviso novo. Repetir o clique devolve a ciência já gravada.
    """
    itens, referencias = recarregar()
    atual = preparar(pesquisa, itens, referencias,
                     pareceres=pareceres_do_jev(str(pesquisa.get("id") or ""),
                                                repositorio))
    if atual.assinatura != preparo.assinatura:
        raise CienciaDesatualizada(atual)
    pesquisa_id = str(pesquisa.get("id") or "")
    existente = localizar(pesquisa_id, atual.assinatura, ator, repositorio)
    if existente:
        return existente
    payload = {**atual.para_registro(),
               "registrada_em": datetime.now(timezone.utc).isoformat(
                   timespec="seconds")}
    gravado = repositorio.registrar_evento(
        pesquisa_id, TIPO_EVENTO, ator=ator,
        descricao=(f"Ciência registrada antes da emissão: "
                   f"{len(atual.alertas)} alerta(s) de preço e "
                   f"{len(atual.pendencias)} pendência(s); valores mantidos "
                   "na cesta como estavam"),
        payload=payload,
        idempotency_key=f"ciencia:{atual.assinatura}:{ator or ''}")
    if gravado:
        return gravado
    # chave já gasta (duplo clique em outra aba) ou falha de gravação
    existente = localizar(pesquisa_id, atual.assinatura, ator, repositorio)
    if existente:
        return existente
    raise ErroDeCiencia("não foi possível registrar a ciência agora; tente "
                        "de novo em instantes")


def exigir(pesquisa: dict, itens: list[dict],
           referencias: dict[str, list[dict]], *, ator: str | None,
           repositorio) -> dict | None:
    """
    A verificação do SERVIDOR antes de gerar qualquer arquivo.

    Sem alerta nem pendência: None (emite direto). Com: a ciência válida
    — ou `CienciaNecessaria`. Nunca recusa por causa do preço em si.
    """
    preparo = preparar(pesquisa, itens, referencias,
                       pareceres=pareceres_do_jev(
                           str(pesquisa.get("id") or ""), repositorio))
    if not preparo.requer_ciencia:
        return None
    evento = localizar(preparo.pesquisa_id, preparo.assinatura, ator,
                       repositorio)
    if evento is None:
        raise CienciaNecessaria(preparo)
    return evento


def para_documento(evento: dict | None, nome_do_ator: str = "") -> dict | None:
    """O que o relatório imprime sobre a ciência — neutro, fiel ao registro."""
    if not evento:
        return None
    payload = evento.get("payload") or {}
    alertas = payload.get("alertas") or []
    return {
        "registrada_em": str(payload.get("registrada_em")
                             or evento.get("criado_em") or ""),
        "por": nome_do_ator or str(evento.get("ator") or ""),
        "assinatura": str(payload.get("assinatura") or ""),
        "politica": str(payload.get("politica") or ""),
        "alertas": alertas,
        "itens": sorted({int(a.get("numero") or 0) for a in alertas}),
        "pendencias": payload.get("pendencias") or [],
    }

