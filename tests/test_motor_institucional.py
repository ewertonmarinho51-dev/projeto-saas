"""
Fase 2.1 — o motor institucional de PDF não pode sumir em silêncio.

O PDF oficial nasce de DOCX → LibreOffice → PDF. Sem o pacote
`libreoffice-writer` nenhum filtro de documento carrega,
`export.motor_pdf()` responde `fpdf2` e TODAS as provas do PDF real
pulam. Foi assim que um defeito grave atravessou a Fase 1 inteira: os 210
códigos da planilha saíam partidos no PDF convertido ("57270" + "4"),
impossíveis de localizar no texto extraído, e a prova que teria acusado
isso nunca rodou — nem localmente, nem na CI, que também não instalava o
LibreOffice.

Pular é razoável na máquina de quem desenvolve. Em CI/release a ausência
do motor institucional é FALHA DE AMBIENTE, e é isso que
`GOVDOCS_EXIGIR_LIBREOFFICE=1` declara.

Este arquivo prova o portão, não o PDF: ele roda sempre, com ou sem
LibreOffice.
"""

import pytest

from conftest import (VARIAVEL_MOTOR_OBRIGATORIO, exigir_motor_institucional,
                      motor_institucional_obrigatorio)
from src import export


# ---------------------------------------------------------------------------
# O interruptor
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("valor", ["1", "true", "sim", "obrigatorio"])
def test_ambiente_pode_declarar_o_motor_obrigatorio(valor, monkeypatch):
    monkeypatch.setenv(VARIAVEL_MOTOR_OBRIGATORIO, valor)
    assert motor_institucional_obrigatorio()


@pytest.mark.parametrize("valor", ["", "0", "false", "não", "off", "  "])
def test_valores_de_desligado_sao_reconhecidos(valor, monkeypatch):
    monkeypatch.setenv(VARIAVEL_MOTOR_OBRIGATORIO, valor)
    assert not motor_institucional_obrigatorio()


def test_sem_a_variavel_o_padrao_e_permissivo(monkeypatch):
    """A máquina de quem desenvolve não é obrigada a ter LibreOffice."""
    monkeypatch.delenv(VARIAVEL_MOTOR_OBRIGATORIO, raising=False)
    assert not motor_institucional_obrigatorio()


# ---------------------------------------------------------------------------
# O portão decide certo nos quatro cruzamentos
# ---------------------------------------------------------------------------
def test_motor_presente_deixa_a_prova_rodar(monkeypatch):
    monkeypatch.setattr(export, "motor_pdf", lambda: "libreoffice")
    for declaracao in ("1", "0"):
        monkeypatch.setenv(VARIAVEL_MOTOR_OBRIGATORIO, declaracao)
        exigir_motor_institucional()   # não levanta nada


def test_motor_ausente_em_ci_e_falha_e_nao_skip(monkeypatch):
    """O ponto de toda a Fase 2.1: em CI, ausência do motor REPROVA."""
    monkeypatch.setattr(export, "motor_pdf", lambda: "fpdf2")
    monkeypatch.setenv(VARIAVEL_MOTOR_OBRIGATORIO, "1")
    # pytest.fail/skip levantam OutcomeException, que deriva de
    # BaseException — capturar só Exception deixaria passar batido
    with pytest.raises(BaseException) as erro:
        exigir_motor_institucional()
    assert erro.typename == "Failed", erro.typename   # não é Skipped
    mensagem = str(erro.value)
    assert "libreoffice" in mensagem.lower()
    assert VARIAVEL_MOTOR_OBRIGATORIO in mensagem


def test_motor_ausente_localmente_pula_com_motivo_nomeado(monkeypatch):
    monkeypatch.setattr(export, "motor_pdf", lambda: "fpdf2")
    monkeypatch.delenv(VARIAVEL_MOTOR_OBRIGATORIO, raising=False)
    with pytest.raises(BaseException) as erro:
        exigir_motor_institucional()
    assert erro.typename == "Skipped", erro.typename
    mensagem = str(erro.value)
    # o motivo diz O QUE falta e COMO resolver — skip sem motivo é ruído
    assert "libreoffice-writer" in mensagem
    assert "packages.txt" in mensagem


# ---------------------------------------------------------------------------
# A declaração de ambiente e a de implantação não podem divergir
# ---------------------------------------------------------------------------
def test_packages_txt_declara_o_motor_institucional():
    """
    `packages.txt` é o que a implantação instala. Se o LibreOffice sair
    dali, o PDF oficial deixa de ser o institucional em produção — e
    nenhuma prova de teste pegaria isso.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    declarados = (raiz / "packages.txt").read_text(encoding="utf-8").split()
    assert any(p.startswith("libreoffice") for p in declarados), declarados


def test_ci_instala_o_motor_e_o_declara_obrigatorio():
    """
    A CI rodou a suíte inteira sem LibreOffice desde sempre: as provas do
    PDF real pulavam e ninguém via. O workflow tem de instalar o motor E
    ligar o interruptor — instalar sem exigir deixaria a porta aberta
    para o silêncio voltar na primeira vez que a instalação falhasse.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    ci = (raiz / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "libreoffice-writer" in ci, "a CI não instala o motor institucional"
    assert VARIAVEL_MOTOR_OBRIGATORIO in ci, \
        "a CI instala o motor mas não exige que ele exista"
