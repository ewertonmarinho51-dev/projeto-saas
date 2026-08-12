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


def _fatos(dados: dict, confirmar: tuple[str, ...] = ()) -> list[dict]:
    """
    Fatos do formulário; `confirmar` marca paths como CONFIRMADOS pelo
    humano — é o que transforma uma inferência heurística em base de
    decisão vinculante (mecanismo de status/confiança já existente).
    """
    lista = fatos.extrair_do_formulario(dados, None)
    for fato in lista:
        if fato["path"] in confirmar:
            fato["status"] = "confirmado"
    return lista


def _decidir(dados: dict, confirmar: tuple[str, ...] = ()) -> dict:
    """Resolve as regras-base sobre os fatos do formulário (sem banco)."""
    return conhecimento.resolver(
        _fatos(dados, confirmar), conhecimento.regras_base())["resultado"]


def _alvos_sugeridos(resultado: dict) -> set[str]:
    return {alvo for s in resultado["sugestoes"] for alvo in s["alvos"]}


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
    # a natureza vem da categoria (heurística): a exclusão é SUGERIDA...
    resultado = _decidir(BENS_SRP)
    assert "preco.repactuacao" not in resultado["clausulas_incluir"]
    assert "preco.repactuacao" in _alvos_sugeridos(resultado)
    # ...e vira decisão quando o fato é confirmado pelo humano
    confirmado = _decidir(BENS_SRP, confirmar=("objeto.natureza",))
    assert "preco.repactuacao" in confirmado["clausulas_excluir"]
    assert "preco.reajuste" in confirmado["clausulas_incluir"]
    bloco = conhecimento.bloco_de_diretrizes(confirmado)
    assert "NÃO PODE CONSTAR" in bloco and "repactuação" in bloco


def test_cond02_servico_com_mao_de_obra_ativa_repactuacao():
    resultado = _decidir(SERVICO_MAO_DE_OBRA)
    assert "preco.repactuacao" in resultado["clausulas_incluir"]
    assert "preco.repactuacao" not in resultado["clausulas_excluir"]


def test_cond03_garantia_nao_e_inventada_sem_fato():
    # ausência de fato é constatação sobre o processo (não é heurística):
    # a exclusão vale de imediato
    sem = _decidir(BENS_SRP)
    assert "contrato.garantia" in sem["clausulas_excluir"]
    # a menção afirmativa em texto livre SUGERE a cláusula; só confirmada
    # ela obriga — exigir garantia é decisão restritiva
    com = _decidir(COM_GARANTIA)
    assert "contrato.garantia" not in com["clausulas_excluir"]
    assert "contrato.garantia" in _alvos_sugeridos(com)
    confirmado = _decidir(COM_GARANTIA,
                          confirmar=("contratacao.garantia_exigida",))
    assert "contrato.garantia" in confirmado["clausulas_incluir"]


def test_cond03_amostra_tambem_nao_e_presumida():
    assert "julgamento.amostra" in _decidir(BENS_SRP)["clausulas_excluir"]
    com_amostra = {**BENS_SRP,
                   "requisitos": "Será exigida amostra do item vencedor."}
    sugerido = _decidir(com_amostra)
    assert "julgamento.amostra" in _alvos_sugeridos(sugerido)
    assert "julgamento.amostra" not in sugerido["clausulas_incluir"]
    confirmado = _decidir(com_amostra,
                          confirmar=("contratacao.amostra_exigida",))
    assert "julgamento.amostra" in confirmado["clausulas_incluir"]


def test_amostra_cita_o_regime_correto():
    regra = next(r for r in conhecimento.regras_base()
                 if r["chave_estavel"] == "base.amostra.exigida-no-processo")
    fontes = " ".join(regra["fontes"])
    assert "art. 41, II" in fontes and "art. 42" in fontes


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


