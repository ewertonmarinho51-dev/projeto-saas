"""
Construtor de templates por blocos (Fase 5 do Centro de Governança V6).

Um template é um ARTEFATO versionado (tipo "template") cujo payload é
uma lista ordenada de BLOCOS tipados (validados no contrato da F1):
cabeçalho, título, metadados, cláusula do catálogo, seção gerada,
tabela, lista de itens, matriz de riscos, assinatura, anexo, quebra e
rodapé. Não existe editor livre de PDF.

A MONTAGEM é 100% determinística (código, nunca IA):
  - condição de bloco avaliada sobre o contexto (formato do motor V5);
  - bloco `clausula_catalogo` injeta a versão PUBLICADA da cláusula;
  - cláusulas FIXED_LOCKED entram literalmente (T10 — nem parâmetro);
  - FIXED_PARAMETERIZED aceita substituição APENAS dos parâmetros
    permitidos — parâmetro fora da lista é REJEITADO (T11);
  - parâmetro obrigatório ausente vira PENDÊNCIA (não inventa valor);
  - `secao_gerada`/tabelas viram marcadores que o pipeline existente
    já resolve ([[TABELA_ITENS]]) ou a IA preenche na geração;
  - o resultado carrega o SNAPSHOT das cláusulas usadas (chave, versão,
    hash) — o documento emitido preserva exatamente o que usou (T03).

O texto montado é Markdown — o renderer determinístico existente
(export.py) segue sendo quem gera DOCX/PDF.

Flag `flag_template_builder`: liga o módulo na página Governança.
"""

import re

from . import conhecimento, db, governanca

_RE_PARAMETRO = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")


class ErroTemplate(Exception):
    """Montagem recusada (parâmetro proibido, cláusula ausente…)."""


def ativa() -> bool:
    return db.flag_ativa(governanca.FLAG_TEMPLATES)


# ---------------------------------------------------------------------------
# Cláusula do catálogo dentro do template
# ---------------------------------------------------------------------------
def _texto_da_clausula(clausula_payload: dict, parametros: dict,
                       pendencias: list) -> str:
    comportamento = clausula_payload.get("comportamento")
    permitidos = set(clausula_payload.get("parametros_permitidos") or [])
    obrigatorios = set(clausula_payload.get("parametros_obrigatorios") or [])
    partes = []
    for bloco_texto in clausula_payload.get("blocos", []):
        texto = bloco_texto
        usados = set(_RE_PARAMETRO.findall(texto))
        if comportamento == "FIXED_LOCKED":
            # entra LITERAL: nenhum parâmetro, nenhuma substituição (T10)
            partes.append(texto)
            continue
        for nome in usados:
            if nome not in permitidos:
                raise ErroTemplate(
                    f"parâmetro {nome!r} não autorizado na cláusula "
                    f"'{clausula_payload.get('titulo')}' (T11)")
            if nome in parametros:
                texto = re.sub(r"\{\{\s*" + nome + r"\s*\}\}",
                               str(parametros[nome]), texto)
            elif nome in obrigatorios:
                pendencias.append({
                    "tipo": "parametro_obrigatorio",
                    "parametro": nome,
                    "clausula": clausula_payload.get("titulo"),
                })
        partes.append(texto)
    return "\n\n".join(partes)


def _clausulas_publicadas_por_chave() -> dict:
    from . import catalogo

    return {item["artefato"]["chave_estavel"]: item["publicada"]
            for item in catalogo.listar_com_situacao("clausula")
            if item["publicada"]}


