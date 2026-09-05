"""
Consistência do processo (Fase 5 do pacote V5).

Validações DETERMINÍSTICAS cruzadas entre os fatos canônicos e todos os
documentos do bundle (e entre documentos): valores, cálculo dos itens,
quantidades, prazos e objeto. Os achados saem no MESMO formato dos
findings da correção automática v4 (achados.py) — ou seja, entram
direto no ciclo auditoria → corretor → patches → reauditoria, com o
FATO CANÔNICO como fonte da correção.

Gravidade:
  - divergência documento × fato (valor, quantidade, prazo): HIGH e
    corrigível automaticamente — o fato é a verdade e tem fonte;
  - erro de CÁLCULO (soma dos itens ≠ valor global): CRITICAL e NÃO
    corrigível — os dados de origem estão em conflito e a decisão é
    humana (KQ-016; crítico bloqueia a emissão);
  - objeto ausente da cláusula própria: LOW (aviso).

Feature flag `flag_process_consistency` (default OFF): desligada, a
auditoria v4 permanece byte a byte idêntica; ligada, os findings de
consistência (C###) somam-se aos do validador (F###).
"""

import re

from . import blocos, db, governanca, planilha

CATEGORIAS = ("consistencia_valor", "consistencia_calculo",
              "consistencia_quantidade", "consistencia_prazo",
              "consistencia_objeto", "consistencia_decisao",
              "requisito_nao_operacionalizavel",
              "consistencia_pesquisa_preco")

# ---------------------------------------------------------------------------
# DECISÕES do processo (P1)
#
# Além dos números, a cadeia DFD → ETP → TR → Edital precisa manter as
# DECISÕES: modalidade, registro de preços, adjudicação por item ou lote,
# exigência de garantia. A comparação NÃO é textual (cada documento
# escreve à sua maneira): de cada documento extrai-se o VALOR da decisão
# e comparam-se os valores. Silêncio não é divergência.
#
# AUTORIDADE POR ESTÁGIO — cada decisão é CONSOLIDADA em um documento:
#   formulário/DFD  propõem (preferência e solução preliminar);
#   ETP             consolida solução, modelagem (SRP) e parcelamento —
#                   pode confirmar, ajustar ou AFASTAR o que veio antes;
#   TR              consolida a execução (modalidade, garantia) e não
#                   pode contrariar a solução consolidada no ETP;
#   Edital          herda o que o TR definiu.
# Divergir ANTES do estágio consolidador é legítimo (é o estudo fazendo
# seu trabalho); divergir DEPOIS é o achado que interessa.
#
# ordem: o primeiro padrão que casar define o valor da decisão no doc.
# ---------------------------------------------------------------------------
DECISOES: dict[str, dict] = {
    "modalidade": {
        "rotulo": "modalidade de licitação",
        "autoridade": "tr",
        "valores": {
            "pregao": r"preg[ãa]o(?:\s+eletr[ôo]nico|\s+presencial)?",
            "concorrencia": r"concorr[êe]ncia(?:\s+eletr[ôo]nica)?",
            "dispensa": r"dispensa\s+de\s+licita[çc][ãa]o",
            "inexigibilidade": r"inexigibilidade\s+de\s+licita[çc][ãa]o",
            "leilao": r"leil[ãa]o",
        },
    },
    "srp": {
        "rotulo": "adoção do Sistema de Registro de Preços",
        "autoridade": "etp",
        "valores": {
            "nao": r"n[ãa]o\s+(?:ser[áa]|se)\s+(?:adotad[oa]|utilizad[oa])\s+"
                   r"(?:o\s+)?(?:sistema\s+de\s+registro\s+de\s+pre[çc]os|SRP)"
                   r"|sem\s+registro\s+de\s+pre[çc]os"
                   r"|contrata[çc][ãa]o\s+direta\s+sem\s+ata",
            "sim": r"sistema\s+de\s+registro\s+de\s+pre[çc]os|\bSRP\b|"
                   r"ata\s+de\s+registro\s+de\s+pre[çc]os",
        },
    },
    "adjudicacao": {
        "rotulo": "critério de adjudicação (item × lote)",
        "autoridade": "etp",
        "valores": {
            "item": r"adjudica[çc][ãa]o\s+por\s+item|julgamento\s+por\s+item|"
                    r"disputa\s+por\s+item",
            "lote": r"adjudica[çc][ãa]o\s+por\s+(?:lote|grupo)|"
                    r"julgamento\s+por\s+(?:lote|grupo)|lote\s+[úu]nico",
        },
    },
    "garantia": {
        "rotulo": "exigência de garantia contratual",
        "autoridade": "tr",
        "valores": {
            "nao": r"(?:n[ãa]o\s+(?:ser[áa]|haver[áa]|se)\s+"
                   r"(?:exigid[ao]|exigir[áa]|exige)[^.]{0,60}garantia"
                   r"|dispensad[ao]\s+a\s+(?:presta[çc][ãa]o\s+de\s+)?garantia"
                   r"|sem\s+exig[êe]ncia\s+de\s+garantia)",
            "sim": r"(?:garantia\s+contratual|garantia\s+de\s+execu[çc][ãa]o)"
                   r"[^.]{0,80}?\d{1,2}\s*%"
                   r"|\d{1,2}\s*%[^.]{0,60}?garantia\s+contratual"
                   r"|ser[áa]\s+exigida[^.]{0,40}garantia",
        },
    },
}

