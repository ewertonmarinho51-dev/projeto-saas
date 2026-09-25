"""Validação automática antes da emissão + perfis de cláusula."""

from src import perfis, validacao


def test_placeholder_bloqueia():
    achados = validacao.validar_documento(
        "dfd", "## 1. INFORMAÇÕES GERAIS\n\nSetor: [PREENCHER: setor].")
    blq = validacao.bloqueios(achados)
    assert blq and "PREENCHER" in blq[0]["mensagem"]


def test_marcador_interno_bloqueia():
    achados = validacao.validar_documento("etp", "## 7. QUANTITATIVO\n\n[[TABELA_ITENS]]")
    assert validacao.bloqueios(achados)


def test_mencao_a_sistema_bloqueia():
    achados = validacao.validar_documento(
        "tr", "Conforme o formulário-matriz preenchido, o objeto é X.")
    assert validacao.bloqueios(achados)


def test_documento_limpo_nao_bloqueia():
    texto = "## 1. DO OBJETO\n\n1.1. Aquisição de material de expediente."
    assert not validacao.bloqueios(validacao.validar_documento("tr", texto))


def test_numeracao_duplicada_e_salto_avisam():
    texto = (
        "## 1. DO OBJETO\n\nx\n\n## 1. DO OBJETO DE NOVO\n\ny\n\n"
        "## 4. QUARTA\n\nz"
    )
    msgs = [a["mensagem"] for a in validacao.validar_documento("edital", texto)]
    assert any("duplicada" in m for m in msgs)
    assert any("salto" in m for m in msgs)


def test_titulo_sem_conteudo_avisa():
    texto = "## 1. DO OBJETO\n\n## 2. SEGUNDA\n\ntexto"
    msgs = [a["mensagem"] for a in validacao.validar_documento("edital", texto)]
    assert any("sem conteúdo" in m for m in msgs)


def test_documento_raso_avisa():
    texto = "## 1. INFORMAÇÕES GERAIS\n\ncurto."
    msgs = [a["mensagem"] for a in validacao.validar_documento("etp", texto)]
    assert any("raso" in m for m in msgs)


def test_clausula_obrigatoria_ausente_avisa():
    # ETP sem "DESCRIÇÃO DOS REQUISITOS" deve alertar
    texto = "\n\n".join(
        f"## {c['n']}. {c['titulo']}\n\nconteúdo " + "x " * 400
        for c in perfis.PERFIS["etp"]["clausulas"] if c["n"] != 4
    )
    msgs = [a["mensagem"] for a in validacao.validar_documento("etp", texto)]
    assert any("REQUISITOS" in m for m in msgs)


# ---------------------------------------------------------------------------
# Perfis
# ---------------------------------------------------------------------------
def test_perfis_seguem_documentos_manuais():
    assert len(perfis.PERFIS["dfd"]["clausulas"]) == 9
    assert len(perfis.PERFIS["etp"]["clausulas"]) == 18
    assert len(perfis.PERFIS["tr"]["clausulas"]) == 17
    titulos_etp = [c["titulo"] for c in perfis.PERFIS["etp"]["clausulas"]]
    assert "LEVANTAMENTO DE SOLUÇÕES" in titulos_etp
    assert "DESCRIÇÃO DOS REQUISITOS DA CONTRATAÇÃO" in titulos_etp


def test_estrutura_para_prompt_tem_metas():
    bloco = perfis.estrutura_para_prompt("tr")
    assert "DO OBJETO" in bloco and "blocos" in bloco
    assert "muito alta" in bloco
    # cláusula condicional de SRP só entra com srp=True
    assert "RENOVAÇÃO DO QUANTITATIVO" not in bloco
    assert "RENOVAÇÃO DO QUANTITATIVO" in perfis.estrutura_para_prompt("tr", srp=True)


def test_prompt_usa_estrutura_dos_manuais():
    from src import prompts

    _, user = prompts.montar_prompt("etp", {"orgao": "X", "objeto": "Y"}, "DFD ap.")
    assert "LEVANTAMENTO DE SOLUÇÕES" in user
    assert "POSICIONAMENTO CONCLUSIVO" in user
    _, user_dfd = prompts.montar_prompt("dfd", {"orgao": "X", "objeto": "Y"}, None)
    assert "NECESSIDADE OU OPORTUNIDADE DE MELHORIA" in user_dfd


