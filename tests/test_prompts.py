"""Testes da montagem de prompts: memorando, hierarquia de fontes e RAG."""

from src import prompts


DADOS = {
    "orgao": "Prefeitura X",
    "objeto": "Aquisição de material de expediente",
    "justificativa": "Reposição de estoque",
    "itens": [{"descricao": "Caneta", "quantidade": 100, "valor_unitario": 1.5}],
}


def test_system_prompt_tem_hierarquia_e_modelo():
    sp = prompts.SYSTEM_PROMPT_BASE
    assert "HIERARQUIA DE FONTES" in sp
    assert "pegue este documento como modelo" in sp.lower()
    # não transportar dados concretos de outro processo
    assert "NUNCA transporte" in sp or "PROIBIDO" in sp
    # sem menção à mecânica interna nos documentos + profundidade controlada
    assert "NUNCA mencione" in sp
    assert "Profundidade" in sp


def test_memorando_entra_em_bloco_proprio():
    dados = dict(DADOS, memorando="Memorando 123: solicita canetas para a Secretaria de Saúde.")
    _, user = prompts.montar_prompt("dfd", dados, None)
    assert "MEMORANDO/OFÍCIO DO PROCESSO ATUAL" in user
    assert "Secretaria de Saúde" in user
    # não deve aparecer duplicado dentro do bloco do formulário
    assert user.count("Secretaria de Saúde") == 1


def test_formatar_dados_nao_inclui_memorando():
    dados = dict(DADOS, memorando="texto do memorando")
    bloco = prompts.formatar_dados_formulario(dados)
    assert "texto do memorando" not in bloco
    # mas inclui os demais campos
    assert "Prefeitura X" in bloco


def test_sem_memorando_nao_cria_bloco():
    _, user = prompts.montar_prompt("dfd", DADOS, None)
    assert "MEMORANDO/OFÍCIO" not in user


def test_contexto_anterior_ainda_entra():
    _, user = prompts.montar_prompt("etp", DADOS, "TEXTO DO DFD APROVADO")
    assert "DFD APROVADO" in user and "TEXTO DO DFD APROVADO" in user
