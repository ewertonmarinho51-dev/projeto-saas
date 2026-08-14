"""
Fase 4 (Edital/ARP) do padrão ouro — instrumentos determinísticos.

No bundle auditado o edital foi redigido por prosa livre e saiu com o
pregão fundado no art. 109 (é o art. 28, I, c/c o art. 29), garantia sem
base legal, tabela de itens parcial (53 de 210) e a Ata de Registro de
Preços inexistente como instrumento — apenas 10 menções dentro do
edital. Agora os dois nascem do catálogo versionado de cláusulas.
"""

import json
from pathlib import Path

import pytest

from src import planilha, state, templates_gov, validacao
from src.config import DOCUMENTOS, DOCUMENTOS_EXPORTAVEIS

FIXTURE = Path(__file__).parent / "fixtures" / "caso_210_itens.json"


@pytest.fixture(scope="module")
def dados():
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    d["orgao"] = "Prefeitura Municipal de Paragominas"
    d["objeto"] = "aquisição de materiais de expediente"
    d["modelo_execucao"] = "Sistema de Registro de Preços (SRP)"
    return d


def _montar(doc_key, dados):
    """Montagem sem banco: vale a base nacional embutida."""
    return templates_gov.montar_oficial(doc_key, dados, clausulas={})


# ---------------------------------------------------------------------------
# ARP é instrumento separado
# ---------------------------------------------------------------------------
def test_arp_e_documento_proprio_e_exportavel():
    assert "arp" in DOCUMENTOS
    assert DOCUMENTOS["arp"]["sigla"] == "ARP"
    assert "arp" in DOCUMENTOS_EXPORTAVEIS
    # não é etapa do wizard: sai junto do edital
    assert DOCUMENTOS["arp"]["etapa"] == DOCUMENTOS["edital"]["etapa"]


def test_srp_e_reconhecido_apenas_pelo_modelo_de_execucao():
    assert state.usa_srp({"modelo_execucao": "Sistema de Registro de Preços"})
    assert not state.usa_srp({"modelo_execucao": "Entrega única"})
    # não se deduz SRP do objeto nem da quantidade
    assert not state.usa_srp({"objeto": "registro de materiais",
                              "modelo_execucao": "Entrega única"})


# ---------------------------------------------------------------------------
# Conteúdo mínimo do art. 25 e fundamentação correta
# ---------------------------------------------------------------------------
def test_edital_cobre_as_materias_obrigatorias(dados):
    texto = _montar("edital", dados)["texto"]
    for materia in ("DO PREÂMBULO", "DO OBJETO",
                    "DAS CONDIÇÕES DE PARTICIPAÇÃO",
                    "DA APRESENTAÇÃO DA PROPOSTA",
                    "DO JULGAMENTO", "DA HABILITAÇÃO",
                    "DA IMPUGNAÇÃO", "DOS RECURSOS",
                    "DAS SANÇÕES ADMINISTRATIVAS", "DA GARANTIA",
                    "DO RECEBIMENTO E DO PAGAMENTO",
                    "DAS DISPOSIÇÕES FINAIS"):
        assert materia in texto, materia


def test_edital_usa_os_dispositivos_corretos(dados):
    texto = _montar("edital", dados)["texto"]
    assert "art. 14" in texto           # vedações de participação
    assert "art. 33" in texto           # critério de julgamento
    assert "arts. 62 a 70" in texto     # habilitação
    assert "art. 164" in texto          # impugnação
    assert "arts. 165 a 168" in texto   # recursos
    assert "art. 155" in texto and "art. 156" in texto   # sanções
    assert "art. 140" in texto          # recebimento
    assert "arts. 141 a 146" in texto   # pagamento


def test_edital_nao_funda_pregao_no_art_109(dados):
    """Defeito literal do edital auditado."""
    texto = _montar("edital", dados)["texto"]
    achados = validacao.validar_documento("edital", texto, None, dados)
    assert not [a for a in achados if "art. 109" in a["mensagem"]]
    assert "109" not in texto


def test_edital_nao_menciona_suspensao_temporaria(dados):
    """Sanção da lei revogada; a vigente é impedimento/inidoneidade."""
    texto = _montar("edital", dados)["texto"].lower()
    assert "suspensão temporária" not in texto
    assert "impedimento de licitar" in texto
    assert "declaração de inidoneidade" in texto


