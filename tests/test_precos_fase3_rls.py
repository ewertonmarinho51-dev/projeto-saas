"""
Fase 3 da pesquisa de preços — o isolamento das tabelas novas, EXECUTADO.

A migração 0021 afirma coisas fortes: `anon` não alcança nada, secretaria
não vê secretaria, tenant não vê tenant, a trilha é append-only até para
quem atravessa o RLS, e reexecutar não duplica. Afirmação em comentário
de SQL não é contenção — estas provas rodam a 0021 sobre o schema REAL
num PostgreSQL descartável e medem cada uma delas.

O §39 do prompt do módulo é a razão de este arquivo existir antes da
UI: "não ativar este módulo em produção sem provar o mesmo isolamento
exigido do restante da plataforma". O isolamento está provado aqui. O
que continua faltando não é do módulo — é a 0020 chegar à produção, e
isso está dito no relatório.

FRONTEIRA, a mesma de `test_ensaio_sql_local.py`: isto prova o BANCO.
Não prova PostgREST, GoTrue nem `supabase-py`.

Como rodar:

    GOVDOCS_ENSAIO_PG_DSN="postgresql://postgres@/ensaio?host=/tmp/pgens" \\
        python -m pytest tests/test_precos_fase3_rls.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import (  # noqa: E402
    NEGADO,
    PERMITIDO,
    EnsaioLocal,
    claims,
    classificar_sql,
    como,
    criar_banco_descartavel,
    descartar_banco,
    exigir_dsn_local,
    preparar,
    voltar_a_ser_servidor,
)

from src.precos import estados  # noqa: E402
from src.precos.modelo import StatusReferencia  # noqa: E402

from tests.conftest import exigir_ensaio_sql  # noqa: E402

DSN = os.getenv("GOVDOCS_ENSAIO_PG_DSN", "")

# `usefixtures`, e não `skipif`: com `GOVDOCS_EXIGIR_ENSAIO_SQL=1` a
# ausência do banco de ensaio precisa FALHAR, e um `skipif` decidiria
# antes que o portão pudesse opinar.
requer_pg = pytest.mark.usefixtures("ensaio_sql")

TABELAS = ("pesquisas_preco", "pesquisa_preco_itens",
           "pesquisa_preco_referencias", "pesquisa_preco_eventos")

# `23505` é unique_violation. As provas de idempotência exigem ESTE
# código: aceitar qualquer exceção deixaria o teste passar por um erro
# de SQL e provar o contrário do que promete.
UNICIDADE_VIOLADA = "23505"


# A fixture `banco` mora em tests/conftest.py: o smoke ponta a ponta
# usa o mesmo banco, e duas cópias da preparação divergiriam caladas.


@pytest.fixture(scope="module")
def cenario(banco):
    """
    Duas prefeituras, duas secretarias na primeira, e cinco identidades
    — cada uma existindo para provar UMA fronteira.

    `sem_sec` é a que mais importa para esta migração: é o servidor sem
    vínculo de secretaria, o caso que `pode_ler_processo` tranca para
    fora e que `pode_ler_pesquisa_preco` resolve pelo dono.
    """
    dados: dict = {}
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)

        for chave, rotulo in (("tenant_a", "Ensaio Preços A"),
                              ("tenant_b", "Ensaio Preços B")):
            c.execute("insert into tenants (slug, nome) values (%s, %s) "
                      "returning id",
                      (f"{chave}-{uuid.uuid4().hex[:8]}", rotulo))
            dados[chave] = c.fetchone()[0]

        for chave, tenant in (("sec_1", "tenant_a"), ("sec_2", "tenant_a"),
                              ("sec_b", "tenant_b")):
            c.execute("insert into secretarias (tenant_id, nome) "
                      "values (%s, %s) returning id", (dados[tenant], chave))
            dados[chave] = c.fetchone()[0]

        desenho = (
            ("titular",   "usuario", "tenant_a", "sec_1"),
            ("colega",    "usuario", "tenant_a", "sec_1"),
            ("outra_sec", "usuario", "tenant_a", "sec_2"),
            ("admin",     "admin",   "tenant_a", "sec_1"),
            ("sem_sec",   "usuario", "tenant_a", None),
            ("outro_ten", "admin",   "tenant_b", "sec_b"),
        )
        dados["quem"] = {}
        for rotulo, papel, tenant, secretaria in desenho:
            metadados = {"papel": papel, "tenant_id": str(dados[tenant])}
            if secretaria:
                metadados["secretaria_id"] = str(dados[secretaria])
            c.execute("insert into auth.users (email, raw_app_meta_data) "
                      "values (%s, %s) returning id",
                      (f"{rotulo}-{uuid.uuid4().hex[:8]}@ensaio.invalid",
                       json.dumps(metadados)))
            auth_id = c.fetchone()[0]
            dados["quem"][rotulo] = {
                "id": str(auth_id),
                "jwt": claims(str(auth_id), papel, str(dados[tenant]),
                              str(dados[secretaria]) if secretaria else None),
            }

        # Processo da OUTRA secretaria: alvo do vínculo forjado.
        c.execute("insert into processos (orgao, objeto, tenant_id, "
                  "secretaria_id, auth_user_id) values "
                  "('ensaio', 'ensaio', %s, %s, %s) returning id",
                  (dados["tenant_a"], dados["sec_2"],
                   dados["quem"]["outra_sec"]["id"]))
        dados["processo_alheio"] = c.fetchone()[0]

        # Pesquisa da secretaria 1, do titular.
        c.execute(
            "insert into pesquisas_preco (tenant_id, secretaria_id, "
            "auth_user_id, nome) values (%s, %s, %s, 'Material de "
            "expediente') returning id",
            (dados["tenant_a"], dados["sec_1"],
             dados["quem"]["titular"]["id"]))
        dados["pesquisa"] = c.fetchone()[0]

        c.execute(
            "insert into pesquisa_preco_itens (pesquisa_id, tenant_id, "
            "numero, descricao, unidade, quantidade) values "
            "(%s, %s, 1, 'CANETA ESFEROGRAFICA AZUL', 'UNIDADE', 100) "
            "returning id", (dados["pesquisa"], dados["tenant_a"]))
        dados["item"] = c.fetchone()[0]

        c.execute(
            "insert into pesquisa_preco_referencias (item_id, tenant_id, "
            "fonte_id, id_externo, raw_hash, valor_unitario_original) "
            "values (%s, %s, 'compras_gov_precos', 'ref-1', 'hash-1', 1.23) "
            "returning id", (dados["item"], dados["tenant_a"]))
        dados["referencia"] = c.fetchone()[0]

        c.execute(
            "insert into pesquisa_preco_eventos (pesquisa_id, tenant_id, "
            "ator, tipo) values (%s, %s, %s, 'pesquisa_criada') returning id",
            (dados["pesquisa"], dados["tenant_a"],
             dados["quem"]["titular"]["id"]))
        dados["evento"] = c.fetchone()[0]

        # Pesquisa AUTÔNOMA: sem processo e sem secretaria (§17-B).
        c.execute(
            "insert into pesquisas_preco (tenant_id, auth_user_id, nome) "
            "values (%s, %s, 'Pesquisa autônoma') returning id",
            (dados["tenant_a"], dados["quem"]["sem_sec"]["id"]))
        dados["pesquisa_autonoma"] = c.fetchone()[0]

        # Pesquisa do outro município.
        c.execute(
            "insert into pesquisas_preco (tenant_id, secretaria_id, "
            "auth_user_id, nome) values (%s, %s, %s, 'De outro município') "
            "returning id",
            (dados["tenant_b"], dados["sec_b"],
             dados["quem"]["outro_ten"]["id"]))
        dados["pesquisa_b"] = c.fetchone()[0]
    return dados


# ---------------------------------------------------------------------------
# Auxiliares: cada operação numa transação própria, sempre desfeita.
# ---------------------------------------------------------------------------
def _ve(banco, cenario, rotulo, tabela, coluna, valor,
        papel_do_banco="authenticated") -> int:
    """Quantas linhas `rotulo` enxerga. RLS de leitura FILTRA, não erra."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["quem"][rotulo]["jwt"], papel_do_banco)
        c.execute(f"select count(*) from public.{tabela} "  # noqa: S608
                  f"where {coluna} = %s", (valor,))
        return c.fetchone()[0]


