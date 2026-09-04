"""
Ensaio EXECUTADO da camada SQL — não mais pulado.

As provas de autorização viviam todas atrás de um `skipif`: exigiam um
projeto Supabase descartável que não existia. Uma matriz de 28 tabelas
que ninguém executou é uma promessa, não uma contenção — e um relatório
cheio de "pulou" é indistinguível de um relatório cheio de "passou"
para quem lê rápido.

Aqui a 0020 é aplicada sobre o schema REAL do repositório num
PostgreSQL local descartável, e as provas RODAM. O JWT é injetado em
`request.jwt.claims`, que é exatamente o que o PostgREST faz a cada
requisição.

FRONTEIRA, dita aqui e no laudo: isto prova o BANCO — políticas,
`SECURITY DEFINER`, matriz papel×evento, resolução de escopo, GRANTs.
Não prova PostgREST, GoTrue nem `supabase-py`. As provas de
`test_seguranca_contencao.py` que dependem daquela camada continuam
pulando, e continuam pulando de propósito.

Como rodar:

    GOVDOCS_ENSAIO_PG_DSN="postgresql://postgres@/ensaio?host=/tmp/pgens" \\
        python -m pytest tests/test_ensaio_sql_local.py
"""

from __future__ import annotations

import json
import os
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

from tests.conftest import exigir_ensaio_sql  # noqa: E402

DSN = os.getenv("GOVDOCS_ENSAIO_PG_DSN", "")

# `usefixtures`, e não `skipif`: com `GOVDOCS_EXIGIR_ENSAIO_SQL=1` a
# ausência do banco de ensaio precisa FALHAR, e um `skipif` decidiria
# antes que o portão pudesse opinar.
requer_pg = pytest.mark.usefixtures("ensaio_sql")

# O vocabulário do veredito — PERMITIDO/NEGADO/INCONCLUSIVO e o
# classificador — mora em `scripts/ensaio_local.py` desde que passou a
# ser usado também pelas provas da pesquisa de preços. Uma cópia só.


@pytest.fixture(scope="module")
def banco():
    """
    Banco descartável com o schema real e a 0020 aplicada.

    Falha de preparação FALHA — não pula. Um schema pela metade mede
    outra coisa e produz verde sobre coisa nenhuma.
    """
    exigir_ensaio_sql()
    import psycopg

    exigir_dsn_local(DSN)
    # Banco NOVO a cada execução: herdar estado da rodada anterior faz
    # o ensaio medir outra coisa, e depender de limpeza manual faz ele
    # deixar de ser reprodutível.
    dsn, nome = criar_banco_descartavel(DSN)
    try:
        with psycopg.connect(dsn, autocommit=True) as conexao:
            try:
                preparar(conexao)
            except EnsaioLocal as erro:
                pytest.fail(f"preparação do ensaio SQL falhou: {erro}")
            yield conexao
    finally:
        descartar_banco(DSN, nome)


