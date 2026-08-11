"""
Testes do P1 — raciocínio do ETP, cláusulas condicionais pelo motor de
conhecimento e consistência semântica DFD → ETP → TR → Edital.

ETP-01..04   o estudo conclui a solução; não parte dela.
COND-01..05  cláusulas condicionais decididas por FATOS + REGRAS.
CONS-01..06  divergências de decisão detectadas sem exigir texto igual.

Cenários: bens (com e sem SRP), serviço contínuo com dedicação de mão de
obra e solução de TI — nada acoplado ao caso que originou o P0.
"""

import pytest

from src import conhecimento, consistencia, fatos, perfis, prompts, validacao

# ---------------------------------------------------------------------------
# Cenários sintéticos
# ---------------------------------------------------------------------------
BENS_SRP = {
    "orgao": "Prefeitura Municipal", "objeto": "Registro de preços para "
    "aquisição de material de expediente para as secretarias",
    "justificativa": "Fornecimento contínuo e padronizado.",
    "modelo_execucao": "Sistema de Registro de Preços (SRP)",
    "requisitos": "Materiais novos, de primeiro uso.",
    "prazo": "até agosto de 2027", "valor_estimado": 1000.0,
    "itens": [{"descricao": "Caneta esferográfica", "quantidade": 100,
               "unidade": "un", "valor_unitario": 10.0}],
}
BENS_SEM_SRP = {**BENS_SRP,
                "objeto": "Aquisição de material de expediente",
                "modelo_execucao": "Entrega única (fornecimento integral)"}
SERVICO_MAO_DE_OBRA = {
    **BENS_SRP,
    "objeto": "Contratação de serviço continuado de limpeza predial",
    "modelo_execucao": "Serviço de execução continuada",
    "requisitos": "Postos de trabalho com dedicação exclusiva de mão de "
                  "obra, uniformes e insumos.",
    "itens": [{"descricao": "Posto de servente", "quantidade": 10,
               "unidade": "posto", "valor_unitario": 4000.0}],
}
SAAS_TI = {
    **BENS_SRP,
    "objeto": "Contratação de software de gestão em nuvem (SaaS)",
    "modelo_execucao": "Serviço de execução continuada",
    "requisitos": "Plataforma digital com hospedagem em nuvem, suporte e "
                  "licença de uso por usuário.",
    "itens": [{"descricao": "Licença de uso do software", "quantidade": 50,
               "unidade": "licença", "valor_unitario": 300.0}],
}
COM_GARANTIA = {**BENS_SEM_SRP,
                "requisitos": "Exige-se garantia contratual de execução na "
                              "modalidade seguro-garantia."}


def _decidir(dados: dict) -> dict:
    """Resolve as regras-base sobre os fatos do formulário (sem banco)."""
    lista = fatos.extrair_do_formulario(dados, None)
    return conhecimento.resolver(lista, conhecimento.regras_base())["resultado"]


# ===========================================================================
# ETP — raciocínio
# ===========================================================================
def test_etp01_necessidade_nao_pode_trazer_a_solucao_decidida():
    texto = (
        "## 2. DESCRIÇÃO DA NECESSIDADE DA CONTRATAÇÃO\n\n"
        "2.1. Adota-se o Sistema de Registro de Preços para atender as "
        "secretarias.\n\n"
        "## 5. LEVANTAMENTO DE SOLUÇÕES\n\nAlternativas analisadas.\n\n"
        "## 6. DESCRIÇÃO DA SOLUÇÃO\n\nSolução escolhida.\n")
    avisos = [a["mensagem"] for a in
              validacao.avisos(validacao.validar_documento("etp", texto))]
    assert any("antecipa a solução" in m for m in avisos)


