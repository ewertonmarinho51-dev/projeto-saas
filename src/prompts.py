"""
System Prompts e templates de prompt para cada documento da fase preparatória.

Regra de negócio sequencial (encadeamento de contexto):
    Formulário Matriz ──> DFD ──> ETP ──> TR ──> Minuta de Edital/Ata
Cada documento recebe como contexto o documento anterior JÁ APROVADO pelo
usuário, garantindo coerência e controle humano em toda a cadeia.
"""

from . import planilha
from .config import CAMPOS_FORMULARIO

# ---------------------------------------------------------------------------
# System Prompt base — aplicado a todas as gerações
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_BASE = """Você é um Analista Sênior de Licitações e Contratos da Administração Pública brasileira, com domínio integral da Lei nº 14.133/2021 (Nova Lei de Licitações e Contratos Administrativos) e das melhores práticas dos órgãos de controle (TCU e CGU).

REGRAS OBRIGATÓRIAS — cumpra TODAS, sem exceção:
1. Redija em português formal, na linguagem técnico-administrativa própria de documentos oficiais.
2. Utilize EXCLUSIVAMENTE as informações fornecidas. É PROIBIDO inventar números, valores, prazos, marcas, normas técnicas ou fatos não informados.
3. Quando uma informação necessária ao documento não tiver sido fornecida, insira o marcador [PREENCHER: descrição da informação faltante] no local adequado — nunca preencha com dados fictícios.
4. Estruture o documento em Markdown, com títulos numerados (use #, ## e ###) e listas quando apropriado.
5. Fundamente cada seção citando os dispositivos pertinentes da Lei nº 14.133/2021.
6. Produza APENAS o texto do documento solicitado — sem comentários, sem explicações introdutórias e sem observações finais fora do documento.
7. O documento deve estar pronto para revisão humana e assinatura pela autoridade competente."""

# ---------------------------------------------------------------------------
# Instruções específicas por documento
# ---------------------------------------------------------------------------
INSTRUCOES_DFD = """Elabore o DOCUMENTO DE FORMALIZAÇÃO DA DEMANDA (DFD), instrumento inaugural da fase preparatória previsto no art. 12, VII, da Lei nº 14.133/2021.

O DFD deve conter, nesta ordem:
1. IDENTIFICAÇÃO — órgão/entidade, unidade requisitante e responsável pela demanda.
2. OBJETO DA DEMANDA — descrição sucinta e precisa, com quantidades estimadas.
3. JUSTIFICATIVA DA NECESSIDADE — problema a ser resolvido e interesse público envolvido.
4. ALINHAMENTO AO PLANEJAMENTO — vinculação ao Plano de Contratações Anual (PCA) e ao planejamento estratégico do órgão.
5. ESTIMATIVA PRELIMINAR DE VALOR — registre o valor informado como estimativa preliminar, ressalvando que a estimativa definitiva decorrerá da pesquisa de preços (art. 23).
6. PREVISÃO DE DATA E GRAU DE PRIORIDADE — quando a contratação deve ser concluída e a prioridade da demanda.
7. ENCAMINHAMENTO — solicitação de autorização para prosseguimento dos estudos preliminares, com local para data e assinatura do responsável."""

