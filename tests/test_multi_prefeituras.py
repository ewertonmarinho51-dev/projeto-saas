"""
Multi-prefeituras: módulos, portarias e assinaturas — a lógica pura.

O isolamento entre prefeituras é medido contra um PostgreSQL de verdade
em `tests/test_multi_prefeituras_rls.py`. Aqui ficam as decisões que não
precisam de banco: herança de módulo, vigência de portaria e quem pode
assinar o quê.

A separação é deliberada. Estas provas rodam em centésimos de segundo e
descrevem REGRA DE NEGÓCIO; misturá-las com as de RLS faria as duas
pularem juntas quando não houvesse PostgreSQL, e a regra de negócio não
tem por que depender disso.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest

from src import assinaturas, modulos, portarias

RAIZ = Path(__file__).resolve().parent.parent
HOJE = dt.date(2026, 3, 1)


# ---------------------------------------------------------------------------
# MÓDULOS — a tabela-verdade inteira (§10)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("flag,tenant,secretaria,esperado", [
    # A flag global manda em tudo: módulo que o produto não entrega não
    # fica disponível porque uma prefeitura marcou uma caixa.
    (False, True,  modulos.HABILITADO,   False),
    (False, False, modulos.HERDAR,       False),
    # Tenant desligado → desligado, qualquer que seja a secretaria.
    (True,  False, modulos.HABILITADO,   False),
    (True,  False, modulos.HERDAR,       False),
    # Tenant ligado: a secretaria decide, e HERDAR é o default.
    (True,  True,  modulos.HERDAR,       True),
    (True,  True,  modulos.HABILITADO,   True),
    (True,  True,  modulos.DESABILITADO, False),
])
def test_a_heranca_de_modulo_segue_a_tabela_verdade(flag, tenant, secretaria,
                                                    esperado):
    assert modulos.resolver(flag_global=flag, no_tenant=tenant,
                            na_secretaria=secretaria) is esperado


def test_estado_invalido_nunca_abre_acesso():
    """
    Lixo vindo do banco não pode ABRIR módulo. Cair em HERDAR devolve a
    decisão ao nível de cima, que é a escolha conservadora; cair em
    HABILITADO seria um estado corrompido concedendo acesso.
    """
    assert modulos.estado_valido("habilitado ") == modulos.HABILITADO
    assert modulos.estado_valido("xpto") == modulos.HERDAR
    assert modulos.estado_valido(None) == modulos.HERDAR
    assert modulos.resolver(flag_global=True, no_tenant=False,
                            na_secretaria=modulos.estado_valido("xpto")) is False


def test_secretaria_nao_habilita_o_que_o_tenant_proibe():
    """
    A regra que o CHECK do banco não expressa. Sem ela, o painel deixaria
    marcar HABILITADO numa secretaria para um módulo que a prefeitura não
    tem — e o registro ficaria parecendo concessão, até alguém ligar o
    módulo no tenant e três secretarias aparecerem "já habilitadas".
    """
    assert modulos.pode_habilitar_na_secretaria(
        no_tenant=False, estado=modulos.HABILITADO) is False
    assert modulos.pode_habilitar_na_secretaria(
        no_tenant=False, estado=modulos.DESABILITADO) is True
    assert modulos.pode_habilitar_na_secretaria(
        no_tenant=True, estado=modulos.HABILITADO) is True


def test_a_indisponibilidade_se_explica():
    """
    "O menu não mostra" é a pior forma de indisponibilidade: o servidor
    não sabe se o sistema não tem, se a prefeitura não contratou ou se a
    secretaria dispensou. Cada caso leva a uma ação diferente.
    """
    assert "versão" in modulos.explicar(flag_global=False, no_tenant=True)
    assert "prefeitura" in modulos.explicar(flag_global=True, no_tenant=False)
    assert "secretaria" in modulos.explicar(
        flag_global=True, no_tenant=True, na_secretaria=modulos.DESABILITADO)
    assert modulos.explicar(flag_global=True, no_tenant=True) == ""


# ---------------------------------------------------------------------------
# PORTARIAS — vigência por data de referência (§23, §24)
# ---------------------------------------------------------------------------
def _portaria(**kw):
    base = {
        "id": "p1", "tipo": portarias.EQUIPE_PLANEJAMENTO,
        "secretaria_id": "sec-a", "status": portarias.ATIVA,
        "numero": "003", "ano": 2026,
        "data_inicio_vigencia": "2026-01-15",
        "data_publicacao": "2026-01-15",
        "data_fim_vigencia": None,
    }
    base.update(kw)
    return base


def test_portaria_futura_nao_vigora_antes_do_inicio():
    p = _portaria(data_inicio_vigencia="2026-06-01")
    assert portarias.vigente_em(p, HOJE) is False
    assert portarias.situacao(p, HOJE) == portarias.FUTURA


def test_portaria_expirada_nao_vigora_depois_do_fim():
    p = _portaria(data_fim_vigencia="2026-02-01")
    assert portarias.vigente_em(p, HOJE) is False
    assert portarias.situacao(p, HOJE) == portarias.EXPIRADA


def test_portaria_revogada_nao_vigora_mesmo_dentro_da_janela():
    """
    Status e janela são coisas diferentes, e é por isso que os dois são
    consultados: uma portaria pode ser revogada ANTES do fim da vigência
    declarada, e nenhuma conta de data descobre isso.
    """
    p = _portaria(status=portarias.REVOGADA, data_fim_vigencia="2027-01-01")
    assert portarias.vigente_em(p, HOJE) is False
    assert portarias.situacao(p, HOJE) == portarias.REVOGADA


def test_rascunho_nao_e_ato():
    assert portarias.vigente_em(_portaria(status=portarias.RASCUNHO), HOJE) is False


def test_a_data_de_referencia_decide_e_nao_o_hoje():
    """
    O ponto inteiro do módulo. Um DFD de janeiro cita a portaria de
    janeiro; reaberto em dezembro, ele não pode passar a citar outra.
    """
    antiga = _portaria(id="p-antiga", numero="001", ano=2025,
                       data_inicio_vigencia="2025-01-01",
                       data_fim_vigencia="2025-12-31")
    nova = _portaria(id="p-nova", numero="003", ano=2026,
                     data_inicio_vigencia="2026-01-15")
    acervo = [antiga, nova]

    em_2025 = portarias.resolver(acervo, secretaria_id="sec-a",
                                 data_referencia=dt.date(2025, 6, 1))
    em_2026 = portarias.resolver(acervo, secretaria_id="sec-a",
                                 data_referencia=dt.date(2026, 6, 1))
    assert em_2025["id"] == "p-antiga"
    assert em_2026["id"] == "p-nova"


def test_duas_portarias_vigentes_levantam_erro_em_vez_de_escolher():
    """
    A prova mais importante deste arquivo.

    Escolher em silêncio — a mais recente, a de número maior — produziria
    um documento citando uma portaria plausível, assinado pelo servidor,
    com o erro aparecendo só numa auditoria do tribunal de contas. Duas
    portarias vigentes é defeito de cadastro, e cadastro com defeito se
    conserta no painel.
    """
    a = _portaria(id="p-a", numero="003")
    b = _portaria(id="p-b", numero="004")
    with pytest.raises(portarias.PortariaAmbigua) as erro:
        portarias.resolver([a, b], secretaria_id="sec-a", data_referencia=HOJE)
    recado = str(erro.value)
    assert "003/2026" in recado and "004/2026" in recado
    assert "não escolhe por você" in recado


def test_portaria_de_outra_secretaria_nao_e_considerada():
    """§57: o processo da Educação não usa a portaria da Administração."""
    da_administracao = _portaria(secretaria_id="sec-a")
    assert portarias.resolver([da_administracao], secretaria_id="sec-educacao",
                              data_referencia=HOJE) is None


def test_ausencia_de_portaria_e_resposta_legitima():
    assert portarias.resolver([], secretaria_id="sec-a",
                              data_referencia=HOJE) is None


def test_data_ilegivel_nao_vira_vigente_desde_sempre():
    """
    Devolver `None` para data corrompida faria `vigente_em` tratar a
    portaria como sem início — o oposto do conservador. Quem não sabe a
    data não vigora.
    """
    with pytest.raises(portarias.ErroPortaria):
        portarias.vigente_em(_portaria(data_inicio_vigencia="15/01/2026"), HOJE)


# ---------------------------------------------------------------------------
# A CITAÇÃO — e o que ela NUNCA pode conter (§27)
# ---------------------------------------------------------------------------
def test_a_citacao_sai_por_extenso_com_os_dados_reais():
    texto = portarias.citacao(_portaria())
    assert "Portaria nº 003/2026" in texto
    assert "15 de janeiro de 2026" in texto


def test_sem_portaria_o_documento_recebe_MARCADOR_e_nunca_um_numero():
    """
    O §27 em forma de prova: sem portaria válida, o documento não pode
    sair com "Portaria nº XXX" nem com número fictício. Sai com o
    marcador de pendência que a revisão transforma em pergunta ao
    servidor.
    """
    texto = portarias.citacao(None)
    assert texto.startswith("[PREENCHER:")
    assert not re.search(r"n[ºo°]\s*\d", texto), (
        "a citação sem portaria inventou um número")


# ---------------------------------------------------------------------------
# ELEGIBILIDADE — quem pode assinar (§30, §31)
# ---------------------------------------------------------------------------
SERVIDORES = [
    {"id": "sv-a", "nome": "Antonio Ewerton", "cargo": "Agente Administrativo",
     "matricula": "1234", "ativo": True},
    {"id": "sv-b", "nome": "Maria Silva", "cargo": "Técnica", "ativo": True},
    {"id": "sv-c", "nome": "João Souza", "cargo": "Assistente", "ativo": True},
    {"id": "sv-x", "nome": "Exonerado", "cargo": "Ex", "ativo": False},
]

MEMBROS = [
    {"portaria_id": "p1", "servidor_id": "sv-a",
     "funcao": "EQUIPE_PLANEJAMENTO", "ordem": 1, "ativo": True},
    {"portaria_id": "p1", "servidor_id": "sv-b",
     "funcao": "COORDENADOR_EQUIPE_PLANEJAMENTO", "ordem": 2, "ativo": True},
    {"portaria_id": "p1", "servidor_id": "sv-x",
     "funcao": "EQUIPE_PLANEJAMENTO", "ordem": 3, "ativo": True},
]


def test_equipe_de_planejamento_mostra_so_quem_esta_na_portaria():
    """
    §31: não mostrar cinquenta servidores do município para qualquer
    assinatura. João não está na portaria e não aparece.
    """
    lista = assinaturas.elegiveis(
        funcao="EQUIPE_PLANEJAMENTO", servidores=SERVIDORES,
        funcoes_do_servidor=[], portaria=_portaria(),
        membros_da_portaria=MEMBROS, secretaria_id="sec-a",
        data_referencia=HOJE)
    ids = {s["id"] for s in lista}
    assert "sv-a" in ids
    assert "sv-b" in ids, "o coordenador também integra a equipe"
    assert "sv-c" not in ids, "João não está na portaria e apareceu"
    assert "sv-x" not in ids, "servidor inativo apareceu como elegível"


def test_sem_portaria_a_equipe_nao_tem_ninguem_elegivel():
    """
    Vazia é a resposta certa. Nomear alguém "integrante da equipe de
    planejamento" sem ato que o designe é o erro que o documento carrega
    para dentro do processo.
    """
    assert assinaturas.elegiveis(
        funcao="EQUIPE_PLANEJAMENTO", servidores=SERVIDORES,
        funcoes_do_servidor=[], portaria=None, membros_da_portaria=MEMBROS,
        secretaria_id="sec-a", data_referencia=HOJE) == []


def test_funcao_expirada_nao_torna_ninguem_elegivel():
    funcoes = [{"servidor_id": "sv-c", "funcao": "PREGOEIRO",
                "secretaria_id": "sec-a", "ativo": True,
                "data_inicio": "2025-01-01", "data_fim": "2025-12-31"}]
    assert assinaturas.elegiveis(
        funcao="PREGOEIRO", servidores=SERVIDORES, funcoes_do_servidor=funcoes,
        portaria=None, membros_da_portaria=[], secretaria_id="sec-a",
        data_referencia=HOJE) == []


def test_funcao_de_outra_secretaria_nao_alcanca():
    funcoes = [{"servidor_id": "sv-c", "funcao": "PREGOEIRO",
                "secretaria_id": "sec-outra", "ativo": True,
                "data_inicio": "2026-01-01"}]
    assert assinaturas.elegiveis(
        funcao="PREGOEIRO", servidores=SERVIDORES, funcoes_do_servidor=funcoes,
        portaria=None, membros_da_portaria=[], secretaria_id="sec-a",
        data_referencia=HOJE) == []


def test_funcao_municipal_alcanca_qualquer_secretaria():
    """
    `secretaria_id` nulo em `servidor_funcoes` é função do município —
    autoridade competente, ordenador de despesas. Ela vale em qualquer
    secretaria do tenant, e restringi-la quebraria a assinatura do
    prefeito em processo de qualquer pasta.
    """
    funcoes = [{"servidor_id": "sv-c", "funcao": "AUTORIDADE_COMPETENTE",
                "secretaria_id": None, "ativo": True,
                "data_inicio": "2026-01-01"}]
    lista = assinaturas.elegiveis(
        funcao="AUTORIDADE_COMPETENTE", servidores=SERVIDORES,
        funcoes_do_servidor=funcoes, portaria=None, membros_da_portaria=[],
        secretaria_id="qualquer-uma", data_referencia=HOJE)
    assert [s["id"] for s in lista] == ["sv-c"]


def test_conferir_elegibilidade_recusa_escolha_vencida():
    """
    A tela mostrou os elegíveis há cinco minutos; nesse intervalo a
    portaria pode ter sido revogada. Conferir de novo ao gravar é o que
    impede a escolha antiga de valer contra o cadastro novo.
    """
    with pytest.raises(assinaturas.ErroAssinatura) as erro:
        assinaturas.conferir_elegibilidade(
            servidor_id="sv-c", funcao="EQUIPE_PLANEJAMENTO",
            elegiveis_agora=[{"id": "sv-a"}])
    assert "revogada ou expirada" in str(erro.value)


# ---------------------------------------------------------------------------
# SNAPSHOT — o que fica congelado (§33, §34)
# ---------------------------------------------------------------------------
def test_o_snapshot_congela_tudo_que_o_documento_imprime():
    snap = assinaturas.montar_snapshot(
        servidor=SERVIDORES[0], funcao="EQUIPE_PLANEJAMENTO",
        secretaria_nome="Secretaria de Administração",
        portaria=_portaria(), ordem=1)

    assert snap["nome_snapshot"] == "Antonio Ewerton"
    assert snap["cargo_snapshot"] == "Agente Administrativo"
    assert snap["matricula_snapshot"] == "1234"
    assert snap["portaria_numero_snapshot"] == "003/2026"
    assert snap["secretaria_snapshot"] == "Secretaria de Administração"
    # `servidor_id` viaja para auditoria, mas a exportação não depende dele.
    assert snap["servidor_id"] == "sv-a"


def test_a_exportacao_le_so_o_snapshot():
    """
    §34: nunca consultar o cadastro vivo para regenerar documento
    histórico. Aqui o servidor foi exonerado e mudou de nome no cadastro;
    o documento continua imprimindo o que era verdade no dia.
    """
    congelado = [{
        "nome_snapshot": "Antonio Ewerton Marinho Leite",
        "funcao_snapshot": "EQUIPE_PLANEJAMENTO",
        "portaria_numero_snapshot": "003/2026",
        "ordem": 1,
    }]
    linhas = assinaturas.linhas_de_exportacao(congelado)
    assert linhas == [[
        "ANTONIO EWERTON MARINHO LEITE",
        "Integrante da Equipe de Planejamento",
        "Portaria nº 003/2026",
    ]]


def test_a_ordem_dos_signatarios_e_respeitada():
    fora_de_ordem = [
        {"nome_snapshot": "Maria", "funcao_snapshot": "SECRETARIO", "ordem": 2},
        {"nome_snapshot": "Antonio", "funcao_snapshot": "EQUIPE_PLANEJAMENTO",
         "ordem": 1},
    ]
    linhas = assinaturas.linhas_de_exportacao(fora_de_ordem)
    assert linhas[0][0] == "ANTONIO"
    assert linhas[1][0] == "MARIA"


def test_servidor_sem_nome_nao_assina():
    with pytest.raises(assinaturas.ErroAssinatura):
        assinaturas.montar_snapshot(
            servidor={"id": "x", "nome": "  "}, funcao="SECRETARIO",
            secretaria_nome=None, portaria=None, ordem=1)


def test_funcao_desconhecida_nao_vira_assinatura():
    with pytest.raises(assinaturas.ErroAssinatura):
        assinaturas.montar_snapshot(
            servidor=SERVIDORES[0], funcao="CHEFE_SUPREMO",
            secretaria_nome=None, portaria=None, ordem=1)


# ---------------------------------------------------------------------------
# A CAMADA DE ACESSO NÃO ACEITA TENANT DE FORA (§4)
# ---------------------------------------------------------------------------
FUNCOES_DA_0025 = (
    "modulos_do_tenant", "salvar_modulo_do_tenant", "modulos_da_secretaria",
    "salvar_modulo_da_secretaria", "modulo_disponivel", "listar_servidores",
    "salvar_servidor", "listar_funcoes_administrativas",
    "listar_funcoes_de_servidores", "listar_portarias", "salvar_portaria",
    "listar_membros_de_portaria", "salvar_membro_de_portaria",
    "gravar_signatarios", "signatarios_do_documento",
)


def test_nenhuma_funcao_da_0025_aceita_tenant_por_parametro():
    """
    O §4 em forma de prova: `tenant_id` nunca pode ser escolhido pelo
    frontend.

    Um parâmetro opcional de tenant é um convite a alguém passá-lo a
    partir da tela — e o dia em que isso acontecer, a RLS recusa, mas o
    código já terá sido escrito e revisado como se fosse aceitável.
    Melhor que a assinatura torne o erro impossível de digitar.
    """
    import inspect

    from src import db

    culpadas = []
    for nome in FUNCOES_DA_0025:
        funcao = getattr(db, nome, None)
        assert funcao is not None, f"{nome} sumiu de db.py"
        parametros = set(inspect.signature(funcao).parameters)
        if parametros & {"tenant_id", "tenant"}:
            culpadas.append(nome)
    assert culpadas == [], (
        f"estas funções aceitam tenant de fora: {culpadas}")


def test_as_funcoes_de_escrita_derivam_o_tenant_da_sessao():
    """
    O outro lado: não basta não ACEITAR o tenant — é preciso PREENCHÊ-LO.
    Uma função de escrita que não cite `tenant_atual()` deixaria a coluna
    nula, e o insert morreria no `not null` do banco em vez de gravar
    onde deve.
    """
    import inspect

    from src import db

    faltando = []
    for nome in ("salvar_servidor", "salvar_portaria",
                 "salvar_modulo_do_tenant", "salvar_modulo_da_secretaria",
                 "salvar_membro_de_portaria", "gravar_signatarios"):
        if "tenant_atual()" not in inspect.getsource(getattr(db, nome)):
            faltando.append(nome)
    assert faltando == [], (
        f"escrita sem tenant derivado da sessão: {faltando}")


# ---------------------------------------------------------------------------
# AS DUAS LISTAS DE FUNÇÃO NÃO PODEM DIVERGIR
# ---------------------------------------------------------------------------
def test_o_vocabulario_de_funcoes_bate_com_a_migracao():
    """
    `assinaturas.ROTULOS` imprime no documento; a 0025 semeia
    `funcoes_administrativas`, que é o destino das FK. Duas listas do
    mesmo vocabulário divergem na primeira função acrescentada só de um
    lado — e a divergência apareceria como função sem rótulo no PDF, ou
    como FK violada no cadastro.
    """
    sql = (RAIZ / "supabase" / "migrations"
           / "0025_multi_prefeituras_servidores_portarias.sql").read_text()

    # Recorta O SEED, e não o arquivo inteiro: a primeira versão desta
    # prova varria tudo e capturou `('CARGO', 'PORTARIA', ...)` do CHECK
    # de `origem_designacao`, reprovando por um vocabulário que não tem
    # nada a ver com este. Prova que lê demais falha pelo motivo errado.
    bloco = re.search(
        r"insert into public\.funcoes_administrativas.*?on conflict",
        sql, re.S)
    assert bloco, "não achei o seed de funcoes_administrativas na 0025"
    no_sql = set(re.findall(r"\('([A-Z_]+)',", bloco.group(0)))

    assert no_sql, "o seed existe mas nenhum código foi extraído dele"
    assert set(assinaturas.ROTULOS) == no_sql, (
        f"só no Python: {set(assinaturas.ROTULOS) - no_sql}; "
        f"só no SQL: {no_sql - set(assinaturas.ROTULOS)}")
    assert set(assinaturas.TIPOS_DE_SIGNATARIO) == no_sql