def _tenta(banco, cenario, rotulo, sql, params=()):
    """Executa como `rotulo` e devolve (veredito, linhas_afetadas)."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["quem"][rotulo]["jwt"])
        try:
            c.execute(sql, params)
            return PERMITIDO, c.rowcount
        except Exception as erro:  # noqa: BLE001
            return classificar_sql(erro), 0


def _como_servidor(banco, sql, params=()):
    """Executa com a conexão de superusuário — o análogo do service_role."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        try:
            c.execute(sql, params)
            return PERMITIDO, c.rowcount
        except Exception as erro:  # noqa: BLE001
            return classificar_sql(erro), 0


# ---------------------------------------------------------------------------
# A migração existe e está fechada
# ---------------------------------------------------------------------------
@requer_pg
def test_as_quatro_tabelas_nascem_com_rls_ligado(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select relname, relrowsecurity from pg_class "
                  "where relname = any(%s) and relkind = 'r'", (list(TABELAS),))
        estado = dict(c.fetchall())
    assert set(estado) == set(TABELAS), f"tabela faltando: {estado}"
    assert all(estado.values()), f"RLS desligado em alguma tabela: {estado}"


@requer_pg
def test_anon_nao_tem_grant_nenhum(banco):
    """
    A afirmação central da migração, medida no catálogo.

    Não basta não haver política para `anon`: sem grant, a tabela nem
    é alcançável. É a diferença entre "a porta está trancada" e "não
    existe porta".
    """
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select table_name, privilege_type "
                  "from information_schema.role_table_grants "
                  "where table_schema = 'public' and table_name = any(%s) "
                  "and grantee in ('anon', 'PUBLIC')", (list(TABELAS),))
        assert c.fetchall() == []


