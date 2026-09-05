"""
Fase 5 — aplicação da pesquisa ao processo.

É a fase em que um resultado de pesquisa vira **valor da contratação**.
As provas aqui giram em torno das quatro maneiras de errar isso:

1. escrever o preço no item errado (casamento por posição cega);
2. alterar o processo sem o servidor ver o que muda (§26);
3. despejar a pesquisa dentro da tabela do documento (§27);
4. deixar a proveniência afirmando algo que já não é verdade.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import consistencia, db, fatos, planilha
from src.precos import aplicacao
from src.precos import repositorio as repo
from src.precos.estados import EstadoItem, EstadoPesquisa
from tests.conftest import ClientePrecosFalso

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _pesquisa(**extras) -> dict:
    base = {
        "id": "pesq-1", "versao": 1, "nome": "Material de expediente",
        "estado": EstadoPesquisa.CONCLUIDA.value,
        "perfil_normativo": "lei_14133", "data_base": "2026-09-01",
        "processo_id": "proc-1",
    }
    base.update(extras)
    return base


def _item_pesquisa(numero=1, descricao="CANETA ESFEROGRAFICA AZUL",
                   **extras) -> dict:
    base = {
        "id": f"item-{numero}", "numero": numero, "descricao": descricao,
        "codigo": "236168", "tipo_catalogo": "CATMAT", "unidade": "UNIDADE",
        "quantidade": "100", "estado": EstadoItem.COMPLETO.value,
        "metodo": "mediana", "preco_estimado": "2.35",
        "preco_total": "235.00",
        "estatisticas": {"estatisticas": {"quantidade": 30}},
    }
    base.update(extras)
    return base


def _dados(itens=None) -> dict:
    return {
        "orgao": "Prefeitura", "objeto": "Aquisição de material",
        "itens": itens if itens is not None else [{
            "codigo": "236168", "descricao": "CANETA ESFEROGRAFICA AZUL",
            "unidade": "UNIDADE", "quantidade": 100, "valor_unitario": 0.0,
        }],
    }


# ===========================================================================
# Casamento — a defesa contra escrever no item errado
# ===========================================================================
def test_casa_por_descricao_normalizada():
    """Acento, caixa e espaço repetido não podem impedir o casamento."""
    dados = _dados([{"descricao": "  caneta   Esferográfica  AZUL ",
                     "unidade": "UNIDADE", "quantidade": 10,
                     "valor_unitario": 0.0}])
    casamentos = aplicacao.casar(dados["itens"], [_item_pesquisa()])
    assert casamentos[0].confere


def test_casa_por_codigo_de_catalogo():
    dados = _dados([{"codigo": "236168", "descricao": "CANETA ESFEROGRAFICA AZUL",
                     "unidade": "UNIDADE", "quantidade": 10,
                     "valor_unitario": 0.0}])
    casamentos = aplicacao.casar(dados["itens"], [_item_pesquisa()])
    assert casamentos[0].confere
    assert casamentos[0].item_pesquisa is not None


def test_nao_casa_por_posicao():
    """
    A defesa central desta fase.

    A planilha ganhou uma linha nova no topo depois que a pesquisa foi
    criada. Casar por índice escreveria o preço da caneta no item novo —
    em silêncio, e com aparência de correção.
    """
    dados = _dados([
        {"descricao": "ITEM INSERIDO DEPOIS", "unidade": "UN",
         "quantidade": 1, "valor_unitario": 5.0},
        {"descricao": "CANETA ESFEROGRAFICA AZUL", "unidade": "UNIDADE",
         "quantidade": 100, "valor_unitario": 0.0},
    ])
    casamentos = aplicacao.casar(dados["itens"], [_item_pesquisa()])
    assert not casamentos[0].confere          # o intruso NÃO recebe preço
    assert casamentos[1].confere              # a caneta recebe
    assert "não há item correspondente" in casamentos[0].motivo


def test_um_item_da_pesquisa_nao_serve_a_duas_linhas():
    """
    Duas linhas iguais na planilha não podem receber o mesmo preço sem
    que alguém veja: a segunda vira recusa nomeada.
    """
    dados = _dados([
        {"descricao": "CANETA ESFEROGRAFICA AZUL", "unidade": "UNIDADE",
         "quantidade": 100, "valor_unitario": 0.0},
        {"descricao": "CANETA ESFEROGRAFICA AZUL", "unidade": "UNIDADE",
         "quantidade": 50, "valor_unitario": 0.0},
    ])
    casamentos = aplicacao.casar(dados["itens"], [_item_pesquisa()])
    assert casamentos[0].confere
    assert not casamentos[1].confere
    assert "já foi usado" in casamentos[1].motivo


@pytest.mark.parametrize("alteracao,trecho", [
    ({"estado": EstadoItem.EM_REVISAO.value}, "não está concluído"),
    ({"preco_estimado": None}, "não tem preço formado"),
    ({"unidade": "CAIXA"}, "a unidade diverge"),
])
def test_o_que_nao_confere_nao_e_aplicado(alteracao, trecho):
    casamentos = aplicacao.casar(
        _dados()["itens"], [_item_pesquisa(**alteracao)])
    assert not casamentos[0].confere
    assert trecho in casamentos[0].motivo


def test_descricao_alterada_depois_da_pesquisa_bloqueia():
    """
    Código igual e descrição completamente diferente é sinal de que
    alguém editou a planilha. Escrever o preço nesse caso é o erro mais
    caro possível desta tela.
    """
    dados = _dados([{"codigo": "236168", "descricao": "GRAMPEADOR DE MESA",
                     "unidade": "UNIDADE", "quantidade": 10,
                     "valor_unitario": 0.0}])
    casamentos = aplicacao.casar(dados["itens"], [_item_pesquisa()])
    assert not casamentos[0].confere
    assert "descrição do item mudou" in casamentos[0].motivo


def test_item_sem_preco_no_processo_nao_bloqueia_o_resto():
    """Uma recusa não derruba as demais aplicações."""
    dados = _dados([
        {"descricao": "CANETA ESFEROGRAFICA AZUL", "unidade": "UNIDADE",
         "quantidade": 100, "valor_unitario": 0.0},
        {"descricao": "ITEM SEM PESQUISA", "unidade": "UN",
         "quantidade": 2, "valor_unitario": 7.0},
    ])
    _, mudancas, recusas = aplicacao.aplicar(
        dados, _pesquisa(), [_item_pesquisa()])
    assert len(mudancas) == 1 and len(recusas) == 1


# ===========================================================================
# Diff (§26)
# ===========================================================================
def test_quantidade_divergente_avisa_mas_nao_impede():
    """
    O preço UNITÁRIO continua válido; o total é recalculado pela
    quantidade da planilha, que é a do processo. Mas o servidor precisa
    saber.
    """
    dados = _dados([{"descricao": "CANETA ESFEROGRAFICA AZUL",
                     "unidade": "UNIDADE", "quantidade": 120,
                     "valor_unitario": 0.0}])
    _, mudancas, recusas = aplicacao.aplicar(
        dados, _pesquisa(), [_item_pesquisa()])
    assert not recusas
    assert any("recalculado pela quantidade da planilha" in a
               for a in mudancas[0].avisos)
    assert mudancas[0].total_novo == Decimal("282.00")


def test_fonte_digitada_a_mao_sera_substituida_e_isso_e_dito():
    dados = _dados([{"descricao": "CANETA ESFEROGRAFICA AZUL",
                     "unidade": "UNIDADE", "quantidade": 100,
                     "valor_unitario": 0.0,
                     planilha.CAMPO_FONTE: "https://exemplo.gov.br/antigo"}])
    _, mudancas, _ = aplicacao.aplicar(dados, _pesquisa(), [_item_pesquisa()])
    assert any("informada à mão será substituída" in a
               for a in mudancas[0].avisos)


def test_o_diff_mostra_o_valor_global_de_depois():
    dados = _dados([
        {"descricao": "CANETA ESFEROGRAFICA AZUL", "unidade": "UNIDADE",
         "quantidade": 100, "valor_unitario": 0.0},
        {"descricao": "OUTRO", "unidade": "UN", "quantidade": 2,
         "valor_unitario": 10.0},
    ])
    _, mudancas, _ = aplicacao.aplicar(dados, _pesquisa(), [_item_pesquisa()])
    # 100 × 2,35 (novo) + 2 × 10,00 (inalterado)
    assert aplicacao.valor_global_apos(dados, mudancas) == Decimal("255.00")


# ===========================================================================
# Aplicação
# ===========================================================================
def test_aplicar_nao_toca_no_original():
    """
    A tela mostra o diff e o usuário pode desistir. Um `dados` mutado no
    meio do caminho deixaria o processo alterado por uma confirmação que
    nunca veio.
    """
    dados = _dados()
    antes = dados["itens"][0]["valor_unitario"]
    novos, _, _ = aplicacao.aplicar(dados, _pesquisa(), [_item_pesquisa()])
    assert dados["itens"][0]["valor_unitario"] == antes
    assert novos["itens"][0]["valor_unitario"] == 2.35
    assert aplicacao.CHAVE_PROVENIENCIA not in dados


def test_o_total_sai_da_planilha_e_nao_de_conta_feita_aqui():
    """
    Dois lugares calculando dinheiro é como eles passam a discordar. O
    valor global vem de `planilha.calcular`.
    """
    dados = _dados()
    novos, _, _ = aplicacao.aplicar(dados, _pesquisa(), [_item_pesquisa()])
    _, esperado = planilha.calcular(novos["itens"])
    assert novos["valor_estimado"] == esperado == 235.0
    assert novos["itens"][0]["valor_total"] == 235.0


def test_o_item_recebe_o_ponteiro_da_fonte():
    novos, _, _ = aplicacao.aplicar(_dados(), _pesquisa(), [_item_pesquisa()])
    fonte = novos["itens"][0][planilha.CAMPO_FONTE]
    assert "Pesquisa de preços" in fonte and "mediana" in fonte and "n=30" in fonte


def test_a_revisao_aparece_no_ponteiro():
    """
    Dois documentos do mesmo processo podem ter saído de revisões
    diferentes da mesma pesquisa. Sem o número, não há como saber qual
    sustentou qual.
    """
    novos, _, _ = aplicacao.aplicar(
        _dados(), _pesquisa(versao=3), [_item_pesquisa()])
    assert "rev. 3" in novos["itens"][0][planilha.CAMPO_FONTE]


# ===========================================================================
# §27 — a pesquisa NÃO entra na tabela do documento
# ===========================================================================
def test_a_proveniencia_nao_vira_coluna_da_tabela():
    """
    A prova mais importante desta fase para o documento final.

    `planilha.colunas_extra` transforma QUALQUER chave nova do item numa
    coluna da tabela exportada. Se a memória da pesquisa fosse gravada
    como campo de item, todo DFD, ETP, TR e edital passaria a exibir
    colunas de score, método e identificadores — exatamente o que o §27
    proíbe: "DFD, ETP e TR não devem reproduzir toda a pesquisa".
    """
    novos, _, _ = aplicacao.aplicar(_dados(), _pesquisa(), [_item_pesquisa()])

    extras = planilha.colunas_extra(novos["itens"])
    assert extras == [planilha.CAMPO_FONTE], extras

    tabela = planilha.para_markdown(novos["itens"], novos["valor_estimado"])
    cabecalho = tabela.splitlines()[0]
    assert "Fonte" in cabecalho
    for proibido in ("pesquisa_preco", "score", "metodologia", "perfil",
                     "raiz_id", "versao_algoritmo"):
        assert proibido not in tabela, proibido


def test_a_proveniencia_fica_fora_dos_itens():
    novos, _, _ = aplicacao.aplicar(_dados(), _pesquisa(), [_item_pesquisa()])
    assert aplicacao.CHAVE_PROVENIENCIA in novos
    assert all(aplicacao.CHAVE_PROVENIENCIA not in item
               for item in novos["itens"])


def test_o_objeto_estruturado_tem_o_que_o_processo_precisa():
    """§27: pequeno de propósito. A memória completa fica na pesquisa."""
    novos, _, _ = aplicacao.aplicar(
        _dados(), _pesquisa(versao=2), [_item_pesquisa()])
    proveniencia = novos[aplicacao.CHAVE_PROVENIENCIA]
    assert proveniencia["id"] == "pesq-1"
    assert proveniencia["versao"] == 2
    assert proveniencia["metodologia"] == "mediana"
    assert proveniencia["perfil_normativo"] == "lei_14133"
    assert proveniencia["itens_aplicados"] == 1
    # nada de referências, scores ou payloads
    assert "referencias" not in proveniencia
    assert "fatores" not in proveniencia


# ===========================================================================
# Conferência posterior
# ===========================================================================
def test_logo_apos_aplicar_nao_ha_divergencia():
    """
    A primeira versão desta conferência comparava o total do PROCESSO
    com o total da PESQUISA — grandezas diferentes sempre que o processo
    tem item não coberto ou quantidade divergente. Ela acenderia em
    quase toda aplicação real, e alerta que acende sempre é ignorado.
    """
    dados = _dados([
        {"descricao": "CANETA ESFEROGRAFICA AZUL", "unidade": "UNIDADE",
         "quantidade": 120, "valor_unitario": 0.0},
        {"descricao": "ITEM FORA DA PESQUISA", "unidade": "UN",
         "quantidade": 3, "valor_unitario": 8.0},
    ])
    novos, _, _ = aplicacao.aplicar(dados, _pesquisa(), [_item_pesquisa()])
    assert aplicacao.divergencia_do_valor(novos) is None


def test_editar_a_planilha_depois_acende_o_alerta():
    novos, _, _ = aplicacao.aplicar(_dados(), _pesquisa(), [_item_pesquisa()])
    novos["valor_estimado"] = 999.0
    aviso = aplicacao.divergencia_do_valor(novos)
    assert aviso and "mudou depois" in aviso


def test_sem_pesquisa_aplicada_nao_ha_o_que_conferir():
    assert aplicacao.divergencia_do_valor(_dados()) is None


# ===========================================================================
# Fatos canônicos e consistência
# ===========================================================================
def test_a_pesquisa_aplicada_vira_fato_canonico():
    novos, _, _ = aplicacao.aplicar(
        _dados(), _pesquisa(versao=2, perfil_normativo="in_65_2021"),
        [_item_pesquisa()])
    lista = fatos.extrair_do_formulario(novos, "proc-1")
    paths = {f["path"]: f for f in lista}

    assert paths["pesquisa_preco.id"]["valor"] == "pesq-1"
    assert paths["pesquisa_preco.versao"]["valor"] == 2.0
    assert paths["pesquisa_preco.metodologia"]["valor"] == "mediana"
    assert paths["pesquisa_preco.perfil"]["valor"] == "in_65_2021"
    assert paths["pesquisa_preco.valor_aplicado"]["valor"] == 235.0


def test_o_fato_da_pesquisa_nao_e_inferencia():
    """
    Uma INFERÊNCIA não vincula sozinha (ver `conhecimento`). A aplicação
    da pesquisa não é deduzida: é o registro de um ato praticado, e a
    fonte precisa dizer isso.
    """
    novos, _, _ = aplicacao.aplicar(_dados(), _pesquisa(), [_item_pesquisa()])
    lista = fatos.extrair_do_formulario(novos, "proc-1")
    fato = next(f for f in lista if f["path"] == "pesquisa_preco.id")
    assert fato["fonte"].startswith("pesquisa_preco:")
    assert not fato["fonte"].startswith("inferencia")
    assert fato["confianca"] >= 0.9


def test_processo_sem_pesquisa_nao_ganha_fatos_de_pesquisa():
    lista = fatos.extrair_do_formulario(_dados(), "proc-1")
    assert not [f for f in lista if f["path"].startswith("pesquisa_preco")]


def test_a_consistencia_cala_logo_apos_aplicar():
    novos, _, _ = aplicacao.aplicar(_dados(), _pesquisa(), [_item_pesquisa()])
    lista = fatos.extrair_do_formulario(novos, "proc-1")
    achados = consistencia.verificar(lista, {"dfd": "# DFD\n\nTexto."})
    assert not [a for a in achados
                if a["categoria"] == "consistencia_pesquisa_preco"]


def test_a_consistencia_acusa_a_edicao_posterior():
    novos, _, _ = aplicacao.aplicar(_dados(), _pesquisa(), [_item_pesquisa()])
    novos["itens"][0]["valor_unitario"] = 9.0
    novos["valor_estimado"] = 900.0

    lista = fatos.extrair_do_formulario(novos, "proc-1")
    achados = consistencia.verificar(lista, {"dfd": "# DFD\n\nTexto."})
    alvo = [a for a in achados
            if a["categoria"] == "consistencia_pesquisa_preco"]
    assert alvo, "a divergência não virou achado"
    achado = alvo[0]
    assert achado["severity"] == "HIGH"
    # O sistema NÃO escolhe qual valor está certo.
    assert achado["autoCorrectable"] is False
    assert achado["blockingReason"] == "UNRESOLVED_SOURCE_CONFLICT"


def test_a_categoria_nova_esta_declarada():
    assert "consistencia_pesquisa_preco" in consistencia.CATEGORIAS


# ===========================================================================
# Interface (§26) — nada silencioso
# ===========================================================================
def _semear(cliente: ClientePrecosFalso, *, estado, processo_id) -> dict:
    pesquisa = _pesquisa(estado=estado, processo_id=processo_id)
    pesquisa["tenant_id"] = db.TENANT_PADRAO
    pesquisa["auth_user_id"] = "u-1"
    pesquisa["filtros"] = {}
    pesquisa["valor_global"] = "235.00"
    item = dict(_item_pesquisa(), pesquisa_id="pesq-1",
                tenant_id=db.TENANT_PADRAO)
    cliente.tabelas["pesquisas_preco"] = [pesquisa]
    cliente.tabelas["pesquisa_preco_itens"] = [item]
    cliente.tabelas["pesquisa_preco_referencias"] = []
    cliente.tabelas["pesquisa_preco_eventos"] = []
    return pesquisa


def _app(monkeypatch, *, estado=EstadoPesquisa.CONCLUIDA.value,
         processo_da_pesquisa="proc-1", processo_aberto="proc-1",
         documentos=None) -> tuple[AppTest, ClientePrecosFalso]:
    from src.ui import precos_ui

    monkeypatch.setenv("GOVDOCS_MODO_ABERTO", "1")
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == repo.FLAG)
    cliente = ClientePrecosFalso()
    _semear(cliente, estado=estado, processo_id=processo_da_pesquisa)
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: cliente)

    at = AppTest.from_file(APP, default_timeout=90)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["pagina"] = "Pesquisa de Preços"
    at.session_state[precos_ui.TELA] = precos_ui.RESUMO
    at.session_state[precos_ui.PESQUISA] = "pesq-1"
    at.session_state["processo_id"] = processo_aberto
    at.session_state["dados"] = _dados()
    if documentos:
        at.session_state["documentos"] = dict(documentos)
        at.session_state["aprovados"] = set(documentos)
    return at, cliente


def test_a_tela_mostra_o_diff_antes_de_qualquer_escrita(monkeypatch):
    at, cliente = _app(monkeypatch)
    at.run()
    assert not at.exception

    metricas = {m.label: m.value for m in at.metric}
    assert metricas.get("Itens a atualizar") == "1"
    assert metricas.get("Valor global atual") == "R$ 0,00"
    assert metricas.get("Valor global depois") == "R$ 235,00"
    # e NADA foi escrito ainda
    assert at.session_state["dados"]["itens"][0]["valor_unitario"] == 0.0


def test_a_tela_nomeia_os_documentos_que_serao_descartados(monkeypatch):
    at, _ = _app(monkeypatch, documentos={"dfd": "# DFD", "etp": "# ETP"})
    at.run()
    assert not at.exception
    avisos = " ".join(w.value for w in at.warning)
    assert "DFD" in avisos and "ETP" in avisos
    assert "descartados" in avisos


@pytest.mark.parametrize("cenario,trecho", [
    ({"estado": EstadoPesquisa.EM_REVISAO.value}, "Conclua a pesquisa"),
    ({"processo_da_pesquisa": None}, "autônoma"),
    ({"processo_aberto": "outro-processo"}, "vinculada a outro processo"),
    ({"estado": EstadoPesquisa.APLICADA.value}, "já foi aplicada"),
])
def test_o_impedimento_e_explicado_em_texto(monkeypatch, cenario, trecho):
    """
    Botão cinza sem explicação faz o servidor procurar o defeito no
    lugar errado.
    """
    at, _ = _app(monkeypatch, **cenario)
    at.run()
    assert not at.exception
    textos = " ".join(i.value for i in at.info)
    assert trecho in textos, textos


def test_processo_diferente_nao_recebe_o_preco(monkeypatch):
    """
    A guarda contra o pior erro desta tela: escrever o preço na planilha
    de OUTRA contratação.
    """
    at, _ = _app(monkeypatch, processo_aberto="outro-processo")
    at.run()
    assert not at.exception
    # nenhum botão de aplicação foi sequer oferecido
    assert not [b for b in at.button
                if "Aplicar preços" in (b.label or "")]
    assert at.session_state["dados"]["itens"][0]["valor_unitario"] == 0.0


def test_aplicar_altera_o_processo_invalida_documentos_e_registra(monkeypatch):
    """
    O ato completo, ponta a ponta.

    Mede as quatro consequências que o §26 exige juntas: a planilha
    atualizada, o total recalculado, os documentos descartados para nova
    geração, e a trilha com o registro do que foi feito.
    """
    from src.ui import precos_ui

    at, cliente = _app(monkeypatch, documentos={"dfd": "# DFD antigo"})
    at.run()
    assert not at.exception

    # confirma o descarte e aplica
    caixa = [c for c in at.checkbox if "descartados" in (c.label or "")]
    assert caixa, "a confirmação de descarte não apareceu"
    caixa[0].check().run()
    botao = [b for b in at.button if "Aplicar preços" in (b.label or "")]
    assert botao, "o botão de aplicar não apareceu"
    botao[0].click().run()
    assert not at.exception

    dados = at.session_state["dados"]
    assert dados["itens"][0]["valor_unitario"] == 2.35
    assert dados["valor_estimado"] == 235.0
    assert dados["itens"][0]["valor_total"] == 235.0

    # proveniência gravada, e fora dos itens
    proveniencia = dados[precos_ui.aplicacao.CHAVE_PROVENIENCIA]
    assert proveniencia["id"] == "pesq-1"
    assert proveniencia["valor_global_aplicado"] == "235.00"

    # documento anterior descartado — a cascata é a do `state`
    assert "dfd" not in at.session_state["documentos"]
    assert "dfd" not in at.session_state["aprovados"]

    # pesquisa aplicada e trilha registrada
    assert cliente.tabelas["pesquisas_preco"][0]["estado"] == \
        EstadoPesquisa.APLICADA.value
    eventos = cliente.tabelas["pesquisa_preco_eventos"]
    assert [e["tipo"] for e in eventos] == ["pesquisa_aplicada"]
    assert eventos[0]["payload"]["itens"] == [1]


def test_aplicar_duas_vezes_nao_duplica_a_trilha(monkeypatch):
    """
    §43: a chave de idempotência do evento é a da aplicação. Uma segunda
    tentativa (duplo clique, rerun) não produz dois registros do mesmo
    ato.
    """
    at, cliente = _app(monkeypatch, documentos={"dfd": "# DFD"})
    at.run()
    caixa = [c for c in at.checkbox if "descartados" in (c.label or "")]
    caixa[0].check().run()
    [b for b in at.button if "Aplicar preços" in (b.label or "")][0].click().run()

    # segunda aplicação forçada, direto no repositório
    repo.registrar_evento("pesq-1", "pesquisa_aplicada",
                          idempotency_key="aplicacao:pesq-1")
    assert len(cliente.tabelas["pesquisa_preco_eventos"]) == 1