# Requisitos objetivamente verificáveis: quando o TR exige um documento
# comprobatório, alguém precisa verificá-lo em algum momento. Começamos
# pelos que são inequívocos (certificação/registro/laudo).
_RE_REQUISITO_VERIFICAVEL = re.compile(
    r"(certifica[çc][ãa]o\s+[\wÀ-ÿ\-/º°\. ]{2,40}"
    r"|certificado\s+de\s+aprova[çc][ãa]o|registro\s+na\s+ANVISA"
    r"|laudo\s+[\wÀ-ÿ\-/ ]{2,30}|norma\s+ABNT\s+NBR\s*[\d\.\-]+"
    r"|selo\s+do\s+INMETRO|licen[çc]a\s+ambiental)", re.IGNORECASE)
_TITULOS_VERIFICACAO = ("ACEITAÇÃO", "ACEITACAO", "RECEBIMENTO",
                        "FISCALIZAÇÃO", "FISCALIZACAO", "HABILITAÇÃO",
                        "HABILITACAO", "OBRIGAÇÕES DA CONTRATADA",
                        "OBRIGACOES DA CONTRATADA", "EXECUÇÃO", "EXECUCAO")

_RE_MOEDA = re.compile(r"R\$\s?([\d.]+,\d{2})")
_RE_MESES = re.compile(r"(\d{1,3})\s*(?:\([^)]*\)\s*)?m[eê]s(?:es)?",
                       re.IGNORECASE)

_TITULOS_VALOR = ("VALOR", "ESTIMATIVA")
_TITULOS_PRAZO = ("PERÍODO", "PERIODO", "VIGÊNCIA", "VIGENCIA", "PRAZO")
_TITULOS_OBJETO = ("OBJETO",)


def ativa() -> bool:
    return db.flag_ativa(governanca.FLAG_CONSISTENCIA)


def _para_float(moeda: str) -> float:
    return float(moeda.replace(".", "").replace(",", "."))


def _blocos_da_clausula_por_titulo(blocos_doc: list[dict],
                                   titulos: tuple) -> list[dict]:
    numeros = {b["clausula"] for b in blocos_doc
               if b["tipo"] == "titulo"
               and any(t in b["conteudo"].upper() for t in titulos)}
    return [b for b in blocos_doc if b.get("clausula") in numeros]