@requer_pg
def test_anon_e_recusado_na_leitura(banco, cenario):
    """
    Prova EXECUTADA, não inferida do catálogo: `anon` tentando ler leva
    42501.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["quem"]["titular"]["jwt"], "anon")
        with pytest.raises(Exception) as capturado:
            c.execute("select count(*) from public.pesquisas_preco")
    assert classificar_sql(capturado.value) == NEGADO


@requer_pg
def test_ninguem_pode_apagar(banco):
    """
    Sem DELETE em lugar nenhum — nem na trilha, nem nas referências.

    Não é esquecimento: rejeitar uma referência é mudar `status`, e uma
    pesquisa em que preço coletado some sem rastro é o oposto do que o
    módulo existe para produzir.
    """
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        # O DONO da tabela sempre tem tudo — é do PostgreSQL, não uma
        # concessão desta migração. O que importa é que nenhum papel do
        # Supabase apague: são eles que chegam pela rede.
        c.execute("select table_name, grantee "
                  "from information_schema.role_table_grants "
                  "where table_schema = 'public' and table_name = any(%s) "
                  "and privilege_type = 'DELETE' "
                  "and grantee in ('anon', 'authenticated', 'service_role', "
                  "'PUBLIC')", (list(TABELAS),))
        assert c.fetchall() == []


# ---------------------------------------------------------------------------
# Leitura — as fronteiras
# ---------------------------------------------------------------------------
@requer_pg
def test_titular_le_a_propria_pesquisa(banco, cenario):
    assert _ve(banco, cenario, "titular", "pesquisas_preco", "id",
               cenario["pesquisa"]) == 1


@requer_pg
def test_colega_da_mesma_secretaria_le(banco, cenario):
    """
    Trabalho colaborativo dentro da pasta — a mesma decisão de
    arquitetura registrada na 0020 para processos.
    """
    assert _ve(banco, cenario, "colega", "pesquisas_preco", "id",
               cenario["pesquisa"]) == 1


@requer_pg
def test_outra_secretaria_do_mesmo_municipio_nao_le(banco, cenario):
    assert _ve(banco, cenario, "outra_sec", "pesquisas_preco", "id",
               cenario["pesquisa"]) == 0


@requer_pg
def test_admin_do_municipio_le_o_tenant_inteiro(banco, cenario):
    assert _ve(banco, cenario, "admin", "pesquisas_preco", "id",
               cenario["pesquisa"]) == 1
    # inclusive a autônoma, que não é de secretaria nenhuma
    assert _ve(banco, cenario, "admin", "pesquisas_preco", "id",
               cenario["pesquisa_autonoma"]) == 1


@requer_pg
def test_admin_de_outro_municipio_nao_le(banco, cenario):
    """
    Ser administrador não atravessa município. É a fronteira que mais
    importa num produto vendido a várias prefeituras.
    """
    assert _ve(banco, cenario, "outro_ten", "pesquisas_preco", "id",
               cenario["pesquisa"]) == 0
    assert _ve(banco, cenario, "titular", "pesquisas_preco", "id",
               cenario["pesquisa_b"]) == 0


@requer_pg
def test_pesquisa_autonoma_e_legivel_pelo_dono_sem_secretaria(banco, cenario):
    """
    O caso que motivou `pode_ler_pesquisa_preco` a divergir de
    `pode_ler_processo`.

    Servidor sem vínculo de secretaria, pesquisa sem secretaria: com o
    predicado de processo, ele não leria a própria pesquisa. Com o do
    módulo, lê — e ninguém mais da casa lê.
    """
    assert _ve(banco, cenario, "sem_sec", "pesquisas_preco", "id",
               cenario["pesquisa_autonoma"]) == 1
    assert _ve(banco, cenario, "titular", "pesquisas_preco", "id",
               cenario["pesquisa_autonoma"]) == 0
    assert _ve(banco, cenario, "colega", "pesquisas_preco", "id",
               cenario["pesquisa_autonoma"]) == 0


@requer_pg
@pytest.mark.parametrize("tabela,coluna,chave", [
    ("pesquisa_preco_itens", "id", "item"),
    ("pesquisa_preco_referencias", "id", "referencia"),
    ("pesquisa_preco_eventos", "id", "evento"),
])
def test_as_filhas_herdam_o_escopo_do_pai(banco, cenario, tabela, coluna,
                                          chave):
    """
    Item, referência e evento seguem a pesquisa — e o predicado não é
    repetido em cada política, é consultado no pai.
    """
    assert _ve(banco, cenario, "titular", tabela, coluna,
               cenario[chave]) == 1
    assert _ve(banco, cenario, "outra_sec", tabela, coluna,
               cenario[chave]) == 0
    assert _ve(banco, cenario, "outro_ten", tabela, coluna,
               cenario[chave]) == 0


# ---------------------------------------------------------------------------
# Escrita — mais estreita que leitura
# ---------------------------------------------------------------------------
@requer_pg
def test_colega_le_mas_nao_edita(banco, cenario):
    """
    A separação que a 0020 aprendeu a fazer: ler a pesquisa da pasta não
    dá direito de mexer nela.

    O RLS de UPDATE FILTRA em vez de erguer erro — por isso a prova é
    "zero linhas afetadas", e não uma exceção.
    """
    veredito, linhas = _tenta(
        banco, cenario, "colega",
        "update public.pesquisas_preco set nome = 'sequestrada' "
        "where id = %s", (cenario["pesquisa"],))
    assert veredito == PERMITIDO   # o comando roda…
    assert linhas == 0             # …e não alcança linha nenhuma

    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select nome from public.pesquisas_preco where id = %s",
                  (cenario["pesquisa"],))
        assert c.fetchone()[0] == "Material de expediente"


@requer_pg
def test_titular_edita_a_propria(banco, cenario):
    veredito, linhas = _tenta(
        banco, cenario, "titular",
        "update public.pesquisas_preco set objeto = 'novo objeto' "
        "where id = %s", (cenario["pesquisa"],))
    assert (veredito, linhas) == (PERMITIDO, 1)


@requer_pg
def test_tenant_forjado_no_insert_e_negado(banco, cenario):
    """
    O cliente manda o `tenant_id`. Se a política não o conferisse contra
    o JWT, bastaria digitar o uuid do outro município.
    """
    veredito, _ = _tenta(
        banco, cenario, "titular",
        "insert into public.pesquisas_preco (tenant_id, secretaria_id, "
        "auth_user_id, nome) values (%s, %s, %s, 'forjada')",
        (cenario["tenant_b"], cenario["sec_1"],
         cenario["quem"]["titular"]["id"]))
    assert veredito == NEGADO


@requer_pg
def test_pesquisa_em_nome_de_outro_e_negada(banco, cenario):
    """Sem isto, uma pesquisa nasceria assinada por quem não a fez."""
    veredito, _ = _tenta(
        banco, cenario, "titular",
        "insert into public.pesquisas_preco (tenant_id, secretaria_id, "
        "auth_user_id, nome) values (%s, %s, %s, 'em nome do colega')",
        (cenario["tenant_a"], cenario["sec_1"],
         cenario["quem"]["colega"]["id"]))
    assert veredito == NEGADO


@requer_pg
def test_vinculo_a_processo_de_outra_secretaria_e_negado(banco, cenario):
    """
    `processo_id` não pode virar sonda: aceitar o vínculo com um processo
    que o autor não alcança revelaria a existência dele.
    """
    veredito, _ = _tenta(
        banco, cenario, "titular",
        "insert into public.pesquisas_preco (tenant_id, secretaria_id, "
        "auth_user_id, nome, processo_id) "
        "values (%s, %s, %s, 'espiã', %s)",
        (cenario["tenant_a"], cenario["sec_1"],
         cenario["quem"]["titular"]["id"], cenario["processo_alheio"]))
    assert veredito == NEGADO


@requer_pg
def test_item_em_pesquisa_alheia_e_negado(banco, cenario):
    veredito, _ = _tenta(
        banco, cenario, "colega",
        "insert into public.pesquisa_preco_itens (pesquisa_id, tenant_id, "
        "numero, descricao) values (%s, %s, 99, 'infiltrado')",
        (cenario["pesquisa"], cenario["tenant_a"]))
    assert veredito == NEGADO


@requer_pg
def test_filha_com_tenant_divergente_do_pai_e_negada(banco, cenario):
    """
    A linha ficaria pendurada numa pesquisa de um município declarando
    pertencer a outro. A política amarra os dois.
    """
    veredito, _ = _tenta(
        banco, cenario, "titular",
        "insert into public.pesquisa_preco_itens (pesquisa_id, tenant_id, "
        "numero, descricao) values (%s, %s, 98, 'tenant trocado')",
        (cenario["pesquisa"], cenario["tenant_b"]))
    assert veredito == NEGADO


@requer_pg
def test_referencia_com_tenant_divergente_do_item_e_negada(banco, cenario):
    veredito, _ = _tenta(
        banco, cenario, "titular",
        "insert into public.pesquisa_preco_referencias (item_id, tenant_id, "
        "fonte_id, id_externo, raw_hash) values (%s, %s, 'x', 'y', 'z')",
        (cenario["item"], cenario["tenant_b"]))
    assert veredito == NEGADO


@requer_pg
def test_titular_inclui_referencia_no_proprio_item(banco, cenario):
    veredito, linhas = _tenta(
        banco, cenario, "titular",
        "insert into public.pesquisa_preco_referencias (item_id, tenant_id, "
        "fonte_id, id_externo, raw_hash, valor_unitario_original) "
        "values (%s, %s, 'pncp', 'ref-nova', 'hash-novo', 2.50)",
        (cenario["item"], cenario["tenant_a"]))
    assert (veredito, linhas) == (PERMITIDO, 1)


# ---------------------------------------------------------------------------
# Trilha — append-only para valer
# ---------------------------------------------------------------------------
@requer_pg
def test_evento_com_ator_forjado_e_negado(banco, cenario):
    """Rede de proteção no gatilho, além da política."""
    veredito, _ = _tenta(
        banco, cenario, "titular",
        "insert into public.pesquisa_preco_eventos (pesquisa_id, tenant_id, "
        "ator, tipo) values (%s, %s, %s, 'referencia_excluida')",
        (cenario["pesquisa"], cenario["tenant_a"],
         cenario["quem"]["colega"]["id"]))
    assert veredito == NEGADO


@requer_pg
def test_evento_automatico_sem_ator_e_carimbado_com_quem_operava(banco,
                                                                 cenario):
    """
    O defeito que a releitura pegou.

    O motor roda dentro da sessão do usuário e não assina nada. Com o
    gatilho recusando qualquer `ator` diferente de `auth.uid()` — NULL
    incluído —, TODO evento automático levaria 42501, e a busca
    quebraria ao tentar registrar que terminou.

    Aceitar o nulo também não serve: trilha sem ator não diz quem estava
    operando, e "alterações humanas" é item do §34. O gatilho carimba.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["quem"]["titular"]["jwt"])
        c.execute(
            "insert into public.pesquisa_preco_eventos (pesquisa_id, "
            "tenant_id, tipo, automatico) values "
            "(%s, %s, 'busca_concluida', true) returning ator",
            (cenario["pesquisa"], cenario["tenant_a"]))
        assert str(c.fetchone()[0]) == cenario["quem"]["titular"]["id"]


