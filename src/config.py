"""
Configurações centrais da aplicação.

Define as etapas do wizard, os metadados dos 4 documentos gerados e os
campos do Formulário Matriz — incluindo os textos de ajuda (tooltips)
que explicam o que a Lei nº 14.133/2021 espera de cada informação.
"""

APP_TITULO = "GovDocs Wizard"
APP_SUBTITULO = "Documentos da fase preparatória de licitações · Lei nº 14.133/2021"

# Motor principal: OpenAI (pode ser sobrescrito em secrets.toml ou env OPENAI_MODEL)
OPENAI_MODEL_PADRAO = "gpt-5-mini"
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"  # com dimensions=768

# Modelos alternativos tentados automaticamente se o configurado não existir
# na conta (erro "model_not_found"/404). Amplamente disponíveis.
OPENAI_MODELOS_FALLBACK = ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"]

# Motor de fallback: Gemini (sobrescreva com GEMINI_MODEL)
GEMINI_MODEL_PADRAO = "gemini-2.5-flash"
GEMINI_MODELOS_FALLBACK = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]

# Parâmetros de robustez das chamadas à API
API_TIMEOUT_SEGUNDOS = 180  # documentos longos + planilhas grandes
API_TENTATIVAS = 3          # nº de tentativas antes de desistir
API_BACKOFF_BASE = 2        # espera 2s, 4s, 8s... entre tentativas

# Base de Conhecimento (RAG)
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSOES = 768   # deve casar com vector(768) no banco
RAG_CHUNK_TAMANHO = 1500    # ~caracteres por trecho indexado
RAG_CHUNK_SOBREPOSICAO = 200
RAG_TOP_K = 6               # trechos recuperados por geração

# ---------------------------------------------------------------------------
# Etapas do wizard
# ---------------------------------------------------------------------------
# etapa 0 = Formulário Matriz | 1..4 = documentos | 5 = tela de sucesso
ETAPAS = [
    "1. Dados da Demanda",
    "2. DFD",
    "3. ETP",
    "4. TR",
    "5. Minuta de Edital",
    "6. Concluído",
]

# Ordem sequencial dos documentos (regra de negócio: cada documento usa o
# anterior aprovado como contexto)
SEQUENCIA_DOCUMENTOS = ["dfd", "etp", "tr", "edital"]

DOCUMENTOS = {
    "dfd": {
        "etapa": 1,
        "sigla": "DFD",
        "titulo": "Documento de Formalização da Demanda",
        "base_legal": "art. 12, VII, da Lei nº 14.133/2021",
        "descricao": (
            "Formaliza a necessidade da contratação, identificando o "
            "requisitante, o objeto, a justificativa e o alinhamento ao "
            "Plano de Contratações Anual (PCA)."
        ),
        "usa_contexto_de": None,  # gerado apenas a partir do formulário
    },
    "etp": {
        "etapa": 2,
        "sigla": "ETP",
        "titulo": "Estudo Técnico Preliminar",
        "base_legal": "art. 18, §1º, da Lei nº 14.133/2021",
        "descricao": (
            "Evidencia o problema a ser resolvido e a melhor solução, "
            "com levantamento de mercado, justificativa de parcelamento "
            "e matriz de riscos."
        ),
        "usa_contexto_de": "dfd",
    },
    "tr": {
        "etapa": 3,
        "sigla": "TR",
        "titulo": "Termo de Referência",
        "base_legal": "art. 6º, XXIII, e art. 40 da Lei nº 14.133/2021",
        "descricao": (
            "Detalha o objeto com especificações técnicas, modelo de "
            "execução, gestão e fiscalização contratual, critérios de "
            "medição, recebimento e pagamento."
        ),
        "usa_contexto_de": "etp",
    },
    "edital": {
        "etapa": 4,
        "sigla": "Edital",
        "titulo": "Minuta de Edital / Ata de Registro de Preços",
        "base_legal": "art. 25 da Lei nº 14.133/2021",
        "descricao": (
            "Minuta com as cláusulas do certame — condições de "
            "participação, julgamento, habilitação e sanções — e, quando "
            "SRP, a minuta da Ata de Registro de Preços."
        ),
        "usa_contexto_de": "tr",
    },
}

