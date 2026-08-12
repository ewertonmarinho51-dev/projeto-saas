"""
UX e rastreabilidade das pendências humanas.

Defeito de produção corrigido aqui: a tela final pedia
`informação pendente (documento DFD)` — o servidor não tinha como saber
o que o sistema queria. Critério de aceite: se o sistema pede ajuda
humana, o usuário nunca precisa adivinhar o que responder.

Nada aqui afrouxa a regra material: [PREENCHER] continua bloqueando a
emissão, o dado ausente continua exigindo intervenção humana e nenhum
valor é inferido para liberar o documento — o que muda é a PERGUNTA.
"""

from src import achados, ciclo, validacao
from src.ui import revisao

# ---------------------------------------------------------------------------
# Fixture de regressão: o documento que produziu a tela reportada.
# Todos os marcadores são "secos" ([PREENCHER] sem descrição) — a forma
# que os prompts e as minutas de demonstração ainda produzem.
# ---------------------------------------------------------------------------
DOC_DA_TELA_REPORTADA = """## 1. IDENTIFICAÇÃO

- Órgão requisitante: [PREENCHER]
- Responsável pela demanda: [PREENCHER]

## 2. PREÂMBULO

Preâmbulo — órgão, número do processo [PREENCHER], modalidade.

## 3. MATRIZ DE RISCOS

| Risco | Probabilidade | Ação preventiva |
|---|---|---|
| Atraso na entrega | [PREENCHER] | [PREENCHER] |
| Falha de qualidade | [PREENCHER] | [PREENCHER] |

## 4. ENCERRAMENTO

[PREENCHER]

Local e data: [PREENCHER]
"""


def _campos(texto: str) -> list[str]:
    return [p["campo"] for p in validacao.campos_pendentes(texto)]


# ---------------------------------------------------------------------------
# 1. Nome do campo: marcador descrito, rótulo, coluna de tabela, cláusula
# ---------------------------------------------------------------------------
def test_marcador_descrito_pergunta_exatamente_o_que_ele_declara():
    texto = "Prazo: [PREENCHER: prazo de vigência em meses]\n"
    pendencia = validacao.campos_pendentes(texto)[0]
    assert pendencia["campo"] == "prazo de vigência em meses"
    assert pendencia["origem"] == "marcador"


def test_marcador_seco_recebe_o_nome_do_rotulo_que_o_antecede():
    texto = "## 1. IDENTIFICAÇÃO\n\n3.2. Prazo de vigência: [PREENCHER]\n"
    pendencia = validacao.campos_pendentes(texto)[0]
    # a numeração da cláusula não faz parte do nome do campo
    assert pendencia["campo"] == "Prazo de vigência"
    assert pendencia["origem"] == "rotulo"


def test_marcador_seco_no_meio_da_enumeracao_pega_a_ultima_expressao():
    texto = "Preâmbulo — órgão, número do processo [PREENCHER], modalidade.\n"
    pendencia = validacao.campos_pendentes(texto)[0]
    assert pendencia["campo"] == "número do processo"


def test_marcador_seco_em_tabela_recebe_o_cabecalho_da_coluna():
    pendencias = [p for p in validacao.campos_pendentes(DOC_DA_TELA_REPORTADA)
                  if p["origem"] == "tabela"]
    assert [p["campo"] for p in pendencias] == [
        "Probabilidade", "Ação preventiva",
        "Probabilidade", "Ação preventiva",
    ]
    # e o qualificador diz de QUAL linha da tabela é cada lacuna
    assert [p["qualificador"] for p in pendencias] == [
        "Atraso na entrega", "Atraso na entrega",
        "Falha de qualidade", "Falha de qualidade",
    ]


def test_marcador_sem_rotulo_algum_cita_a_clausula_e_nunca_o_rotulo_generico():
    texto = "## 4. ENCERRAMENTO\n\n[PREENCHER]\n"
    pendencia = validacao.campos_pendentes(texto)[0]
    assert pendencia["origem"] == "clausula"
    assert "4. ENCERRAMENTO" in pendencia["campo"]
    assert pendencia["campo"] != "informação pendente"


