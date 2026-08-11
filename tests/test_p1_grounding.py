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

import pytest

from src import llm, rag

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
    assert "pode fundamentar juridicamente" in bloco
    assert "a norma pode ter mudado" in bloco


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
