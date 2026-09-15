"""
Provas do estado derivado do processo (`src/processos.py`).

Tudo aqui é sobre dicionário — sem banco, sem Streamlit. O ponto de
derivar status e progresso, em vez de guardá-los em colunas, é
justamente poder exercitar a máquina inteira assim: os casos de canto
aparecem como linhas de teste em vez de ficarem escondidos dentro de um
laço de renderização.
"""

from __future__ import annotations

import pytest

from src import processos


def _processo(**ajustes):
    base = {
        "id": "p1",
        "nome": "",
        "orgao": "Prefeitura de Exemplo",
        "objeto": "Aquisição de material de expediente",
        "etapa": 0,
        "dados": {},
        "documentos": {},
        "aprovados": [],
        "criado_em": "2026-09-01T10:00:00+00:00",
        "atualizado_em": "2026-09-10T15:30:00+00:00",
    }
    base.update(ajustes)
    return base


# ---------------------------------------------------------------------------
# Quais documentos ESTE processo precisa ter
# ---------------------------------------------------------------------------
def test_processo_comum_nao_precisa_de_ata_de_registro_de_precos():
    """
    São quatro documentos, não cinco.

    Exigir a ARP de todo processo faria um processo comum empacar em 4/5
    para sempre — "quase pronto" sem nada que o servidor pudesse fazer a
    respeito.
    """
    assert processos.documentos_do_processo(_processo()) == (
        "dfd", "etp", "tr", "edital")


def test_processo_com_registro_de_precos_inclui_a_ata():
    proc = _processo(dados={"modelo_execucao": "Sistema de Registro de Preços"})
    assert "arp" in processos.documentos_do_processo(proc)


# ---------------------------------------------------------------------------
# Progresso
# ---------------------------------------------------------------------------
def test_progresso_conta_aprovados_e_nao_gerados():
    """
    Documento gerado e não revisado NÃO é trabalho concluído — é
    trabalho esperando conferência humana, que é o que o produto existe
    para não deixar passar.
    """
    proc = _processo(documentos={"dfd": "texto", "etp": "texto"},
                     aprovados=["dfd"])
    assert processos.progresso(proc) == (1, 4)


def test_progresso_do_processo_vazio():
    assert processos.progresso(_processo()) == (0, 4)


def test_progresso_completo():
    proc = _processo(aprovados=["dfd", "etp", "tr", "edital"])
    assert processos.progresso(proc) == (4, 4)


# ---------------------------------------------------------------------------
# Etapa atual
# ---------------------------------------------------------------------------
def test_etapa_atual_aponta_o_primeiro_documento_que_falta():
    proc = _processo(aprovados=["dfd"])
    assert processos.etapa_atual(proc) == "ETP — a elaborar"


def test_etapa_atual_distingue_gerado_de_nao_gerado():
    """
    "Aguardando revisão" e "a elaborar" pedem ações diferentes do
    servidor: uma é ler, a outra é escrever. Dizer só "ETP" deixaria ele
    abrir a tela para descobrir qual das duas.
    """
    proc = _processo(documentos={"dfd": "texto"})
    assert processos.etapa_atual(proc) == "DFD — aguardando revisão"


def test_etapa_atual_ignora_o_cursor_do_wizard_e_olha_o_que_falta():
    """
    `etapa` diz onde o cursor parou; o servidor quer saber o que falta.
    Os dois divergem quando alguém volta para revisar algo anterior.
    """
    proc = _processo(etapa=3, aprovados=["dfd"])
    assert processos.etapa_atual(proc) == "ETP — a elaborar"


def test_etapa_atual_quando_tudo_esta_aprovado():
    proc = _processo(aprovados=["dfd", "etp", "tr", "edital"])
    assert processos.etapa_atual(proc) == "Todos os documentos aprovados"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def test_status_de_processo_novo():
    assert processos.status(_processo()) == processos.EM_ELABORACAO


def test_status_em_revisao_quando_ha_documento_gerado_sem_aprovacao():
    proc = _processo(documentos={"dfd": "texto"})
    assert processos.status(proc) == processos.EM_REVISAO


def test_status_concluido_quando_todos_os_obrigatorios_estao_aprovados():
    proc = _processo(aprovados=["dfd", "etp", "tr", "edital"])
    assert processos.status(proc) == processos.CONCLUIDO


def test_status_aguardando_precos():
    """Há itens para cotar, o DFD saiu, e o ETP depende do valor."""
    proc = _processo(dados={"itens": [{"descricao": "caneta"}]},
                     aprovados=["dfd"])
    assert processos.status(proc) == processos.AGUARDANDO_PRECOS


def test_pesquisa_ja_aplicada_nao_deixa_o_processo_aguardando_preco():
    proc = _processo(
        dados={"itens": [{"descricao": "caneta"}], "pesquisa_preco_id": "x"},
        aprovados=["dfd"])
    assert processos.status(proc) != processos.AGUARDANDO_PRECOS


def test_sem_itens_o_status_nunca_menciona_pesquisa_de_precos():
    """
    Com o módulo de preços desligado, ou num processo sem planilha, a
    tela não pode prometer uma etapa que o sistema não vai executar.
    """
    proc = _processo(aprovados=["dfd"])
    assert processos.status(proc) != processos.AGUARDANDO_PRECOS