@pytest.fixture(scope="module")
def cenario(banco):
    """
    Um tenant, duas secretarias, e uma trilha completa por fronteira.

    Montado com a conexão de superusuário — é o análogo da credencial
    de servidor, e é assim que o cenário é criado no ensaio remoto.
    """
    dados: dict = {}
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)

        c.execute("insert into tenants (slug, nome) values "
                  "(%s, 'Ensaio A') returning id",
                  (f"ensaio-a-{uuid.uuid4().hex[:8]}",))
        dados["tenant_a"] = c.fetchone()[0]
        c.execute("insert into tenants (slug, nome) values "
                  "(%s, 'Ensaio B') returning id",
                  (f"ensaio-b-{uuid.uuid4().hex[:8]}",))
        dados["tenant_b"] = c.fetchone()[0]

        for chave, tenant in (("sec_1", "tenant_a"), ("sec_2", "tenant_a"),
                              ("sec_outro", "tenant_b")):
            c.execute("insert into secretarias (tenant_id, nome) values "
                      "(%s, %s) returning id", (dados[tenant], chave))
            dados[chave] = c.fetchone()[0]

        # identidades: cada uma prova UMA fronteira
        desenho = (
            ("titular",    "usuario", None,               "tenant_a", "sec_1"),
            ("colega",     "usuario", None,               "tenant_a", "sec_1"),
            ("outra_sec",  "usuario", None,               "tenant_a", "sec_2"),
            ("admin",      "admin",   "admin_municipal",  "tenant_a", "sec_1"),
            ("revisor_a",  "usuario", "revisor_juridico", "tenant_a", "sec_1"),
            ("revisor_b",  "usuario", "revisor_juridico", "tenant_a", "sec_2"),
            ("publicador", "usuario", "publicador",       "tenant_a", "sec_1"),
            ("auditor",    "usuario", "auditor",          "tenant_a", "sec_1"),
            ("outro_ten",  "usuario", "admin_municipal",  "tenant_b",
             "sec_outro"),
        )
        dados["quem"] = {}
        for rotulo, papel, papel_gov, tenant, secretaria in desenho:
            metadados = {"papel": papel, "tenant_id": str(dados[tenant]),
                         "secretaria_id": str(dados[secretaria])}
            if papel_gov:
                metadados["papel_governanca"] = papel_gov
            c.execute("insert into auth.users (email, raw_app_meta_data) "
                      "values (%s, %s) returning id",
                      (f"{rotulo}-{uuid.uuid4().hex[:8]}@ensaio.invalid",
                       json.dumps(metadados)))
            auth_id = c.fetchone()[0]
            c.execute(
                "insert into usuarios (nome, login, senha_hash, papel, "
                "tenant_id, secretaria_id, auth_user_id) "
                "values (%s, %s, 'sem-uso', %s, %s, %s, %s)",
                (rotulo, f"{rotulo}-{uuid.uuid4().hex[:8]}", papel,
                 dados[tenant], dados[secretaria], auth_id))
            dados["quem"][rotulo] = {
                "id": str(auth_id),
                "jwt": claims(str(auth_id), papel, str(dados[tenant]),
                              str(dados[secretaria]), papel_gov),
            }

        # três trilhas completas: artefato → versão → aprovação
        for sufixo, tenant, secretaria in (
                ("", "tenant_a", "sec_1"),
                ("_b", "tenant_a", "sec_2"),
                ("_outro_tenant", "tenant_b", "sec_outro")):
            c.execute(
                "insert into governanca_artefatos "
                "(tenant_id, secretaria_id, tipo_artefato, chave_estavel) "
                "values (%s, %s, 'clausula', %s) returning id",
                (dados[tenant], dados[secretaria],
                 f"ensaio-{uuid.uuid4().hex[:8]}"))
            dados[f"artefato{sufixo}"] = c.fetchone()[0]
            c.execute("insert into governanca_versoes (artefato_id) "
                      "values (%s) returning id", (dados[f"artefato{sufixo}"],))
            dados[f"versao{sufixo}"] = c.fetchone()[0]
            c.execute(
                "insert into governanca_aprovacoes "
                "(tenant_id, entidade_tipo, entidade_id) "
                "values (%s, 'versao', %s) returning id",
                (dados[tenant], dados[f"versao{sufixo}"]))
            dados[f"aprovacao{sufixo}"] = c.fetchone()[0]

        # `entidade_tipo` é `text not null` sem CHECK: a tabela aceita
        # qualquer string, e é por isso que a matriz da RPC precisa ser
        # fechada
        c.execute("insert into processos (orgao, objeto, tenant_id, "
                  "secretaria_id, auth_user_id) values "
                  "('ensaio', 'ensaio', %s, %s, %s) returning id",
                  (dados["tenant_a"], dados["sec_1"],
                   dados["quem"]["titular"]["id"]))
        dados["processo"] = c.fetchone()[0]
        c.execute("insert into governanca_aprovacoes "
                  "(tenant_id, entidade_tipo, entidade_id) "
                  "values (%s, 'processo', %s) returning id",
                  (dados["tenant_a"], dados["processo"]))
        dados["aprovacao_tipo_desconhecido"] = c.fetchone()[0]

        c.execute("insert into governanca_publicacoes (tenant_id) "
                  "values (%s) returning id", (dados["tenant_a"],))
        dados["publicacao"] = c.fetchone()[0]
    return dados


