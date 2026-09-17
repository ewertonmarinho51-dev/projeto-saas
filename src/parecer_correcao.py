"""
Do parecer jurídico à correção dos documentos — a camada processual.

Não é um segundo módulo de parecer. `pareceres.py` continua dono da
ingestão, do hash contra duplicata, da extração de texto, da análise com
defesa contra prompt injection e da persistência em `parecer_achados`.
O que entra aqui é o passo seguinte, que não existia:

    achado → classificação → plano global → patches → nova versão

E nada disso é motor novo. O plano é validado por `corretor.validar_plano`
e aplicado por `patches.aplicar_plano`, que já recusam caminho fora de
escopo, cláusula fixa de governança, bloco inexistente e — o que o §30
pede — patch calculado sobre uma versão que ficou obsoleta. Reescrever
esse motor aqui seria criar um caminho paralelo com menos guardas.

O que "correção automática" significa e o que não significa
-----------------------------------------------------------
Corrige sozinho o que é objetivamente mapeável a um bloco existente:
troca de texto, inclusão de cláusula claramente indicada, ajuste de
nomenclatura. Não inventa quantitativo, valor, prazo, responsável nem
modalidade — nada disso está no parecer, e preencher com um palpite
transformaria uma recomendação jurídica em decisão administrativa
tomada por software.

Quando falta dado, o achado vira PERGUNTA. Quando falta decisão, vira
PENDÊNCIA nominal do servidor. As duas aparecem no relatório de
atendimento com essa palavra, não como "não foi possível".

O texto do parecer é DADO
-------------------------
Vale aqui a mesma regra de `pareceres.py`: um parecer que contenha
"ignore as instruções anteriores" ou "execute o seguinte SQL" é um
documento com aquele texto dentro, e nada mais. Esta camada não executa
SQL, não lê segredo, não toca configuração e não publica nada — ela só
propõe operações sobre blocos de documento, que o motor de patch depois
valida uma segunda vez.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from . import blocos, config

# ---------------------------------------------------------------------------
# §19 — a situação de cada apontamento
#
# São nomes de TELA além de constantes: é o que o servidor lê no relatório
# de atendimento, e por isso dizem o que ele precisa fazer, não o estado
# interno do sistema.
# ---------------------------------------------------------------------------
JA_ATENDIDO = "JA_ATENDIDO"
CORRECAO_AUTOMATICA = "CORRECAO_AUTOMATICA"
EXIGE_DADO_FALTANTE = "EXIGE_DADO_FALTANTE"
EXIGE_DECISAO_ADMINISTRATIVA = "EXIGE_DECISAO_ADMINISTRATIVA"
AMBIGUO = "AMBIGUO"
CONFLITANTE = "CONFLITANTE"
NAO_APLICAVEL = "NAO_APLICAVEL"

SITUACOES = (
    JA_ATENDIDO, CORRECAO_AUTOMATICA, EXIGE_DADO_FALTANTE,
    EXIGE_DECISAO_ADMINISTRATIVA, AMBIGUO, CONFLITANTE, NAO_APLICAVEL,
)

ROTULO_DA_SITUACAO = {
    JA_ATENDIDO: "Já atendido",
    CORRECAO_AUTOMATICA: "Corrigido automaticamente",
    EXIGE_DADO_FALTANTE: "Exige informação que não está no processo",
    EXIGE_DECISAO_ADMINISTRATIVA: "Exige decisão do servidor",
    AMBIGUO: "Recomendação ambígua — precisa de leitura humana",
    CONFLITANTE: "Conflita com outra recomendação do mesmo parecer",
    NAO_APLICAVEL: "Não se aplica a este processo",
}

# Carimbo do §26. Correção automática não é aprovação administrativa, e
# o documento alterado volta para a fila de revisão.
CARIMBO_PENDENTE = "CORRIGIDO PELO PARECER — PENDENTE DE REVISÃO/APROVAÇÃO"

# ---------------------------------------------------------------------------
# §20 — o que o parecer NÃO pode decidir sozinho
#
# Estes termos não bloqueiam por serem "palavras proibidas": bloqueiam
# porque o dado correspondente não existe no parecer nem no processo, e
# preencher exigiria escolher em nome da Administração. A lista é
# deliberadamente curta e explícita — heurística ampla demais recusaria
# correção legítima e devolveria o servidor ao trabalho manual.
# ---------------------------------------------------------------------------
_PEDE_DECISAO = (
    "modalidade", "critério de julgamento", "criterio de julgamento",
    "definir o responsável", "definir o responsavel",
    "indicar o responsável", "indicar o responsavel",
    "decisão da administração", "decisao da administracao",
    "juízo de conveniência", "juizo de conveniencia",
    "a critério da administração", "a criterio da administracao",
)
_PEDE_DADO = (
    "informar o valor", "informar a quantidade", "informar o prazo",
    "incluir o valor", "incluir a quantidade", "incluir o prazo",
    "estimativa de", "dotação orçamentária", "dotacao orcamentaria",
    "número do processo", "numero do processo",
)
_AMBIGUO = ("ou, alternativamente", "caso entenda", "se for o caso",
            "eventualmente", "poderá optar", "podera optar")


class ErroCorrecaoParecer(Exception):
    """Recusa deliberada antes de tocar em documento do processo."""


@dataclass(frozen=True, slots=True)
class Apontamento:
    """Um achado do parecer, já situado no processo."""

    id: str
    problema: str
    recomendacao: str
    fundamento: str
    documento: str
    clausula: str
    gravidade: str
    confianca: float
    situacao: str
    motivo: str = ""
    caminhos: tuple[str, ...] = ()
    evidencias: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Plano:
    """
    O plano GLOBAL do §22: montado inteiro antes da primeira alteração.

    Existe como objeto próprio para que a ordem das correções seja
    decidida uma vez, com o parecer todo à vista — e não documento a
    documento, onde uma recomendação sobre o Edital seria aplicada sem
    saber que outra vai mudar o ETP de onde ele deriva.
    """

    lote: str
    apontamentos: tuple[Apontamento, ...] = ()
    snapshot: dict = field(default_factory=dict)
    ordem: tuple[str, ...] = ()
    # O texto literal de cada documento antes da primeira alteração. O
    # snapshot guarda blocos e hashes, que provam integridade mas não
    # reconstroem o original byte a byte — e "desfazer" precisa devolver
    # exatamente o que estava lá, não uma reconstrução plausível.
    original: dict = field(default_factory=dict)


def _texto(valor) -> str:
    return str(valor or "").strip()


def _contem(agulha_s, palheiro: str) -> str:
    baixo = palheiro.lower()
    for agulha in agulha_s:
        if agulha in baixo:
            return agulha
    return ""


def _documento_do_achado(achado: dict, documentos: dict) -> str:
    """
    A qual documento do processo o achado se refere.

    Aceita a sigla ("TR") e a chave ("tr"), porque o parecer é escrito
    por gente e a IA devolve o que leu. Documento que o processo não tem
    não vira erro: vira NAO_APLICAVEL, com o motivo dito.
    """
    bruto = _texto(achado.get("documento_afetado")).lower()
    if not bruto:
        return ""
    for chave, meta in config.DOCUMENTOS.items():
        sigla = str(meta.get("sigla", "")).lower()
        if bruto == chave or bruto == sigla or sigla and sigla in bruto:
            return chave if chave in documentos else ""
    return bruto if bruto in documentos else ""


def _caminhos(doc_key: str, achado: dict, documentos: dict) -> list[str]:
    """
    Os blocos que a recomendação pode tocar.

    Quando o parecer nomeia a cláusula, o escopo é ela. Quando não
    nomeia, NÃO vira "o documento inteiro": sem alvo identificado a
    correção não é objetiva, e o achado sai como ambíguo. Autorizar o
    documento todo daria ao patch uma licença que ninguém concedeu.
    """
    if not doc_key:
        return []
    lista = blocos.dividir_em_blocos(doc_key, documentos.get(doc_key) or "")
    caminhos = [b["path"] for b in lista]
    alvo = _texto(achado.get("clausula_afetada")).lower()
    if not alvo:
        return []
    exatos = [p for p in caminhos if alvo in p.lower()]
    if exatos:
        return exatos
    # O parecer costuma citar a cláusula pelo nome ("CLÁUSULA SEGUNDA"),
    # não pelo caminho interno. Procura no rótulo da cláusula e, em
    # último caso, no texto do bloco — nessa ordem, porque casar pelo
    # conteúdo é mais frouxo e só vale quando nada mais casou.
    por_clausula = [b["path"] for b in lista
                    if alvo in _texto(b.get("clausula")).lower()]
    if por_clausula:
        return por_clausula
    return [b["path"] for b in lista
            if alvo in _texto(b.get("conteudo")).lower()]


def classificar(achado: dict, documentos: dict, dados: dict | None = None) -> tuple[str, str]:
    """
    Devolve `(situação, motivo)` para um achado. Sem tocar em nada.

    A ordem das perguntas é a ordem da precedência e ela importa: um
    achado que exige decisão administrativa continua exigindo mesmo que
    aponte para uma cláusula existente, e um achado sobre documento que
    o processo não tem não vira pendência do servidor — vira não
    aplicável.
    """
    doc_key = _documento_do_achado(achado, documentos)
    if not doc_key:
        return NAO_APLICAVEL, (
            "O parecer aponta um documento que este processo não tem.")

    texto = f"{_texto(achado.get('problema'))} {_texto(achado.get('correcao_solicitada'))}"

    achado_termo = _contem(_PEDE_DECISAO, texto)
    if achado_termo:
        return EXIGE_DECISAO_ADMINISTRATIVA, (
            f"A recomendação depende de uma escolha da Administração "
            f"({achado_termo}). O sistema não decide no lugar do servidor.")

    achado_termo = _contem(_PEDE_DADO, texto)
    if achado_termo:
        return EXIGE_DADO_FALTANTE, (
            f"A recomendação pede uma informação que não está no processo "
            f"({achado_termo}). Preencher exigiria inventar o número.")

    achado_termo = _contem(_AMBIGUO, texto)
    if achado_termo:
        return AMBIGUO, (
            "A recomendação oferece mais de um caminho possível e não diz "
            "qual seguir.")

    if not _texto(achado.get("correcao_solicitada")):
        return AMBIGUO, (
            "O parecer aponta o problema mas não diz o que colocar no "
            "lugar.")

    caminhos = _caminhos(doc_key, achado, documentos)
    if not caminhos:
        return AMBIGUO, (
            "Não foi possível localizar no documento a cláusula citada "
            "pelo parecer.")

    return CORRECAO_AUTOMATICA, ""


def situar(achados: list[dict], documentos: dict,
           dados: dict | None = None) -> tuple[Apontamento, ...]:
    """
    Classifica o parecer INTEIRO antes de qualquer alteração (§22).

    Também é aqui que o conflito entre recomendações aparece: duas
    recomendações que mandam mexer no mesmo bloco não podem ser
    aplicadas às cegas, porque a segunda escreveria por cima da primeira
    e o parecer sairia atendido pela metade sem ninguém notar.
    """
    situados: list[Apontamento] = []
    for n, achado in enumerate(achados, start=1):
        situacao, motivo = classificar(achado, documentos, dados)
        doc_key = _documento_do_achado(achado, documentos)
        caminhos = _caminhos(doc_key, achado, documentos) if doc_key else []
        situados.append(Apontamento(
            id=f"A{n:03d}",
            problema=_texto(achado.get("problema")),
            recomendacao=_texto(achado.get("correcao_solicitada")),
            fundamento=_texto(achado.get("fundamento")),
            documento=doc_key,
            clausula=_texto(achado.get("clausula_afetada")),
            gravidade=_texto(achado.get("gravidade")) or "MEDIUM",
            confianca=float(achado.get("confianca") or 0.5),
            situacao=situacao,
            motivo=motivo,
            caminhos=tuple(caminhos),
            evidencias=tuple(achado.get("evidencias") or ()),
        ))

    return _marcar_conflitos(tuple(situados))


def _marcar_conflitos(apontamentos: tuple[Apontamento, ...]) -> tuple[Apontamento, ...]:
    """Dois automáticos disputando o mesmo bloco viram CONFLITANTE."""
    from dataclasses import replace

    contagem: dict[str, int] = {}
    for a in apontamentos:
        if a.situacao != CORRECAO_AUTOMATICA:
            continue
        for caminho in a.caminhos:
            contagem[caminho] = contagem.get(caminho, 0) + 1

    resultado = []
    for a in apontamentos:
        disputado = [c for c in a.caminhos if contagem.get(c, 0) > 1]
        if a.situacao == CORRECAO_AUTOMATICA and disputado:
            resultado.append(replace(
                a, situacao=CONFLITANTE,
                motivo=("Outra recomendação do mesmo parecer também manda "
                        f"alterar {disputado[0]}. Aplicar as duas às cegas "
                        "faria a segunda escrever por cima da primeira.")))
        else:
            resultado.append(a)
    return tuple(resultado)


def ordenar(apontamentos) -> tuple[Apontamento, ...]:
    """
    De montante para jusante (§23): DFD → ETP → TR → Edital → ARP.

    A ordem não é estética. O Edital deriva do TR, que deriva do ETP:
    corrigir o Edital primeiro e o ETP depois deixaria o Edital apoiado
    numa versão que deixou de existir no meio da própria execução.
    """
    ordem = list(config.SEQUENCIA_DOCUMENTOS)
    for chave in config.DOCUMENTOS:
        if chave not in ordem:
            ordem.append(chave)

    def posicao(a: Apontamento) -> tuple[int, str]:
        try:
            return ordem.index(a.documento), a.id
        except ValueError:
            return len(ordem), a.id

    return tuple(sorted(apontamentos, key=posicao))


def planejar(achados: list[dict], documentos: dict,
             dados: dict | None = None) -> Plano:
    """
    O plano global, com snapshot de TODOS os documentos (§22).

    O snapshot é tirado antes da primeira alteração e é ele que o §25
    usa para desfazer. Tirá-lo documento a documento, à medida que cada
    um fosse corrigido, guardaria estados de instantes diferentes — e
    "desfazer" devolveria o processo a um momento que nunca existiu.
    """
    situados = ordenar(situar(achados, documentos, dados))
    return Plano(
        lote=uuid.uuid4().hex,
        apontamentos=situados,
        snapshot=blocos.snapshot_bundle(documentos),
        ordem=tuple(a.documento for a in situados if a.documento),
        original=dict(documentos),
    )


def aplicar(plano: Plano, documentos: dict, aprovados=None, *,
            gerar=None, aplicar_patch=None) -> dict:
    """
    Executa o plano e devolve o estado novo do processo.

    Devolve sempre um dicionário com `documentos`, `aprovados`, `diff`,
    `relatorio` e `aplicados` — mesmo quando nada foi aplicado. Não
    levanta exceção por não haver correção automática: parecer sem
    correção objetiva é um resultado legítimo, e transformá-lo em erro
    faria a tela mostrar falha onde houve análise.

    O patch em si é montado e validado pelo motor que já existe. Se ele
    recusar — caminho fora de escopo, cláusula fixa de governança, hash
    de origem divergente — a recusa vira FALHA no relatório e **nenhum
    documento é alterado**: `patches.aplicar_plano` trabalha em cópia e
    só devolve o novo bundle quando todas as pós-condições passam.
    """
    from . import corretor, patches

    gerar = gerar or corretor.gerar_plano
    aplicar_patch = aplicar_patch or patches.aplicar_plano

    relatorio = relatorio_de_findings(plano)
    corrigiveis = [f for f in relatorio["findings"] if f["autoCorrectable"]]
    if not corrigiveis:
        return {
            "documentos": dict(documentos),
            "aprovados": set(aprovados or set()),
            "diff": {},
            "aplicados": (),
            "relatorio": relatorio_de_atendimento(plano),
        }

    falhas: dict[str, str] = {}
    try:
        plano_patch = gerar(relatorio, documentos, {}, )
    except Exception as exc:  # noqa: BLE001 — recusa do motor é caso previsto
        for f in corrigiveis:
            falhas[f["findingId"]] = str(exc)[:200]
        return {
            "documentos": dict(documentos),
            "aprovados": set(aprovados or set()),
            "diff": {},
            "aplicados": (),
            "relatorio": relatorio_de_atendimento(plano, falhas=falhas),
        }

    try:
        resultado = aplicar_patch(plano_patch, documentos, relatorio)
    except Exception as exc:  # noqa: BLE001
        for f in corrigiveis:
            falhas[f["findingId"]] = str(exc)[:200]
        return {
            "documentos": dict(documentos),
            "aprovados": set(aprovados or set()),
            "diff": {},
            "aplicados": (),
            "relatorio": relatorio_de_atendimento(plano, falhas=falhas),
        }

    diff = resultado.get("diff") or {}
    alterados = documentos_alterados(diff)
    aplicados = tuple(
        op["findingId"] for op in (plano_patch.get("operations") or []))
    return {
        "documentos": resultado.get("documentos") or dict(documentos),
        # §26: correção automática não é aprovação administrativa.
        "aprovados": retirar_aprovacoes(aprovados, alterados),
        "diff": diff,
        "alterados": alterados,
        "aplicados": aplicados,
        "relatorio": relatorio_de_atendimento(plano, aplicados, falhas),
    }


def desfazer(plano: Plano) -> dict:
    """
    §25: devolve os documentos exatamente como estavam antes do parecer.

    Restaura o texto literal guardado no plano, não uma reconstrução a
    partir dos blocos. A versão pré-parecer nunca é destruída — desfazer
    é copiar de volta, não recalcular.
    """
    if not plano.original:
        raise ErroCorrecaoParecer(
            "Este lote não guardou o estado anterior; não é possível "
            "desfazer com segurança.")
    return dict(plano.original)


def relatorio_de_findings(plano: Plano) -> dict:
    """
    Traduz o plano para o contrato que `corretor` e `patches` já falam.

    É a peça que permite reusar o motor de patch inteiro em vez de
    escrever um segundo. `autoCorrectable` só é verdadeiro para a
    situação CORRECAO_AUTOMATICA — as demais chegam ao motor já
    marcadas como não corrigíveis, e ele recusaria de qualquer forma.
    """
    findings = []
    for a in plano.apontamentos:
        findings.append({
            "findingId": a.id,
            "documentId": a.documento,
            "clauseId": a.clausula or None,
            "categoria": "parecer_juridico",
            "severity": a.gravidade,
            "descricao": a.problema,
            "evidencia": list(a.evidencias),
            "regraViolada": a.fundamento,
            "resultadoEsperado": a.recomendacao,
            "autoCorrectable": a.situacao == CORRECAO_AUTOMATICA,
            "allowedPaths": list(a.caminhos),
            "blockedPaths": [],
            "sourceIds": [],
            "blockingReason": a.motivo or None,
        })
    return {"findings": findings}


def contagem(plano: Plano) -> dict:
    """O placar do §28, por situação."""
    placar = {s: 0 for s in SITUACOES}
    for a in plano.apontamentos:
        placar[a.situacao] = placar.get(a.situacao, 0) + 1
    return placar


def relatorio_de_atendimento(plano: Plano, aplicados: tuple[str, ...] = (),
                             falhas: dict | None = None) -> dict:
    """
    O que aconteceu com CADA apontamento (§28).

    Um apontamento classificado como automático que não chegou a ser
    aplicado não some do relatório: aparece como falha, com o motivo. Um
    relatório que só listasse sucessos deixaria o servidor achando que o
    parecer foi inteiramente atendido.
    """
    falhas = falhas or {}
    linhas = []
    for a in plano.apontamentos:
        if a.situacao == CORRECAO_AUTOMATICA and a.id in aplicados:
            estado, detalhe = "ATENDIDO", ""
        elif a.situacao == CORRECAO_AUTOMATICA:
            estado = "FALHOU"
            detalhe = falhas.get(a.id, "A correção não pôde ser aplicada.")
        else:
            estado, detalhe = a.situacao, a.motivo
        linhas.append({
            "id": a.id,
            "documento": a.documento,
            "clausula": a.clausula,
            "parecer": a.problema,
            "recomendacao": a.recomendacao,
            "fundamento": a.fundamento,
            "estado": estado,
            "rotulo": ROTULO_DA_SITUACAO.get(estado, estado),
            "detalhe": detalhe,
        })
    return {
        "lote": plano.lote,
        "total": len(plano.apontamentos),
        "atendidos": sum(1 for l in linhas if l["estado"] == "ATENDIDO"),
        "falharam": sum(1 for l in linhas if l["estado"] == "FALHOU"),
        "por_situacao": contagem(plano),
        "apontamentos": linhas,
    }


def documentos_alterados(diff: dict) -> tuple[str, ...]:
    """Quais documentos o patch de fato mudou — para o §26."""
    mudou = set()
    for path, bloco in (diff or {}).get("blocos", {}).items():
        if bloco.get("estado") in ("alterado", "incluido", "removido"):
            mudou.add(path.split("/")[0])
    return tuple(sorted(mudou))


def retirar_aprovacoes(aprovados, alterados) -> set:
    """
    §26: documento alterado pelo parecer perde a aprovação anterior.

    Quem aprovou aprovou OUTRO texto. Manter o carimbo faria o processo
    seguir como se um humano tivesse lido a versão corrigida — que é
    exatamente a afirmação que o produto existe para não deixar passar.
    """
    return {a for a in (aprovados or set()) if a not in set(alterados)}


__all__ = [
    "AMBIGUO", "Apontamento", "CARIMBO_PENDENTE", "CONFLITANTE",
    "CORRECAO_AUTOMATICA", "EXIGE_DADO_FALTANTE",
    "EXIGE_DECISAO_ADMINISTRATIVA", "ErroCorrecaoParecer", "JA_ATENDIDO",
    "NAO_APLICAVEL", "Plano", "ROTULO_DA_SITUACAO", "SITUACOES",
    "aplicar", "classificar", "contagem", "desfazer",
    "documentos_alterados", "ordenar",
    "planejar", "relatorio_de_atendimento", "relatorio_de_findings",
    "retirar_aprovacoes", "situar",
]
