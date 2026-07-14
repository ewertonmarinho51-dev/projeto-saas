"""
Perfis de cláusula dos documentos — extraídos dos documentos APROVADOS
manualmente pela Administração (Prefeitura Municipal de Paragominas).

Cada perfil descreve a ESTRUTURA e a PROFUNDIDADE esperadas de uma
cláusula: título, finalidade, nº de blocos (parágrafos+itens) mínimo/
médio/máximo, complexidade, obrigatoriedade e necessidade de tabela.
Os perfis alimentam:
  - a montagem do prompt (prompts.py) — a IA recebe o esqueleto e as
    metas de profundidade;
  - a validação (validacao.py) — documentos rasos demais são apontados.

Referências medidas nos documentos manuais:
  DFD  ~4.800 palavras, 9 cláusulas, ~7 blocos/cláusula (1–13);
  ETP  ~12.500 palavras, 18 cláusulas, ~14 blocos/cláusula (1–45);
  TR   ~11.400 palavras, 17 cláusulas, ~15 blocos/cláusula (1–50).
A profundidade final deve considerar o objeto e a complexidade da
contratação — as metas orientam, não obrigam texto artificial.
"""

# complexidade: baixa | media | alta | muito_alta
# obrigatoria: True (sempre) | False (condicional ao objeto)
PERFIS: dict[str, dict] = {
    "dfd": {
        "titulo": "DOCUMENTO DE FORMALIZAÇÃO DA DEMANDA (DFD)",
        "palavras_alvo": (2500, 4800),
        "clausulas": [
            {"n": 1, "titulo": "INFORMAÇÕES GERAIS",
             "finalidade": "Setor requisitante, responsável pela formalização "
                           "(nome/matrícula), data prevista para conclusão e prioridade.",
             "blocos": (3, 5, 8), "complexidade": "baixa", "obrigatoria": True,
             "tabela": False, "fundamentacao": False},
            {"n": 2, "titulo": "JUSTIFICATIVA",
             "finalidade": "Motivos da contratação, problemas administrativos a "
                           "resolver, benefícios e economicidade, com síntese conclusiva.",
             "blocos": (5, 8, 13), "complexidade": "alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 3, "titulo": "NECESSIDADE OU OPORTUNIDADE DE MELHORIA IDENTIFICADA",
             "finalidade": "Descrição da necessidade sob a ótica do interesse público.",
             "blocos": (4, 7, 12), "complexidade": "alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 4, "titulo": "SOLUÇÃO PROPOSTA PELO DEMANDANTE",
             "finalidade": "Solução pretendida e alternativas consideradas pelo demandante.",
             "blocos": (4, 7, 12), "complexidade": "alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": False},
            {"n": 5, "titulo": "DESCRIÇÃO DA SOLUÇÃO E ESTIMATIVA DE QUANTIDADES",
             "finalidade": "Itens/serviços com quantidades estimadas e memória "
                           "das quantidades (planilha).",
             "blocos": (3, 6, 10), "complexidade": "media", "obrigatoria": True,
             "tabela": True, "fundamentacao": False},
            {"n": 6, "titulo": "DIMENSIONAMENTO/DESCRIÇÃO PARA A PRESTAÇÃO",
             "finalidade": "Como a prestação/fornecimento será dimensionada e executada.",
             "blocos": (3, 6, 10), "complexidade": "media", "obrigatoria": True,
             "tabela": False, "fundamentacao": False},
            {"n": 7, "titulo": "ESTIMATIVA DE VALOR DA CONTRATAÇÃO",
             "finalidade": "Valor estimado (planilha orçamentária) com ressalva da "
                           "pesquisa de preços definitiva (art. 23).",
             "blocos": (2, 4, 7), "complexidade": "media", "obrigatoria": True,
             "tabela": True, "fundamentacao": True},
            {"n": 8, "titulo": "PERÍODO",
             "finalidade": "Período/prazo pretendido para a contratação e vigência.",
             "blocos": (1, 2, 5), "complexidade": "baixa", "obrigatoria": True,
             "tabela": False, "fundamentacao": False,
             # correção automática: só PARÂMETROS (prazos, datas, valores)
             # podem mudar — a prosa da cláusula é preservada
             "fixa": "PARAMETERIZED"},
            {"n": 9, "titulo": "EQUIPE DE PLANEJAMENTO",
             "finalidade": "Composição da equipe, com local para data e assinaturas.",
             "blocos": (1, 3, 5), "complexidade": "baixa", "obrigatoria": True,
             "tabela": False, "fundamentacao": False,
             # correção automática: quem assina não é decisão de máquina
             "fixa": "LOCKED"},
        ],
    },
    "etp": {
        "titulo": "ESTUDO TÉCNICO PRELIMINAR (ETP)",
        "palavras_alvo": (6000, 12500),
        "clausulas": [
            {"n": 1, "titulo": "INFORMAÇÕES BÁSICAS DO ETP",
             "finalidade": "Identificação do processo, órgão e demanda de origem.",
             "blocos": (2, 4, 6), "complexidade": "baixa", "obrigatoria": True,
             "tabela": False, "fundamentacao": False},
            {"n": 2, "titulo": "DESCRIÇÃO DA NECESSIDADE DA CONTRATAÇÃO",
             "finalidade": "Necessidade sob a perspectiva do interesse público "
                           "(art. 18, §1º, I).",
             "blocos": (6, 12, 20), "complexidade": "alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 3, "titulo": "PREVISÃO NO PLANO ANUAL DE CONTRATAÇÕES",
             "finalidade": "Vinculação ao PCA (art. 18, §1º, II).",
             "blocos": (1, 3, 5), "complexidade": "baixa", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 4, "titulo": "DESCRIÇÃO DOS REQUISITOS DA CONTRATAÇÃO",
             "finalidade": "Requisitos técnicos, normativos, de garantia, "
                           "sustentabilidade e níveis de serviço (art. 18, §1º, III).",
             "blocos": (15, 25, 45), "complexidade": "muito_alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 5, "titulo": "LEVANTAMENTO DE SOLUÇÕES",
             "finalidade": "Alternativas de mercado analisadas, com vantagens e "
                           "desvantagens de cada uma (art. 18, §1º, V).",
             "blocos": (10, 18, 35), "complexidade": "muito_alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 6, "titulo": "DESCRIÇÃO DA SOLUÇÃO",
             "finalidade": "Solução escolhida como um todo, ciclo de vida, "
                           "manutenção e assistência (art. 18, §1º, VII).",
             "blocos": (10, 18, 35), "complexidade": "muito_alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 7, "titulo": "ESTIMATIVA DO QUANTITATIVO",
             "finalidade": "Quantidades com memórias de cálculo (art. 18, §1º, IV) — planilha.",
             "blocos": (3, 6, 12), "complexidade": "media", "obrigatoria": True,
             "tabela": True, "fundamentacao": False},
            {"n": 8, "titulo": "ESTIMATIVA E FUNDAMENTAÇÃO DO VALOR PARA A CONTRATAÇÃO",
             "finalidade": "Valor estimado e método da estimativa (art. 18, §1º, VI).",
             "blocos": (3, 6, 12), "complexidade": "media", "obrigatoria": True,
             "tabela": True, "fundamentacao": True},
            {"n": 9, "titulo": "ANÁLISE DE RISCOS",
             "finalidade": "Riscos do planejamento/execução com matriz "
                           "Risco × Probabilidade × Impacto × Mitigação × Responsável.",
             "blocos": (6, 12, 20), "complexidade": "alta", "obrigatoria": True,
             "tabela": True, "fundamentacao": False},
            {"n": 10, "titulo": "JUSTIFICATIVA PARA O PARCELAMENTO",
             "finalidade": "Divisibilidade do objeto (Súmula 247/TCU; art. 40, V, 'b').",
             "blocos": (4, 8, 15), "complexidade": "alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 11, "titulo": "CONTRATAÇÕES CORRELATAS E/OU INTERDEPENDENTES",
             "finalidade": "Contratações relacionadas (art. 18, §1º, XI).",
             "blocos": (1, 3, 6), "complexidade": "baixa", "obrigatoria": True,
             "tabela": False, "fundamentacao": False},
            {"n": 12, "titulo": "RESULTADOS PRETENDIDOS",
             "finalidade": "Benefícios e resultados esperados (art. 18, §1º, IX).",
             "blocos": (3, 6, 12), "complexidade": "media", "obrigatoria": True,
             "tabela": False, "fundamentacao": False},
            {"n": 13, "titulo": "PROVIDÊNCIAS A SEREM ADOTADAS PELA ADMINISTRAÇÃO",
             "finalidade": "Providências prévias ao contrato (art. 18, §1º, X).",
             "blocos": (2, 5, 10), "complexidade": "media", "obrigatoria": True,
             "tabela": False, "fundamentacao": False},
            {"n": 14, "titulo": "POSSÍVEIS IMPACTOS AMBIENTAIS",
             "finalidade": "Impactos ambientais e medidas mitigadoras (art. 18, §1º, XII).",
             "blocos": (2, 5, 10), "complexidade": "media", "obrigatoria": True,
             "tabela": False, "fundamentacao": False},
            {"n": 15, "titulo": "POSICIONAMENTO CONCLUSIVO SOBRE A VIABILIDADE E "
                                "RAZOABILIDADE DA CONTRATAÇÃO",
             "finalidade": "Declaração de viabilidade (art. 18, §1º, XIII).",
             "blocos": (3, 6, 12), "complexidade": "alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 16, "titulo": "EQUIPE DE PLANEJAMENTO",
             "finalidade": "Composição e assinaturas da equipe de planejamento.",
             "blocos": (1, 3, 5), "complexidade": "baixa", "obrigatoria": True,
             "tabela": False, "fundamentacao": False,
             # correção automática: quem assina não é decisão de máquina
             "fixa": "LOCKED"},
            {"n": 17, "titulo": "POSSIBILIDADE DE RENOVAÇÃO DO QUANTITATIVO REGISTRADO",
             "finalidade": "Renovação de quantitativos — aplicável quando SRP.",
             "blocos": (1, 3, 6), "complexidade": "media", "obrigatoria": False,
             "tabela": False, "fundamentacao": True},
            {"n": 18, "titulo": "CONSIDERAÇÕES FINAIS",
             "finalidade": "Fecho, encaminhamento e local para data/assinatura.",
             "blocos": (1, 3, 5), "complexidade": "baixa", "obrigatoria": True,
             "tabela": False, "fundamentacao": False},
        ],
    },
    "tr": {
        "titulo": "TERMO DE REFERÊNCIA (TR)",
        "palavras_alvo": (6000, 11500),
        "clausulas": [
            {"n": 1, "titulo": "DO OBJETO",
             "finalidade": "Definição precisa do objeto, natureza, quantitativos, "
                           "prazo e prorrogação (art. 6º, XXIII, 'a').",
             "blocos": (4, 8, 14), "complexidade": "alta", "obrigatoria": True,
             "tabela": True, "fundamentacao": True},
            {"n": 2, "titulo": "DA FUNDAMENTAÇÃO DA CONTRATAÇÃO",
             "finalidade": "Referência expressa ao DFD e ao ETP (art. 6º, XXIII, 'b').",
             "blocos": (3, 6, 10), "complexidade": "media", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 3, "titulo": "DESCRIÇÃO DA SOLUÇÃO COMO UM TODO CONSIDERANDO O "
                               "CICLO DE VIDA DO OBJETO",
             "finalidade": "Solução completa, ciclo de vida, garantia e assistência "
                           "(art. 6º, XXIII, 'c').",
             "blocos": (8, 15, 25), "complexidade": "alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": False},
            {"n": 4, "titulo": "DESCRIÇÃO DOS REQUISITOS DA CONTRATAÇÃO",
             "finalidade": "Especificações técnicas detalhadas, certificações e "
                           "normas (art. 6º, XXIII, 'd').",
             "blocos": (18, 30, 50), "complexidade": "muito_alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 5, "titulo": "EXECUÇÃO DO OBJETO",
             "finalidade": "Prazos, local, condições de entrega/execução e modelo de "
                           "execução (art. 6º, XXIII, 'e').",
             "blocos": (12, 20, 40), "complexidade": "muito_alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": False},
            {"n": 6, "titulo": "DA FORMALIZAÇÃO DA CONTRATAÇÃO",
             "finalidade": "Instrumento contratual/ata, condições de assinatura e vigência.",
             "blocos": (4, 8, 15), "complexidade": "media", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 7, "titulo": "DO CRITÉRIO DE ACEITAÇÃO DO OBJETO",
             "finalidade": "Recebimento provisório e definitivo, critérios e prazos "
                           "(art. 140).",
             "blocos": (8, 14, 25), "complexidade": "muito_alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 8, "titulo": "DAS OBRIGAÇÕES DA CONTRATANTE",
             "finalidade": "Obrigações da Administração.",
             "blocos": (5, 9, 15), "complexidade": "alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": False},
            {"n": 9, "titulo": "DAS OBRIGAÇÕES DA CONTRATADA",
             "finalidade": "Obrigações do particular, inclusive trabalhistas e fiscais.",
             "blocos": (10, 18, 35), "complexidade": "muito_alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": False},
            {"n": 10, "titulo": "DO PAGAMENTO E CRITÉRIOS DE RECEBIMENTO",
             "finalidade": "Critérios de medição e pagamento (art. 6º, XXIII, 'g').",
             "blocos": (5, 10, 18), "complexidade": "alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 11, "titulo": "LIQUIDAÇÃO",
             "finalidade": "Procedimento e prazos de liquidação da despesa.",
             "blocos": (2, 5, 10), "complexidade": "media", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 12, "titulo": "PRAZO DE PAGAMENTO",
             "finalidade": "Prazos de pagamento após a liquidação.",
             "blocos": (2, 4, 8), "complexidade": "media", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 13, "titulo": "FORMA DE PAGAMENTO",
             "finalidade": "Forma/meio de pagamento e documentos exigidos.",
             "blocos": (2, 4, 8), "complexidade": "media", "obrigatoria": True,
             "tabela": False, "fundamentacao": False},
            {"n": 14, "titulo": "DA GESTÃO, EXECUÇÃO E FISCALIZAÇÃO DO CONTRATO",
             "finalidade": "Gestor e fiscal do contrato, rotinas de fiscalização e "
                           "registro de ocorrências (arts. 117 e 140).",
             "blocos": (8, 15, 30), "complexidade": "muito_alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 15, "titulo": "DAS SANÇÕES ADMINISTRATIVAS",
             "finalidade": "Infrações e sanções (arts. 155 a 163), com gradação.",
             "blocos": (8, 14, 25), "complexidade": "muito_alta", "obrigatoria": True,
             "tabela": False, "fundamentacao": True},
            {"n": 16, "titulo": "ESTIMATIVA DO VALOR DA CONTRATAÇÃO",
             "finalidade": "Valor estimado (planilha) e adequação orçamentária "
                           "(art. 6º, XXIII, 'i' e 'j').",
             "blocos": (3, 6, 12), "complexidade": "media", "obrigatoria": True,
             "tabela": True, "fundamentacao": True},
            {"n": 17, "titulo": "POSSIBILIDADE DE RENOVAÇÃO DO QUANTITATIVO REGISTRADO",
             "finalidade": "Renovação de quantitativos — aplicável quando SRP.",
             "blocos": (1, 3, 6), "complexidade": "media", "obrigatoria": False,
             "tabela": False, "fundamentacao": True},
        ],
    },
}

