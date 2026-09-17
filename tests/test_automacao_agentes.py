"""
A camada de automação de agentes, provada onde ela PODE ser provada.

Os cenários que o pedido descreve — "analise o projeto e recomende
automações", "precisamos de Playwright?" — são comportamento de modelo,
e `pytest` não decide isso. O que `pytest` decide, e que importa mais:

  1. a configuração é válida e aponta para arquivos que existem;
  2. o gancho de segredo recusa o que promete recusar e deixa passar o
     que promete deixar — EXECUTADO, não inferido do código;
  3. o gancho de provas relacionadas nunca reprova a edição;
  4. nada em `.claude/` carrega segredo, medido pela mesma varredura que
     guarda o repositório;
  5. **a fronteira**: nenhum módulo de `src/` conhece esta camada.

A quinta é a razão de este arquivo existir. O Cartographer e o Setup
Advisor servem a quem DESENVOLVE; o Streamlit que gera documento de
licitação não pode passar a depender deles. Fronteira que mora só em
comentário é fronteira que a primeira pressa atravessa.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
CLAUDE = RAIZ / ".claude"
GANCHOS = CLAUDE / "hooks"

sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(GANCHOS))


def _rodar_gancho(script: str, entrada: dict) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(GANCHOS / script)],
        input=json.dumps(entrada), capture_output=True, text=True,
        timeout=120, cwd=RAIZ,
    )


# ---------------------------------------------------------------------------
# 1) A configuração existe e aponta para o que existe
# ---------------------------------------------------------------------------
def test_o_settings_e_json_valido_e_aponta_para_ganchos_reais():
    config = json.loads((CLAUDE / "settings.json").read_text())
    ganchos = config["hooks"]
    assert set(ganchos) == {"PreToolUse", "PostToolUse"}

    citados = re.findall(r"\.claude/hooks/([\w.]+\.py)", json.dumps(ganchos))
    assert citados, "nenhum gancho citado no settings.json"
    for nome in citados:
        assert (GANCHOS / nome).exists(), f"gancho citado e ausente: {nome}"


def test_o_gancho_de_segredo_cobre_as_ferramentas_de_escrita():
    """
    Cobrir só `Write` deixaria `Edit` livre — e é por `Edit` que um
    arquivo existente é alterado, que é o caso do `secrets.toml`.
    """
    config = json.loads((CLAUDE / "settings.json").read_text())
    pre = config["hooks"]["PreToolUse"][0]["matcher"]
    for ferramenta in ("Write", "Edit", "MultiEdit"):
        assert ferramenta in pre, f"{ferramenta} fora do gancho de segredo"


# ---------------------------------------------------------------------------
# 2) O gancho de segredo, EXECUTADO
# ---------------------------------------------------------------------------
BLOQUEADOS = (
    ".streamlit/secrets.toml",
    # A cópia "só para não perder" é o mesmo segredo com outro nome, e é
    # o que aparece na prática antes de alguém mexer no arquivo.
    ".streamlit/secrets.toml.bak",
    "contas-auth.json",
    "contas-auth-producao.json",
    ".env",
    ".env.local",
    "credentials.json",
    "chave.pem",
)

LIBERADOS = (
    "src/db.py",
    "tests/test_db.py",
    ".streamlit/config.toml",
    "supabase/migrations/0024_service_role_sem_truncate.sql",
    # Os dois que SÓ passam por causa da lista de exceções: `.env.example`
    # casa com `.env.*` e `secrets.toml.example` casa com
    # `.streamlit/secrets.toml*`. Sem a exceção, os dois são bloqueados —
    # e a primeira versão desta prova passava sem ela, porque os padrões
    # de então nem chegavam a casá-los. Prova que passa pelo motivo
    # errado ocupa a vaga do que deveria estar medindo.
    ".env.example",
    ".streamlit/secrets.toml.example",
)


@pytest.mark.parametrize("caminho", BLOQUEADOS)
def test_o_gancho_recusa_escrita_em_segredo(caminho):
    saida = _rodar_gancho(
        "bloquear_segredo.py",
        {"tool_name": "Write", "tool_input": {"file_path": caminho}})
    assert saida.returncode == 2, f"passou livre: {caminho}"
    assert caminho in saida.stderr


@pytest.mark.parametrize("caminho", LIBERADOS)
def test_o_gancho_deixa_passar_o_trabalho_normal(caminho):
    """
    O lado que decide se o gancho sobrevive. Um bloqueio que atrapalha o
    trabalho de todo dia é arrancado na semana seguinte — e aí a
    proteção deixa de existir de verdade.

    `secrets.toml.example` está aqui de propósito: é o MODELO
    versionado, sem valor dentro, e existe para ser editado.
    """
    saida = _rodar_gancho(
        "bloquear_segredo.py",
        {"tool_name": "Edit", "tool_input": {"file_path": caminho}})
    assert saida.returncode == 0, f"bloqueado indevidamente: {caminho}"


def test_o_gancho_de_segredo_falha_aberto():
    """
    Entrada corrompida NÃO pode travar a edição. Um gancho de proteção
    que quebra o desenvolvimento inteiro quando ele próprio falha é
    removido — e a contenção real dos segredos é o `.gitignore`, a
    varredura e o fato de nenhum deles estar versionado.
    """
    saida = subprocess.run(  # noqa: S603
        [sys.executable, str(GANCHOS / "bloquear_segredo.py")],
        input="isto não é json", capture_output=True, text=True, timeout=60)
    assert saida.returncode == 0


def test_o_gancho_de_segredo_ignora_leitura():
    """Ele é PreToolUse de ESCRITA. Bash e Read não passam por ele."""
    saida = _rodar_gancho(
        "bloquear_segredo.py",
        {"tool_name": "Read", "tool_input": {"file_path": ".env"}})
    assert saida.returncode == 0


# ---------------------------------------------------------------------------
# 3) O gancho de provas relacionadas
# ---------------------------------------------------------------------------
def test_o_mapeamento_de_provas_e_burro_de_proposito():
    """
    Ou existe o arquivo com o nome certo, ou o gancho se cala. Rodar o
    teste PARECIDO e dizer "verde" é pior que não rodar nada.
    """
    import provas_relacionadas as pr

    # Módulo de pacote: o nome específico primeiro.
    achados = pr.candidatos(str(RAIZ / "src" / "demanda" / "extracao.py"))
    assert [c.name for c in achados] == ["test_demanda_extracao.py"]

    # Módulo de raiz.
    assert [c.name for c in pr.candidatos(str(RAIZ / "src" / "auth.py"))] \
        == ["test_auth.py"]

    # `src/db.py` existe e `tests/test_db.py` NÃO. O gancho se cala em
    # vez de rodar o teste mais parecido.
    assert (RAIZ / "src" / "db.py").exists()
    assert pr.candidatos(str(RAIZ / "src" / "db.py")) == []

    # Fora de `src/`, e inexistente.
    assert pr.candidatos(str(RAIZ / "app.py")) == []
    assert pr.candidatos(str(RAIZ / "src" / "inexistente_zzz.py")) == []


def test_o_gancho_de_provas_nunca_reprova_a_edicao():
    """
    Quem decide se a mudança está pronta é a suíte inteira, no `pytest
    -q` e no CI. Um gancho que reprova pela metade do sinal treina a
    ignorar o sinal inteiro.
    """
    for entrada in (
        {"tool_name": "Edit", "tool_input": {"file_path": "src/db.py"}},
        {"tool_name": "Edit", "tool_input": {"file_path": "README.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
    ):
        saida = _rodar_gancho("provas_relacionadas.py", entrada)
        assert saida.returncode == 0


# ---------------------------------------------------------------------------
# 4) Skills e subagente: forma mínima e nenhum segredo
# ---------------------------------------------------------------------------
def _frontmatter(caminho: Path) -> str:
    texto = caminho.read_text()
    assert texto.startswith("---\n"), f"{caminho.name} sem frontmatter"
    fim = texto.index("\n---", 4)
    return texto[4:fim]


@pytest.mark.parametrize("caminho", sorted(CLAUDE.glob("skills/*/SKILL.md")),
                         ids=lambda p: p.parent.name)
def test_toda_skill_se_identifica(caminho):
    """
    Sem `name` e `description` a skill não é descoberta — fica no disco
    parecendo instalada e não é invocável por ninguém.
    """
    cabeca = _frontmatter(caminho)
    assert re.search(r"^name:\s*\S", cabeca, re.M), caminho
    assert re.search(r"^description:\s*\S", cabeca, re.M), caminho


@pytest.mark.parametrize("caminho", sorted(CLAUDE.glob("agents/*.md")),
                         ids=lambda p: p.stem)
def test_todo_subagente_se_identifica(caminho):
    cabeca = _frontmatter(caminho)
    assert re.search(r"^name:\s*\S", cabeca, re.M), caminho
    assert re.search(r"^description:\s*\S", cabeca, re.M), caminho


def test_nada_em_claude_carrega_segredo():
    """
    Mesma varredura que guarda o repositório, apontada para a camada
    nova. Instruções de agente falam de chave, papel e credencial o
    tempo todo — é exatamente o tipo de arquivo onde um valor de
    exemplo copiado de um `secrets.toml` real passaria despercebido.
    """
    from varredura_segredos import SEGREDO_REAL, varrer

    reais = []
    for arquivo in sorted(CLAUDE.rglob("*")):
        if not arquivo.is_file() or arquivo.suffix == ".pyc":
            continue
        try:
            texto = arquivo.read_text()
        except UnicodeDecodeError:
            continue
        reais += [a for a in varrer(str(arquivo.relative_to(RAIZ)), texto)
                  if a.situacao == SEGREDO_REAL]

    assert reais == [], f"segredo em .claude/: {reais}"


# ---------------------------------------------------------------------------
# 5) A FRONTEIRA — a prova que existe para ser desobedecida algum dia
# ---------------------------------------------------------------------------
def test_o_aplicativo_nao_conhece_a_camada_de_automacao():
    """
    Nenhuma funcionalidade do produto pode depender desta camada. Se ela
    sumir — plugin desinstalado, Cartographer fora do ar, `.claude/`
    apagado —, o app tem que continuar gerando documento igual.

    A prova é por MENÇÃO e não por import porque o vazamento provável
    não é `import setup_advisor`: é alguém montar um caminho para
    `.claude/skills/...` e ler de lá em tempo de execução.
    """
    vazamentos = []
    for arquivo in sorted((RAIZ / "src").rglob("*.py")):
        texto = arquivo.read_text()
        for marca in (".claude", "setup-advisor", "setup_advisor",
                      "cartographer", "claude-code-setup"):
            if marca in texto:
                vazamentos.append(f"{arquivo.relative_to(RAIZ)}: {marca}")

    assert vazamentos == [], (
        "a camada de desenvolvimento vazou para o produto: "
        f"{vazamentos}")


def test_o_app_nao_depende_do_settings_para_subir():
    """
    O contrapositivo da anterior, dito no que o app IMPORTA: `app.py`
    não lê `.claude/` e não conhece MCP nenhum.
    """
    texto = (RAIZ / "app.py").read_text()
    for marca in (".claude", ".mcp.json", "cartographer"):
        assert marca not in texto, f"app.py menciona {marca}"