# ---------------------------------------------------------------------------
# Valor global afirmado na PROSA — achado da auditoria pré-operacional
#
# A tabela emitida já era conferida item a item contra a planilha. A
# prosa não era: um DFD que escrevia "valor global estimado de R$ 1,00"
# num processo de R$ 167.774,50 saía sem um único achado bloqueante,
# porque a tabela ao lado estava certa e ninguém confrontava as duas.
#
# É a classe de erro que um modelo comete com mais facilidade — o número
# da tabela entra por injeção de código e está sempre certo; o número
# escrito no meio do texto vem do modelo.
#
# As provas abaixo cobrem tanto o que a checagem PEGA quanto o que ela
# NÃO pode pegar: bloqueio com falso positivo pararia documento legítimo,
# que é pior do que a ausência da checagem.
# ---------------------------------------------------------------------------
ITENS_DE_PROVA = [
    {"item": "1", "codigo": "001", "descricao": "Caneta", "unidade": "UN",
     "quantidade": 100, "valor_unitario": 2.50},
    {"item": "2", "codigo": "002", "descricao": "Papel", "unidade": "RESMA",
     "quantidade": 10, "valor_unitario": 25.00},
]
GLOBAL_DE_PROVA = "R$ 500,00"          # 100×2,50 + 10×25,00


def _validar(texto: str):
    """
    Só os achados DESTA checagem.

    Os trechos de prova não trazem a tabela de itens, e a conferência da
    tabela — outra checagem, com outro teste — bloquearia sempre. Sem o
    filtro, as provas abaixo passariam pelo motivo errado, e as que
    exigem AUSÊNCIA de bloqueio nunca poderiam passar.
    """
    return [a for a in validacao.validar_documento(
                "dfd", texto, dados={"itens": ITENS_DE_PROVA})
            if "valor global afirmado no texto" in a["mensagem"]]


def test_valor_global_divergente_na_prosa_bloqueia():
    texto = ("## 4. ESTIMATIVA\n\nA contratação tem valor global estimado "
             "de R$ 1,00.")
    blq = validacao.bloqueios(_validar(texto))
    assert blq, "valor global inventado passou sem bloqueio"
    assert "R$ 500,00" in blq[0]["mensagem"], (
        "a mensagem precisa dizer qual é o valor CERTO — senão o servidor "
        "sabe que há erro e não sabe o que corrigir")


def test_valor_global_correto_na_prosa_nao_bloqueia():
    """
    A mutação que importa: uma checagem que bloqueasse sempre também
    faria o primeiro teste passar, e pararia todo documento correto.
    """
    texto = (f"## 4. ESTIMATIVA\n\nA contratação tem valor global estimado "
             f"de {GLOBAL_DE_PROVA}.")
    assert not validacao.bloqueios(_validar(texto))


def test_valor_de_item_solto_na_prosa_nao_e_tratado_como_total():
    """
    Um "R$" no texto não é afirmação de total. Bloquear por ele pararia
    documento legítimo — por exemplo, o preço unitário citado numa
    justificativa.
    """
    texto = ("## 3. JUSTIFICATIVA\n\nO preço unitário da caneta, de "
             "R$ 2,50, está abaixo da média praticada.")
    assert not validacao.bloqueios(_validar(texto))


def test_o_valor_dentro_da_tabela_nao_e_conferido_duas_vezes():
    """
    A linha de tabela tem conferência própria, item a item. Conferi-la
    aqui de novo produziria dois achados para o mesmo problema — e um
    relatório que conta o mesmo defeito duas vezes deixa de servir para
    medir.
    """
    texto = ("## 4. ITENS\n\n| Código | Descrição | Valor Total |\n"
             "|---|---|---|\n"
             "|  |  | **VALOR GLOBAL** R$ 999,00 |\n")
    achados = [a for a in _validar(texto)
               if "valor global afirmado no texto" in a["mensagem"]]
    assert not achados


def test_sem_planilha_na_sessao_a_checagem_nao_opina():
    """
    Documento importado ou revisado fora do fluxo não tem planilha. Sem
    fonte para comparar, afirmar divergência seria inventar achado.
    """
    texto = "## 4. ESTIMATIVA\n\nValor global estimado de R$ 1,00."
    achados = validacao.validar_documento("dfd", texto, dados=None)
    assert not [a for a in achados
                if "valor global afirmado no texto" in a["mensagem"]]
