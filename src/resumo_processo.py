"""
Contexto canônico do processo — o que o próximo documento precisa saber.

O DEFEITO QUE ESTE MÓDULO CORRIGE

Até aqui, `state.contexto_para_documento` mandava para o modelo a CADEIA
INTEIRA de documentos aprovados, texto integral, incluindo a tabela de
itens que o próprio sistema injeta por código. Medido com o tokenizador
do provedor (ver `docs/custo/antes.json`), num processo de 210 itens isso
dava 84.828 dos 119.940 tokens de entrada de um processo — 71% da conta,
e a maior parte dela era a mesma tabela viajando três vezes.

O que este módulo faz é o contrário disso: seleciona, por documento de
destino, as CLÁUSULAS que carregam decisão, e deixa de fora:

  * as TABELAS. A tabela de itens é determinística: nasce da planilha,
    é injetada por `planilha.injetar_tabela` e conferida item a item por
    `validacao`. Mandá-la ao modelo como contexto não acrescenta um fato
    que ele possa usar — os números que ele pode citar já chegam
    calculados no bloco do formulário;
  * as cláusulas que o documento seguinte REFAZ por conta própria
    (dimensionamento, equipe de planejamento, considerações finais);
  * as cláusulas cujo conteúdo já vem do formulário (previsão no PCA,
    informações básicas).

O QUE NÃO PODE ACONTECER, E COMO SE IMPEDE

Perder uma decisão. O TR que não souber qual solução o ETP escolheu vai
escolher outra, e aí a cadeia mente. Três defesas:

  1. o mapa `PRECISA_DE` é DECLARADO, cláusula por cláusula, com o
     motivo de cada inclusão escrito ao lado. Não é heurística;
  2. se o documento não trouxer as cláusulas esperadas — numeração
     diferente, documento importado, texto editado à mão —, o módulo
     NÃO advinha: devolve o documento inteiro (sem as tabelas). Contexto
     demais custa dinheiro; contexto de menos custa a decisão;
  3. `tests/test_resumo_processo.py` confere que cada decisão que o
     próximo documento precisa herdar continua atravessando.

Feature flag `contexto_canonico` (config_app). DESLIGADA, o contexto é
byte a byte o de antes.
"""

from __future__ import annotations

import re

from . import blocos, db, perfis

FLAG = "contexto_canonico"

# Versão do formato. Entra na chave do cache: mudar a seleção de
# cláusulas muda o prompt, e um cache que não soubesse disso devolveria
# documento montado com o contexto antigo.
VERSAO = 2


# ---------------------------------------------------------------------------
# O que cada documento precisa herdar — DECLARADO, com o motivo.
#
# Chave: documento a gerar. Valor: {documento anterior: (cláusulas,)}.
# Cláusula ausente do mapa é cláusula deliberadamente não enviada.
# ---------------------------------------------------------------------------
PRECISA_DE: dict[str, dict[str, tuple[int, ...]]] = {
    # O ETP parte da necessidade formalizada e TESTA a solução proposta.
    #   2 justificativa · 3 necessidade · 4 solução proposta · 8 período
    # Fora: 1 (informações gerais, iguais às do formulário), 5 e 7 (as
    # duas cláusulas de tabela), 6 (dimensionamento — o ETP refaz ao
    # descrever a solução), 9 (equipe de planejamento: nome de agente
    # não se herda, é [PREENCHER]).
    "etp": {"dfd": (2, 3, 4, 8)},

    # O Mapa analisa risco das decisões do ETP.
    #   2 necessidade · 4 requisitos · 6 solução escolhida ·
    #   9 análise de riscos · 10 parcelamento · 13 providências
    "mapa_riscos": {"etp": (2, 4, 6, 9, 10, 13)},

    # O TR OPERACIONALIZA o que o ETP decidiu.
    #   2 necessidade · 4 requisitos · 6 solução escolhida ·
    #   7 quantitativo (prosa; a tabela sai) · 8 valor (idem) ·
    #   9 riscos · 10 parcelamento · 12 resultados ·
    #   15 posicionamento conclusivo · 17 renovação (só SRP)
    # Fora, e a maior economia do mapa: 5 LEVANTAMENTO DE SOLUÇÕES, de
    # 10 a 35 blocos. É a comparação entre alternativas que levou à
    # escolha — o TR não reabre a escolha, herda a da cláusula 6.
    # Reabrir seria o defeito que a instrução do TR proíbe.
    "tr": {"etp": (2, 4, 6, 7, 8, 9, 10, 12, 15, 17),
           # O mapa é quase todo tabela de risco; o que o TR aproveita
           # são as ações. Sem seleção de cláusula: o documento é curto
           # e a estrutura dele não segue os perfis.
           "mapa_riscos": ()},

    # O edital e a ARP não passam por modelo nenhum (montados do
    # catálogo de cláusulas). Ficam aqui para que a ausência seja
    # explícita e não pareça esquecimento.
    "edital": {},
    "arp": {},
}

