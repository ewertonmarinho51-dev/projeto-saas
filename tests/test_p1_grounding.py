"""
Testes do P1 — grounding jurídico do RAG e rastro auditável.

RAG-01  recuperação temática prioriza o chunk do tema consultado;
RAG-02  tema não arrasta chunk de outra matéria só por palavra comum;
RAG-03  score abaixo do piso não vira evidência;
RAG-04  sem lastro, o prompt manda NÃO inventar o número do artigo;
RAG-05  processo anterior nunca supera a norma na hierarquia;
RAG-06  o trace registra consulta + fontes, sem segredo nem documento.

Os cenários cobrem objetos diferentes (materiais, serviço contínuo,
SaaS) para que nada fique acoplado à contratação que originou o P0.
"""

import sys

import pytest

from pathlib import Path

from src import llm, rag

RAIZ_REPO = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# Cenários (fixtures sintéticas — nenhum contrato real)
# --------------------------------------------------------------------------
BENS_SRP = {
    "objeto": "Registro de preços para aquisição de material de expediente",
    "justificativa": "Fornecimento contínuo às secretarias.",
    "modelo_execucao": "Sistema de Registro de Preços (SRP)",
    "requisitos": "Materiais novos, de primeiro uso.",
    "itens": [{"descricao": "Caneta esferográfica azul", "quantidade": 100,
               "unidade": "un", "valor_unitario": 2.5}],
}
SERVICO_CONTINUO = {
    "objeto": "Contratação de serviço continuado de limpeza predial",
    "justificativa": "Manutenção das condições de higiene dos prédios.",
    "modelo_execucao": "Serviço de execução continuada",
    "requisitos": "Postos de trabalho com dedicação exclusiva de mão de obra.",
    "itens": [{"descricao": "Posto de servente diurno", "quantidade": 10,
               "unidade": "posto", "valor_unitario": 4200.0}],
}
SAAS_TI = {
    "objeto": "Contratação de software de gestão em nuvem (SaaS) para a "
              "Secretaria de Saúde",
    "justificativa": "Substituição de planilhas por sistema de informação.",
    "modelo_execucao": "Serviço de execução continuada",
    "requisitos": "Plataforma digital com hospedagem em nuvem e suporte.",
    "itens": [{"descricao": "Licença de uso do software", "quantidade": 50,
               "unidade": "licença", "valor_unitario": 300.0}],
}
BENS_SEM_SRP = {**BENS_SRP, "modelo_execucao": "Entrega única (fornecimento "
                                              "integral)"}


def _fingir_base(monkeypatch, resultados_por_consulta, modo="textual",
                 config=""):
    """Base de conhecimento simulada: consulta → trechos devolvidos."""
    monkeypatch.setattr(rag.db, "disponivel", lambda: True)
    monkeypatch.setattr(rag.db, "obter_config", lambda chave: config)
    monkeypatch.setattr(
        rag, "_gerar_embeddings",
        lambda textos, para_consulta: ([[0.1] * 8 for _ in textos]
                                       if modo == "vetorial" else None))
    chamadas = []

    def _rpc(funcao, params):
        consulta = params.get("consulta") or params.get("query_embedding")
        chamadas.append({"funcao": funcao, "params": params})
        if isinstance(consulta, str):
            return resultados_por_consulta(consulta)
        # modo vetorial: devolve por ordem de chamada
        return resultados_por_consulta(f"#{len(chamadas) - 1}")

    monkeypatch.setattr(rag, "_executar_rpc", _rpc)
    return chamadas


def _chunk(id_, titulo, categoria, conteudo, score):
    return {"id": id_, "titulo": titulo, "categoria": categoria,
            "conteudo": conteudo, "similaridade": score,
            "documento_id": id_, "ordem": 0}


# --------------------------------------------------------------------------
# Seleção temática
# --------------------------------------------------------------------------
def test_temas_sao_controlados_e_dependem_do_documento_e_dos_fatos():
    temas_edital = rag.temas_para(BENS_SRP, "edital")
    assert "srp" in temas_edital                    # gatilho estrutural
    assert len(temas_edital) <= rag.MAX_TEMAS       # orçamento respeitado
    # sem SRP o tema da ata não é consultado
    assert "srp" not in rag.temas_para(BENS_SEM_SRP, "edital")
    # tema de proteção de dados só entra em objeto de TI
    assert "protecao_dados" in rag.temas_para(SAAS_TI, "tr")
    assert "protecao_dados" not in rag.temas_para(BENS_SRP, "tr")
    # cada documento tem seus temas: recurso é matéria de edital
    assert "recursos" not in rag.temas_para(BENS_SRP, "dfd")