def test_arp_funda_vigencia_no_art_84_e_adesao_no_86(dados):
    texto = _montar("arp", dados)["texto"]
    assert "art. 84" in texto
    assert "art. 86" in texto
    # e não repete o erro de fundar a vigência da ata no art. 82
    achados = validacao.validar_documento("arp", texto, None, dados)
    assert not [a for a in achados if "art. 82" in a["mensagem"]]


def test_arp_nao_preve_repactuacao_para_bens(dados):
    texto = _montar("arp", dados)["texto"]
    assert "repactua" not in texto.lower()
    assert "art. 92, § 3º" in texto or "art. 92, §3º" in texto
    achados = validacao.validar_documento("arp", texto, None, dados)
    assert not [a for a in achados if "instituto" in a["mensagem"]]


# ---------------------------------------------------------------------------
# Dado ausente fica VISÍVEL e bloqueia — nunca é preenchido por plausibilidade
# ---------------------------------------------------------------------------
def test_decisoes_nao_sao_preenchidas_automaticamente(dados):
    """Modalidade, critério, disputa, regime e garantia são DECISÕES."""
    texto = _montar("edital", dados)["texto"]
    for rotulo in ("modalidade da licitação", "critério de julgamento",
                   "modo de disputa", "regime de execução",
                   "número do processo administrativo",
                   "data da sessão pública", "plataforma eletrônica",
                   "garantia contratual"):
        assert f"[PREENCHER: {rotulo}" in texto or rotulo in texto, rotulo
    assert "[PREENCHER" in texto


def test_arp_nao_inventa_fornecedor_nem_cnpj(dados):
    """
    A ARP auditada trazia fornecedor 'licitantes' e CNPJ inválido. Agora
    ambos são pendência explícita até o processo trazer o dado real.
    """
    texto = _montar("arp", dados)["texto"]
    assert "[PREENCHER: razão social do fornecedor beneficiário]" in texto
    assert "[PREENCHER: CNPJ do fornecedor beneficiário]" in texto
    # nenhum CNPJ sintático no texto
    assert not validacao._RE_CNPJ.search(texto)


def test_instrumento_com_pendencia_bloqueia_a_emissao(dados):
    texto = _montar("edital", dados)["texto"]
    bloqueios = validacao.bloqueios(
        validacao.validar_documento("edital", texto, None, dados))
    assert any("campo pendente" in a["mensagem"] for a in bloqueios)


def test_dados_do_processo_entram_sem_marcador(dados):
    texto = _montar("edital", dados)["texto"]
    assert "Prefeitura Municipal de Paragominas" in texto
    assert "aquisição de materiais de expediente" in texto


# ---------------------------------------------------------------------------
# Tabela oficial nos dois instrumentos
# ---------------------------------------------------------------------------
def test_edital_e_arp_recebem_a_tabela_integral(dados):
    for doc_key in ("edital", "arp"):
        texto = planilha.injetar_tabela(
            _montar(doc_key, dados)["texto"], dados["itens"])
        assert planilha.conferir_tabela(texto, dados["itens"]) == [], doc_key
        assert len(planilha.linhas_de_itens_do_texto(texto)) == 210


# ---------------------------------------------------------------------------
# Cláusula municipal publicada prevalece sobre a base nacional
# ---------------------------------------------------------------------------
def test_clausula_publicada_do_municipio_sobrepoe_a_base(dados):
    municipal = {
        "arp.foro": {
            "versao": 3, "hash": "abc",
            "payload": {
                "titulo": "DO FORO",
                "blocos": ["Fica eleito o foro da Comarca de Paragominas/PA."],
                "comportamento": "FIXED_LOCKED",
                "parametros_permitidos": [], "parametros_obrigatorios": [],
            },
        }
    }
    resultado = templates_gov.montar_oficial("arp", dados, municipal)
    assert "Comarca de Paragominas/PA" in resultado["texto"]
    assert "[PREENCHER: comarca do foro]" not in resultado["texto"]
    assert {"chave": "arp.foro", "versao": 3, "hash": "abc"} in \
        resultado["clausulas_usadas"]
