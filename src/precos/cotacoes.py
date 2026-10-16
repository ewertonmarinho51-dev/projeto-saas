"""
Serviço de Cotações — o orquestrador fino de UMA cotação.

"Cotação" é o nome que o servidor vê; a entidade é a MESMA pesquisa de
preços da migração 0021 (`pesquisas_preco` + itens + referências +
eventos). Não há segunda tabela, segunda busca nem segunda cesta:

    criar_cotacao ─┐
    salvar_item    │  repositorio (JWT do usuário, RLS, idempotência)
    pesquisar_item ┼─ busca.coletar ── cesta.recalcular_e_gravar ── estatistica
    alterar_status │
    concluir_item ─┘

`pesquisar_item` é o mesmo caminho para a busca MANUAL e para a
**Cotação automática**: a única diferença é quem marca a cesta — o
servidor, referência a referência, ou a regra determinística da cesta
automática (comparabilidade ≥ piso, natureza de preço, unidade
comprovada), sempre com revisão humana antes de concluir. Trocar de modo
no meio do trabalho não cria nada novo: as linhas são as mesmas, e a
decisão humana já gravada numa referência NUNCA é desfeita por uma busca
nova (a busca só acrescenta candidatas).

O que este módulo NÃO faz: calcular preço (é `estatistica`), decidir
cesta por IA (o Jev só sugere, ver `seletor`), desenhar tela, chamar
rede fora de `busca.coletar`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from .. import db
from . import busca, cesta, estatistica, estados, unidades
from . import repositorio as repo
from .estados import EstadoItem, EstadoPesquisa
from .modelo import NATUREZAS_COMPARAVEIS, StatusReferencia
from .perfil import PERFIS
from .perfil import obter as obter_perfil

MAXIMO_NOME = 255
MODOS = ("manual", "automatico")
# Situações que só mudam por ato do revisor (ou já formaram a cesta).
DECIDIDAS = frozenset({"selected", "rejected", "warning"})


class ErroCotacao(ValueError):
    """Pedido recusado — a mensagem diz o que corrigir."""


class CotacaoImutavel(ErroCotacao):
    """Aplicada ou arquivada: mudar exige revisão nova."""


@dataclass
class Contexto:
    """Quem opera. O banco confere de novo pelo JWT (RLS); isto é a trilha."""

    auth_user_id: str
    secretaria_id: str | None = None
    processo_aberto: str | None = None


# ---------------------------------------------------------------------------
# Cotação
# ---------------------------------------------------------------------------
def criar_cotacao(ctx: Contexto, dados: dict, *,
                  idempotency_key: str = "") -> dict:
    """
    Cria a cotação ANTES de qualquer item (a identidade vem primeiro,
    U01). Nome obrigatório; o perfil normativo e a data-base ficam
    gravados e vão para o relatório. Critério percentual é opcional e só
    sinaliza.
    """
    nome = str(dados.get("nome") or "").strip()
    if not nome:
        raise ErroCotacao("dê um nome à cotação")
    if len(nome) > MAXIMO_NOME:
        raise ErroCotacao(f"o nome tem {len(nome)} caracteres; o limite é "
                          f"{MAXIMO_NOME}")
    if not ctx.auth_user_id:
        raise ErroCotacao("sua conta precisa estar vinculada ao login por "
                          "e-mail para criar uma cotação")
    perfil_id = str(dados.get("perfil_normativo") or "lei_14133")
    if perfil_id not in PERFIS:
        raise ErroCotacao("perfil normativo desconhecido")
    from .execucao import JANELA_PADRAO_DIAS, janela_efetiva

    filtros: dict = {"janela_dias": janela_efetiva(
        {"janela_dias": dados.get("janela_dias") or JANELA_PADRAO_DIAS})}
    if dados.get("uf"):
        filtros["uf"] = str(dados["uf"]).strip().upper()
    criterio = dados.get("criterio_percentual")
    if criterio:
        if estatistica.criterio_percentual_da(
                {"criterio_percentual": criterio}) is None:
            raise ErroCotacao("critério percentual inválido: elevado > 0 e "
                              "inexequível entre 0 e 100")
        filtros["criterio_percentual"] = {
            "elevado": str(criterio["elevado"]),
            "inexequivel": str(criterio["inexequivel"])}
    cotacao = repo.criar_pesquisa(
        nome, auth_user_id=ctx.auth_user_id, secretaria_id=ctx.secretaria_id,
        processo_id=dados.get("processo_id") or None,
        objeto=str(dados.get("objeto") or "").strip(),
        responsavel=str(dados.get("responsavel") or "").strip(),
        local_referencia=str(dados.get("local_referencia") or "").strip(),
        data_base=dados.get("data_base") or date.today(),
        perfil_normativo=perfil_id, filtros=filtros,
        versao_regras=estatistica.REGRAS_MEDIA_PADRAO,
        idempotency_key=idempotency_key)
    repo.registrar_evento(
        str(cotacao["id"]), "pesquisa_criada", ator=ctx.auth_user_id,
        descricao=nome, payload={"origem": "cotacoes"},
        idempotency_key=f"criada:{idempotency_key}" if idempotency_key else "")
    return cotacao


def _exigir_editavel(cotacao: dict | None) -> dict:
    if not cotacao:
        raise ErroCotacao("cotação não encontrada ou fora do seu acesso")
    estado = EstadoPesquisa(str(cotacao.get("estado") or "draft"))
    if estado in estados.IMUTAVEIS:
        raise CotacaoImutavel(
            "esta cotação já foi aplicada ao processo ou arquivada; para "
            "mudar, crie uma revisão nova (a anterior fica preservada)")
    return cotacao


def ativos(itens: list[dict]) -> list[dict]:
    """Itens que não foram retirados da cotação, pela ordem do número."""
    return sorted((i for i in itens if not i.get("removido_em")),
                  key=lambda i: int(i.get("numero") or 0))


@dataclass
class Resumo:
    """Uma linha de Minhas Cotações."""

    id: str
    nome: str
    objeto: str
    estado: str
    versao: int
    itens: int
    com_minimo: int
    pendentes: int
    valor_concluidos: Decimal
    atualizado_em: str
    vinculada: bool

    @property
    def cobertura(self) -> float:
        return 0.0 if not self.itens else self.com_minimo / self.itens


RECORTES = {
    "Em elaboração": {"draft", "queued", "running", "review"},
    "Com pendência": {"partial", "failed"},
    "Concluídas": {"completed", "applied"},
    "Arquivadas": {"archived"},
}


def listar_cotacoes(ctx: Contexto, *, busca_texto: str = "",
                    recorte: str | None = None, limite: int = 200
                    ) -> list[Resumo]:
    """Cotações que o usuário alcança (RLS), com o resumo dos itens."""
    linhas = repo.listar_pesquisas(limite=limite)
    if recorte in RECORTES:
        linhas = [l for l in linhas if str(l.get("estado")) in RECORTES[recorte]]
    elif recorte != "Todas":
        linhas = [l for l in linhas if str(l.get("estado")) != "archived"]
    termo = busca_texto.strip().casefold()
    if termo:
        linhas = [l for l in linhas
                  if termo in str(l.get("nome") or "").casefold()
                  or termo in str(l.get("objeto") or "").casefold()]
    por_cotacao: dict[str, list[dict]] = {}
    for item in repo.itens_de_varias([str(l["id"]) for l in linhas]):
        por_cotacao.setdefault(str(item["pesquisa_id"]), []).append(item)
    saida = []
    for linha in linhas:
        itens = ativos(por_cotacao.get(str(linha["id"]), []))
        minimo = obter_perfil(linha.get("perfil_normativo")).minimo_referencias
        concluidos = [i for i in itens
                      if str(i.get("estado")) == EstadoItem.COMPLETO.value]
        saida.append(Resumo(
            id=str(linha["id"]), nome=str(linha.get("nome") or ""),
            objeto=str(linha.get("objeto") or ""),
            estado=str(linha.get("estado") or ""),
            versao=int(linha.get("versao") or 1), itens=len(itens),
            com_minimo=sum(1 for i in itens
                           if (cesta.na_cesta_do_item(i) or 0) >= minimo),
            pendentes=len(itens) - len(concluidos),
            valor_concluidos=sum(
                (Decimal(str(i["preco_total"])) for i in concluidos
                 if i.get("preco_total") not in (None, "")), Decimal(0)),
            atualizado_em=str(linha.get("atualizado_em") or ""),
            vinculada=bool(linha.get("processo_id"))))
    return saida


def duplicar(ctx: Contexto, cotacao_id: str) -> dict:
    """
    Cópia para uma cotação NOVA, com os mesmos itens e nenhum preço — a
    coleta é refeita na nova data-base. (Revisão é outra coisa: mesma
    cotação lógica, `repositorio.revisar`.)
    """
    origem = repo.obter_pesquisa(cotacao_id)
    if not origem:
        raise ErroCotacao("cotação não encontrada ou fora do seu acesso")
    copia = repo.criar_pesquisa(
        f"{origem.get('nome') or 'Cotação'} (cópia)"[:MAXIMO_NOME],
        auth_user_id=ctx.auth_user_id, secretaria_id=ctx.secretaria_id,
        objeto=str(origem.get("objeto") or ""),
        responsavel=str(origem.get("responsavel") or ""),
        local_referencia=str(origem.get("local_referencia") or ""),
        perfil_normativo=str(origem.get("perfil_normativo") or "lei_14133"),
        filtros=dict(origem.get("filtros") or {}),
        versao_regras=estatistica.REGRAS_MEDIA_PADRAO)
    itens = ativos(repo.listar_itens(cotacao_id))
    if itens:
        repo.salvar_itens(str(copia["id"]), [{
            "numero": posicao, "codigo": i.get("codigo"),
            "tipo_catalogo": i.get("tipo_catalogo"),
            "descricao": i.get("descricao"), "unidade": i.get("unidade"),
            "quantidade": i.get("quantidade"), "lote": i.get("lote"),
            "uf": i.get("uf")} for posicao, i in enumerate(itens, start=1)])
    repo.registrar_evento(str(copia["id"]), "pesquisa_criada",
                          ator=ctx.auth_user_id,
                          descricao=f"duplicada de {origem.get('nome')}",
                          payload={"origem": cotacao_id})
    return copia


def arquivar(ctx: Contexto, cotacao_id: str) -> dict:
    atual = repo.obter_pesquisa(cotacao_id)
    if not atual:
        raise ErroCotacao("cotação não encontrada ou fora do seu acesso")
    linha = repo.mover_pesquisa(cotacao_id, EstadoPesquisa.ARQUIVADA,
                                atual["estado"])
    repo.registrar_evento(cotacao_id, "pesquisa_arquivada",
                          ator=ctx.auth_user_id)
    return linha


# ---------------------------------------------------------------------------
# Estado da cotação — DERIVADO dos itens, por transições declaradas
# ---------------------------------------------------------------------------
def _caminho(origem: EstadoPesquisa, destino: EstadoPesquisa
             ) -> list[EstadoPesquisa]:
    """Menor sequência de transições declaradas de `origem` a `destino`."""
    if origem == destino:
        return []
    fila = [(origem, [])]
    vistos = {origem}
    while fila:
        atual, trilha = fila.pop(0)
        for proximo in estados.TRANSICOES_PESQUISA.get(atual, ()):
            if proximo in (EstadoPesquisa.APLICADA, EstadoPesquisa.ARQUIVADA,
                           EstadoPesquisa.FALHOU):
                continue
            if proximo == destino:
                return trilha + [proximo]
            if proximo not in vistos:
                vistos.add(proximo)
                fila.append((proximo, trilha + [proximo]))
    return []


def estado_da_cotacao(itens: list[EstadoItem]) -> EstadoPesquisa | None:
    """
    O estado que os itens justificam — ou None (não mexer).

    Diferente de `estado_derivado` (que serve ao lote automático) em dois
    pontos: item ainda não pesquisado não faz a cotação "executar" —
    cotação só com itens novos continua como está —, e tudo concluído
    fica EM REVISÃO, porque concluir a cotação é ato humano.
    """
    conjunto = set(itens)
    if not conjunto or conjunto == {EstadoItem.PENDENTE}:
        return None
    if conjunto & {EstadoItem.BUSCANDO, EstadoItem.CLASSIFICANDO}:
        return EstadoPesquisa.EXECUTANDO
    if conjunto & {EstadoItem.EM_REVISAO, EstadoItem.ERRO}:
        return EstadoPesquisa.EM_REVISAO
    if conjunto & {EstadoItem.INCOMPLETO, EstadoItem.PENDENTE}:
        return EstadoPesquisa.PARCIAL
    return EstadoPesquisa.EM_REVISAO


def sincronizar_estado(cotacao_id: str) -> str:
    """
    Leva a cotação ao estado que os itens dizem (`estado_derivado`),
    passando só por transições declaradas. Nunca toca cotação aplicada
    ou arquivada e nunca a declara CONCLUÍDA — concluir é ato humano
    (`concluir_cotacao`).
    """
    cotacao = repo.obter_pesquisa(cotacao_id) or {}
    atual = EstadoPesquisa(str(cotacao.get("estado") or "draft"))
    if atual in estados.IMUTAVEIS:
        return atual.value
    # Só o ESTADO dos itens (consulta leve): em 210 itens, reler as
    # estatísticas de todos a cada passo era o custo dominante (G6).
    alvo = estado_da_cotacao(
        [EstadoItem(str(i.get("estado") or "pending"))
         for i in repo.itens_de_varias([cotacao_id])
         if not i.get("removido_em")])
    if alvo is None:
        return atual.value
    for passo in _caminho(atual, alvo):
        repo.mover_pesquisa(cotacao_id, passo, atual)
        atual = passo
    return atual.value


def concluir_cotacao(ctx: Contexto, cotacao_id: str) -> dict:
    """Todos os itens ativos COMPLETOS → CONCLUÍDA. Senão diz quais faltam."""
    cotacao = _exigir_editavel(repo.obter_pesquisa(cotacao_id))
    itens = ativos(repo.listar_itens(cotacao_id))
    faltam = [int(i.get("numero") or 0) for i in itens
              if str(i.get("estado")) != EstadoItem.COMPLETO.value]
    if not itens or faltam:
        raise ErroCotacao(
            "conclua todos os itens antes — faltam: "
            + (", ".join(str(n) for n in faltam) or "nenhum item"))
    sincronizar_estado(cotacao_id)
    cotacao = repo.obter_pesquisa(cotacao_id) or cotacao
    linha = repo.mover_pesquisa(cotacao_id, EstadoPesquisa.CONCLUIDA,
                                cotacao["estado"])
    repo.registrar_evento(cotacao_id, "pesquisa_concluida",
                          ator=ctx.auth_user_id)
    return linha


# ---------------------------------------------------------------------------
# Itens
# ---------------------------------------------------------------------------
def _validar_item(dados: dict) -> dict:
    from .importacao import UFS, quantidade_de

    descricao = " ".join(str(dados.get("descricao") or "").split())
    if len(descricao) < 3:
        raise ErroCotacao("descreva o item (descrição e especificação)")
    unidade = unidades.canonizar(dados.get("unidade"))
    if unidade is None:
        raise ErroCotacao(
            f"unidade '{dados.get('unidade') or ''}' não reconhecida — use "
            "uma das unidades do dicionário (ex.: "
            + ", ".join(unidades.unidades_aceitas()[:8]) + "…)")
    quantidade = quantidade_de(dados.get("quantidade"))
    if quantidade is None or quantidade <= 0:
        raise ErroCotacao("a quantidade precisa ser um número maior que zero")
    uf = str(dados.get("uf") or "").strip().upper()
    if uf and uf not in UFS:
        raise ErroCotacao(f"UF '{uf}' inválida")
    saida = {"descricao": descricao, "unidade": unidade,
             "quantidade": quantidade,
             "codigo": str(dados.get("codigo") or "").strip() or None}
    for campo in ("lote", "uf"):
        if dados.get(campo):
            saida[campo] = uf if campo == "uf" else str(dados[campo]).strip()
    return saida


def salvar_item(ctx: Contexto, cotacao_id: str, dados: dict, *,
                item_id: str | None = None,
                revisao_esperada: int | None = None) -> dict:
    """
    Inclui (sem `item_id`) ou edita um item, validado. Editar descrição
    ou unidade de item já pesquisado devolve o item à busca — a cesta
    valia para o item antigo; mudar só a quantidade refaz o total.
    """
    cotacao = _exigir_editavel(repo.obter_pesquisa(cotacao_id))
    campos = _validar_item(dados)
    itens = repo.listar_itens(cotacao_id)
    if item_id is None:
        numero = max([int(i.get("numero") or 0) for i in itens] or [0]) + 1
        [novo] = repo.salvar_itens(cotacao_id, [{"numero": numero, **campos}])
        repo.registrar_evento(cotacao_id, "item_editado", ator=ctx.auth_user_id,
                              item_id=str(novo["id"]),
                              descricao=f"item {numero} incluído")
        return novo
    atual = next((i for i in itens if str(i["id"]) == str(item_id)), None)
    if atual is None:
        raise ErroCotacao("item não encontrado nesta cotação")
    mudou = [c for c in ("descricao", "unidade", "quantidade", "codigo",
                         "lote", "uf")
             if c in campos and str(campos[c]) != str(atual.get(c) or "")
             and not (c == "quantidade" and Decimal(str(campos[c]))
                      == Decimal(str(atual.get(c) or 0)))]
    if not mudou:
        return atual
    linha = repo.atualizar_item(str(item_id),
                                {c: campos[c] for c in mudou},
                                revisao_esperada=revisao_esperada)
    estado = EstadoItem(str(linha.get("estado") or "pending"))
    if {"descricao", "unidade"} & set(mudou) and estado not in (
            EstadoItem.PENDENTE, EstadoItem.BUSCANDO):
        linha = repo.mover_item(str(item_id), EstadoItem.BUSCANDO, estado,
                                erro="")
    elif "quantidade" in mudou and estado in (
            EstadoItem.EM_REVISAO, EstadoItem.INCOMPLETO, EstadoItem.COMPLETO):
        cesta.recalcular_e_gravar(
            cotacao, linha, repo,
            perfil=obter_perfil(cotacao.get("perfil_normativo")))
        linha = repo.obter_item(str(item_id)) or linha
    repo.registrar_evento(cotacao_id, "item_editado", ator=ctx.auth_user_id,
                          item_id=str(item_id),
                          descricao=f"alterado: {', '.join(mudou)}")
    sincronizar_estado(cotacao_id)
    return linha


def remover_item(ctx: Contexto, cotacao_id: str, item_id: str,
                 motivo: str) -> dict:
    """
    Retira o item da cotação SEM apagar (a 0021 não concede DELETE): o
    item e as referências ficam no banco e na trilha, com o motivo.
    """
    _exigir_editavel(repo.obter_pesquisa(cotacao_id))
    if len(str(motivo or "").strip()) < 5:
        raise ErroCotacao("diga por que o item sai da cotação")
    linha = repo.atualizar_item(
        str(item_id),
        {"removido_em": datetime.now(timezone.utc).isoformat()})
    repo.registrar_evento(cotacao_id, "item_removido", ator=ctx.auth_user_id,
                          item_id=str(item_id), descricao=motivo.strip())
    sincronizar_estado(cotacao_id)
    return linha


def mover_item_na_lista(ctx: Contexto, cotacao_id: str, item_id: str,
                        direcao: int) -> None:
    """
    Troca o item de lugar com o vizinho (direção -1/+1), preservando os
    números como identidade da linha: a troca passa por um número
    temporário fora da faixa, porque (pesquisa, número) é chave única.
    """
    _exigir_editavel(repo.obter_pesquisa(cotacao_id))
    lista = ativos(repo.listar_itens(cotacao_id))
    posicao = next((n for n, i in enumerate(lista)
                    if str(i["id"]) == str(item_id)), None)
    if posicao is None:
        raise ErroCotacao("item não encontrado nesta cotação")
    alvo = posicao + (1 if direcao > 0 else -1)
    if not 0 <= alvo < len(lista):
        return
    a, b = lista[posicao], lista[alvo]
    id_a, numero_a = str(a["id"]), int(a["numero"])
    id_b, numero_b = str(b["id"]), int(b["numero"])
    temporario = max(int(i.get("numero") or 0)
                     for i in repo.listar_itens(cotacao_id)) + 1000
    repo.atualizar_item(id_a, {"numero": temporario})
    repo.atualizar_item(id_b, {"numero": numero_a})
    repo.atualizar_item(id_a, {"numero": numero_b})


# ---------------------------------------------------------------------------
# Pesquisa de preços do item — manual e automática no MESMO caminho
# ---------------------------------------------------------------------------
DIAGNOSTICOS = {
    "fonte_indisponivel": "As fontes de preço não responderam — falha "
                          "técnica, não ausência de mercado. Repita mais "
                          "tarde; nada foi apagado.",
    "zero_resultados": "As fontes responderam e não há compra registrada "
                       "para este item no período. Amplie a janela, revise "
                       "a descrição ou registre cotação direta.",
    "sem_comparaveis": "Há resultados, mas nenhum é comparável ao item "
                       "(produto, unidade ou natureza diferentes) — são só "
                       "itens parecidos, e nenhum vira preço.",
    "amostra_insuficiente": "Há preço comparável, mas abaixo do mínimo do "
                            "perfil. Amplie a busca, registre cotação "
                            "direta ou justifique a exceção.",
    "ok": "Amostra suficiente para formar o preço; revise antes de concluir.",
}


@dataclass
class ResultadoPesquisa:
    item_id: str
    modo: str
    diagnostico: str
    brutas: int = 0
    unicas: int = 0
    elegiveis: int = 0
    novas: int = 0
    preservadas: int = 0
    consideradas: int = 0
    desfechos: dict = field(default_factory=dict)
    ocorrencias: list[str] = field(default_factory=list)
    termos: list[str] = field(default_factory=list)
    duracao_s: float = 0.0
    estimativa: estatistica.Estimativa | None = None
    sugestao: dict | None = None

    @property
    def mensagem(self) -> str:
        return DIAGNOSTICOS.get(self.diagnostico, "")


def diagnostico_da_coleta(coleta: busca.Coleta, consideradas: int,
                          minimo: int, piso: Decimal) -> str:
    """Quatro situações que pedem ações diferentes — nunca confundidas."""
    if coleta.erro:
        return "fonte_indisponivel"
    if not coleta.referencias:
        return "zero_resultados"
    if consideradas == 0 and coleta.elegiveis(piso) == 0:
        return "sem_comparaveis"
    if consideradas < minimo:
        return "amostra_insuficiente"
    return "ok"


def _fontes_padrao():
    from . import fontes_padrao

    return fontes_padrao()


def _ao_buscar(item_id: str, atual: EstadoItem) -> None:
    if atual is EstadoItem.CLASSIFICANDO:
        # sobra de uma rodada interrompida: a máquina não volta de
        # CLASSIFICANDO para BUSCANDO; passa por ERRO, que é o que houve
        repo.mover_item(item_id, EstadoItem.ERRO, atual,
                        erro="rodada anterior interrompida")
        atual = EstadoItem.ERRO
    if atual is not EstadoItem.BUSCANDO:
        repo.mover_item(item_id, EstadoItem.BUSCANDO, atual, erro="")


def pesquisar_item(ctx: Contexto, cotacao_id: str, item_id: str, *,
                   modo: str = "manual", filtros: dict | None = None,
                   termo: str = "", fontes=None, motor_semantico=None,
                   seletor=None, sincronizar: bool = True,
                   cotacao: dict | None = None) -> ResultadoPesquisa:
    """
    Busca preços para UM item e grava as candidatas no próprio item.

    * `manual`: as candidatas novas entram como `candidate`; quem marca
      a cesta é o servidor (U03);
    * `automatico`: as novas passam pela regra determinística da cesta
      automática (`estatistica.selecionar_cesta`) — e, se houver
      `seletor` (Jev, G4), recebem uma SUGESTÃO registrada para revisão.
      Nada é aceito pela IA (U04).

    Em ambos: a decisão humana já gravada numa referência é preservada;
    o preço é refeito por `cesta.recalcular_e_gravar`; a busca fica
    registrada na trilha com termo, filtros, fontes e contagens (F077).
    """
    if modo not in MODOS:
        raise ErroCotacao("modo de pesquisa desconhecido")
    inicio = time.monotonic()
    # O lote passa a cotação já lida: reler a cada item custava uma
    # requisição a mais ao banco em cada um dos 210 itens (benchmark G6).
    cotacao = _exigir_editavel(cotacao if cotacao is not None
                               else repo.obter_pesquisa(cotacao_id))
    item = repo.obter_item(item_id)
    if not item or str(item.get("pesquisa_id")) != str(cotacao_id) \
            or item.get("removido_em"):
        raise ErroCotacao("item não encontrado nesta cotação")
    perfil = obter_perfil(cotacao.get("perfil_normativo"))
    filtros_efetivos = {**(cotacao.get("filtros") or {}), **(filtros or {}),
                        "data_base": cotacao.get("data_base")
                        or date.today().isoformat()}
    termos: tuple[str, ...] = ()
    if termo.strip() and termo.strip().casefold() != \
            str(item.get("descricao") or "").strip().casefold():
        termos = (termo.strip(),)
    # Ampliação semântica só quando o servidor DESMARCA "apenas o termo
    # digitado" — e só acrescenta palavras: a descrição do item continua
    # sendo a régua de comparação, então vizinho não vira preço (F071).
    if motor_semantico is not None and not filtros_efetivos.get("literal"):
        from . import semantica

        termos = termos + tuple(semantica.sugerir_termos(motor_semantico, item))

    estado = EstadoItem(str(item.get("estado") or "pending"))
    if estado is EstadoItem.COMPLETO:
        raise ErroCotacao("o item está concluído; reabra-o (com motivo) "
                          "antes de pesquisar de novo")
    _ao_buscar(item_id, estado)
    fontes = list(fontes if fontes is not None else _fontes_padrao())
    escolhidas = set(filtros_efetivos.get("fontes") or ())
    if escolhidas:
        fontes = [f for f in fontes
                  if getattr(getattr(f, "fonte", None), "id", "") in escolhidas]
    coleta = busca.coletar(item, fontes, filtros=filtros_efetivos,
                           termos=termos)
    resultado = ResultadoPesquisa(
        item_id=item_id, modo=modo, diagnostico="", brutas=coleta.brutas,
        unicas=coleta.unicas,
        elegiveis=coleta.elegiveis(estatistica.PISO_COMPARABILIDADE),
        desfechos=dict(coleta.desfechos), ocorrencias=list(coleta.ocorrencias),
        termos=list(termos))

    if coleta.erro:
        repo.mover_item(item_id, EstadoItem.ERRO, EstadoItem.BUSCANDO,
                        desfechos=coleta.desfechos,
                        ocorrencias=coleta.ocorrencias, erro=coleta.erro)
        resultado.diagnostico = "fonte_indisponivel"
        _registrar_busca(ctx, cotacao_id, item_id, resultado, filtros_efetivos,
                         termo, inicio, falhou=True)
        if sincronizar:
            sincronizar_estado(cotacao_id)
        return resultado

    # Decisões já gravadas sobre a CESTA (dentro, fora com motivo, ou
    # sinalizada) valem mais que a busca nova. Candidata solta não é
    # decisão: a Cotação automática pode reavaliá-la pela mesma regra.
    existentes = {(str(r.get("fonte_id")), str(r.get("id_externo"))): r
                  for r in repo.listar_referencias(item_id)}
    novas = []
    for referencia, comparabilidade in coleta.referencias:
        chave = (referencia.fonte.id, referencia.id_externo)
        anterior = existentes.get(chave)
        decidida = anterior is not None and (
            str(anterior.get("status")) in DECIDIDAS or modo == "manual")
        if decidida:
            referencia.status = StatusReferencia(str(anterior.get("status")))
            for motivo in anterior.get("motivos") or []:
                referencia.com_motivo(str(motivo))
            resultado.preservadas += 1
        else:
            novas.append((referencia, comparabilidade))
    if modo == "automatico" and novas:
        estatistica.selecionar_cesta(novas, perfil)
    else:
        for referencia, _ in novas:
            referencia.status = StatusReferencia.CANDIDATA
            if referencia.valor_unitario_normalizado is None:
                referencia.com_motivo("sem preço na unidade do item — não "
                                      "pode compor a cesta")
            elif referencia.natureza_valor not in NATUREZAS_COMPARAVEIS:
                referencia.com_motivo(f"{referencia.rotulo_da_natureza} — "
                                      "não é preço praticado")
    resultado.novas = len(novas)
    gravadas = (repo.registrar_referencias(item_id, coleta.referencias)
                if coleta.referencias else [])
    item = repo.mover_item(item_id, EstadoItem.CLASSIFICANDO,
                           EstadoItem.BUSCANDO, desfechos=coleta.desfechos,
                           ocorrencias=coleta.ocorrencias, erro="") or item
    # Linhas do item = as que já existiam + o que o upsert devolveu, pela
    # mesma chave única do banco — sem reler a tabela.
    por_chave = dict(existentes)
    for gravada in gravadas:
        por_chave[(str(gravada.get("fonte_id")),
                   str(gravada.get("id_externo")))] = gravada
    linhas = list(por_chave.values())
    if modo == "automatico" and seletor is not None:
        try:
            resultado.sugestao = seletor(cotacao, item, linhas)
        except Exception as exc:  # noqa: BLE001 — IA fora não para a cotação
            resultado.ocorrencias.append(
                "análise complementar indisponível "
                f"({type(exc).__name__}); seleção determinística mantida")
    resultado.estimativa = cesta.recalcular_e_gravar(
        cotacao, item, repo, perfil=perfil, linhas=linhas)
    resultado.consideradas = len(cesta.consideradas(linhas))
    resultado.diagnostico = diagnostico_da_coleta(
        coleta, resultado.consideradas, perfil.minimo_referencias,
        estatistica.PISO_COMPARABILIDADE)
    _registrar_busca(ctx, cotacao_id, item_id, resultado, filtros_efetivos,
                     termo, inicio)
    if sincronizar:
        sincronizar_estado(cotacao_id)
    return resultado


def _registrar_busca(ctx, cotacao_id, item_id, resultado: ResultadoPesquisa,
                     filtros: dict, termo: str, inicio: float, *,
                     falhou: bool = False) -> None:
    """Cada busca na trilha — o 'IdLogPesquisa' que reabre a pesquisa."""
    resultado.duracao_s = time.monotonic() - inicio
    repo.registrar_evento(
        cotacao_id, "busca_falhou" if falhou else "busca_concluida",
        ator=ctx.auth_user_id, item_id=item_id,
        descricao=f"{resultado.modo}: {DIAGNOSTICOS[resultado.diagnostico][:120]}",
        payload={"modo": resultado.modo, "termo": termo,
                 "termos_extras": resultado.termos,
                 "filtros": {k: v for k, v in filtros.items()
                             if k in ("janela_dias", "uf", "literal",
                                      "fontes", "data_base")},
                 "desfechos": resultado.desfechos,
                 "brutas": resultado.brutas, "unicas": resultado.unicas,
                 "elegiveis": resultado.elegiveis, "novas": resultado.novas,
                 "preservadas": resultado.preservadas,
                 "consideradas": resultado.consideradas,
                 "diagnostico": resultado.diagnostico,
                 "duracao_s": round(resultado.duracao_s, 3),
                 "em": datetime.now(timezone.utc).isoformat(
                     timespec="seconds")})


def pesquisar_em_lote(ctx: Contexto, cotacao_id: str, *, modo: str,
                      item_ids: list[str] | None = None, tamanho: int = 1,
                      ja_tentados: set[str] | None = None, **opcoes
                      ) -> tuple[list[ResultadoPesquisa], int]:
    """
    Um passo da pesquisa em lote, REENTRANTE: processa até `tamanho`
    itens que ainda precisam de busca e devolve (resultados, restantes).
    O checkpoint é o estado de cada item no banco — fechar a aba não perde
    nada; 1 e 210 itens usam o mesmo contrato (pacote, 04 §Operação).
    """
    from .execucao import A_PROCESSAR

    ja_tentados = ja_tentados if ja_tentados is not None else set()
    itens = ativos(repo.listar_itens(cotacao_id))
    if item_ids is not None:
        alvo = set(map(str, item_ids))
        itens = [i for i in itens if str(i["id"]) in alvo]
    fila = [i for i in itens
            if str(i.get("estado") or "pending") in A_PROCESSAR
            and str(i["id"]) not in ja_tentados]
    resultados = []
    cotacao = repo.obter_pesquisa(cotacao_id)
    for item in fila[:max(1, tamanho)]:
        ja_tentados.add(str(item["id"]))
        try:
            # estado da cotação sincronizado UMA vez por passo, não por item
            resultados.append(pesquisar_item(ctx, cotacao_id, str(item["id"]),
                                             modo=modo, sincronizar=False,
                                             cotacao=cotacao, **opcoes))
        except (ErroCotacao, db.ErroBanco, estados.TransicaoInvalida) as exc:
            resultados.append(ResultadoPesquisa(
                item_id=str(item["id"]), modo=modo,
                diagnostico="fonte_indisponivel",
                ocorrencias=[f"item não processado: {exc}"]))
    if resultados:
        sincronizar_estado(cotacao_id)
    restantes = len([i for i in fila if str(i["id"]) not in ja_tentados])
    return resultados, restantes


# ---------------------------------------------------------------------------
# Cesta: incluir/excluir com controle de versão; concluir item
# ---------------------------------------------------------------------------
def alterar_status_referencia(ctx: Contexto, cotacao_id: str, item_id: str,
                              referencia_id: str, *, incluir: bool,
                              motivo: str,
                              revisao_esperada: int | None = None
                              ) -> estatistica.Estimativa:
    """
    Põe ou tira UMA referência da cesta, com motivo, e refaz o preço.

    Precondição de versão ANTES de mexer (outra aba mudou o item? recusa
    sem gravar). Se o conflito aparecer na escrita final, a mudança da
    referência é DESFEITA (compensação registrada no motivo) e o
    conflito sobe — nada fica meio gravado.
    """
    cotacao = _exigir_editavel(repo.obter_pesquisa(cotacao_id))
    if not str(motivo or "").strip():
        raise ErroCotacao("registre o motivo: ele vai para a memória de cálculo")
    item = repo.obter_item(item_id)
    if not item or str(item.get("pesquisa_id")) != str(cotacao_id):
        raise ErroCotacao("item não encontrado nesta cotação")
    if revisao_esperada is not None and \
            int(item.get("revisao") or 1) != int(revisao_esperada):
        raise repo.ConflitoDeVersao(
            "Este item foi alterado em outra aba ou por outra pessoa depois "
            "que você o abriu. Nada foi gravado: recarregue e refaça.")
    linhas = repo.listar_referencias(item_id)
    alvo = next((r for r in linhas if str(r["id"]) == str(referencia_id)), None)
    if alvo is None:
        raise ErroCotacao("referência não pertence a este item")
    if incluir:
        problema = _impedimento_de_inclusao(alvo)
        if problema:
            raise ErroCotacao(problema)
    anterior = str(alvo.get("status"))
    novo = "selected" if incluir else "rejected"
    repo.reclassificar_referencia(str(referencia_id), novo, motivo.strip())
    try:
        estimativa = cesta.recalcular_e_gravar(
            cotacao, item, repo,
            perfil=obter_perfil(cotacao.get("perfil_normativo")),
            revisao_esperada=revisao_esperada)
    except repo.ConflitoDeVersao:
        repo.reclassificar_referencia(
            str(referencia_id), anterior,
            "desfeito: conflito de versão com outra aba")
        raise
    repo.registrar_evento(
        cotacao_id, "referencia_incluida" if incluir else "referencia_excluida",
        ator=ctx.auth_user_id, item_id=item_id, descricao=motivo.strip(),
        payload={"referencia": str(referencia_id), "de": anterior,
                 "para": novo,
                 "preco_recalculado": None if estimativa.valor_unitario is None
                 else format(estimativa.valor_unitario, "f"),
                 "metodo": estimativa.metodo,
                 "status_da_cesta": estimativa.status})
    sincronizar_estado(cotacao_id)
    return estimativa


def _impedimento_de_inclusao(linha: dict) -> str:
    """O servidor decide se a chave pode compor cesta — não o botão."""
    if cesta._decimal(linha.get("valor_unitario_normalizado")) is None:
        return ("esta referência não tem preço na unidade do item (unidade "
                "não comprovada) e não pode compor a cesta")
    if not cesta._compoe_cesta(cesta.referencia_da_linha(linha)):
        return ("o valor desta referência não é preço praticado (ex.: "
                "estimativa de outro órgão) e não pode compor a cesta")
    return ""


def concluir_item(ctx: Contexto, cotacao_id: str, item_id: str, *,
                  justificativa: str = "",
                  revisao_esperada: int | None = None) -> dict:
    """REVISÃO → COMPLETO: o ato humano, com as mesmas exigências da cesta."""
    _exigir_editavel(repo.obter_pesquisa(cotacao_id))
    item = repo.obter_item(item_id)
    if not item or str(item.get("pesquisa_id")) != str(cotacao_id):
        raise ErroCotacao("item não encontrado nesta cotação")
    if str(item.get("estado")) != EstadoItem.EM_REVISAO.value:
        raise ErroCotacao("só item em revisão pode ser concluído — item com "
                          "menos preços que o mínimo precisa de mais "
                          "referências ou da exceção formal")
    erro = cesta.validar_conclusao(item, justificativa)
    if erro:
        raise ErroCotacao(erro)
    linha = repo.confirmar_item(item_id, justificativa=justificativa,
                                revisao_esperada=revisao_esperada)
    repo.registrar_evento(cotacao_id, "item_concluido", ator=ctx.auth_user_id,
                          item_id=item_id, descricao=justificativa.strip())
    sincronizar_estado(cotacao_id)
    return linha


def reabrir_item(ctx: Contexto, cotacao_id: str, item_id: str,
                 motivo: str) -> dict:
    """COMPLETO → REVISÃO, com motivo (o revisor mudou de ideia)."""
    _exigir_editavel(repo.obter_pesquisa(cotacao_id))
    if len(str(motivo or "").strip()) < 5:
        raise ErroCotacao("diga por que o item volta para revisão")
    linha = repo.mover_item(item_id, EstadoItem.EM_REVISAO,
                            EstadoItem.COMPLETO)
    repo.registrar_evento(cotacao_id, "item_editado", ator=ctx.auth_user_id,
                          item_id=item_id, descricao=f"reaberto: {motivo}")
    sincronizar_estado(cotacao_id)
    return linha