def test_rag01_consulta_de_tema_prioriza_o_chunk_correto(monkeypatch):
    pregao = _chunk("c-pregao", "Lei nº 14.133/2021", "lei",
                    "Art. 28. São modalidades de licitação: I - pregão... "
                    "Art. 29. O pregão segue o rito procedimental...", 0.88)
    irrelevante = _chunk("c-irrelevante", "Manual de patrimônio", "outro",
                         "Procedimentos de tombamento de bens móveis.", 0.31)

    def resultados(consulta):
        if "modalidade" in str(consulta) or "pregão" in str(consulta):
            return [pregao, irrelevante]
        return [irrelevante]

    _fingir_base(monkeypatch, resultados)
    resultado = rag.recuperar(BENS_SRP, "edital")
    titulos = [r["titulo"] for r in resultado["referencias"]]
    assert "Lei nº 14.133/2021" == titulos[0]      # norma primeiro
    tema_da_lei = next(r["tema"] for r in resultado["referencias"]
                       if r["id"] == "c-pregao")
    assert tema_da_lei == "modalidade"


def test_rag02_tema_nao_arrasta_chunk_de_outra_materia(monkeypatch):
    garantia = _chunk("c-garantia", "Lei nº 14.133/2021", "lei",
                      "Art. 98. A garantia contratual não excederá 5% do "
                      "valor do contrato.", 0.15)   # abaixo do piso
    pagamento = _chunk("c-pagamento", "Lei nº 14.133/2021", "lei",
                       "Arts. 141 a 146. Ordem cronológica de pagamento e "
                       "liquidação da despesa.", 0.80)

    def resultados(consulta):
        if "pagamento" in str(consulta):
            return [pagamento, garantia]
        return []

    _fingir_base(monkeypatch, resultados, config="0.20")
    resultado = rag.recuperar(BENS_SRP, "tr")
    ids = {r["id"] for r in resultado["referencias"]}
    assert "c-pagamento" in ids
    assert "c-garantia" not in ids   # "contrato" em comum não basta


def test_rag03_score_abaixo_do_piso_nao_e_evidencia(monkeypatch):
    fraco = _chunk("c-fraco", "Apostila antiga", "outro", "Texto genérico.",
                   0.02)
    _fingir_base(monkeypatch, lambda consulta: [fraco], config="0.20")
    resultado = rag.recuperar(BENS_SRP, "tr")
    assert resultado["referencias"] == []
    assert resultado["descartados"] > 0
    # e o piso é configurável pelo mecanismo existente (config_app)
    _fingir_base(monkeypatch, lambda consulta: [fraco], config="0.01")
    assert rag.recuperar(BENS_SRP, "tr")["referencias"]


def test_piso_diferencia_busca_vetorial_de_textual(monkeypatch):
    monkeypatch.setattr(rag.db, "disponivel", lambda: True)
    monkeypatch.setattr(rag.db, "obter_config", lambda chave: "")
    assert rag.piso_de_relevancia("vetorial") == rag.PISO_VETORIAL_PADRAO
    assert rag.piso_de_relevancia("textual") == rag.PISO_TEXTUAL_PADRAO
    # a busca textual (ts_rank, escala menor) não é descartada
    assert rag.PISO_TEXTUAL_PADRAO < rag.PISO_VETORIAL_PADRAO


def test_rag04_bloco_manda_nao_inventar_dispositivo(monkeypatch):
    chunk = _chunk("c1", "Lei nº 14.133/2021", "lei",
                   "Art. 84. O prazo de vigência da ata será de um ano.", 0.7)
    _fingir_base(monkeypatch, lambda consulta: [chunk])
    bloco = rag.montar_bloco_referencias(BENS_SRP, "edital")
    assert "REGRA DE CITAÇÃO" in bloco
    assert "só escreva o NÚMERO de um dispositivo" in bloco
    assert "cite apenas a norma" in bloco
    assert "PROIBIDO deduzir número de artigo" in bloco


def test_rag05_processo_anterior_nao_supera_a_norma(monkeypatch):
    anterior = _chunk("c-antigo", "Edital 2019 (processo anterior)",
                      "processo_anterior",
                      "Cláusula: pregão na forma do art. 4º da Lei 10.520/02.",
                      0.95)
    norma = _chunk("c-lei", "Lei nº 14.133/2021", "lei",
                   "Art. 28. São modalidades de licitação: I - pregão.", 0.45)
    _fingir_base(monkeypatch, lambda consulta: [anterior, norma])
    resultado = rag.recuperar(BENS_SRP, "edital")
    referencias = resultado["referencias"]
    # apesar do score MENOR, a norma vem antes do processo anterior
    assert referencias[0]["categoria"] == "lei"
    bloco = rag.montar_bloco_referencias(BENS_SRP, "edital")
    assert "NÃO fundamenta" in bloco        # o molde é rotulado como tal
    assert "fundamenta diretamente a cláusula" in bloco   # papel da lei
    assert "a norma pode ter mudado" in bloco


def test_acordao_nao_e_apresentado_como_legislacao(monkeypatch):
    acordao = _chunk("c-ac", "Acórdão 1234/2023-TCU", "acordao",
                     "Entendimento sobre parcelamento do objeto.", 0.8)
    lei = _chunk("c-lei", "Lei nº 14.133/2021", "lei",
                 "Art. 40. O termo de referência…", 0.6)
    _fingir_base(monkeypatch, lambda consulta: [acordao, lei])
    bloco = rag.montar_bloco_referencias(BENS_SRP, "etp")
    assert "jurisprudência de controle" in bloco
    assert "não substitui a norma" in bloco
    # e a hierarquia separa legislação de jurisprudência
    assert "LEGISLAÇÃO E REGULAMENTO" in bloco
    assert "JURISPRUDÊNCIA E ORIENTAÇÃO DE CONTROLE" in bloco
    assert "PRECEDÊNCIA OPERACIONAL" in bloco   # regulamentação municipal


