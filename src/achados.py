"""
Findings estruturados da revisão (Etapa 1 do ciclo de correção
automática — pacote_correcao_automatica_documentos_v1).

Envolve o revisor determinístico existente (validacao.py — PRESERVADO,
nenhuma linha alterada) e converte cada achado no formato audit-report:
documento, caminho, erro, gravidade, evidência, regra violada, resultado
esperado, fontes, caminhos permitidos/bloqueados e se a correção pode
ser automática. O auditor NÃO altera documentos — só lê e classifica.

Feature flag `flag_achados_estruturados` (config_app, default OFF):
  - DESLIGADA: a tela final fica exatamente como antes; o relatório é
    calculado em SHADOW MODE (apenas log), como na Fase 2.
  - LIGADA: o relatório estruturado aparece na tela final e alimenta o
    corretor (Etapas 3+). O fluxo de emissão NÃO muda nesta etapa.
"""

import logging
import re
import uuid
from datetime import datetime, timezone

from . import blocos, db, perfis, validacao

FLAG_ACHADOS = "achados_estruturados"

_log = logging.getLogger("govdocs.achados")

# Motivos de bloqueio que exigem intervenção humana (04_limites_e_excecoes)
MOTIVO_DADO_AUSENTE = "MISSING_REQUIRED_DATA"
MOTIVO_DISCRICIONARIO = "DISCRETIONARY_DECISION"

_RE_PREENCHER = re.compile(r"\[PREENCHER:?\s*([^\]]*)\]", re.IGNORECASE)
_RE_CLAUSULA_AUSENTE = re.compile(r"ausente:\s*(\d{1,2})\.")

# Classificação por prefixo da mensagem do validador (validacao.py).
# Campos: categoria, regra violada, resultado esperado, corrigível
# automaticamente, gravidade e (opcional) motivo de bloqueio.
_CLASSIFICACAO: list[tuple[str, dict]] = [
    ("campo pendente [PREENCHER]", {
        "categoria": "dado_pendente",
        "regra": "Nenhum campo pendente pode chegar ao documento final "
                 "(a emissão é bloqueada enquanto existir [PREENCHER]).",
        "esperado": "Campo preenchido com a informação real do processo, "
                    "fornecida pelo requisitante.",
        "auto": False,
        "gravidade": "HIGH",
        "bloqueio": MOTIVO_DADO_AUSENTE,
    }),
    ("marcador interno de tabela", {
        "categoria": "marcador_interno",
        "regra": "Marcadores internos ([[TABELA_ITENS]]) devem ser "
                 "substituídos pela tabela da planilha orçamentária.",
        "esperado": "Tabela de itens renderizada a partir do formulário.",
        "auto": True,
        "gravidade": "HIGH",
        "fontes": ["formulario:itens"],
    }),
    ("texto 'placeholder'", {
        "categoria": "texto_placeholder",
        "regra": "Texto provisório não pode constar do documento final.",
        "esperado": "Trecho reescrito com o conteúdo real, restrito ao "
                    "bloco apontado.",
        "auto": True,
        "gravidade": "HIGH",
    }),
    ("menção ao formulário interno", {
        "categoria": "vazamento_mecanica_interna",
        "regra": "O documento final não pode expor a mecânica interna do "
                 "sistema (formulário, prompts, base de conhecimento, IA).",
        "esperado": "Frase reescrita em linguagem institucional, sem "
                    "referência ao sistema.",
        "auto": True,
        "gravidade": "HIGH",
    }),
    ("menção à IA/modelo de linguagem", {
        "categoria": "vazamento_mecanica_interna",
        "regra": "O documento final não pode expor a mecânica interna do "
                 "sistema (formulário, prompts, base de conhecimento, IA).",
        "esperado": "Frase reescrita em linguagem institucional, sem "
                    "referência ao sistema.",
        "auto": True,
        "gravidade": "HIGH",
    }),
    ("menção a prompt do sistema", {
        "categoria": "vazamento_mecanica_interna",
        "regra": "O documento final não pode expor a mecânica interna do "
                 "sistema (formulário, prompts, base de conhecimento, IA).",
        "esperado": "Frase reescrita em linguagem institucional, sem "
                    "referência ao sistema.",
        "auto": True,
        "gravidade": "HIGH",
    }),
    ("menção à base interna do sistema", {
        "categoria": "vazamento_mecanica_interna",
        "regra": "O documento final não pode expor a mecânica interna do "
                 "sistema (formulário, prompts, base de conhecimento, IA).",
        "esperado": "Frase reescrita em linguagem institucional, sem "
                    "referência ao sistema.",
        "auto": True,
        "gravidade": "HIGH",
    }),
    ("numeração de cláusula duplicada", {
        "categoria": "numeracao",
        "regra": "A numeração das cláusulas deve ser sequencial e única.",
        "esperado": "Cláusulas renumeradas em sequência, sem alterar o "
                    "conteúdo.",
        "auto": True,
        "gravidade": "MEDIUM",
    }),
    ("salto na numeração", {
        "categoria": "numeracao",
        "regra": "A numeração das cláusulas deve ser sequencial e única.",
        "esperado": "Cláusulas renumeradas em sequência, sem alterar o "
                    "conteúdo.",
        "auto": True,
        "gravidade": "MEDIUM",
    }),
    ("título de cláusula sem conteúdo", {
        "categoria": "clausula_vazia",
        "regra": "Toda cláusula do documento deve ter conteúdo próprio.",
        "esperado": "Cláusula redigida a partir do formulário e do perfil "
                    "do documento.",
        "auto": True,
        "gravidade": "MEDIUM",
        "fontes": ["formulario"],
    }),
    ("cláusula obrigatória possivelmente ausente", {
        "categoria": "clausula_obrigatoria_ausente",
        "regra": "Cláusulas obrigatórias do perfil (documentos aprovados) "
                 "devem estar presentes.",
        "esperado": "Cláusula obrigatória incluída na posição correta, "
                    "redigida a partir do formulário e do perfil.",
        "auto": True,
        "gravidade": "MEDIUM",
        "fontes": ["formulario"],
    }),
    ("documento raso", {
        "categoria": "profundidade",
        "regra": "O documento deve ter a profundidade de referência dos "
                 "documentos aprovados.",
        "esperado": "Complementação ou regeneração — decisão do revisor "
                    "humano (não é correção pontual).",
        "auto": False,
        "gravidade": "LOW",
        "bloqueio": MOTIVO_DISCRICIONARIO,
    }),
    ("tabela sem linha de cabeçalho", {
        "categoria": "tabela_malformada",
        "regra": "Toda tabela Markdown precisa da linha separadora de "
                 "cabeçalho para renderizar corretamente no DOCX/PDF.",
        "esperado": "Linha separadora inserida logo após o cabeçalho.",
        "auto": True,
        "gravidade": "LOW",
    }),
]

