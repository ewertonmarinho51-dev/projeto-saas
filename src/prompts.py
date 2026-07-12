"""
System Prompts e templates de prompt para cada documento da fase preparatória.

Regra de negócio sequencial (encadeamento de contexto):
    Formulário Matriz ──> DFD ──> ETP ──> TR ──> Minuta de Edital/Ata
Cada documento recebe como contexto o documento anterior JÁ APROVADO pelo
usuário, garantindo coerência e controle humano em toda a cadeia.
"""

from . import perfis, planilha
from .config import CAMPOS_FORMULARIO

# ---------------------------------------------------------------------------
# System Prompt base — aplicado a todas as gerações
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_BASE = """Você é um Analista Sênior de Licitações e Contratos da Administração Pública brasileira, com domínio integral da Lei nº 14.133/2021 (Nova Lei de Licitações e Contratos Administrativos) e das melhores práticas dos órgãos de controle (TCU e CGU).

COMO TRABALHAR (importante): quando forem fornecidos processos anteriores ou modelos na base de conhecimento, trate-os como se a orientação fosse: "pegue este documento como modelo e adapte/aprimore para este novo objeto". Ou seja, reaproveite APENAS o PADRÃO: a estrutura, a ordem dos tópicos, a forma de redação, as cláusulas administrativas padrão e os textos imutáveis. NUNCA transporte para o documento atual dados concretos de outro processo (objeto, justificativa, quantitativos, valores, fornecedores, fiscais/gestores, dotações orçamentárias, secretarias/unidades, prazos, datas ou números). Esses dados vêm EXCLUSIVAMENTE do processo atual (memorando/ofício inicial, formulário, planilha e anexos).

HIERARQUIA DE FONTES — em caso de divergência, priorize NESTA ordem:
1º) a legislação, os regulamentos, decretos e manuais fornecidos (especialmente a Lei nº 14.133/2021 e regulamentos municipais);
2º) as informações específicas do processo atual (memorando/ofício, formulário, planilha, anexos);
3º) o padrão dos documentos anteriores — somente como referência de estrutura, linguagem e cláusulas.

REGRAS OBRIGATÓRIAS — cumpra TODAS, sem exceção:
1. Redija em português formal, na linguagem técnico-administrativa, jurídica e institucional própria de documentos oficiais da Administração Pública municipal.
2. Utilize EXCLUSIVAMENTE as informações do processo atual. É PROIBIDO inventar, presumir ou copiar de outro processo números, valores, prazos, marcas, normas técnicas, nomes ou fatos não informados.
3. Quando uma informação necessária não constar do memorando, do formulário, da planilha ou dos anexos, insira o marcador [PREENCHER: descrição da informação faltante] no local adequado — nunca preencha com dados fictícios nem reaproveitados de outro processo. Esses marcadores são resolvidos na etapa de revisão humana; o sistema impede a emissão do documento final enquanto existirem.
4. Estruture o documento em Markdown: cláusulas como '## N. TÍTULO EM CAIXA ALTA'; itens e subitens como parágrafos numerados hierarquicamente no próprio texto (1.1., 1.1.1.), no padrão dos documentos oficiais; tabelas em Markdown.
5. Fundamente as cláusulas citando os dispositivos pertinentes da Lei nº 14.133/2021 e das normas/manuais fornecidos — sempre CONECTANDO o dispositivo ao conteúdo tratado; não transforme cláusulas em mera transcrição de artigos de lei.
6. Produza APENAS o texto do documento solicitado — sem comentários, sem explicações introdutórias e sem observações finais fora do documento.
7. NUNCA mencione no documento: o funcionamento interno do sistema, prompts, inteligência artificial, modelos de linguagem, "formulário matriz", bases de treinamento ou instruções recebidas. O documento é um ato administrativo, não um relatório do sistema.
8. Profundidade: siga as metas de blocos indicadas por cláusula. É proibido tanto o texto raso/genérico que serviria a qualquer contratação quanto o enchimento artificial com repetições. Cada afirmação relevante deve decorrer de informação do processo atual ou de norma aplicável.
9. O documento deve estar pronto para revisão humana e assinatura pela autoridade competente."""

