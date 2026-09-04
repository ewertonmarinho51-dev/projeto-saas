"""Contratos estáticos de segurança do GovBot.

Estes testes não importam Streamlit nem executam JavaScript. Eles inspecionam
os artefatos como texto/AST para continuar úteis no modo demo e no CI
hermético.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]
CORE = RAIZ / "src" / "govbot.py"
COMPONENTE = RAIZ / "src" / "ui" / "govbot_component.py"
DOCUMENTACAO = RAIZ / "docs" / "govbot.md"
DB = RAIZ / "src" / "db.py"

ACOES_ESPERADAS = {
    "explain_current",
    "suggest_field",
    "replace_form_field",
    "suggest_section_patch",
    "apply_section_patch",
    "explain_finding",
    "fix_finding",
    "undo_last_change",
    "show_missing_information",
    "compare_with_previous_document",
}


def _fonte(caminho: Path) -> str:
    assert caminho.is_file(), f"artefato obrigatório ausente: {caminho}"
    return caminho.read_text(encoding="utf-8")


def _arvore(caminho: Path) -> ast.Module:
    return ast.parse(_fonte(caminho), filename=str(caminho))


def _atribuicao_literal(arvore: ast.Module, nome: str):
    for no in arvore.body:
        if isinstance(no, (ast.Assign, ast.AnnAssign)):
            alvos = no.targets if isinstance(no, ast.Assign) else [no.target]
            if any(isinstance(alvo, ast.Name) and alvo.id == nome
                   for alvo in alvos):
                return ast.literal_eval(no.value)
    raise AssertionError(f"contrato literal ausente: {nome}")


def _nome_importado(no: ast.AST) -> str:
    if isinstance(no, ast.Import):
        return ",".join(alias.name for alias in no.names)
    if isinstance(no, ast.ImportFrom):
        return no.module or ""
    return ""


def _nome_da_chamada(no: ast.Call) -> str:
    funcao = no.func
    if isinstance(funcao, ast.Name):
        return funcao.id
    if isinstance(funcao, ast.Attribute):
        return funcao.attr
    return ""


def test_contratos_sao_parseaveis_sem_importar_streamlit():
    """A coleta falha se houver erro sintático, sem importar o app real."""
    _arvore(CORE)
    _arvore(COMPONENTE)


def test_dominio_govbot_nao_depende_de_streamlit():
    importacoes = {
        _nome_importado(no).split(".")[0]
        for no in ast.walk(_arvore(CORE))
        if isinstance(no, (ast.Import, ast.ImportFrom))
    }
    assert "streamlit" not in importacoes
    assert "session_state" not in _fonte(CORE)


def test_allowlist_de_actions_e_literal_e_fechada():
    valor = _atribuicao_literal(_arvore(CORE), "ACOES_PERMITIDAS")
    acoes = set(valor.keys() if isinstance(valor, dict) else valor)
    assert acoes == ACOES_ESPERADAS


def test_flag_govbot_usa_mecanismo_central_e_default_off():
    arvore = _arvore(CORE)
    assert _atribuicao_literal(arvore, "FLAG_GOVBOT") == "govbot"

    fonte_core = _fonte(CORE)
    assert re.search(
        r"db\s*\.\s*flag_ativa\s*\(\s*FLAG_GOVBOT\s*\)", fonte_core
    ), "GovBot deve usar db.flag_ativa(FLAG_GOVBOT)"

    # O contrato OFF está no mecanismo central: valor ausente vira string
    # vazia, que não pertence à lista fechada de valores verdadeiros.
    fonte_db = _fonte(DB)
    trecho = fonte_db[fonte_db.index("def flag_ativa("):]
    trecho = trecho[:trecho.index("\n\n", 1)]
    assert 'obter_config(f"flag_{nome}")' in trecho
    assert re.search(r"\.lower\(\)\s+in\s+\(", trecho)
    assert "True" not in trecho


def test_frontend_nao_referencia_segredos_ou_configuracao_privilegiada():
    frontend = _fonte(COMPONENTE).casefold()
    proibidos = {
        "openai_api_key",
        "google_api_key",
        "supabase_secret_key",
        "service_role",
        "st.secrets",
        "process.env",
        "os.environ",
    }
    encontrados = sorted(fragmento for fragmento in proibidos
                         if fragmento in frontend)
    assert encontrados == [], encontrados


def test_frontend_nao_possui_sinks_html_ou_execucao_dinamica():
    fonte = _fonte(COMPONENTE)
    normalizada = fonte.casefold()
    proibidos = {
        "innerhtml",
        "outerhtml",
        "insertadjacenthtml",
        "document.write",
        "unsafe_allow_html=true",
        "unsafe_allow_html = true",
    }
    encontrados = sorted(fragmento for fragmento in proibidos
                         if fragmento in normalizada)
    assert encontrados == [], encontrados

    chamadas = {
        _nome_da_chamada(no)
        for no in ast.walk(_arvore(COMPONENTE))
        if isinstance(no, ast.Call)
    }
    assert chamadas.isdisjoint({"eval", "exec", "setattr"})


def test_core_nao_executa_codigo_nem_escreve_chaves_dinamicas():
    arvore = _arvore(CORE)
    chamadas = {
        _nome_da_chamada(no)
        for no in ast.walk(arvore)
        if isinstance(no, ast.Call)
    }
    assert chamadas.isdisjoint({"eval", "exec", "setattr"})

    # O core devolve intenções tipadas. Escrita no estado pertence ao
    # executor explícito da aplicação, nunca ao conteúdo gerado pelo modelo.
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            continue
        alvos = no.targets if isinstance(no, ast.Assign) else [no.target]
        for alvo in alvos:
            if isinstance(alvo, ast.Subscript):
                base = ast.unparse(alvo.value)
                assert "session_state" not in base, (
                    f"escrita direta em estado encontrada na linha {no.lineno}"
                )


def test_documentacao_explicita_flag_sessao_e_bloqueio_rls():
    texto = _fonte(DOCUMENTACAO)
    termos = (
        "flag_govbot",
        "OFF",
        "Bloqueio de produção",
        "RLS",
        "JWT do usuário",
        "st.session_state",
        "perdidos ao encerrar a sessão",
    )
    ausentes = [termo for termo in termos if termo not in texto]
    assert ausentes == [], ausentes


def test_arquivos_de_contrato_nao_contem_literais_de_credencial():
    """Guarda simples; a varredura geral do projeto continua soberana."""
    texto = "\n".join((_fonte(CORE), _fonte(COMPONENTE)))
    padroes = (
        r"\bsk-[A-Za-z0-9_-]{20,}\b",
        r"\bsb_secret_[A-Za-z0-9_-]{12,}\b",
        r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.",
    )
    assert not any(re.search(padrao, texto) for padrao in padroes)