_PADRAO_DESCONHECIDO = {
    "categoria": "outros",
    "regra": "Regra de validação do documento final.",
    "esperado": "Ajuste conforme a mensagem do achado.",
    "auto": False,
    "gravidade": "MEDIUM",
}


def _classificar(mensagem: str) -> dict:
    for prefixo, regra in _CLASSIFICACAO:
        if mensagem.startswith(prefixo):
            return regra
    return _PADRAO_DESCONHECIDO


def caminhos_bloqueados(doc_key: str, blocos_doc: list[dict]) -> list[str]:
    """
    Caminhos que a IA nunca pode alterar:
      - cláusulas FIXED_LOCKED do perfil do documento (perfis.py);
      - cláusulas de assinatura/equipe pelo título (heurística que cobre
        documentos fora do perfil — quem assina não é decisão de máquina).
    """
    numeros: set[int] = {
        n for n, tipo in perfis.clausulas_fixas(doc_key).items()
        if tipo == "LOCKED"
    }
    for bloco in blocos_doc:
        if bloco["tipo"] != "titulo":
            continue
        titulo = bloco["conteudo"].upper()
        if "ASSINATURA" in titulo or "EQUIPE DE PLANEJAMENTO" in titulo:
            numeros.add(bloco["clausula"])
    bloqueados: list[str] = []
    for numero in sorted(numeros):
        bloqueados.extend(blocos.caminhos_da_clausula(blocos_doc, numero))
    return bloqueados


def _caminhos_permitidos(achado: dict, regra: dict,
                         blocos_doc: list[dict]) -> list[str]:
    """
    Escopo autorizado da correção. Sem escopo localizável não há
    correção automática segura — o chamador rebaixa `auto` para False.
    """
    doc = achado["doc"]
    if regra["categoria"] == "numeracao":
        return blocos.caminhos_de_titulos(blocos_doc)
    if regra["categoria"] == "clausula_obrigatoria_ausente":
        m = _RE_CLAUSULA_AUSENTE.search(achado["mensagem"])
        # caminho FUTURO da cláusula a inserir (operação `add`)
        return [f"{doc}/clausula/{m.group(1)}"] if m else []
    bloco = blocos.localizar_bloco(blocos_doc, achado.get("trecho", ""))
    return [bloco["path"]] if bloco else []