_COMPLEXIDADE_ROTULO = {
    "baixa": "baixa", "media": "média", "alta": "alta", "muito_alta": "muito alta",
}


def perfil(doc_key: str) -> dict | None:
    """Perfil do documento ('dfd' | 'etp' | 'tr') ou None (ex.: edital)."""
    return PERFIS.get(doc_key)


def clausulas_obrigatorias(doc_key: str) -> list[dict]:
    p = perfil(doc_key)
    return [c for c in p["clausulas"] if c["obrigatoria"]] if p else []


def clausulas_fixas(doc_key: str) -> dict[int, str]:
    """
    Governança da correção automática: nº da cláusula → 'LOCKED'
    (a IA nunca altera) ou 'PARAMETERIZED' (só parâmetros autorizados —
    números, valores, datas e percentuais — podem mudar).
    """
    p = perfil(doc_key)
    if not p:
        return {}
    return {c["n"]: c["fixa"] for c in p["clausulas"] if c.get("fixa")}


def palavras_minimas(doc_key: str) -> int:
    """Piso de palavras do documento (abaixo disso a validação alerta)."""
    p = perfil(doc_key)
    if not p:
        return 0
    # metade do alvo inferior: tolera contratações simples sem aceitar esqueleto
    return p["palavras_alvo"][0] // 2


