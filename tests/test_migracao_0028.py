"""
A 0028 aplicada de verdade, num PostgreSQL descartável.

POR QUE ESTE ARQUIVO EXISTE

Ele nasceu quando a 0028 ainda tinha o sufixo `.NAO_APLICAR`, para
responder a pergunta que a trava não responde: ela FUNCIONA? Aplicar num
cluster local descartável era o único jeito de saber antes que alguém a
aplicasse de verdade — o argumento que já governa as 0018/0019/0020
neste repositório.

A 0028 foi aplicada em produção em 08/10/2026 e perdeu o sufixo, mas o
arquivo continua valendo, e por duas razões:

  * ela entrou em `SEQUENCIA_EM_ENSAIO`, de modo que a fixture `banco`
    já a aplica — e aplicá-la DE NOVO aqui é uma prova de
    IDEMPOTÊNCIA de graça, que é o que separa uma migração reaplicável
    de uma que trava o segundo passo de quem repetiu depois de uma
    falha de rede;
  * as asserções não são sobre o arquivo, são sobre o CATÁLOGO: RLS
    ligada e forçada, nenhuma política irrestrita, `anon` sem grant,
    índice único da chave, cascade do processo e as sete colunas
    nuláveis. Elas continuam valendo a cada execução, contra qualquer
    alteração futura que afrouxe alguma dessas garantias.
"""

from __future__ import annotations

import pathlib

import pytest

_MIGRACOES = (pathlib.Path(__file__).resolve().parent.parent
              / "supabase" / "migrations")


def _arquivo_da_0028() -> pathlib.Path:
    """
    A 0028, pelo nome que ela tiver.

    Os dois nomes são aceitos porque o sufixo `.NAO_APLICAR` sai no dia
    da aplicação: amarrar a prova a um deles a quebraria exatamente no
    commit que a destrava, por um motivo que não tem nada a ver com o
    que ela mede.
    """
    for nome in ("0028_controle_de_consumo_e_cache.sql",
                 "0028_controle_de_consumo_e_cache.sql.NAO_APLICAR"):
        caminho = _MIGRACOES / nome
        if caminho.exists():
            return caminho
    raise AssertionError("a 0028 sumiu do repositório")


MIGRACAO = _arquivo_da_0028()

COLUNAS_NOVAS = ("operacao", "secretaria_id", "usuario_id", "cache_hit",
                 "tokens_evitados_entrada", "tokens_evitados_saida", "custo")


@pytest.fixture(scope="module")
def banco_com_0028(banco):
    """
    O schema real com a 0028 aplicada.

    A fixture `banco` já a aplica, porque ela está em
    `SEQUENCIA_EM_ENSAIO`. Aplicá-la aqui de novo não é redundância: é
    a prova de idempotência, e ela roda antes de todas as outras deste
    arquivo. Se a migração não suportasse reaplicação, o erro subiria
    aqui e nenhuma das asserções abaixo chegaria a correr.
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
    uma falha no meio.

    Isto não é hipótese: a aplicação em produção foi por partes, porque
    o `apply_migration` do servidor deu timeout duas vezes sem aplicar
    nada. Cada parte precisou ser reenviável.

    A terceira aplicação. A fixture `banco` fez a primeira (a 0028 está
    em `SEQUENCIA_EM_ENSAIO`), `banco_com_0028` fez a segunda, e esta é
    a terceira — nenhuma delas pode levantar.
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