def _campos_requeridos(doc_key: str, texto: str) -> list[str]:
    """Descrições dos [PREENCHER: …] — o que pedir ao servidor."""
    return [
        (m.group(1).strip() or "informação pendente")
        for m in _RE_PREENCHER.finditer(texto or "")
    ]


def estruturar(achados_brutos: list[dict],
               documentos: dict[str, str]) -> list[dict]:
    """Converte os achados do validacao.py em findings estruturados."""
    por_doc = {k: blocos.dividir_em_blocos(k, v or "")
               for k, v in documentos.items()}
    findings = []
    for n, achado in enumerate(achados_brutos, start=1):
        regra = _classificar(achado["mensagem"])
        blocos_doc = por_doc.get(achado["doc"], [])
        permitidos = _caminhos_permitidos(achado, regra, blocos_doc)
        bloqueados = caminhos_bloqueados(achado["doc"], blocos_doc)
        permitidos = [p for p in permitidos if p not in bloqueados]
        auto = bool(regra["auto"] and permitidos)
        finding = {
            "findingId": f"F{n:03d}",
            "documentId": achado["doc"],
            "clauseId": None,
            "categoria": regra["categoria"],
            "severity": regra["gravidade"],
            "descricao": achado["mensagem"],
            "evidencia": [achado["trecho"]] if achado.get("trecho") else [],
            "regraViolada": regra["regra"],
            "resultadoEsperado": regra["esperado"],
            "autoCorrectable": auto,
            "allowedPaths": permitidos,
            "blockedPaths": bloqueados,
            "sourceIds": list(regra.get("fontes", [])),
            "blockingReason": regra.get("bloqueio") if not auto else None,
        }
        if regra["categoria"] == "dado_pendente":
            finding["camposRequeridos"] = _campos_requeridos(
                achado["doc"], documentos.get(achado["doc"], ""))
        findings.append(finding)
    return findings


def gerar_relatorio(documentos: dict[str, str],
                    processo_id: str | None = None,
                    versao: int = 1) -> dict:
    """
    Relatório de auditoria (audit-report) do bundle: roda o revisor
    determinístico existente e estrutura o resultado. Não altera nada.
    """
    brutos = validacao.validar_todos(documentos)
    findings = estruturar(brutos, documentos)
    # V5 Fase 5 (flag_process_consistency): consistência cruzada entre
    # fatos canônicos e documentos entra no MESMO relatório — o corretor
    # v4 corrige divergências usando o fato como fonte. Flag OFF: nada.
    from . import consistencia

    findings = findings + consistencia.verificar_para_processo(
        documentos, processo_id)
    if not findings:
        status = "APPROVED"
    elif any(f["blockingReason"] for f in findings):
        status = "BLOCKED"
    else:
        status = "CORRECTIONS_REQUIRED"
    corrigiveis = sum(1 for f in findings if f["autoCorrectable"])
    return {
        "auditId": uuid.uuid4().hex,
        "bundleId": processo_id or "sessao-local",
        "bundleVersion": versao,
        "bundleHash": blocos.hash_bundle(documentos),
        "status": status,
        "findings": findings,
        "summary": (
            f"{len(findings)} finding(s): {corrigiveis} corrigível(is) "
            f"automaticamente, {len(findings) - corrigiveis} exigindo "
            "intervenção humana." if findings
            else "Nenhum problema encontrado."
        ),
        "model": "validacao-deterministica",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Feature flag + shadow mode (mesmo padrão da Fase 2 / contexto.py)
# ---------------------------------------------------------------------------
def ativo() -> bool:
    return db.flag_ativa(FLAG_ACHADOS)


def relatorio_para_tela(documentos: dict[str, str],
                        processo_id: str | None = None) -> dict | None:
    """
    Flag LIGADA: relatório estruturado para exibição na tela final.
    Flag DESLIGADA: None (tela idêntica à anterior), registrando em log
    o que seria reportado — validação em produção antes do corte.
    """
    relatorio = gerar_relatorio(documentos, processo_id)
    if not ativo():
        _log.info(
            "shadow: auditoria estruturada status=%s findings=%d "
            "corrigiveis=%d",
            relatorio["status"], len(relatorio["findings"]),
            sum(1 for f in relatorio["findings"] if f["autoCorrectable"]),
        )
        return None
    return relatorio