@requer_pg
def test_servidor_comum_registra_o_proprio_ato(banco, cenario):
    """
    O motivo de a trilha ser própria e não `governanca_eventos`: lá o
    servidor comum tem `papel_governanca` nulo e nenhum evento
    permitido — não conseguiria registrar a exclusão que acabou de
    fazer.
    """
    veredito, linhas = _tenta(
        banco, cenario, "titular",
        "insert into public.pesquisa_preco_eventos (pesquisa_id, tenant_id, "
        "ator, tipo, descricao) values (%s, %s, %s, 'referencia_excluida', "
        "'fora da curva')",
        (cenario["pesquisa"], cenario["tenant_a"],
         cenario["quem"]["titular"]["id"]))
    assert (veredito, linhas) == (PERMITIDO, 1)


@requer_pg
@pytest.mark.parametrize("comando", [
    "update public.pesquisa_preco_eventos set descricao = 'reescrito' "
    "where id = %s",
    "delete from public.pesquisa_preco_eventos where id = %s",
])
def test_trilha_e_imutavel_ate_para_quem_atravessa_o_rls(banco, cenario,
                                                        comando):
    """
    A prova que separa "append-only" de "append-only de mentira".

    Grants e políticas param `authenticated`. Quem opera hoje é a
    credencial de servidor, que atravessa RLS por definição — aqui
    representada pela conexão de superusuário. O gatilho recusa os dois.
    """
    veredito, _ = _como_servidor(banco, comando, (cenario["evento"],))
    assert veredito == NEGADO


