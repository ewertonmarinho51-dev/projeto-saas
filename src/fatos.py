"""
Fatos canônicos do processo (Fase 2 do pacote V5).

Extração DETERMINÍSTICA do Formulário Matriz para o registro canônico
(`fatos_canonicos`, migração 0009): objeto, natureza, SRP, execução,
prazo, valores e itens viram fatos versionados com fonte — a fonte da
verdade que os documentos passam a referenciar. Prosa (justificativa,
riscos, memorando) NÃO vira fato: fato é dado material.

Versionamento: mudou o valor no formulário ⇒ NOVA versão do fato
(status volta a 'extraido' — a confirmação anterior não vale para o
valor novo) e a versão anterior é marcada 'substituido'. Nada é
editado in-place (KQ-005).

Feature flag `flag_canonical_facts` (default OFF):
  - DESLIGADA: extração roda em SHADOW (log de fatos e divergências);
    nada persiste, nenhuma tela muda.
  - LIGADA: fatos sincronizados no banco e exibidos na tela final com
    pendências de confirmação e divergências documentais.
"""

import logging
import re

import streamlit as st

from . import blocos, db, governanca, planilha

_log = logging.getLogger("govdocs.fatos")

# Confiança dos fatos derivados: quem nasce de campo estruturado do
# formulário sustenta decisão vinculante; quem nasce de heurística sobre
# texto livre só sugere (o motor aplica o corte — ver conhecimento.py).
CONFIANCA_ESTRUTURADA = 0.85
CONFIANCA_HEURISTICA = 0.6

# Prefixo de fonte que marca o fato como INFERÊNCIA do sistema (e não
# informação prestada). É o que o motor observa para não transformar
# heurística em obrigação — ver conhecimento.py.
PREFIXO_INFERENCIA = "inferencia"

# Natureza do objeto: SÓ das opções de execução que a declaram. "SRP",
# "Entrega única" e "Entrega parcelada" são MODELAGEM/procedimento e
# servem a qualquer natureza — delas não se deduz nada. Sem base segura,
# nenhum fato é emitido (ausência ≠ BENS).
NATUREZA_POR_EXECUCAO = {
    "Obra / serviço de engenharia": "OBRAS_ENGENHARIA",
    "Serviço de execução continuada": "SERVICOS",
    "Serviço por escopo (execução única)": "SERVICOS",
}

# Natureza que a CATEGORIA do objeto permite inferir (heurística — herda
# a confiança baixa da categoria). TI_SOFTWARE fica de fora: licença de
# uso e SaaS ora são bem, ora serviço.
NATUREZA_POR_CATEGORIA = {
    "MATERIAL_CONSUMO": "BENS", "TI_EQUIPAMENTO": "BENS", "EPI": "BENS",
    "VEICULOS": "BENS", "MEDICAMENTOS": "BENS", "ALIMENTOS": "BENS",
    "OBRAS_ENGENHARIA": "OBRAS_ENGENHARIA",
}

# ---------------------------------------------------------------------------
# Vocabulário controlado da CATEGORIA do objeto (P1).
#
# As regras do motor de conhecimento precisam de um dado ESTRUTURADO para
# decidir cláusulas condicionais — jamais de um `if "software" in objeto`
# espalhado pelo prompt. A categoria é, portanto, extraída aqui como FATO
# (confiança baixa, status 'extraido' → confirmável pelo humano) a partir
# de EVIDÊNCIA ACUMULADA em vários campos do formulário, não de uma única
# ocorrência textual. Quando a evidência é fraca, nenhum fato é emitido —
# ausência de fato faz as regras condicionais NÃO dispararem (conservador).
# ---------------------------------------------------------------------------
CATEGORIAS_OBJETO: dict[str, tuple[str, ...]] = {
    "TI_SOFTWARE": ("software", "sistema de informacao", "licenca de uso",
                    "saas", "plataforma digital", "aplicativo", "nuvem",
                    "hospedagem", "assinatura de solucao", "erp"),
    "TI_EQUIPAMENTO": ("computador", "notebook", "servidor de rede",
                       "switch", "storage", "impressora", "monitor",
                       "nobreak", "scanner"),
    "EPI": ("equipamento de protecao", "epi", "luva de seguranca",
            "capacete", "protetor auricular", "bota de seguranca",
            "oculos de protecao"),
    "VEICULOS": ("veiculo", "automovel", "caminhao", "onibus",
                 "motocicleta", "ambulancia", "retroescavadeira"),
    "MEDICAMENTOS": ("medicamento", "farmaco", "insumo farmaceutico",
                     "material medico-hospitalar", "anvisa"),
    "ALIMENTOS": ("genero alimenticio", "merenda", "alimentacao escolar",
                  "cesta basica"),
    "MATERIAL_CONSUMO": ("material de expediente", "material de consumo",
                         "papel a4", "caneta", "grampeador", "almofada "
                         "para carimbo", "material de limpeza"),
    "OBRAS_ENGENHARIA": ("reforma", "construcao", "pavimentacao",
                         "obra de engenharia", "recuperacao de via"),
}