# ---------------------------------------------------------------------------
# Montagem determinística do template
# ---------------------------------------------------------------------------
def montar(template_payload: dict, contexto: dict,
           parametros: dict | None = None,
           clausulas: dict | None = None) -> dict:
    """
    {"texto": markdown, "pendencias": [...], "clausulas_usadas":
     [{chave, versao, hash}]}. `clausulas` = {chave: versão publicada}
    (injetável para teste; default: catálogo do banco).
    """
    parametros = parametros or {}
    if clausulas is None:
        clausulas = _clausulas_publicadas_por_chave()
    partes: list[str] = []
    pendencias: list[dict] = []
    usadas: list[dict] = []
    numero = 0

    for bloco in template_payload.get("blocos", []):
        condicao = bloco.get("condicao")
        if condicao and not conhecimento.avaliar_condicao(
                condicao, contexto)["resultado"]:
            continue
        tipo = bloco.get("tipo")
        if tipo == "titulo":
            partes.append(f"# {bloco.get('texto', '')}".strip())
        elif tipo == "metadados":
            linhas = [f"**{campo}**: {contexto.get(campo, '—')}"
                      for campo in bloco.get("campos", [])]
            partes.append("\n".join(linhas))
        elif tipo == "clausula_catalogo":
            chave = bloco.get("clausula")
            versao = clausulas.get(chave)
            if versao is None:
                pendencias.append({"tipo": "clausula_nao_publicada",
                                   "clausula": chave})
                continue
            numero += 1
            payload = versao.get("payload") or {}
            corpo = _texto_da_clausula(payload, parametros, pendencias)
            partes.append(f"## {numero}. {payload.get('titulo', '')}\n\n"
                          f"{corpo}")
            usadas.append({"chave": chave,
                           "versao": versao.get("versao"),
                           "hash": versao.get("hash")})
        elif tipo == "secao_gerada":
            numero += 1
            partes.append(f"## {numero}. {bloco.get('titulo', '')}\n\n"
                          f"[[SECAO_GERADA:{bloco.get('id')}]]")
        elif tipo in ("tabela", "lista_itens"):
            partes.append("[[TABELA_ITENS]]")
        elif tipo == "matriz_riscos":
            partes.append("[[MATRIZ_RISCOS]]")
        elif tipo == "assinatura":
            partes.append(bloco.get("texto")
                          or "Local e data.\n\n_________________________\n"
                             "Assinatura da autoridade competente")
        elif tipo == "quebra":
            partes.append("\\pagebreak")
        # cabecalho/rodape/anexo: tratados pelo renderer/branding

    return {"texto": "\n\n".join(p for p in partes if p),
            "pendencias": pendencias,
            "clausulas_usadas": usadas}


def criar_template(chave_estavel: str, blocos: list[dict],
                   plataforma: bool = False) -> tuple[dict, dict]:
    from . import catalogo

    return catalogo.criar_artefato("template", chave_estavel,
                                   {"blocos": blocos}, plataforma)


# ---------------------------------------------------------------------------
# Catálogo BASE de cláusulas do Edital e da Ata de Registro de Preços
#
# Edital e ARP não são redigidos por prosa livre da IA: são instrumentos
# de conteúdo obrigatório, e o que falta neles tem de ficar VISÍVEL como
# pendência, não preenchido por plausibilidade. O edital auditado saiu
# com o pregão fundado no art. 109 (é o art. 28, I, c/c o art. 29),
# garantia sem base legal, tabela de itens parcial e ARP inexistente —
# tudo consequência de deixar a redação jurídica a cargo do gerador.
#
# Este catálogo é a camada NACIONAL (a menos específica): cláusula
# publicada no catálogo do município/secretaria com a MESMA chave
# prevalece (ver `montar_oficial`). Os dispositivos citados são os da
# Lei nº 14.133/2021; nenhum número foi deduzido por analogia.
# ---------------------------------------------------------------------------
_PARAM = "FIXED_PARAMETERIZED"


def _clausula(titulo: str, blocos: list[str], permitidos=(),
              obrigatorios=()) -> dict:
    """Versão publicada sintética, no formato que `montar` consome."""
    return {
        "versao": 0,                      # 0 = base nacional embutida
        "hash": "",
        "payload": {
            "titulo": titulo,
            "blocos": blocos,
            "comportamento": _PARAM,
            "parametros_permitidos": list(permitidos),
            "parametros_obrigatorios": list(obrigatorios),
        },
    }