def test_hierarquia_e_jurisdicao_explicitas_no_bloco(monkeypatch):
    chunk = _chunk("c1", "IN SEGES nº 65/2021", "outro",
                   "Orientações federais sobre pesquisa de preços.", 0.6)
    _fingir_base(monkeypatch, lambda consulta: [chunk])
    bloco = rag.montar_bloco_referencias(BENS_SRP, "etp")
    assert "HIERARQUIA DAS FONTES" in bloco
    assert "contratação MUNICIPAL" in bloco
    assert "FEDERAIS só valem como referência técnica" in bloco


def test_deduplicacao_evita_o_mesmo_chunk_duas_vezes(monkeypatch):
    repetido = _chunk("c-rep", "Lei nº 14.133/2021", "lei",
                      "Art. 40. O termo de referência conterá...", 0.7)
    _fingir_base(monkeypatch, lambda consulta: [repetido])
    resultado = rag.recuperar(BENS_SRP, "tr")
    assert len(resultado["consultas"]) > 1          # várias buscas
    assert len(resultado["referencias"]) == 1       # uma única referência
    assert len(resultado["referencias"]) <= rag.MAX_CHUNKS_PROMPT


def test_uma_unica_chamada_de_embeddings_para_todos_os_temas(monkeypatch):
    chamadas = []
    monkeypatch.setattr(rag.db, "disponivel", lambda: True)
    monkeypatch.setattr(rag.db, "obter_config", lambda chave: "")
    monkeypatch.setattr(rag, "_executar_rpc", lambda funcao, params: [])

    def _embeddings(textos, para_consulta):
        chamadas.append(list(textos))
        return [[0.1] * 8 for _ in textos]

    monkeypatch.setattr(rag, "_gerar_embeddings", _embeddings)
    rag.recuperar(BENS_SRP, "edital")
    assert len(chamadas) == 1                 # lote, não uma por tema
    assert len(chamadas[0]) > 1               # geral + temas


# --------------------------------------------------------------------------
# RAG-06 — trace
# --------------------------------------------------------------------------
def test_rag06_trace_registra_consultas_e_fontes_sem_segredo(monkeypatch):
    chunk = _chunk("c1", "Lei nº 14.133/2021", "lei",
                   "Art. 84. Vigência da ata de registro de preços...", 0.77)
    _fingir_base(monkeypatch, lambda consulta: [chunk])
    trace = rag.montar_contexto(BENS_SRP, "edital")["trace"]

    assert trace["modo"] in ("vetorial", "textual")
    assert trace["piso"] is not None
    temas = {c["tema"] for c in trace["consultas"]}
    assert "geral" in temas and len(temas) > 1
    referencia = trace["referencias"][0]
    assert referencia["titulo"] == "Lei nº 14.133/2021"
    assert referencia["categoria"] == "lei"
    assert referencia["score"] > 0
    assert referencia["documento_id"] == "c1"
    assert len(referencia["trecho"]) <= 160     # identificação, não cópia
    bruto = str(trace)
    for proibido in ("sk-", "api_key", "SUPABASE_KEY", "Bearer"):
        assert proibido not in bruto


def test_trace_chega_ao_registro_da_geracao(monkeypatch):
    gravados = []
    monkeypatch.setattr(llm, "_ultimo_uso", {})
    from src import db

    monkeypatch.setattr(db, "registrar_geracao_bd", gravados.append)
    registro = llm.registrar_geracao(
        "edital", "openai", 0.0, "ok",
        rag_trace={"modo": "vetorial", "consultas": [{"tema": "srp"}]})
    assert registro["rag_trace"]["consultas"][0]["tema"] == "srp"
    assert gravados and gravados[0]["rag_trace"]["modo"] == "vetorial"


def test_insert_sem_coluna_rag_trace_ainda_grava(monkeypatch):
    """Banco sem a migração 0011: cai para o formato antigo, não perde."""
    from src import db

    tentativas = []

    class _Tabela:
        def insert(self, linha):
            tentativas.append(linha)
            if "rag_trace" in linha:
                raise RuntimeError("column geracoes.rag_trace does not exist")
            return self

        def execute(self):
            return self

    class _Cliente:
        def table(self, nome):
            return _Tabela()

    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "_cliente", _Cliente)
    monkeypatch.setattr(db, "tenant_atual", lambda: "t1")
    db.registrar_geracao_bd({"documento": "tr", "motor": "openai",
                             "status": "ok", "rag_trace": {"modo": "textual"}})
    assert len(tentativas) == 2                    # com e sem a coluna
    assert "rag_trace" not in tentativas[1]


