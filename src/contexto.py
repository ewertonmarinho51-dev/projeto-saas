"""
Contexto institucional derivado da SESSÃO (Fase 2 da matriz de
compatibilidade — ver docs/matriz-compatibilidade.md).

Princípio central dos pacotes multi-município: tenant e secretaria de um
processo vêm do VÍNCULO do usuário autenticado — nunca de campo livre do
formulário. O servidor não escolhe timbrado nem unidade; o sistema
resolve a partir de quem ele é.

Feature flag `flag_secretarias` (config_app, default OFF):
  - DESLIGADA: o app se comporta exatamente como antes; o resolvedor de
    identidade roda em SHADOW MODE (apenas loga a decisão que tomaria).
  - LIGADA: identidade visual resolvida automaticamente na exportação e
    `processos.secretaria_id` gravado no autosave.
Rollback = desligar a flag (colunas novas ficam inertes).
"""

import logging

import streamlit as st

from . import db

FLAG_SECRETARIAS = "secretarias"

_log = logging.getLogger("govdocs.contexto")

# Campos que caracterizam identidade visual própria (imagem ou texto)
CAMPOS_VISUAIS = (
    "cabecalho", "rodape", "marca_dagua",
    "cabecalho_img", "rodape_img", "marca_img",
)


def ativo() -> bool:
    """Flag da Fase 2 ligada (resolução automática de contexto)."""
    return db.flag_ativa(FLAG_SECRETARIAS)


def _usuario_sessao() -> dict:
    return st.session_state.get("usuario") or {}


def contexto_institucional() -> dict:
    """
    Tenant + secretaria do usuário logado. Deriva EXCLUSIVAMENTE da
    sessão autenticada; dados digitados no formulário não participam.
    """
    usuario = _usuario_sessao()
    secretaria_id = usuario.get("secretaria_id")
    return {
        "tenant_id": db.tenant_atual(),
        "usuario_id": usuario.get("id"),
        "secretaria_id": secretaria_id,
        "origem": "vinculo" if secretaria_id else "tenant_padrao",
    }


def secretaria_para_processo() -> str | None:
    """`secretaria_id` a gravar no processo — apenas com a flag ligada."""
    if not ativo():
        return None
    return contexto_institucional().get("secretaria_id")


# ---------------------------------------------------------------------------
# Resolvedor hierárquico de identidade visual.
# Precedência da Fase 2: secretaria (vínculo) > município (padrão).
# O nível "documento > secretaria" (override por tipo documental) entra
# na Fase 3, com os templates versionados.
# ---------------------------------------------------------------------------
def tem_identidade_propria(registro: dict | None) -> bool:
    return any((registro or {}).get(campo) for campo in CAMPOS_VISUAIS)


def resolver_identidade(
    secretarias: list[dict], secretaria_id: str | None
) -> tuple[dict | None, str]:
    """
    (identidade, origem) para a lista de secretarias do tenant:
      - 'secretaria': o vínculo aponta uma secretaria com identidade própria;
      - 'municipio' : herda a identidade padrão do município (padrao=true);
      - 'nenhuma'   : não há identidade cadastrada (documentos sem timbrado).
    Função pura (sem banco) para permitir teste direto da precedência.
    """
    da_secretaria = next(
        (s for s in secretarias if s.get("id") == secretaria_id), None
    )
    if tem_identidade_propria(da_secretaria):
        return da_secretaria, "secretaria"
    padrao = next((s for s in secretarias if s.get("padrao")), None)
    if tem_identidade_propria(padrao):
        return padrao, "municipio"
    return None, "nenhuma"


def identidade_para_exportacao() -> tuple[dict | None, str] | None:
    """
    Flag LIGADA: (identidade resolvida, origem) — aplicada sem escolha
    manual. Flag DESLIGADA: None (chamador mantém o comportamento
    antigo), mas a decisão que seria tomada é registrada em log
    (shadow mode), permitindo validar a resolução antes do corte.
    """
    if not db.disponivel():
        return None
    try:
        secretarias = db.listar_secretarias()
    except db.ErroBanco:
        # Migração 0007 ainda não aplicada (ou banco fora): sem resolução.
        return None
    contexto = contexto_institucional()
    identidade, origem = resolver_identidade(
        secretarias, contexto.get("secretaria_id")
    )
    if not ativo():
        _log.info(
            "shadow: identidade que seria aplicada=%r origem=%s secretaria=%s",
            (identidade or {}).get("nome"), origem, contexto.get("secretaria_id"),
        )
        return None
    return identidade, origem
