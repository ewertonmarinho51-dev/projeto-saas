"""Garante que a raiz do projeto esteja no sys.path.

O AppTest executa app.py no processo do pytest; sem isto, `from src
import ...` falha quando o pytest é invocado como binário (`pytest`),
que — ao contrário de `python -m pytest` — não inclui o diretório
atual no sys.path.
"""

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