def test_etp01_necessidade_que_descreve_o_problema_passa():
    texto = (
        "## 2. DESCRIÇÃO DA NECESSIDADE DA CONTRATAÇÃO\n\n"
        "2.1. As secretarias enfrentam desabastecimento recorrente de "
        "materiais, com paralisação de atividades-meio e aquisições "
        "fragmentadas de baixo poder de barganha.\n\n"
        "## 5. LEVANTAMENTO DE SOLUÇÕES\n\nAlternativas analisadas.\n\n"
        "## 6. DESCRIÇÃO DA SOLUÇÃO\n\nSolução escolhida.\n")
    avisos = [a["mensagem"] for a in
              validacao.avisos(validacao.validar_documento("etp", texto))]
    assert not any("antecipa a solução" in m for m in avisos)


def test_etp02_levantamento_deve_preceder_a_solucao_escolhida():
    invertido = (
        "## 2. DESCRIÇÃO DA NECESSIDADE DA CONTRATAÇÃO\n\nProblema.\n\n"
        "## 5. DESCRIÇÃO DA SOLUÇÃO\n\nSolução escolhida.\n\n"
        "## 6. LEVANTAMENTO DE SOLUÇÕES\n\nAlternativas.\n")
    avisos = [a["mensagem"] for a in
              validacao.avisos(validacao.validar_documento("etp", invertido))]
    assert any("ordem do raciocínio invertida" in m for m in avisos)


def test_etp02_solucao_sem_levantamento_e_sinalizada():
    texto = ("## 2. DESCRIÇÃO DA NECESSIDADE\n\nProblema.\n\n"
             "## 6. DESCRIÇÃO DA SOLUÇÃO\n\nSolução escolhida.\n")
    avisos = [a["mensagem"] for a in
              validacao.avisos(validacao.validar_documento("etp", texto))]
    assert any("sem cláusula de levantamento" in m for m in avisos)


def test_etp03_prompt_trata_dfd_e_formulario_como_hipotese():
    _, user = prompts.montar_prompt("etp", BENS_SRP, "## DFD\nSolução "
                                    "sugerida: registro de preços.")
    assert "PREFERÊNCIA DE MODELAGEM" in user
    assert "CONFIRMADA OU AFASTADA pelo estudo" in user
    assert "hipótese inicial do estudo" in user
    assert "confirmá-la, ajustá-la ou afastá-la" in user


def test_etp03_raciocinio_obrigatorio_esta_no_prompt():
    _, user = prompts.montar_prompt("etp", BENS_SRP, None)
    assert "RACIOCÍNIO OBRIGATÓRIO DO ETP" in user
    posicao = user.index("RACIOCÍNIO OBRIGATÓRIO DO ETP")
    trecho = user[posicao:posicao + 1200]
    assert "NECESSIDADE" in trecho and "ALTERNATIVAS" in trecho
    assert trecho.index("ALTERNATIVAS") < trecho.index("SOLUÇÃO ESCOLHIDA")


def test_etp04_prompt_proibe_alternativa_ficticia_e_absolutismo():
    _, user = prompts.montar_prompt("etp", SAAS_TI, None)
    assert "PROIBIDO inventar alternativas fictícias" in user
    assert "única solução possível" in user
    assert "aquisição × locação" in user   # alternativas reais sugeridas


def test_etp04_absolutismo_no_texto_gera_aviso():
    texto = ("## 15. POSICIONAMENTO CONCLUSIVO\n\n15.1. Trata-se da única "
             "solução possível e juridicamente irrepreensível.\n")
    avisos = [a["mensagem"] for a in
              validacao.avisos(validacao.validar_documento("etp", texto))]
    assert any("afirmação absoluta" in m for m in avisos)


def test_tr_e_edital_recebem_o_papel_de_executar_a_decisao():
    _, tr = prompts.montar_prompt("tr", BENS_SRP, "## ETP aprovado")
    assert "OPERACIONALIZA a solução escolhida no ETP" in tr
    _, edital = prompts.montar_prompt("edital", BENS_SRP, "## TR aprovado")
    assert "respeitar objeto, requisitos" in edital


