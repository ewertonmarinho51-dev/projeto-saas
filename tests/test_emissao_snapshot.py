"""
Emissão e exportação: o documento aprovado para de depender do cadastro.

A prova que decide este arquivo é
`test_o_documento_historico_nao_muda_quando_o_cadastro_muda`. Todas as
outras existem para que ela signifique alguma coisa.

O cenário é o que acontece de verdade numa prefeitura: o edital é
aprovado em janeiro com a equipe designada pela portaria de janeiro; em
março o servidor é exonerado, muda de cargo e a portaria é revogada. O
PDF de janeiro tem que continuar dizendo o que dizia — porque ele é ato
administrativo publicado, e um sistema que o regenerasse com os dados de
março produziria um documento que nunca existiu.
"""

from __future__ import annotations

import datetime as dt

import pytest

from src import assinaturas, emissao

SERVIDORES = [
    {"id": "sv-a", "nome": "Antonio Ewerton Marinho Leite",
     "cargo": "Agente Administrativo", "matricula": "1234", "ativo": True},
    {"id": "sv-b", "nome": "Maria Silva", "cargo": "Técnica",
     "matricula": "5678", "ativo": True},
]

PORTARIA = {
    "id": "p1", "numero": "003", "ano": 2026,
    "tipo": "EQUIPE_PLANEJAMENTO", "secretaria_id": "sec-a",
    "status": "ATIVA", "data_publicacao": "2026-01-15",
    "data_inicio_vigencia": "2026-01-15", "data_fim_vigencia": None,
}

ESCOLHAS = [
    {"servidor_id": "sv-a", "funcao": "EQUIPE_PLANEJAMENTO"},
    {"servidor_id": "sv-b", "funcao": "COORDENADOR_EQUIPE_PLANEJAMENTO"},
]


# ---------------------------------------------------------------------------
# A PROVA QUE DECIDE
# ---------------------------------------------------------------------------
def test_o_documento_historico_nao_muda_quando_o_cadastro_muda():
    """
    Congela em janeiro; em março o mundo muda; o documento não.

    Se esta prova falhar, o sistema está regenerando documento histórico
    com dados de hoje — e isso não é bug de formatação, é um edital
    dizendo que foi assinado por alguém que não o assinou.
    """
    congelado = emissao.montar_signatarios(
        ESCOLHAS, servidores=SERVIDORES,
        secretaria_nome="Secretaria de Administração", portaria=PORTARIA)
    bloco_de_janeiro = emissao.bloco_de_assinaturas(congelado)

    # Março: exonerado, cargo trocado, portaria revogada, secretaria
    # renomeada. Nada disso alcança o que já foi congelado.
    _mundo_de_marco = {
        "servidores": [{"id": "sv-a", "nome": "OUTRO NOME", "cargo": "Ex",
                        "ativo": False}],
        "portaria": {**PORTARIA, "status": "REVOGADA", "numero": "999"},
    }
    bloco_de_marco = emissao.bloco_de_assinaturas(congelado)

    assert bloco_de_marco == bloco_de_janeiro
    assert "ANTONIO EWERTON MARINHO LEITE" in bloco_de_janeiro
    assert "Portaria nº 003/2026" in bloco_de_janeiro
    assert "OUTRO NOME" not in bloco_de_janeiro
    assert "999" not in bloco_de_janeiro


def test_a_exportacao_nao_conhece_cadastro_de_pessoal():
    """
    `gerar_docx`/`gerar_pdf` recebem o bloco JÁ RENDERIZADO — nunca uma
    lista de servidores a consultar.

    É essa assinatura que torna impossível regenerar um documento
    histórico com dados de hoje: a exportação não tem como perguntar ao
    banco quem é o servidor, porque ela não sabe que existe um.
    """
    import inspect

    from src import export

    for funcao in (export.gerar_docx, export.gerar_pdf):
        parametros = inspect.signature(funcao).parameters
        assert "assinaturas" in parametros
        assert parametros["assinaturas"].default == "", (
            "o bloco precisa ser opcional: documento sem snapshot sai "
            "como sempre saiu")

    fonte = inspect.getsource(export)
    for proibido in ("listar_servidores", "signatarios_do_documento",
                     "db.listar", "portarias.resolver"):
        assert proibido not in fonte, (
            f"export.py passou a consultar cadastro ({proibido})")


