"""Garante que a raiz do projeto esteja no sys.path.

O AppTest executa app.py no processo do pytest; sem isto, `from src
import ...` falha quando o pytest é invocado como binário (`pytest`),
que — ao contrário de `python -m pytest` — não inclui o diretório
atual no sys.path.
"""

import pytest
import sys
import types
import uuid
from pathlib import Path

RAIZ = str(Path(__file__).resolve().parent.parent)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)


# ---------------------------------------------------------------------------
# Trilha de governança nos bancos falsos
#
# A trilha deixou de ser `insert` direto pelo cliente de SERVIDOR e
# passou a ser a RPC `registrar_evento_governanca`, chamada pelo
# cliente do USUÁRIO. Os bancos falsos dos testes de domínio precisam
# acompanhar — senão testam um caminho que o app não usa mais.
#
# Esta emulação é DELIBERADAMENTE mínima: confere o vocabulário (o que
# um erro de nome de evento faria o servidor recusar) e grava `ator`
# como identidade fixa da sessão falsa. Ela NÃO emula papel, tenant nem
# secretaria — quem prova autorização é o ensaio contra um Postgres de
# verdade, e um fake que fingisse fazer isso daria falsa segurança.
# ---------------------------------------------------------------------------
ATOR_FALSO = "00000000-0000-0000-0000-0000000000a7"


def ligar_trilha_falsa(monkeypatch, db_mod, cliente, tabelas) -> None:
    """
    Faz o cliente falso responder à RPC da trilha e ser o cliente do
    usuário. Sem isto, `cliente_do_usuario()` devolve None e a trilha
    recusa — que é o comportamento certo em produção e ruído no teste
    de domínio.
    """
    from src import trilha

    def rpc(nome, parametros):
        assert nome == "registrar_evento_governanca", nome
        # o servidor confere; o fake confere o mesmo, para que um nome
        # de evento errado apareça aqui e não só no ensaio
        trilha.exigir_evento_valido(parametros["p_tipo_evento"],
                                    parametros["p_entidade_tipo"])
        registro = {
            "id": str(uuid.uuid4()),
            "tenant_id": db_mod.tenant_atual(),
            "ator": ATOR_FALSO,
            "tipo_evento": parametros["p_tipo_evento"],
            "entidade_tipo": parametros["p_entidade_tipo"],
            "entidade_id": parametros["p_entidade_id"],
            "payload": parametros["p_payload"],
        }
        tabelas.setdefault("governanca_eventos", []).append(registro)
        return types.SimpleNamespace(
            execute=lambda: types.SimpleNamespace(data=registro["id"]))

    cliente.rpc = rpc
    monkeypatch.setattr(db_mod, "cliente_do_usuario", lambda: cliente)


# ---------------------------------------------------------------------------
# Motor institucional de PDF (DOCX → LibreOffice → PDF)
#
# As provas do PDF real dependem do LibreOffice Writer. Sem ele, nenhum
# filtro de documento carrega, `export.motor_pdf()` responde "fpdf2" e as
# provas PULAM — foi assim que um defeito grave ficou invisível: os 210
# códigos da planilha saíam partidos no PDF ("57270" + "4"), e a prova
# que teria acusado isso nunca rodou, nem aqui nem na CI.
#
# Pular é aceitável na máquina de quem desenvolve. Em CI/release não é:
# ali a ausência do motor institucional é FALHA DE AMBIENTE, e o
# interruptor abaixo é o que faz essa diferença ser explícita em vez de
# depender de quem lê a saída notar 10 linhas de 's'.
# ---------------------------------------------------------------------------
VARIAVEL_MOTOR_OBRIGATORIO = "GOVDOCS_EXIGIR_LIBREOFFICE"


def motor_institucional_obrigatorio() -> bool:
    """O ambiente declara que o LibreOffice é requisito, não conveniência?"""
    import os

    valor = (os.environ.get(VARIAVEL_MOTOR_OBRIGATORIO) or "").strip().lower()
    return valor not in ("", "0", "false", "nao", "não", "off")


def exigir_motor_institucional() -> None:
    """
    Falha (CI/release) ou pula (local) quando o motor não é o LibreOffice.

    Chamada pelas provas que medem o PDF REAL. Nunca silencia: ou o teste
    roda, ou o motivo aparece nomeado na saída.
    """
    import pytest

    from src import export

    motor = export.motor_pdf()
    if motor == "libreoffice":
        return
    recado = (
        f"motor de PDF efetivo é '{motor}', não 'libreoffice': a conversão "
        "DOCX→PDF não roda neste ambiente (falta o pacote "
        "libreoffice-writer — o meta-pacote 'libreoffice' de packages.txt o "
        "inclui). As provas do PDF institucional não podem ser executadas."
    )
    if motor_institucional_obrigatorio():
        pytest.fail(
            f"{recado} Este ambiente declarou "
            f"{VARIAVEL_MOTOR_OBRIGATORIO}=1: aqui a ausência do motor "
            "institucional é falha, não skip."
        )
    pytest.skip(recado)


@pytest.fixture
def motor_institucional():
    """Provas que exigem o PDF real pedem esta fixture."""
    exigir_motor_institucional()
