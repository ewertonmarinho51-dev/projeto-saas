"""
Continuidade e gancho Stop, EXECUTADOS num repositório git descartável:
tarefa incompleta bloqueia com a próxima ação; concluída libera; bloqueio
externo libera explicando; evidência forjada, falha ou vencida não conta;
o laço sem progresso termina; o SessionStart devolve o checkpoint.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
CLI = RAIZ / "scripts" / "continuidade.py"
STOP = RAIZ / ".claude" / "hooks" / "parar_com_evidencia.py"
INICIO = RAIZ / ".claude" / "hooks" / "retomar_checkpoint.py"


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "teste@exemplo.invalid")
    git("config", "user.name", "Teste")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "modulo.py").write_text("VALOR = 1\n")
    (tmp_path / "doc.md").write_text("texto\n")
    git("add", ".")
    git("commit", "-qm", "inicio")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONTINUIDADE", raising=False)
    return tmp_path


def cli(repo, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=repo,
                          capture_output=True, text=True, timeout=120,
                          env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo)})


def parar(repo, sessao="s1") -> dict | None:
    saida = subprocess.run([sys.executable, str(STOP)], cwd=repo, capture_output=True,
                           text=True, timeout=300,
                           input=json.dumps({"session_id": sessao, "cwd": str(repo)}),
                           env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo)})
    assert saida.returncode == 0, saida.stderr
    return json.loads(saida.stdout) if saida.stdout.strip() else None


OK = [sys.executable, "-c", "print('provas verdes')"]
FALHA = [sys.executable, "-c", "import sys; sys.exit(3)"]


def iniciar(repo, *criterios):
    r = cli(repo, "iniciar", "--objetivo", "entregar X",
            *[x for c in criterios for x in ("--criterio", c)])
    assert r.returncode == 0, r.stderr


def test_sem_tarefa_registrada_o_gancho_nao_interfere(repo):
    assert parar(repo) is None


def test_tarefa_incompleta_bloqueia_com_a_proxima_acao(repo):
    iniciar(repo, "C1: provas verdes", "C2: implantado")
    cli(repo, "proxima", "rodar as provas de preços")
    resposta = parar(repo)
    assert resposta["decision"] == "block"
    assert "C1" in resposta["reason"] and "C2" in resposta["reason"]
    assert "rodar as provas de preços" in resposta["reason"]
    assert "continuidade.py provar C1" in resposta["reason"]


def test_tarefa_concluida_com_prova_executada_libera(repo):
    iniciar(repo, "C1: provas verdes")
    assert cli(repo, "provar", "C1", "--arquivos", "src", "--", *OK).returncode == 0
    resposta = parar(repo)
    assert "decision" not in (resposta or {})
    assert cli(repo, "concluir").returncode == 0
    assert parar(repo) is None  # concluída: inativa


def test_bloqueio_externo_documentado_libera_explicando(repo):
    iniciar(repo, "C1: implantado em produção")
    cli(repo, "bloquear", "--motivo", "senha da chave SSH",
        "--falta", "o dono digitar a senha no Terminal")
    resposta = parar(repo)
    assert "decision" not in resposta
    assert "senha da chave SSH" in resposta["systemMessage"]


def test_comando_que_falhou_nao_prova_nada(repo):
    iniciar(repo, "C1: provas verdes")
    assert cli(repo, "provar", "C1", "--", *FALHA).returncode == 1
    resposta = parar(repo)
    assert resposta["decision"] == "block" and "código 3" in resposta["reason"]


def test_declaracao_forjada_no_estado_nao_conta(repo):
    iniciar(repo, "C1: provas verdes")
    arq = repo / ".claude" / "continuidade" / "estado.json"
    estado = json.loads(arq.read_text(encoding="utf-8"))
    estado["criterios"][0]["evidencia"] = {
        "argv": ["pytest"], "codigo": 0, "log": ".claude/continuidade/evidencias/x.log",
        "saida_sha256": "0" * 64, "arquivos": [], "assinatura": "qualquer"}
    arq.write_text(json.dumps(estado), encoding="utf-8")
    resposta = parar(repo)
    assert resposta["decision"] == "block" and "evidência inválida" in resposta["reason"]


def test_log_adulterado_depois_da_prova_nao_conta(repo):
    iniciar(repo, "C1: provas verdes")
    cli(repo, "provar", "C1", "--", *FALHA)
    log = next((repo / ".claude" / "continuidade" / "evidencias").glob("C1-*.log"))
    log.write_text("tudo verde\n")
    estado = json.loads((repo / ".claude/continuidade/estado.json").read_text(encoding="utf-8"))
    estado["criterios"][0]["evidencia"]["codigo"] = 0
    (repo / ".claude/continuidade/estado.json").write_text(json.dumps(estado), encoding="utf-8")
    assert parar(repo)["decision"] == "block"


def test_mudanca_no_codigo_coberto_vence_a_prova_cara(repo):
    iniciar(repo, "C1: provas verdes")
    cli(repo, "provar", "C1", "--arquivos", "src", "--", *OK)
    (repo / "src" / "modulo.py").write_text("VALOR = 2\n")
    resposta = parar(repo)
    assert resposta["decision"] == "block" and "evidência vencida" in resposta["reason"]


def test_mudanca_fora_do_que_a_prova_cobre_nao_vence(repo):
    iniciar(repo, "C1: provas verdes")
    cli(repo, "provar", "C1", "--arquivos", "src", "--", *OK)
    (repo / "doc.md").write_text("outro texto\n")
    assert "decision" not in (parar(repo) or {})


def test_prova_barata_vencida_e_refeita_pelo_gancho(repo):
    iniciar(repo, "C1: provas verdes")
    cli(repo, "provar", "C1", "--arquivos", "src", "--barato", "--", *OK)
    (repo / "src" / "modulo.py").write_text("VALOR = 2\n")
    assert "decision" not in (parar(repo) or {})
    logs = list((repo / ".claude" / "continuidade" / "evidencias").glob("C1-*.log"))
    assert len(logs) >= 1


def test_sem_progresso_o_laco_termina_e_registra_a_interrupcao(repo):
    iniciar(repo, "C1: provas verdes")
    respostas = [parar(repo) for _ in range(5)]
    assert respostas[0]["decision"] == "block"
    liberou = [r for r in respostas if "decision" not in r]
    assert liberou, "o gancho prendeu a sessão para sempre"
    assert "SEM concluir" in liberou[0]["systemMessage"]
    estado = json.loads((repo / ".claude/continuidade/estado.json").read_text(encoding="utf-8"))
    assert estado["interrupcoes"] and "sem progresso" in estado["interrupcoes"][0]["motivo"]


def test_progresso_real_reinicia_a_contagem(repo):
    iniciar(repo, "C1: provas verdes", "C2: outra")
    parar(repo)
    parar(repo)
    (repo / "src" / "novo.py").write_text("X = 1\n")  # trabalho de verdade
    assert parar(repo)["decision"] == "block"


def test_desligado_pelo_ambiente(repo, monkeypatch):
    iniciar(repo, "C1: provas verdes")
    saida = subprocess.run([sys.executable, str(STOP)], cwd=repo, capture_output=True,
                           text=True, input=json.dumps({"cwd": str(repo)}),
                           env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo),
                                "CLAUDE_CONTINUIDADE": "0"})
    assert saida.stdout.strip() == ""


def test_retomada_recebe_o_checkpoint(repo):
    iniciar(repo, "C1: provas verdes")
    cli(repo, "etapa", "migração revisada")
    cli(repo, "proxima", "abrir o PR")
    saida = subprocess.run([sys.executable, str(INICIO)], cwd=repo, capture_output=True,
                           text=True, input=json.dumps({"cwd": str(repo)}),
                           env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo)})
    texto = json.loads(saida.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "entregar X" in texto and "migração revisada" in texto and "abrir o PR" in texto
    assert (repo / ".claude" / "continuidade" / "CONTINUIDADE.md").exists()


def test_espera_declarada_libera_e_vencida_volta_a_cobrar(repo):
    iniciar(repo, "C1: suíte completa verde")
    cli(repo, "aguardar", "suíte completa em segundo plano", "--minutos", "20")
    resposta = parar(repo)
    assert "decision" not in resposta and "Aguardando" in resposta["systemMessage"]
    arq = repo / ".claude" / "continuidade" / "estado.json"
    estado = json.loads(arq.read_text(encoding="utf-8"))
    estado["aguardando"]["ate"] = "2000-01-01T00:00:00+00:00"   # prazo vencido
    arq.write_text(json.dumps(estado), encoding="utf-8")
    assert parar(repo)["decision"] == "block"


def test_espera_tem_teto(repo):
    iniciar(repo, "C1: suíte completa verde")
    cli(repo, "aguardar", "carga sem fim", "--minutos", "100000")
    estado = json.loads((repo / ".claude/continuidade/estado.json").read_text(encoding="utf-8"))
    from datetime import datetime, timezone
    ate = datetime.fromisoformat(estado["aguardando"]["ate"])
    assert (ate - datetime.now(timezone.utc)).total_seconds() <= 121 * 60


def test_concluir_recusa_com_criterio_sem_prova(repo):
    iniciar(repo, "C1: provas verdes")
    assert cli(repo, "concluir").returncode == 1