# ---------------------------------------------------------------------------
# Idempotência (§43)
# ---------------------------------------------------------------------------
@requer_pg
def test_reexecutar_nao_duplica_referencia(banco, cenario):
    """
    A garantia central: a mesma referência da mesma fonte no mesmo item
    entra uma vez só. Sem ela, "pesquisar de novo" dobraria a amostra e,
    com ela, a estatística.
    """
    # A recusa tem de vir da UNICIDADE (23505), e não de autorização:
    # o titular pode escrever no próprio item. Conferir o sqlstate é o
    # que separa "a chave única funcionou" de "a política me barrou".
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["quem"]["titular"]["jwt"])
        with pytest.raises(Exception) as capturado:
            c.execute(
                "insert into public.pesquisa_preco_referencias (item_id, "
                "tenant_id, fonte_id, id_externo, raw_hash) values "
                "(%s, %s, 'compras_gov_precos', 'ref-1', 'hash-1')",
                (cenario["item"], cenario["tenant_a"]))
    assert getattr(capturado.value, "sqlstate", None) == UNICIDADE_VIOLADA

    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select count(*) from public.pesquisa_preco_referencias "
                  "where item_id = %s and fonte_id = 'compras_gov_precos' "
                  "and id_externo = 'ref-1'", (cenario["item"],))
        assert c.fetchone()[0] == 1