def _registrar(banco, cenario, rotulo, tipo, entidade, alvo):
    """
    Chama a RPC como `rotulo`. Devolve (veredito, id_do_evento).

    Cada chamada roda na PRÓPRIA transação e desfaz: assim uma recusa
    não deixa estado e o `set local role` não vaza para a prova
    seguinte.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["quem"][rotulo]["jwt"])
        try:
            c.execute(
                "select public.registrar_evento_governanca(%s, %s, %s, %s)",
                (tipo, entidade, alvo, "{}"))
            return PERMITIDO, c.fetchone()[0]
        except Exception as erro:  # noqa: BLE001
            return classificar_sql(erro), None


def _eventos_de(banco, entidade_id) -> list:
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select id, ator, tipo_evento from governanca_eventos "
                  "where entidade_id = %s", (entidade_id,))
        return c.fetchall()


EVENTOS_DE_APROVACAO = ("aprovacao_registrada", "aprovacao_revogada")


# ---------------------------------------------------------------------------
# A migração aplica
# ---------------------------------------------------------------------------
@requer_pg
def test_a_0020_aplica_sobre_o_schema_real(banco):
    """
    Antes deste ensaio ninguém sabia se a 0020 sequer EXECUTA. Uma
    migração que nunca rodou é um texto, não uma migração.
    """
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select count(*) from pg_proc p join pg_namespace n "
                  "on n.oid = p.pronamespace where n.nspname = 'public' "
                  "and p.proname in ('registrar_evento_governanca', "
                  "'aprovacao_no_escopo', 'papel_alcanca_o_tenant', "
                  "'eventos_permitidos_ao_papel', 'tipos_de_evento_validos')")
        assert c.fetchone()[0] == 5


@requer_pg
def test_toda_tabela_privada_tem_rls_ligado(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select relname from pg_class c "
                  "join pg_namespace n on n.oid = c.relnamespace "
                  "where n.nspname = 'public' and c.relkind = 'r' "
                  "and not c.relrowsecurity")
        sem_rls = [linha[0] for linha in c.fetchall()]
    assert not sem_rls, f"tabelas sem RLS: {sem_rls}"


@requer_pg
@pytest.mark.parametrize("tabela", ["processos", "usuarios", "config_app",
                                    "governanca_eventos", "secretarias",
                                    "governanca_artefatos"])
def test_anon_nao_le_tabela_privada(banco, cenario, tabela):
    """
    Duas formas de fechar, ambas aceitas: negação por GRANT (a consulta
    nem roda) ou zero linhas por RLS. O que NÃO se aceita é linha
    voltando.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        c.execute("set local role anon")
        try:
            c.execute(f"select count(*) from {tabela}")
            assert c.fetchone()[0] == 0, f"anon leu {tabela}"
        except Exception as erro:  # noqa: BLE001
            assert classificar_sql(erro) == NEGADO, (tabela, erro)


# ---------------------------------------------------------------------------
# P2 — o escopo da aprovação, EXECUTADO
# ---------------------------------------------------------------------------
@requer_pg
@pytest.mark.parametrize("tipo", EVENTOS_DE_APROVACAO)
def test_revisor_nao_alcanca_aprovacao_de_outra_secretaria(banco, cenario,
                                                           tipo):
    """
    O P2 exato, agora rodando. `revisor_a` tem papel legítimo e enxerga
    `governanca_aprovacoes` do tenant inteiro — portanto CONHECE o id
    da aprovação da secretaria 2. Conhecer o id não é autorização.
    """
    antes = len(_eventos_de(banco, cenario["aprovacao_b"]))
    veredito, _ = _registrar(banco, cenario, "revisor_a", tipo,
                             "aprovacao", cenario["aprovacao_b"])
    assert veredito == NEGADO, f"{tipo}: {veredito}"
    assert len(_eventos_de(banco, cenario["aprovacao_b"])) == antes, (
        "recusa que ainda assim gravou não é contenção")


