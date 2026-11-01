"""
Elaboração automática sem tela: o que `ui/steps._gerar_com_progresso` faz,
para a API e o worker usarem sem o Streamlit.

O texto continua saindo de `llm.gerar_documento` (prompts, Base de
Conhecimento, família de modelo, cláusulas determinísticas, cache, tabela
oficial de itens), e edital e Ata continuam montados do catálogo, sem IA.
Daqui saem só as decisões que a tela tomava em volta dessa chamada:

* QUAL é o próximo documento, pela sequência persistida do processo. A
  aprovação de cada um é humana e vale a do editor nativo; sem cabeça
  nativa, a do GovDocs (`processos.aprovados`);
* o que o próximo documento herda: só o que já foi APROVADO, como em
  `state.cadeia_aprovada`.

Nada aqui aprova documento, grava revisão nativa ou decide autorização.
Abrir o documento no editor importa o texto gerado uma vez, e o resto é o
fluxo do `DocumentoService`.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from . import familias, llm, processos, resumo_processo, validacao
from .config import CHAVE_FLUXO_MAPA, DOCUMENTOS, adota_srp, sequencia_do_processo

FLAG_MAPA = "mapa_riscos"

# Ordem do progresso real, gravada no job. `feitos` é o índice do estágio.
ESTAGIOS = ("LENDO", "CONSULTANDO", "GERANDO", "REVISANDO", "FINALIZANDO")

PENDENTE = "pendente"
GERADO = "gerado"           # texto pronto, ainda não aberto no editor
EM_REVISAO = "em_revisao"
APROVADO = "aprovado"
EMITIDO = "emitido"
_CONCLUIDAS = {APROVADO, EMITIDO}

FORMULARIO = "formulario"
ELABORAR = "elaborar"
REVISAR = "revisar"
CONCLUIDO = "concluido"


class EscolhaDeFamilia(RuntimeError):
    """Mais de um modelo serve: a escolha é humana, e a geração não adivinha."""


@dataclass(frozen=True)
class SituacaoDoDocumento:
    tipo: str
    situacao: str
    revisao: int | None = None


@dataclass(frozen=True)
class Proximo:
    acao: str
    tipo: str | None = None


@dataclass(frozen=True)
class Elaborado:
    documentos: dict[str, str]
    bloqueios: int
    avisos: int


def com_fluxo(dados: Mapping | None, documentos: Mapping | None, mapa_ligado: bool) -> dict:
    """`dados` com a decisão do Mapa de Riscos, como `state.configurar_fluxo`.

    A flag só vale para processo sem documento nenhum: ela não insere o Mapa
    no histórico de quem já tem cadeia."""
    saida = dict(dados or {})
    if mapa_ligado and not documentos:
        saida[CHAVE_FLUXO_MAPA] = True
    return saida


def situacoes(processo: Mapping, cabecas: Mapping[str, Mapping]) -> list[SituacaoDoDocumento]:
    """Cada documento que este processo precisa ter, na ordem da sequência.

    `cabecas` são as linhas de `documentos_editor`, por tipo. Onde há cabeça
    nativa, é ela que manda: o texto legado foi só a origem da importação."""
    legados = processo.get("documentos") or {}
    aprovados = set(processo.get("aprovados") or [])
    saida = []
    for tipo in processos.documentos_do_processo(dict(processo)):
        cabeca = cabecas.get(tipo)
        if cabeca is not None:
            status = cabeca.get("status")
            situacao = status if status in _CONCLUIDAS else EM_REVISAO
            saida.append(SituacaoDoDocumento(tipo, situacao, cabeca.get("revision")))
        elif legados.get(tipo):
            saida.append(SituacaoDoDocumento(tipo, APROVADO if tipo in aprovados else GERADO))
        else:
            saida.append(SituacaoDoDocumento(tipo, PENDENTE))
    return saida


def proximo_passo(documentos: Iterable[SituacaoDoDocumento], faltantes: Iterable[str]) -> Proximo:
    """O primeiro documento não concluído decide: a sequência não pula etapa."""
    for documento in documentos:
        if documento.situacao in _CONCLUIDAS:
            continue
        if documento.situacao != PENDENTE:
            return Proximo(REVISAR, documento.tipo)
        return Proximo(FORMULARIO) if list(faltantes) else Proximo(ELABORAR, documento.tipo)
    return Proximo(CONCLUIDO)


def contexto_para(doc_key: str, processo: Mapping, aprovados: Mapping[str, str]) -> str | None:
    """A cadeia aprovada, como `state.contexto_para_documento`. `aprovados`
    são os textos de {tipo: texto} que o chamador leu com a sessão do usuário."""
    ordem = sequencia_do_processo(processo.get("dados"), processo.get("documentos"))
    anteriores = ordem[:ordem.index(doc_key)] if doc_key in ordem else ordem[:-1]
    cadeia = {d: aprovados[d] for d in anteriores if (aprovados.get(d) or "").strip()}
    if not cadeia:
        return None
    if resumo_processo.ativo():
        return resumo_processo.contexto_canonico(cadeia, doc_key)
    return "\n\n".join(f"=== {DOCUMENTOS[d]['titulo']} aprovado ===\n{texto}"
                       for d, texto in cadeia.items()) or None


def _bloco_da_familia(doc_key: str, dados: dict, processo_id: str) -> str:
    if doc_key == "mapa_riscos":
        return ""
    resolucao = familias.resolver_para_processo(doc_key, dados, processo_id)
    if resolucao is None:
        return ""
    if resolucao["situacao"] == "ambigua":
        raise EscolhaDeFamilia(doc_key)
    return familias.bloco_para_prompt(resolucao["payload"]) if resolucao["situacao"] == "unica" else ""


def elaborar(doc_key: str, dados: dict, contexto: str | None, processo_id: str,
             etapa: Callable[[str], None]) -> Elaborado:
    """Gera o candidato e a Ata que sai com o edital. Não grava nada: quem
    substitui é o chamador, depois de conferir que o processo não mudou."""
    etapa("CONSULTANDO")
    bloco = _bloco_da_familia(doc_key, dados, processo_id)
    candidatos = {doc_key: llm.gerar_documento(doc_key, copy.deepcopy(dados), contexto,
                                               instrucoes_extra=bloco,
                                               progresso=lambda _estagio: etapa("GERANDO"))}
    if doc_key == "edital" and adota_srp(dados):
        candidatos["arp"] = llm.gerar_documento("arp", copy.deepcopy(dados), contexto)
    etapa("REVISANDO")
    relatorio = validacao.validar_todos(candidatos, dados=dados)
    return Elaborado(candidatos, len(validacao.bloqueios(relatorio)), len(validacao.avisos(relatorio)))