def test_marcador_sem_clausula_e_sem_rotulo_cita_o_trecho():
    pendencia = validacao.campos_pendentes("[PREENCHER] do contrato\n")[0]
    assert pendencia["origem"] == "trecho"
    assert "do contrato" in pendencia["campo"]


def test_nenhum_campo_da_tela_reportada_fica_como_informacao_pendente():
    """Regressão direta do defeito: a tela mostrava rótulos genéricos."""
    campos = _campos(DOC_DA_TELA_REPORTADA)
    assert len(campos) == 9
    assert all(c.strip() and c != "informação pendente" for c in campos)
    assert "Órgão requisitante" in campos
    assert "Responsável pela demanda" in campos
    assert "Local e data" in campos


# ---------------------------------------------------------------------------
# 2. Um achado (e um finding) POR pendência — endereçável individualmente
# ---------------------------------------------------------------------------
def test_cada_marcador_vira_um_achado_com_o_campo_na_mensagem():
    achados_brutos = validacao.validar_documento(
        "dfd", "Prazo: [PREENCHER]\nSetor: [PREENCHER]\n")
    pendentes = [a for a in achados_brutos
                 if a["mensagem"].startswith("campo pendente")]
    assert len(pendentes) == 2
    assert pendentes[0]["mensagem"] == "campo pendente [PREENCHER]: Prazo"
    assert pendentes[1]["mensagem"] == "campo pendente [PREENCHER]: Setor"
    assert all(a["gravidade"] == "bloqueia" for a in pendentes)


def test_finding_de_dado_ausente_carrega_alvo_exato_da_substituicao():
    rel = achados.gerar_relatorio(
        {"dfd": "## 1. OBJETO\n\nPrazo de entrega: [PREENCHER]\n"})
    f = next(x for x in rel["findings"] if x["categoria"] == "dado_pendente")
    assert f["blockingReason"] == achados.MOTIVO_DADO_AUSENTE
    assert f["camposRequeridos"] == ["Prazo de entrega"]
    assert f["pendencias"][0]["marcador"] == "[PREENCHER]"
    assert f["pendencias"][0]["ocorrencia"] == 1
    assert rel["status"] == "BLOCKED"   # a emissão continua bloqueada


# ---------------------------------------------------------------------------
# 3. Deduplicação: uma pergunta por dado, inclusive entre documentos
# ---------------------------------------------------------------------------
def test_mesmo_dado_em_documentos_diferentes_e_perguntado_uma_vez_so():
    rel = achados.gerar_relatorio({
        "dfd": "Prazo: [PREENCHER: prazo de vigência]\n",
        "etp": "A vigência será de [PREENCHER: prazo de vigência].\n",
    })
    pedidos = ciclo._campos_requeridos(rel)
    assert len(pedidos) == 1
    assert pedidos[0]["campo"] == "prazo de vigência"
    assert pedidos[0]["documentos"] == ["dfd", "etp"]
    # …e a resposta única atinge os dois documentos
    assert {a["documento"] for a in pedidos[0]["alvos"]} == {"dfd", "etp"}


def test_lacunas_homonimas_de_linhas_diferentes_nao_sao_deduplicadas():
    """A 'Ação preventiva' do risco A não é a do risco B."""
    rel = achados.gerar_relatorio({"dfd": DOC_DA_TELA_REPORTADA})
    pedidos = ciclo._campos_requeridos(rel)
    acoes = [p for p in pedidos if p["campo"] == "Ação preventiva"]
    assert len(acoes) == 2
    assert {p["qualificador"] for p in acoes} == {"Atraso na entrega",
                                                  "Falha de qualidade"}
    # cada uma com o seu próprio alvo (mesmo marcador, ocorrências distintas)
    ocorrencias = {p["alvos"][0]["ocorrencia"] for p in acoes}
    assert len(ocorrencias) == 2


