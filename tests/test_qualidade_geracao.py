"""
Regressões de QUALIDADE DA GERAÇÃO a partir de defeitos reais observados
nos documentos gerados pela Prefeitura de Paragominas:
  - "(fonte: formulário)" vazando no corpo (mecânica interna);
  - "conforme o formulário" referenciando a mecânica interna;
  - cláusula meta-descritiva ("Indicação da solução... conforme...");
  - o prompt endurecido contra improviso e meta-texto.
Garante que a revisão CAPTURA esses defeitos e o corretor recebe o que
é pontual.
"""

from src import achados, prompts, validacao

# Trechos LITERAIS extraídos dos documentos reais gerados.
CLAUSULA_COM_FONTE = (
    "## 2. JUSTIFICATIVA\n\n"
    "Atender as necessidades administrativas da Prefeitura Municipal e "
    "das secretarias que compõem a esfera municipal. (fonte: formulário)\n"
)
CLAUSULA_META = (
    "## 4. SOLUÇÃO PROPOSTA PELO DEMANDANTE\n\n"
    "Indicação da solução proposta pelo demandante para atender à "
    "necessidade, conforme informações do formulário.\n"
)
DOC_BOM = (
    "## 2. JUSTIFICATIVA\n\n"
    "A contratação justifica-se pela necessidade de assegurar o "
    "fornecimento contínuo e padronizado de materiais de expediente às "
    "secretarias, com economicidade via Sistema de Registro de Preços "
    "(art. 82 da Lei nº 14.133/2021).\n"
)


# ---------------------------------------------------------------------------
# validacao.py captura os defeitos
# ---------------------------------------------------------------------------
def test_etiqueta_fonte_formulario_bloqueia_emissao():
    achados_v = validacao.validar_documento("dfd", CLAUSULA_COM_FONTE)
    bloqueios = validacao.bloqueios(achados_v)
    assert any("etiqueta de origem interna" in a["mensagem"]
               for a in bloqueios)


def test_conforme_o_formulario_bloqueia():
    texto = ("## 3. NECESSIDADE\n\nDescrição da necessidade conforme o "
             "formulário apresentado.\n")
    bloqueios = validacao.bloqueios(validacao.validar_documento("dfd", texto))
    assert any("mecânica interna" in a["mensagem"] for a in bloqueios)


def test_clausula_meta_descritiva_e_aviso():
    avisos = validacao.avisos(validacao.validar_documento("dfd", CLAUSULA_META))
    assert any("meta-descritiva" in a["mensagem"] for a in avisos)


def test_clausula_bem_desenvolvida_nao_gera_achado_de_qualidade():
    achados_v = validacao.validar_documento("dfd", DOC_BOM)
    mensagens = " ".join(a["mensagem"] for a in achados_v)
    assert "origem interna" not in mensagens
    assert "meta-descritiva" not in mensagens
    assert "conforme o formulário" not in mensagens


def test_fonte_legitima_de_lei_nao_e_bloqueada():
    # "(fonte: TCU Acórdão …)" ou citação de lei não pode ser falso-positivo
    texto = ("## 7. VALOR\n\nO valor estimado observa o art. 23 da Lei nº "
             "14.133/2021 e a pesquisa de preços realizada.\n")
    assert validacao.bloqueios(validacao.validar_documento("dfd", texto)) == []


# ---------------------------------------------------------------------------
# achados.py estrutura os novos defeitos para o ciclo de correção
# ---------------------------------------------------------------------------
def test_fonte_formulario_vira_finding_corrigivel():
    # doc sem perfil isola o achado do vazamento (sem "documento raso")
    relatorio = achados.gerar_relatorio({"memo": CLAUSULA_COM_FONTE})
    f = next(x for x in relatorio["findings"]
             if x["categoria"] == "vazamento_mecanica_interna")
    assert f["autoCorrectable"] is True      # remoção pontual da etiqueta
    assert f["severity"] == "HIGH"
    assert relatorio["status"] != "APPROVED"


def test_meta_descritiva_vira_finding_nao_corrigivel():
    relatorio = achados.gerar_relatorio({"dfd": CLAUSULA_META})
    f = next(x for x in relatorio["findings"]
             if x["categoria"] == "clausula_nao_desenvolvida")
    # reescrever a cláusula inteira não é patch pontual → revisor/regeração
    assert f["autoCorrectable"] is False
    assert f["blockingReason"] == achados.MOTIVO_DISCRICIONARIO


# ---------------------------------------------------------------------------
# prompt endurecido contra os modos de falha
# ---------------------------------------------------------------------------
def test_system_prompt_proibe_improviso_e_meta_texto():
    p = prompts.SYSTEM_PROMPT_BASE
    assert "MARCADOR, NUNCA IMPROVISO" in p
    assert "ESCREVA O CONTEÚDO, NÃO O DESCREVA" in p
    assert "(fonte: formulário)" in p          # citado como exemplo ERRADO
    assert "PROIBIDO EXPOR A ORIGEM DO DADO" in p
    # o exemplo bom/ruim de Justificativa está presente
    assert "EXEMPLO DO PADRÃO EXIGIDO" in p
