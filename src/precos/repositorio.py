"""
Persistência da pesquisa de preços (migração 0021).

Três decisões governam este módulo, e as três são consequência do que o
ensaio SQL mostrou, não preferência de estilo.

**1. Aqui não se usa a credencial de servidor.**

As tabelas da 0021 concedem a `authenticated` e a mais ninguém — igual a
`processos` e `geracoes` depois da 0019. `service_role` não tem grant
nenhum. Portanto o caminho é `db.cliente_do_usuario()`, com o JWT de
quem está operando, e é o RLS do banco que decide o que a pessoa
alcança.

Sem sessão do Supabase Auth, este módulo **recusa** — não cai para
`db._cliente()`. Cair seria transformar a matriz de políticas provada em
`tests/test_precos_fase3_rls.py` em decoração: uma política que nunca é
avaliada não protege nada, e o pior é que ela *parece* proteger. É a
mesma regra que a Etapa E fixou para o resto do app.

**2. Reexecutar não duplica.**

A garantia é do BANCO — índices únicos em (item, fonte, id externo), em
(pesquisa, chave de idempotência) e em (raiz, versão). Este módulo
apenas os usa direito: `upsert` com `on_conflict` onde repetir é normal,
e releitura da linha existente onde a chave já foi gasta. Idempotência
implementada só em Python seria idempotência até a primeira corrida
entre duas abas.

**3. Estado não anda sozinho.**

Toda mudança de estado passa por `estados.transitar_*` ANTES de ir ao
banco. O CHECK do SQL impede o valor inválido; a máquina de estados
impede a ORDEM inválida — que é o defeito de verdade, porque produz um
item `complete` que ninguém pesquisou.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from .. import db, governanca
from . import estados
from .estados import EstadoItem, EstadoPesquisa
from .matching import Comparabilidade
from .modelo import Referencia

# Feature flag (§40). Ligada em nenhum lugar por esta fase: implementar
# não é ativar. O valor vem de `governanca.py`, onde moram todas as
# flags do projeto — string repetida em três arquivos é flag que um dia
# fica meio ligada.
FLAG = governanca.FLAG_PESQUISA_PRECOS

TABELA_PESQUISAS = "pesquisas_preco"
TABELA_ITENS = "pesquisa_preco_itens"
TABELA_REFERENCIAS = "pesquisa_preco_referencias"
TABELA_EVENTOS = "pesquisa_preco_eventos"

# Colunas que o `upsert` de referência atualiza quando a linha já existe.
# `bruto`, `raw_hash` e `coletado_em` FICAM como estavam: são a evidência
# do que a fonte devolveu na coleta, e reescrevê-las apagaria a prova que
# o §34 manda guardar.
_CONFLITO_REFERENCIA = "item_id,fonte_id,id_externo"

# Cabeçalho editável sem criar revisão. `processo_id` está aqui porque o
# §17-B prevê a pesquisa autônoma sendo vinculada a um processo depois.
# `valor_global` NÃO está: é derivado dos itens, e digitá-lo à mão faria
# o total divergir da soma que o sustenta.
CAMPOS_EDITAVEIS = frozenset({
    "nome", "objeto", "responsavel", "local_referencia", "data_base",
    "processo_id",
})


class SemSessao(db.ErroBanco):
    """
    Não há JWT de usuário — e o módulo não opera sem ele.

    Erro específico (e não `ErroBanco` genérico) porque a interface
    precisa saber a diferença entre "o banco falhou" e "você não está
    autenticado pelo Supabase Auth": a primeira é um incidente, a
    segunda é uma tela de login.
    """


def modulo_ativo() -> bool:
    """Feature flag do módulo. Default OFF, como manda o §40."""
    return db.flag_ativa(FLAG)


def _cliente():
    """
    Cliente com o JWT do usuário. Sem sessão, recusa.

    Não existe caminho alternativo aqui de propósito — ver o cabeçalho
    do módulo.
    """
    cliente = db.cliente_do_usuario()
    if cliente is None:
        raise SemSessao(
            "A pesquisa de preços exige sessão autenticada. Entre no "
            "sistema para continuar.")
    return cliente


# ---------------------------------------------------------------------------
# Serialização
#
# `Decimal` vira TEXTO, nunca `float`. O PostgREST envia JSON, e
# `json.dumps(float(Decimal('0.1')))` reintroduz o erro binário que o
# módulo inteiro existe para evitar. O Postgres converte o texto para
# `numeric` sem perda.
# ---------------------------------------------------------------------------
def _numero(valor: Decimal | int | float | None) -> str | None:
    if valor is None:
        return None
    return format(Decimal(str(valor)), "f")


def _data(valor: date | str | None) -> str | None:
    if valor is None or valor == "":
        return None
    return valor.isoformat() if isinstance(valor, date) else str(valor)


def linha_de_referencia(referencia: Referencia,
                        comparabilidade: Comparabilidade | None = None,
                        *, tenant_id: str, item_id: str) -> dict:
    """
    Uma referência do domínio virando linha da tabela.

    Guarda os três níveis que o §34 e o §35 pedem juntos: o que a fonte
    disse, o que o motor derivou com prova, e o payload bruto com o
    hash. Sem os três, a pesquisa não se refaz meses depois.
    """
    linha: dict[str, Any] = {
        "item_id": item_id,
        "tenant_id": tenant_id,
        "fonte_id": referencia.fonte.id,
        "fonte_nome": referencia.fonte.nome,
        "fonte_tipo": referencia.fonte.tipo,
        "id_externo": referencia.id_externo,
        "referencia_externa": referencia.referencia_externa,
        "raw_hash": referencia.raw_hash,
        "descricao_original": referencia.descricao_original,
        "unidade_original": referencia.unidade_original,
        "quantidade_original": _numero(referencia.quantidade_original),
        "valor_unitario_original": _numero(
            referencia.valor_unitario_original),
        "capacidade_embalagem": _numero(referencia.capacidade_embalagem),
        "unidade_normalizada": referencia.unidade_normalizada,
        "valor_unitario_normalizado": _numero(
            referencia.valor_unitario_normalizado),
        "codigo_catalogo": referencia.codigo_catalogo,
        "tipo_catalogo": referencia.tipo_catalogo,
        "orgao": referencia.orgao,
        "uf": referencia.uf,
        "municipio": referencia.municipio,
        "fornecedor": referencia.fornecedor,
        "ni_fornecedor": referencia.ni_fornecedor,
        "marca": referencia.marca,
        "data_compra": _data(referencia.data_compra),
        "data_resultado": _data(referencia.data_resultado),
        "status": referencia.status.value,
        "motivos": list(referencia.motivos),
        "bruto": referencia.bruto,
    }
    if comparabilidade is not None:
        relatorio = comparabilidade.para_relatorio()
        linha.update({
            "score": relatorio["score"],
            "identidade": relatorio["identidade"],
            "circunstancias": relatorio["circunstancias"],
            "fatores": relatorio["fatores"],
        })
    return linha


# ---------------------------------------------------------------------------
# Pesquisa
# ---------------------------------------------------------------------------
def criar_pesquisa(nome: str, *, auth_user_id: str,
                   secretaria_id: str | None = None,
                   processo_id: str | None = None,
                   objeto: str = "", responsavel: str = "",
                   local_referencia: str = "",
                   data_base: date | str | None = None,
                   perfil_normativo: str = "lei_14133",
                   filtros: dict | None = None,
                   versao_algoritmo: str = "", versao_regras: str = "",
                   idempotency_key: str = "") -> dict:
    """
    Cria a pesquisa em RASCUNHO e devolve a linha.

    Com `idempotency_key`, reexecutar devolve a pesquisa que já existe
    em vez de criar a segunda — inclusive na corrida entre duas abas,
    resolvida pelo índice único do banco e não por esta função.
    """
    if idempotency_key:
        existente = obter_por_chave(idempotency_key)
        if existente:
            return existente

    registro = {
        "tenant_id": db.tenant_atual(),
        "auth_user_id": auth_user_id,
        "secretaria_id": secretaria_id,
        "processo_id": processo_id,
        "nome": nome,
        "objeto": objeto,
        "responsavel": responsavel,
        "local_referencia": local_referencia,
        "data_base": _data(data_base),
        "perfil_normativo": perfil_normativo,
        "estado": EstadoPesquisa.RASCUNHO.value,
        "filtros": filtros or {},
        "versao_algoritmo": versao_algoritmo,
        "versao_regras": versao_regras,
        "idempotency_key": idempotency_key,
    }
    try:
        resposta = _cliente().table(TABELA_PESQUISAS).insert(
            registro).execute()
        return resposta.data[0]
    except SemSessao:
        raise
    except Exception as exc:  # noqa: BLE001
        # A corrida perdida cai aqui: a outra aba gravou primeiro e o
        # índice único recusou. Devolver a linha dela é o comportamento
        # idempotente correto.
        texto = str(exc).lower()
        if idempotency_key and ("duplicate" in texto or "unique" in texto):
            existente = obter_por_chave(idempotency_key)
            if existente:
                return existente
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def obter_por_chave(idempotency_key: str) -> dict | None:
    if not idempotency_key:
        return None
    try:
        resposta = (
            _cliente().table(TABELA_PESQUISAS).select("*")
            .eq("idempotency_key", idempotency_key).limit(1).execute())
        return resposta.data[0] if resposta.data else None
    except SemSessao:
        raise
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def obter_pesquisa(pesquisa_id: str) -> dict | None:
    try:
        resposta = (
            _cliente().table(TABELA_PESQUISAS).select("*")
            .eq("id", pesquisa_id).limit(1).execute())
        return resposta.data[0] if resposta.data else None
    except SemSessao:
        raise
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def listar_pesquisas(limite: int = 20,
                     processo_id: str | None = None) -> list[dict]:
    """
    Pesquisas mais recentes que o usuário alcança.

    Sem filtro de tenant nesta consulta, e é proposital: o filtro é do
    RLS. Repeti-lo aqui daria a impressão de que a segurança está no
    aplicativo — e faria a política deixar de ser exercitada.
    """
    try:
        consulta = (
            _cliente().table(TABELA_PESQUISAS)
            .select("id, nome, objeto, estado, versao, raiz_id, "
                    "valor_global, processo_id, atualizado_em"))
        if processo_id:
            consulta = consulta.eq("processo_id", processo_id)
        resposta = (consulta.order("atualizado_em", desc=True)
                    .limit(limite).execute())
        return resposta.data or []
    except SemSessao:
        raise
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def mover_pesquisa(pesquisa_id: str, destino: EstadoPesquisa,
                   atual: EstadoPesquisa | str | None = None) -> dict:
    """
    Muda o estado da pesquisa, validando a transição ANTES de gravar.

    `atual` pode ser passado por quem já tem a linha em mãos; sem ele, a
    função lê. Ler é o caminho seguro — o estado pode ter mudado em
    outra aba —, e por isso é o padrão.
    """
    if atual is None:
        linha = obter_pesquisa(pesquisa_id)
        if not linha:
            raise db.ErroBanco("Pesquisa de preços não encontrada.")
        atual = linha["estado"]
    origem = EstadoPesquisa(atual)
    estados.transitar_pesquisa(origem, destino)   # levanta se não valer

    campos: dict[str, Any] = {"estado": destino.value}
    if destino is EstadoPesquisa.APLICADA:
        # Timestamp em ISO, não a string 'now()': o corpo vai como JSON
        # e o Postgres tentaria converter o literal 'now()' para
        # timestamptz — o que falha.
        campos["aplicada_em"] = datetime.now(timezone.utc).isoformat()
    try:
        resposta = (_cliente().table(TABELA_PESQUISAS)
                    .update(campos).eq("id", pesquisa_id).execute())
        if not resposta.data:
            # RLS de UPDATE filtra em silêncio: zero linhas significa
            # "você não escreve nesta pesquisa", não "sumiu".
            raise db.ErroBanco(
                "Não foi possível alterar esta pesquisa de preços.")
        return resposta.data[0]
    except db.ErroBanco:
        raise
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def atualizar_pesquisa(pesquisa_id: str, **campos) -> dict:
    """
    Campos do cabeçalho que NÃO versionam (nome, objeto, responsável…).

    A regra é uma LISTA DE PERMITIDOS, não de proibidos. Com lista de
    proibidos, `estado` passava — e escrever `estado` por aqui pularia a
    máquina de estados inteira, que é justamente o que ela existe para
    impedir. Lista de permitidos também não envelhece: coluna nova nasce
    fechada em vez de nascer aberta.

    Cada recusa aponta o caminho certo em vez de só negar: `estado` vai
    por `mover_pesquisa`, o que muda o resultado vai por `revisar` (§44).
    Corrigir a grafia do nome não é revisão da pesquisa; trocar o método
    é, porque muda o valor que vai para o processo.
    """
    if estados.exige_nova_revisao(campos):
        proibidos = sorted(estados.CAMPOS_QUE_VERSIONAM & set(campos))
        raise ValueError(
            f"{', '.join(proibidos)}: alterar isto cria revisão nova — "
            "use `revisar()`, que preserva o histórico")
    if "estado" in campos:
        raise ValueError(
            "estado: use `mover_pesquisa()`, que valida a transição — "
            "escrever o estado direto pula a máquina de estados")
    fora = sorted(set(campos) - CAMPOS_EDITAVEIS)
    if fora:
        raise ValueError(
            f"{', '.join(fora)}: não é campo editável do cabeçalho "
            f"(editáveis: {', '.join(sorted(CAMPOS_EDITAVEIS))})")
    if "data_base" in campos:
        campos["data_base"] = _data(campos["data_base"])
    try:
        resposta = (_cliente().table(TABELA_PESQUISAS)
                    .update(campos).eq("id", pesquisa_id).execute())
        if not resposta.data:
            raise db.ErroBanco(
                "Não foi possível alterar esta pesquisa de preços.")
        return resposta.data[0]
    except db.ErroBanco:
        raise
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def revisar(pesquisa_id: str, motivo: str = "") -> str:
    """
    Cria a revisão lógica (§44) e devolve o id da nova pesquisa.

    O trabalho é da RPC `revisar_pesquisa_preco`: copiar cabeçalho,
    itens e referências dentro do banco, numa transação só. Uma pesquisa
    de 210 itens tem ~6.300 referências — trazê-las para o Python e
    reescrevê-las seria lento e, pior, não atômico.
    """
    try:
        resposta = _cliente().rpc(
            "revisar_pesquisa_preco",
            {"p_pesquisa": pesquisa_id, "p_motivo": motivo}).execute()
        return resposta.data
    except SemSessao:
        raise
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def historico(pesquisa_id: str) -> list[dict]:
    """
    Todas as revisões da mesma pesquisa lógica, da primeira à vigente.

    `raiz_id` é nulo na primeira revisão, então a chave da linhagem é
    `coalesce(raiz_id, id)`. Como o PostgREST não expressa `coalesce`
    num filtro, a raiz é resolvida em duas consultas — que é o preço de
    não guardar a raiz repetida em cada linha.
    """
    linha = obter_pesquisa(pesquisa_id)
    if not linha:
        return []
    raiz = linha.get("raiz_id") or linha["id"]
    try:
        resposta = (
            _cliente().table(TABELA_PESQUISAS)
            .select("id, versao, estado, motivo_da_revisao, valor_global, "
                    "criado_em, revisao_de")
            .or_(f"id.eq.{raiz},raiz_id.eq.{raiz}")
            .order("versao").execute())
        return resposta.data or []
    except SemSessao:
        raise
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


# ---------------------------------------------------------------------------
# Itens
# ---------------------------------------------------------------------------
def salvar_itens(pesquisa_id: str, itens: list[dict]) -> list[dict]:
    """
    Grava os itens da pesquisa. Reexecutar com os mesmos números
    ATUALIZA em vez de duplicar — a chave é (pesquisa, número).

    É o que torna a importação da planilha repetível: importar duas
    vezes a mesma planilha de 210 itens deixa 210 itens, não 420.
    """
    if not itens:
        return []
    tenant = db.tenant_atual()
    registros = []
    for posicao, item in enumerate(itens, start=1):
        registros.append({
            "pesquisa_id": pesquisa_id,
            "tenant_id": tenant,
            "numero": int(item.get("numero") or posicao),
            "codigo": item.get("codigo") or None,
            "tipo_catalogo": item.get("tipo_catalogo") or None,
            "descricao": item.get("descricao") or "",
            "unidade": item.get("unidade") or "",
            "quantidade": _numero(item.get("quantidade")),
            "estado": EstadoItem(
                item.get("estado") or EstadoItem.PENDENTE).value,
        })
    try:
        resposta = (_cliente().table(TABELA_ITENS)
                    .upsert(registros, on_conflict="pesquisa_id,numero")
                    .execute())
        return resposta.data or []
    except SemSessao:
        raise
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def listar_itens(pesquisa_id: str) -> list[dict]:
    try:
        resposta = (_cliente().table(TABELA_ITENS).select("*")
                    .eq("pesquisa_id", pesquisa_id).order("numero").execute())
        return resposta.data or []
    except SemSessao:
        raise
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def mover_item(item_id: str, destino: EstadoItem,
               atual: EstadoItem | str, **campos) -> dict:
    """
    Muda o estado do item — validando a transição — e, no mesmo write,
    grava o que aquele estado produziu.

    Uma chamada só, de propósito: gravar o preço e mudar o estado em
    dois writes deixa uma janela em que o item está `complete` sem
    preço, e é essa a linha que a tela de resumo lê.
    """
    estados.transitar_item(EstadoItem(atual), destino)
    campos["estado"] = destino.value
    for chave in ("preco_estimado", "preco_total", "quantidade"):
        if chave in campos:
            campos[chave] = _numero(campos[chave])
    try:
        resposta = (_cliente().table(TABELA_ITENS)
                    .update(campos).eq("id", item_id).execute())
        if not resposta.data:
            raise db.ErroBanco("Não foi possível alterar este item.")
        return resposta.data[0]
    except db.ErroBanco:
        raise
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def registrar_estimativa(item_id: str, estimativa, *,
                         atual: EstadoItem | str,
                         quantidade: Decimal | None = None) -> dict:
    """
    Grava o resultado de `estatistica.estimar` e manda o item para
    REVISÃO — não para concluído.

    A distinção não é burocracia. O motor terminou de calcular; quem
    conclui é a pessoa que olha a cesta, os discrepantes e a memória de
    cálculo (§20). Um item que passasse de `matching` direto a
    `complete` produziria pesquisa "concluída" que ninguém leu, e é
    exatamente o que a máquina de estados recusa.

    A `Estimativa` decide entre REVISÃO e INCOMPLETO, não quem chama:
    deixar o chamador escolher permitiria mandar para revisão um item
    cuja cesta não fechou a regra dos três, como se houvesse o que
    aprovar.
    """
    destino = (EstadoItem.EM_REVISAO if estimativa.concluida
               else EstadoItem.INCOMPLETO)
    return mover_item(
        item_id, destino, atual,
        metodo=estimativa.metodo,
        preco_estimado=estimativa.valor_unitario,
        preco_total=estimativa.valor_total(quantidade),
        estatisticas=estimativa.para_relatorio(),
        justificativa="\n".join(estimativa.memoria))


def confirmar_item(item_id: str, *, atual: EstadoItem | str = EstadoItem.EM_REVISAO,
                   justificativa: str = "") -> dict:
    """
    O ato humano que fecha o item: REVISÃO → COMPLETO.

    Só sai daqui item que passou pela revisão. `justificativa`, quando
    vem, é acrescentada à memória de cálculo — é onde o revisor registra
    por que aceitou uma cesta com discrepantes sinalizados, por exemplo.
    """
    campos: dict[str, Any] = {}
    if justificativa.strip():
        campos["justificativa"] = justificativa
    return mover_item(item_id, EstadoItem.COMPLETO, atual, **campos)


# ---------------------------------------------------------------------------
# Referências
# ---------------------------------------------------------------------------
def registrar_referencias(
        item_id: str, coletadas: list[Referencia] | list[tuple],
        ) -> list[dict]:
    """
    Grava as referências do item. Pesquisar de novo NÃO duplica.

    Aceita `Referencia` ou o par `(Referencia, Comparabilidade)` que
    `ordenar_por_comparabilidade` devolve — assim o score explicado
    entra na mesma escrita, e não numa segunda passada que poderia
    falhar deixando referência sem explicação.

    A unicidade é (item, fonte, id externo). Em conflito, ATUALIZA o que
    o motor derivou (unidade, valor normalizado, score, status) e
    PRESERVA a evidência (`bruto`, `raw_hash`, `coletado_em`): a segunda
    coleta pode reclassificar, nunca reescrever o que a fonte devolveu
    na primeira.
    """
    if not coletadas:
        return []
    tenant = db.tenant_atual()
    registros = []
    for entrada in coletadas:
        if isinstance(entrada, tuple):
            referencia, comparabilidade = entrada[0], entrada[1]
        else:
            referencia, comparabilidade = entrada, None
        registros.append(linha_de_referencia(
            referencia, comparabilidade,
            tenant_id=tenant, item_id=item_id))
    try:
        resposta = (_cliente().table(TABELA_REFERENCIAS)
                    .upsert(registros, on_conflict=_CONFLITO_REFERENCIA)
                    .execute())
        return resposta.data or []
    except SemSessao:
        raise
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def listar_referencias(item_id: str,
                       status: str | None = None) -> list[dict]:
    try:
        consulta = (_cliente().table(TABELA_REFERENCIAS).select("*")
                    .eq("item_id", item_id))
        if status:
            consulta = consulta.eq("status", status)
        resposta = consulta.order("score", desc=True).execute()
        return resposta.data or []
    except SemSessao:
        raise
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def reclassificar_referencia(referencia_id: str, status: str,
                             motivo: str) -> dict:
    """
    Inclui ou exclui uma referência da cesta.

    Exclusão é MUDANÇA DE STATUS, com motivo obrigatório — não é
    apagar. A 0021 não concede DELETE a ninguém justamente para que este
    seja o único caminho: preço coletado que some sem rastro é o oposto
    de pesquisa auditável.
    """
    if not motivo.strip():
        raise ValueError(
            "excluir ou incluir referência exige motivo registrado")
    try:
        atual = (_cliente().table(TABELA_REFERENCIAS).select("motivos")
                 .eq("id", referencia_id).limit(1).execute())
        motivos = list(atual.data[0]["motivos"]) if atual.data else []
        if motivo not in motivos:
            motivos.append(motivo)
        resposta = (_cliente().table(TABELA_REFERENCIAS)
                    .update({"status": status, "motivos": motivos})
                    .eq("id", referencia_id).execute())
        if not resposta.data:
            raise db.ErroBanco("Não foi possível alterar esta referência.")
        return resposta.data[0]
    except db.ErroBanco:
        raise
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


# ---------------------------------------------------------------------------
# Trilha
# ---------------------------------------------------------------------------
def registrar_evento(pesquisa_id: str, tipo: str, *,
                     ator: str | None = None, item_id: str | None = None,
                     descricao: str = "", payload: dict | None = None,
                     automatico: bool = False,
                     idempotency_key: str = "") -> dict | None:
    """
    Registra um ato na trilha. Reexecutar com a mesma chave não duplica.

    Devolve `None` quando a chave já foi gasta — o evento já está lá, e
    quem chamou não precisa distinguir "gravei agora" de "já estava
    gravado". O gatilho do banco confere que `ator` é quem está
    autenticado; passar outro é recusado com 42501.

    A trilha é registro, não regra de negócio: falha ao gravá-la NÃO
    derruba a operação que ela descreve. Mas também não é engolida —
    vira incidente com identificador de correlação, do mesmo jeito que
    o resto do app faz.
    """
    registro = {
        "pesquisa_id": pesquisa_id,
        "tenant_id": db.tenant_atual(),
        "item_id": item_id,
        "ator": ator,
        "automatico": automatico,
        "tipo": tipo,
        "descricao": descricao,
        "payload": payload or {},
        "idempotency_key": idempotency_key,
    }
    try:
        resposta = _cliente().table(TABELA_EVENTOS).insert(
            registro).execute()
        return resposta.data[0] if resposta.data else None
    except SemSessao:
        raise
    except Exception as exc:  # noqa: BLE001
        texto = str(exc).lower()
        if idempotency_key and ("duplicate" in texto or "unique" in texto):
            return None
        db.registrar_incidente(exc, contexto="trilha da pesquisa de preços")
        return None


def listar_eventos(pesquisa_id: str, limite: int = 200) -> list[dict]:
    try:
        resposta = (_cliente().table(TABELA_EVENTOS).select("*")
                    .eq("pesquisa_id", pesquisa_id)
                    .order("criado_em", desc=True).limit(limite).execute())
        return resposta.data or []
    except SemSessao:
        raise
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001
