"""
Vocabulário do cadastro institucional, sem tela.

Morava em `ui/instituicional.py`, que importa o Streamlit; a API
(apps/api) e o `instituicional_bridge` precisam dos mesmos nomes sem ele.
A tela continua exportando estes nomes (importa daqui) — um lugar só
para cada constante. O porquê de cada flag está documentado na tela.
"""

from __future__ import annotations

FLAG_MULTI_PREFEITURAS = "multi_prefeituras"

# Seções da aba Instituição: AUSENTE = LIGADA (ver `ui/instituicional`).
FLAG_ADMIN = "multi_tenant_admin"
FLAG_SERVIDORES = "servidores"
FLAG_PORTARIAS = "portarias"

# Os módulos que o painel oferece por prefeitura e por secretaria. A flag
# global de cada um continua sendo a palavra final.
MODULOS_OFERECIDOS = (
    ("price_research", "Pesquisa de Preços"),
    ("demand_consolidation", "Consolidação de Solicitações de Despesa"),
    ("legal_opinion_correction", "Correção por Parecer Jurídico"),
    ("canonical_facts", "Fatos Canônicos"),
    ("process_consistency", "Consistência do Processo"),
)

TIPOS_DE_PORTARIA = (
    ("EQUIPE_PLANEJAMENTO", "Equipe de Planejamento"),
    ("PREGOEIRO", "Pregoeiro"),
    ("AGENTE_CONTRATACAO", "Agente de Contratação"),
    ("FISCAL", "Fiscal"),
    ("GESTOR", "Gestor"),
    ("COMISSAO", "Comissão"),
    ("OUTRO", "Outro"),
)

# Campos institucionais da prefeitura (§8): (coluna, rótulo, exemplo). São
# exatamente as colunas que a 0035 abre ao admin por grant de coluna.
CAMPOS_DA_PREFEITURA = (
    ("nome_oficial", "Nome oficial", "Ex.: Município de Paragominas"),
    ("cnpj", "CNPJ", "00.000.000/0001-00"),
    ("sigla", "Sigla", "Ex.: PMP"),
    ("cidade", "Cidade", "Ex.: Paragominas"),
    ("endereco", "Endereço", "Rua, número, bairro"),
    ("telefone", "Telefone", "(00) 0000-0000"),
    ("email", "E-mail institucional", "contato@municipio.gov.br"),
    ("site", "Site", "https://..."),
)

# Situação DECLARADA de uma portaria. EXPIRADA e FUTURA não entram: são
# efeito da vigência, calculados por `portarias.situacao`.
SITUACOES_DECLARADAS = ("RASCUNHO", "ATIVA", "REVOGADA")


def secao_liberada(valor: str) -> bool:
    """
    Flag de SEÇÃO: ausente = liberada (o contrário das flags de
    funcionalidade). Só some quem alguém desligou de propósito — a mesma
    regra de `ui/instituicional._liberada`.
    """
    return (valor or "").strip().lower() not in ("0", "false", "off", "nao", "não", "desligado")