# Peso da evidência por campo: o objeto é a fonte primária da categoria.
_PESO_CAMPO = {"objeto": 3, "itens": 1, "requisitos": 1}
_EVIDENCIA_MINIMA = 3

# ---------------------------------------------------------------------------
# Fatos derivados são TRI-STATE: True (evidência positiva), False
# (o processo diz expressamente que não) e AUSENTE (não se sabe).
#
# Ausência de evidência NÃO é evidência de ausência: quando o processo
# nada diz, nenhum fato é emitido e as regras que dependem dele não
# disparam em nenhuma direção. Frases negativas ("não será exigida
# garantia") produzem o fato FALSE — nunca o positivo.
# ---------------------------------------------------------------------------
# Instituto de reajuste × repactuação: repactuação pressupõe serviço
# contínuo COM dedicação de mão de obra. A base é ESTRUTURADA (modelo de
# execução); o texto livre apenas complementa.
_TERMOS_MAO_DE_OBRA = ("dedicacao exclusiva", "mao de obra", "posto de "
                       "trabalho", "terceirizacao de pessoal")
# Garantia CONTRATUAL (arts. 96 a 98) — não confundir com garantia do
# produto/fabricante ("garantia de 12 meses do fabricante"), que é
# requisito técnico do objeto e NÃO exige garantia de execução.
_TERMOS_GARANTIA = ("garantia contratual", "garantia de execucao",
                    "caucao", "seguro-garantia", "fianca bancaria")
_TERMOS_AMOSTRA = ("amostra", "prova de conceito", "prototipo")

# Negação imediatamente antes do termo (até ~60 caracteres): "não será
# exigida garantia contratual", "dispensa-se a apresentação de amostra",
# "sem exigência de amostra", "fica dispensada a caução".
_RE_NEGACAO = re.compile(
    r"\b(nao\s+(?:sera|serao|se|ha|havera|e)\b[^.;]{0,60}?"
    r"|sem\s+(?:exigencia|necessidade|apresentacao)\s+de\s+[^.;]{0,40}?"
    r"|dispensa(?:-se|da|do|se)\b[^.;]{0,60}?"
    r"|fica\s+dispensad[ao]\b[^.;]{0,60}?"
    r"|inexig[ei]\w*\b[^.;]{0,40}?)$")


# ---------------------------------------------------------------------------
# Extração determinística (formulário → fatos)
# ---------------------------------------------------------------------------
def _sem_acento(texto) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def _texto_dos_campos(dados: dict) -> dict[str, str]:
    """Texto normalizado por campo de origem (para evidência ponderada)."""
    itens = " ".join(str(i.get("descricao") or "")
                     for i in (dados.get("itens") or []))
    return {
        "objeto": _sem_acento(dados.get("objeto")),
        "itens": _sem_acento(itens),
        "requisitos": _sem_acento(dados.get("requisitos")),
    }


