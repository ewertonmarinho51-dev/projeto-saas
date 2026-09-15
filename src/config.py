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

# ---------------------------------------------------------------------------
# Terceiro motor: OpenRouter (sobrescreva com OPENROUTER_MODEL)
#
# Entra DEPOIS da OpenAI e do Gemini, e a ordem é deliberada: os modelos
# gratuitos daqui são mais fracos que `gpt-5-mini`/`gemini-2.5-flash` para
# texto jurídico longo, e vêm com teto de requisições. Quem já tem chave
# paga não pode ser rebaixado em silêncio por ter configurado OpenRouter
# também.
#
# A API é compatível com a da OpenAI — muda a base e a chave —, então
# este motor reusa `_openai_uma_chamada` inteiro: não há segundo cliente
# HTTP, segundo laço de retentativa nem segunda tradução de erro.
#
# ESCOLHA DOS MODELOS (lida na documentação do provedor em 14/09/2026):
#
#   * `nemotron-3-ultra` — 550B MoE (55B ativos), contexto de 1M e até
#     65.536 tokens de saída. O maior da lista gratuita, e o teto de saída
#     importa porque a geração de documento pede 16.384;
#   * `nemotron-3-super` — 120B A12B, a irmã menor, para quando a Ultra
#     estiver saturada;
#   * `gemma-4-31b` — densa, 262k de contexto, 32.768 de saída;
#   * `gemma-4-26b-a4b` — MoE com apenas 3,8B ativos por token. A mais
#     fraca das quatro; fica por último, como rede.
#
# FICARAM DE FORA, e o porquê vale registrado: `ling-3.0-flash-fin` e
# `-sante` são variantes de DOMÍNIO (finanças e saúde), `-vl` é visão, e o
# restante da lista gratuita é embedding, reranker, TTS ou pequeno demais
# para um Termo de Referência.
#
# O sufixo `:free` é explícito de propósito. O mesmo identificador sem ele
# é o endpoint PAGO do mesmo modelo — deixar implícito transformaria um
# erro de digitação em fatura.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL_PADRAO = "nvidia/nemotron-3-ultra-550b-a55b:free"
OPENROUTER_MODELOS_FALLBACK = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
]

# Parâmetros de robustez das chamadas à API
API_TIMEOUT_SEGUNDOS = 180  # documentos longos + planilhas grandes
API_TENTATIVAS = 3          # nº de tentativas antes de desistir
API_BACKOFF_BASE = 2        # espera 2s, 4s, 8s... entre tentativas

# ---------------------------------------------------------------------------
# Base de Conhecimento (RAG) — índice vetorial V2
#
# Decisão registrada em 11/08/2026 (auditoria de proveniência): o índice
# tem UM provedor, UM modelo, UMA dimensão e UMA versão. A versão do
# índice muda SEMPRE que qualquer um dos três primeiros mudar — e trocar
# a versão exige reindexar a base inteira, porque vetores de modelos
# diferentes não são comparáveis entre si.
#
# A geração de TEXTO mantém o fallback OpenAI → Gemini; os EMBEDDINGS
# não têm fallback algum (ver rag._gerar_embeddings).
# ---------------------------------------------------------------------------
EMBEDDING_V2_PROVEDOR = "openai"
EMBEDDING_V2_MODELO = "text-embedding-3-small"
EMBEDDING_V2_DIMENSOES = 768
EMBEDDING_V2_VERSAO = "v2"

# Compatibilidade com o índice legado (coluna `embedding`), cuja origem
# não pôde ser comprovada documentalmente — mantido apenas para leitura
# até o corte para o V2.
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
        "titulo": "Minuta de Edital",
        "base_legal": "art. 25 da Lei nº 14.133/2021",
        "descricao": (
            "Minuta com as cláusulas do certame — condições de "
            "participação, julgamento, habilitação, recursos e sanções."
        ),
        "usa_contexto_de": "tr",
    },
    # Instrumento PRÓPRIO, não um capítulo do edital: a Ata é montada
    # deterministicamente na mesma etapa, quando o processo adota o
    # Sistema de Registro de Preços.
    "arp": {
        "etapa": 4,
        "sigla": "ARP",
        "titulo": "Minuta da Ata de Registro de Preços",
        "base_legal": "arts. 82 a 86 da Lei nº 14.133/2021",
        "descricao": (
            "Minuta da Ata — objeto e preços registrados, vigência "
            "(art. 84), gerenciamento, cadastro de reserva, adesão "
            "(art. 86) e cancelamento do registro."
        ),
        "usa_contexto_de": "tr",
    },
}

# Ordem de EXPORTAÇÃO do dossiê. Difere de SEQUENCIA_DOCUMENTOS porque a
# ARP não é etapa do wizard: é emitida junto do edital, como instrumento
# separado, quando há Sistema de Registro de Preços.
DOCUMENTOS_EXPORTAVEIS = SEQUENCIA_DOCUMENTOS + ["arp"]

# Instrumentos emitidos JUNTO de um documento do wizard, e não como etapa
# própria. Quem invalida o documento-âncora invalida o instrumento: a Ata
# nasce do edital e da modelagem declarada no formulário, então nenhuma
# Ata pode sobreviver à regeneração daquilo que a fundamenta.
INSTRUMENTOS_DERIVADOS = {"edital": ("arp",)}


