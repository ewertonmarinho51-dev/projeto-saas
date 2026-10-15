"""
Aplicador determinístico de patches (Etapa 4 da correção automática —
pacote_correcao_automatica_documentos_v1, 01_ARQUITETURA).

A IA propõe (corretor.py); ESTE código valida e aplica. A aplicação é
TRANSACIONAL: primeiro todas as pré-condições, depois a aplicação em
cópia, depois todas as pós-condições — qualquer violação em qualquer
fase rejeita o plano INTEIRO e o bundle original permanece intocado.

Camadas de defesa (em ordem):
  1. hash/versão de origem: o plano só vale para o bundle exato que o
     originou (documento editado depois = plano descartado);
  2. revalidação do plano (corretor.validar_plano) — defesa em
     profundidade, não confia que o chamador validou;
  3. cláusulas fixas dos perfis: FIXED_LOCKED nunca muda;
     FIXED_PARAMETERIZED só aceita mudança de PARÂMETROS (números,
     valores, datas, percentuais) com a prosa preservada;
  4. diff estrutural pós-aplicação com granularidade de CLÁUSULA: as
     operações são exatas por bloco, mas o resultado é conferido por
     cláusula (um replace que vira dois parágrafos continua dentro da
     cláusula autorizada; qualquer efeito em cláusula não autorizada
     rejeita tudo);
  5. orçamento do ciclo: no máximo `max_proporcao_blocos` dos blocos do
     bundle alterados de uma vez.

Feature flag `flag_correcao_automatica` (default OFF): consultada pelo
ORQUESTRADOR do ciclo (Etapa 5) — este módulo é função pura e não lê
flag nem banco.
"""

import re
import math
import hashlib
from pathlib import Path

from . import blocos, corretor, perfis, wordcraft_blocos as nativos, wordcraft_native

FLAG_APLICACAO = "correcao_automatica"

MAX_PROPORCAO_BLOCOS = 0.25  # orçamento padrão de alterações por ciclo


class ErroAplicacao(Exception):
    """Plano rejeitado — nenhuma alteração foi aplicada."""


# ---------------------------------------------------------------------------
# FIXED_PARAMETERIZED: só parâmetros podem mudar
# ---------------------------------------------------------------------------
# classes de parâmetro autorizadas: moeda, data, número/percentual
_RE_PARAMETRO = re.compile(
    r"R\$\s?[\d.,]+|\d{2}/\d{2}/\d{4}|\d+(?:[.,]\d+)?\s*%?")


def _esqueleto(texto: str) -> str:
    """Texto com os parâmetros mascarados — o que NÃO pode mudar."""
    return _RE_PARAMETRO.sub("§", " ".join((texto or "").split()))


def parametros_compativeis(antigo: str, novo: str) -> bool:
    """True se apenas parâmetros autorizados diferem entre as versões."""
    return _esqueleto(antigo) == _esqueleto(novo)


# ---------------------------------------------------------------------------
# Utilidades de caminho (granularidade de cláusula)
# ---------------------------------------------------------------------------
def _prefixo_clausula(path: str) -> str:
    """'dfd/clausula/2/1' → 'dfd/clausula/2'; 'dfd/preambulo/0' → 'dfd/preambulo'."""
    partes = path.split("/")
    tamanho = 3 if len(partes) > 1 and partes[1] == "clausula" else 2
    return "/".join(partes[:tamanho])


def _numero_da_clausula(path: str) -> int | None:
    partes = path.split("/")
    if len(partes) < 3 or partes[1] != "clausula":
        return None
    return int(str(partes[2]).split(".")[0])


# ---------------------------------------------------------------------------
# Validações específicas da aplicação
# ---------------------------------------------------------------------------
def _validar_clausulas_fixas(plano: dict, snapshot: dict) -> list[str]:
    violacoes = []
    hashes_conteudo = {
        b["path"]: b["conteudo"]
        for doc in snapshot["documentos"].values() for b in doc["blocos"]
    }
    for i, op in enumerate(plano["operations"]):
        rotulo = f"operação {i + 1}"
        doc_key = (op.get("path") or "").split("/")[0]
        numero = _numero_da_clausula(op.get("path") or "")
        if numero is None:
            continue
        fixa = perfis.clausulas_fixas(doc_key).get(numero)
        if fixa == "LOCKED":
            violacoes.append(
                f"{rotulo}: cláusula {numero} do {doc_key} é FIXED_LOCKED "
                "— a IA não pode alterá-la")
        elif fixa == "PARAMETERIZED":
            if op.get("op") != "replace":
                violacoes.append(
                    f"{rotulo}: cláusula {numero} do {doc_key} é "
                    "FIXED_PARAMETERIZED — só aceita substituição de "
                    "parâmetros (sem adicionar/remover blocos)")
            elif not parametros_compativeis(
                hashes_conteudo.get(op["path"], ""),
                str(op.get("newValue") or ""),
            ):
                violacoes.append(
                    f"{rotulo}: cláusula {numero} do {doc_key} é "
                    "FIXED_PARAMETERIZED — apenas números, valores, datas "
                    "e percentuais podem mudar; a prosa foi alterada")
    return violacoes