@requer_pg
@pytest.mark.parametrize("tipo", EVENTOS_DE_APROVACAO)
def test_a_fronteira_vale_nos_dois_sentidos(banco, cenario, tipo):
    """Sem isto, a regra seria favorecimento da secretaria 1."""
    veredito, _ = _registrar(banco, cenario, "revisor_b", tipo,
                             "aprovacao", cenario["aprovacao"])
    assert veredito == NEGADO, f"{tipo}: {veredito}"


@requer_pg
@pytest.mark.parametrize("tipo", EVENTOS_DE_APROVACAO)
def test_revisor_da_propria_secretaria_registra(banco, cenario, tipo):
    veredito, evento = _registrar(banco, cenario, "revisor_b", tipo,
                                  "aprovacao", cenario["aprovacao_b"])
    assert veredito == PERMITIDO, f"{tipo}: {veredito}"
    assert evento is not None


@requer_pg
@pytest.mark.parametrize("tipo", EVENTOS_DE_APROVACAO)
def test_admin_municipal_alcanca_as_duas_secretarias(banco, cenario, tipo):
    """
    O alcance tenant-wide é decisão registrada, não descuido: o admin
    está lotado na secretaria 1 e registra sobre a aprovação da 2.
    """
    veredito, _ = _registrar(banco, cenario, "admin", tipo,
                             "aprovacao", cenario["aprovacao_b"])
    assert veredito == PERMITIDO, f"{tipo}: {veredito}"


@requer_pg
@pytest.mark.parametrize("rotulo", ["revisor_a", "revisor_b", "admin"])
@pytest.mark.parametrize("tipo", EVENTOS_DE_APROVACAO)
def test_aprovacao_de_outro_tenant_e_recusada_para_todos(banco, cenario,
                                                         rotulo, tipo):
    """Alcançar O tenant é diferente de alcançar QUALQUER tenant."""
    veredito, _ = _registrar(banco, cenario, rotulo, tipo, "aprovacao",
                             cenario["aprovacao_outro_tenant"])
    assert veredito == NEGADO, f"{rotulo}/{tipo}: {veredito}"


@requer_pg
@pytest.mark.parametrize("rotulo", ["revisor_a", "admin"])
def test_aprovacao_de_tipo_desconhecido_e_recusada(banco, cenario, rotulo):
    """
    Um `else` permissivo na matriz tipo→tabela seria pior que o P2
    original: bastaria criar a aprovação com um tipo inventado para
    contornar a fronteira. A coluna aceita qualquer string.
    """
    veredito, _ = _registrar(banco, cenario, rotulo, "aprovacao_registrada",
                             "aprovacao",
                             cenario["aprovacao_tipo_desconhecido"])
    assert veredito == NEGADO, f"{rotulo}: {veredito}"


# ---------------------------------------------------------------------------
# Autoridade — identidade não basta
# ---------------------------------------------------------------------------
@requer_pg
def test_sem_papel_de_governanca_nao_registra(banco, cenario):
    """Ser dono do processo não dá competência de governança."""
    veredito, _ = _registrar(banco, cenario, "titular", "artefato_criado",
                             "artefato", cenario["artefato"])
    assert veredito == NEGADO, veredito


@requer_pg
def test_auditor_nao_registra_evento_algum(banco, cenario):
    veredito, _ = _registrar(banco, cenario, "auditor", "artefato_criado",
                             "artefato", cenario["artefato"])
    assert veredito == NEGADO, veredito


@requer_pg
@pytest.mark.parametrize("rotulo,tipo,entidade,esperado", [
    ("revisor_a", "aprovacao_registrada", "aprovacao", PERMITIDO),
    ("revisor_a", "publicacao_registrada", "publicacao", NEGADO),
    ("publicador", "publicacao_registrada", "publicacao", PERMITIDO),
    ("publicador", "aprovacao_registrada", "aprovacao", NEGADO),
])
def test_cada_papel_registra_so_os_eventos_da_sua_matriz(
        banco, cenario, rotulo, tipo, entidade, esperado):
    """
    Revisor aprova e não publica; publicador publica e não aprova. Sem
    a matriz, ter QUALQUER papel daria acesso a TODOS os atos.
    """
    alvo = cenario["publicacao"] if entidade == "publicacao" \
        else cenario["aprovacao"]
    veredito, _ = _registrar(banco, cenario, rotulo, tipo, entidade, alvo)
    assert veredito == esperado, f"{rotulo}/{tipo}: {veredito}"


