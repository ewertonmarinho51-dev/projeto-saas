"""
ORIGEM e CANAL de uma referência de preço — dois campos, não um.

* **Origem** é o portal em que a compra aconteceu: Licitanet, Licitações-e,
  Portal de Compras Públicas, Compras.gov.br… É quem publicou o processo.
* **Canal** é por onde o Gov Conect LEU o preço: o índice do PNCP, os dados
  abertos do Compras.gov, um arquivo oficial baixado direto do portal.

Misturar os dois era o que fazia uma homologação da Licitanet aparecer como
"PNCP" — verdade sobre o canal, silêncio sobre a origem. A tela e o
relatório passam a dizer **Origem Licitanet · Coleta via PNCP**.

A atribuição da origem usa duas evidências que o próprio PNCP publica em
cada contratação:

1. `usuarioNome` — o sistema que enviou a contratação ao PNCP;
2. `linkSistemaOrigem` — o endereço do processo no sistema de origem.

Valem quando CORROBORAM: as duas apontam o mesmo portal, ou uma aponta e a
outra falta. Se apontam portais diferentes, ou nenhuma é reconhecida, a
origem é **Origem não identificada** — com o publicador e o link guardados
como evidência, nunca um palpite.

O REGISTRO abaixo também diz, para cada portal, como ele entra na pesquisa
hoje (`Situacao`). Canal direto só conta como ativo depois de uma consulta
real com preço por item e evidência recuperável — a mesma régua de
`fontes_externas`, que guarda as trilhas de licença das bases novas.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit


class Situacao(str, Enum):
    """Como o portal chega à pesquisa de preços HOJE."""

    VIA_PNCP_VERIFICADA = "via_pncp_verificada"
    DIRETA_VALIDADA = "direta_validada"
    EVIDENCIA_MANUAL = "evidencia_manual"
    AGUARDANDO_ACESSO = "aguardando_acesso"


ROTULO_SITUACAO = {
    Situacao.VIA_PNCP_VERIFICADA: "via PNCP verificada",
    Situacao.DIRETA_VALIDADA: "direta validada",
    Situacao.EVIDENCIA_MANUAL: "evidência manual",
    Situacao.AGUARDANDO_ACESSO: "aguardando acesso/dados",
}

# Canais de leitura (por ONDE o preço chegou)
CANAL_PNCP = "pncp"
CANAL_COMPRAS_GOV = "compras_gov"
CANAL_DIRETO = "direto"
CANAL_MANUAL = "manual"

ROTULO_CANAL = {
    CANAL_PNCP: "Coleta via PNCP",
    CANAL_COMPRAS_GOV: "Coleta via Compras.gov.br (dados abertos)",
    CANAL_DIRETO: "Coleta direta no portal de origem",
    CANAL_MANUAL: "Registro manual com evidência",
}

NAO_IDENTIFICADA = "nao_identificada"
ROTULO_NAO_IDENTIFICADA = "Origem não identificada"


@dataclass(frozen=True)
class Portal:
    id: str
    nome: str
    # trechos do `usuarioNome` (sem acento, maiúsculas) que identificam o
    # publicador; conferidos nas contratações reais do índice paraense
    publicadores: tuple[str, ...]
    # domínios do `linkSistemaOrigem` (o próprio ou um subdomínio)
    dominios: tuple[str, ...]
    situacao: Situacao
    # o que sustenta a situação, com data — medição, consulta real, prova
    evidencia: str
    # o que falta para o CANAL DIRETO (chave, termo, documento) — vazio
    # quando já é direto ou quando não há canal a buscar
    pendencia_direta: str = ""
    # id em `fontes_externas.REGISTRO`, quando a trilha de licença mora lá
    registro_externo: str = ""


_MEDICAO_188 = ("índice PNCP do Pará, pregão eletrônico publicado de 10 a "
                "30/09/2026, 37 contratações lidas (PR #188, 10/11/2026)")

REGISTRO: dict[str, Portal] = {p.id: p for p in (
    Portal("compras_gov", "Compras.gov.br",
           ("COMPRAS.GOV", "COMPRASNET", "SERPRO"),
           ("compras.gov.br", "comprasnet.gov.br", "serpro.gov.br"),
           Situacao.DIRETA_VALIDADA,
           "fonte padrão da pesquisa (dados abertos de preços praticados); "
           "em produção desde 2026"),
    Portal("licitanet", "Licitanet", ("LICITANET",), ("licitanet.com.br",),
           Situacao.VIA_PNCP_VERIFICADA, f"558 resultados no {_MEDICAO_188}",
           pendencia_direta="documentação oficial de leitura de resultados "
                            "por item e prova de ganho de cobertura sobre o "
                            "PNCP",
           registro_externo="licitanet"),
    Portal("licitacoes_e", "Licitações-e (Banco do Brasil)",
           ("LICITACOES-E", "LICITACOES E", "BANCO DO BRASIL"),
           ("licitacoes-e.com.br", "licitacoes-e2.bb.com.br", "bb.com.br"),
           Situacao.VIA_PNCP_VERIFICADA, f"161 resultados no {_MEDICAO_188}",
           pendencia_direta="documentação oficial de leitura e prova de "
                            "ganho de cobertura"),
    Portal("pcp", "Portal de Compras Públicas",
           ("ECUSTOMIZE", "PORTAL DE COMPRAS PUBLICAS"),
           ("portaldecompraspublicas.com.br",),
           Situacao.VIA_PNCP_VERIFICADA, f"113 resultados no {_MEDICAO_188}",
           pendencia_direta="PublicKey de parceiro (novas solicitações "
                            "suspensas na página do portal), termo de uso, "
                            "leiaute vigente e preço por item em resposta "
                            "real",
           registro_externo="pcp"),
    Portal("bll", "BLL Compras", ("BLL", "BOLSA DE LICITACOES"),
           ("bll.org.br", "bllcompras.com", "bllcompras.org.br"),
           Situacao.VIA_PNCP_VERIFICADA, f"61 resultados no {_MEDICAO_188}",
           pendencia_direta="API ou exportação oficial de resultados por "
                            "item, com termos verificados",
           registro_externo="bll"),
    Portal("bnc", "BNC — Bolsa Nacional de Compras",
           ("BOLSA NACIONAL DE COMPRAS", "BNC"),
           ("bnc.org.br", "bnccompras.com"),
           Situacao.VIA_PNCP_VERIFICADA, f"36 resultados no {_MEDICAO_188}",
           pendencia_direta="API ou exportação oficial de resultados por "
                            "item, com termos verificados",
           registro_externo="bnc"),
    Portal("compras_para", "Compras Pará",
           ("COMPRAS PARA", "COMPRASPARA", "SEPLAD"),
           ("compraspara.pa.gov.br", "sistemas.pa.gov.br"),
           Situacao.VIA_PNCP_VERIFICADA,
           f"5 resultados no {_MEDICAO_188}; atas do portal oficial como "
           "evidência manual",
           pendencia_direta="canal autorizado com dados por item (as atas "
                            "públicas servem de evidência manual)"),
    Portal("m2a", "M2A Tecnologia", ("M2A",), ("m2atecnologia.com.br",),
           Situacao.VIA_PNCP_VERIFICADA, f"3 resultados no {_MEDICAO_188}"),
    Portal("comprasbr", "Compras BR", ("COMPRAS BR", "COMPRASBR"),
           ("comprasbr.com.br",), Situacao.AGUARDANDO_ACESSO,
           "cadastrado; sem resultado com origem comprovada no índice "
           "medido — entra via PNCP quando aparecer",
           pendencia_direta="autorização, leitura documentada de resultados "
                            "por item e prova real",
           registro_externo="comprasbr"),
    Portal("bbmnet", "BBMNET", ("BBMNET", "BBM NET"), ("bbmnet.com.br",),
           Situacao.AGUARDANDO_ACESSO,
           "cadastrado; sem resultado com origem comprovada no índice "
           "medido — entra via PNCP quando aparecer",
           pendencia_direta="autorização pelo manual de integração e prova "
                            "real com preço por item",
           registro_externo="bbmnet"),
    Portal("licitar_digital", "Licitar Digital", ("LICITAR DIGITAL",),
           ("licitardigital.com.br",), Situacao.AGUARDANDO_ACESSO,
           "cadastrado; sem resultado com origem comprovada no índice "
           "medido — entra via PNCP quando aparecer",
           pendencia_direta="autorização, leitura documentada e prova real",
           registro_externo="licitar_digital"),
    Portal("curitiba", "Portal de Dados Abertos de Curitiba", (),
           ("dadosabertos.curitiba.pr.gov.br", "curitiba.pr.gov.br"),
           Situacao.AGUARDANDO_ACESSO,
           "primeiro canal direto de compras gerais — aguarda a validação "
           "da amostra real (Itens Processo × Dados Básicos)",
           pendencia_direta="conferir a amostra de 01/11/2026 contra o "
                            "dicionário oficial e o contrato vigente"),
    Portal("tcm_pa", "TCM-PA — Mural de Licitações", (),
           ("tcm.pa.gov.br",), Situacao.EVIDENCIA_MANUAL,
           "documentos municipais anexados na revisão; sem base estruturada "
           "com preço por item",
           pendencia_direta="base estruturada com preço por item",
           registro_externo="tcm_pa"),
    Portal("tce_rs", "TCE-RS — LicitaCon", (), ("tce.rs.gov.br",),
           Situacao.AGUARDANDO_ACESSO,
           "ETL existente (`etl_tce_rs`); leiaute de TP_RESULTADO_ITEM e "
           "licença de reúso por resolver",
           pendencia_direta="leiaute oficial de TP_RESULTADO_ITEM e licença",
           registro_externo="tce_rs"),
    Portal("tce_pr", "TCE-PR — Mural de Licitações", (), ("tce.pr.gov.br",),
           Situacao.AGUARDANDO_ACESSO,
           "dicionário a validar: granularidade, etapa do preço e vigência",
           pendencia_direta="dicionário atualizado com preço por item e "
                            "etapa"),
)}


def _norm(texto) -> str:
    """Sem acento, maiúsculas, pontuação vira espaço: "Licitações-e" e
    "LICITACOES E" são o mesmo trecho; casamento só por PALAVRA inteira."""
    base = unicodedata.normalize("NFKD", str(texto or "").upper())
    limpo = "".join(c if c.isalnum() else " " for c in base
                    if not unicodedata.combining(c))
    return " ".join(limpo.split())


def portal_do_publicador(usuario_nome) -> Portal | None:
    """`usuarioNome` do PNCP → portal, ou `None` se não reconhecido."""
    nome = _norm(usuario_nome)
    if not nome:
        return None
    # Por palavra inteira: "LICITANET LICITACOES ELETRONICAS" não é
    # "LICITACOES E". O trecho mais longo vence ("BOLSA NACIONAL DE
    # COMPRAS" antes de "BNC").
    candidatos = [(len(_norm(trecho)), p) for p in REGISTRO.values()
                  for trecho in p.publicadores
                  if _norm(trecho) and f" {_norm(trecho)} " in f" {nome} "]
    if not candidatos:
        return None
    return max(candidatos, key=lambda c: c[0])[1]


def _host(url) -> str:
    try:
        return (urlsplit(str(url or "").strip()).hostname or "").lower()
    except ValueError:
        return ""


def portal_do_link(url) -> Portal | None:
    """Domínio do `linkSistemaOrigem` → portal, ou `None`."""
    host = _host(url)
    if not host:
        return None
    for portal in REGISTRO.values():
        for dominio in portal.dominios:
            if host == dominio or host.endswith("." + dominio):
                return portal
    return None


@dataclass(frozen=True)
class Atribuicao:
    origem_id: str
    origem: str
    canal_id: str
    canal: str
    corroborada: bool       # publicador e link concordam (ou um só existe)
    publicador: str = ""    # o que o PNCP declarou, como evidência
    link_origem: str = ""

    @property
    def rotulo(self) -> str:
        """"Origem Licitanet · Coleta via PNCP"."""
        origem = (self.origem if self.origem_id == NAO_IDENTIFICADA
                  else f"Origem {self.origem}")
        return f"{origem} · {self.canal}"

    def para_registro(self) -> dict:
        return {"origem_id": self.origem_id, "origem": self.origem,
                "canal_id": self.canal_id, "canal": self.canal,
                "corroborada": self.corroborada,
                "publicador": self.publicador,
                "link_origem": self.link_origem}


def atribuir_pncp(usuario_nome, link_origem) -> Atribuicao:
    """Origem de uma contratação lida pelo PNCP, pelas duas evidências."""
    por_nome = portal_do_publicador(usuario_nome)
    por_link = portal_do_link(link_origem)
    publicador = " ".join(str(usuario_nome or "").split())[:200]
    link = str(link_origem or "").strip()[:500]
    if por_nome and por_link and por_nome.id != por_link.id:
        escolhido, corroborada = None, False
    else:
        escolhido = por_nome or por_link
        corroborada = escolhido is not None
    canal = ROTULO_CANAL[CANAL_PNCP]
    if escolhido is None:
        return Atribuicao(NAO_IDENTIFICADA, ROTULO_NAO_IDENTIFICADA,
                          CANAL_PNCP, canal, False, publicador, link)
    return Atribuicao(escolhido.id, escolhido.nome, CANAL_PNCP, canal,
                      corroborada, publicador, link)


def atribuir(fonte_id, bruto: dict | None) -> Atribuicao | None:
    """
    Origem e canal de uma referência (gravada ou em memória). `None` para
    fonte que não declara origem (a tela mostra só a fonte, como antes).
    """
    fonte_id = str(fonte_id or "")
    bruto = bruto or {}
    if fonte_id in ("compras_gov_precos", "compras_gov_itens"):
        portal = REGISTRO["compras_gov"]
        return Atribuicao(portal.id, portal.nome, CANAL_COMPRAS_GOV,
                          ROTULO_CANAL[CANAL_COMPRAS_GOV], True)
    if fonte_id == "pncp":
        indice = bruto.get("indice") or {}
        publicador = (bruto.get("usuarioNome") or indice.get("plataforma")
                      or ((bruto.get("contratacao") or {}).get("usuarioNome")))
        return atribuir_pncp(publicador, bruto.get("linkSistemaOrigem"))
    if fonte_id == "cotacao_direta":
        return Atribuicao("cotacao_direta", "Cotação direta com fornecedor",
                          CANAL_MANUAL, ROTULO_CANAL[CANAL_MANUAL], True)
    direta = bruto.get("origem_direta") or {}
    if direta.get("portal") in REGISTRO:
        portal = REGISTRO[direta["portal"]]
        return Atribuicao(portal.id, portal.nome, CANAL_DIRETO,
                          ROTULO_CANAL[CANAL_DIRETO], True,
                          link_origem=str(direta.get("url") or "")[:500])
    return None


def situacao_dos_portais() -> list[dict]:
    """Tabela para o PR, o runbook e a tela de fontes: um portal por linha."""
    return [{"id": p.id, "nome": p.nome, "situacao": p.situacao.value,
             "rotulo": ROTULO_SITUACAO[p.situacao], "evidencia": p.evidencia,
             "pendencia_direta": p.pendencia_direta}
            for p in REGISTRO.values()]
