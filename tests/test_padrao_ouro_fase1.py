"""
Fase 1 do padrão ouro — a aprovação vale para o ARTEFATO FINAL e para o
AUDITOR que o aprovou.

Defeito de produção reproduzido no diagnóstico
(docs/diagnostico-padrao-ouro.md): um bundle aprovado em 08/08 por
regras antigas seguia sendo reproduzido como APPROVED — e exportado —
depois de os validadores mudarem, porque (a) a chave de idempotência do
ciclo não carregava a versão das regras e (b) o caminho "aprovado" da
tela final não revalidava o conteúdo exportado.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from src import ciclo, db, validacao
from src.ui import revisao

APP = str(Path(__file__).resolve().parent.parent / "app.py")


# ---------------------------------------------------------------------------
# identidade do auditor
# ---------------------------------------------------------------------------
def test_versao_do_auditor_e_sha256_estavel():
    v1 = validacao.versao_do_auditor()
    v2 = validacao.versao_do_auditor()
    assert v1 == v2
    assert len(v1) == 64 and all(c in "0123456789abcdef" for c in v1)


def test_chave_de_idempotencia_amarra_bundle_e_auditor(monkeypatch):
    chaves = []
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "flag_ativa", lambda n: False)
    monkeypatch.setattr(db, "tenant_atual", lambda: "t1")
    monkeypatch.setattr(
        db, "obter_revisao_por_chave",
        lambda chave: chaves.append(chave) or None)
    monkeypatch.setattr(
        db, "criar_revisao",
        lambda *a, **k: {"id": "rev-1", "tenant_id": "t1"})
    monkeypatch.setattr(db, "atualizar_revisao", lambda *a, **k: None)

    docs = {"memo": "## 1. OBJETO\n\nAquisição de canetas.\n"}
    ciclo.executar_com_persistencia(docs, {}, "proc-1")
    assert len(chaves) == 1
    sufixo = f"-r{validacao.versao_do_auditor()[:12]}"
    assert chaves[0].startswith("ciclo-proc-1-")
    assert chaves[0].endswith(sufixo), chaves[0]


# ---------------------------------------------------------------------------
# revalidação do pacote final no caminho "aprovado"
# ---------------------------------------------------------------------------
def _app_na_tela_final(docs):
    import os

    os.environ["GOVDOCS_MODO_ABERTO"] = "1"
    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["etapa"] = 5
    at.session_state["dados"] = {"orgao": "Prefeitura", "objeto": "canetas"}
    at.session_state["documentos"] = dict(docs)
    at.session_state["aprovados"] = {"dfd", "etp", "tr", "edital"}
    return at


def test_aprovacao_persistida_nao_libera_bundle_que_o_auditor_atual_bloqueia(
        monkeypatch):
    """APPROVED antigo + bloqueio atual ⇒ emissão retida, minuta marcada."""
    docs_com_defeito = {
        "dfd": "## 1. OBJETO\n\nSetor: [PREENCHER: setor requisitante].\n"}
    resultado = {
        "status": "APPROVED", "documentos": dict(docs_com_defeito),
        "versao": 1, "ciclos": 0,
        "relatorios": [{"summary": "aprovado por regras antigas",
                        "findings": []}],
        "planos": [], "diffs": [], "eventos": [],
        "campos_requeridos": [], "decisoes_requeridas": [],
    }
    monkeypatch.setattr(
        db, "flag_ativa",
        lambda n: n in (revisao.FLAG_TELA, "correcao_automatica"))
    monkeypatch.setattr(ciclo, "executar_com_persistencia",
                        lambda *a, **k: resultado)
    at = _app_na_tela_final(docs_com_defeito)
    at.run()
    assert not at.exception
    erros = " ".join(e.value for e in at.error)
    assert "revalidação" in erros or "Emissão retida" in erros
    rotulos = [b.label or "" for b in at.get("download_button")]
    # nenhum download oficial…
    assert not any("Baixar todos" in r for r in rotulos), rotulos
    # …mas a MINUTA marcada continua disponível
    assert any("MINUTA" in r for r in rotulos), rotulos


def test_aprovacao_valida_continua_liberando(monkeypatch):
    docs_limpos = {"dfd": "## 1. OBJETO\n\nAquisição de canetas.\n"}
    resultado = {
        "status": "APPROVED", "documentos": dict(docs_limpos),
        "versao": 1, "ciclos": 0,
        "relatorios": [{"summary": "ok", "findings": []}],
        "planos": [], "diffs": [], "eventos": [],
        "campos_requeridos": [], "decisoes_requeridas": [],
    }
    monkeypatch.setattr(
        db, "flag_ativa",
        lambda n: n in (revisao.FLAG_TELA, "correcao_automatica"))
    monkeypatch.setattr(ciclo, "executar_com_persistencia",
                        lambda *a, **k: resultado)
    at = _app_na_tela_final(docs_limpos)
    at.run()
    assert not at.exception
    rotulos = [b.label or "" for b in at.get("download_button")]
    assert any("Baixar todos em PDF" in r for r in rotulos), rotulos
    sucessos = " ".join(s.value for s in at.success)
    assert "Processo concluído" in sucessos


# ---------------------------------------------------------------------------
# minuta não aprovada
# ---------------------------------------------------------------------------
def test_docs_como_minuta_marcam_todos_os_documentos():
    docs = {"dfd": "conteúdo A", "etp": "conteúdo B"}
    minuta = revisao.docs_como_minuta(docs)
    assert all(v.startswith(revisao.AVISO_MINUTA) for v in minuta.values())
    assert "NÃO APROVADA PARA EMISSÃO" in minuta["dfd"]
    assert docs["dfd"] == "conteúdo A"  # original intocado


# ---------------------------------------------------------------------------
# auditor semântico sem a tabela determinística
# ---------------------------------------------------------------------------
def test_texto_para_auditor_omite_tabela_grande_e_preserva_prosa():
    tabela = "\n".join(f"| {i} | item {i} | UN | 1 | R$ 1,00 |"
                       for i in range(200))
    texto = ("## 1. OBJETO\n\nProsa inicial.\n\n" + tabela +
             "\n\n## 2. CONCLUSÃO\n\nProsa final importantíssima.")
    resumido = ciclo._texto_para_auditor(texto)
    assert "Prosa inicial." in resumido
    assert "Prosa final importantíssima." in resumido
    assert "| 150 |" not in resumido
    assert "TABELA DETERMINÍSTICA DE 200 LINHAS OMITIDA" in resumido
    # tabela pequena (até 8 linhas) permanece — pode conter prosa relevante
    pequena = "\n".join(f"| a{i} | b |" for i in range(4))
    assert ciclo._texto_para_auditor(pequena) == pequena