_RE_CLAUSULA = re.compile(r"(?m)^#{1,3}\s*(\d{1,2})\s*[\.\-–]?\s+(.+?)\s*$")

# Proporção mínima das cláusulas pedidas que precisa ser encontrada para
# a seleção valer. Abaixo disso o documento não segue os perfis e a
# seleção por número seria recorte às cegas.
COBERTURA_MINIMA = 0.6


def ativo() -> bool:
    """Flag ligada? Desligada, o chamador mantém o contexto integral."""
    try:
        return db.flag_ativa(FLAG)
    except Exception:  # noqa: BLE001 — banco fora não muda o prompt
        return False


def sem_tabelas(texto: str) -> str:
    """
    O documento sem as linhas de tabela Markdown.

    A tabela de itens é injetada por código a partir da planilha e
    conferida contra ela. No prompt do documento seguinte ela é peso
    morto: o modelo não pode alterá-la e os números que ele pode citar
    chegam pelo bloco do formulário, já calculados.

    Onde havia tabela fica uma linha dizendo que havia — sem isso, o
    modelo leria uma cláusula de quantitativo sem quantitativo algum e
    poderia concluir que o dado não existe.
    """
    saida: list[str] = []
    linhas_de_tabela = 0
    em_branco: list[str] = []      # linhas vazias DENTRO de uma tabela

    def descarregar() -> None:
        nonlocal linhas_de_tabela, em_branco
        if linhas_de_tabela:
            saida.append(
                f"[tabela de {linhas_de_tabela} linhas omitida — montada "
                "por código a partir da planilha; os totais estão no bloco "
                "do formulário]")
        else:
            saida.extend(em_branco)
        linhas_de_tabela = 0
        em_branco = []

    for linha in (texto or "").splitlines():
        if linha.lstrip().startswith("|"):
            # Linha em branco entre duas linhas de tabela não encerra a
            # tabela. Sem isto, um documento com a tabela separada por
            # linhas vazias ganhava um aviso de omissão POR LINHA — e o
            # contexto "reduzido" saía maior que o original.
            em_branco = []
            linhas_de_tabela += 1
            continue
        if linhas_de_tabela and not linha.strip():
            em_branco.append(linha)
            continue
        descarregar()
        saida.append(linha)
    descarregar()
    return "\n".join(saida).strip()


def _clausulas_do_texto(texto: str) -> dict[int, str]:
    """{número: texto da cláusula} — só a PRIMEIRA ocorrência de cada."""
    achados = list(_RE_CLAUSULA.finditer(texto or ""))
    resultado: dict[int, str] = {}
    for i, m in enumerate(achados):
        numero = int(m.group(1))
        if numero in resultado:
            continue      # cláusula repetida: a primeira é a legítima
        fim = achados[i + 1].start() if i + 1 < len(achados) else len(texto)
        resultado[numero] = texto[m.start():fim].strip()
    return resultado


def _titulos_conferem(doc_key: str, clausulas: dict[int, str]) -> bool:
    """
    A numeração do documento corresponde à dos perfis?

    Sem esta conferência, recortar "a cláusula 6" de um documento
    renumerado entregaria o texto errado com a etiqueta certa — que é
    pior do que mandar o documento inteiro.
    """
    perfil = perfis.PERFIS.get(doc_key)
    if not perfil:
        return False
    esperados = {c["n"]: c["titulo"] for c in perfil["clausulas"]}
    conferidos = acertos = 0
    for numero, texto in clausulas.items():
        esperado = esperados.get(numero)
        if not esperado:
            continue
        conferidos += 1
        primeira_linha = texto.splitlines()[0].upper()
        # Casa pelas três primeiras palavras significativas do título:
        # "DESCRIÇÃO DOS REQUISITOS DA CONTRATAÇÃO" continua casando se
        # o modelo escrever "DESCRIÇÃO DOS REQUISITOS".
        palavras = [p for p in esperado.split() if len(p) > 3][:3]
        if palavras and all(p in primeira_linha for p in palavras):
            acertos += 1
    return conferidos > 0 and acertos / conferidos >= COBERTURA_MINIMA


