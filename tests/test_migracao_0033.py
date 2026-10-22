"""
A 0033 (flags do painel para a API) aplicada de verdade, num PostgreSQL
descartável.

O que ela promete e o que não pode virar: `authenticated` lê as flags
pela função — e só as flags com valor booleano; segredo guardado em
`config_app` (inclusive numa chave mal nomeada `flag_*`) não sai; `anon`
não executa; a TABELA continua sem grant e sem política; e a conferência
morde quando o `anon` ganha EXECUTE.
"""

from __future__ import annotations

import json
import pathlib
import re
import uuid

import pytest

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0033_flags_do_app.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))


class _Desfaz(Exception):
    pass


@pytest.fixture(scope="module")
def banco_com_0033(banco):
    with banco.cursor() as cursor:
        cursor.execute(TEXTO)   # idempotência
    return banco


def _transacao(conexao, corpo):
    import psycopg

    with pytest.raises(_Desfaz):
        with conexao.transaction():
            with conexao.cursor() as cursor:
                corpo(cursor, psycopg)
            raise _Desfaz


def _como_usuario(cursor):
    cursor.execute("set local role authenticated")
    cursor.execute("select set_config('request.jwt.claims', %s, true)",
                   (json.dumps({"sub": str(uuid.uuid4()), "role": "authenticated"}),))


def _semear(cursor):
    sufixo = uuid.uuid4().hex[:8]
    linhas = {f"flag_ensaio_{sufixo}": "on",
              f"flag_vazia_{sufixo}": "",
              f"flag_segredo_{sufixo}": "sk-nao-pode-sair",
              f"OPENAI_API_KEY_{sufixo}": "sk-segredo"}
    for chave, valor in linhas.items():
        cursor.execute("insert into public.config_app (chave, valor) values (%s, %s)",
                       (chave, valor))
    return sufixo


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def test_funcao_definer_com_search_path_fixo_e_sem_anon():
    assert "security definer" in SQL
    assert "set search_path = ''" in SQL
    assert "revoke all on function public.flags_do_app() from public, anon;" in SQL
    assert "grant execute on function public.flags_do_app() to authenticated;" in SQL


@pytest.mark.parametrize("proibido", [
    r"grant\s+[^;]*\bon\s+(table\s+)?public\.config_app\b",
    r"create\s+policy\s+[^;]*\bon\s+public\.config_app\b",
    r"disable\s+row\s+level\s+security", r"\bdrop\s+table\b", r"\bdelete\s+from\b",
])
def test_a_tabela_continua_fechada(proibido):
    assert not re.search(proibido, SQL, re.IGNORECASE), proibido


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0033 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
def test_reaplicar_e_inofensivo(banco_com_0033):
    with banco_com_0033.cursor() as cursor:
        cursor.execute(TEXTO)


def test_autenticado_le_so_flags_booleanas(banco_com_0033):
    def corpo(cursor, psycopg):
        sufixo = _semear(cursor)
        _como_usuario(cursor)
        lidas = dict(cursor.execute("select chave, valor from public.flags_do_app()").fetchall())
        assert lidas[f"flag_ensaio_{sufixo}"] == "on"
        assert lidas[f"flag_vazia_{sufixo}"] == ""
        assert f"flag_segredo_{sufixo}" not in lidas, "valor não booleano saiu"
        assert f"OPENAI_API_KEY_{sufixo}" not in lidas, "segredo saiu"
        assert all(c.startswith("flag_") for c in lidas)
    _transacao(banco_com_0033, corpo)


def test_autenticado_continua_sem_ler_a_tabela(banco_com_0033):
    def corpo(cursor, psycopg):
        _semear(cursor)
        _como_usuario(cursor)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with banco_com_0033.transaction():
                cursor.execute("select chave from public.config_app limit 1")
    _transacao(banco_com_0033, corpo)


def test_anon_nao_executa(banco_com_0033):
    def corpo(cursor, psycopg):
        cursor.execute("set local role anon")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with banco_com_0033.transaction():
                cursor.execute("select * from public.flags_do_app()")
    _transacao(banco_com_0033, corpo)


def test_a_conferencia_morde_com_anon_executando(banco_com_0033):
    conferencia = TEXTO[TEXTO.index("do $$"):]

    def corpo(cursor, psycopg):
        cursor.execute("grant execute on function public.flags_do_app() to anon")
        with pytest.raises(psycopg.errors.RaiseException, match="anon_executa"):
            with banco_com_0033.transaction():
                cursor.execute(conferencia)
    _transacao(banco_com_0033, corpo)