@requer_pg
def test_mesma_referencia_em_itens_diferentes_e_permitida(banco, cenario):
    """
    A unicidade é por ITEM, e tem de ser: dois itens da mesma pesquisa
    podem legitimamente citar a mesma contratação.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("insert into public.pesquisa_preco_itens (pesquisa_id, "
                  "tenant_id, numero, descricao) values (%s, %s, 2, 'outro') "
                  "returning id", (cenario["pesquisa"], cenario["tenant_a"]))
        outro_item = c.fetchone()[0]
        c.execute("insert into public.pesquisa_preco_referencias (item_id, "
                  "tenant_id, fonte_id, id_externo, raw_hash) values "
                  "(%s, %s, 'compras_gov_precos', 'ref-1', 'hash-1')",
                  (outro_item, cenario["tenant_a"]))
        assert c.rowcount == 1


@requer_pg
def test_evento_com_a_mesma_chave_entra_uma_vez(banco, cenario):
    """
    Reexecutar a rodada 7 não gera dois `busca_concluida`.

    A recusa tem de ser POR UNICIDADE (23505). Aceitar qualquer exceção
    deixaria o teste passar por um erro de digitação no SQL, e aí ele
    provaria o contrário do que promete.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        comando = ("insert into public.pesquisa_preco_eventos (pesquisa_id, "
                   "tenant_id, tipo, idempotency_key, automatico) values "
                   "(%s, %s, 'busca_concluida', 'rodada-7', true)")
        c.execute(comando, (cenario["pesquisa"], cenario["tenant_a"]))
        assert c.rowcount == 1
        with pytest.raises(Exception) as capturado:
            c.execute(comando, (cenario["pesquisa"], cenario["tenant_a"]))
    assert getattr(capturado.value, "sqlstate", None) == UNICIDADE_VIOLADA


@requer_pg
def test_chave_vazia_nao_colide(banco, cenario):
    """
    O índice é PARCIAL de propósito: a criação interativa não tem chave
    de idempotência, e duas pesquisas sem chave não podem colidir.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        for nome in ("sem chave 1", "sem chave 2"):
            c.execute("insert into public.pesquisas_preco (tenant_id, "
                      "auth_user_id, nome) values (%s, %s, %s)",
                      (cenario["tenant_a"],
                       cenario["quem"]["titular"]["id"], nome))
            assert c.rowcount == 1


@requer_pg
def test_a_mesma_chave_em_municipios_diferentes_nao_colide(banco, cenario):
    """A idempotência é por tenant — nunca global."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        for tenant, dono in ((cenario["tenant_a"], "titular"),
                             (cenario["tenant_b"], "outro_ten")):
            c.execute("insert into public.pesquisas_preco (tenant_id, "
                      "auth_user_id, nome, idempotency_key) values "
                      "(%s, %s, 'mesma chave', 'import-2026-01')",
                      (tenant, cenario["quem"][dono]["id"]))
            assert c.rowcount == 1


# ---------------------------------------------------------------------------
# Versionamento (§44)
# ---------------------------------------------------------------------------
@requer_pg
def test_duas_revisoes_com_o_mesmo_numero_sao_recusadas(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        with pytest.raises(Exception) as capturado:
            c.execute(
                "insert into public.pesquisas_preco (tenant_id, "
                "auth_user_id, nome, versao, raiz_id) values "
                "(%s, %s, 'revisão duplicada', 1, %s)",
                (cenario["tenant_a"], cenario["quem"]["titular"]["id"],
                 cenario["pesquisa"]))
    assert getattr(capturado.value, "sqlstate", None) == UNICIDADE_VIOLADA


@requer_pg
def test_a_revisao_copia_a_arvore_inteira(banco, cenario):
    """
    Revisar cria uma pesquisa NOVA com cabeçalho, itens e referências.

    Meia cópia não serve: se as referências ficassem na revisão antiga,
    a cesta anterior sumiria assim que alguém mudasse um status — que é
    exatamente o histórico que o §44 manda preservar.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["quem"]["titular"]["jwt"])
        c.execute("select public.revisar_pesquisa_preco(%s, %s)",
                  (cenario["pesquisa"], "troca de metodologia"))
        nova = c.fetchone()[0]

        voltar_a_ser_servidor(c)
        c.execute("select versao, revisao_de, raiz_id, estado, auth_user_id, "
                  "motivo_da_revisao from public.pesquisas_preco where id = %s",
                  (nova,))
        versao, revisao_de, raiz, estado, dono, motivo = c.fetchone()
        assert versao == 2
        assert str(revisao_de) == str(cenario["pesquisa"])
        assert str(raiz) == str(cenario["pesquisa"])
        assert estado == "review"
        assert motivo == "troca de metodologia"
        # O AUTOR é preservado. É por isto que a função é definer: a
        # política de INSERT exigiria `auth_user_id = auth.uid()`, e a
        # revisão passaria a pesquisa para o nome de quem revisou.
        assert str(dono) == cenario["quem"]["titular"]["id"]

        c.execute("select count(*) from public.pesquisa_preco_itens "
                  "where pesquisa_id = %s", (nova,))
        assert c.fetchone()[0] == 1

        c.execute("select count(*) from public.pesquisa_preco_referencias r "
                  "join public.pesquisa_preco_itens i on i.id = r.item_id "
                  "where i.pesquisa_id = %s", (nova,))
        assert c.fetchone()[0] == 1

        # E a revisão fica registrada na trilha da linha nova.
        c.execute("select tipo, ator from public.pesquisa_preco_eventos "
                  "where pesquisa_id = %s", (nova,))
        tipo, ator = c.fetchone()
        assert tipo == "pesquisa_revisada"
        assert str(ator) == cenario["quem"]["titular"]["id"]


@requer_pg
def test_a_revisao_nao_transfere_o_dono_quando_o_admin_revisa(banco, cenario):
    """
    O admin pode revisar; o trabalho continua sendo de quem o fez.

    Sem isto, uma pesquisa autônoma revisada pelo admin sairia do
    alcance do próprio autor — que não tem secretaria para alcançá-la
    de volta.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["quem"]["admin"]["jwt"])
        c.execute("select public.revisar_pesquisa_preco(%s, %s)",
                  (cenario["pesquisa_autonoma"], "ajuste do gabinete"))
        nova = c.fetchone()[0]

        # Quem revisou aparece na TRILHA; quem fez continua no cabeçalho.
        voltar_a_ser_servidor(c)
        c.execute("select auth_user_id from public.pesquisas_preco "
                  "where id = %s", (nova,))
        assert str(c.fetchone()[0]) == cenario["quem"]["sem_sec"]["id"]
        c.execute("select ator from public.pesquisa_preco_eventos "
                  "where pesquisa_id = %s", (nova,))
        assert str(c.fetchone()[0]) == cenario["quem"]["admin"]["id"]