def extrair(doc_origem: str, texto: str, pedidas: tuple[int, ...]) -> tuple[str, str]:
    """
    (texto do contexto, modo). Modo é 'clausulas' quando a seleção
    valeu e 'integral' quando o módulo se recusou a recortar.

    Devolver o motivo junto do texto é o que permite ao rastro dizer
    depois POR QUE aquele processo mandou o documento inteiro — em vez
    de o operador descobrir pela fatura.
    """
    limpo = sem_tabelas(texto)
    if not pedidas:
        return limpo, "integral"
    clausulas = _clausulas_do_texto(limpo)
    if not clausulas or not _titulos_conferem(doc_origem, clausulas):
        return limpo, "integral"
    encontradas = [n for n in pedidas if n in clausulas]
    # Cláusula condicional (SRP) legitimamente ausente não conta contra
    # a cobertura: exigir todas faria todo processo sem registro de
    # preços cair no documento integral.
    obrigatorias = {c["n"] for c in perfis.PERFIS[doc_origem]["clausulas"]
                    if c["obrigatoria"]}
    exigidas = [n for n in pedidas if n in obrigatorias]
    faltando = [n for n in exigidas if n not in clausulas]
    if faltando:
        return limpo, "integral"
    if not encontradas:
        return limpo, "integral"
    return "\n\n".join(clausulas[n] for n in encontradas), "clausulas"


def contexto_canonico(aprovados: dict[str, str], doc_key: str) -> str | None:
    """
    O contexto do próximo documento: só as decisões que ele herda.

    `aprovados` é {documento: texto} apenas do que o servidor APROVOU —
    rascunho pendente nunca vira fonte, que é a regra do
    `state.contexto_para_documento` e continua valendo aqui.
    """
    from .config import DOCUMENTOS

    mapa = PRECISA_DE.get(doc_key)
    if mapa is None:      # documento fora do encadeamento conhecido
        return _integral(aprovados)
    partes: list[str] = []
    for origem, pedidas in mapa.items():
        texto = (aprovados.get(origem) or "").strip()
        if not texto:
            continue
        recorte, modo = extrair(origem, texto, pedidas)
        if not recorte:
            continue
        titulo = DOCUMENTOS[origem]["titulo"]
        cabecalho = (
            f"=== {titulo} aprovado — DECISÕES HERDADAS ==="
            if modo == "clausulas" else
            f"=== {titulo} aprovado (íntegra, sem as tabelas) ===")
        partes.append(cabecalho + "\n" + recorte)
    if not partes:
        return None
    return (
        "=== CONTEXTO DO PROCESSO — CADEIA APROVADA ===\n"
        "Abaixo estão as decisões já tomadas e aprovadas neste processo. "
        "Elas são VINCULANTES: expresse o conteúdo delas como seu, sem "
        "remeter à numeração de outro documento, e não reabra o que já "
        "foi decidido. O que não estiver aqui não foi decidido — não o "
        "invente.\n\n" + "\n\n".join(partes))


def _integral(aprovados: dict[str, str]) -> str | None:
    from .config import DOCUMENTOS

    partes = [f"=== {DOCUMENTOS[d]['titulo']} aprovado ===\n{sem_tabelas(t)}"
              for d, t in aprovados.items() if (t or "").strip()]
    return "\n\n".join(partes) or None


def como_era(aprovados: dict[str, str]) -> str | None:
    """
    O contexto do jeito ANTIGO — cadeia inteira, tabelas e tudo.

    Fica aqui, e não só no histórico do Git, porque é a referência com
    que a economia de cada geração é medida no registro de consumo. Uma
    economia comparada contra um número que ninguém pode recalcular não
    é medição.
    """
    from .config import DOCUMENTOS

    partes = [f"=== {DOCUMENTOS[d]['titulo']} aprovado ===\n{t}"
              for d, t in aprovados.items() if (t or "").strip()]
    return "\n\n".join(partes) or None


def economia(aprovados: dict[str, str], doc_key: str) -> dict:
    """
    Caracteres do contexto antigo × do canônico, para o rastro.

    Existe para que a economia apareça no registro de consumo de cada
    geração, e não apenas num relatório feito uma vez.
    """
    antigo = como_era(aprovados) or ""
    canonico = contexto_canonico(aprovados, doc_key) or ""
    return {"caracteres_antes": len(antigo),
            "caracteres_depois": len(canonico)}