# --------------------------------------------------------------------------
# Degradação: RAG indisponível não bloqueia a geração
# --------------------------------------------------------------------------
def test_rag_indisponivel_nao_impede_geracao(monkeypatch):
    monkeypatch.setattr(rag.db, "disponivel", lambda: False)
    contexto = rag.montar_contexto(BENS_SRP, "tr")
    assert contexto["bloco"] == ""
    assert contexto["trace"]["referencias"] == []


def test_falha_da_base_vira_aviso_e_nao_excecao(monkeypatch):
    monkeypatch.setattr(rag.db, "disponivel", lambda: True)
    monkeypatch.setattr(rag.db, "obter_config", lambda chave: "")
    monkeypatch.setattr(rag, "_gerar_embeddings",
                        lambda textos, para_consulta: None)

    def _explode(funcao, params):
        raise rag.ErroRAG("base indisponível")

    monkeypatch.setattr(rag, "_executar_rpc", _explode)
    avisos = []
    monkeypatch.setattr(rag.st, "warning", avisos.append)
    contexto = rag.montar_contexto(BENS_SRP, "tr")
    assert contexto["bloco"] == ""
    assert avisos and "erro" in contexto["trace"]


@pytest.mark.parametrize("dados,doc_key", [
    (BENS_SRP, "dfd"), (SERVICO_CONTINUO, "etp"), (SAAS_TI, "tr"),
    (BENS_SEM_SRP, "edital"),
])
def test_recuperacao_funciona_para_objetos_diferentes(monkeypatch, dados,
                                                      doc_key):
    _fingir_base(monkeypatch, lambda consulta: [])
    resultado = rag.recuperar(dados, doc_key)
    assert resultado["consultas"][0]["tema"] == "geral"
    assert len(resultado["consultas"]) <= rag.MAX_TEMAS + 1


# --------------------------------------------------------------------------
# GROUNDING pós-geração: citação sem lastro vira finding
# --------------------------------------------------------------------------
def _lastro(*dispositivos):
    """Lastro no formato `norma:artigo` (identidade completa)."""
    return set(dispositivos)


def test_artigo_sustentado_pelo_trace_passa():
    from src import validacao

    texto = ("## 3. DO REGIME\n\n3.1. Observa-se o art. 211 da Lei nº "
             "14.133/2021.\n")
    achados = validacao.validar_documento(
        "edital", texto, _lastro("lei_14133_2021:211"))
    assert not any("sem lastro" in a["mensagem"] for a in achados)


def test_artigo_do_mapa_canonico_passa():
    from src import validacao

    texto = ("## 2. DA ATA\n\n2.5. Vigência de 1 (um) ano (art. 84), "
             "com pagamento na forma dos arts. 141 a 146.\n")
    achados = validacao.validar_documento("edital", texto, _lastro())
    assert not any("sem lastro" in a["mensagem"] for a in achados)


def test_artigo_sem_trace_e_fora_do_mapa_gera_finding():
    from src import validacao

    texto = "## 8. DAS SANÇÕES\n\n8.1. Aplica-se o art. 347 da Lei.\n"
    achados = validacao.validar_documento(
        "edital", texto, _lastro("lei_14133_2021:211"))
    mensagens = [a["mensagem"] for a in achados if "sem lastro" in a["mensagem"]]
    assert mensagens and "347" in mensagens[0]


def test_correcao_preferida_remove_o_numero_e_nao_inventa_substituto():
    from src import achados as achados_mod
    from src import validacao

    texto = "## 8. DAS SANÇÕES\n\n8.1. Aplica-se o art. 347 da Lei.\n"
    bruto = [a for a in validacao.validar_documento("edital", texto, set())
             if "sem lastro" in a["mensagem"]]
    finding = achados_mod.estruturar(bruto, {"edital": texto})[0]
    assert finding["categoria"] == "fundamento_sem_lastro"
    assert "Remoção do número" in finding["resultadoEsperado"]
    assert "NUNCA a substituição por outro artigo" in finding["resultadoEsperado"]


def test_sem_rastro_do_rag_a_checagem_nao_opina():
    from src import validacao

    texto = "## 8. DAS SANÇÕES\n\n8.1. Aplica-se o art. 347 da Lei.\n"
    achados = validacao.validar_documento("edital", texto)   # lastro=None
    assert not any("sem lastro" in a["mensagem"] for a in achados)


def test_mapa_canonico_nao_aceita_numero_espurio():
    from src import prompts

    # "art. 84 (1 ano…)" e "LC nº 123/2006" não podem virar lastro
    for espurio in ("1", "123", "2006"):
        assert f"lei_14133_2021:{espurio}" not in prompts.DISPOSITIVOS_CANONICOS
    assert {"lei_14133_2021:84", "lei_14133_2021:141",
            "lei_14133_2021:156"} <= prompts.DISPOSITIVOS_CANONICOS
    # e o lastro canônico é ANCORADO na norma: nada de número solto
    assert all(":" in d for d in prompts.DISPOSITIVOS_CANONICOS)