def _finding(n, doc_key, categoria, severidade, descricao, evidencia,
             esperado, corrigivel, paths, fontes, bloqueio=None) -> dict:
    return {
        "findingId": f"C{n:03d}",
        "documentId": doc_key,
        "clauseId": None,
        "categoria": categoria,
        "severity": severidade,
        "descricao": descricao,
        "evidencia": [evidencia] if evidencia else [],
        "regraViolada": "Coerência entre fatos canônicos e documentos "
                        "do processo (02_regras_cruzadas).",
        "resultadoEsperado": esperado,
        "autoCorrectable": bool(corrigivel and paths),
        "allowedPaths": list(paths),
        "blockedPaths": [],
        "sourceIds": list(fontes),
        "blockingReason": bloqueio if not (corrigivel and paths) else None,
    }


# ---------------------------------------------------------------------------
# Verificações (todas puras: fatos + documentos → achados)
# ---------------------------------------------------------------------------
def _verificar_calculo(contexto: dict, achados_out: list, contador) -> None:
    """Soma dos itens × valor global — refeito por CÓDIGO (KQ-016)."""
    total = contexto.get("valor.total")
    if total is None:
        return
    itens, soma = [], 0.0
    indice = 0
    while f"itens[{indice}].descricao" in contexto:
        quantidade = float(contexto.get(f"itens[{indice}].quantidade") or 0)
        unitario = float(
            contexto.get(f"itens[{indice}].valor_unitario") or 0)
        soma += quantidade * unitario
        itens.append(indice)
        indice += 1
    if itens and abs(soma - float(total)) > 0.01:
        achados_out.append(_finding(
            contador(), "bundle", "consistencia_calculo", "CRITICAL",
            f"o valor global registrado "
            f"({planilha.formatar_moeda(float(total))}) difere da soma "
            f"dos itens ({planilha.formatar_moeda(soma)})",
            "", "Valores de origem reconciliados pelo responsável — o "
            "sistema não escolhe qual está certo.",
            False, [], ["fato:valor.total"],
            bloqueio="UNRESOLVED_SOURCE_CONFLICT"))


def _verificar_pesquisa_aplicada(contexto, achados_out, contador) -> None:
    """
    O processo ainda vale o que valia quando a pesquisa foi aplicada?

    Editar a planilha depois de aplicar é legítimo. O que não pode é a
    proveniência continuar afirmando que o valor veio da pesquisa quando
    o valor já mudou — os documentos citam esse número, e a memória de
    cálculo anexada deixaria de explicá-lo.

    A comparação é contra `pesquisa_preco.valor_aplicado`, que é o total
    do PROCESSO no instante da aplicação. Comparar contra o total da
    própria pesquisa acenderia o alerta em quase toda aplicação real: o
    processo costuma ter itens que a pesquisa não cobriu, e as
    quantidades da planilha podem divergir das que formaram o preço.

    Não é auto-corrigível: o sistema não sabe qual dos dois números está
    certo. Ou o servidor confirma a edição e reaplica a pesquisa, ou
    desfaz a edição — e essa é uma decisão dele.
    """
    aplicado = contexto.get("pesquisa_preco.valor_aplicado")
    total = contexto.get("valor.total")
    if aplicado is None or total is None:
        return
    if abs(float(total) - float(aplicado)) <= 0.01:
        return
    identificador = str(contexto.get("pesquisa_preco.id") or "")
    achados_out.append(_finding(
        contador(), "bundle", "consistencia_pesquisa_preco", "HIGH",
        f"o valor global do processo "
        f"({planilha.formatar_moeda(float(total))}) mudou depois que a "
        f"pesquisa de preços foi aplicada "
        f"({planilha.formatar_moeda(float(aplicado))}): a proveniência "
        f"registrada já não descreve o valor atual",
        f"pesquisa {identificador[:8]}" if identificador else "",
        "Planilha e pesquisa reconciliadas pelo responsável — reaplicar a "
        "pesquisa ou desfazer a edição. O sistema não escolhe qual dos "
        "dois valores está certo.",
        False, [], ["fato:pesquisa_preco.valor_aplicado", "fato:valor.total"],
        bloqueio="UNRESOLVED_SOURCE_CONFLICT"))