def test_numeracao_do_perfil_fecha_sem_buraco_quando_clausula_sai():
    # sem SRP as cláusulas condicionais saem: a sequência não pode pular
    aplicaveis = perfis.clausulas_aplicaveis("etp", srp=False)
    numeros = [c["n"] for c in aplicaveis]
    assert numeros == list(range(1, len(numeros) + 1))
    # a cláusula de renovação do quantitativo (SRP) não entrou...
    titulos = " ".join(c["titulo"] for c in aplicaveis)
    assert "RENOVAÇÃO DO QUANTITATIVO" not in titulos
    # ...e entra quando é SRP, ainda com numeração contínua
    com_srp = perfis.clausulas_aplicaveis("etp", srp=True)
    assert [c["n"] for c in com_srp] == list(range(1, len(com_srp) + 1))
    assert "RENOVAÇÃO DO QUANTITATIVO" in " ".join(c["titulo"]
                                                   for c in com_srp)
    assert len(com_srp) > len(aplicaveis)


# ===========================================================================
# Cláusulas condicionais (motor de conhecimento)
# ===========================================================================
def test_fatos_derivados_sao_estruturados_e_nao_palavra_solta():
    por_path = {f["path"]: f["valor"]
                for f in fatos.extrair_do_formulario(SAAS_TI, None)}
    assert por_path["objeto.categoria"] == "TI_SOFTWARE"
    # a categoria exige EVIDÊNCIA acumulada: uma menção incidental não basta
    incidental = {**BENS_SEM_SRP,
                  "justificativa": "O setor usa um software de planilhas."}
    categoria, _ = fatos.categoria_do_objeto(incidental)
    assert categoria != "TI_SOFTWARE"


def test_cond01_compra_de_materiais_nao_ativa_repactuacao():
    resultado = _decidir(BENS_SRP)
    assert "preco.repactuacao" in resultado["clausulas_excluir"]
    assert "preco.reajuste" in resultado["clausulas_incluir"]
    bloco = conhecimento.bloco_de_diretrizes(resultado)
    assert "NÃO PODE CONSTAR" in bloco and "repactuação" in bloco


def test_cond02_servico_com_mao_de_obra_ativa_repactuacao():
    resultado = _decidir(SERVICO_MAO_DE_OBRA)
    assert "preco.repactuacao" in resultado["clausulas_incluir"]
    assert "preco.repactuacao" not in resultado["clausulas_excluir"]


def test_cond03_garantia_nao_e_inventada_sem_fato():
    sem = _decidir(BENS_SRP)
    assert "contrato.garantia" in sem["clausulas_excluir"]
    com = _decidir(COM_GARANTIA)
    assert "contrato.garantia" in com["clausulas_incluir"]


def test_cond03_amostra_tambem_nao_e_presumida():
    assert "julgamento.amostra" in _decidir(BENS_SRP)["clausulas_excluir"]
    com_amostra = {**BENS_SRP,
                   "requisitos": "Será exigida amostra do item vencedor."}
    assert "julgamento.amostra" in _decidir(com_amostra)["clausulas_incluir"]


def test_cond04_srp_ativa_as_clausulas_da_ata():
    incluir = _decidir(BENS_SRP)["clausulas_incluir"]
    for alvo in ("srp.vigencia_ata", "srp.adesao", "srp.cadastro_reserva",
                 "srp.gerenciamento"):
        assert alvo in incluir


def test_cond05_sem_srp_as_clausulas_da_ata_nao_aparecem():
    resultado = _decidir(BENS_SEM_SRP)
    assert "srp.vigencia_ata" in resultado["clausulas_excluir"]
    assert "srp.vigencia_ata" not in resultado["clausulas_incluir"]
    bloco = conhecimento.bloco_de_diretrizes(resultado)
    assert "vigência da Ata de Registro de Preços" in bloco


def test_objeto_de_ti_ativa_lgpd_e_niveis_de_servico():
    incluir = _decidir(SAAS_TI)["clausulas_incluir"]
    for alvo in ("ti.protecao_dados", "ti.nivel_servico",
                 "ti.seguranca_backup", "ti.migracao_saida"):
        assert alvo in incluir
    # e não vazam para uma compra de material comum
    assert "ti.protecao_dados" not in _decidir(BENS_SRP)["clausulas_incluir"]