CLAUSULAS_BASE: dict[str, dict] = {
    # -- EDITAL (conteúdo mínimo do art. 25) ---------------------------
    "edital.preambulo": _clausula(
        "DO PREÂMBULO",
        ["O **{{orgao}}**, por meio da autoridade competente, torna público "
         "que realizará licitação na modalidade **{{modalidade}}**, sob a "
         "forma eletrônica, do tipo **{{criterio_julgamento}}**, no modo de "
         "disputa **{{modo_disputa}}**, sob o regime de **{{regime_execucao}}"
         "**, regida pela Lei nº 14.133, de 1º de abril de 2021, pelo "
         "Decreto Municipal nº 012/2023 e demais normas aplicáveis.",
         "Processo administrativo nº {{numero_processo}}. A sessão pública "
         "será realizada em {{data_sessao}}, às {{hora_sessao}}, no sítio "
         "eletrônico {{plataforma}}."],
        permitidos=("orgao", "modalidade", "criterio_julgamento",
                    "modo_disputa", "regime_execucao", "numero_processo",
                    "data_sessao", "hora_sessao", "plataforma"),
        obrigatorios=("orgao", "modalidade", "criterio_julgamento",
                      "modo_disputa", "regime_execucao", "numero_processo",
                      "data_sessao", "hora_sessao", "plataforma")),
    "edital.objeto": _clausula(
        "DO OBJETO",
        ["Constitui objeto desta licitação a {{objeto}}, conforme "
         "especificações, quantitativos e condições estabelecidos no Termo "
         "de Referência, anexo a este Edital.",
         "O valor total estimado da contratação e a relação completa dos "
         "itens constam da tabela a seguir e do Termo de Referência."],
        permitidos=("objeto",), obrigatorios=("objeto",)),
    "edital.participacao": _clausula(
        "DAS CONDIÇÕES DE PARTICIPAÇÃO",
        ["Poderão participar os interessados cujo objeto social seja "
         "compatível com o objeto licitado e que atendam às condições "
         "deste Edital.",
         "Estão impedidos de participar os que incorrerem nas vedações do "
         "art. 14 da Lei nº 14.133/2021.",
         "Será assegurado o tratamento favorecido às microempresas e "
         "empresas de pequeno porte, nos termos da Lei Complementar nº "
         "123/2006, observado o art. 4º da Lei nº 14.133/2021."]),
    "edital.proposta": _clausula(
        "DA APRESENTAÇÃO DA PROPOSTA E DOS DOCUMENTOS",
        ["A proposta e os documentos de habilitação serão encaminhados "
         "exclusivamente por meio do sistema eletrônico, até a data e hora "
         "designadas para a abertura da sessão pública.",
         "A proposta deverá conter o preço unitário e o total por item, já "
         "incluídos todos os tributos, encargos e despesas, e terá prazo "
         "de validade de {{validade_proposta}}."],
        permitidos=("validade_proposta",),
        obrigatorios=("validade_proposta",)),
    "edital.julgamento": _clausula(
        "DO JULGAMENTO DAS PROPOSTAS",
        ["O julgamento observará o critério de **{{criterio_julgamento}}**, "
         "na forma do art. 33 da Lei nº 14.133/2021.",
         "Encerrada a etapa competitiva, será verificada a conformidade da "
         "proposta melhor classificada com as exigências deste Edital e do "
         "Termo de Referência, podendo ser negociada condição mais "
         "vantajosa (art. 61)."],
        permitidos=("criterio_julgamento",),
        obrigatorios=("criterio_julgamento",)),
    "edital.habilitacao": _clausula(
        "DA HABILITAÇÃO",
        ["A habilitação será aferida mediante documentação relativa à "
         "habilitação jurídica, à qualificação técnica, à qualificação "
         "econômico-financeira e à regularidade fiscal, social e "
         "trabalhista, nos termos dos arts. 62 a 70 da Lei nº "
         "14.133/2021.",
         "A documentação exigida é a estritamente necessária à execução do "
         "objeto, vedada exigência que restrinja indevidamente a "
         "competitividade."]),
    "edital.impugnacao": _clausula(
        "DA IMPUGNAÇÃO E DOS PEDIDOS DE ESCLARECIMENTO",
        ["Qualquer pessoa poderá impugnar os termos deste Edital ou "
         "solicitar esclarecimentos, na forma e nos prazos do art. 164 da "
         "Lei nº 14.133/2021.",
         "As respostas serão divulgadas no mesmo sítio eletrônico de "
         "publicação do Edital e vincularão os participantes."]),
    "edital.recursos": _clausula(
        "DOS RECURSOS",
        ["Os recursos observarão as hipóteses, a forma e os prazos dos "
         "arts. 165 a 168 da Lei nº 14.133/2021, exigida a manifestação "
         "imediata da intenção de recorrer, sob pena de preclusão."]),
    "edital.sancoes": _clausula(
        "DAS SANÇÕES ADMINISTRATIVAS",
        ["O licitante ou contratado que incorrer nas infrações do art. 155 "
         "da Lei nº 14.133/2021 estará sujeito às sanções de advertência, "
         "multa, impedimento de licitar e contratar e declaração de "
         "inidoneidade para licitar ou contratar, na forma do art. 156.",
         "A aplicação das sanções observará o contraditório e a ampla "
         "defesa, com a dosimetria do art. 156, § 1º."]),
    "edital.garantia": _clausula(
        "DA GARANTIA",
        ["{{clausula_garantia}}"],
        permitidos=("clausula_garantia",),
        obrigatorios=("clausula_garantia",)),
    "edital.recebimento_pagamento": _clausula(
        "DO RECEBIMENTO E DO PAGAMENTO",
        ["O objeto será recebido provisória e definitivamente na forma do "
         "art. 140 da Lei nº 14.133/2021 e do Termo de Referência.",
         "O pagamento será efetuado após o recebimento definitivo, mediante "
         "apresentação de nota fiscal devidamente atestada, observados os "
         "arts. 141 a 146 da Lei nº 14.133/2021 e a ordem cronológica de "
         "exigibilidade."]),
    "edital.disposicoes_finais": _clausula(
        "DAS DISPOSIÇÕES FINAIS",
        ["Integram este Edital, independentemente de transcrição: o Termo "
         "de Referência, a minuta do instrumento contratual e/ou da Ata de "
         "Registro de Preços e os modelos de declaração.",
         "Os casos omissos serão resolvidos pela autoridade competente, à "
         "luz da Lei nº 14.133/2021 e do Decreto Municipal nº 012/2023."]),

    # -- ATA DE REGISTRO DE PREÇOS -------------------------------------
    "arp.preambulo": _clausula(
        "DO PREÂMBULO",
        ["Aos {{data_assinatura_ata}}, o **{{orgao}}**, na qualidade de "
         "órgão gerenciador, e o fornecedor **{{fornecedor}}**, inscrito no "
         "CNPJ sob o nº {{cnpj_fornecedor}}, firmam a presente Ata de "
         "Registro de Preços, decorrente do {{modalidade}} nº "
         "{{numero_licitacao}}, processo administrativo nº "
         "{{numero_processo}}, nos termos da Lei nº 14.133/2021 e do "
         "Decreto Municipal nº 012/2023."],
        permitidos=("data_assinatura_ata", "orgao", "fornecedor",
                    "cnpj_fornecedor", "modalidade", "numero_licitacao",
                    "numero_processo"),
        obrigatorios=("data_assinatura_ata", "orgao", "fornecedor",
                      "cnpj_fornecedor", "modalidade", "numero_licitacao",
                      "numero_processo")),
    "arp.objeto": _clausula(
        "DO OBJETO E DOS PREÇOS REGISTRADOS",
        ["Constitui objeto desta Ata o registro de preços para a "
         "{{objeto}}, nas quantidades, especificações e preços unitários "
         "registrados na tabela a seguir.",
         "Os preços registrados não obrigam a Administração a contratar, "
         "facultada a realização de licitação específica, assegurada ao "
         "beneficiário do registro a preferência em igualdade de "
         "condições."],
        permitidos=("objeto",), obrigatorios=("objeto",)),
    "arp.vigencia": _clausula(
        "DA VIGÊNCIA",
        ["A presente Ata de Registro de Preços terá vigência de 1 (um) "
         "ano, contado da data de sua assinatura, prorrogável por igual "
         "período mediante comprovação de que as condições e os preços "
         "registrados permanecem vantajosos, nos termos do art. 84 da Lei "
         "nº 14.133/2021.",
         "A vigência dos contratos decorrentes desta Ata observará o art. "
         "105 da Lei nº 14.133/2021."]),
    "arp.gerenciamento": _clausula(
        "DO GERENCIAMENTO E DO CADASTRO DE RESERVA",
        ["O gerenciamento desta Ata caberá a {{orgao_gerenciador}}, a quem "
         "compete conduzir eventuais renegociações e aplicar as "
         "penalidades cabíveis.",
         "Fica registrado o cadastro de reserva dos licitantes que "
         "aceitaram cotar o objeto em preço igual ao do adjudicatário, na "
         "ordem de classificação, para convocação em caso de cancelamento "
         "do registro do primeiro colocado."],
        permitidos=("orgao_gerenciador",),
        obrigatorios=("orgao_gerenciador",)),
    "arp.adesao": _clausula(
        "DA ADESÃO POR ÓRGÃO NÃO PARTICIPANTE",
        ["A adesão a esta Ata por órgão ou entidade não participante "
         "dependerá de anuência do órgão gerenciador e observará os "
         "limites, as condições e o procedimento do art. 86 da Lei nº "
         "14.133/2021 e do Decreto Municipal nº 012/2023.",
         "As aquisições por adesão não poderão exceder os limites legais "
         "por órgão aderente nem o limite global do quantitativo "
         "registrado."]),
    "arp.reajuste": _clausula(
        "DA ATUALIZAÇÃO DOS PREÇOS REGISTRADOS",
        ["Os preços registrados são fixos e irreajustáveis durante a "
         "vigência da Ata, ressalvados a revisão para restabelecer o "
         "equilíbrio econômico-financeiro na hipótese do art. 124, II, "
         "'d', e o reajuste em sentido estrito na forma do art. 92, § 3º, "
         "da Lei nº 14.133/2021, quando cabível.",
         "Comprovada a alteração dos preços praticados no mercado, o órgão "
         "gerenciador poderá promover a negociação, o remanejamento ou o "
         "cancelamento do registro."]),
    "arp.cancelamento": _clausula(
        "DO CANCELAMENTO DO REGISTRO",
        ["O registro do fornecedor será cancelado quando este descumprir "
         "as condições da Ata, não retirar o instrumento equivalente no "
         "prazo estabelecido, não aceitar reduzir o preço registrado que "
         "se tornar superior ao de mercado ou sofrer sanção que o impeça "
         "de contratar com a Administração.",
         "O cancelamento será formalizado por despacho fundamentado da "
         "autoridade competente, assegurados o contraditório e a ampla "
         "defesa."]),
    "arp.sancoes": _clausula(
        "DAS SANÇÕES",
        ["O descumprimento das obrigações desta Ata sujeita o fornecedor "
         "às sanções dos arts. 155 e 156 da Lei nº 14.133/2021, "
         "assegurados o contraditório e a ampla defesa."]),
    "arp.foro": _clausula(
        "DO FORO",
        ["Fica eleito o foro da Comarca de {{comarca}} para dirimir as "
         "questões oriundas desta Ata, com renúncia a qualquer outro, por "
         "mais privilegiado que seja."],
        permitidos=("comarca",), obrigatorios=("comarca",)),
}