# ---------------------------------------------------------------------------
# A DATA DE REFERÊNCIA (§24)
# ---------------------------------------------------------------------------
def test_a_referencia_e_a_criacao_do_processo_e_nao_hoje():
    processo = {"criado_em": "2026-01-20T10:30:00+00:00"}
    assert emissao.data_de_referencia(processo) == dt.date(2026, 1, 20)


def test_sem_data_legivel_cai_para_hoje_em_vez_de_travar():
    """
    Registro corrompido não pode impedir a aprovação de um processo. Cair
    para hoje é a única escolha que não trava o servidor na tela.
    """
    assert emissao.data_de_referencia({}) == dt.date.today()
    assert emissao.data_de_referencia(
        {"criado_em": "ontem"}) == dt.date.today()


# ---------------------------------------------------------------------------
# O QUE ENTRA — E O QUE NÃO ENTRA — NO SNAPSHOT
# ---------------------------------------------------------------------------
def test_so_funcao_de_portaria_carrega_o_numero_dela():
    """
    Carimbar "Portaria nº 003/2026" sob o nome do Secretário Municipal
    seria atribuir a ele uma designação que a portaria não fez.
    """
    escolhas = [
        {"servidor_id": "sv-a", "funcao": "EQUIPE_PLANEJAMENTO"},
        {"servidor_id": "sv-b", "funcao": "SECRETARIO"},
    ]
    snaps = emissao.montar_signatarios(
        escolhas, servidores=SERVIDORES, secretaria_nome="SEMAD",
        portaria=PORTARIA)

    por_funcao = {s["funcao_snapshot"]: s for s in snaps}
    assert por_funcao["EQUIPE_PLANEJAMENTO"]["portaria_numero_snapshot"] == "003/2026"
    assert por_funcao["SECRETARIO"]["portaria_numero_snapshot"] is None


def test_escolha_de_servidor_que_sumiu_do_cadastro_e_descartada():
    """
    Bloco de assinatura sem nome é pior que bloco ausente: parece
    assinado. Melhor descartar com log do que imprimir uma linha vazia
    sob um traço.
    """
    escolhas = [{"servidor_id": "sv-fantasma", "funcao": "SECRETARIO"},
                {"servidor_id": "sv-a", "funcao": "SECRETARIO"}]
    snaps = emissao.montar_signatarios(
        escolhas, servidores=SERVIDORES, secretaria_nome=None, portaria=None)
    assert len(snaps) == 1
    assert snaps[0]["nome_snapshot"].startswith("Antonio")


def test_a_ordem_da_escolha_vira_a_ordem_do_documento():
    snaps = emissao.montar_signatarios(
        ESCOLHAS, servidores=SERVIDORES, secretaria_nome=None,
        portaria=PORTARIA)
    assert [s["ordem"] for s in snaps] == [1, 2]
    bloco = emissao.bloco_de_assinaturas(snaps)
    assert bloco.index("ANTONIO") < bloco.index("MARIA")


def test_sem_signatarios_o_bloco_e_vazio():
    """
    §58: processo antigo, sem snapshot, exporta como sempre exportou. Um
    bloco em branco pareceria assinatura pendente.
    """
    assert emissao.bloco_de_assinaturas([]) == ""


# ---------------------------------------------------------------------------
# O CONGELAMENTO É BEST-EFFORT (§35)
# ---------------------------------------------------------------------------
def test_falha_ao_gravar_nao_derruba_a_aprovacao():
    """
    Travar o avanço do processo porque uma tabela auxiliar não respondeu
    seria trocar um registro incompleto por um servidor público parado.
    A falha vira `False` e log — nunca exceção subindo para a tela.
    """
    def gravar_quebrado(_identidade, _signatarios):
        raise RuntimeError("PostgREST fora do ar")

    assert emissao.congelar(
        "proc-1", "edital", escolhas=ESCOLHAS, servidores=SERVIDORES,
        secretaria_id="sec-a", secretaria_nome="SEMAD", portaria=PORTARIA,
        identidade={"cabecalho": "x"}, origem="secretaria",
        gravar=gravar_quebrado) is False