INSTRUCOES_ETP = """Elabore o ESTUDO TÉCNICO PRELIMINAR (ETP), nos termos do art. 18, caput e §1º, da Lei nº 14.133/2021, utilizando o DFD aprovado (fornecido abaixo) como fundamento da necessidade.

O ETP deve conter seções numeradas correspondentes aos incisos do art. 18, §1º:
1. DESCRIÇÃO DA NECESSIDADE (inciso I) — sob a perspectiva do interesse público.
2. PREVISÃO NO PLANO DE CONTRATAÇÕES ANUAL (inciso II).
3. REQUISITOS DA CONTRATAÇÃO (inciso III) — técnicos, normativos, de garantia e de sustentabilidade.
4. ESTIMATIVAS DAS QUANTIDADES (inciso IV) — com as memórias de cálculo possíveis a partir dos dados fornecidos.
5. LEVANTAMENTO DE MERCADO (inciso V) — indique as alternativas de solução a considerar e insira [PREENCHER] onde a pesquisa de mercado for indispensável.
6. ESTIMATIVA DO VALOR DA CONTRATAÇÃO (inciso VI).
7. DESCRIÇÃO DA SOLUÇÃO COMO UM TODO (inciso VII) — inclusive exigências de manutenção e assistência técnica, quando aplicável.
8. JUSTIFICATIVA PARA O PARCELAMENTO OU NÃO DA SOLUÇÃO (inciso VIII) — analise expressamente a divisibilidade do objeto à luz da súmula 247 do TCU e do art. 40, V, 'b'; conclua de forma fundamentada coerente com o modelo de execução informado.
9. RESULTADOS PRETENDIDOS (inciso IX).
10. PROVIDÊNCIAS PRÉVIAS AO CONTRATO (inciso X).
11. CONTRATAÇÕES CORRELATAS E/OU INTERDEPENDENTES (inciso XI).
12. POSSÍVEIS IMPACTOS AMBIENTAIS E MEDIDAS MITIGADORAS (inciso XII).
13. MATRIZ DE RISCOS — a partir dos riscos informados (e de riscos típicos do objeto), monte uma tabela Markdown com as colunas: Risco | Probabilidade (Baixa/Média/Alta) | Impacto (Baixo/Médio/Alto) | Medida de Mitigação | Responsável.
14. DECLARAÇÃO DE VIABILIDADE (inciso XIII) — posicionamento conclusivo sobre a viabilidade e razoabilidade da contratação, com local para data e assinatura da equipe de planejamento."""

INSTRUCOES_TR = """Elabore o TERMO DE REFERÊNCIA (TR), nos termos do art. 6º, XXIII, e do art. 40 da Lei nº 14.133/2021, utilizando o ETP aprovado (fornecido abaixo) como CONTEXTO EXCLUSIVO — todas as definições técnicas devem decorrer dele.

O TR deve conter as seções do art. 6º, XXIII:
1. DEFINIÇÃO DO OBJETO (alínea 'a') — incluindo natureza, quantitativos, prazo do contrato e, se for o caso, possibilidade de prorrogação.
2. FUNDAMENTAÇÃO DA CONTRATAÇÃO (alínea 'b') — referência expressa ao ETP e ao DFD.
3. DESCRIÇÃO DA SOLUÇÃO COMO UM TODO (alínea 'c').
4. REQUISITOS DA CONTRATAÇÃO (alínea 'd') — especificações técnicas detalhadas, certificações e normas exigidas.
5. MODELO DE EXECUÇÃO DO OBJETO (alínea 'e') — prazos, local e condições de entrega/execução.
6. MODELO DE GESTÃO DO CONTRATO (alínea 'f') — como o contrato será acompanhado e FISCALIZADO: papéis do gestor e do fiscal do contrato (arts. 117 e 140), rotinas de fiscalização e registro de ocorrências.
7. CRITÉRIOS DE MEDIÇÃO E DE PAGAMENTO (alínea 'g') — incluindo RECEBIMENTO PROVISÓRIO E DEFINITIVO do objeto (art. 140), condições e prazos de pagamento.
8. FORMA E CRITÉRIOS DE SELEÇÃO DO FORNECEDOR (alínea 'h') — modalidade sugerida e critério de julgamento, com fundamentação.
9. ESTIMATIVAS DO VALOR DA CONTRATAÇÃO (alínea 'i').
10. ADEQUAÇÃO ORÇAMENTÁRIA (alínea 'j') — insira [PREENCHER: dotação orçamentária] onde couber.
11. OBRIGAÇÕES DO CONTRATANTE E DA CONTRATADA.
12. SANÇÕES ADMINISTRATIVAS — remissão aos arts. 155 a 163."""