# ---------------------------------------------------------------------------
# 4. Dado ausente SEM marcador continua sendo uma pergunta formulável
# ---------------------------------------------------------------------------
def test_matricula_improvisada_pergunta_a_matricula_e_nao_um_form_vazio():
    rel = achados.gerar_relatorio(
        {"dfd": "Servidor João — matrícula: 15.\n"})
    f = next(x for x in rel["findings"]
             if x["blockingReason"] == achados.MOTIVO_DADO_AUSENTE)
    assert f["camposRequeridos"] == ["matrícula do agente responsável"]
    pedidos = ciclo._campos_requeridos(rel)
    assert [p["campo"] for p in pedidos] == ["matrícula do agente responsável"]


def test_resposta_de_dado_improvisado_substitui_o_valor_errado_no_lugar():
    """Sem marcador a resposta ainda entra — o molde preserva o rótulo."""
    docs = {"dfd": "Servidor João — matrícula: 15.\n"}
    rel = achados.gerar_relatorio(docs)
    pedido = ciclo._campos_requeridos(rel)[0]
    alvo = pedido["alvos"][0]
    assert alvo["molde"] == "matrícula: {valor}"
    novos = revisao.aplicar_dado_pontual(
        docs, "dfd", pedido["campo"], "48291",
        marcador=alvo["marcador"], ocorrencia=alvo["ocorrencia"],
        molde=alvo["molde"])
    assert novos["dfd"] == "Servidor João — matrícula: 48291.\n"
    # e o achado desaparece na revalidação
    assert not [a for a in validacao.validar_documento("dfd", novos["dfd"])
                if "matrícula" in a["mensagem"]]


def test_cnpj_invalido_pergunta_o_cnpj_e_aplica_a_resposta():
    docs = {"dfd": "Contratada: EMPRESA LTDA, CNPJ 11.111.111/1111-11.\n"}
    rel = achados.gerar_relatorio(docs)
    pedido = next(p for p in ciclo._campos_requeridos(rel)
                  if p["campo"].startswith("CNPJ"))
    alvo = pedido["alvos"][0]
    novos = revisao.aplicar_dado_pontual(
        docs, "dfd", pedido["campo"], "05.514.464/0001-30",
        marcador=alvo["marcador"], ocorrencia=alvo["ocorrencia"],
        molde=alvo["molde"])
    assert "05.514.464/0001-30" in novos["dfd"]
    assert not [a for a in validacao.validar_documento("dfd", novos["dfd"])
                if "CNPJ" in a["mensagem"]]


def test_cada_valor_improvisado_e_uma_pergunta_propria():
    docs = {"dfd": ("Servidora Ana — matrícula: 11.\n"
                    "Servidor Bruno — matrícula: 999999.\n")}
    rel = achados.gerar_relatorio(docs)
    pedidos = ciclo._campos_requeridos(rel)
    matriculas = [p for p in pedidos if p["campo"].startswith("matrícula")]
    assert len(matriculas) == 2
    assert {p["alvos"][0]["molde"] for p in matriculas} == {
        "matrícula: {valor}"}
    assert {p["contexto"] for p in matriculas} == {
        "Servidora Ana — matrícula: 11.",
        "Servidor Bruno — matrícula: 999999.",
    }


# ---------------------------------------------------------------------------
# 5. Decisão discricionária NÃO é caixa de texto
# ---------------------------------------------------------------------------
def test_decisao_discricionaria_vira_card_com_etapa_e_nao_campo_de_texto():
    texto = ("## 5. GARANTIA\n\nGarantia contratual: 5%\n")
    rel = achados.gerar_relatorio({"tr": texto})
    f = next(x for x in rel["findings"]
             if x["blockingReason"] == achados.MOTIVO_DISCRICIONARIO)
    assert "camposRequeridos" not in f      # nunca vira input
    decisoes = ciclo._decisoes_requeridas(rel)
    garantia = next(d for d in decisoes if "garantia" in d["descricao"])
    assert garantia["documento"] == "tr"
    assert garantia["sigla"] == "TR"
    assert garantia["etapa"] == 3           # leva o revisor ao TR
    assert garantia["esperado"]
    # toda decisão sabe para onde mandar o revisor
    assert all(d["etapa"] for d in decisoes)
    assert ciclo._campos_requeridos(rel) == []