# ---------------------------------------------------------------------------
# Instruções específicas por documento
# ---------------------------------------------------------------------------
# DFD, ETP e TR seguem a ESTRUTURA DOS DOCUMENTOS APROVADOS pela
# Administração (perfis.py — extraída dos documentos manuais). O texto de
# abertura dá o enquadramento legal; o esqueleto e as metas de profundidade
# vêm de perfis.estrutura_para_prompt().
_ABERTURAS = {
    "dfd": (
        "Elabore o DOCUMENTO DE FORMALIZAÇÃO DA DEMANDA (DFD), instrumento "
        "inaugural da fase preparatória previsto no art. 12, VII, da Lei nº "
        "14.133/2021, no padrão institucional da Administração demandante."
    ),
    "etp": (
        "Elabore o ESTUDO TÉCNICO PRELIMINAR (ETP), nos termos do art. 18, "
        "caput e §1º, da Lei nº 14.133/2021, utilizando o DFD aprovado "
        "(fornecido abaixo) como fundamento da necessidade, no padrão "
        "institucional da Administração demandante. Na cláusula de ANÁLISE DE "
        "RISCOS, monte a matriz em tabela Markdown com as colunas: Risco | "
        "Probabilidade (Baixa/Média/Alta) | Impacto (Baixo/Médio/Alto) | "
        "Medida de Mitigação | Responsável."
    ),
    "tr": (
        "Elabore o TERMO DE REFERÊNCIA (TR), nos termos do art. 6º, XXIII, e "
        "do art. 40 da Lei nº 14.133/2021, utilizando o ETP aprovado "
        "(fornecido abaixo) como CONTEXTO EXCLUSIVO — todas as definições "
        "técnicas devem decorrer dele —, no padrão institucional da "
        "Administração demandante."
    ),
}

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

def _instrucoes(doc_key: str, dados: dict) -> str:
    """
    Instruções do documento: abertura legal + estrutura/profundidade dos
    documentos APROVADOS (perfis.py). O edital mantém instruções próprias —
    não há documento manual de edital no acervo para servir de referência.
    """
    if doc_key == "edital":
        return INSTRUCOES_EDITAL
    srp = "SRP" in (dados.get("modelo_execucao") or "")
    return _ABERTURAS[doc_key] + "\n\n" + perfis.estrutura_para_prompt(doc_key, srp=srp)


def formatar_dados_formulario(dados: dict) -> str:
    """Converte o Formulário Matriz em um bloco de texto legível para a IA."""
    linhas = []
    for chave, meta in CAMPOS_FORMULARIO.items():
        if chave == "memorando":
            continue  # entra em bloco próprio, mais destacado, em montar_prompt
        if chave == "itens":
            itens, valor_global = planilha.calcular(dados.get("itens") or [])
            if len(itens) > planilha.LIMITE_ITENS_INLINE:
                # Tabela grande: resumo no prompt + injeção da tabela real depois.
                linhas.append(
                    f"- {meta['rotulo']}:\n"
                    + planilha.resumo_para_prompt(itens, valor_global)
                )
            else:
                linhas.append(
                    f"- {meta['rotulo']} (o VALOR GLOBAL é a estimativa da "
                    "contratação; reproduza a planilha COMPLETA, com todas as "
                    "colunas, na estimativa de valor do documento. Mantenha os "
                    "links no formato Markdown exatamente como estão, ex.: "
                    "[link](https://...), sem expandir a URL):\n"
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
    partes = [_instrucoes(doc_key, dados)]
    memorando = (dados.get("memorando") or "").strip()
    if memorando:
        partes.append(
            "\n=== DOCUMENTO INICIAL DA DEMANDA — MEMORANDO/OFÍCIO DO PROCESSO "
            "ATUAL (contexto da origem da demanda) ===\n"
            "Use este documento para compreender a origem da demanda, a unidade "
            "solicitante, a justificativa, a necessidade e a finalidade pública. "
            "É informação DO PROCESSO ATUAL; extraia dele apenas o que estiver "
            "escrito, sem inventar. Onde faltar dado, use [PREENCHER].\n"
            + memorando
        )
    partes.append(
        "\n=== DADOS DO FORMULÁRIO MATRIZ (fonte primária do processo atual) ===\n"
        + formatar_dados_formulario(dados)
    )
    if contexto_anterior:
        nomes = {"dfd": "DFD APROVADO", "etp": "ETP APROVADO", "tr": "TR APROVADO"}
        origem = {"etp": "dfd", "tr": "etp", "edital": "tr"}[doc_key]
        partes.append(
            f"\n=== {nomes[origem]} PELO USUÁRIO (contexto obrigatório) ===\n"
            + contexto_anterior
        )
    return SYSTEM_PROMPT_BASE, "\n".join(partes)
