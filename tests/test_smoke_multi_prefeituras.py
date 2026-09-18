"""
Smoke ponta a ponta do §57: duas secretarias, um timbrado herdado e uma
portaria que não atravessa.

POR QUE ESTE ARQUIVO EXISTE SEPARADO DOS OUTROS

As peças já estão provadas isoladamente: a herança de módulo em
`test_multi_prefeituras.py`, o isolamento em
`test_multi_prefeituras_rls.py`, o congelamento em
`test_emissao_snapshot.py`. Todas passam. E nenhuma delas percorre o
CAMINHO INTEIRO.

É essa a categoria de defeito que sobra: integração errada entre peças
certas. O resolvedor de identidade funciona; o de portaria funciona; e
ninguém tinha verificado que, montados sobre o mesmo banco, o processo da
Educação não termina com o timbrado da Administração.

O CENÁRIO É O DO ESCOPO, LITERAL

    Prefeitura Municipal Alfa
      ├── Secretaria de Administração — timbrado PRÓPRIO
      │     └── Portaria 003/2026 — Equipe de Planejamento
      │           ├── Servidor A
      │           └── Servidor B
      └── Secretaria de Educação — HERDA o timbrado da Prefeitura

    Processo da Administração → timbrado próprio, portaria 003/2026,
                                 só A e B elegíveis
    Processo da Educação      → timbrado herdado, NENHUMA portaria

FRONTEIRA, dita antes que alguém confie demais: isto roda contra o schema
REAL num PostgreSQL descartável e exercita os RESOLVEDORES sobre dados
lidos desse banco. **Não** passa por `db.py` — que fala PostgREST por
HTTP — nem por Streamlit. O que ele prova é que schema, constraints e
lógica de domínio se encaixam; não prova a camada de transporte.
"""

from __future__ import annotations

import datetime as dt
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import claims, como, voltar_a_ser_servidor  # noqa: E402

from src import assinaturas, contexto, emissao, portarias  # noqa: E402

requer_pg = pytest.mark.usefixtures("ensaio_sql")

# O processo é criado em março; a portaria vale desde janeiro. A data de
# referência é a do PROCESSO — ver `emissao.data_de_referencia`.
CRIACAO_DO_PROCESSO = "2026-03-10T09:00:00+00:00"

TIMBRADO_DA_PREFEITURA = "BRASÃO — PREFEITURA MUNICIPAL ALFA"
TIMBRADO_DA_ADMINISTRACAO = "BRASÃO — SECRETARIA DE ADMINISTRAÇÃO"