def test_regra_do_municipio_prevalece_sobre_a_base_da_plataforma():
    municipal = {
        "chave_estavel": "municipio.garantia.sempre", "versao": 1,
        "status": "PUBLISHED", "camada": "municipio", "prioridade": 100,
        "condicao": {"field": "objeto.natureza", "operator": "EQ",
                     "value": "BENS"},
        "acoes": [{"type": "INCLUIR_CLAUSULA", "target": "contrato.garantia"}],
        "fontes": ["Decreto municipal 1/2026"], "justificativa": "política local",
    }
    lista = fatos.extrair_do_formulario(BENS_SRP, None)
    resultado = conhecimento.resolver(
        lista, conhecimento.regras_base() + [municipal])["resultado"]
    assert "contrato.garantia" in resultado["clausulas_incluir"]
    assert "contrato.garantia" not in resultado["clausulas_excluir"]


def test_decisao_do_motor_e_rastreavel_ate_a_fonte_normativa():
    lista = fatos.extrair_do_formulario(BENS_SRP, None)
    decisao = conhecimento.resolver(lista, conhecimento.regras_base())
    trilha = decisao["explicacao"]["regras_avaliadas"]
    repactuacao = next(r for r in trilha
                       if r["chave"] == "base.repactuacao.somente-mao-de-obra")
    assert repactuacao["satisfeita"] is True
    assert any("art. 135" in f for f in repactuacao["fontes"])
    assert repactuacao["folhas"]      # condição avaliada, com valor observado


def test_diretrizes_nao_entram_no_prompt_com_motor_inativo(monkeypatch):
    monkeypatch.setattr(conhecimento, "motor_ativo", lambda: False)
    assert conhecimento.diretrizes_para_prompt(BENS_SRP, None) == ""


# ===========================================================================
# Consistência transversal
# ===========================================================================
def _achados(documentos: dict, dados: dict = None) -> list[str]:
    lista = fatos.extrair_do_formulario(dados or BENS_SRP, None)
    return [a["descricao"] for a in consistencia.verificar(lista, documentos)]


def test_cons01_valores_divergentes_entre_documentos():
    dados = {**BENS_SRP, "valor_estimado": 1000.0}
    docs = {
        "dfd": "## 7. ESTIMATIVA DE VALOR\n\nValor global: R$ 1.000,00.\n",
        "etp": "## 8. ESTIMATIVA DE VALOR\n\nValor global: R$ 2.500,00.\n",
    }
    assert any("valor divergente" in m for m in _achados(docs, dados))


def test_cons02_etp_por_item_e_edital_lote_unico():
    docs = {
        "etp": "## 10. PARCELAMENTO\n\nHaverá adjudicação por item, "
               "ampliando a competitividade.\n",
        "edital": "## 5. DO JULGAMENTO\n\nO julgamento será por lote único.\n",
    }
    mensagens = _achados(docs)
    assert any("critério de adjudicação" in m and "ETP" in m
               for m in mensagens)


def test_cons03_etp_sem_garantia_e_edital_com_5_por_cento():
    docs = {
        "etp": "## 6. REQUISITOS\n\nNão será exigida garantia contratual, "
               "dada a natureza do fornecimento.\n",
        "edital": "## 9. DA ATA\n\nSerá exigida garantia contratual de 5% "
                  "do valor do contrato.\n",
    }
    assert any("garantia" in m for m in _achados(docs))


def test_cons04_tr_pregao_e_edital_concorrencia():
    docs = {
        "tr": "## 2. FUNDAMENTAÇÃO\n\nA contratação se dará por pregão "
              "eletrônico, por se tratar de bem comum.\n",
        "edital": "## 1. PREÂMBULO\n\nModalidade: concorrência eletrônica.\n",
    }
    mensagens = _achados(docs)
    assert any("modalidade" in m and "TR" in m for m in mensagens)