def test_congelamento_bem_sucedido_grava_identidade_e_signatarios():
    recebido = {}

    def gravar(identidade, signatarios):
        recebido["identidade"] = identidade
        recebido["signatarios"] = signatarios

    assert emissao.congelar(
        "proc-1", "edital", escolhas=ESCOLHAS, servidores=SERVIDORES,
        secretaria_id="sec-a", secretaria_nome="SEMAD", portaria=PORTARIA,
        identidade={"cabecalho": "brasão"}, origem="secretaria",
        gravar=gravar) is True

    assert recebido["identidade"]["origem"] == "secretaria"
    assert recebido["identidade"]["hash_identidade"]
    assert len(recebido["signatarios"]) == 2


def test_origem_invalida_de_identidade_vira_nenhuma():
    """
    A coluna tem CHECK. Mandar um valor fora do domínio faria o insert
    morrer no banco e o congelamento inteiro falhar — inclusive os
    signatários, que estavam corretos.
    """
    linha = emissao.montar_identidade({}, "inventada", secretaria_id=None)
    assert linha["origem"] == "nenhuma"


def test_o_hash_da_identidade_e_estavel_e_sensivel():
    """
    Estável para o mesmo timbrado (ordem de chave não muda o hash) e
    diferente quando o timbrado muda — senão ele não serviria para
    responder "este PDF saiu com a identidade que o snapshot registra?".
    """
    a = emissao.impressao_da_identidade({"cabecalho": "x", "rodape": "y"})
    b = emissao.impressao_da_identidade({"rodape": "y", "cabecalho": "x"})
    c = emissao.impressao_da_identidade({"cabecalho": "OUTRO", "rodape": "y"})
    assert a == b
    assert a != c


# ---------------------------------------------------------------------------
# A PONTE NÃO ATRAVESSA A FLAG
# ---------------------------------------------------------------------------
def test_com_a_flag_desligada_nada_e_congelado_nem_exportado(monkeypatch):
    """
    §58: processo antigo continua pelo caminho legado. Com a flag
    desligada a ponte não consulta banco nenhum — nem para congelar, nem
    para exportar.
    """
    from src import instituicional_bridge

    monkeypatch.setattr(instituicional_bridge, "ativo", lambda: False)
    assert instituicional_bridge.congelar_na_aprovacao("edital") is False
    assert instituicional_bridge.bloco_para_exportacao("edital") == ""


def test_a_aprovacao_chama_o_congelamento():
    """
    A ligação entre o botão e o congelamento, lida no código: renderizar
    o fluxo inteiro aqui mediria dez coisas para verificar uma linha.
    """
    import inspect

    from src import state

    fonte = inspect.getsource(state.aprovar_e_avancar)
    assert "instituicional_bridge.congelar_na_aprovacao" in fonte
    # E ANTES de avançar a etapa: congelar depois do `st.rerun()` seria
    # código morto.
    assert (fonte.index("congelar_na_aprovacao")
            < fonte.index("st.session_state.etapa += 1"))


@pytest.mark.parametrize("funcao", ["congelar_na_aprovacao",
                                    "bloco_para_exportacao"])
def test_a_ponte_nunca_levanta(monkeypatch, funcao):
    """
    Nem o congelamento nem a exportação podem quebrar a tela. Os dois
    caminhos capturam tudo e seguem.
    """
    from src import instituicional_bridge

    def explodir():
        raise RuntimeError("banco fora")

    monkeypatch.setattr(instituicional_bridge, "ativo", explodir)
    resultado = getattr(instituicional_bridge, funcao)("edital")
    assert resultado in (False, "")


