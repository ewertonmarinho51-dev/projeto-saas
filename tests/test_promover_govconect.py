"""
A trava de regressão de `implantacao/promover_govconect.sh`, com o script
de verdade e um Git de verdade.

POR QUE EXISTE

Em 30/10/2026 uma versão mais antiga foi promovida por cima de outra mais
nova, publicada por outra frente, e dois PRs saíram de produção por
minutos. O script aceitava qualquer `sha-<12>` que tivesse imagem.

FRONTEIRA: o `docker` aqui é um substituto que só anota o que recebeu. A
subida real e o rollback automático são do job `imagens` do CI, contra um
registro local. Esta prova responde outra pergunta: o script chega ou não
a tocar no Docker?
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "implantacao" / "promover_govconect.sh"

DOCKER_FALSO = """#!/usr/bin/env bash
echo "$*" >> "$DOCKER_LOG"
case "$*" in
  *"ps -q"*) echo contentor ;;
  inspect*) echo "${SAUDE_FALSA:-healthy}" ;;
esac
"""

# Pelo PATH: no Windows, `subprocess` com o nome solto acha o do WSL antes.
BASH = shutil.which("bash")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=prova", "-c", "user.email=prova@exemplo.test", *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


class Bancada:
    """Um clone do host com esta história:

    raiz --- no_ar --- depois       (main)
         \\
          lateral                   (nunca entrou no main)
    """

    def __init__(self, base: Path):
        self.base = base
        self.repo = base / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        self.raiz = self._commit("raiz")
        self.no_ar = self._commit("no ar")
        self.depois = self._commit("depois")
        _git(self.repo, "checkout", "-q", "-b", "lateral", self.raiz)
        self.lateral = self._commit("lateral")
        _git(self.repo, "checkout", "-q", "main")

        self.estado = base / "imagens.env"
        self.log = base / "promocoes.log"
        self.docker_log = base / "docker.log"
        self.docker_log.touch()
        binarios = base / "bin"
        binarios.mkdir()
        docker = binarios / "docker"
        docker.write_text(DOCKER_FALSO, encoding="utf-8", newline="\n")
        docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
        self.binarios = binarios
        self.colocar_no_ar(self.no_ar)

    def _commit(self, mensagem: str) -> str:
        _git(self.repo, "commit", "-q", "--allow-empty", "-m", mensagem)
        return _git(self.repo, "rev-parse", "--short=12", "HEAD")

    def colocar_no_ar(self, sha: str) -> None:
        self.estado.write_text(
            f"GOVCONECT_IMAGEM_API=registro/govconect-api:sha-{sha}\n"
            f"GOVCONECT_IMAGEM_WORKER=registro/govconect-worker:sha-{sha}\n"
            f"GOVCONECT_IMAGEM_WEB=registro/govconect-web:production-sha-{sha}\n",
            encoding="utf-8", newline="\n",
        )

    def promover(self, *args: str, **ambiente: str) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "PATH": f"{self.binarios}{os.pathsep}{os.environ['PATH']}",
            "REPO_GIT": str(self.repo),
            "COMPOSE_DIR": str(self.base),
            "ESTADO": str(self.estado),
            "REGISTRO": "registro",
            "LOG": str(self.log),
            "DOCKER_LOG": str(self.docker_log),
            **ambiente,
        }
        return subprocess.run(
            [BASH, SCRIPT.as_posix(), *args],
            env=env, capture_output=True, encoding="utf-8", stdin=subprocess.DEVNULL, timeout=120,
        )

    def tocou_no_docker(self) -> bool:
        return self.docker_log.read_text(encoding="utf-8") != ""

    def tag_no_estado(self) -> str:
        return self.estado.read_text(encoding="utf-8")


@pytest.fixture
def bancada(tmp_path) -> Bancada:
    return Bancada(tmp_path)


def _recusou_sem_mexer(b: Bancada, r: subprocess.CompletedProcess, estado_antes: str) -> None:
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PAROU" in r.stderr
    assert "Nada foi alterado" in r.stderr
    assert not b.tocou_no_docker(), "a recusa tem de vir antes de baixar imagem"
    assert b.tag_no_estado() == estado_antes
    assert not b.estado.with_name(b.estado.name + ".anterior").exists()


def test_versao_que_contem_a_atual_segue(bancada):
    r = bancada.promover(f"sha-{bancada.depois}", "production")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"govconect-api:sha-{bancada.depois}" in bancada.tag_no_estado()
    assert "pull -q" in bancada.docker_log.read_text(encoding="utf-8")


def test_busca_no_origin_o_commit_que_o_clone_ainda_nao_tem(bancada):
    """O caso comum: o merge é mais novo que o último `fetch` do host."""
    host = bancada.base / "host"
    subprocess.run(["git", "clone", "-q", str(bancada.repo), str(host)], check=True)
    novo = bancada._commit("merge depois do clone")

    r = bancada.promover(f"sha-{novo}", "production", REPO_GIT=str(host))
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"govconect-api:sha-{novo}" in bancada.tag_no_estado()


def test_repromover_a_mesma_versao_segue(bancada):
    """Trocar variável de ambiente e subir de novo é rotina, não regressão."""
    r = bancada.promover(f"sha-{bancada.no_ar}", "production")
    assert r.returncode == 0, r.stdout + r.stderr


def test_primeira_promocao_nao_tem_o_que_comparar(bancada):
    bancada.estado.unlink()
    r = bancada.promover(f"sha-{bancada.no_ar}", "production")
    assert r.returncode == 0, r.stdout + r.stderr


def test_versao_atras_da_atual_e_recusada(bancada):
    """O caso de 30/10/2026."""
    bancada.colocar_no_ar(bancada.depois)
    antes = bancada.tag_no_estado()
    r = bancada.promover(f"sha-{bancada.no_ar}", "production")
    _recusou_sem_mexer(bancada, r, antes)
    assert "tiraria 1 commit(s) de produção" in r.stderr
    assert "depois" in r.stderr, "precisa mostrar o que sairia do ar"
    assert "RECUSADO" in bancada.log.read_text(encoding="utf-8")


def test_versao_em_paralelo_e_recusada(bancada):
    """Ramo que não contém a atual tira commits, mesmo tendo commit novo."""
    antes = bancada.tag_no_estado()
    r = bancada.promover(f"sha-{bancada.lateral}", "production")
    _recusou_sem_mexer(bancada, r, antes)
    assert "tiraria 1 commit(s) de produção" in r.stderr


def test_commit_desconhecido_e_recusado(bancada):
    antes = bancada.tag_no_estado()
    r = bancada.promover("sha-abcdefabcdef", "production")
    _recusou_sem_mexer(bancada, r, antes)
    assert "não achei sha-abcdefabcdef" in r.stderr


def test_versao_no_ar_desconhecida_e_recusada(bancada):
    bancada.colocar_no_ar("abcdefabcdef")
    antes = bancada.tag_no_estado()
    r = bancada.promover(f"sha-{bancada.depois}", "production")
    _recusou_sem_mexer(bancada, r, antes)


def test_estado_ilegivel_e_recusado(bancada):
    bancada.estado.write_text("GOVCONECT_IMAGEM_API=registro/govconect-api:latest\n", encoding="utf-8")
    antes = bancada.tag_no_estado()
    r = bancada.promover(f"sha-{bancada.depois}", "production")
    _recusou_sem_mexer(bancada, r, antes)
    assert "não achei a versão no ar" in r.stderr


def test_sem_repositorio_recusa(bancada):
    """Sem como comparar, parar é o lado seguro."""
    antes = bancada.tag_no_estado()
    r = bancada.promover(f"sha-{bancada.depois}", "production", REPO_GIT=str(bancada.base / "nao-existe"))
    _recusou_sem_mexer(bancada, r, antes)


def test_voltar_de_proposito_passa_e_fica_no_log(bancada):
    bancada.colocar_no_ar(bancada.depois)
    r = bancada.promover(f"sha-{bancada.no_ar}", "production", "--voltar")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"govconect-api:sha-{bancada.no_ar}" in bancada.tag_no_estado()
    log = bancada.log.read_text(encoding="utf-8")
    assert f"sha-{bancada.no_ar} production VOLTA intencional: sha-{bancada.depois}" in log


def test_voltar_funciona_sem_repositorio(bancada):
    """Rollback no meio de incidente não pode depender do GitHub nem do clone."""
    bancada.colocar_no_ar(bancada.depois)
    r = bancada.promover(f"sha-{bancada.no_ar}", "production", "--voltar",
                         REPO_GIT=str(bancada.base / "nao-existe"))
    assert r.returncode == 0, r.stdout + r.stderr


def test_rollback_automatico_nao_passa_pela_trava(bancada):
    """A volta sozinha, depois de `api`/`web` não ficarem healthy, restaura
    o arquivo direto. Se dependesse da trava, a versão nova travaria ali."""
    espera = bancada.base / "bin" / "seq"
    espera.write_text('#!/usr/bin/env bash\necho 1\n', encoding="utf-8", newline="\n")
    espera.chmod(espera.stat().st_mode | stat.S_IEXEC)
    dorme = bancada.base / "bin" / "sleep"
    dorme.write_text('#!/usr/bin/env bash\nexit 0\n', encoding="utf-8", newline="\n")
    dorme.chmod(dorme.stat().st_mode | stat.S_IEXEC)

    antes = bancada.tag_no_estado()
    r = bancada.promover(f"sha-{bancada.depois}", "production", SAUDE_FALSA="unhealthy")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "voltando à versão anterior" in r.stderr
    assert bancada.tag_no_estado().strip() == antes.strip()
    assert "FALHOU, revertido" in bancada.log.read_text(encoding="utf-8")


@pytest.mark.parametrize("args", [
    ("sha-123", "production"),
    ("sha-0123456789ab", "homologacao"),
    ("sha-0123456789ab", "production", "--forcar"),
])
def test_argumento_invalido_para_com_uso(bancada, args):
    r = bancada.promover(*args)
    assert r.returncode == 2
    assert "uso:" in r.stderr
    assert not bancada.tocou_no_docker()


def test_atual_continua_so_lendo(bancada):
    r = bancada.promover("--atual")
    assert r.returncode == 0
    assert f"sha-{bancada.no_ar}" in r.stdout
    assert not bancada.tocou_no_docker()
