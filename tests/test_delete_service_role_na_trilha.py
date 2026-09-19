"""
A 0027, EXECUTADA: a credencial de servidor não apaga linha da trilha.

A DECISÃO DE PRODUTO QUE DESTRAVOU ISTO

`docs/proposta-delete-service-role.md` terminava numa pergunta só, e ela
era de produto, não de banco: em `secretarias`, `usuarios` e
`config_orgaos`, "remover" significa apagar a linha ou marcar como
inativa? Em 19/09/2026 o operador respondeu: **apagar a linha**.

A resposta MANTÉM o DELETE nessas tabelas — uma tela de administração
que apaga precisa do privilégio — e não diz nada sobre o grupo da
TRILHA, que é o que esta migração fecha. Por isso ela vem primeiro: é o
grupo onde a resposta não muda nada e onde revogar é coerência, não
aposta.

POR QUE A TRILHA É O GRUPO CERTO PARA COMEÇAR

`governanca_eventos` já não aceita escrita de `authenticated` desde a
0020 — "nenhuma escrita direta, por ninguém, nem o admin". E a
credencial de servidor apagava o que o admin não pode apagar. Essa
contradição a 0021 corrigiu nas tabelas de preço e ninguém estendeu ao
resto.

E há um agravante novo: desde a 0026 a tabela `geracoes` registra SOB
QUAL POLÍTICA cada documento foi gerado. Uma trilha que diz de quem é o
ato e sob que regra ele saiu, e que a credencial do app pode reescrever
linha a linha, prova menos do que aparenta.

DOIS NÍVEIS, E O SEGUNDO É O QUE DECIDE

  1. o catálogo não concede DELETE a `service_role` nas 13;
  2. `set role service_role; delete from governanca_eventos` leva 42501.

Catálogo limpo é afirmação sobre um `information_schema`. O que o órgão
precisa é que o COMANDO seja recusado.

A GUARDA INVERTIDA, que protege o outro lado: `service_role` PRECISA
continuar apagando em `processos`, `config_orgaos` e
`documentos_referencia` — é o que `src/db.py` e `src/rag.py` fazem.
Sem ela, a próxima rodada de endurecimento leva junto, e a descoberta
acontece em produção.

FRONTEIRA: isto prova o BANCO. Não prova PostgREST, GoTrue nem
`supabase-py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import voltar_a_ser_servidor  # noqa: E402

requer_pg = pytest.mark.usefixtures("ensaio_sql")

PRIVILEGIO_INSUFICIENTE = "42501"

# As 13 do grupo "trilha e histórico" da proposta. Nenhum código apaga
# nelas — medido por leitura de `src/` (três `.delete(` no sistema
# inteiro) e de `pg_proc` (nenhuma função de `public` com `delete from`).
TRILHA = (
    "aprendizado_feedback", "decisoes", "geracoes",
    "governanca_aprovacoes", "governanca_artefatos", "governanca_eventos",
    "governanca_publicacoes", "governanca_versoes", "parecer_achados",
    "pareceres", "qualidade_scores", "revisoes", "simulacoes",
)

# Onde o aplicativo REALMENTE apaga, via `service_role`:
#   src/db.py:1385  config_orgaos
#   src/db.py:1402  processos
#   src/rag.py:447  documentos_referencia
ONDE_O_APP_APAGA = ("processos", "config_orgaos", "documentos_referencia")

# As que a resposta do operador MANTÉM apagáveis: "remover" ali é apagar
# a linha, e uma tela de administração que apaga precisa do privilégio.
# Estão aqui para que um endurecimento futuro não as leve por engano.
ONDE_A_DECISAO_MANTEM = ("secretarias", "usuarios")

PAPEIS_DE_REDE = ("service_role", "authenticated", "anon", "PUBLIC")


def _como_service_role(banco, sql):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        c.execute("set local role service_role")
        try:
            c.execute(sql)
            return None
        except Exception as erro:  # noqa: BLE001
            return getattr(erro, "sqlstate", None)


# ---------------------------------------------------------------------------
# 0) A prova de que as outras não são vazias
# ---------------------------------------------------------------------------
@requer_pg
def test_as_treze_tabelas_da_trilha_existem(banco):
    """
    Sem isto, uma prova de "ninguém apaga em X" passaria com X
    inexistente — e passaria por um motivo que não tem nada a ver com
    privilégio. Foi assim que a suíte aprendeu a exigir o schema de pé.
    """
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select to_regclass('public.' || t) is not null "
                  "from unnest(%s::text[]) t", (list(TRILHA),))
        existem = [linha[0] for linha in c.fetchall()]
    assert all(existem), (
        "tabela da trilha ausente do ensaio: "
        f"{[t for t, ok in zip(TRILHA, existem) if not ok]}")


# ---------------------------------------------------------------------------
# 1) O catálogo
# ---------------------------------------------------------------------------
@requer_pg
def test_nenhum_papel_de_rede_apaga_na_trilha(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(
            "select table_name, grantee from information_schema."
            "role_table_grants where table_schema = 'public' "
            "and table_name = any(%s) and privilege_type = 'DELETE' "
            "and grantee = any(%s)",
            (list(TRILHA), list(PAPEIS_DE_REDE)))
        sobrou = c.fetchall()
    assert sobrou == [], f"DELETE ainda concedido na trilha: {sobrou}"


# ---------------------------------------------------------------------------
# 2) O COMANDO — é este nível que decide
# ---------------------------------------------------------------------------
@requer_pg
@pytest.mark.parametrize("tabela", TRILHA)
def test_service_role_nao_apaga_linha_da_trilha(banco, tabela):
    """
    Executado, não lido. E a asserção é no SQLSTATE: exigir "alguma
    exceção" deixaria passar uma recusa por outro motivo — FK, tabela
    ausente, sintaxe — que provaria o contrário do que o teste promete.
    """
    estado = _como_service_role(banco, f"delete from public.{tabela}")
    assert estado == PRIVILEGIO_INSUFICIENTE, (
        f"`delete from {tabela}` como service_role devolveu {estado!r}, "
        f"e não {PRIVILEGIO_INSUFICIENTE} — a trilha continua apagável")


# ---------------------------------------------------------------------------
# 3) A GUARDA INVERTIDA — o que NÃO pode ser levado junto
# ---------------------------------------------------------------------------
@requer_pg
@pytest.mark.parametrize("tabela", ONDE_O_APP_APAGA)
def test_service_role_continua_apagando_onde_o_app_apaga(banco, tabela):
    """
    Esta prova existe para QUEBRAR se a próxima rodada de endurecimento
    for ampla demais. O aplicativo apaga nestas três; revogar aqui
    derruba um botão que funciona hoje, e a descoberta seria em produção.
    """
    estado = _como_service_role(banco, f"delete from public.{tabela}")
    assert estado != PRIVILEGIO_INSUFICIENTE, (
        f"a 0027 revogou DELETE de {tabela}, que o aplicativo USA — "
        "ver src/db.py e src/rag.py")


@requer_pg
@pytest.mark.parametrize("tabela", ONDE_A_DECISAO_MANTEM)
def test_a_decisao_do_operador_manteve_estas_apagaveis(banco, tabela):
    """
    "Remover" nestas tabelas é apagar a linha — decisão registrada em
    19/09/2026. A prova fixa a decisão no código: quem a mudar depois
    muda um teste com nome, e não descobre pela tela de administração.
    """
    estado = _como_service_role(banco, f"delete from public.{tabela}")
    assert estado != PRIVILEGIO_INSUFICIENTE, (
        f"{tabela} ficou sem DELETE, mas a decisão de produto diz que "
        "'remover' ali apaga a linha")


# ---------------------------------------------------------------------------
# 4) O dono continua podendo — revogar de `postgres` seria teatro
# ---------------------------------------------------------------------------
@requer_pg
def test_o_dono_continua_podendo_apagar(banco):
    """
    `postgres` é dono das tabelas e tem tudo por construção. A limpeza
    legítima de registro antigo continua possível — por migração com
    nome, que é onde ela deve estar, e não pela credencial do app.
    """
    estado = _como_service_role(banco, "select 1")  # sanidade do dublê
    assert estado is None

    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("delete from public.governanca_eventos")  # não levanta
