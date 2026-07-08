"""Testes da planilha orçamentária (cálculo de totais e valor global)."""

from src import planilha, prompts


def test_calcula_total_por_item_e_valor_global():
    itens = [
        {"codigo": "1", "descricao": "Notebook", "unidade": "un",
         "quantidade": 10, "valor_unitario": 4500.0},
        {"codigo": "2", "descricao": "Monitor", "unidade": "un",
         "quantidade": 10, "valor_unitario": 900.0},
    ]
    calculados, global_ = planilha.calcular(itens)
    assert calculados[0]["valor_total"] == 45000.0
    assert calculados[1]["valor_total"] == 9000.0
    assert global_ == 54000.0


def test_ignora_linhas_vazias_ou_incompletas():
    itens = [
        {"descricao": "", "quantidade": 0, "valor_unitario": 0},          # vazia
        {"descricao": "Serviço", "quantidade": 0, "valor_unitario": 0},   # sem valor
        {"descricao": "Cadeira", "quantidade": 5, "valor_unitario": 200},  # válida
    ]
    calculados, global_ = planilha.calcular(itens)
    assert len(calculados) == 1
    assert global_ == 1000.0


def test_valores_invalidos_nao_quebram():
    itens = [{"descricao": "X", "quantidade": "abc", "valor_unitario": None}]
    calculados, global_ = planilha.calcular(itens)
    assert calculados == [] and global_ == 0.0


def test_formatar_moeda_padrao_brasileiro():
    assert planilha.formatar_moeda(1234567.89) == "R$ 1.234.567,89"
    assert planilha.formatar_moeda(0) == "R$ 0,00"


def test_markdown_tem_cabecalho_itens_e_valor_global():
    itens, global_ = planilha.calcular(
        [{"descricao": "Notebook", "quantidade": 2, "valor_unitario": 5000}]
    )
    md = planilha.para_markdown(itens, global_)
    assert "| Código | Descrição |" in md
    assert "Notebook" in md
    assert "VALOR GLOBAL" in md and "R$ 10.000,00" in md


def test_prompt_inclui_a_planilha():
    dados = {
        "orgao": "Prefeitura X", "objeto": "Aquisição",
        "itens": [{"descricao": "Notebook", "quantidade": 2, "valor_unitario": 5000}],
    }
    bloco = prompts.formatar_dados_formulario(dados)
    assert "VALOR GLOBAL" in bloco and "Notebook" in bloco
    assert "R$ 10.000,00" in bloco
