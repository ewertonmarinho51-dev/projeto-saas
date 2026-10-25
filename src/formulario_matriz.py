"""
Formulário Matriz sem tela: as regras que `ui/steps.render_formulario`
aplica, em funções puras, para a API (apps/api) usar sem o Streamlit.

O que vem de cá é o MESMO que o wizard faz:

* os campos, rótulos e ajudas são os de `config.CAMPOS_FORMULARIO`;
* a planilha passa por `planilha.calcular` (valor total por item e valor
  global, número em formato brasileiro aceito);
* "iniciar a elaboração" exige os obrigatórios — a planilha conta pelo
  item válido, não por linha em branco;
* dado alterado desatualiza a cadeia documental inteira, com a mesma
  cascata de `precos.aplicacao.descartar_por_planilha` (a Ata sai com o
  edital).

Diferença deliberada: a regeneração parcial (`regeneracao`, que guarda o
documento com um plano de atualização por cláusula) não entra aqui. Na
API, dado alterado descarta como com aquela flag desligada — mais
conservador: nenhum documento continua afirmando um dado que mudou.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import planilha
from .config import CAMPOS_FORMULARIO, CHAVE_FLUXO_MAPA

# Limites de tamanho (caracteres). O Streamlit não tinha: a API precisa,
# porque o corpo vem da rede. Folgados para o maior texto real conhecido
# (memorando colado inteiro).
LIMITE_TEXTO = 500
LIMITE_AREA = 20_000
LIMITE_MEMORANDO = 60_000
LIMITE_ITENS = 2_000
LIMITE_CELULA = 2_000

CAMPOS_DE_TEXTO = tuple(k for k, m in CAMPOS_FORMULARIO.items() if m["tipo"] in ("texto", "area", "selecao"))


class ErroDoFormulario(ValueError):
    """Valor que não cabe no campo (tamanho, opção inexistente)."""


@dataclass(frozen=True)
class Gravacao:
    """A linha nova do processo, sem gravar."""

    dados: dict
    documentos: dict
    aprovados: list[str]
    descartados: list[str]
    etapa: int
    mudou: bool


def campos() -> list[dict]:
    """Os campos para a tela: o rótulo e a ajuda SIMPLES, como o wizard mostra."""
    saida = []
    for chave, meta in CAMPOS_FORMULARIO.items():
        saida.append({
            "chave": chave,
            "tipo": meta["tipo"],
            "rotulo": meta.get("rotulo_tela") or meta["rotulo"],
            "ajuda": meta.get("ajuda_simples") or meta["help"],
            "exemplo": (meta.get("exemplo") or "").strip(),
            "placeholder": meta.get("placeholder") or "",
            "obrigatorio": bool(meta["obrigatorio"]),
            "opcoes": list(meta.get("opcoes") or []),
        })
    return saida


def _limite(chave: str) -> int:
    if chave == "memorando":
        return LIMITE_MEMORANDO
    return LIMITE_AREA if CAMPOS_FORMULARIO[chave]["tipo"] == "area" else LIMITE_TEXTO


def _itens(brutos) -> list[dict]:
    if brutos is None:
        return []
    if not isinstance(brutos, list):
        raise ErroDoFormulario("A planilha de itens precisa ser uma lista de linhas.")
    if len(brutos) > LIMITE_ITENS:
        raise ErroDoFormulario(f"A planilha passa de {LIMITE_ITENS} itens.")
    linhas = []
    for bruta in brutos:
        if not isinstance(bruta, dict):
            raise ErroDoFormulario("Cada linha da planilha precisa ser um objeto.")
        linha = {}
        for coluna, valor in bruta.items():
            if not isinstance(coluna, str) or not coluna or len(coluna) > 80:
                raise ErroDoFormulario("Coluna da planilha com nome inválido.")
            if coluna == "valor_total":
                continue  # derivado: quem calcula é o servidor
            if valor is None:
                valor = ""
            if not isinstance(valor, (str, int, float)) or isinstance(valor, bool):
                raise ErroDoFormulario("Célula da planilha com valor inválido.")
            if isinstance(valor, str) and len(valor) > LIMITE_CELULA:
                raise ErroDoFormulario("Célula da planilha longa demais.")
            linha[coluna] = valor
        linhas.append(linha)
    itens, _ = planilha.calcular(linhas)
    return itens


def normalizar(valores: dict) -> dict:
    """
    Os valores do formulário como o wizard os grava: texto aparado, opção
    conferida, planilha calculada (`itens` + `valor_estimado`). Só os
    campos do Formulário Matriz; o resto é recusado pela API antes daqui.
    """
    if not isinstance(valores, dict):
        raise ErroDoFormulario("Formulário inválido.")
    desconhecidos = set(valores) - set(CAMPOS_FORMULARIO)
    if desconhecidos:
        raise ErroDoFormulario(f"Campo desconhecido: {sorted(desconhecidos)[0]}.")
    saida: dict = {}
    for chave in CAMPOS_DE_TEXTO:
        bruto = valores.get(chave)
        if bruto is None:
            bruto = ""
        if not isinstance(bruto, str):
            raise ErroDoFormulario(f"O campo {chave} precisa ser texto.")
        texto = bruto.strip()
        if len(texto) > _limite(chave):
            raise ErroDoFormulario(f"O campo {CAMPOS_FORMULARIO[chave]['rotulo']} passa do tamanho permitido.")
        opcoes = CAMPOS_FORMULARIO[chave].get("opcoes")
        if opcoes and texto and texto not in opcoes:
            raise ErroDoFormulario(f"Opção inexistente em {CAMPOS_FORMULARIO[chave]['rotulo']}.")
        saida[chave] = texto
    itens = _itens(valores.get("itens"))
    _, valor_global = planilha.calcular(itens)
    saida["itens"] = itens
    saida["valor_estimado"] = valor_global
    return saida


def faltantes(dados: dict) -> list[str]:
    """Rótulos dos obrigatórios vazios — a mesma regra do botão de avançar."""
    falta = []
    for chave, meta in CAMPOS_FORMULARIO.items():
        if not meta["obrigatorio"]:
            continue
        if chave == "itens":
            if not [i for i in (dados.get("itens") or []) if planilha.item_valido(i)]:
                falta.append(meta.get("rotulo_tela") or meta["rotulo"])
        elif not str(dados.get(chave) or "").strip():
            falta.append(meta.get("rotulo_tela") or meta["rotulo"])
    return falta


def _comparavel(dados: dict) -> dict:
    """
    O formulário na forma em que se compara: texto aparado e planilha
    recalculada. Processo antigo pode ter a quantidade gravada como texto
    ou sem `valor_total`; sem isto, abrir e salvar sem mexer em nada
    contaria como alteração e descartaria os documentos.
    """
    saida = {k: str(dados.get(k) or "").strip() for k in CAMPOS_DE_TEXTO}
    try:
        itens, valor = planilha.calcular([dict(i) for i in (dados.get("itens") or []) if isinstance(i, dict)])
    except Exception:  # noqa: BLE001 — dado legado estranho: compara como veio
        itens, valor = dados.get("itens") or [], dados.get("valor_estimado")
    saida["itens"] = itens
    saida["valor_estimado"] = valor
    return saida


def gravar(processo: dict, valores: dict, *, iniciar: bool) -> Gravacao:
    """
    Aplica o formulário à linha do processo, sem gravar.

    `iniciar=True` é o "Iniciar elaboração dos documentos": exige os
    obrigatórios (levanta `ErroDoFormulario` com a lista) e leva a etapa
    a 1 se o processo ainda estava no formulário. Rascunho grava como
    está.

    Chaves de `dados` que não são do formulário (o fluxo do Mapa de
    Riscos, a estimativa que a pesquisa de preços deixou) são mantidas.
    """
    from .precos.aplicacao import descartar_por_planilha

    atuais = dict(processo.get("dados") or {})
    novos = normalizar(valores)
    if iniciar:
        falta = faltantes(novos)
        if falta:
            raise ErroDoFormulario("Preencha os campos obrigatórios: " + ", ".join(falta) + ".")
    mudou = _comparavel(atuais) != _comparavel(novos)
    dados = {**atuais, **novos}
    if atuais.get(CHAVE_FLUXO_MAPA):
        dados[CHAVE_FLUXO_MAPA] = True
    documentos = dict(processo.get("documentos") or {})
    aprovados = list(processo.get("aprovados") or [])
    descartados: list[str] = []
    if mudou:
        documentos, aprovados, descartados = descartar_por_planilha(atuais, documentos, aprovados)
    etapa = int(processo.get("etapa") or 0)
    if iniciar and etapa == 0:
        etapa = 1
    return Gravacao(dados, documentos, aprovados, descartados, etapa, mudou)


def a_descartar(processo: dict) -> list[str]:
    """O que sairia se o formulário mudasse agora — para a tela avisar ANTES."""
    from .precos.aplicacao import descartar_por_planilha

    _, _, descartados = descartar_por_planilha(
        processo.get("dados") or {}, processo.get("documentos") or {}, processo.get("aprovados") or [])
    return descartados