def _validar_diff_por_clausula(diff_bundle: dict, permitidos: set[str],
                               bloqueados: set[str],
                               max_proporcao: float) -> list[str]:
    """Pós-condições sobre o diff (granularidade de cláusula) + orçamento."""
    violacoes = []
    prefixos_permitidos = {_prefixo_clausula(p) for p in permitidos}
    prefixos_bloqueados = {_prefixo_clausula(p) for p in bloqueados}
    tocados_total, blocos_total = 0, 0
    for doc, diff in diff_bundle["documentos"].items():
        tocados = diff["alterados"] + diff["adicionados"] + diff["removidos"]
        tocados_total += len(tocados)
        blocos_total += diff.get("total_antes") or 0
        for path in tocados:
            prefixo = _prefixo_clausula(path)
            if prefixo in prefixos_bloqueados:
                violacoes.append(
                    f"{doc}: alteração em cláusula bloqueada ({path})")
            elif prefixo not in prefixos_permitidos:
                violacoes.append(
                    f"{doc}: alteração fora do escopo autorizado ({path})")
    proporcao = tocados_total / max(blocos_total, 1)
    if tocados_total and proporcao > max_proporcao:
        violacoes.append(
            f"orçamento do ciclo excedido: {tocados_total}/{blocos_total} "
            f"blocos alterados ({proporcao:.0%} > {max_proporcao:.0%})")
    return violacoes


# ---------------------------------------------------------------------------
# Aplicação em memória (cópia) — nunca toca o bundle original
# ---------------------------------------------------------------------------
def _aplicar_no_documento(doc_key: str, texto: str,
                          operacoes: list[dict]) -> str:
    bloclist = blocos.dividir_em_blocos(doc_key, texto)
    indice = {b["path"]: i for i, b in enumerate(bloclist)}
    conteudos: list[str | None] = [b["conteudo"] for b in bloclist]

    insercoes: list[tuple[int, str]] = []
    for op in operacoes:
        path, novo = op["path"], str(op.get("newValue") or "").strip()
        if op["op"] == "replace":
            conteudos[indice[path]] = novo
        elif op["op"] == "remove":
            conteudos[indice[path]] = None
        elif op["op"] == "add":
            numero = _numero_da_clausula(path)
            posicao = len(bloclist)
            if numero is not None:
                existentes = [i for i, b in enumerate(bloclist)
                              if b.get("clausula") == numero]
                if existentes:
                    posicao = existentes[-1] + 1  # fim da própria cláusula
                else:
                    posteriores = [
                        i for i, b in enumerate(bloclist)
                        if (b.get("clausula") or 0) > numero
                    ]
                    if posteriores:
                        posicao = posteriores[0]  # antes da cláusula seguinte
            insercoes.append((posicao, novo))

    partes: list[str] = []
    for i, conteudo in enumerate(conteudos):
        partes.extend(txt for pos, txt in insercoes if pos == i)
        if conteudo:
            partes.append(conteudo)
    partes.extend(txt for pos, txt in insercoes if pos >= len(conteudos))
    return "\n\n".join(partes)