@requer_pg
def test_o_publicador_tambem_fica_preso_a_sua_secretaria(banco, cenario):
    """A restrição de secretaria vale para todo papel local."""
    veredito, _ = _registrar(banco, cenario, "publicador", "versao_publicada",
                             "versao", cenario["versao_b"])
    assert veredito == NEGADO, veredito


# ---------------------------------------------------------------------------
# O ator é o autenticado, e a trilha só se escreve pela RPC
# ---------------------------------------------------------------------------
@requer_pg
def test_o_ator_gravado_e_exatamente_o_auth_uid(banco, cenario):
    """
    `ator` era parâmetro. Assinatura confiável de um ato que a pessoa
    não praticou é uma confissão falsa bem redigida.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["quem"]["admin"]["jwt"])
        c.execute("select public.registrar_evento_governanca("
                  "'artefato_criado', 'artefato', %s, '{}')",
                  (cenario["artefato"],))
        evento = c.fetchone()[0]
        voltar_a_ser_servidor(c)
        c.execute("select ator from governanca_eventos where id = %s",
                  (evento,))
        gravado = c.fetchone()[0]
    assert str(gravado) == cenario["quem"]["admin"]["id"]


@requer_pg
def test_insert_direto_na_trilha_e_negado(banco, cenario):
    """
    A RPC não vale nada se a tabela continuar gravável por fora: seria
    a mesma escrita, sem nenhuma das checagens.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["quem"]["admin"]["jwt"])
        try:
            c.execute(
                "insert into governanca_eventos (tenant_id, ator, "
                "tipo_evento, entidade_tipo, entidade_id, payload) "
                "values (%s, %s, 'aprovacao_registrada', 'aprovacao', "
                "%s, '{}')",
                (cenario["tenant_a"], str(uuid.uuid4()),
                 cenario["aprovacao"]))
            veredito = PERMITIDO
        except Exception as erro:  # noqa: BLE001
            veredito = classificar_sql(erro)
    assert veredito == NEGADO, veredito


@requer_pg
def test_a_trilha_nao_aceita_update_nem_delete(banco, cenario):
    """Append-only não é convenção: é ausência de política de escrita."""
    # `set local` só vale dentro de transação, e este evento precisa
    # SOBREVIVER a ela: é o alvo das tentativas de alteração abaixo.
    with banco.transaction(), banco.cursor() as c:
        como(c, cenario["quem"]["admin"]["jwt"])
        c.execute("select public.registrar_evento_governanca("
                  "'artefato_alterado', 'artefato', %s, '{}')",
                  (cenario["artefato"],))
        evento = c.fetchone()[0]
        voltar_a_ser_servidor(c)

    comandos = (
        "update governanca_eventos set payload = %s::jsonb where id = %s",
        "delete from governanca_eventos where id = %s",
    )
    for comando in comandos:
        parametros = ('{"x": 1}', evento) if "update" in comando else (evento,)
        with banco.transaction(force_rollback=True), banco.cursor() as c:
            como(c, cenario["quem"]["admin"]["jwt"])
            try:
                c.execute(comando, parametros)
                # sem policy de UPDATE/DELETE o RLS não levanta erro:
                # ele simplesmente não encontra linha para alterar
                assert c.rowcount == 0, f"a trilha cedeu a: {comando}"
            except Exception as erro:  # noqa: BLE001
                assert classificar_sql(erro) == NEGADO, (comando, erro)


# ---------------------------------------------------------------------------
# Vocabulário e vínculo
# ---------------------------------------------------------------------------
@requer_pg
def test_entidade_nula_e_recusada(banco, cenario):
    """Nulo pulava a checagem de existência inteira."""
    veredito, _ = _registrar(banco, cenario, "admin", "artefato_criado",
                             "artefato", None)
    assert veredito != PERMITIDO, veredito


@requer_pg
def test_entidade_de_tabela_incompativel_e_recusada(banco, cenario):
    """
    Declarar 'artefato' e passar o id de uma publicação registrava um
    vínculo que não existe.
    """
    veredito, _ = _registrar(banco, cenario, "admin", "artefato_criado",
                             "artefato", cenario["publicacao"])
    assert veredito != PERMITIDO, veredito