def test_arquivado_vence_qualquer_outro_status():
    """Arquivado é arquivado mesmo incompleto — a decisão foi humana."""
    proc = _processo(arquivado=True, documentos={"dfd": "t"})
    assert processos.status(proc) == processos.ARQUIVADO


def test_concluido_vence_em_revisao():
    """
    Com tudo aprovado, um texto pendente de edição não devolve o
    processo para "em revisão": a aprovação é o ato que fecha.
    """
    proc = _processo(documentos={"dfd": "t", "etp": "t", "tr": "t",
                                 "edital": "t"},
                     aprovados=["dfd", "etp", "tr", "edital"])
    assert processos.status(proc) == processos.CONCLUIDO


# ---------------------------------------------------------------------------
# Nome
# ---------------------------------------------------------------------------
def test_nome_proprio_tem_precedencia():
    assert processos.nome_exibido(_processo(nome="Canetas 2027")) == \
        "Canetas 2027"


def test_sem_nome_mostra_orgao_e_objeto_que_o_servidor_escreveu():
    """
    Nunca um rótulo inventado: "Processo 3" não ajuda a encontrar nada, e
    um nome que o servidor não digitou o faria procurar por um texto que
    nunca escreveu.
    """
    esperado = "Prefeitura de Exemplo — Aquisição de material de expediente"
    assert processos.nome_exibido(_processo()) == esperado


def test_nome_so_com_espacos_conta_como_ausente():
    assert processos.nome_exibido(_processo(nome="   ")) == \
        "Prefeitura de Exemplo — Aquisição de material de expediente"


def test_processo_sem_nada_ainda_tem_rotulo():
    vazio = {"id": "x", "dados": {}, "documentos": {}, "aprovados": []}
    assert processos.nome_exibido(vazio) == "Processo sem nome"


# ---------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------
def test_data_legivel():
    assert processos.data_legivel("2026-09-10T15:30:00+00:00") == \
        "10/09/2026 15:30"


def test_data_ausente_vira_travessao():
    assert processos.data_legivel(None) == "—"


def test_data_em_formato_inesperado_nao_derruba_a_lista():
    """O painel existe para mostrar processos, não para validar carimbo."""
    assert processos.data_legivel("10 de setembro") == "10 de setembro"


# ---------------------------------------------------------------------------
# Busca e ordenação
# ---------------------------------------------------------------------------
def test_busca_ignora_acento_e_caixa():
    """Quem digita "aquisicao" espera achar "Aquisição"."""
    lista = [_processo()]
    assert processos.filtrar(lista, "AQUISICAO") == lista


def test_busca_alcanca_nome_orgao_e_objeto():
    lista = [_processo(nome="Canetas 2027")]
    assert processos.filtrar(lista, "canetas")
    assert processos.filtrar(lista, "prefeitura")
    assert processos.filtrar(lista, "expediente")


def test_busca_vazia_devolve_tudo():
    lista = [_processo(), _processo(id="p2")]
    assert len(processos.filtrar(lista, "   ")) == 2


def test_busca_sem_correspondencia_devolve_vazio():
    assert processos.filtrar([_processo()], "veículo") == []


def test_ordenacao_por_status_segue_a_precedencia_e_nao_o_alfabeto():
    """
    Alfabética colocaria "Arquivado" no topo e "Aguardando" antes de
    "Concluído" por acaso. A ordem certa é a da ação pendente.
    """
    concluido = _processo(id="c", aprovados=["dfd", "etp", "tr", "edital"])
    elaborando = _processo(id="e")
    aguardando = _processo(id="a", dados={"itens": [{"d": 1}]},
                           aprovados=["dfd"])
    ordenados = processos.ordenar([concluido, elaborando, aguardando],
                                  "status")
    assert [p["id"] for p in ordenados] == ["a", "e", "c"]


def test_ordenacao_por_data_traz_o_mais_recente_primeiro():
    antigo = _processo(id="antigo", atualizado_em="2026-01-01T00:00:00")
    novo = _processo(id="novo", atualizado_em="2026-09-14T00:00:00")
    assert [p["id"] for p in processos.ordenar([antigo, novo])] == \
        ["novo", "antigo"]


# ---------------------------------------------------------------------------
# Resumo — o que a linha do painel consome
# ---------------------------------------------------------------------------
def test_resumo_traz_tudo_que_a_linha_precisa():
    proc = _processo(nome="Canetas 2027", documentos={"dfd": "t"},
                     aprovados=["dfd"])
    r = processos.resumo(proc)
    assert r["nome"] == "Canetas 2027"
    assert r["nome_proprio"] == "Canetas 2027"
    assert r["progresso"] == (1, 4)
    assert r["progresso_fracao"] == pytest.approx(0.25)
    assert r["criado_em"] == "01/09/2026 10:00"
    assert r["status"] == processos.EM_ELABORACAO


def test_resumo_nunca_divide_por_zero():
    """Processo sem documento obrigatório nenhum não pode derrubar a tela."""
    r = processos.resumo({"id": "x", "dados": {"modelo_execucao": ""},
                          "documentos": {}, "aprovados": []})
    assert r["progresso_fracao"] == 0.0