def _bloco(chave: str) -> dict:
    return {"tipo": "clausula_catalogo", "clausula": chave}


TEMPLATE_EDITAL = {"blocos": [
    {"tipo": "titulo", "texto": "EDITAL DE LICITAÇÃO"},
    _bloco("edital.preambulo"),
    _bloco("edital.objeto"),
    {"tipo": "tabela"},
    _bloco("edital.participacao"),
    _bloco("edital.proposta"),
    _bloco("edital.julgamento"),
    _bloco("edital.habilitacao"),
    _bloco("edital.impugnacao"),
    _bloco("edital.recursos"),
    _bloco("edital.sancoes"),
    _bloco("edital.garantia"),
    _bloco("edital.recebimento_pagamento"),
    _bloco("edital.disposicoes_finais"),
    {"tipo": "assinatura"},
]}

TEMPLATE_ARP = {"blocos": [
    {"tipo": "titulo", "texto": "ATA DE REGISTRO DE PREÇOS"},
    _bloco("arp.preambulo"),
    _bloco("arp.objeto"),
    {"tipo": "tabela"},
    _bloco("arp.vigencia"),
    _bloco("arp.gerenciamento"),
    _bloco("arp.adesao"),
    _bloco("arp.reajuste"),
    _bloco("arp.cancelamento"),
    _bloco("arp.sancoes"),
    _bloco("arp.foro"),
    {"tipo": "assinatura"},
]}