def categoria_do_objeto(dados: dict) -> tuple[str, int]:
    """
    (categoria, evidência) do objeto pelo vocabulário controlado.
    Evidência = soma dos pesos dos campos onde os termos aparecem; abaixo
    de `_EVIDENCIA_MINIMA` devolve ("INDEFINIDA", n) e nenhum fato é
    emitido — regra condicional não dispara sem dado.
    """
    campos = _texto_dos_campos(dados)
    placar: dict[str, int] = {}
    for categoria, termos in CATEGORIAS_OBJETO.items():
        pontos = 0
        for campo, texto in campos.items():
            achados = sum(1 for t in termos if t in texto)
            pontos += achados * _PESO_CAMPO[campo]
        if pontos:
            placar[categoria] = pontos
    if not placar:
        return "INDEFINIDA", 0
    categoria, pontos = max(placar.items(), key=lambda kv: (kv[1], kv[0]))
    if pontos < _EVIDENCIA_MINIMA:
        return "INDEFINIDA", pontos
    return categoria, pontos


def _tem_termo(campos: dict[str, str], termos: tuple[str, ...]) -> bool:
    return any(t in texto for texto in campos.values() for t in termos)


def avaliar_termos(campos: dict[str, str],
                   termos: tuple[str, ...]) -> bool | None:
    """
    TRI-STATE do termo nos campos do formulário:
      True   — o termo aparece em contexto afirmativo;
      False  — TODAS as ocorrências estão negadas ("não será exigida…");
      None   — o termo não aparece: o processo nada diz (não decida).
    Conservador: basta UMA ocorrência afirmativa para valer True.
    """
    achou = False
    for texto in campos.values():
        for termo in termos:
            inicio = 0
            while (pos := texto.find(termo, inicio)) >= 0:
                achou = True
                antes = texto[max(0, pos - 70):pos]
                if not _RE_NEGACAO.search(antes.strip()):
                    return True          # ocorrência afirmativa
                inicio = pos + len(termo)
    return False if achou else None


def extrair_do_formulario(dados: dict,
                          processo_id: str | None = None) -> list[dict]:
    """Fatos materiais do Formulário Matriz (sempre com fonte)."""
    fatos: list[dict] = []

    def fato(path, valor, tipo, campo, confianca=0.9, inferido=False):
        # A fonte distingue o que foi INFORMADO do que foi INFERIDO: o
        # motor não deixa uma inferência, sozinha, impor cláusula
        # (ver conhecimento.CONFIANCA_VINCULANTE).
        fonte = f"{PREFIXO_INFERENCIA if inferido else 'formulario'}:{campo}"
        fatos.append(governanca.novo_fato(
            processo_id, path, valor, tipo, fonte, confianca=confianca))

    if (dados.get("orgao") or "").strip():
        fato("orgao.nome", dados["orgao"].strip(), "texto", "orgao")
    if (dados.get("responsavel") or "").strip():
        fato("responsavel.nome", dados["responsavel"].strip(), "texto",
             "responsavel")
    if (dados.get("objeto") or "").strip():
        fato("objeto.descricao", dados["objeto"].strip(), "texto", "objeto")

    execucao = (dados.get("modelo_execucao") or "").strip()
    if execucao:
        fato("execucao.modelo", execucao, "texto", "modelo_execucao")
        fato("procedimento.srp",
             execucao.startswith("Sistema de Registro de Preços"),
             "booleano", "modelo_execucao")
        fato("procedimento.execucao_continuada",
             "continuada" in execucao.lower(), "booleano",
             "modelo_execucao")

    if (dados.get("prazo") or "").strip():
        fato("prazo.descricao", dados["prazo"].strip(), "texto", "prazo")

    # -----------------------------------------------------------------
    # Fatos DERIVADOS (P1) — base estruturada das cláusulas condicionais.
    # Confiança menor: são inferências determinísticas e documentadas,
    # sujeitas a confirmação humana como qualquer outro fato 'extraido'.
    # -----------------------------------------------------------------
    campos = _texto_dos_campos(dados)
    categoria, evidencia = categoria_do_objeto(dados)
    if categoria != "INDEFINIDA":
        fato("objeto.categoria", categoria, "texto", "objeto+itens",
             confianca=CONFIANCA_HEURISTICA, inferido=True)
        fato("objeto.categoria_evidencia", float(evidencia), "numero",
             "objeto+itens", confianca=CONFIANCA_HEURISTICA, inferido=True)

    # Natureza do objeto: da execução quando ela a declara (base
    # estruturada); senão da categoria (heurística, confiança baixa);
    # sem nenhuma das duas, NENHUM fato — 'não sei' não é 'BENS'.
    natureza = NATUREZA_POR_EXECUCAO.get(execucao)
    if natureza:
        fato("objeto.natureza", natureza, "texto", "modelo_execucao",
             confianca=CONFIANCA_ESTRUTURADA)
    elif categoria in NATUREZA_POR_CATEGORIA:
        fato("objeto.natureza", NATUREZA_POR_CATEGORIA[categoria], "texto",
             "objeto+itens", confianca=CONFIANCA_HEURISTICA, inferido=True)

    if "continuada" in execucao.lower():
        # Repactuação exige serviço contínuo COM dedicação de mão de obra
        # (art. 135). TRI-STATE: sem informação sobre o regime de pessoal
        # nenhum fato é emitido — o motor alerta em vez de decidir.
        dedicacao = avaliar_termos(campos, _TERMOS_MAO_DE_OBRA)
        if dedicacao is not None:
            fato("procedimento.dedicacao_mao_de_obra", dedicacao,
                 "booleano", "modelo_execucao+requisitos",
                 confianca=CONFIANCA_ESTRUTURADA)

    # Garantia CONTRATUAL e amostra: fato positivo só com menção
    # afirmativa; menção negada vira fato FALSE; silêncio não vira fato.
    for path, termos in (("contratacao.garantia_exigida", _TERMOS_GARANTIA),
                         ("contratacao.amostra_exigida", _TERMOS_AMOSTRA)):
        valor = avaliar_termos(campos, termos)
        if valor is None:
            continue
        # a negativa é explícita no processo (alta confiança); a
        # afirmativa vem de texto livre e continua heurística
        fato(path, valor, "booleano", "requisitos",
             confianca=CONFIANCA_ESTRUTURADA if valor is False
             else CONFIANCA_HEURISTICA,
             inferido=valor is not False)

    if dados.get("valor_estimado") is not None:
        fato("valor.total", float(dados["valor_estimado"]), "numero",
             "itens")

    for i, item in enumerate(dados.get("itens") or []):
        if not str(item.get("descricao") or "").strip():
            continue
        fato(f"itens[{i}].descricao", str(item["descricao"]).strip(),
             "texto", "itens")
        for campo, tipo in (("quantidade", "numero"),
                            ("unidade", "texto"),
                            ("valor_unitario", "numero")):
            valor = item.get(campo)
            if valor in (None, ""):
                continue
            fato(f"itens[{i}].{campo}",
                 float(valor) if tipo == "numero" else str(valor).strip(),
                 tipo, "itens")
    return fatos