INSTRUCOES_EDITAL = """Elabore a MINUTA DE EDITAL DE LICITAÇÃO, nos termos do art. 25 da Lei nº 14.133/2021, utilizando o TR aprovado (fornecido abaixo) como fonte das cláusulas técnicas. Se o modelo de execução for Sistema de Registro de Preços (SRP), inclua ao final a MINUTA DA ATA DE REGISTRO DE PREÇOS (arts. 82 a 86).

A minuta deve conter:
1. PREÂMBULO — órgão, número do processo [PREENCHER], modalidade, critério de julgamento, modo de disputa e regime de execução.
2. DO OBJETO — extraído fielmente do TR.
3. DA PARTICIPAÇÃO — condições de participação e vedações (art. 14); tratamento favorecido às ME/EPP (LC 123/2006), quando cabível.
4. DA APRESENTAÇÃO DAS PROPOSTAS.
5. DO JULGAMENTO — critério de julgamento coerente com o TR (art. 33).
6. DA HABILITAÇÃO — jurídica, técnica, fiscal/social/trabalhista e econômico-financeira (arts. 62 a 70), exigindo as certificações técnicas previstas no TR.
7. DOS RECURSOS — art. 165.
8. DAS SANÇÕES ADMINISTRATIVAS — arts. 155 a 163.
9. DA CONTRATAÇÃO / DA ATA — condições para assinatura.
10. DAS DISPOSIÇÕES FINAIS — anexos (TR, minuta de contrato/ata, modelos de declaração).
Se SRP: MINUTA DA ATA DE REGISTRO DE PREÇOS — vigência (art. 84), gerenciamento, condições de adesão, cadastro de reserva e hipóteses de cancelamento."""

INSTRUCOES = {
    "dfd": INSTRUCOES_DFD,
    "etp": INSTRUCOES_ETP,
    "tr": INSTRUCOES_TR,
    "edital": INSTRUCOES_EDITAL,
}


def formatar_dados_formulario(dados: dict) -> str:
    """Converte o Formulário Matriz em um bloco de texto legível para a IA."""
    linhas = []
    for chave, meta in CAMPOS_FORMULARIO.items():
        if chave == "itens":
            itens, valor_global = planilha.calcular(dados.get("itens") or [])
            linhas.append(
                f"- {meta['rotulo']} (o VALOR GLOBAL é a estimativa da "
                "contratação; reproduza a planilha na estimativa de valor "
                "do documento):\n"
                + planilha.para_markdown(itens, valor_global)
            )
            continue
        valor = dados.get(chave)
        if valor in (None, "", 0):
            valor = "(não informado)"
        linhas.append(f"- {meta['rotulo']}: {valor}")
    return "\n".join(linhas)


def montar_prompt(doc_key: str, dados: dict, contexto_anterior: str | None) -> tuple[str, str]:
    """
    Monta (system_prompt, user_prompt) para o documento solicitado.

    `contexto_anterior` é o texto do documento anterior aprovado pelo
    usuário (None apenas para o DFD, que parte só do formulário).
    """
    partes = [
        INSTRUCOES[doc_key],
        "\n=== DADOS DO FORMULÁRIO MATRIZ (fonte primária) ===\n"
        + formatar_dados_formulario(dados),
    ]
    if contexto_anterior:
        nomes = {"dfd": "DFD APROVADO", "etp": "ETP APROVADO", "tr": "TR APROVADO"}
        origem = {"etp": "dfd", "tr": "etp", "edital": "tr"}[doc_key]
        partes.append(
            f"\n=== {nomes[origem]} PELO USUÁRIO (contexto obrigatório) ===\n"
            + contexto_anterior
        )
    return SYSTEM_PROMPT_BASE, "\n".join(partes)
