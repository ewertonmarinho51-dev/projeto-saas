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