def _verificar_valor_global(contexto, por_doc, achados_out, contador):
    total = contexto.get("valor.total")
    if not total:
        return
    moeda_fato = planilha.formatar_moeda(float(total))
    for doc_key, blocos_doc in por_doc.items():
        clausula = _blocos_da_clausula_por_titulo(blocos_doc,
                                                  _TITULOS_VALOR)
        for bloco in clausula:
            for bruto in _RE_MOEDA.findall(bloco["conteudo"]):
                if abs(_para_float(bruto) - float(total)) > 0.01:
                    achados_out.append(_finding(
                        contador(), doc_key, "consistencia_valor", "HIGH",
                        f"valor divergente do fato canônico: o documento "
                        f"traz R$ {bruto}, mas o valor global do processo "
                        f"é {moeda_fato}",
                        bloco["conteudo"][:160],
                        f"Cláusula com o valor global {moeda_fato} "
                        "(fato canônico).",
                        True, [bloco["path"]], ["fato:valor.total"]))
                    break  # um finding por bloco basta


def _verificar_quantidades(contexto, por_doc, achados_out, contador):
    indice = 0
    while f"itens[{indice}].descricao" in contexto:
        descricao = str(contexto[f"itens[{indice}].descricao"])
        quantidade = contexto.get(f"itens[{indice}].quantidade")
        indice += 1
        if quantidade is None:
            continue
        alvo = float(quantidade)
        # grafias aceitas da quantidade na linha da tabela
        variantes = {f"{alvo:g}", f"{alvo:.2f}", f"{alvo:.2f}".replace(".", ",")}
        if alvo == int(alvo):
            variantes.add(str(int(alvo)))
        for doc_key, blocos_doc in por_doc.items():
            for bloco in blocos_doc:
                if bloco["tipo"] != "tabela" or \
                        descricao not in bloco["conteudo"]:
                    continue
                linha = next((ln for ln in bloco["conteudo"].splitlines()
                              if descricao in ln), "")
                numeros = set(re.findall(r"\d+(?:[.,]\d+)?", linha))
                if numeros and not (numeros & variantes):
                    achados_out.append(_finding(
                        contador(), doc_key, "consistencia_quantidade",
                        "HIGH",
                        f"quantidade do item '{descricao}' na tabela não "
                        f"confere com o fato canônico ({alvo:g})",
                        linha[:160],
                        f"Linha do item com a quantidade {alvo:g}.",
                        True, [bloco["path"]],
                        [f"fato:itens[{indice - 1}].quantidade"]))


def _verificar_prazo(por_doc, achados_out, contador):
    """Vigências explícitas divergentes ENTRE documentos."""
    meses_por_doc: dict[str, tuple[int, dict]] = {}
    for doc_key, blocos_doc in por_doc.items():
        for bloco in _blocos_da_clausula_por_titulo(blocos_doc,
                                                    _TITULOS_PRAZO):
            m = _RE_MESES.search(bloco["conteudo"])
            if m:
                meses_por_doc[doc_key] = (int(m.group(1)), bloco)
                break
    valores = {meses for meses, _ in meses_por_doc.values()}
    if len(valores) > 1:
        detalhe = ", ".join(f"{doc} = {meses} meses"
                            for doc, (meses, _) in
                            sorted(meses_por_doc.items()))
        for doc_key, (_, bloco) in meses_por_doc.items():
            achados_out.append(_finding(
                contador(), doc_key, "consistencia_prazo", "HIGH",
                f"vigência divergente entre documentos ({detalhe})",
                bloco["conteudo"][:160],
                "Mesma vigência em todos os documentos do processo.",
                True, [bloco["path"]], ["fato:prazo.descricao"]))


