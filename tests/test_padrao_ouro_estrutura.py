"""
Fase 4 (DFD/ETP/TR) do padrão ouro — estrutura, fundamentação e
autossuficiência dos documentos.

Defeitos reproduzidos do bundle auditado: repactuação prevista em
aquisição de bens nos quatro documentos, TR remetendo à numeração
interna do ETP ("ETP, item 4.3" — 12 ocorrências), DFD decidindo
pregão/SRP antes do estudo.
"""

import json
from pathlib import Path

import pytest

from src import prompts, validacao

FIXTURE = Path(__file__).parent / "fixtures" / "caso_210_itens.json"


@pytest.fixture(scope="module")
def caso_bens():
    """Processo de BENS: materiais de expediente, 210 itens."""
    dados = json.loads(FIXTURE.read_text(encoding="utf-8"))
    dados["modelo_execucao"] = "Sistema de Registro de Preços (SRP)"
    return dados


# ---------------------------------------------------------------------------
# Repactuação × natureza do objeto
# ---------------------------------------------------------------------------
def test_natureza_bens_e_deduzida_do_processo(caso_bens):
    assert validacao._natureza_do_objeto(caso_bens) == "BENS"


def test_repactuacao_em_aquisicao_de_bens_bloqueia(caso_bens):
    texto = ("## 9. DO REAJUSTE\n\n9.1. Os preços serão repactuados "
             "anualmente conforme índice oficial.\n")
    achados = validacao.validar_documento("tr", texto, None, caso_bens)
    bloqueios = [a["mensagem"] for a in validacao.bloqueios(achados)]
    assert any("instituto incabível" in m and "BENS" in m
               for m in bloqueios), bloqueios


def test_repactuacao_em_servico_com_mao_de_obra_nao_bloqueia():
    dados = {"objeto": "Contratação de serviços de limpeza",
             "modelo_execucao": "Serviço de execução continuada",
             "requisitos": "com dedicação exclusiva de mão de obra"}
    texto = ("9.1. A repactuação observará a data-base da categoria, "
             "havendo dedicação exclusiva de mão de obra.\n")
    achados = validacao.validar_documento("tr", texto, None, dados)
    assert not [a for a in achados if "instituto" in a["mensagem"]]


def test_sem_natureza_definida_repactuacao_e_apenas_aviso():
    """'Não sei' não vira 'BENS': o revisor decide, a emissão segue."""
    texto = "9.1. Os preços poderão ser repactuados.\n"
    achados = validacao.validar_documento("tr", texto, None, {"objeto": ""})
    instituto = [a for a in achados if "instituto" in a["mensagem"]]
    assert instituto and all(a["gravidade"] == "aviso" for a in instituto)


# ---------------------------------------------------------------------------
# Autossuficiência: sem remissão à numeração de outro documento
# ---------------------------------------------------------------------------
def test_remissao_a_item_de_outro_documento_e_sinalizada():
    texto = ("4.1. Os requisitos técnicos observam o disposto no ETP, "
             "item 4.3, e no ETP, item 6.7.\n")
    achados = validacao.validar_documento("tr", texto)
    avisos = [a["mensagem"] for a in validacao.avisos(achados)]
    assert any("remissão à numeração interna" in m and "2 ocorrência" in m
               for m in avisos), avisos


def test_citar_o_documento_sem_o_numero_do_item_e_legitimo():
    texto = ("4.1. Os requisitos decorrem do Estudo Técnico Preliminar "
             "aprovado nos autos.\n")
    achados = validacao.validar_documento("tr", texto)
    assert not [a for a in achados if "remissão" in a["mensagem"]]


# ---------------------------------------------------------------------------
# Instruções de prompt (contrato com o gerador)
# ---------------------------------------------------------------------------
def test_prompt_do_dfd_proibe_decidir_modalidade_e_srp():
    instrucoes = prompts._ABERTURAS["dfd"]
    assert "PROIBIDO ao DFD decidir modalidade" in instrucoes
    assert "Sistema de Registro de Preços" in instrucoes
    # e separa as quatro peças do raciocínio inaugural
    for peca in ("JUSTIFICATIVA", "NECESSIDADE", "OPORTUNIDADE",
                 "SOLUÇÃO PRELIMINARMENTE PROPOSTA"):
        assert peca in instrucoes


def test_prompt_do_dfd_proibe_planilha_na_identificacao():
    """Defeito real: a linha do item 572704 caiu na cláusula 1.5."""
    assert "PROIBIDO inserir nelas itens" in prompts._ABERTURAS["dfd"]


def test_prompt_do_tr_veda_exigencias_inventadas_e_repactuacao():
    instrucoes = prompts._ABERTURAS["tr"]
    for termo in ("certificação", "ensaio", "amostra", "assistência técnica"):
        assert termo in instrucoes
    assert "PROIBIDO prever repactuação" in instrucoes
    assert "RASTREABILIDADE" in instrucoes


def test_regra_de_evidencia_cobre_as_afirmacoes_sem_lastro():
    base = prompts.SYSTEM_PROMPT_BASE
    for termo in ("histórico ou média de consumo", "sazonalidade",
                  "emergência", "armazenamento", "PCA", "LOA",
                  "pesquisa de preços"):
        assert termo in base, termo


def test_regra_contra_enchimento_e_contra_remissao_interna():
    base = prompts.SYSTEM_PROMPT_BASE
    assert "NADA DE ENCHIMENTO" in base
    assert "AUTOSSUFICIENTE" in base
    assert "conforme ETP, item 4.3" in base


def test_regra_de_designacao_de_agentes():
    base = prompts.SYSTEM_PROMPT_BASE
    assert "QUEM ASSINA E QUEM É DESIGNADO NÃO É DECISÃO DE MÁQUINA" in base
    # designar unidade continua permitido
    assert "Designar uma UNIDADE" in base


def test_forma_verbal_de_repactuacao_tambem_e_detectada():
    """
    'os preços serão repactuados' escapava do padrão antigo, que exigia
    'repactuaç/repactuac' — a regra pegava o substantivo e perdia o verbo.
    """
    for forma in ("repactuação", "repactuados", "repactuar", "repactuado"):
        achados = validacao.validar_documento(
            "tr", f"9.1. Cláusula com {forma} de preços.\n")
        assert [a for a in achados if "instituto" in a["mensagem"]], forma