# ---------------------------------------------------------------------------
# Versionamento (puro): o que inserir e o que marcar como substituído
# ---------------------------------------------------------------------------
def planejar_versionamento(
    novos: list[dict], existentes: list[dict]
) -> tuple[list[dict], list[str]]:
    """
    (a_inserir, ids_a_substituir). Compara por path com a versão vigente:
      - path novo             → insere versão 1;
      - valor idêntico        → mantém (inclusive a confirmação);
      - valor diferente       → insere versão n+1 (status 'extraido',
                                `substitui` aponta a anterior) e a
                                anterior é marcada 'substituido'.
    """
    vigentes: dict[str, dict] = {}
    for fato in existentes:
        if fato.get("status") == "substituido":
            continue
        atual = vigentes.get(fato["path"])
        if atual is None or fato.get("versao", 1) > atual.get("versao", 1):
            vigentes[fato["path"]] = fato

    inserir: list[dict] = []
    substituir: list[str] = []
    for novo in novos:
        vigente = vigentes.get(novo["path"])
        if vigente is None:
            inserir.append(novo)
            continue
        if governanca.hash_canonico(vigente.get("valor")) == \
                governanca.hash_canonico(novo.get("valor")):
            continue  # nada mudou: preserva versão (e confirmação)
        derivado = dict(novo)
        derivado["versao"] = int(vigente.get("versao", 1)) + 1
        derivado["substitui"] = vigente.get("id")
        derivado["hash"] = governanca.hash_canonico(
            {k: derivado[k] for k in ("path", "tipo", "valor", "versao")})
        inserir.append(derivado)
        if vigente.get("id"):
            substituir.append(vigente["id"])
    return inserir, substituir