def test_objeto_de_ti_software_ativa_lgpd_e_niveis_de_servico():
    confirmado = _decidir(SAAS_TI, confirmar=("objeto.categoria",))
    for alvo in ("ti.protecao_dados", "ti.nivel_servico",
                 "ti.seguranca_backup", "ti.migracao_saida"):
        assert alvo in confirmado["clausulas_incluir"]
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
    resultado = conhecimento.resolver(
        _fatos(BENS_SRP, confirmar=("objeto.natureza",)),
        conhecimento.regras_base() + [municipal])["resultado"]
    assert "contrato.garantia" in resultado["clausulas_incluir"]
    assert "contrato.garantia" not in resultado["clausulas_excluir"]


def test_decisao_do_motor_e_rastreavel_ate_a_fonte_normativa():
    decisao = conhecimento.resolver(
        _fatos(BENS_SRP, confirmar=("objeto.natureza",)),
        conhecimento.regras_base())
    trilha = decisao["explicacao"]["regras_avaliadas"]
    reajuste = next(r for r in trilha if r["chave"] == "base.reajuste.bens")
    assert reajuste["satisfeita"] is True
    assert any("art. 92" in f for f in reajuste["fontes"])
    assert reajuste["folhas"]        # condição avaliada, com valor observado
    assert reajuste["confianca"] == 1.0   # fato confirmado pelo humano


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
    # a garantia se consolida no TR: com o TR presente e alinhado ao ETP,
    # o Edital que diverge é apontado
    docs = {
        "etp": "## 6. REQUISITOS\n\nNão será exigida garantia contratual, "
               "dada a natureza do fornecimento.\n",
        "tr": "## 6. FORMALIZAÇÃO\n\nNão será exigida garantia "
              "contratual.\n",
        "edital": "## 9. DA ATA\n\nSerá exigida garantia contratual de 5% "
                  "do valor do contrato.\n",
    }
    mensagens = _achados(docs)
    assert any("garantia" in m and "EDITAL" in m for m in mensagens)


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


# ===========================================================================
# Segunda auditoria (P1-R): autoridade decisória, tri-state, negações,
# confiança dos fatos e regras-base revisadas.
# ===========================================================================
SERVICO_SEM_INFO = {**BENS_SRP,
                    "objeto": "Contratação de serviço de manutenção predial",
                    "modelo_execucao": "Serviço de execução continuada",
                    "requisitos": "Atendimento em dias úteis."}
SEM_GARANTIA = {**BENS_SEM_SRP,
                "requisitos": "Não será exigida garantia contratual, dada a "
                              "natureza do fornecimento."}
SEM_AMOSTRA = {**BENS_SEM_SRP,
               "requisitos": "Dispensa-se a apresentação de amostra."}
GARANTIA_DE_FABRICA = {
    **BENS_SEM_SRP,
    "requisitos": "Os equipamentos devem ter garantia de 12 meses do "
                  "fabricante contra defeitos."}
EQUIPAMENTO_TI = {
    **BENS_SEM_SRP,
    "objeto": "Aquisição de monitores e notebooks para as secretarias",
    "requisitos": "Monitor de 24 polegadas; notebook com 16GB.",
    "itens": [{"descricao": "Monitor 24 polegadas", "quantidade": 30,
               "unidade": "un", "valor_unitario": 900.0}]}
VEICULOS = {
    **BENS_SEM_SRP,
    "objeto": "Aquisição de veículo utilitário para a Secretaria de Saúde",
    "requisitos": "Veículo zero quilômetro.",
    "itens": [{"descricao": "Veículo utilitário", "quantidade": 1,
               "unidade": "un", "valor_unitario": 120000.0}]}


# --- autoridade decisória por estágio -------------------------------------
def test_autoridade_formulario_srp_e_etp_afasta_sem_finding():
    docs = {
        "dfd": "## 4. SOLUÇÃO PROPOSTA\n\nSugere-se registro de preços.\n",
        "etp": "## 6. DESCRIÇÃO DA SOLUÇÃO\n\nO estudo conclui pela "
               "contratação sem registro de preços, dada a previsibilidade "
               "do consumo e a entrega única.\n",
    }
    mensagens = _achados(docs, BENS_SRP)   # formulário pedia SRP
    assert not any("divergente" in m or "incompatível" in m
                   for m in mensagens)