# ---------------------------------------------------------------------------
# 6. Aplicação da resposta: cirúrgica, por código, sem IA
# ---------------------------------------------------------------------------
def test_resposta_atinge_somente_a_ocorrencia_perguntada():
    docs = {"dfd": "A: [PREENCHER]\nB: [PREENCHER]\n"}
    novos = revisao.aplicar_dado_pontual(
        docs, "dfd", "B", "valor de B", marcador="[PREENCHER]", ocorrencia=2)
    assert novos["dfd"] == "A: [PREENCHER]\nB: valor de B\n"
    assert docs["dfd"] == "A: [PREENCHER]\nB: [PREENCHER]\n"  # original intacto


def test_resposta_sem_ocorrencia_mantem_o_comportamento_historico():
    docs = {"dfd": "Prazo: [PREENCHER: prazo de vigência]."}
    novos = revisao.aplicar_dado_pontual(
        docs, "dfd", "prazo de vigência", "12 meses")
    assert novos["dfd"] == "Prazo: 12 meses."


def test_varias_respostas_de_uma_vez_caem_cada_uma_na_sua_lacuna():
    """
    Marcadores secos são idênticos: aplicados na ordem do formulário, a
    resposta 1 deslocaria as ocorrências seguintes e a resposta 2 cairia
    na lacuna errada. Regressão do enfileiramento das substituições.
    """
    docs = {"etp": ("## 7. Matriz de Riscos\n\n"
                    "| Risco | Probabilidade | Impacto | Mitigação |\n"
                    "|---|---|---|---|\n"
                    "| Atraso | [PREENCHER] | [PREENCHER] | [PREENCHER] |\n")}
    rel = achados.gerar_relatorio(docs)
    pedidos = ciclo._campos_requeridos(rel)
    assert [p["campo"] for p in pedidos] == [
        "Probabilidade", "Impacto", "Mitigação"]
    novos = revisao.aplicar_respostas(
        docs, [(p, f"<{p['campo']}>") for p in pedidos])
    assert ("| Atraso | <Probabilidade> | <Impacto> | <Mitigação> |"
            in novos["etp"])
    assert "[PREENCHER]" not in novos["etp"]


def test_resposta_em_branco_nao_altera_o_documento():
    """Dado ausente não é inventado: sem resposta, a lacuna permanece."""
    docs = {"dfd": "Prazo de entrega: [PREENCHER]\n"}
    pedidos = ciclo._campos_requeridos(achados.gerar_relatorio(docs))
    assert revisao.aplicar_respostas(docs, [(pedidos[0], "   ")]) == docs


def test_preenchimento_da_ultima_pendencia_desbloqueia_a_emissao():
    """Fim a fim: perguntar → responder → revalidar → deixar de bloquear."""
    docs = {"dfd": "## 1. OBJETO\n\nPrazo de entrega: [PREENCHER]\n"}
    rel = achados.gerar_relatorio(docs)
    pedido = ciclo._campos_requeridos(rel)[0]
    alvo = pedido["alvos"][0]
    novos = revisao.aplicar_dado_pontual(
        docs, alvo["documento"], pedido["campo"], "30 dias corridos",
        marcador=alvo["marcador"], ocorrencia=alvo["ocorrencia"])
    assert "[PREENCHER]" not in novos["dfd"]
    assert not [a for a in validacao.validar_documento("dfd", novos["dfd"])
                if a["mensagem"].startswith("campo pendente")]


# ---------------------------------------------------------------------------
# 7. Rótulo exibido na tela
# ---------------------------------------------------------------------------
def test_rotulo_da_tela_nomeia_o_campo_antes_do_documento():
    rotulo = revisao._rotulo_do_pedido({
        "campo": "prazo de vigência", "documento": "dfd",
        "documentos": ["dfd", "etp"], "qualificador": "",
    })
    assert rotulo == "prazo de vigência (DFD, ETP)"


def test_rotulo_da_tela_inclui_o_qualificador_quando_ha_homonimos():
    rotulo = revisao._rotulo_do_pedido({
        "campo": "Ação preventiva", "documento": "etp",
        "documentos": ["etp"], "qualificador": "Atraso na entrega",
    })
    assert rotulo == "Ação preventiva — Atraso na entrega (ETP)"
