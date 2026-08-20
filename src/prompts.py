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
# Mapa canônico da Lei nº 14.133/2021 — DADO, não texto solto.
#
# É a única lista de dispositivos que o sistema considera validada. Serve
# a dois consumidores, que assim não podem divergir:
#   - a regra 7 do system prompt (texto gerado a partir daqui);
#   - a verificação de LASTRO das citações (validacao.py), que aponta
#     artigo citado sem apoio nem no mapa nem no que o RAG recuperou.
# Acrescentar dispositivo aqui é ato deliberado de curadoria.
# ---------------------------------------------------------------------------
# (tema, artigos com lastro, como citar). Os artigos são DECLARADOS, não
# extraídos do texto: "art. 84 (1 ano…)" não pode fazer o sistema aceitar
# um "art. 1" qualquer.
MAPA_CANONICO: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("modalidade pregão", ("28", "29"), "arts. 28, I, e 29"),
    ("modalidade concorrência", ("28", "29"), "arts. 28, II, e 29"),
    ("critério de julgamento", ("33",), "art. 33"),
    ("termo de referência", ("6",), "art. 6º, XXIII"),
    ("estudo técnico preliminar", ("18",), "art. 18, §1º"),
    ("documento de formalização da demanda", ("12",), "art. 12, VII"),
    ("edital", ("25",), "art. 25"),
    ("pesquisa de preços / valor estimado", ("23",), "art. 23"),
    ("exigência de amostra ou prova de conceito", ("41", "42"),
     "art. 41, II, e art. 42"),
    ("Sistema de Registro de Preços", ("82", "83", "84", "85", "86"),
     "arts. 82 a 86"),
    ("vigência da Ata de Registro de Preços", ("84",),
     "art. 84 (1 ano, prorrogável por igual período)"),
    ("adesão à Ata por não participantes", ("86",), "art. 86"),
    ("habilitação", ("62", "63", "64", "65", "66", "67", "68", "69", "70"),
     "arts. 62 a 70"),
    ("recebimento provisório e definitivo", ("140",), "art. 140"),
    ("pagamento e ordem cronológica", ("141", "142", "143", "144", "145",
                                       "146"), "arts. 141 a 146"),
    ("garantia contratual", ("96", "97", "98"),
     "arts. 96 a 98 (o art. 98 fixa o LIMITE da garantia — não fundamenta "
     "pagamento)"),
    ("reajuste por índice (bens e materiais)", ("92",), "art. 92, §3º"),
    ("repactuação (somente serviço contínuo com dedicação de mão de obra)",
     ("135",), "art. 135"),
    ("gestão e fiscalização do contrato", ("117",), "art. 117"),
    ("infrações e sanções", ("155", "156"), "arts. 155 e 156"),
    ("impugnações e recursos", ("164", "165", "166", "167", "168"),
     "arts. 164 a 168"),
    ("tratamento favorecido a ME/EPP", (), "LC nº 123/2006"),
)


# Todo o mapa é da Lei nº 14.133/2021 (o item de ME/EPP não traz artigo,
# apenas a LC nº 123/2006): o lastro canônico é ancorado NELA — nunca em
# um número de artigo solto, que serviria a qualquer norma.
NORMA_DO_MAPA = "lei_14133_2021"


def _dispositivos_do_mapa() -> set[str]:
    """Dispositivos validados pelo mapa, como `norma:artigo`."""
    from .normas import dispositivo

    return {dispositivo(NORMA_DO_MAPA, numero)
            for _, numeros, _ in MAPA_CANONICO for numero in numeros}