def sincronizar(processo_id: str, dados: dict) -> list[dict]:
    """Extrai, versiona e persiste; retorna os fatos vigentes."""
    novos = extrair_do_formulario(dados, processo_id)
    existentes = db.listar_fatos(processo_id, apenas_vigentes=False)
    inserir, substituir = planejar_versionamento(novos, existentes)
    if inserir:
        db.salvar_fatos(inserir)
    for fato_id in substituir:
        db.atualizar_fato(fato_id, status="substituido")
    return db.listar_fatos(processo_id)


def confirmar_todos(processo_id: str, usuario_id: str | None) -> int:
    """Confirma os fatos 'extraido' vigentes; retorna quantos confirmou."""
    confirmados = 0
    for fato in db.listar_fatos(processo_id):
        if fato.get("status") == "extraido":
            db.atualizar_fato(fato["id"], status="confirmado",
                              confirmado_por=usuario_id)
            confirmados += 1
    return confirmados


# ---------------------------------------------------------------------------
# Divergências documentais (presença de fatos materiais nos documentos;
# a consistência cruzada completa é a Fase 5)
# ---------------------------------------------------------------------------
def divergencias_documentais(fatos: list[dict],
                             documentos: dict[str, str]) -> list[dict]:
    divergencias = []
    docs_com_texto = {k: v for k, v in (documentos or {}).items()
                      if (v or "").strip()}
    if not docs_com_texto:
        return []
    por_path = {f["path"]: f for f in fatos
                if f.get("status") != "substituido"}

    valor = por_path.get("valor.total")
    if valor and float(valor.get("valor") or 0) > 0:
        moeda = planilha.formatar_moeda(float(valor["valor"]))
        ausentes = [doc for doc, texto in docs_com_texto.items()
                    if moeda not in texto]
        if len(ausentes) == len(docs_com_texto):
            divergencias.append({
                "path": "valor.total",
                "tipo": "fato_nao_refletido",
                "mensagem": (f"o valor global {moeda} (fato canônico) não "
                             "aparece em nenhum documento"),
                "documentos": sorted(ausentes),
            })

    prazo = por_path.get("prazo.descricao")
    if prazo and len(str(prazo.get("valor") or "")) > 4:
        alvo = " ".join(str(prazo["valor"]).split())
        presente = any(
            blocos.localizar_bloco(
                blocos.dividir_em_blocos(doc, texto), alvo)
            for doc, texto in docs_com_texto.items()
        )
        if not presente:
            divergencias.append({
                "path": "prazo.descricao",
                "tipo": "fato_nao_refletido",
                "mensagem": "o prazo informado no formulário não foi "
                            "localizado em nenhum documento",
                "documentos": sorted(docs_com_texto),
            })
    return divergencias


# ---------------------------------------------------------------------------
# Entrada única da tela final (flag + shadow)
# ---------------------------------------------------------------------------
def ativo() -> bool:
    return db.flag_ativa(governanca.FLAG_FATOS)


def processar_na_tela(dados: dict, documentos: dict[str, str],
                      processo_id: str | None) -> dict | None:
    """
    Flag LIGADA (com banco): sincroniza e retorna
    {"fatos": vigentes, "divergencias": [...]} para exibição.
    Flag DESLIGADA: shadow — extrai, compara e LOGA; retorna None
    (tela idêntica). Cache por conteúdo na sessão evita retrabalho.
    """
    chave = governanca.hash_canonico(
        {"dados": dados, "docs": documentos, "proc": processo_id})
    cache = st.session_state.get("_fatos_cache")
    if cache and cache.get("chave") == chave:
        return cache["resultado"]

    if not ativo() or not (db.disponivel() and processo_id):
        fatos = extrair_do_formulario(dados, processo_id)
        divergencias = divergencias_documentais(fatos, documentos)
        _log.info(
            "shadow: %d fato(s) canônico(s) extraído(s), %d divergência(s) "
            "documental(is)", len(fatos), len(divergencias))
        st.session_state["_fatos_cache"] = {"chave": chave,
                                            "resultado": None}
        return None

    fatos = sincronizar(processo_id, dados)
    resultado = {
        "fatos": fatos,
        "divergencias": divergencias_documentais(fatos, documentos),
    }
    st.session_state["_fatos_cache"] = {"chave": chave,
                                        "resultado": resultado}
    return resultado