@requer_pg
@pytest.mark.parametrize("rotulo", ["colega", "outra_sec", "outro_ten"])
def test_quem_nao_escreve_nao_revisa(banco, cenario, rotulo):
    """
    A função é SECURITY DEFINER — atravessa o RLS por construção. A
    autorização volta explicitamente, com o mesmo predicado das
    políticas, e é isto que o teste mede.

    `colega` é o caso interessante: ele LÊ a pesquisa (mesma secretaria)
    e mesmo assim não pode revisá-la.
    """
    veredito, _ = _tenta(
        banco, cenario, rotulo,
        "select public.revisar_pesquisa_preco(%s, 'tentativa')",
        (cenario["pesquisa"],))
    assert veredito == NEGADO


@requer_pg
def test_pesquisa_inexistente_e_pesquisa_alheia_respondem_igual(banco,
                                                                cenario):
    """
    Mensagens diferentes fariam da função uma sonda: bastaria comparar
    a resposta para descobrir quais pesquisas existem nas outras pastas.
    """
    mensagens = []
    # Uma transação por tentativa: a primeira exceção aborta a
    # transação, e insistir nela mediria o erro do Postgres, não o da
    # função.
    for alvo in (cenario["pesquisa_b"], str(uuid.uuid4())):
        with banco.transaction(force_rollback=True), banco.cursor() as c:
            como(c, cenario["quem"]["colega"]["jwt"])
            with pytest.raises(Exception) as capturado:
                c.execute("select public.revisar_pesquisa_preco(%s, '')",
                          (alvo,))
        assert classificar_sql(capturado.value) == NEGADO
        mensagens.append(str(capturado.value).splitlines()[0])
    assert mensagens[0] == mensagens[1], mensagens


@requer_pg
def test_pesquisa_arquivada_nao_admite_revisao(banco, cenario):
    """
    `archived` é terminal na máquina de estados. Revisar a partir dela
    desfaria a decisão de arquivar sem que ninguém a revogasse.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("update public.pesquisas_preco set estado = 'archived' "
                  "where id = %s", (cenario["pesquisa"],))
        como(c, cenario["quem"]["titular"]["jwt"])
        with pytest.raises(Exception) as capturado:
            c.execute("select public.revisar_pesquisa_preco(%s, '')",
                      (cenario["pesquisa"],))
    assert classificar_sql(capturado.value) == NEGADO


@requer_pg
def test_o_historico_sai_por_uma_consulta_so(banco, cenario):
    """
    Revisar cria linha nova e não apaga a anterior. `coalesce(raiz_id,
    id)` devolve a pesquisa lógica inteira, da raiz à vigente.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        anterior = cenario["pesquisa"]
        for versao in (2, 3):
            c.execute(
                "insert into public.pesquisas_preco (tenant_id, "
                "secretaria_id, auth_user_id, nome, versao, revisao_de, "
                "raiz_id, motivo_da_revisao) values "
                "(%s, %s, %s, 'Material de expediente', %s, %s, %s, "
                "'troca de metodologia') returning id",
                (cenario["tenant_a"], cenario["sec_1"],
                 cenario["quem"]["titular"]["id"], versao, anterior,
                 cenario["pesquisa"]))
            anterior = c.fetchone()[0]

        c.execute("select versao from public.pesquisas_preco "
                  "where coalesce(raiz_id, id) = %s order by versao",
                  (cenario["pesquisa"],))
        assert [linha[0] for linha in c.fetchall()] == [1, 2, 3]


# ---------------------------------------------------------------------------
# O banco e o Python falam o mesmo vocabulário
# ---------------------------------------------------------------------------
def _valores_do_check(banco, tabela: str, restricao: str) -> set[str]:
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(
            "select pg_get_constraintdef(con.oid) from pg_constraint con "
            "join pg_class rel on rel.oid = con.conrelid "
            "where rel.relname = %s and con.contype = 'c' "
            "and pg_get_constraintdef(con.oid) like %s",
            (tabela, f"%{restricao}%"))
        linhas = c.fetchall()
    assert linhas, f"CHECK de {restricao} não encontrado em {tabela}"
    # O PostgreSQL devolve a definição normalizada, com cada literal
    # anotado: ARRAY['draft'::text, 'queued'::text, …].
    return set(re.findall(r"'([^']+)'::text", linhas[0][0]))