def _verificar_objeto(contexto, por_doc, achados_out, contador):
    objeto = str(contexto.get("objeto.descricao") or "")
    if len(objeto) < 8:
        return
    for doc_key, blocos_doc in por_doc.items():
        clausula = _blocos_da_clausula_por_titulo(blocos_doc,
                                                  _TITULOS_OBJETO)
        if not clausula:
            continue
        corpo = [b for b in clausula if b["tipo"] != "titulo"]
        if corpo and not any(
            blocos.localizar_bloco([b], objeto) for b in corpo
        ):
            achados_out.append(_finding(
                contador(), doc_key, "consistencia_objeto", "LOW",
                "a cláusula de objeto não menciona o objeto registrado "
                "no formulário",
                (corpo[0]["conteudo"] if corpo else "")[:160],
                "Cláusula de objeto alinhada ao fato canônico "
                "objeto.descricao.",
                False, [], ["fato:objeto.descricao"],
                bloqueio="DISCRETIONARY_DECISION"))


def decisao_no_documento(texto: str, chave: str) -> tuple[str, str]:
    """
    (valor, evidência) da decisão `chave` no documento — ("", "") quando
    o documento não se manifesta. A negativa é testada antes da
    afirmativa: "não será exigida garantia" não pode virar "sim".
    """
    definicao = DECISOES[chave]
    for valor, padrao in definicao["valores"].items():
        m = re.search(padrao, texto or "", re.IGNORECASE)
        if m:
            ini = max(0, m.start() - 60)
            return valor, (texto[ini:m.end() + 60] or "").replace("\n", " ")
    return "", ""


def _ordem_documental(doc_key: str) -> int:
    from .config import SEQUENCIA_DOCUMENTOS

    return (SEQUENCIA_DOCUMENTOS.index(doc_key)
            if doc_key in SEQUENCIA_DOCUMENTOS else 99)


def documento_consolidador(chave: str, documentos: dict) -> tuple[str, str, str]:
    """
    (documento consolidador, valor consolidado, evidência) para a decisão
    `chave` — ("", "", "") quando ela AINDA NÃO FOI CONSOLIDADA.

    Só o documento com AUTORIDADE sobre a matéria consolida: o SRP se
    consolida no ETP, a modalidade no TR. Documento preliminar não é
    promovido a consolidador pelo silêncio do consolidador — o DFD
    apenas propõe, e uma proposta não obriga o TR.
    """
    autoridade = DECISOES[chave].get("autoridade", "etp")
    valor, evidencia = decisao_no_documento(documentos.get(autoridade, ""),
                                            chave)
    return (autoridade, valor, evidencia) if valor else ("", "", "")


def _verificar_decisoes(contexto, documentos, por_doc, achados_out,
                        contador) -> None:
    """
    Decisões contraditórias APÓS a consolidação. Documento anterior ao
    estágio consolidador que divirja não é erro: é proposta preliminar
    sendo revista (o ETP existe justamente para isso).

    Com o consolidador silencioso, nada é acusado de contrariar decisão
    — no máximo se registra que a decisão ainda não foi consolidada.
    """
    for chave, definicao in DECISOES.items():
        base_doc, base_valor, _ = documento_consolidador(chave, documentos)
        if not base_doc:
            _avisar_decisao_nao_consolidada(chave, definicao, documentos,
                                            achados_out, contador)
            continue
        ordem_base = _ordem_documental(base_doc)
        for doc_key, texto in documentos.items():
            if _ordem_documental(doc_key) <= ordem_base:
                continue  # antes (ou o próprio) do consolidador: preliminar
            valor, evidencia = decisao_no_documento(texto, chave)
            if not valor or valor == base_valor:
                continue
            bloco = blocos.localizar_bloco(por_doc.get(doc_key, []), evidencia)
            achados_out.append(_finding(
                contador(), doc_key, "consistencia_decisao", "HIGH",
                f"{definicao['rotulo']} divergente da decisão já "
                f"consolidada: {base_doc.upper()} define '{base_valor}' e "
                f"{doc_key.upper()} traz '{valor}'",
                evidencia[:160],
                f"Documento alinhado à decisão consolidada no "
                f"{base_doc.upper()} ({base_valor}) — ou alteração "
                "justificada e propagada a todo o processo.",
                False, [bloco["path"]] if bloco else [],
                [f"documento:{base_doc}"],
                bloqueio="DISCRETIONARY_DECISION"))