def test_prompt_e_validacao_leem_o_mesmo_mapa():
    from src import prompts

    # o texto da regra 7 é gerado a partir da estrutura: não há duas
    # listas para divergirem
    assert "{MAPA_CANONICO}" not in prompts.SYSTEM_PROMPT_BASE
    for _, _, referencia in prompts.MAPA_CANONICO:
        assert referencia in prompts.SYSTEM_PROMPT_BASE


def test_lastro_do_trace_extrai_dispositivos_das_fontes():
    trace = {"referencias": [
        {"titulo": "Lei nº 14.133/2021", "categoria": "lei",
         "dispositivos": ["lei_14133_2021:84", "lei_14133_2021:86"]},
        {"titulo": "Decreto municipal", "categoria": "lei",
         "dispositivos": ["decreto_7_2024:7"]}]}
    assert rag.lastro_do_trace(trace) == {
        "lei_14133_2021:84", "lei_14133_2021:86", "decreto_7_2024:7"}
    assert rag.lastro_do_trace(None) == set()


def test_trace_registra_dispositivos_do_trecho_recuperado(monkeypatch):
    chunk = _chunk("c1", "Lei nº 14.133/2021", "lei",
                   "Art. 84. A vigência da ata será de 1 (um) ano. "
                   "Art. 86. A adesão observará…", 0.8)
    _fingir_base(monkeypatch, lambda consulta: [chunk])
    trace = rag.montar_contexto(BENS_SRP, "edital")["trace"]
    assert trace["referencias"][0]["dispositivos"] == [
        "lei_14133_2021:84", "lei_14133_2021:86"]


# --------------------------------------------------------------------------
# Orçamento revisado: núcleo garantido + reserva por tema
# --------------------------------------------------------------------------
def test_sancoes_do_tr_recebem_consulta_tematica():
    temas = rag.temas_para(BENS_SRP, "tr")
    for essencial in ("execucao_recebimento", "pagamento", "sancoes",
                      "gestao_fiscalizacao"):
        assert essencial in temas
    # tema condicional não expulsa o núcleo
    assert "srp" in temas


def test_tema_prioritario_mantem_pelo_menos_um_chunk(monkeypatch):
    forte = [_chunk(f"forte{i}", "Lei nº 14.133/2021", "lei",
                    f"Art. 4{i}. Requisitos…", 0.99) for i in range(9)]
    sancao = _chunk("sancao", "Lei nº 14.133/2021", "lei",
                    "Art. 156. São sanções…", 0.30)

    def resultados(consulta):
        if "sanções" in str(consulta) or "infrações" in str(consulta):
            return [sancao]
        return forte

    _fingir_base(monkeypatch, resultados)
    referencias = rag.recuperar(BENS_SRP, "tr")["referencias"]
    ids = {r["id"] for r in referencias}
    assert "sancao" in ids           # sobreviveu ao ranking global
    assert len(referencias) <= rag.MAX_CHUNKS_PROMPT
    assert len(ids) == len(referencias)      # sem duplicatas


# --------------------------------------------------------------------------
# Identidade norma:dispositivo e quem pode fornecer lastro
# --------------------------------------------------------------------------
def test_artigo_de_outra_norma_nao_sustenta_o_mesmo_numero_da_lei():
    from src import validacao

    # o art. 84 do decreto NÃO autoriza o art. 84 da Lei nº 14.133/2021
    texto = ("## 2. DA ATA\n\n2.5. A vigência observa o art. 84 do Decreto "
             "nº 10.024/2019 e o art. 250 da Lei nº 14.133/2021.\n")
    lastro = {"decreto_10024_2019:84", "decreto_10024_2019:250"}
    mensagens = [a["mensagem"] for a in
                 validacao.validar_documento("edital", texto, lastro)
                 if "sem lastro" in a["mensagem"]]
    assert mensagens and "250" in mensagens[0]
    assert "lei_14133_2021" in mensagens[0]


def test_artigo_da_norma_correta_tem_lastro():
    from src import validacao

    texto = ("## 3. DO REGIME\n\n3.1. Observa-se o art. 250 da Lei nº "
             "14.133/2021.\n")
    achados = validacao.validar_documento("edital", texto,
                                          {"lei_14133_2021:250"})
    assert not any("sem lastro" in a["mensagem"] for a in achados)


def test_processo_anterior_nao_fornece_lastro():
    trace = {"referencias": [
        {"titulo": "Edital 2019", "categoria": "processo_anterior",
         "dispositivos": ["lei_14133_2021:250"]},
        {"titulo": "Minuta padrão", "categoria": "modelo",
         "dispositivos": ["lei_14133_2021:251"]}]}
    assert rag.lastro_do_trace(trace) == set()


def test_acordao_nao_autoriza_dispositivo_de_lei():
    trace = {"referencias": [
        {"titulo": "Acórdão 1234/2023-TCU", "categoria": "acordao",
         "dispositivos": ["lei_14133_2021:250"]}]}
    assert rag.lastro_do_trace(trace) == set()