def test_autoridade_etp_afasta_srp_e_tr_reintroduz_gera_finding():
    docs = {
        "etp": "## 6. SOLUÇÃO\n\nA contratação será feita sem registro de "
               "preços.\n",
        "tr": "## 6. FORMALIZAÇÃO\n\nSerá firmada ata de registro de "
              "preços com os fornecedores.\n",
    }
    mensagens = _achados(docs, BENS_SRP)
    assert any("Registro de Preços" in m and "TR" in m for m in mensagens)


def test_autoridade_etp_escolhe_srp_e_tr_mantem_sem_finding():
    docs = {
        "etp": "## 6. SOLUÇÃO\n\nAdota-se o sistema de registro de preços.\n",
        "tr": "## 6. FORMALIZAÇÃO\n\nSerá firmada ata de registro de "
              "preços, na forma do edital.\n",
    }
    assert not any("divergente" in m for m in _achados(docs, BENS_SRP))


def test_autoridade_tr_define_modalidade_e_edital_diverge():
    docs = {
        "tr": "## 2. FUNDAMENTAÇÃO\n\nA contratação se dará por pregão "
              "eletrônico.\n",
        "edital": "## 1. PREÂMBULO\n\nModalidade: concorrência eletrônica.\n",
    }
    mensagens = _achados(docs)
    assert any("modalidade" in m and "EDITAL" in m for m in mensagens)


def test_autoridade_dfd_sugere_item_e_etp_escolhe_lote_sem_finding():
    docs = {
        "dfd": "## 5. DESCRIÇÃO DA SOLUÇÃO\n\nPropõe-se adjudicação por "
               "item.\n",
        "etp": "## 10. PARCELAMENTO\n\nA análise técnica recomenda "
               "adjudicação por lote, por economia de escala na "
               "distribuição.\n",
    }
    assert not any("adjudicação" in m for m in _achados(docs))


def test_diretrizes_seguem_a_decisao_consolidada_e_nao_o_formulario():
    # formulário pede SRP; o ETP aprovado afastou → o TR não recebe as
    # cláusulas da Ata
    documentos = {"etp": "## 6. SOLUÇÃO\n\nA contratação será feita sem "
                         "registro de preços.\n"}
    sobrepostos = conhecimento.sobrepor_decisoes_consolidadas(
        _fatos(BENS_SRP), documentos)
    vigentes = {f["path"]: f for f in sobrepostos
                if f.get("status") != "substituido"}
    assert vigentes["procedimento.srp"]["valor"] is False
    assert vigentes["procedimento.srp"]["fonte"] == "documento:etp"
    resultado = conhecimento.resolver(
        sobrepostos, conhecimento.regras_base())["resultado"]
    assert "srp.vigencia_ata" in resultado["clausulas_excluir"]
    assert "srp.vigencia_ata" not in resultado["clausulas_incluir"]


def test_consolidacao_do_srp_nao_inventa_forma_de_execucao():
    # o ETP decidiu sobre REGISTRO DE PREÇOS — não sobre entrega única,
    # parcelada ou serviço continuado
    documentos = {"etp": "## 6. SOLUÇÃO\n\nA contratação será feita sem "
                         "registro de preços.\n"}
    sobrepostos = conhecimento.sobrepor_decisoes_consolidadas(
        _fatos(BENS_SRP), documentos)
    vigentes = {f["path"]: f["valor"] for f in sobrepostos
                if f.get("status") != "substituido"}
    # a forma de execução informada permanece intacta
    assert vigentes["execucao.modelo"] == BENS_SRP["modelo_execucao"]
    assert BENS_SRP["modelo_execucao"] == "Sistema de Registro de Preços (SRP)"
    # e nenhum fato de execução foi inventado
    assert vigentes.get("procedimento.execucao_continuada") is False


