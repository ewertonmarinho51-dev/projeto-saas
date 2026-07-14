"""
Testes dos findings estruturados (Etapa 1 da correção automática):
classificação, escopo autorizado, caminhos bloqueados, campos
requeridos, status do relatório e comportamento da feature flag
(OFF = shadow mode, tela idêntica à anterior).
"""

from src import achados

# Documento "limpo": sem pendências, numeração sequencial, cláusulas com
# conteúdo. doc_key fora dos perfis (sem exigência de cláusulas/palavras).
DOC_LIMPO = """## 1. OBJETO

Aquisição de material escolar para a rede municipal.

## 2. VIGÊNCIA

Doze meses a contar da assinatura.
"""

CAMPOS_SCHEMA = {
    "findingId", "documentId", "categoria", "severity", "descricao",
    "evidencia", "regraViolada", "resultadoEsperado", "autoCorrectable",
    "allowedPaths", "blockedPaths", "sourceIds", "blockingReason",
}


def test_documento_limpo_gera_relatorio_aprovado():
    rel = achados.gerar_relatorio({"memo": DOC_LIMPO})
    assert rel["status"] == "APPROVED"
    assert rel["findings"] == []
    assert "Nenhum problema" in rel["summary"]


def test_todo_finding_tem_os_campos_do_schema():
    doc = DOC_LIMPO + "\n[PREENCHER: prazo]\n\ncomo modelo de linguagem\n"
    rel = achados.gerar_relatorio({"memo": doc})
    assert rel["findings"]
    for f in rel["findings"]:
        assert CAMPOS_SCHEMA <= set(f), f"faltam campos em {f['findingId']}"


def test_campo_pendente_bloqueia_e_lista_campos_requeridos():
    doc = DOC_LIMPO + "\nPrazo: [PREENCHER: prazo de vigência]\n"
    rel = achados.gerar_relatorio({"memo": doc})
    f = next(x for x in rel["findings"] if x["categoria"] == "dado_pendente")
    assert f["autoCorrectable"] is False
    assert f["blockingReason"] == achados.MOTIVO_DADO_AUSENTE
    assert f["camposRequeridos"] == ["prazo de vigência"]
    assert rel["status"] == "BLOCKED"


def test_mencao_a_ia_e_corrigivel_com_escopo_no_bloco_certo():
    doc = DOC_LIMPO + "\nEste texto foi redigido como modelo de linguagem.\n"
    rel = achados.gerar_relatorio({"memo": doc})
    f = next(x for x in rel["findings"]
             if x["categoria"] == "vazamento_mecanica_interna")
    assert f["autoCorrectable"] is True
    assert f["severity"] == "HIGH"
    assert f["allowedPaths"] == ["memo/clausula/2/2"]
    assert rel["status"] == "CORRECTIONS_REQUIRED"


def test_marcador_de_tabela_e_corrigivel_com_fonte_do_formulario():
    doc = DOC_LIMPO + "\n[[TABELA_ITENS]]\n"
    rel = achados.gerar_relatorio({"memo": doc})
    f = next(x for x in rel["findings"]
             if x["categoria"] == "marcador_interno")
    assert f["autoCorrectable"] is True
    assert f["sourceIds"] == ["formulario:itens"]


def test_numeracao_duplicada_autoriza_somente_os_titulos():
    doc = "## 1. OBJETO\n\ntexto\n\n## 1. VIGÊNCIA\n\ntexto b\n"
    rel = achados.gerar_relatorio({"memo": doc})
    f = next(x for x in rel["findings"] if x["categoria"] == "numeracao")
    assert f["autoCorrectable"] is True
    assert f["allowedPaths"] == ["memo/clausula/1/0", "memo/clausula/1.2/0"]


def test_clausula_obrigatoria_ausente_aponta_caminho_futuro():
    # dfd tem perfil: cláusulas obrigatórias 1..9 — só a 1 presente
    doc = "## 1. INFORMAÇÕES GERAIS\n\nSetor requisitante: Educação.\n"
    rel = achados.gerar_relatorio({"dfd": doc})
    ausentes = [x for x in rel["findings"]
                if x["categoria"] == "clausula_obrigatoria_ausente"]
    assert ausentes
    f = next(x for x in ausentes if "2." in x["descricao"])
    assert f["allowedPaths"] == ["dfd/clausula/2"]
    assert f["autoCorrectable"] is True


def test_documento_raso_exige_decisao_humana():
    doc = "## 1. INFORMAÇÕES GERAIS\n\nCurto.\n"
    rel = achados.gerar_relatorio({"dfd": doc})
    f = next(x for x in rel["findings"] if x["categoria"] == "profundidade")
    assert f["autoCorrectable"] is False
    assert f["blockingReason"] == achados.MOTIVO_DISCRICIONARIO


def test_clausula_de_assinaturas_e_caminho_bloqueado():
    doc = (DOC_LIMPO
           + "\n## 3. EQUIPE DE PLANEJAMENTO\n\n"
           + "Assinam como modelo de linguagem os responsáveis.\n")
    rel = achados.gerar_relatorio({"memo": doc})
    f = next(x for x in rel["findings"]
             if x["categoria"] == "vazamento_mecanica_interna")
    # o trecho está DENTRO da cláusula bloqueada: sem correção automática
    assert "memo/clausula/3/1" in f["blockedPaths"]
    assert f["allowedPaths"] == []
    assert f["autoCorrectable"] is False


def test_relatorio_e_deterministico_para_o_mesmo_conteudo():
    doc = {"memo": DOC_LIMPO + "\n[PREENCHER: valor]\n"}
    rel1, rel2 = achados.gerar_relatorio(doc), achados.gerar_relatorio(doc)
    estaveis = ("status", "bundleHash", "summary")
    assert all(rel1[c] == rel2[c] for c in estaveis)
    sem_ids = [{k: v for k, v in f.items()} for f in rel1["findings"]]
    assert sem_ids == rel2["findings"]


# ---------------------------------------------------------------------------
# Feature flag: OFF = shadow mode (tela idêntica), ON = relatório na tela
# ---------------------------------------------------------------------------
def test_flag_desligada_nao_leva_relatorio_para_a_tela(monkeypatch, caplog):
    monkeypatch.setattr(achados.db, "flag_ativa", lambda nome: False)
    with caplog.at_level("INFO", logger="govdocs.achados"):
        resultado = achados.relatorio_para_tela({"memo": DOC_LIMPO})
    assert resultado is None  # tela final permanece exatamente como antes
    assert any("shadow" in r.message for r in caplog.records)


def test_flag_ligada_entrega_relatorio_estruturado(monkeypatch):
    monkeypatch.setattr(
        achados.db, "flag_ativa",
        lambda nome: nome == achados.FLAG_ACHADOS)
    resultado = achados.relatorio_para_tela({"memo": DOC_LIMPO}, "proc-1")
    assert resultado is not None
    assert resultado["status"] == "APPROVED"
    assert resultado["bundleId"] == "proc-1"