@requer_pg
@pytest.mark.parametrize("tabela,coluna,enumeracao", [
    ("pesquisas_preco", "estado", estados.EstadoPesquisa),
    ("pesquisa_preco_itens", "estado", estados.EstadoItem),
    ("pesquisa_preco_referencias", "status", StatusReferencia),
])
def test_o_check_do_banco_e_o_enum_do_python_nao_divergem(banco, tabela,
                                                          coluna, enumeracao):
    """
    Um estado que o Python produz e o banco recusa vira erro em
    produção; um que o banco aceita e o Python não conhece vira linha
    ilegível. Os dois vocabulários são conferidos um contra o outro.
    """
    do_banco = _valores_do_check(banco, tabela, coluna)
    do_python = {membro.value for membro in enumeracao}
    assert do_banco == do_python, (
        f"{tabela}.{coluna}: banco={sorted(do_banco)} "
        f"python={sorted(do_python)}")


@requer_pg
def test_a_revisao_preserva_a_natureza_do_valor(banco, cenario):
    """
    Defeito encontrado lendo a RPC contra o modelo novo, e ele era
    silencioso — o pior tipo.

    `natureza_valor` tem default `'outro'` no schema, e `outro` não é
    natureza comparável. A RPC copiava a árvore inteira SEM esta coluna,
    então toda referência da revisão nascia `'outro'`: a cesta de todos
    os itens esvaziava, cada item virava `incomplete`, e o motivo estava
    num default de schema — invisível na tela, no relatório e no diff.
    Revisar uma pesquisa para trocar a metodologia teria zerado o
    trabalho inteiro.

    A prova grava naturezas DIFERENTES e exige que a revisão as
    reproduza uma a uma: contar linhas não pegaria o defeito, porque a
    contagem estava certa.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        for ident, natureza in (("nat-praticado", "praticado"),
                                ("nat-estimado", "estimado_origem"),
                                ("nat-homologado", "homologado")):
            c.execute(
                "insert into public.pesquisa_preco_referencias "
                "(item_id, tenant_id, fonte_id, id_externo, raw_hash, "
                " valor_unitario_original, natureza_valor) "
                "values (%s, %s, 'compras_gov_itens', %s, %s, 1.50, %s)",
                (cenario["item"], cenario["tenant_a"], ident,
                 f"hash-{ident}", natureza))

        como(c, cenario["quem"]["titular"]["jwt"])
        c.execute("select public.revisar_pesquisa_preco(%s, %s)",
                  (cenario["pesquisa"], "conferir natureza"))
        nova = c.fetchone()[0]

        voltar_a_ser_servidor(c)
        c.execute(
            "select r.id_externo, r.natureza_valor "
            "  from public.pesquisa_preco_referencias r "
            "  join public.pesquisa_preco_itens i on i.id = r.item_id "
            " where i.pesquisa_id = %s and r.id_externo like 'nat-%%' "
            " order by r.id_externo", (nova,))
        copiadas = dict(c.fetchall())

    assert copiadas == {
        "nat-estimado": "estimado_origem",
        "nat-homologado": "homologado",
        "nat-praticado": "praticado",
    }, "a revisão perdeu a natureza e esvaziaria a cesta"


@requer_pg
def test_a_natureza_do_valor_e_restrita_pelo_banco(banco, cenario):
    """
    O CHECK não é decorativo: o app e o banco compartilham a lista, e
    natureza que o app não conhece não entra. Sem isto, um valor
    inventado passaria e a comparação `natureza in NATUREZAS_COMPARAVEIS`
    silenciosamente o deixaria de fora sem ninguém saber por quê.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        with pytest.raises(Exception) as capturado:
            c.execute(
                "insert into public.pesquisa_preco_referencias "
                "(item_id, tenant_id, fonte_id, id_externo, raw_hash, "
                " natureza_valor) values (%s, %s, 'x', 'y', 'z', 'inventada')",
                (cenario["item"], cenario["tenant_a"]))
    assert getattr(capturado.value, "sqlstate", None) == "23514"


@requer_pg
def test_a_natureza_nasce_outro_e_nao_praticado(banco, cenario):
    """
    O default seguro. Se fosse `'praticado'`, um adapter que esquecesse
    de classificar entregaria valor estimado como preço pago — e o erro
    seria por OMISSÃO, que é o mais fácil de cometer.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(
            "insert into public.pesquisa_preco_referencias "
            "(item_id, tenant_id, fonte_id, id_externo, raw_hash) "
            "values (%s, %s, 'x', 'sem-natureza', 'h') "
            "returning natureza_valor",
            (cenario["item"], cenario["tenant_a"]))
        assert c.fetchone()[0] == "outro"
