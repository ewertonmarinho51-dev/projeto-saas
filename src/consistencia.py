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
              "consistencia_objeto")

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
    _verificar_valor_global(contexto, por_doc, achados_out, contador)
    _verificar_quantidades(contexto, por_doc, achados_out, contador)
    _verificar_prazo(por_doc, achados_out, contador)
    _verificar_objeto(contexto, por_doc, achados_out, contador)
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