def estrutura_para_prompt(doc_key: str, srp: bool = False) -> str:
    """
    Esqueleto de cláusulas + metas de profundidade, no formato usado pelos
    documentos aprovados da Administração. Injetado nas instruções da IA.
    """
    p = perfil(doc_key)
    if not p:
        return ""
    linhas = [
        f"ESTRUTURA OBRIGATÓRIA DO DOCUMENTO — siga EXATAMENTE esta sequência "
        f"de cláusulas, com títulos numerados em caixa alta (ex.: '## 1. TÍTULO') "
        f"e itens/subitens numerados hierarquicamente (1.1., 1.1.1.):",
    ]
    for c in p["clausulas"]:
        if not c["obrigatoria"] and not srp:
            continue
        minimo, medio, maximo = c["blocos"]
        extras = []
        if c["tabela"]:
            extras.append("DEVE conter tabela")
        if c["fundamentacao"]:
            extras.append("DEVE citar a base legal pertinente")
        if not c["obrigatoria"]:
            extras.append("aplicável por ser SRP")
        sufixo = f" [{'; '.join(extras)}]" if extras else ""
        linhas.append(
            f"{c['n']}. {c['titulo']} — {c['finalidade']} "
            f"Profundidade (complexidade {_COMPLEXIDADE_ROTULO[c['complexidade']]}): "
            f"entre {minimo} e {maximo} blocos (parágrafos/itens), "
            f"referência típica {medio}.{sufixo}"
        )
    faixa = p["palavras_alvo"]
    linhas.append(
        f"\nEXTENSÃO TOTAL de referência: {faixa[0]} a {faixa[1]} palavras, "
        "modulada pela complexidade real do objeto — contratações simples podem "
        "ficar próximas do piso, NUNCA abaixo da metade dele. É PROIBIDO inflar "
        "o texto com repetições ou generalidades para atingir a meta: cada bloco "
        "deve trazer conteúdo específico do processo atual ou fundamento normativo "
        "aplicável."
    )
    return "\n".join(linhas)
