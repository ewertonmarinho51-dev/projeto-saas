"""Modelo documental fornecido pelo órgão, sem escala numérica inventada.

Não há banco, chamada de IA ou decisão jurídica neste módulo. As avaliações
são qualitativas e independentes; lacunas continuam visíveis para revisão.
"""
from __future__ import annotations

import re
import unicodedata

MODELO_VERSAO = "pdf-fornecido-v1.1"
INSTRUCOES = """Elabore o MAPA DE RISCOS da contratação, conforme o art. 18, X,
da Lei nº 14.133/2021, usando o ETP aprovado, DFD e fatos do processo.
Siga EXATAMENTE esta estrutura documental do modelo fornecido:
# MAPA DE RISCOS
| IDENTIFICAÇÃO DA NECESSIDADE DA CONTRATAÇÃO |
|---|
| Parágrafo com necessidade, objeto e abrangência da análise. |

| FASE DE ANÁLISE |
|---|
| Uma fase pertinente por linha. |
## RISCO 01
Descrição objetiva do evento (a causa pode ser explicada na descrição).
| Avaliação | Baixa | Média | Alta |
|---|---|---|---|
| Probabilidade: | | | |
| Impacto: | | | |
Marque X em UMA opção por linha somente quando houver base técnica.
| Id | Dano |
|---|---|
| 1. | Consequência potencial pertinente ao evento. |
| Id | Ação Preventiva | Responsável |
|---|---|---|
| 1. | Providência concreta ligada ao evento. | Unidade/função com base no processo. |
| Id | Ação de Contingência | Responsável |
|---|---|---|
| 1. | Providência concreta diante do evento. | Unidade/função com base no processo. |
Repita RISCO 02 etc. conforme os riscos pertinentes, sem quantidade fixa.
Feche com local e data efetivos, Elaborado por:, linha de assinatura, nome e
matrícula quando informados. Ausências: [PREENCHER: informação específica].
Preserve Baixa/Média/Alta inclusive na linha Impacto. NÃO crie códigos, notas,
P x I, nível global, tabela-resumo, risco residual ou colunas adicionais.
Não copie fatos, marcas, municípios, datas, nomes, avaliações ou os sete riscos
do exemplo. Não invente responsáveis nominais, prazos ou controles implementados.
Sem base para avaliar: mantenha a marcação em branco e explique a pendência na
descrição do risco. Distinga hipótese de fato. Não declare legalidade integral.
Este mapa NÃO substitui a matriz contratual de alocação de riscos. Não reproduza
a planilha orçamentária neste documento. Não inclua instruções de elaboração no
corpo final. O resultado é uma minuta sujeita à revisão humana."""


def _normalizar(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower())
                   if unicodedata.category(c) != "Mn").replace("*", "")


def minuta_demo(dados: dict) -> str:
    """Esqueleto explicitamente demo; não simula avaliação técnica aprovada."""
    objeto = (dados.get("objeto") or "[PREENCHER: objeto]").replace("|", "\\|").replace("\n", "<br>")
    risco = dados.get("riscos") or "[PREENCHER: evento de risco pertinente ao objeto]"
    return (
        "# MAPA DE RISCOS\n\n"
        "Minuta de demonstração. Avaliações e responsabilidades aguardam revisão.\n\n"
        "| IDENTIFICAÇÃO DA NECESSIDADE DA CONTRATAÇÃO |\n|---|\n"
        f"| {objeto} |\n\n"
        "| FASE DE ANÁLISE |\n|---|\n"
        "| Planejamento da contratação |\n\n"
        f"## RISCO 01\n\n{risco}\n\n"
        "| Avaliação | Baixa | Média | Alta |\n|---|---|---|---|\n"
        "| Probabilidade: | | | |\n| Impacto: | | | |\n\n"
        "| Id | Dano |\n|---|---|\n| 1. | [PREENCHER: consequência potencial] |\n\n"
        "| Id | Ação Preventiva | Responsável |\n|---|---|---|\n"
        "| 1. | [PREENCHER: ação preventiva] | [PREENCHER: unidade responsável] |\n\n"
        "| Id | Ação de Contingência | Responsável |\n|---|---|---|\n"
        "| 1. | [PREENCHER: ação de contingência] | [PREENCHER: unidade responsável] |\n\n"
        "[PREENCHER: município e data]\n\nElaborado por:\n\n"
        "________________________________________\n\n"
        "[PREENCHER: elaborador]\n\nMatrícula: [PREENCHER: matrícula]\n"
    )


def validar(texto: str) -> list[dict]:
    """Achados documentais, sem transformar avaliação de risco em veto legal."""
    achados = []

    def aviso(mensagem, trecho=""):
        achados.append({"doc": "mapa_riscos", "documento": "Mapa de Riscos", "gravidade": "aviso",
                        "mensagem": mensagem, "trecho": trecho[:300]})

    normal = _normalizar(texto)
    for titulo in ("identificacao da necessidade da contratacao", "fase de analise"):
        if titulo not in normal:
            aviso(f"Mapa de Riscos sem {titulo}.")
    partes = re.split(r"(?im)^\s*(?:#{1,6}\s*|\*\*)?risco\s+(\d+)\b[^\n]*", normal)
    if len(partes) < 3:
        aviso("Mapa de Riscos sem blocos de risco identificados.")
        return achados
    for numero, bloco in zip(partes[1::2], partes[2::2]):
        for campo in ("dano", "acao preventiva", "acao de contingencia"):
            if campo not in bloco:
                aviso(f"Risco {numero} sem {campo}.", f"RISCO {numero}")
        for campo in ("probabilidade", "impacto"):
            linha = next((ln for ln in bloco.splitlines() if campo in ln), "")
            marcacoes = re.findall(r"(?:\[\s*x\s*\]|(?<=\|)\s*x\s*(?=\|))", linha)
            if len(marcacoes) != 1:
                aviso(f"Risco {numero}: {campo} requer uma avaliação fundamentada.", linha)
        # Examina as tabelas de ações, não apenas a presença do cabeçalho.
        tabela = None
        linhas_uteis = {"preventiva": 0, "contingencia": 0}
        for ln in bloco.splitlines():
            celulas = [c.strip() for c in re.split(r"(?<!\\)\|", ln.strip().strip("|"))]
            if len(celulas) >= 2 and celulas[1] == "acao preventiva":
                tabela = "preventiva"
            elif len(celulas) >= 2 and celulas[1] == "acao de contingencia":
                tabela = "contingencia"
            elif ln.strip().startswith("|") and tabela and re.search(r"\|\s*\d+\.?\s*\|", ln):
                celulas = [c.strip() for c in re.split(r"(?<!\\)\|", ln.strip().strip("|"))]
                if len(celulas) >= 3:
                    acao, responsavel = celulas[1:3]
                    if not acao or "[preencher" in acao:
                        aviso(f"Risco {numero} sem tratamento de {tabela} definido.", ln)
                    else:
                        linhas_uteis[tabela] += 1
                    if not responsavel or "[preencher" in responsavel:
                        aviso(f"Risco {numero} com responsável ausente na ação {tabela}.", ln)
        for tipo, quantidade in linhas_uteis.items():
            if quantidade == 0:
                aviso(f"Risco {numero} requer ação {tipo} vinculada ao evento.", f"RISCO {numero}")
    return achados