@requer_pg
def test_tipo_de_evento_fora_do_vocabulario_e_recusado(banco, cenario):
    veredito, _ = _registrar(banco, cenario, "admin", "clausula_published",
                             "versao", cenario["versao"])
    assert veredito != PERMITIDO, veredito


@requer_pg
def test_o_vocabulario_do_banco_e_o_do_app_sao_o_mesmo(banco):
    """
    A interseção entre os dois era VAZIA. Aqui a lista é lida do banco
    EM EXECUÇÃO, não do texto da migração.
    """
    from src import trilha

    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select public.tipos_de_evento_validos()")
        do_banco = set(c.fetchone()[0])
        c.execute("select public.entidades_de_evento_validas()")
        entidades = set(c.fetchone()[0])
    assert do_banco == set(trilha.EVENTOS), (
        f"banco={sorted(do_banco)} app={sorted(trilha.EVENTOS)}")
    assert entidades == set(trilha.ENTIDADES)


@requer_pg
def test_cada_evento_exige_no_banco_a_entidade_que_o_app_declara(banco):
    from src import trilha

    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        for tipo, entidade in trilha.EVENTOS.items():
            c.execute("select public.entidade_do_tipo_de_evento(%s)", (tipo,))
            assert c.fetchone()[0] == entidade, tipo


