"""Alertas determinísticos e efêmeros no bucket isolado já existente do GovBot."""
from __future__ import annotations

import hashlib
import json

from . import achados, consistencia, fatos, validacao, governanca
from .config import CAMPOS_FORMULARIO

ESTADOS = {"NOVO", "VISTO", "ADIADO", "RESOLVIDO", "OBSOLETO"}
ATIVOS = {"NOVO", "VISTO", "ADIADO"}


def _hash(valor):
    return hashlib.sha256(json.dumps(valor, ensure_ascii=False, sort_keys=True,
                                     default=str).encode()).hexdigest()


def avaliar(sessao, bucket):
    """Reavalia só quando as fontes mudam; não consulta IA ou banco."""
    dados = dict(sessao.get("dados") or {})
    docs = {**(sessao.get("documentos") or {}), **(sessao.get("edicoes_pendentes") or {})}
    obsoletos = sessao.get("_documentos_obsoletos") or {}
    contexto_hash = governanca.hash_canonico({"dados": dados, "docs": docs, "proc": sessao.get("processo_id")})
    def cache_atual(chave, campo, versao="chave"):
        cache = sessao.get(chave) or {}
        return (cache.get(campo) or {}) if cache.get(versao) == contexto_hash else {}
    decisao = cache_atual("_decisao_cache", "decisao", "context_hash")
    fatos_cache = cache_atual("_fatos_cache", "resultado")
    qualidade = cache_atual("_score_cache", "resultado")
    versao = _hash([dados, docs, obsoletos, decisao, fatos_cache, qualidade])
    cache = bucket.setdefault("alertas", {"versao": None, "itens": {}})
    if cache["versao"] == versao:
        return ordenar(cache["itens"].values())
    encontrados = []
    for campo, meta in CAMPOS_FORMULARIO.items():
        if meta.get("obrigatorio") and not dados.get(campo):
            encontrados.append({"documentId": "formulario", "campo": campo,
                "severity": "aviso", "regraViolada": f"campo:{campo}",
                "descricao": f"Preencha {meta.get('rotulo_tela') or meta['rotulo']}.",
                "evidencia": [], "resultadoEsperado": "Informe o dado real da demanda."})
    encontrados.extend(achados.estruturar(validacao.validar_todos(docs, dados=dados), docs))
    encontrados.extend(consistencia.verificar(fatos.extrair_do_formulario(dados, sessao.get("processo_id")), docs))
    for fato in fatos_cache.get("fatos", []):
        if fato.get("status") == "extraido":
            encontrados.append({"documentId": "formulario", "severity": "MEDIUM",
                "regraViolada": "fato_nao_confirmado", "categoria": "fatos",
                "descricao": f"Confirme o fato {fato.get('path', '')} na revisão do processo.",
                "evidencia": [str(fato.get("valor", ""))], "resultadoEsperado": "Confirmação humana do dado de origem."})
    for critico in qualidade.get("criticos", []):
        encontrados.append({"documentId": "formulario", "severity": "CRITICAL",
            "regraViolada": "qualidade", "categoria": "qualidade",
            "descricao": str(critico), "evidencia": [],
            "resultadoEsperado": "Revise o apontamento objetivo do motor de qualidade."})
    from .precos.aplicacao import CHAVE_PROVENIENCIA
    proveniencia = dados.get(CHAVE_PROVENIENCIA) or {}
    for sinal in proveniencia.get("sinais_estatisticos", []):
        encontrados.append({"documentId": "formulario", "campo": "itens", "severity": "MEDIUM",
            "regraViolada": "preco_discrepante", "categoria": "pesquisa_precos",
            "descricao": f"Item {sinal['item']}: {sinal['quantidade']} referência(s) discrepante(s) na pesquisa aplicada.",
            "evidencia": list(sinal["criterios"]),
            "resultadoEsperado": "Confira a análise e a justificativa no módulo de preços. Sinal estatístico não determina ilegalidade nem sobrepreço."})
    for doc, origem in obsoletos.items():
        encontrados.append({"documentId": doc, "severity": "aviso",
            "regraViolada": "documento_obsoleto", "descricao": f"Refaça este documento após a alteração de {origem}.",
            "evidencia": [], "resultadoEsperado": "Revise a cadeia documental antes da emissão."})
    resultado = decisao.get("resultado") or {}
    for item in resultado.get("bloqueios", []):
        encontrados.append({"documentId": "formulario", "severity": "critica",
            "regraViolada": item.get("regra", "conhecimento"), "descricao": item.get("motivo", "Revise a decisão do processo."),
            "evidencia": [], "resultadoEsperado": "Atenda à pendência registrada pelo motor de conhecimento."})
    atuais = set()
    for item in encontrados:
        alvo = item.get("documentId", "formulario")
        fingerprint = _hash([alvo, item.get("campo"), item.get("regraViolada"),
                             item.get("descricao"), item.get("evidencia")])
        atuais.add(fingerprint)
        anterior = cache["itens"].get(fingerprint, {})
        estado = anterior.get("estado", "NOVO")
        if estado in {"RESOLVIDO", "OBSOLETO"}:
            estado = "NOVO"
        gravidade = str(item.get("severity", "MEDIUM")).upper()
        nivel = "CRITICO" if gravidade in {"CRITICAL", "HIGH", "CRITICA", "BLOQUEIA"} else "INFO" if gravidade == "LOW" else "ATENCAO"
        cache["itens"][fingerprint] = {**item, "id": fingerprint, "estado": estado,
            "status": estado, "fingerprint": fingerprint, "context_version": versao,
            "gravidade": nivel, "titulo": item["descricao"][:100],
            "mensagem_curta": item["descricao"], "documento": alvo,
            "categoria": item.get("categoria", "dados_do_processo"),
            "bloco": next(iter(item.get("allowedPaths") or []), None),
            "origem": "consistencia" if str(item.get("findingId", "")).startswith("C") else item.get("categoria", "validacao"),
            "evidencias": item.get("evidencia", []),
            "acao_sugerida": item.get("resultadoEsperado", "Revise o apontamento."),
            "auto_corrigivel": bool(item.get("autoCorrectable"))}
    for fingerprint, item in cache["itens"].items():
        if fingerprint not in atuais and item["estado"] in ATIVOS:
            doc = item.get("documentId")
            item["estado"] = "OBSOLETO" if doc != "formulario" and doc not in docs else "RESOLVIDO"
            item["status"] = item["estado"]
    cache["versao"] = versao
    # Histórico limitado por processo, sem eliminar os alertas atuais.
    encerrados = [k for k,v in cache["itens"].items() if v["estado"] not in ATIVOS]
    for k in encerrados[:-100]:
        cache["itens"].pop(k)
    return ordenar(cache["itens"].values())


def ordenar(itens):
    ordem = {"critica": 0, "critico": 0, "critical": 0, "bloqueia": 0,
             "alta": 1, "high": 1, "erro": 1, "aviso": 2, "medium": 2, "low": 3}
    return sorted(itens, key=lambda a: (a["estado"] not in ATIVOS,
                  ordem.get(str(a.get("severity", "")).lower(), 2), a.get("documentId", ""), a["id"]))


def marcar(bucket, identificador, estado):
    if estado not in {"VISTO", "ADIADO"}:
        raise ValueError("Estado de alerta não permitido")
    item = bucket.get("alertas", {}).get("itens", {}).get(identificador)
    if item is None or item["estado"] not in ATIVOS:
        raise ValueError("Alerta não existe ou está desatualizado")
    item["estado"] = estado
    item["status"] = estado
    return item