def test_legislacao_fornece_lastro():
    trace = {"referencias": [
        {"titulo": "Lei nº 14.133/2021", "categoria": "lei",
         "dispositivos": ["lei_14133_2021:250"]},
        {"titulo": "Decreto municipal nº 45/2024", "categoria": "lei",
         "dispositivos": ["decreto_45_2024:7"]}]}
    assert rag.lastro_do_trace(trace) == {"lei_14133_2021:250",
                                          "decreto_45_2024:7"}


def test_norma_do_chunk_vem_do_titulo_quando_o_trecho_nao_a_declara():
    # trecho cru da lei ("Art. 84. …") sem repetir o nome da norma
    assert rag.dispositivos_do_trecho(
        "Art. 84. A vigência da ata…", "Lei nº 14.133/2021") == [
        "lei_14133_2021:84"]
    # sem norma identificável em lugar nenhum, não há lastro
    assert rag.dispositivos_do_trecho("Art. 84. …", "Apostila") == []


# --------------------------------------------------------------------------
# Trace pertence à geração que produziu o documento
# --------------------------------------------------------------------------
def _preparar_geracao(monkeypatch, chunk_conteudo, falhar_tudo=False,
                      falhar_openai=False):
    import streamlit as st

    from src import conhecimento, planilha, prompts

    st.session_state.clear()
    monkeypatch.setattr(llm, "obter_openai_key", lambda: "k-openai")
    monkeypatch.setattr(llm, "obter_api_key", lambda: "k-gemini")
    monkeypatch.setattr(llm, "montar_prompt",
                        lambda doc, dados, ctx: ("s", "u"))
    monkeypatch.setattr(llm, "registrar_geracao",
                        lambda *a, **k: {})
    monkeypatch.setattr(conhecimento, "diretrizes_para_prompt",
                        lambda *a, **k: "")
    monkeypatch.setattr(planilha, "injetar_tabela", lambda texto, itens: texto)
    monkeypatch.setattr(
        rag, "montar_contexto",
        lambda dados, doc: {"bloco": "", "trace": {
            "modo": "vetorial", "consultas": [],
            "referencias": [{"titulo": "Lei nº 14.133/2021",
                             "categoria": "lei",
                             "dispositivos": [chunk_conteudo]}]}})

    def _openai(s, u, chave):
        if falhar_tudo or falhar_openai:
            raise llm.ErroGeracaoIA("openai fora do ar")
        return f"texto via openai ({chunk_conteudo})"

    def _gemini(s, u, chave):
        if falhar_tudo:
            raise llm.ErroGeracaoIA("gemini fora do ar")
        return f"texto via gemini ({chunk_conteudo})"

    monkeypatch.setattr(llm, "_chamar_openai", _openai)
    monkeypatch.setattr(llm, "_chamar_gemini", _gemini)
    monkeypatch.setattr(llm.st, "warning", lambda *a, **k: None)
    return st


def test_geracao_bem_sucedida_associa_o_trace_novo(monkeypatch):
    st = _preparar_geracao(monkeypatch, "lei_14133_2021:84")
    texto = llm.gerar_documento("tr", BENS_SRP, None)
    trace = st.session_state["_rag_trace"]["tr"]
    assert trace["referencias"][0]["dispositivos"] == ["lei_14133_2021:84"]
    assert trace["hash_texto"]           # amarrado ao texto produzido
    assert rag.lastro_do_trace(trace) == {"lei_14133_2021:84"}
    assert "openai" in texto


def test_falha_de_todas_as_engines_preserva_o_trace_anterior(monkeypatch):
    import pytest as _pytest

    st = _preparar_geracao(monkeypatch, "lei_14133_2021:84")
    llm.gerar_documento("tr", BENS_SRP, None)
    anterior = st.session_state["_rag_trace"]["tr"]

    # nova tentativa (com outro rastro) que fracassa em todos os motores
    _preparar_geracao(monkeypatch, "lei_14133_2021:999", falhar_tudo=True)
    st.session_state["_rag_trace"] = {"tr": anterior}
    with _pytest.raises(llm.ErroGeracaoIA):
        llm.gerar_documento("tr", BENS_SRP, None)
    assert st.session_state["_rag_trace"]["tr"] is anterior
    assert rag.lastro_do_trace(
        st.session_state["_rag_trace"]["tr"]) == {"lei_14133_2021:84"}


def test_fallback_para_gemini_associa_o_trace_da_geracao_vencedora(monkeypatch):
    st = _preparar_geracao(monkeypatch, "lei_14133_2021:140",
                           falhar_openai=True)
    texto = llm.gerar_documento("tr", BENS_SRP, None)
    assert "gemini" in texto
    assert rag.lastro_do_trace(
        st.session_state["_rag_trace"]["tr"]) == {"lei_14133_2021:140"}


# --------------------------------------------------------------------------
# Busca textual: websearch_to_tsquery combina termos com E — a frase
# temática inteira zera a recuperação (medido na base real)
# --------------------------------------------------------------------------
def test_consulta_textual_usa_ou_entre_termos_significativos():
    consulta = rag.consulta_textual(
        "pagamento liquidação da despesa ordem cronológica prazo de "
        "pagamento nota fiscal atesto")
    assert " or " in consulta
    assert "pagamento" in consulta and "liquidação" in consulta
    # preposições e artigos não viram termo de busca
    for stop in (" da ", " de ", " or da or ", " or de or "):
        assert stop not in f" {consulta} "
    # sem repetição e dentro do teto
    termos = consulta.split(" or ")
    assert len(termos) == len(set(termos)) <= 6