TEMPLATES_OFICIAIS = {"edital": TEMPLATE_EDITAL, "arp": TEMPLATE_ARP}

# Rótulo legível de cada parâmetro: é ele que aparece no [PREENCHER: …]
# e, por consequência, é a pergunta que a revisão faz ao servidor.
ROTULOS_PARAMETRO = {
    "orgao": "órgão/entidade licitante",
    "objeto": "objeto da licitação",
    "modalidade": "modalidade da licitação (art. 28 da Lei nº 14.133/2021)",
    "criterio_julgamento": "critério de julgamento (art. 33)",
    "modo_disputa": "modo de disputa (art. 56)",
    "regime_execucao": "regime de execução",
    "numero_processo": "número do processo administrativo",
    "data_sessao": "data da sessão pública",
    "hora_sessao": "horário da sessão pública",
    "plataforma": "plataforma eletrônica onde ocorrerá a sessão",
    "validade_proposta": "prazo de validade da proposta",
    "clausula_garantia": ("decisão motivada sobre garantia contratual — "
                          "exigir ou dispensar, com modalidade e "
                          "percentual (arts. 96 a 98)"),
    "data_assinatura_ata": "data de assinatura da Ata",
    "fornecedor": "razão social do fornecedor beneficiário",
    "cnpj_fornecedor": "CNPJ do fornecedor beneficiário",
    "numero_licitacao": "número da licitação que originou a Ata",
    "orgao_gerenciador": "órgão gerenciador da Ata",
    "comarca": "comarca do foro",
}