@pytest.fixture(scope="module")
def alfa(banco):
    """Monta o cenário do §57 no banco real. Falha aqui é erro, nunca skip."""
    dados: dict = {}
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)

        c.execute("insert into tenants (slug, nome, uf, nome_oficial) "
                  "values (%s, 'Prefeitura Municipal Alfa', 'PA', "
                  "'Município de Alfa') returning id",
                  (f"alfa-{uuid.uuid4().hex[:8]}",))
        dados["tenant"] = c.fetchone()[0]

        # A "identidade da Prefeitura" é a secretaria marcada `padrao` —
        # é assim que `contexto.resolver_identidade` já resolvia antes
        # desta entrega, e não foi inventado um segundo mecanismo.
        c.execute(
            "insert into secretarias (tenant_id, nome, sigla, padrao, "
            "cabecalho) values (%s, 'Gabinete do Prefeito', 'GAB', true, %s) "
            "returning id", (dados["tenant"], TIMBRADO_DA_PREFEITURA))
        dados["gabinete"] = c.fetchone()[0]

        c.execute(
            "insert into secretarias (tenant_id, nome, sigla, cabecalho) "
            "values (%s, 'Secretaria de Administração', 'SEMAD', %s) "
            "returning id",
            (dados["tenant"], TIMBRADO_DA_ADMINISTRACAO))
        dados["administracao"] = c.fetchone()[0]

        # Educação SEM identidade própria: é o caso de herança.
        c.execute(
            "insert into secretarias (tenant_id, nome, sigla) "
            "values (%s, 'Secretaria de Educação', 'SEMED') returning id",
            (dados["tenant"],))
        dados["educacao"] = c.fetchone()[0]

        for chave, nome, cargo in (
                ("servidor_a", "Antonio Ewerton Marinho Leite",
                 "Agente Administrativo"),
                ("servidor_b", "Maria Silva Souza", "Técnica em Contabilidade"),
                ("servidor_c", "João Pereira Lima", "Assistente")):
            c.execute("insert into servidores (tenant_id, nome, cargo) "
                      "values (%s, %s, %s) returning id",
                      (dados["tenant"], nome, cargo))
            dados[chave] = c.fetchone()[0]

        c.execute(
            "insert into portarias (tenant_id, secretaria_id, numero, ano, "
            "tipo, data_publicacao, data_inicio_vigencia, status) values "
            "(%s, %s, '003', 2026, 'EQUIPE_PLANEJAMENTO', '2026-01-15', "
            "'2026-01-15', 'ATIVA') returning id",
            (dados["tenant"], dados["administracao"]))
        dados["portaria"] = c.fetchone()[0]

        # Só A e B. O C existe no município e NÃO integra a equipe — é ele
        # que torna a prova de elegibilidade não-vazia.
        for servidor, funcao, ordem in (
                ("servidor_a", "EQUIPE_PLANEJAMENTO", 1),
                ("servidor_b", "COORDENADOR_EQUIPE_PLANEJAMENTO", 2)):
            c.execute(
                "insert into portaria_membros (portaria_id, servidor_id, "
                "tenant_id, funcao, ordem) values (%s, %s, %s, %s, %s)",
                (dados["portaria"], dados[servidor], dados["tenant"],
                 funcao, ordem))

    banco.commit()

    dados = {k: (str(v) if isinstance(v, uuid.UUID) else v)
             for k, v in dados.items()}
    dados["jwt_semad"] = claims("u-semad", papel="usuario",
                                tenant=dados["tenant"],
                                secretaria=dados["administracao"])
    dados["jwt_semed"] = claims("u-semed", papel="usuario",
                                tenant=dados["tenant"],
                                secretaria=dados["educacao"])
    return dados