def test_consolidacao_preserva_os_fatos_quando_etp_confirma():
    documentos = {"etp": "## 6. SOLUÇÃO\n\nAdota-se o sistema de registro "
                         "de preços.\n"}
    lista = _fatos(BENS_SRP)
    assert conhecimento.sobrepor_decisoes_consolidadas(
        lista, documentos) is lista


# --- fatos: tri-state, natureza e negações --------------------------------
def test_srp_nao_gera_natureza_bens():
    caminhos = {f["path"] for f in fatos.extrair_do_formulario(
        {"objeto": "Registro de preços para aquisição diversa",
         "modelo_execucao": "Sistema de Registro de Preços (SRP)"}, None)}
    assert "objeto.natureza" not in caminhos


def test_natureza_vem_da_execucao_quando_ela_a_declara():
    por_path = {f["path"]: f for f in fatos.extrair_do_formulario(
        {"objeto": "Serviço de vigilância",
         "modelo_execucao": "Serviço de execução continuada"}, None)}
    assert por_path["objeto.natureza"]["valor"] == "SERVICOS"
    assert por_path["objeto.natureza"]["fonte"] == "formulario:modelo_execucao"


def test_dedicacao_sem_informacao_fica_desconhecida():
    caminhos = {f["path"] for f in
                fatos.extrair_do_formulario(SERVICO_SEM_INFO, None)}
    assert "procedimento.dedicacao_mao_de_obra" not in caminhos
    # e o motor ALERTA em vez de decidir o instituto
    resultado = _decidir(SERVICO_SEM_INFO)
    assert "preco.repactuacao" not in resultado["clausulas_incluir"]
    assert "preco.repactuacao" not in resultado["clausulas_excluir"]
    assert any("dedicação de mão de obra" in a for a in resultado["alertas"])


def test_dedicacao_explicita_e_verdadeira():
    por_path = {f["path"]: f["valor"] for f in
                fatos.extrair_do_formulario(SERVICO_MAO_DE_OBRA, None)}
    assert por_path["procedimento.dedicacao_mao_de_obra"] is True


def test_dedicacao_negada_explicitamente_e_falsa():
    dados = {**SERVICO_SEM_INFO,
             "requisitos": "O serviço não será prestado com dedicação "
                           "exclusiva de mão de obra."}
    por_path = {f["path"]: f["valor"] for f in
                fatos.extrair_do_formulario(dados, None)}
    assert por_path["procedimento.dedicacao_mao_de_obra"] is False
    resultado = _decidir(dados)
    assert "preco.repactuacao" in resultado["clausulas_excluir"]
    assert "preco.reajuste" in resultado["clausulas_incluir"]


def test_negacao_de_garantia_nao_vira_fato_positivo():
    por_path = {f["path"]: f["valor"] for f in
                fatos.extrair_do_formulario(SEM_GARANTIA, None)}
    assert por_path["contratacao.garantia_exigida"] is False
    assert "contrato.garantia" in _decidir(SEM_GARANTIA)["clausulas_excluir"]


def test_negacao_de_amostra_nao_vira_fato_positivo():
    por_path = {f["path"]: f["valor"] for f in
                fatos.extrair_do_formulario(SEM_AMOSTRA, None)}
    assert por_path["contratacao.amostra_exigida"] is False
    assert "julgamento.amostra" in _decidir(SEM_AMOSTRA)["clausulas_excluir"]


def test_garantia_do_fabricante_nao_vira_garantia_contratual():
    caminhos = {f["path"] for f in
                fatos.extrair_do_formulario(GARANTIA_DE_FABRICA, None)}
    assert "contratacao.garantia_exigida" not in caminhos
    assert "contrato.garantia" in _decidir(
        GARANTIA_DE_FABRICA)["clausulas_excluir"]