def _avisar_decisao_nao_consolidada(chave, definicao, documentos,
                                    achados_out, contador) -> None:
    """
    Documentos divergem numa matéria que o documento competente ainda não
    decidiu. Não é contradição com decisão consolidada (não há decisão):
    é lacuna de instrução — aviso de gravidade menor, sem culpar um
    documento por contrariar outro que não tinha autoridade.
    """
    autoridade = definicao.get("autoridade", "etp")
    if autoridade not in documentos:
        return  # o documento competente nem existe no dossiê ainda
    valores = {}
    for doc_key, texto in documentos.items():
        valor, evidencia = decisao_no_documento(texto, chave)
        if valor:
            valores[doc_key] = (valor, evidencia)
    if len({v for v, _ in valores.values()}) < 2:
        return
    detalhe = ", ".join(f"{doc.upper()} = {valor}"
                        for doc, (valor, _) in sorted(valores.items()))
    achados_out.append(_finding(
        contador(), autoridade, "consistencia_decisao", "MEDIUM",
        f"{definicao['rotulo']} ainda NÃO CONSOLIDADA: os documentos "
        f"divergem ({detalhe}) e o {autoridade.upper()} — competente pela "
        "matéria — não se manifesta",
        "", f"Decisão expressa e fundamentada no {autoridade.upper()}, "
        "propagada aos documentos seguintes.",
        False, [], [f"documento:{autoridade}"],
        bloqueio="DISCRETIONARY_DECISION"))


def _verificar_srp_contra_fato(contexto, documentos, achados_out,
                               contador) -> None:
    """
    Modelagem do formulário × documentos. O formulário é PREFERÊNCIA: se
    o ETP (estágio consolidador do SRP) se manifestou, é ele que vale e
    nada é apontado. Sem ETP no dossiê, a divergência vira aviso de
    modelagem não confirmada — nunca erro do documento.
    """
    fato_srp = contexto.get("procedimento.srp")
    if fato_srp is None:
        return
    consolidador = DECISOES["srp"].get("autoridade", "etp")
    valor_etp, _ = decisao_no_documento(documentos.get(consolidador, ""), "srp")
    if valor_etp:
        return  # o estudo consolidou a modelagem: a preferência cedeu
    esperado = "sim" if fato_srp else "nao"
    for doc_key, texto in documentos.items():
        valor, evidencia = decisao_no_documento(texto, "srp")
        if valor and valor != esperado:
            achados_out.append(_finding(
                contador(), doc_key, "consistencia_decisao", "MEDIUM",
                "o documento trata o Sistema de Registro de Preços de forma "
                f"incompatível com o processo (formulário: "
                f"{'com' if fato_srp else 'sem'} SRP) e não há ETP no "
                "dossiê consolidando a mudança",
                evidencia[:160],
                "Modelagem alinhada ao processo — ou consolidada no ETP "
                "com justificativa.",
                False, [], ["fato:procedimento.srp"],
                bloqueio="DISCRETIONARY_DECISION"))