# ---------------------------------------------------------------------------
# GRANTs — nada nasce aberto
# ---------------------------------------------------------------------------
@requer_pg
def test_anon_nao_executa_a_rpc_da_trilha(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(
            "select has_function_privilege('anon', p.oid, 'execute') "
            "from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
            "where n.nspname = 'public' and p.proname in "
            "('registrar_evento_governanca', 'aprovacao_no_escopo', "
            "'papel_alcanca_o_tenant', 'eventos_permitidos_ao_papel')")
        assert not any(linha[0] for linha in c.fetchall())


@requer_pg
def test_nenhuma_funcao_da_aplicacao_e_executavel_por_anon(banco):
    """
    A guarda que o ensaio existe para ter.

    O padrão do PostgreSQL concede EXECUTE a PUBLIC em toda função
    nova, e PUBLIC alcança `anon`. A 0019 tentava fechar isso com
    `alter default privileges ... revoke execute on functions from
    public` — e ESSA LINHA NÃO FUNCIONA: rodando a migração de verdade
    descobriu-se que ela não grava nada em `pg_default_acl` e a função
    seguinte nasce aberta do mesmo jeito. O `trg_evento_ator_confiavel`
    da própria 0020 estava assim.

    Como a única garantia é o revoke explícito, função por função, a
    verificação tem de olhar as FUNÇÕES — não a tabela de defaults, que
    devolve zero linhas tanto no caso fechado quanto no nunca-fechado.

    Funções de EXTENSÃO ficam de fora: revogar `vector_in` de PUBLIC
    quebraria o tipo, e `gen_random_uuid` é default de coluna em meia
    dúzia de tabelas. Elas não tocam dado do app.
    """
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(
            "select p.proname from pg_proc p "
            "join pg_namespace n on n.oid = p.pronamespace "
            "left join pg_depend d on d.objid = p.oid and d.deptype = 'e' "
            "where n.nspname = 'public' and d.objid is null "
            "and has_function_privilege('anon', p.oid, 'execute')")
        abertas = [linha[0] for linha in c.fetchall()]
    assert not abertas, f"executáveis por anon: {abertas}"


@requer_pg
def test_o_revoke_de_default_privileges_para_funcoes_nao_basta(banco):
    """
    Prova NEGATIVA, e é ela que impede a afirmação falsa de voltar.

    Se um dia o PostgreSQL passar a suportar o que a 0019 supunha, este
    teste falha — e aí a documentação das duas migrações precisa mudar
    junto. Enquanto ele passar, está registrado por que cada função
    carrega o seu próprio `revoke`.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        # o gatilho precisa sair de cena para que a prova meça o que
        # afirma medir: sem isso ela mediria o gatilho, não o default
        c.execute("alter event trigger funcao_nasce_fechada disable")
        c.execute("alter default privileges in schema public "
                  "revoke execute on functions from public")
        c.execute("create function public.f_da_prova() returns int "
                  "language sql as $fn$ select 1 $fn$")
        c.execute("select has_function_privilege('anon', "
                  "'public.f_da_prova()', 'execute')")
        ainda_aberta = c.fetchone()[0]
    assert ainda_aberta is True, (
        "o `alter default privileges` passou a fechar funções novas: "
        "atualize o texto da 0019 e da 0020, que documentam o contrário, "
        "e reavalie se o gatilho de evento ainda é necessário")


# ---------------------------------------------------------------------------
# Leitura por secretaria — a decisão de arquitetura, executada
# ---------------------------------------------------------------------------
@requer_pg
@pytest.mark.parametrize("rotulo,visivel", [
    ("titular", True),
    ("colega", True),        # mesma secretaria
    ("outra_sec", False),
    ("admin", True),         # alcança o tenant
    ("outro_ten", False),
])
def test_a_leitura_de_processo_respeita_a_secretaria(banco, cenario,
                                                     rotulo, visivel):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["quem"][rotulo]["jwt"])
        c.execute("select count(*) from processos where id = %s",
                  (cenario["processo"],))
        viu = c.fetchone()[0] == 1
    assert viu is visivel, f"{rotulo}: viu={viu}, esperado={visivel}"


# ---------------------------------------------------------------------------
# O gatilho que fecha a função NOVA
#
# `alter default privileges ... revoke execute on functions from public`
# não impede a próxima função de nascer aberta — provado aqui e, ponta a
# ponta, contra um Supabase de verdade, onde `anon` chamou pelo
# PostgREST uma função criada depois da revogação e recebeu o resultado.
#
# O gatilho de evento age no momento da criação, em vez de depender de
# um default que o PostgreSQL não aplica.
# ---------------------------------------------------------------------------
@requer_pg
def test_a_funcao_nova_nasce_fechada_por_causa_do_gatilho(banco):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("create function public.f_depois_do_gatilho() returns int "
                  "language sql as $fn$ select 1 $fn$")
        c.execute("select has_function_privilege('anon', "
                  "'public.f_depois_do_gatilho()', 'execute')")
        assert c.fetchone()[0] is False, (
            "função nova nasceu executável por anon: o gatilho "
            "`funcao_nasce_fechada` não está ativo")


@requer_pg
def test_o_gatilho_existe_e_cobre_create_e_alter(banco):
    """
    `ALTER FUNCTION` também precisa estar coberto: um `create or replace`
    sobre função já existente entra como ALTER, e sem isso a substituição
    reabriria o que a criação tinha fechado.
    """
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select evtname, evtenabled, evttags from pg_event_trigger "
                  "where evtname = 'funcao_nasce_fechada'")
        linha = c.fetchone()
    assert linha, "gatilho de evento ausente"
    assert linha[1] != 'D', "gatilho desabilitado"
    assert set(linha[2]) == {"CREATE FUNCTION", "ALTER FUNCTION"}, linha[2]


@requer_pg
def test_o_ajuste_de_default_privileges_tolera_recusa(banco):
    """
    No Supabase gerenciado, `alter default privileges for role
    supabase_admin` devolve 42501 — e a 0019, sendo um bloco
    `begin/commit`, ABORTAVA INTEIRA. O ensaio local não pegava: aqui o
    `supabase_admin` é papel comum e o superusuário pode alterá-lo.

    A prova é textual porque o comportamento só aparece com o papel
    gerenciado: o que se garante é que cada tentativa está isolada.
    """
    sql = (Path(__file__).resolve().parent.parent
           / "supabase/migrations/0019_emergencial_fecha_anon.sql.NAO_APLICAR"
           ).read_text()
    assert "insufficient_privilege" in sql, (
        "as tentativas de default privileges não toleram recusa: uma "
        "delas aborta a migração inteira no Supabase gerenciado")
    assert "supabase_admin" in sql
    # e o gatilho, que é o que realmente fecha
    assert "create event trigger funcao_nasce_fechada" in sql