# ---------------------------------------------------------------------------
# Entrada única: aplicar o plano (transacional)
# ---------------------------------------------------------------------------
def aplicar_plano(plano: dict, documentos: dict[str, str], relatorio: dict,
                  max_proporcao_blocos: float = MAX_PROPORCAO_BLOCOS) -> dict:
    """
    Aplica o plano sobre o bundle e retorna
    {"documentos", "snapshot", "diff", "versao"} da NOVA versão.
    Levanta ErroAplicacao (sem efeito colateral) em qualquer violação.
    """
    versao_origem = plano["sourceBundleVersion"]
    snap_antes = blocos.snapshot_bundle(documentos, versao=versao_origem)

    # 1. o plano só vale para o bundle exato que o originou
    if plano["sourceBundleHash"] != snap_antes["hash"]:
        raise ErroAplicacao(
            "o conteúdo dos documentos mudou depois que o plano foi "
            "criado (hash de origem divergente) — gere um novo plano")

    # 2. revalidação completa do plano (defesa em profundidade)
    violacoes = corretor.validar_plano(plano, relatorio, snap_antes)
    # 3. cláusulas fixas de governança (perfis.py)
    violacoes += _validar_clausulas_fixas(plano, snap_antes)
    if violacoes:
        raise ErroAplicacao("; ".join(violacoes))

    # 4. aplicação em cópia
    por_doc: dict[str, list[dict]] = {}
    for op in plano["operations"]:
        por_doc.setdefault(op["path"].split("/")[0], []).append(op)
    novos = dict(documentos)
    for doc_key, operacoes in por_doc.items():
        novos[doc_key] = _aplicar_no_documento(
            doc_key, documentos.get(doc_key, ""), operacoes)

    # 5. pós-condições: diff estrutural, escopo por cláusula e orçamento
    snap_depois = blocos.snapshot_bundle(novos, versao=versao_origem + 1)
    diff = blocos.diff_bundle(snap_antes, snap_depois)
    findings_usados = {op["findingId"] for op in plano["operations"]}
    permitidos = {
        p for f in relatorio["findings"]
        if f["findingId"] in findings_usados for p in f["allowedPaths"]
    }
    bloqueados = {
        p for f in relatorio["findings"] for p in f["blockedPaths"]
    }
    violacoes = _validar_diff_por_clausula(
        diff, permitidos, bloqueados, max_proporcao_blocos)
    if violacoes:
        raise ErroAplicacao("; ".join(violacoes))

    return {
        "documentos": novos,
        "snapshot": snap_depois,
        "diff": diff,
        "versao": versao_origem + 1,
    }


def _range_nativo(antigo: str, novo: str) -> dict:
    """Smallest exact UTF-8 replacement, retaining a native character context.

    The business operation remains a whole-paragraph replacement. Context is
    needed because the current native command refuses unsupported mark changes
    when selection consumes the entire paragraph. There is no JSON edit fallback.
    """
    if (not antigo or not novo.strip() or antigo == novo
            or not nativos._texto_inline(novo)
            or nativos.validacao._RE_CLAUSULA.fullmatch(novo)):
        raise ErroAplicacao("Substituição nativa vazia, idêntica ou não suportada.")
    prefix = 0
    while prefix < min(len(antigo), len(novo)) and antigo[prefix] == novo[prefix]:
        prefix += 1
    suffix = 0
    while (suffix < min(len(antigo), len(novo)) - prefix
           and antigo[-1 - suffix] == novo[-1 - suffix]):
        suffix += 1
    start, end = prefix, len(antigo) - suffix
    new_end = len(novo) - suffix
    if start == end:
        # Native insertion-only is intentionally not in the command allowlist.
        if start:
            start -= 1
        elif end < len(antigo):
            end += 1
            new_end += 1
    if start == 0 and end == len(antigo):
        raise ErroAplicacao("Substituição integral sem contexto nativo não suportada.")
    return {"start_byte": len(antigo[:start].encode("utf-8")),
            "end_byte": len(antigo[:end].encode("utf-8")),
            "old_text": antigo[start:end], "new_text": novo[start:new_end]}


def _verificar_modelo_nativo(antes: bytes, depois: bytes,
                            alvos: dict[nativos.CaminhoNativo, str]) -> None:
    """Postcondition oracle only; it never produces checkpoint bytes."""
    old, new = nativos._modelo_validado(antes), nativos._modelo_validado(depois)
    masked = {}
    for path, expected in alvos.items():
        source = nativos._bloco_modelo(old, path)
        target = nativos._bloco_modelo(new, path)
        if (not nativos._paragrafo_uniforme(target) or target.get("text") != expected
                or {k: v for k, v in source.items() if k not in {"text", "runs"}}
                != {k: v for k, v in target.items() if k not in {"text", "runs"}}
                or source["runs"][0].get("props", {}) != target["runs"][0].get("props", {})):
            raise ErroAplicacao("Pós-condição de texto ou formatação nativa recusada.")
        # This replacement occurs ONLY in a comparison copy, after the real
        # engine has returned. It is never serialized or sent back as a model.
        masked[id(target)] = source

    def same(left, right):
        if isinstance(right, dict) and id(right) in masked:
            return left == masked[id(right)]
        if type(left) is not type(right):
            return False
        if isinstance(left, dict):
            return left.keys() == right.keys() and all(same(left[k], right[k]) for k in left)
        if isinstance(left, list):
            return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
        return left == right

    if not same(old, new):
        raise ErroAplicacao("O motor alterou conteúdo ou estrutura fora do plano autorizado.")