# --- confiança: inferência não obriga -------------------------------------
def test_inferencia_de_baixa_confianca_nao_cria_obrigacao_restritiva():
    resultado = _decidir(SAAS_TI)          # categoria inferida do texto
    assert resultado["clausulas_incluir"] == [] or \
        "ti.protecao_dados" not in resultado["clausulas_incluir"]
    assert "ti.protecao_dados" in _alvos_sugeridos(resultado)
    sugestao = next(s for s in resultado["sugestoes"]
                    if "ti.protecao_dados" in s["alvos"])
    assert sugestao["fato"] == "objeto.categoria"
    assert "confirme o fato" in sugestao["motivo"]


def test_fato_informado_no_processo_continua_vinculante():
    # procedimento.srp vem de campo do formulário (informação, não
    # inferência): decide sem depender de confirmação
    assert "srp.vigencia_ata" in _decidir(BENS_SRP)["clausulas_incluir"]


def test_regra_pode_aceitar_inferencia_por_politica_explicita():
    regra = {
        "chave_estavel": "municipio.ti.exige-lgpd", "versao": 1,
        "status": "PUBLISHED", "camada": "municipio", "prioridade": 100,
        "condicao": {"field": "objeto.categoria", "operator": "EQ",
                     "value": "TI_SOFTWARE"},
        "acoes": [{"type": "INCLUIR_CLAUSULA", "target": "ti.protecao_dados"}],
        "fontes": ["Decreto municipal"], "justificativa": "política local",
        "aceita_inferencia": True,
    }
    resultado = conhecimento.resolver(
        _fatos(SAAS_TI), conhecimento.regras_base() + [regra])["resultado"]
    assert "ti.protecao_dados" in resultado["clausulas_incluir"]


# --- regras-base revisadas -------------------------------------------------
def test_srp_nao_ativa_renovacao_de_quantitativo():
    resultado = _decidir(BENS_SRP)
    assert "srp.renovacao_quantitativo" not in resultado["clausulas_incluir"]
    assert "srp.vigencia_ata" in resultado["clausulas_incluir"]
    # sem SRP, a matéria continua expressamente excluída
    assert "srp.renovacao_quantitativo" in _decidir(
        BENS_SEM_SRP)["clausulas_excluir"]


def test_equipamento_de_ti_nao_ativa_migracao_de_dados():
    confirmado = _decidir(EQUIPAMENTO_TI, confirmar=("objeto.categoria",))
    for alvo in ("ti.migracao_saida", "ti.protecao_dados",
                 "ti.seguranca_backup"):
        assert alvo not in confirmado["clausulas_incluir"]


def test_software_ativa_requisitos_digitais_pertinentes():
    confirmado = _decidir(SAAS_TI, confirmar=("objeto.categoria",))
    assert "ti.migracao_saida" in confirmado["clausulas_incluir"]
    assert "ti.protecao_dados" in confirmado["clausulas_incluir"]


def test_veiculo_nao_recebe_exigencia_territorial_automatica():
    confirmado = _decidir(VEICULOS, confirmar=("objeto.categoria",))
    juntos = confirmado["clausulas_incluir"] + confirmado["clausulas_excluir"]
    assert not any(alvo.startswith("veiculos.") for alvo in juntos)
    assert any("assistência" in a and "justificativa" in a
               for a in confirmado["alertas"])


def test_epi_mantem_ca_com_fonte_identificada():
    regra = next(r for r in conhecimento.regras_base()
                 if r["chave_estavel"] == "base.epi.certificado-de-aprovacao")
    fonte = " ".join(regra["fontes"])
    assert "NR-6" in fonte and "Portaria" in fonte
    assert "confirmar vigência" in fonte     # depende de indexação no RAG


# ===========================================================================
# Ajustes finais (3ª revisão): consolidador silencioso, norma+dispositivo,
# trace da geração bem-sucedida, gatilho de TI e dedicação inequívoca.
# ===========================================================================
def test_dfd_nao_vira_consolidador_quando_o_etp_silencia():
    docs = {
        "dfd": "## 4. SOLUÇÃO PROPOSTA\n\nPropõe-se o sistema de registro "
               "de preços.\n",
        "etp": "## 6. DESCRIÇÃO DA SOLUÇÃO\n\nO estudo detalha os "
               "requisitos e a análise de mercado da contratação.\n",
        "tr": "## 6. FORMALIZAÇÃO\n\nA contratação será formalizada sem "
              "registro de preços, por contrato direto.\n",
    }
    # o ETP (competente) não decidiu: o DFD não é promovido a consolidador
    assert consistencia.documento_consolidador("srp", docs) == ("", "", "")
    mensagens = _achados(docs, BENS_SEM_SRP)
    assert not any("decisão já consolidada" in m for m in mensagens)
    # e a lacuna é registrada, sem acusar o TR
    assert any("NÃO CONSOLIDADA" in m for m in mensagens)


