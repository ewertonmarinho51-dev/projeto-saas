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