def aplicar_plano_nativo(plano: dict, documentos: dict[str, nativos.DocumentoNativo],
                          relatorio: dict, *, node: Path, bundle: Path,
                          manifest_sha256: str,
                          max_proporcao_blocos: float = MAX_PROPORCAO_BLOCOS) -> dict:
    """The same policy applicator over native paragraphs, entirely in memory.

    Backend-owned checkpoints/indices/report/config are required. No ACL, save,
    CAS or live-editor Undo is performed here. A failure returns no partial lot.
    """
    config = {"node": node, "bundle": bundle, "manifest_sha256": manifest_sha256}
    try:
        if (not isinstance(plano, dict) or not isinstance(documentos, dict) or not documentos
                or len(documentos) > 32 or not isinstance(relatorio, dict)
                or not isinstance(max_proporcao_blocos, (int, float))
                or isinstance(max_proporcao_blocos, bool)
                or not math.isfinite(max_proporcao_blocos) or not 0 < max_proporcao_blocos <= 1
                or any(not isinstance(d, nativos.DocumentoNativo) for d in documentos.values())):
            raise ErroAplicacao("Entrada nativa ou orçamento inválido.")
        version = relatorio["bundleVersion"]
        nativos._inteiro(version, minimum=1)
        if (type(plano.get("sourceBundleVersion")) is not int
                or plano["sourceBundleVersion"] != version
                or not isinstance(relatorio.get("bundleId"), str)
                or plano.get("bundleId") != relatorio["bundleId"]):
            raise ErroAplicacao("Plano de outra revisão ou dossiê.")
        views = {key: nativos.projetar_documento(key, doc.checkpoint, indice=doc.indice, **config)
                 for key, doc in documentos.items()}
        binding = plano.get("sourceNative")
        if (not isinstance(binding, dict)
                or any(not isinstance(b, dict) or type(b.get("revision")) is not int for b in binding.values())
                or binding != {key: view.vinculo() for key, view in views.items()}):
            raise ErroAplicacao("Vínculo nativo de documento, revisão, hash ou build divergente.")
        snap_antes = nativos.snapshot_nativo(views, versao=version)
        if plano.get("sourceBundleHash") != snap_antes["hash"]:
            raise ErroAplicacao("Hash de origem nativa divergente.")
        operations = plano.get("operations")
        if (not isinstance(operations, list) or not 1 <= len(operations) <= corretor.MAX_OPERACOES
                or any(not isinstance(op, dict) for op in operations)):
            raise ErroAplicacao("Lista de operações nativas inválida.")
        violacoes = corretor.validar_plano(plano, relatorio, snap_antes)
        violacoes += _validar_clausulas_fixas(plano, snap_antes)
        if violacoes:
            # Validator details can contain arbitrary AI paths; do not log them.
            raise ErroAplicacao("Plano recusado pelas regras canônicas de escopo, fonte ou cláusula fixa.")
        by_path = {block.path: (key, block) for key, view in views.items() for block in view.blocos}
        compiled, targets, touched = {}, {}, set()
        for op in operations:
            path = op["path"]
            if not isinstance(path, str) or path not in by_path or path in touched:
                raise ErroAplicacao("Alvo nativo inexistente ou repetido.")
            key, block = by_path[path]
            view, doc = views[key], documentos[key]
            if (op.get("documentId") != key or op.get("op") != "replace"
                    or not isinstance(op.get("newValue"), str)
                    or not isinstance(op.get("expectedOldHash"), str)
                    or op["expectedOldHash"] != block.hash):
                raise ErroAplicacao("Operação ou hash obrigatório de parágrafo inválido.")
            if not view.apto_autocorrecao or block.bloqueio is not None:
                raise ErroAplicacao("Estrutura ou parágrafo nativo bloqueado para autocorreção.")
            anchor = block.ancora
            target = nativos.resolver_ancora(doc.indice, anchor.block_id,
                document_id=view.document_id, revision=view.revision,
                content_hash=view.content_hash, block_hash=anchor.content_hash)
            compiled.setdefault(key, []).append({"op": "replace_text", **target.posicao(),
                                                 **_range_nativo(block.conteudo, op["newValue"])})
            targets.setdefault(key, {})[target] = op["newValue"]
            touched.add(path)
        # Preflight the same structural budget before any worker invocation.
        budget_diff = {"documentos": {key: {"alterados": sorted(p for p in touched if p.startswith(key + "/")),
            "adicionados": [], "removidos": [], "total_antes": len(view.blocos)} for key, view in views.items()}}
        used = {op["findingId"] for op in operations}
        allowed = {p for f in relatorio["findings"] if f["findingId"] in used for p in f["allowedPaths"]}
        blocked = {p for f in relatorio["findings"] for p in f["blockedPaths"]}
        if _validar_diff_por_clausula(budget_diff, allowed, blocked, max_proporcao_blocos):
            raise ErroAplicacao("Diff nativo excede escopo, bloqueio ou orçamento do ciclo.")
        novos, after_views = dict(documentos), dict(views)
        for key, native_ops in compiled.items():
            original = documentos[key]
            result = wordcraft_native.aplicar_patch(original.checkpoint, revision=original.indice.revision,
                plano={"schema": "gc-wordcraft-native-patch/v1", "source_hash": original.indice.content_hash,
                       "source_revision": original.indice.revision, "operations": native_ops}, **config)
            digest = hashlib.sha256(result).hexdigest()
            fresh = nativos.construir_indice(result, document_id=original.indice.document_id,
                revision=original.indice.revision + 1, content_hash=digest, **config)
            _verificar_modelo_nativo(original.checkpoint, result, targets[key])
            after_by_path = {b.caminho: b for b in fresh.blocos}
            # The exact model proof and the native text-only command establish
            # every existing position, including duplicate unchanged paragraphs
            # and table ancestors. Receipts are generated here only; no generic
            # index reconciliation infers identity from position/similarity.
            links = tuple(nativos.VinculoOperacional(old.block_id, old.caminho, old.caminho,
                    old.content_hash, after_by_path[old.caminho].content_hash)
                for old in original.indice.blocos)
            transition = nativos.TransicaoNativa(original.indice.document_id, original.indice.revision,
                original.indice.content_hash, fresh.revision, digest, manifest_sha256)

            def confirm(observed, candidates, *, expected=transition, receipt=links):
                return observed == expected and candidates == receipt

            reconciled = nativos.reconciliar_indice(original.indice, original.checkpoint, result,
                revision=fresh.revision, content_hash=digest, vinculos=links, confirmar_vinculos=confirm, **config)
            novos[key] = nativos.DocumentoNativo(result, reconciled)
            after_views[key] = nativos.projetar_documento(key, result, indice=reconciled, **config)
            if (views[key].areas_nao_cobertas != after_views[key].areas_nao_cobertas
                    or views[key].impedimentos_autocorrecao != after_views[key].impedimentos_autocorrecao
                    or [(b.path, b.tipo, b.clausula, b.bloqueio) for b in views[key].blocos]
                    != [(b.path, b.tipo, b.clausula, b.bloqueio) for b in after_views[key].blocos]):
                raise ErroAplicacao("A alteração modificou a classificação de governança nativa.")
        snap_depois = nativos.snapshot_nativo(after_views, versao=version + 1)
        diff = blocos.diff_bundle(snap_antes, snap_depois)
        if _validar_diff_por_clausula(diff, allowed, blocked, max_proporcao_blocos):
            raise ErroAplicacao("Pós-condição de diff nativo recusada pelas regras canônicas.")
        actual = {p for d in diff["documentos"].values()
                  for p in d["alterados"] + d["adicionados"] + d["removidos"]}
        if actual != touched:
            raise ErroAplicacao("O resultado nativo não corresponde exatamente aos parágrafos do plano.")
        return {"documentos": novos, "snapshot": snap_depois, "diff": diff, "versao": version + 1}
    except ErroAplicacao:
        raise
    except (wordcraft_native.ModeloRecusado, wordcraft_native.MotorIndisponivel,
            ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError,
            RecursionError, OverflowError):
        raise ErroAplicacao("Aplicação nativa recusada; lote original preservado.") from None