# ---------------------------------------------------------------------------
# A TELA DE SELEÇÃO DE SIGNATÁRIOS (§29–§32)
#
# Provas de POLÍTICA e de ORDEM, não de pixel. O que decide a qualidade
# desta tela é a sequência dos dois campos e o que ela diz quando a lista
# vem vazia.
# ---------------------------------------------------------------------------
def test_o_tipo_vem_antes_do_servidor():
    """
    §29 e §30, e a ordem É a funcionalidade.

    Invertida — uma lista de servidores e um campo de função ao lado — a
    tela viraria um formulário onde alguém digita que o Antonio é
    pregoeiro, e a designação passaria a ser afirmação do operador em vez
    de ato administrativo.
    """
    import inspect

    from src.ui import signatarios

    fonte = inspect.getsource(signatarios._render_adicionar)
    posicao_tipo = fonte.index("Tipo de signatário")
    posicao_pessoa = fonte.index('col_pessoa.selectbox')
    assert posicao_tipo < posicao_pessoa, (
        "o seletor de servidor veio antes do tipo")

    # E a lista de servidores é FILTRADA por elegibilidade, não a lista
    # inteira do município (§31).
    assert "assinaturas.elegiveis(" in fonte
    assert "disponiveis" in fonte


def test_a_selecao_aparece_antes_do_botao_de_aprovar():
    """
    Aprovar é emitir: o que estiver escolhido é o que fica congelado.
    Pôr a seleção depois do botão faria o servidor descobrir que assinou
    sem escolher.
    """
    import inspect

    from src.ui import steps

    fonte = inspect.getsource(steps)
    assert "signatarios.render(doc_key)" in fonte
    assert (fonte.index("signatarios.render(doc_key)")
            < fonte.index('f"Aprovar {meta[\'sigla\']} e avançar"'))


@pytest.mark.parametrize("funcao,tem_portaria,elegiveis,esperado", [
    # Cada causa leva a uma ação diferente, e "nenhum servidor
    # disponível" mandaria o operador procurar defeito no lugar errado.
    ("EQUIPE_PLANEJAMENTO", False, [], "não tem Portaria"),
    ("EQUIPE_PLANEJAMENTO", True, [], "não tem membros"),
    ("PREGOEIRO", False, [], "designação vigente"),
    ("PREGOEIRO", False, [{"id": "x"}], "já foram adicionados"),
])
def test_a_lista_vazia_diz_o_motivo(funcao, tem_portaria, elegiveis, esperado):
    from src.ui import signatarios

    recado = signatarios._por_que_vazio(
        funcao, elegiveis, {"id": "p1"} if tem_portaria else None)
    assert esperado in recado


def test_a_tela_reconfere_elegibilidade_no_clique():
    """
    Entre montar a lista e o clique, a portaria pode ter sido revogada. A
    reconferência é o que impede a escolha antiga de valer contra o
    cadastro novo.
    """
    import inspect

    from src.ui import signatarios

    fonte = inspect.getsource(signatarios._render_adicionar)
    assert "conferir_elegibilidade" in fonte
    assert fonte.index("conferir_elegibilidade") < fonte.index("escolhas.append")


def test_a_tela_nao_quebra_sem_as_tabelas():
    """
    Sem a 0025 aplicada o documento continua sendo aprovado pelo caminho
    legado. A tela avisa em vez de sumir: o administrador precisa saber
    que o bloco de assinatura não vai sair.
    """
    import inspect

    from src.ui import signatarios

    fonte = inspect.getsource(signatarios.render)
    assert "instituicional_bridge.ativo()" in fonte
    assert "db.ErroBanco" in fonte
    assert "st.info" in fonte


def test_o_conflito_de_portarias_nao_e_resolvido_na_tela():
    """
    A tela mostra o erro e não escolhe — nem a mais recente, nem a de
    número maior. Ver `src/portarias.py`.
    """
    import inspect

    from src.ui import signatarios

    fonte = inspect.getsource(signatarios._portaria_vigente)
    assert "PortariaAmbigua" in fonte
    assert "return None" in fonte