def adota_srp(dados: dict | None) -> bool:
    """
    O processo adota Sistema de Registro de Preços?

    Critério ÚNICO e explícito: o modelo de execução informado no
    Formulário Matriz. Não se deduz SRP de objeto, quantidade ou
    parcelamento — adotar SRP é decisão do estudo, não inferência.

    Vive aqui, e não em `state`, porque a camada de exportação precisa
    do mesmo critério sem depender do estado da sessão do Streamlit.
    """
    return "registro de preços" in ((dados or {}).get("modelo_execucao")
                                    or "").lower()


def exportaveis_do_processo(dados: dict | None,
                            documentos: dict | None) -> list[str]:
    """
    Chaves realmente exportáveis, na ordem do dossiê.

    Segunda linha de defesa contra Ata obsoleta: um processo que NÃO
    adota SRP nunca exporta ARP, ainda que uma chave 'arp' residual de
    uma modelagem anterior tenha sobrado em `documentos`. A limpeza de
    estado é a primeira linha; esta função é a que decide o arquivo.
    """
    documentos = documentos or {}
    ordem = (DOCUMENTOS_EXPORTAVEIS if adota_srp(dados)
             else SEQUENCIA_DOCUMENTOS)
    return [k for k in ordem if k in documentos]

# ---------------------------------------------------------------------------
# Formulário Matriz — Passo 1
# ---------------------------------------------------------------------------
# Cada campo tem um "help" curto explicando o que a Lei 14.133/2021 espera.
# O Streamlit exibe esse texto como tooltip (ícone ? ao lado do rótulo).
CAMPOS_FORMULARIO = {
    "memorando": {
        "rotulo_tela": "Documento que pediu a compra",
        "ajuda_simples": (
            "Cole aqui o memorando ou ofício que pediu a compra. Se "
            "preferir, envie o arquivo no campo acima."
        ),
        "exemplo": (
            "Memorando nº 45/2026 — SEMED. A Secretaria de Educação "
            "solicita a aquisição de material de expediente para as 12 "
            "escolas da rede, cujo estoque se esgota em março."
        ),
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
        "rotulo_tela": "Quem está pedindo",
        "ajuda_simples": "A secretaria ou departamento que precisa da compra.",
        "exemplo": "Prefeitura Municipal de Bom Jardim — Secretaria de Educação",
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
        "rotulo_tela": "Quem assina o pedido",
        "ajuda_simples": "Nome e cargo de quem responde pelas informações.",
        "exemplo": "Maria Silva — Diretora de Compras",
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
        "rotulo_tela": "O que vai ser comprado ou contratado",
        "ajuda_simples": (
            "Descreva com quantidade e unidade de medida. Quanto mais "
            "concreto, melhor o documento sai."
        ),
        "exemplo": (
            "Aquisição de 5.000 resmas de papel A4 75g, 600 canetas "
            "esferográficas azuis e 300 pastas suspensas, para as escolas "
            "da rede municipal."
        ),
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
        "rotulo_tela": "Por que isso é necessário",
        "ajuda_simples": (
            "Explique o problema que a compra resolve e o que acontece se "
            "ela não for feita."
        ),
        "exemplo": (
            "O estoque atual de material de expediente atende até março de "
            "2027. Sem a reposição, as 12 escolas ficam sem material para "
            "matrícula, diários de classe e comunicados às famílias."
        ),
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
        "rotulo_tela": "Já estava no planejamento do ano?",
        "ajuda_simples": (
            "Se a compra consta do Plano de Contratações Anual, informe o "
            "item. Se não consta, explique por quê."
        ),
        "exemplo": (
            "Item 23 do Plano de Contratações Anual de 2027, aprovado pelo "
            "Decreto nº 12/2026."
        ),
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
        "rotulo_tela": "Exigências que o fornecedor precisa cumprir",
        "ajuda_simples": (
            "Normas, certificações, garantia, prazo de troca — o que for "
            "obrigatório para o produto ou serviço servir."
        ),
        "exemplo": (
            "Papel A4 com certificação FSC. Canetas com tinta à base de "
            "água. Garantia de troca de itens com defeito em até 30 dias."
        ),
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
        "rotulo_tela": "Lista de itens e preços",
        "ajuda_simples": (
            "Um item por linha, com quantidade e valor unitário. Dá para "
            "importar de uma planilha."
        ),
        "exemplo": "Papel A4 75g — resma — 5.000 un — R$ 24,90",
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
        "rotulo_tela": "Como a entrega vai acontecer",
        "ajuda_simples": (
            "Entrega única, entregas parceladas ao longo do ano, ou "
            "registro de preços (quando ainda não se sabe a quantidade "
            "exata)."
        ),
        "exemplo": "Entrega parcelada, conforme a necessidade de cada escola.",
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
        "rotulo_tela": "Para quando você precisa",
        "ajuda_simples": "A data em que a compra precisa estar concluída.",
        "exemplo": "Até março de 2027, antes do início do ano letivo.",
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
        "rotulo_tela": "O que pode dar errado",
        "ajuda_simples": "Problemas que podem atrapalhar a compra ou a entrega.",
        "exemplo": (
            "Atraso na entrega no início do ano letivo. Variação de preço "
            "do papel. Fornecedor único na região."
        ),
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