def test_cons05_etp_srp_e_tr_incompativel():
    docs = {
        "etp": "## 6. SOLUÇÃO\n\nAdota-se o sistema de registro de preços.\n",
        "tr": "## 6. FORMALIZAÇÃO\n\nA contratação será formalizada sem "
              "registro de preços, por contrato direto.\n",
    }
    assert any("Registro de Preços" in m or "registro de preços" in m
               for m in _achados(docs))


def test_cons06_heranca_semantica_correta_nao_gera_falso_positivo():
    # textos DIFERENTES, decisões coerentes: nada a apontar
    docs = {
        "dfd": "## 4. SOLUÇÃO PROPOSTA\n\nSugere-se o sistema de registro "
               "de preços para o fornecimento parcelado.\n",
        "etp": "## 6. DESCRIÇÃO DA SOLUÇÃO\n\nO estudo confirma a "
               "conveniência da ata de registro de preços, com adjudicação "
               "por item.\n",
        "tr": "## 6. DA FORMALIZAÇÃO\n\nSerá firmada ata de registro de "
              "preços, com julgamento por item.\n",
        "edital": "## 1. PREÂMBULO\n\nPregão eletrônico pelo sistema de "
                  "registro de preços, adjudicação por item.\n",
    }
    mensagens = _achados(docs)
    assert not any("divergente na cadeia" in m for m in mensagens)


def test_silencio_de_um_documento_nao_e_divergencia():
    docs = {
        "etp": "## 10. PARCELAMENTO\n\nAdjudicação por item.\n",
        "tr": "## 5. EXECUÇÃO\n\nA entrega será parcelada conforme "
              "solicitação da unidade.\n",     # não decide item × lote
    }
    assert not any("divergente na cadeia" in m for m in _achados(docs))


def test_srp_do_formulario_prevalece_sobre_documento_divergente():
    docs = {"tr": "## 6. FORMALIZAÇÃO\n\nA contratação será feita sem "
                  "registro de preços.\n"}
    mensagens = _achados(docs, BENS_SRP)
    assert any("incompatível com o processo" in m for m in mensagens)


def test_requisito_verificavel_sem_operacionalizacao_e_apontado():
    docs = {"tr": (
        "## 4. DESCRIÇÃO DOS REQUISITOS DA CONTRATAÇÃO\n\n"
        "4.1. Os equipamentos deverão possuir certificação INMETRO e "
        "atender à norma ABNT NBR 15575.\n\n"
        "## 7. DO CRITÉRIO DE ACEITAÇÃO DO OBJETO\n\n"
        "7.1. O recebimento definitivo ocorrerá em 15 dias úteis após a "
        "conferência quantitativa.\n")}
    assert any("sem operacionalização" in m for m in _achados(docs))


def test_requisito_retomado_na_aceitacao_nao_gera_achado():
    docs = {"tr": (
        "## 4. DESCRIÇÃO DOS REQUISITOS DA CONTRATAÇÃO\n\n"
        "4.1. Os equipamentos deverão possuir certificação INMETRO.\n\n"
        "## 7. DO CRITÉRIO DE ACEITAÇÃO DO OBJETO\n\n"
        "7.1. No recebimento provisório, a fiscalização conferirá a "
        "certificação INMETRO de cada equipamento; a ausência do "
        "certificado enseja recusa do item.\n")}
    assert not any("sem operacionalização" in m for m in _achados(docs))


@pytest.mark.parametrize("dados", [BENS_SRP, BENS_SEM_SRP,
                                   SERVICO_MAO_DE_OBRA, SAAS_TI])
def test_motor_resolve_qualquer_cenario_sem_conflito_nem_bloqueio(dados):
    resultado = _decidir(dados)
    assert resultado["conflitos"] == []
    assert resultado["bloqueios"] == []
    assert resultado["clausulas_incluir"] or resultado["clausulas_excluir"]