def test_busca_textual_recebe_a_consulta_reduzida(monkeypatch):
    enviadas = []

    monkeypatch.setattr(rag.db, "disponivel", lambda: True)
    monkeypatch.setattr(rag.db, "obter_config", lambda chave: "")
    monkeypatch.setattr(rag, "_gerar_embeddings",
                        lambda textos, para_consulta: None)   # modo textual

    def _rpc(funcao, params):
        enviadas.append(params.get("consulta"))
        return []

    monkeypatch.setattr(rag, "_executar_rpc", _rpc)
    rag.recuperar(BENS_SRP, "tr")
    assert enviadas and all(" or " in c for c in enviadas)
    assert all(len(c.split(" or ")) <= 6 for c in enviadas)


def test_busca_vetorial_mantem_a_consulta_semantica_completa(monkeypatch):
    monkeypatch.setattr(rag.db, "disponivel", lambda: True)
    monkeypatch.setattr(rag.db, "obter_config", lambda chave: "")
    monkeypatch.setattr(rag, "_gerar_embeddings",
                        lambda textos, para_consulta: [[0.1] * 8
                                                       for _ in textos])
    monkeypatch.setattr(rag, "_executar_rpc", lambda funcao, params: [])
    resultado = rag.recuperar(BENS_SRP, "tr")
    # a consulta registrada no trace é a frase temática, não a reduzida
    assert all(" or " not in c["texto"] for c in resultado["consultas"])


def test_trace_nao_inventa_campos_que_o_rpc_nao_devolve(monkeypatch):
    # os RPCs devolvem apenas conteudo/titulo/categoria/similaridade
    real = {"conteudo": "Art. 84. …", "titulo": "Lei nº 14.133/2021",
            "categoria": "lei", "similaridade": 0.7}
    _fingir_base(monkeypatch, lambda consulta: [real])
    referencia = rag.montar_contexto(BENS_SRP, "edital")["trace"]["referencias"][0]
    assert "documento_id" not in referencia and "ordem" not in referencia
    assert referencia["titulo"] == "Lei nº 14.133/2021"
    assert referencia["dispositivos"] == ["lei_14133_2021:84"]


# --------------------------------------------------------------------------
# Índice vetorial V2: um único provedor/modelo, sem fallback silencioso
# --------------------------------------------------------------------------
def test_embeddings_nao_caem_para_outro_provedor(monkeypatch):
    """Sem chave do provedor do índice NÃO se gera vetor com outro motor."""
    from src import llm

    chamou_gemini = []
    monkeypatch.setattr(llm, "obter_openai_key", lambda: "")
    monkeypatch.setattr(llm, "obter_api_key",
                        lambda: chamou_gemini.append(True) or "k-gemini")
    avisos = []
    monkeypatch.setattr(rag.st, "warning", avisos.append)

    assert rag._gerar_embeddings(["texto"], para_consulta=False) is None
    assert not chamou_gemini            # o Gemini nem foi consultado
    assert any("NÃO admite outro provedor" in a for a in avisos)


def test_proveniencia_v2_e_fixa_e_declarada():
    from src import config

    p = rag.proveniencia_v2()
    assert p["embedding_provider"] == config.EMBEDDING_V2_PROVEDOR == "openai"
    assert p["embedding_model"] == "text-embedding-3-small"
    assert p["embedding_dimensions"] == 768
    assert p["embedding_version"] == config.EMBEDDING_V2_VERSAO


def test_dimensao_divergente_e_recusada(monkeypatch):
    """Vetor fora da dimensão do índice não entra na base."""
    import types as _types

    from src import llm

    monkeypatch.setattr(llm, "obter_openai_key", lambda: "k")

    class _Embeddings:
        def create(self, **kwargs):
            return _types.SimpleNamespace(
                data=[_types.SimpleNamespace(embedding=[0.1] * 1536)])

    class _Cliente:
        def __init__(self, **kwargs):
            self.embeddings = _Embeddings()

    monkeypatch.setitem(sys.modules, "openai",
                        _types.SimpleNamespace(OpenAI=_Cliente))
    with pytest.raises(rag.ErroRAG, match="dimensão"):
        rag._gerar_embeddings(["texto"], para_consulta=False)