def _texto_do_mapa() -> str:
    return "; ".join(f"{tema} = {referencia}"
                     for tema, _, referencia in MAPA_CANONICO)

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
3. DADO FALTANTE = MARCADOR, NUNCA IMPROVISO. Quando uma informação concreta necessária (um nome, uma matrícula, uma data, um prazo em dias, um número, uma dotação) não constar do memorando, do formulário, da planilha ou dos anexos, escreva EXATAMENTE o marcador [PREENCHER: descrição precisa da informação faltante] no local. É TERMINANTEMENTE PROIBIDO tapar a lacuna com um número ou valor solto (ex.: escrever "matrícula: 15" ou "prazo de entrega: 15" quando esse dado não foi informado), com um dado de outro processo, ou com texto vago. Os marcadores são resolvidos na revisão humana; o sistema bloqueia a emissão enquanto existirem.
4. ESCREVA O CONTEÚDO, NÃO O DESCREVA. Cada cláusula deve conter o texto real e desenvolvido do ato administrativo — jamais uma frase que apenas DESCREVE o que a cláusula deveria conter. É PROIBIDO redigir cláusulas como "Descrição da necessidade...", "Indicação da solução proposta...", "Justificativa da contratação conforme o processo" ou qualquer variação meta-descritiva. Desenvolva a Justificativa, a Necessidade e a Solução a partir do objeto, do memorando e da natureza da contratação, com argumentação técnica própria; se faltar o insumo essencial, use [PREENCHER: ...] específico — nunca um resumo genérico que serviria a qualquer contratação.
5. PROIBIDO EXPOR A ORIGEM DO DADO NO CORPO. Nunca escreva no documento etiquetas de procedência como "(fonte: formulário)", "(fonte: planilha)", "(conforme formulário)", "conforme o formulário" ou similares. O documento é um ato administrativo; a origem dos dados é interna e não aparece no texto oficial. Fontes legítimas (leis, acórdãos, pesquisa de preços) são citadas de forma institucional no corpo.
6. Estruture o documento em Markdown: cláusulas como '## N. TÍTULO EM CAIXA ALTA'; itens e subitens como parágrafos numerados hierarquicamente no próprio texto (1.1., 1.1.1.), no padrão dos documentos oficiais; tabelas em Markdown. Não cole URLs cruas no meio da prosa: links de pesquisa de preço permanecem SOMENTE na coluna de fonte da planilha, no formato [link](https://...).
7. Fundamente as cláusulas citando os dispositivos pertinentes da Lei nº 14.133/2021 e das normas/manuais fornecidos — sempre CONECTANDO o dispositivo ao conteúdo tratado; não transforme cláusulas em mera transcrição de artigos de lei. CITE APENAS dispositivos COM LASTRO: os do MAPA CANÔNICO abaixo, ou os que constem EXPRESSAMENTE de um trecho recuperado da base de conhecimento. Sem lastro, cite a norma SEM o número do artigo — "nos termos da Lei nº 14.133/2021" é sempre preferível a um artigo errado; é PROIBIDO deduzir número de dispositivo por memória ou analogia. Em contratação de bens/materiais NUNCA use "repactuação": o instituto é o reajuste. MAPA CANÔNICO (Lei nº 14.133/2021) — use exatamente estas referências: {MAPA_CANONICO}.
8. Produza APENAS o texto do documento solicitado — sem comentários, sem explicações introdutórias e sem observações finais fora do documento.
9. NUNCA mencione no documento: o funcionamento interno do sistema, prompts, inteligência artificial, modelos de linguagem, "formulário matriz", bases de treinamento ou instruções recebidas. O documento é um ato administrativo, não um relatório do sistema.
10. Profundidade: siga as metas de blocos indicadas por cláusula. É proibido tanto o texto raso/genérico que serviria a qualquer contratação quanto o enchimento artificial com repetições. Cada afirmação relevante deve decorrer de informação do processo atual ou de norma aplicável.
11. O documento deve estar pronto para revisão humana e assinatura pela autoridade competente.
12. AFIRMAÇÃO DE FATO EXIGE EVIDÊNCIA NO PROCESSO. É PROIBIDO afirmar como ocorrido, existente ou verificado qualquer fato que o processo atual não demonstre — em especial: histórico ou média de consumo, séries e percentuais de crescimento, sazonalidade, situação de emergência ou desabastecimento, capacidade de armazenamento, número ou capacidade de fornecedores do mercado, existência de pesquisa de preços realizada, inclusão no Plano de Contratações Anual (PCA), dotação orçamentária e previsão na LOA, prazos de entrega praticados, certificações, ensaios, amostras e assistência técnica. Se o insumo não estiver no processo, ou você escreve a cláusula sem a afirmação, ou registra [PREENCHER: descrição do dado] — nunca a afirmação sem lastro.
13. NADA DE ENCHIMENTO. As metas de profundidade são atingidas com ANÁLISE do objeto desta contratação, nunca com repetição da mesma ideia em outras palavras, paráfrase da lei, frases de efeito ("em consonância com os princípios da eficiência e economicidade") ou reenunciação do que já foi dito em outra cláusula. Texto que serviria a qualquer contratação não conta como profundidade.
14. CADA DOCUMENTO É AUTOSSUFICIENTE. Ao herdar uma decisão do documento anterior, EXPRESSE O CONTEÚDO da decisão — é PROIBIDO remeter o leitor à numeração interna de outro artefato ("conforme ETP, item 4.3", "nos termos do item 6.7 do TR"). Citar o documento sem o número do item ("conforme o Estudo Técnico Preliminar aprovado") é permitido.
15. QUEM ASSINA E QUEM É DESIGNADO NÃO É DECISÃO DE MÁQUINA. Nome, cargo, matrícula, número funcional, gestor, fiscal, pregoeiro, equipe de planejamento e autoridade competente só entram no documento se constarem do processo atual. Não os deduza do órgão, do objeto ou dos documentos anteriores: sem o dado, use [PREENCHER: nome e matrícula do agente]. Designar uma UNIDADE ("a fiscalização caberá à Secretaria Municipal de Administração") é legítimo quando o processo a indica.

EXEMPLO DO PADRÃO EXIGIDO (cláusula de Justificativa):
- ERRADO (raso/meta-descritivo, com etiqueta de origem): "Atender as necessidades administrativas da Prefeitura. (fonte: formulário)"
- CERTO (desenvolvido, institucional): "A contratação justifica-se pela necessidade de assegurar o fornecimento contínuo e padronizado de materiais de expediente às secretarias municipais, evitando a descontinuidade das atividades-meio e os custos de aquisições fragmentadas. O Sistema de Registro de Preços (art. 82 da Lei nº 14.133/2021) confere economicidade e previsibilidade ao atendimento de demanda recorrente e de quantitativo não exatamente conhecido. [PREENCHER: indicador ou histórico de consumo que dimensione a economia esperada, se disponível]." """

# O mapa canônico é injetado a partir da estrutura de dados: prompt e
# verificação de lastro (validacao.py) leem a MESMA fonte e não divergem.
SYSTEM_PROMPT_BASE = SYSTEM_PROMPT_BASE.replace("{MAPA_CANONICO}",
                                                _texto_do_mapa())

# Números de artigo com lastro canônico — consumido pela validação.
DISPOSITIVOS_CANONICOS = _dispositivos_do_mapa()

# ---------------------------------------------------------------------------
# Raciocínio do ETP (P1)
#
# A estrutura do ETP já vinha correta dos documentos aprovados; o defeito
# era SEMÂNTICO: o modelo recebia "modelo de execução: SRP" do formulário
# e escrevia o estudo como se a solução já estivesse decidida — as
# alternativas viravam enfeite e a conclusão apenas confirmava a premissa.
# O ETP é o documento que ESCOLHE a solução; a preferência do requisitante
# entra como hipótese a ser testada, não como conclusão.
# ---------------------------------------------------------------------------
RACIOCINIO_ETP = """

RACIOCÍNIO OBRIGATÓRIO DO ETP (o estudo CONCLUI, não pressupõe):
Encadeie o documento nesta ordem lógica, e só avance quando a etapa anterior estiver estabelecida:
NECESSIDADE (qual problema administrativo existe) → REQUISITOS (o que a solução precisa atender) → ALTERNATIVAS (quais caminhos reais existem no mercado/na Administração) → ANÁLISE TÉCNICA E ECONÔMICA (comparação entre as alternativas) → SOLUÇÃO ESCOLHIDA (decorrência da análise) → CONSEQUÊNCIAS DA ESCOLHA (quantitativos, valor, riscos, providências, resultados).

REGRAS DESTE RACIOCÍNIO:
a) A cláusula de NECESSIDADE descreve o PROBLEMA e o interesse público — é PROIBIDO anunciar nela a solução, a modalidade ou o modelo de execução como decisão tomada ("adota-se o SRP", "a solução será…"). A necessidade não conhece a resposta ainda.
b) A solução indicada pelo demandante no DFD e o MODELO DE EXECUÇÃO informado no formulário são PREFERÊNCIA/HIPÓTESE DE MODELAGEM do requisitante — insumos legítimos, jamais conclusão. O ETP pode confirmá-los, ajustá-los, refiná-los ou REJEITÁ-LOS de forma fundamentada. Se confirmar, precisa DEMONSTRAR por que a modelagem é adequada a esta demanda (ex.: por que o Sistema de Registro de Preços serve a este objeto), e não apenas repetir que foi o que se pediu.
c) O LEVANTAMENTO DE SOLUÇÕES analisa alternativas REAIS e pertinentes ao objeto — por exemplo, conforme o caso: aquisição × locação; contratação própria × adesão a ata; execução direta × terceirizada; solução integrada × fragmentada; contratação pontual × registro de preços; solução instalada × serviço em nuvem. Selecione apenas as plausíveis para ESTE objeto, com vantagens e desvantagens de cada uma. É PROIBIDO inventar alternativas fictícias só para preencher a cláusula; se houver de fato uma única alternativa tecnicamente viável, diga isso e explique o motivo.
d) A SOLUÇÃO ESCOLHIDA deve decorrer de critérios explicitáveis — adequação técnica, custo, competitividade, capacidade de atendimento do mercado, flexibilidade, padronização, risco, prazo, manutenção, ciclo de vida, escalabilidade, economicidade e eficiência administrativa —, indicando quais pesaram nesta contratação.
e) É PROIBIDO o absolutismo sem evidência: não escreva "única solução possível", "solução incontestável", "juridicamente irrepreensível" ou equivalentes. Conclua com a firmeza que a análise sustenta."""


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
        "14.133/2021, no padrão institucional da Administração demandante.\n"
        "O DFD ABRE o processo: ele expõe a demanda, NÃO decide a "
        "contratação. Distinga com clareza, em cláusulas próprias: a "
        "JUSTIFICATIVA (por que a Administração precisa agir — o interesse "
        "público em jogo), a NECESSIDADE (qual carência concreta existe "
        "hoje), a OPORTUNIDADE (por que agora, e o que ocorre se nada for "
        "feito) e a SOLUÇÃO PRELIMINARMENTE PROPOSTA pelo demandante — que "
        "é PROPOSTA, não decisão. É PROIBIDO ao DFD decidir modalidade "
        "(pregão, concorrência), adotar Sistema de Registro de Preços, "
        "fixar critério de julgamento ou concluir pelo parcelamento: essas "
        "escolhas pertencem ao Estudo Técnico Preliminar, que ainda não "
        "foi feito. Mencione a preferência do requisitante como hipótese a "
        "ser avaliada, se for o caso.\n"
        "A cláusula de identificação e a de prioridade/previsão contêm "
        "APENAS os dados do processo (unidade, responsável, prazo "
        "pretendido, grau de prioridade); é PROIBIDO inserir nelas itens, "
        "quantidades, preços ou qualquer trecho da planilha."
    ),
    "etp": (
        "Elabore o ESTUDO TÉCNICO PRELIMINAR (ETP), nos termos do art. 18, "
        "caput e §1º, da Lei nº 14.133/2021, utilizando o DFD aprovado "
        "(fornecido abaixo) como fundamento da necessidade, no padrão "
        "institucional da Administração demandante. Na cláusula de ANÁLISE DE "
        "RISCOS, monte a matriz em tabela Markdown com as colunas: Risco | "
        "Probabilidade (Baixa/Média/Alta) | Impacto (Baixo/Médio/Alto) | "
        "Medida de Mitigação | Responsável."
        + RACIOCINIO_ETP
    ),
    "tr": (
        "Elabore o TERMO DE REFERÊNCIA (TR), nos termos do art. 6º, XXIII, e "
        "do art. 40 da Lei nº 14.133/2021, utilizando o ETP aprovado "
        "(fornecido abaixo) como CONTEXTO EXCLUSIVO — todas as definições "
        "técnicas devem decorrer dele —, no padrão institucional da "
        "Administração demandante.\n"
        "O TR HERDA as decisões do ETP aprovado e as expressa como "
        "conteúdo próprio: não reabra o que o estudo decidiu (modelagem, "
        "parcelamento, solução escolhida) nem decida o que ele não "
        "decidiu. Não invente exigências: certificação, norma técnica, "
        "ensaio, amostra, prova de conceito, prazo de entrega, garantia do "
        "produto, assistência técnica e nível de serviço só entram se "
        "constarem do ETP ou do processo — caso contrário, "
        "[PREENCHER: descrição da exigência], porque exigência sem "
        "respaldo restringe a competição indevidamente.\n"
        "RASTREABILIDADE: a cadeia requisito → modelo de execução → "
        "fiscalização → critério de recebimento → pagamento deve ser "
        "explícita e coerente — o que se exige tem de ser o que se "
        "fiscaliza, o que se recebe e o que se paga. Em aquisição de bens, "
        "o instituto de atualização de preços é o REAJUSTE (art. 92, §3º) "
        "ou o reequilíbrio econômico-financeiro; é PROIBIDO prever "
        "repactuação, que pressupõe serviço contínuo com dedicação "
        "exclusiva de mão de obra (art. 135)."
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


# ---------------------------------------------------------------------------
# Duas representações do MESMO formulário
#
# Causa-raiz do vazamento de mecânica interna nos documentos: havia uma
# única representação, escrita para o MODELO, e o Modo Demonstração a
# colava no corpo do documento. Frases como "PROIBIDO escrever a lista de
# itens" ou "para você compreender o que se contrata" são legítimas num
# prompt e ilegítimas num ato administrativo — um documento oficial não
# dá ordens a quem o redige.
#
# A separação é de DESTINO, não de dados: o percurso dos campos é um só,
# o cálculo da planilha é um só (`planilha.calcular`), e a diferença fica
# restrita a como o bloco da planilha é renderizado e ao enquadramento do
# modelo de execução no ETP — que também é fala dirigida ao modelo.
# ---------------------------------------------------------------------------
def _bloco_do_formulario(dados: dict, doc_key: str, *,
                         para_modelo: bool) -> str:
    """Percurso ÚNICO dos campos; só o destino do texto muda."""
    linhas = []
    for chave, meta in CAMPOS_FORMULARIO.items():
        if chave == "memorando":
            continue  # entra em bloco próprio, mais destacado, em montar_prompt
        if chave == "itens":
            # A planilha NUNCA entra no prompt: nem completa, nem como
            # amostra. O modelo recebe só estatística e o marcador; a
            # tabela é injetada por código, em qualquer tamanho. Enquanto
            # linhas reais iam no prompt, elas voltavam copiadas e
            # parciais no documento (edital com 53 de 210 códigos).
            itens, valor_global = planilha.calcular(dados.get("itens") or [])
            resumo = (planilha.resumo_para_prompt if para_modelo
                      else planilha.resumo_objetivo)
            linhas.append(f"- {meta['rotulo']}:\n"
                          + resumo(itens, valor_global))
            continue
        valor = dados.get(chave)
        if valor in (None, "", 0):
            valor = "(não informado)"
        if chave == "modelo_execucao" and doc_key == "etp" and para_modelo:
            linhas.append(
                f"- {meta['rotulo']} — PREFERÊNCIA DE MODELAGEM indicada "
                f"pelo requisitante, a ser CONFIRMADA OU AFASTADA pelo "
                f"estudo (não é conclusão do ETP): {valor}")
            continue
        linhas.append(f"- {meta['rotulo']}: {valor}")
    return "\n".join(linhas)


def formatar_dados_formulario(dados: dict, doc_key: str = "") -> str:
    """
    O Formulário Matriz como bloco de texto PARA A IA.

    Contém instrução endereçada ao modelo (proibições sobre a lista de
    itens, o marcador da tabela, a composição funcional do objeto). Por
    isso **não pode ir para o corpo de documento nenhum** — para esse uso
    existe `dados_objetivos_do_formulario`.

    No ETP o modelo de execução é apresentado como PREFERÊNCIA do
    requisitante — é justamente o estudo que decide a modelagem (P1).
    """
    return _bloco_do_formulario(dados, doc_key, para_modelo=True)


def dados_objetivos_do_formulario(dados: dict) -> str:
    """
    O Formulário Matriz como bloco de texto PARA O DOCUMENTO.

    Mesmos campos, mesmos números, mesma planilha calculada — sem uma
    linha dirigida ao modelo. É o que o Modo Demonstração pode escrever
    no corpo de uma minuta.
    """
    return _bloco_do_formulario(dados, "", para_modelo=False)


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
            "escrito, sem inventar. Onde faltar dado, use o marcador COM a "
            "descrição do que falta — [PREENCHER: descrição precisa da "
            "informação faltante] —, nunca [PREENCHER] sozinho: é essa "
            "descrição que o sistema pergunta ao servidor na revisão. "
            "ATENÇÃO: se o memorando contiver a lista/planilha de itens (com "
            "quantidades, valores ou links), NÃO a reproduza no texto do "
            "documento — a tabela oficial vem exclusivamente da planilha do "
            "sistema; links de pesquisa de preço nunca aparecem na prosa.\n"
            + memorando
        )
    partes.append(
        "\n=== DADOS DO FORMULÁRIO MATRIZ (fonte primária do processo atual) ===\n"
        + formatar_dados_formulario(dados, doc_key)
    )
    if contexto_anterior:
        nomes = {"dfd": "DFD APROVADO", "etp": "ETP APROVADO", "tr": "TR APROVADO"}
        origem = {"etp": "dfd", "tr": "etp", "edital": "tr"}[doc_key]
        # P1: o DFD PROPÕE, o ETP DECIDE, o TR EXECUTA a decisão do ETP.
        papel = {
            "etp": "A solução indicada pelo DFD é PRELIMINAR: use-a como "
                   "hipótese inicial do estudo, que pode confirmá-la, "
                   "ajustá-la ou afastá-la de forma fundamentada.",
            "tr": "O TR OPERACIONALIZA a solução escolhida no ETP: é "
                  "PROIBIDO criar solução, modelagem, modalidade ou "
                  "critério de julgamento diferentes dos definidos no ETP.",
            "edital": "O Edital deve respeitar objeto, requisitos, "
                      "modalidade, critério de julgamento, prazos, "
                      "garantia e habilitação já definidos no TR.",
        }[doc_key]
        partes.append(
            f"\n=== {nomes[origem]} PELO USUÁRIO (contexto obrigatório) ===\n"
            f"{papel}\n"
            + contexto_anterior
        )
    return SYSTEM_PROMPT_BASE, "\n".join(partes)