def parametros_do_processo(dados: dict) -> dict:
    """
    Parâmetros que o PROCESSO realmente fornece. Nada é deduzido: o que
    não estiver aqui vira pendência e, na montagem, [PREENCHER: …].

    Modalidade, critério de julgamento, modo de disputa, regime de
    execução, garantia, datas, plataforma e fornecedor são DECISÕES ou
    fatos externos — não saem do formulário atual e por isso jamais são
    preenchidos automaticamente.
    """
    parametros = {}
    if (dados.get("orgao") or "").strip():
        parametros["orgao"] = dados["orgao"].strip()
        parametros["orgao_gerenciador"] = dados["orgao"].strip()
    if (dados.get("objeto") or "").strip():
        parametros["objeto"] = dados["objeto"].strip()
    return parametros


def montar_oficial(doc_key: str, dados: dict,
                   clausulas: dict | None = None) -> dict:
    """
    Edital ou Ata montados por CÓDIGO a partir do catálogo.

    Cláusula publicada no catálogo do órgão (mesma chave) prevalece sobre
    a base nacional — a personalização municipal continua sendo pelo
    catálogo versionado, nunca por prosa livre da IA.

    Toda pendência de parâmetro vira [PREENCHER: descrição do dado] no
    lugar exato: o validador existente bloqueia a emissão enquanto o
    marcador existir, e a revisão pergunta exatamente o campo que falta.
    """
    template = TEMPLATES_OFICIAIS.get(doc_key)
    if template is None:
        raise ErroTemplate(f"não há template oficial para {doc_key!r}")

    catalogo_efetivo = dict(CLAUSULAS_BASE)
    if clausulas is None:
        try:
            clausulas = _clausulas_publicadas_por_chave()
        except Exception:
            clausulas = {}     # sem banco: vale a base nacional
    catalogo_efetivo.update(
        {k: v for k, v in (clausulas or {}).items() if k in CLAUSULAS_BASE})

    resultado = montar(template, dados, parametros_do_processo(dados),
                       catalogo_efetivo)

    texto = resultado["texto"]
    for pendencia in resultado["pendencias"]:
        nome = pendencia.get("parametro")
        if not nome:
            continue
        rotulo = ROTULOS_PARAMETRO.get(nome, nome)
        texto = re.sub(r"\{\{\s*" + re.escape(nome) + r"\s*\}\}",
                       f"[PREENCHER: {rotulo}]", texto)
    resultado["texto"] = texto
    return resultado