def test_indexacao_sem_vetor_fica_pendente_e_avisa(monkeypatch):
    """Nunca mais `embedding = NULL` silencioso (causa dos 34% sem vetor)."""
    gravados = {}

    class _Tabela:
        def __init__(self, nome):
            self.nome = nome

        def insert(self, dados):
            gravados.setdefault(self.nome, []).extend(
                dados if isinstance(dados, list) else [dados])
            return self

        def execute(self):
            return _Resposta(gravados[self.nome][-1:])

    class _Resposta:
        def __init__(self, data):
            self.data = [{"id": "doc-1"}] if data and "titulo" in data[0] else data

    class _Cliente:
        def table(self, nome):
            return _Tabela(nome)

    monkeypatch.setattr(rag.db, "disponivel", lambda: True)
    monkeypatch.setattr(rag.db, "_cliente", _Cliente)
    monkeypatch.setattr(rag, "_gerar_embeddings",
                        lambda textos, para_consulta: None)
    avisos = []
    monkeypatch.setattr(rag.st, "warning", avisos.append)

    rag.indexar_arquivo("norma.txt", "Norma", "lei", b"x" * 200)
    chunks = gravados["chunks_referencia"]
    assert chunks and all(c["embedding_status"] == "pendente" for c in chunks)
    assert all(c["embedding_v2"] is None for c in chunks)
    assert all("embedding_provider" not in c for c in chunks)
    assert any("PENDENTE de indexação vetorial" in a for a in avisos)


def test_indexacao_com_vetor_grava_proveniencia_completa(monkeypatch):
    gravados = {}

    class _Tabela:
        def __init__(self, nome):
            self.nome = nome

        def insert(self, dados):
            gravados.setdefault(self.nome, []).extend(
                dados if isinstance(dados, list) else [dados])
            return self

        def execute(self):
            return type("R", (), {"data": [{"id": "doc-1"}]})()

    class _Cliente:
        def table(self, nome):
            return _Tabela(nome)

    monkeypatch.setattr(rag.db, "disponivel", lambda: True)
    monkeypatch.setattr(rag.db, "_cliente", _Cliente)
    monkeypatch.setattr(rag, "_gerar_embeddings",
                        lambda textos, para_consulta: [[0.1] * 768
                                                       for _ in textos])
    rag.indexar_arquivo("norma.txt", "Norma", "lei", b"x" * 200)
    chunk = gravados["chunks_referencia"][0]
    assert chunk["embedding_status"] == "ok"
    assert chunk["embedding_provider"] == "openai"
    assert chunk["embedding_model"] == "text-embedding-3-small"
    assert chunk["embedding_dimensions"] == 768
    assert chunk["embedding_version"] == "v2"
    assert chunk["embedding_generated_at"]


# --------------------------------------------------------------------------
# Categoria `manual`: apoia a redação, não fundamenta dispositivo
# --------------------------------------------------------------------------
def test_manual_esta_no_catalogo_e_fora_da_legislacao():
    assert rag.CATEGORIAS["manual"] == "Manual / Orientação técnica"
    assert "manual" in rag.MANUAIS
    assert "manual" not in rag.LEGISLACAO
    assert "manual" not in rag.CONTROLE
    assert "manual" not in rag.NORMATIVAS


def test_manual_nao_fornece_lastro_juridico():
    trace = {"referencias": [
        {"titulo": "Manual de Licitações (AGU)", "categoria": "manual",
         "dispositivos": ["lei_14133_2021:40"]},
        {"titulo": "Modelo de TR", "categoria": "modelo",
         "dispositivos": ["lei_14133_2021:41"]},
        {"titulo": "Lei nº 14.133/2021", "categoria": "lei",
         "dispositivos": ["lei_14133_2021:84"]}]}
    # só a legislação sustenta dispositivo
    assert rag.lastro_do_trace(trace) == {"lei_14133_2021:84"}


def test_manual_fica_abaixo_de_lei_e_de_controle_e_acima_dos_moldes():
    prioridade = rag._prioridade_fonte
    assert (prioridade({"categoria": "lei"})
            > prioridade({"categoria": "acordao"})
            > prioridade({"categoria": "manual"})
            > prioridade({"categoria": "modelo"}))
    assert prioridade({"categoria": "manual"}) > prioridade(
        {"categoria": "processo_anterior"})


def test_manual_e_rotulado_sem_forca_normativa_no_bloco(monkeypatch):
    manual = _chunk("c-manual", "Manual de Licitações e Contratações (AGU)",
                    "manual", "Orientação sobre a fase preparatória…", 0.9)
    lei = _chunk("c-lei", "Lei nº 14.133/2021", "lei",
                 "Art. 18. A fase preparatória…", 0.4)
    _fingir_base(monkeypatch, lambda consulta: [manual, lei])
    bloco = rag.montar_bloco_referencias(BENS_SRP, "etp")

    assert "Manual / Orientação técnica" in bloco
    assert "NÃO fornece dispositivo normativo" in bloco
    assert "não obriga o Município" in bloco
    # apesar do score maior, a lei aparece antes do manual
    assert bloco.index("Lei nº 14.133/2021") < bloco.index(
        "Manual de Licitações e Contratações (AGU)")


def test_categoria_manual_do_codigo_existe_no_banco():
    """O CHECK do banco (migração 0017) e o catálogo do código batem."""
    migracao = (RAIZ_REPO / "supabase" / "migrations"
                / "0017_categoria_manual.sql").read_text(encoding="utf-8")
    for categoria in rag.CATEGORIAS:
        assert f"'{categoria}'::text" in migracao