def _verificar_requisitos_operacionalizaveis(por_doc, achados_out,
                                             contador) -> None:
    """
    REQUISITO → EXECUÇÃO → FISCALIZAÇÃO → ACEITAÇÃO: um requisito
    objetivamente verificável (certificação, laudo, norma técnica) exigido
    no TR precisa ser retomado em alguma cláusula de verificação — senão
    ninguém sabe quando nem quem confere. Aviso: a forma é discricionária.
    """
    blocos_doc = por_doc.get("tr") or []
    if not blocos_doc:
        return
    requisitos = _blocos_da_clausula_por_titulo(blocos_doc, ("REQUISITOS",))
    if not requisitos:
        return
    verificacao = " ".join(
        b["conteudo"] for b in
        _blocos_da_clausula_por_titulo(blocos_doc, _TITULOS_VERIFICACAO))
    if not verificacao.strip():
        return
    verificacao_norm = _normalizar(verificacao)
    vistos: set[str] = set()
    for bloco in requisitos:
        for achado in _RE_REQUISITO_VERIFICAVEL.finditer(bloco["conteudo"]):
            termo = " ".join(achado.group(0).split())
            chave = _normalizar(termo)
            if chave in vistos or len(chave) < 8:
                continue
            vistos.add(chave)
            # o requisito é retomado se o termo (ou seu núcleo) reaparece
            nucleo = " ".join(chave.split()[:3])
            if nucleo and nucleo in verificacao_norm:
                continue
            achados_out.append(_finding(
                contador(), "tr", "requisito_nao_operacionalizavel", "LOW",
                f"requisito verificável sem operacionalização: '{termo}' é "
                "exigido, mas não aparece nas cláusulas de execução, "
                "fiscalização, recebimento/aceitação ou habilitação",
                bloco["conteudo"][:160],
                "Indicar o documento comprobatório, o momento da "
                "verificação, o responsável e a consequência da não "
                "conformidade.",
                False, [], ["documento:tr"],
                bloqueio="DISCRETIONARY_DECISION"))


def _normalizar(texto: str) -> str:
    """Minúsculo, sem acento e SEM pontuação — 'INMETRO.' casa com
    'INMETRO de cada equipamento'."""
    import unicodedata

    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^0-9a-z\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def verificar(fatos: list[dict],
              documentos: dict[str, str]) -> list[dict]:
    """Achados de consistência (formato v4) — função pura."""
    from . import conhecimento

    contexto = conhecimento.contexto_dos_fatos(fatos)
    docs = {k: v for k, v in (documentos or {}).items()
            if (v or "").strip()}
    if not contexto or not docs:
        return []
    por_doc = {k: blocos.dividir_em_blocos(k, v) for k, v in docs.items()}
    achados_out: list[dict] = []
    sequencia = iter(range(1, 1000))

    def contador() -> int:
        return next(sequencia)

    _verificar_calculo(contexto, achados_out, contador)
    _verificar_pesquisa_aplicada(contexto, achados_out, contador)
    _verificar_valor_global(contexto, por_doc, achados_out, contador)
    _verificar_quantidades(contexto, por_doc, achados_out, contador)
    _verificar_prazo(por_doc, achados_out, contador)
    _verificar_objeto(contexto, por_doc, achados_out, contador)
    # P1: coerência das DECISÕES ao longo da cadeia e requisitos que
    # precisam ser verificáveis na execução
    _verificar_decisoes(contexto, docs, por_doc, achados_out, contador)
    _verificar_srp_contra_fato(contexto, docs, achados_out, contador)
    _verificar_requisitos_operacionalizaveis(por_doc, achados_out, contador)
    return achados_out


# ---------------------------------------------------------------------------
# Integração com a auditoria v4 (achados.gerar_relatorio chama aqui)
# ---------------------------------------------------------------------------
def verificar_para_processo(documentos: dict[str, str],
                            processo_id: str | None) -> list[dict]:
    """
    Fatos do banco quando existem (inclui confirmações); senão, extração
    determinística do formulário da sessão. Sem flag, lista vazia.
    """
    if not ativa():
        return []
    lista_fatos: list[dict] = []
    if db.disponivel() and processo_id:
        try:
            lista_fatos = db.listar_fatos(processo_id)
        except db.ErroBanco:
            lista_fatos = []
    if not lista_fatos:
        import streamlit as st

        from . import fatos as fatos_mod

        dados = st.session_state.get("dados") or {}
        lista_fatos = fatos_mod.extrair_do_formulario(dados, processo_id)
    return verificar(lista_fatos, documentos)
