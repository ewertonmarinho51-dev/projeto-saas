"""
A 0028 aplicada de verdade, num PostgreSQL descartável.

POR QUE ESTE ARQUIVO EXISTE

A 0028 está com o sufixo `.NAO_APLICAR`, que é a trava contra aplicá-la
em produção por engano. A trava impede o acidente e não responde à
pergunta que importa: ela FUNCIONA?

Aplicar num cluster local descartável é o único jeito de saber antes
que alguém a aplique de verdade — é o argumento que já governa as
0018/0019/0020 neste repositório, e vale igual aqui.

O que se mede: que o bloco de conferência da própria migração passa,
que a tabela nasce com RLS, que nenhuma política é irrestrita, que o
índice único existe (sem ele o upsert do cache não tem em que
conflitar) e que as sete colunas novas de `geracoes` nascem NULLABLE —
porque as 168 linhas anteriores correram sem esses dados, e inventar
valor para elas seria afirmar o que ninguém mediu.
"""

from __future__ import annotations

import pathlib

import pytest

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations"
            / "0028_controle_de_consumo_e_cache.sql.NAO_APLICAR")

COLUNAS_NOVAS = ("operacao", "secretaria_id", "usuario_id", "cache_hit",
                 "tokens_evitados_entrada", "tokens_evitados_saida", "custo")


@pytest.fixture(scope="module")
def banco_com_0028(banco):
    """
    O schema real com a 0028 por cima.

    Se a migração falhar, o erro sobe — o bloco `do $$` dela levanta
    exceção quando não cumpre o que declara, e é exatamente isso que
    esta prova quer ver acontecer (ou não acontecer).
    """
    with banco.cursor() as cursor:
        cursor.execute(MIGRACAO.read_text(encoding="utf-8"))
    return banco


def test_a_migracao_aplica_e_a_propria_conferencia_dela_passa(banco_com_0028):
    """
    O bloco de conferência da 0028 levanta exceção se `add column if not
    exists` não acrescentou ou se a tabela nasceu sem RLS. Chegar aqui
    já é o resultado; a asserção abaixo é a testemunha disso.
    """
    with banco_com_0028.cursor() as cursor:
        cursor.execute(
            "select count(*) from information_schema.tables "
            "where table_schema='public' and table_name='cache_geracoes'")
        assert cursor.fetchone()[0] == 1


def test_e_idempotente(banco_com_0028):
    """
    Migração que só funciona uma vez trava qualquer reaplicação — e
    reaplicar é o que acontece quando alguém repete o passo depois de
    uma falha de rede no meio.
    """
    with banco_com_0028.cursor() as cursor:
        cursor.execute(MIGRACAO.read_text(encoding="utf-8"))


@pytest.mark.parametrize("coluna", COLUNAS_NOVAS)
def test_as_colunas_de_consumo_nascem_nulaveis(banco_com_0028, coluna):
    with banco_com_0028.cursor() as cursor:
        cursor.execute(
            "select is_nullable, column_default "
            "from information_schema.columns "
            "where table_schema='public' and table_name='geracoes' "
            "and column_name=%s", (coluna,))
        linha = cursor.fetchone()
    assert linha, f"a coluna {coluna} não foi criada"
    assert linha[0] == "YES" and linha[1] is None, (
        f"{coluna} nasceu com NOT NULL ou default — as 168 linhas "
        "anteriores passariam a afirmar um consumo que ninguém mediu")


def test_o_cache_nasce_com_rls_ligada_e_forcada(banco_com_0028):
    """
    `force row level security` é o que faz a política valer também para
    o DONO da tabela. Sem ele, a RLS existe e não alcança quem mais
    importa neste banco.
    """
    with banco_com_0028.cursor() as cursor:
        cursor.execute(
            "select relrowsecurity, relforcerowsecurity from pg_class "
            "where relname='cache_geracoes' and relnamespace='public'::regnamespace")
        ligada, forcada = cursor.fetchone()
    assert ligada and forcada


def test_nenhuma_politica_do_cache_e_irrestrita(banco_com_0028):
    """
    `USING (true)` numa tabela que guarda o texto de documentos de
    contratação entregaria o rascunho de um município a outro. A regra
    do §12 do enunciado de segurança, medida no catálogo e não na
    intenção.
    """
    with banco_com_0028.cursor() as cursor:
        cursor.execute(
            "select policyname, qual, with_check from pg_policies "
            "where schemaname='public' and tablename='cache_geracoes'")
        politicas = cursor.fetchall()
    assert len(politicas) >= 3, politicas
    for nome, usando, checando in politicas:
        for expressao in (usando, checando):
            assert (expressao or "").strip().lower() not in ("true", "(true)"), (
                f"política irrestrita: {nome}")


def test_anon_nao_alcanca_o_cache(banco_com_0028):
    """
    `anon` é o papel do visitante não autenticado. A 0019 fechou o
    acesso dele; uma tabela nova que reabrisse desfaria aquela correção
    sem que ninguém percebesse.
    """
    with banco_com_0028.cursor() as cursor:
        cursor.execute(
            "select count(*) from information_schema.role_table_grants "
            "where table_schema='public' and table_name='cache_geracoes' "
            "and grantee='anon'")
        assert cursor.fetchone()[0] == 0


def test_o_indice_unico_da_chave_existe(banco_com_0028):
    """
    Sem ele o `upsert(on_conflict="tenant_id,chave")` do
    `cache_geracao.py` não tem em que conflitar: a tabela viraria um log
    que cresce e nunca acerta, e o cache ficaria ligado sem efeito.
    """
    with banco_com_0028.cursor() as cursor:
        cursor.execute(
            "select indexdef from pg_indexes where schemaname='public' "
            "and tablename='cache_geracoes' "
            "and indexname='idx_cache_geracoes_chave'")
        linha = cursor.fetchone()
    assert linha and "UNIQUE" in linha[0].upper()
    assert "tenant_id" in linha[0] and "chave" in linha[0]


def test_apagar_o_processo_leva_o_cache_dele_junto(banco_com_0028):
    """
    `on delete cascade`: cache órfão de processo apagado é dado de
    contratação sobrevivendo ao processo que o justificava.
    """
    with banco_com_0028.cursor() as cursor:
        cursor.execute(
            "select confdeltype from pg_constraint "
            "where conrelid='public.cache_geracoes'::regclass "
            "and contype='f' and confrelid='public.processos'::regclass")
        assert cursor.fetchone()[0] == "c"   # 'c' = cascade