def _ler(banco, jwt, sql, params=()):
    """Lê como um usuário AUTENTICADO — atravessando a RLS de verdade."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, jwt)
        c.execute(sql, params)
        colunas = [d.name for d in c.description]
        return [dict(zip(colunas, linha)) for linha in c.fetchall()]


def _secretarias(banco, jwt):
    return _ler(banco, jwt,
                "select id::text, nome, sigla, padrao, cabecalho, rodape, "
                "marca_dagua, cabecalho_img, rodape_img, marca_img "
                "from secretarias order by padrao desc, nome")


# ---------------------------------------------------------------------------
# TIMBRADO: próprio na Administração, herdado na Educação (§11, §12, §57)
# ---------------------------------------------------------------------------
@requer_pg
def test_a_administracao_usa_o_timbrado_dela(banco, alfa):
    identidade, origem = contexto.resolver_identidade(
        _secretarias(banco, alfa["jwt_semad"]), alfa["administracao"])
    assert origem == "secretaria"
    assert identidade["cabecalho"] == TIMBRADO_DA_ADMINISTRACAO


@requer_pg
def test_a_educacao_herda_o_timbrado_da_prefeitura(banco, alfa):
    """
    O caso que o §57 nomeia. A Educação não tem identidade própria, e o
    resolvedor sobe um nível — não devolve vazio nem inventa.
    """
    identidade, origem = contexto.resolver_identidade(
        _secretarias(banco, alfa["jwt_semed"]), alfa["educacao"])
    assert origem == "municipio"
    assert identidade["cabecalho"] == TIMBRADO_DA_PREFEITURA
    assert identidade["cabecalho"] != TIMBRADO_DA_ADMINISTRACAO


@requer_pg
def test_a_heranca_escolhe_o_padrao_e_nao_a_primeira_da_lista(banco, alfa):
    """
    O teste acima passa mesmo com a herança quebrada.

    `listar_secretarias` ordena `padrao desc, nome`, então a do município
    já chega primeiro e "pegar a primeira com identidade" dá a mesma
    resposta que "pegar a padrão". A prova acerta por acidente de ORDER
    BY, não por mérito do resolvedor.

    Aqui a lista chega HOSTIL — a Administração antes do Gabinete. Se o
    resolvedor passar a depender da ordem do chamador, a Educação sai
    com o brasão da Administração e é este teste que denuncia.
    """
    hostil = sorted(_secretarias(banco, alfa["jwt_semed"]),
                    key=lambda s: bool(s.get("padrao")))
    assert not hostil[0]["padrao"], "a lista não ficou hostil"

    identidade, origem = contexto.resolver_identidade(hostil, alfa["educacao"])
    assert origem == "municipio"
    assert identidade["cabecalho"] == TIMBRADO_DA_PREFEITURA


# ---------------------------------------------------------------------------
# PORTARIA: a da Administração não atravessa para a Educação (§57)
# ---------------------------------------------------------------------------
def _portarias(banco, jwt):
    return _ler(banco, jwt,
                "select id::text, secretaria_id::text, numero, ano, tipo, "
                "status, data_publicacao, data_inicio_vigencia, "
                "data_fim_vigencia from portarias")


@requer_pg
def test_o_processo_da_administracao_encontra_a_portaria(banco, alfa):
    referencia = emissao.data_de_referencia({"criado_em": CRIACAO_DO_PROCESSO})
    vigente = portarias.resolver(
        _portarias(banco, alfa["jwt_semad"]),
        secretaria_id=alfa["administracao"], data_referencia=referencia)

    assert vigente is not None
    assert vigente["numero"] == "003"
    assert "Portaria nº 003/2026" in portarias.citacao(vigente)
    assert "15 de janeiro de 2026" in portarias.citacao(vigente)


@requer_pg
def test_o_processo_da_educacao_nao_usa_a_portaria_da_administracao(banco, alfa):
    """
    A frase literal do §57. A Educação não tem portaria, e a da
    Administração está vigente e visível para o mesmo tenant — é
    exatamente a situação em que um filtro esquecido vazaria.
    """
    referencia = emissao.data_de_referencia({"criado_em": CRIACAO_DO_PROCESSO})
    acervo = _portarias(banco, alfa["jwt_semed"])
    assert acervo, "o cenário perdeu a portaria: a prova ficaria vazia"

    vigente = portarias.resolver(acervo, secretaria_id=alfa["educacao"],
                                 data_referencia=referencia)
    assert vigente is None


@requer_pg
def test_sem_portaria_a_educacao_recebe_MARCADOR_e_nunca_um_numero(banco, alfa):
    """§27 no caminho inteiro, e não só na função pura."""
    import re

    texto = portarias.citacao(None)
    assert texto.startswith("[PREENCHER:")
    assert not re.search(r"n[ºo°]\s*\d", texto)


# ---------------------------------------------------------------------------
# ELEGIBILIDADE: só A e B (§30, §31, §57)
# ---------------------------------------------------------------------------
def _servidores(banco, jwt):
    return _ler(banco, jwt,
                "select id::text, nome, cargo, matricula, ativo "
                "from servidores order by nome")


def _membros(banco, jwt, portaria_id):
    return _ler(banco, jwt,
                "select portaria_id::text, servidor_id::text, funcao, ordem, "
                "ativo from portaria_membros where portaria_id = %s",
                (portaria_id,))


@requer_pg
def test_so_os_membros_da_portaria_podem_assinar_pela_equipe(banco, alfa):
    """
    O município tem TRÊS servidores; a portaria designou DOIS. A tela de
    assinatura mostra dois — não a lista do município (§31).
    """
    referencia = emissao.data_de_referencia({"criado_em": CRIACAO_DO_PROCESSO})
    servidores = _servidores(banco, alfa["jwt_semad"])
    assert len(servidores) == 3, "o cenário perdeu um servidor"

    portaria = portarias.resolver(
        _portarias(banco, alfa["jwt_semad"]),
        secretaria_id=alfa["administracao"], data_referencia=referencia)

    elegiveis = assinaturas.elegiveis(
        funcao="EQUIPE_PLANEJAMENTO", servidores=servidores,
        funcoes_do_servidor=[], portaria=portaria,
        membros_da_portaria=_membros(banco, alfa["jwt_semad"],
                                     alfa["portaria"]),
        secretaria_id=alfa["administracao"], data_referencia=referencia)

    ids = {s["id"] for s in elegiveis}
    assert ids == {alfa["servidor_a"], alfa["servidor_b"]}
    assert alfa["servidor_c"] not in ids, (
        "João não foi designado pela portaria e apareceu como elegível")


@requer_pg
def test_a_educacao_nao_tem_ninguem_elegivel_pela_equipe(banco, alfa):
    """
    Sem portaria, lista vazia — e vazia é a resposta certa: nomear alguém
    "integrante da equipe" sem ato que o designe é o erro que o documento
    carrega para dentro do processo.
    """
    referencia = emissao.data_de_referencia({"criado_em": CRIACAO_DO_PROCESSO})
    elegiveis = assinaturas.elegiveis(
        funcao="EQUIPE_PLANEJAMENTO",
        servidores=_servidores(banco, alfa["jwt_semed"]),
        funcoes_do_servidor=[], portaria=None, membros_da_portaria=[],
        secretaria_id=alfa["educacao"], data_referencia=referencia)
    assert elegiveis == []


# ---------------------------------------------------------------------------
# O DOCUMENTO: do banco até o bloco de assinatura
# ---------------------------------------------------------------------------
@requer_pg
def test_o_caminho_inteiro_produz_o_bloco_correto(banco, alfa):
    """
    Banco → resolvedor de portaria → elegibilidade → snapshot → bloco.

    É a prova que junta tudo: se qualquer peça passar o dado errado para
    a seguinte, o texto final denuncia.
    """
    referencia = emissao.data_de_referencia({"criado_em": CRIACAO_DO_PROCESSO})
    servidores = _servidores(banco, alfa["jwt_semad"])
    portaria = portarias.resolver(
        _portarias(banco, alfa["jwt_semad"]),
        secretaria_id=alfa["administracao"], data_referencia=referencia)

    escolhas = [
        {"servidor_id": alfa["servidor_a"], "funcao": "EQUIPE_PLANEJAMENTO"},
        {"servidor_id": alfa["servidor_b"],
         "funcao": "COORDENADOR_EQUIPE_PLANEJAMENTO"},
    ]
    snaps = emissao.montar_signatarios(
        escolhas, servidores=servidores,
        secretaria_nome="Secretaria de Administração", portaria=portaria)
    bloco = emissao.bloco_de_assinaturas(snaps)

    assert "ANTONIO EWERTON MARINHO LEITE" in bloco
    assert "Integrante da Equipe de Planejamento" in bloco
    assert "MARIA SILVA SOUZA" in bloco
    assert "Coordenador da Equipe de Planejamento" in bloco
    assert bloco.count("Portaria nº 003/2026") == 2
    assert bloco.index("ANTONIO") < bloco.index("MARIA")
    assert "JOÃO" not in bloco.upper()


@requer_pg
def test_o_snapshot_sobrevive_a_exoneracao_no_banco(banco, alfa):
    """
    A promessa inteira, medida contra o banco de verdade: congela, muda o
    CADASTRO no PostgreSQL, e o bloco continua igual.

    A mudança é desfeita no fim — este banco é de módulo e outras provas
    leem os mesmos servidores.
    """
    referencia = emissao.data_de_referencia({"criado_em": CRIACAO_DO_PROCESSO})
    portaria = portarias.resolver(
        _portarias(banco, alfa["jwt_semad"]),
        secretaria_id=alfa["administracao"], data_referencia=referencia)

    congelado = emissao.montar_signatarios(
        [{"servidor_id": alfa["servidor_a"], "funcao": "EQUIPE_PLANEJAMENTO"}],
        servidores=_servidores(banco, alfa["jwt_semad"]),
        secretaria_nome="Secretaria de Administração", portaria=portaria)
    antes = emissao.bloco_de_assinaturas(congelado)

    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("update servidores set nome = 'NOME TROCADO', "
                  "cargo = 'Ex-servidor', ativo = false where id = %s",
                  (alfa["servidor_a"],))
        # Sem isto a prova é vaga: um update que não pegou linha nenhuma
        # faria o bloco continuar igual pelo motivo errado.
        assert c.rowcount == 1, "a exoneração não alterou o cadastro"
        c.execute("update portarias set status = 'REVOGADA' where id = %s",
                  (alfa["portaria"],))
        assert c.rowcount == 1, "a revogação não alterou a portaria"
    banco.commit()

    try:
        depois = emissao.bloco_de_assinaturas(congelado)
        assert depois == antes
        assert "ANTONIO EWERTON MARINHO LEITE" in depois
        assert "NOME TROCADO" not in depois
        assert "Portaria nº 003/2026" in depois
    finally:
        with banco.cursor() as c:
            voltar_a_ser_servidor(c)
            c.execute("update servidores set nome = %s, cargo = %s, "
                      "ativo = true where id = %s",
                      ("Antonio Ewerton Marinho Leite",
                       "Agente Administrativo", alfa["servidor_a"]))
            c.execute("update portarias set status = 'ATIVA' where id = %s",
                      (alfa["portaria"],))
        banco.commit()


# ---------------------------------------------------------------------------
# E O SNAPSHOT GRAVADO É MESMO IMUTÁVEL
# ---------------------------------------------------------------------------
@requer_pg
def test_o_snapshot_gravado_nao_pode_ser_alterado(banco, alfa):
    """
    Não basta a aplicação não oferecer edição: o BANCO tem que recusar.
    Aqui a prova é executada, e não lida do catálogo.
    """
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(
            "insert into processos (tenant_id, secretaria_id, orgao, objeto, "
            "nome, etapa, dados, documentos, aprovados, snapshot, criado_em) "
            "values (%s, %s, 'Alfa', 'Objeto', 'Proc', 1, '{}', '{}', "
            "'{}', '{}', %s) returning id",
            (alfa["tenant"], alfa["administracao"], CRIACAO_DO_PROCESSO))
        processo_id = c.fetchone()[0]
        c.execute(
            "insert into documento_signatarios (processo_id, doc_key, "
            "tenant_id, nome_snapshot, funcao_snapshot, ordem) "
            "values (%s, 'edital', %s, 'ANTONIO', 'EQUIPE_PLANEJAMENTO', 1)",
            (processo_id, alfa["tenant"]))
    banco.commit()

    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, alfa["jwt_semad"])
        with pytest.raises(Exception) as erro:
            c.execute("update documento_signatarios "
                      "set nome_snapshot = 'OUTRO' where processo_id = %s",
                      (processo_id,))
    assert getattr(erro.value, "sqlstate", None) == "42501", (
        "o snapshot aceitou UPDATE: documento assinado mudaria de "
        f"signatário depois de emitido ({erro.value})")