def test_etp_nao_vira_consolidador_de_materia_cuja_autoridade_e_o_tr():
    docs = {
        "etp": "## 6. REQUISITOS\n\nNão será exigida garantia contratual.\n",
        "tr": "## 6. FORMALIZAÇÃO\n\nO contrato observará as condições "
              "previstas no edital.\n",       # silente quanto à garantia
        "edital": "## 9. DA ATA\n\nSerá exigida garantia contratual de 5% "
                  "do valor do contrato.\n",
    }
    assert consistencia.documento_consolidador("garantia", docs) == ("", "", "")
    mensagens = _achados(docs)
    assert not any("decisão já consolidada" in m and "garantia" in m
                   for m in mensagens)


def test_sem_o_documento_competente_no_dossie_nao_ha_aviso():
    # só DFD e TR: o ETP nem existe ainda — nada a cobrar
    docs = {
        "dfd": "## 4. SOLUÇÃO\n\nPropõe-se registro de preços.\n",
        "tr": "## 6. FORMALIZAÇÃO\n\nSem registro de preços.\n",
    }
    assert not any("NÃO CONSOLIDADA" in m for m in _achados(docs,
                                                            BENS_SEM_SRP))


# --- gatilho de TI ---------------------------------------------------------
def test_equipamento_de_ti_nao_aciona_tema_de_protecao_de_dados():
    from src import rag

    assert "protecao_dados" not in rag.temas_para(EQUIPAMENTO_TI, "tr")
    assert "dados" not in rag._gatilhos(EQUIPAMENTO_TI)


def test_software_aciona_tema_de_protecao_de_dados():
    from src import rag

    assert "protecao_dados" in rag.temas_para(SAAS_TI, "tr")


def test_processo_que_exige_seguranca_aciona_o_tema_mesmo_sem_ser_software():
    from src import rag

    servico_com_dados = {
        **BENS_SEM_SRP,
        "objeto": "Serviço de digitalização de prontuários",
        "requisitos": "Tratamento de dados pessoais sensíveis com sigilo e "
                      "segurança da informação."}
    assert "protecao_dados" in rag.temas_para(servico_com_dados, "tr")


# --- dedicação de mão de obra inequívoca -----------------------------------
def test_mencao_generica_a_mao_de_obra_nao_ativa_repactuacao():
    generico = {
        **BENS_SRP,
        "objeto": "Contratação de serviço continuado de manutenção predial",
        "modelo_execucao": "Serviço de execução continuada",
        "requisitos": "Mão de obra especializada para reparos sob demanda."}
    caminhos = {f["path"]: f["valor"]
                for f in fatos.extrair_do_formulario(generico, None)}
    assert "procedimento.dedicacao_mao_de_obra" not in caminhos
    assert caminhos.get("procedimento.mencao_mao_de_obra") is True
    resultado = _decidir(generico)
    assert "preco.repactuacao" not in resultado["clausulas_incluir"]
    assert any("dedicação de mão de obra" in a for a in resultado["alertas"])


def test_dedicacao_exclusiva_continua_ativando_repactuacao():
    caminhos = {f["path"]: f["valor"]
                for f in fatos.extrair_do_formulario(SERVICO_MAO_DE_OBRA, None)}
    assert caminhos["procedimento.dedicacao_mao_de_obra"] is True
    assert "preco.repactuacao" in _decidir(
        SERVICO_MAO_DE_OBRA)["clausulas_incluir"]