# ---------------------------------------------------------------------------
# Formulário Matriz — Passo 1
# ---------------------------------------------------------------------------
# Cada campo tem um "help" curto explicando o que a Lei 14.133/2021 espera.
# O Streamlit exibe esse texto como tooltip (ícone ? ao lado do rótulo).
CAMPOS_FORMULARIO = {
    "memorando": {
        "rotulo": "Documento inicial da demanda (memorando / ofício)",
        "tipo": "area",
        "obrigatorio": False,
        "placeholder": (
            "Cole aqui o texto do memorando, ofício ou solicitação que "
            "originou a demanda (ou envie um arquivo PDF/DOCX no campo acima)."
        ),
        "help": (
            "Documento que deflagra o processo (memorando, ofício, "
            "solicitação formal). Contextualiza a ORIGEM da demanda: unidade "
            "solicitante, justificativa, necessidade administrativa e "
            "finalidade pública. É usado como base de contextualização do DFD, "
            "ETP, TR e demais peças — sempre junto do formulário. Não substitui "
            "os campos: dados concretos vêm do formulário/planilha."
        ),
    },
    "orgao": {
        "rotulo": "Órgão / Entidade Requisitante",
        "tipo": "texto",
        "obrigatorio": True,
        "placeholder": "Ex.: Prefeitura Municipal de Exemplo, Secretaria de Saúde",
        "help": (
            "Identifique o órgão e a unidade requisitante. O DFD deve "
            "indicar claramente quem demanda a contratação (art. 12, VII)."
        ),
    },
    "responsavel": {
        "rotulo": "Responsável pela Demanda (nome e cargo)",
        "tipo": "texto",
        "obrigatorio": False,
        "placeholder": "Ex.: Maria Silva, Diretora de Compras",
        "help": (
            "Agente público que formaliza a demanda e responde pelas "
            "informações prestadas no DFD."
        ),
    },
    "objeto": {
        "rotulo": "Objeto Detalhado da Contratação",
        "tipo": "area",
        "obrigatorio": True,
        "placeholder": (
            "Ex.: Aquisição de 40 computadores desktop tipo corporativo, "
            "com monitor de 24\", para as unidades administrativas..."
        ),
        "help": (
            "Descreva o que será contratado com precisão, incluindo "
            "quantidades e unidades de medida. A definição do objeto deve "
            "ser clara e suficiente (art. 6º, XXIII, 'a')."
        ),
    },
    "justificativa": {
        "rotulo": "Justificativa e Problema a Ser Resolvido",
        "tipo": "area",
        "obrigatorio": True,
        "placeholder": (
            "Ex.: O parque tecnológico atual tem mais de 8 anos, gerando "
            "falhas recorrentes e indisponibilidade dos serviços..."
        ),
        "help": (
            "Demonstre a necessidade da contratação e o interesse público "
            "envolvido. É a base da 'descrição da necessidade' exigida no "
            "DFD e no ETP (art. 18, §1º, I)."
        ),
    },
    "alinhamento": {
        "rotulo": "Alinhamento Estratégico (PCA / Planejamento)",
        "tipo": "area",
        "obrigatorio": False,
        "placeholder": (
            "Ex.: Demanda prevista no item 12 do PCA 2026 e alinhada ao "
            "objetivo 3 do Planejamento Estratégico Institucional..."
        ),
        "help": (
            "Indique a previsão no Plano de Contratações Anual e a conexão "
            "com o planejamento do órgão (art. 12, VII, e art. 18, §1º, II)."
        ),
    },
    "requisitos": {
        "rotulo": "Requisitos Técnicos e Normativos",
        "tipo": "area",
        "obrigatorio": False,
        "placeholder": (
            "Ex.: Certificação INMETRO; garantia mínima de 36 meses; "
            "conformidade com a norma ABNT NBR XXXX; assistência técnica "
            "no estado..."
        ),
        "help": (
            "Liste certificações, normas técnicas, garantias, níveis de "
            "serviço e demais exigências da contratação (art. 18, §1º, III, "
            "e art. 40, §1º, I)."
        ),
    },
    "itens": {
        "rotulo": "Planilha Orçamentária (itens da contratação)",
        "tipo": "planilha",
        "obrigatorio": True,
        "placeholder": "",
        "help": (
            "Relacione os itens: código, descrição, unidade, quantidade e "
            "valor unitário. O valor total de cada item e o VALOR GLOBAL "
            "(soma = estimativa da contratação) são calculados "
            "automaticamente. Na fase interna a estimativa orienta a "
            "modalidade e a reserva orçamentária (art. 23); a definitiva "
            "exigirá pesquisa de preços."
        ),
    },
    "modelo_execucao": {
        "rotulo": "Modelo de Execução / Fornecimento",
        "tipo": "selecao",
        "obrigatorio": True,
        "opcoes": [
            "Sistema de Registro de Preços (SRP)",
            "Entrega única (fornecimento integral)",
            "Entrega parcelada",
            "Serviço de execução continuada",
            "Serviço por escopo (execução única)",
            "Obra / serviço de engenharia",
        ],
        "help": (
            "Como o objeto será executado ou fornecido. A escolha do SRP "
            "exige justificativa própria (art. 82) e altera a minuta final "
            "(Edital + Ata de Registro de Preços)."
        ),
    },
    "prazo": {
        "rotulo": "Prazo / Data Pretendida para a Contratação",
        "tipo": "texto",
        "obrigatorio": False,
        "placeholder": "Ex.: Contratação necessária até março/2027",
        "help": (
            "O DFD deve indicar a previsão de data em que a contratação "
            "deve ser concluída e o grau de prioridade da demanda."
        ),
    },
    "riscos": {
        "rotulo": "Riscos Identificados",
        "tipo": "area",
        "obrigatorio": False,
        "placeholder": (
            "Ex.: Risco de atraso na entrega por escassez de componentes; "
            "risco de sobrepreço; risco de descontinuidade do fabricante..."
        ),
        "help": (
            "Riscos que possam comprometer a contratação ou a execução "
            "contratual. Alimentam a matriz de riscos do ETP e a análise "
            "de riscos exigida pelo art. 18, caput e §1º, X."
        ),
    },
}
