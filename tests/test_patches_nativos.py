"""Canonical native policy adapter with IPC isolated explicitly.

Synthetic JSON and the fake worker below test policy/postconditions, not the
real WordCraft model or Session semantics. Production always validates natively.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from src import patches, wordcraft_blocos as nativos, wordcraft_native

PIN = "a" * 64
DOCUMENT = "586e25cd-8ea4-45c8-b196-d76c0424d9e9"
OTHER = "313fa9a1-452c-4092-949c-6c1c0f825bab"
CONFIG = {"node": Path("/test-only/node"), "bundle": Path("/test-only/bundle"), "manifest_sha256": PIN}


def para(text, style=None, props=None):
    value = {"kind": "para", "text": text,
             "runs": [{"len": len(text.encode("utf-8")), **({"props": props} if props else {})}] if text else []}
    if style:
        value["props"] = {"style": style}
    return value


def heading(text, style="GovDocsClausula"):
    return para(text, style)


def table(*cells):
    return {"kind": "table", "props": {}, "grid": [100.0] * len(cells),
            "rows": [{"props": {}, "cells": [{"props": {}, "blocks": cell} for cell in cells]}]}


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def checkpoint(body=None, **document):
    return encode({"schema": "gc-wordcraft-snapshot/v1", "document": {
        "body": body if body is not None else [heading("1. OBJETO"), para("Texto original."),
             para("Outro trecho."), para("Terceiro trecho."), para("Quarto trecho.")],
        "parts": {}, **document}, "media": {}, "passthrough": {}})


@pytest.fixture
def engine(monkeypatch):
    calls = []
    monkeypatch.setattr(nativos, "validar", lambda *a, **k: None)

    def apply(content, *, revision, plano, **config):
        calls.append((content, revision, deepcopy(plano)))
        value = json.loads(content)
        for operation in plano["operations"]:
            position = nativos.CaminhoNativo(None if operation["story"] == "body" else operation["story"]["part"],
                                             tuple(operation["path"]))
            block = nativos._bloco_modelo(value, position)
            data = block["text"].encode("utf-8")
            start, end = operation["start_byte"], operation["end_byte"]
            assert data[start:end].decode("utf-8") == operation["old_text"]
            block["text"] = (data[:start] + operation["new_text"].encode("utf-8") + data[end:]).decode("utf-8")
            block["runs"] = [{"len": len(block["text"].encode("utf-8")),
                              **({"props": block["runs"][0]["props"]} if block["runs"][0].get("props") else {})}]
        return encode(value)

    monkeypatch.setattr(wordcraft_native, "aplicar_patch", apply)
    return calls, apply


def source(content=None, *, document_id=DOCUMENT):
    content = checkpoint() if content is None else content
    index = nativos.construir_indice(content, document_id=document_id, revision=1,
                                     content_hash=hashlib.sha256(content).hexdigest(), **CONFIG)
    return nativos.DocumentoNativo(content, index)


def view(doc, key="memo"):
    return nativos.projetar_documento(key, doc.checkpoint, indice=doc.indice, **CONFIG)


def plan_for(docs, changes):
    views = {key: view(doc, key) for key, doc in docs.items()}
    snapshot = nativos.snapshot_nativo(views, versao=1)
    operations, findings = [], []
    for i, (key, old, new) in enumerate(changes):
        target = next(b for b in views[key].blocos if b.conteudo == old)
        fid = f"F{i:03d}"
        operations.append({"findingId": fid, "documentId": key, "op": "replace", "path": target.path,
            "expectedOldHash": target.hash, "newValue": new, "sourceIds": [], "reason": "r"})
        findings.append({"findingId": fid, "documentId": key, "autoCorrectable": True,
            "allowedPaths": [target.path], "blockedPaths": [], "sourceIds": []})
    plan = {"patchPlanId": "test-only", "bundleId": "b", "sourceBundleVersion": 1,
        "sourceBundleHash": snapshot["hash"], "sourceNative": {key: v.vinculo() for key, v in views.items()},
        "operations": operations, "unresolvedFindings": []}
    return plan, {"bundleId": "b", "bundleVersion": 1, "findings": findings}


def apply(plan, docs, report, **kwargs):
    return patches.aplicar_plano_nativo(plan, docs, report, **CONFIG, **kwargs)


@pytest.mark.parametrize("style", ["GovDocsClausula", "Heading1", "Heading2", "Heading3"])
def test_projection_uses_canonical_regex_only_in_typed_heading_and_inherits_cells(engine, style):
    content = checkpoint([heading("2. JUSTIFICATIVA", style), para("Corpo."),
                          table([para("Célula."), table([para("Célula interna.")])])],
                         parts={"1": {"kind": "header", "blocks": [para("Cabeçalho")]}})
    doc = source(content)
    projection = view(doc)
    assert projection.apto_analise and projection.apto_autocorrecao
    assert projection.texto_analise.startswith("## 2. JUSTIFICATIVA")
    assert json.loads(content)["document"]["body"][0]["text"] == "2. JUSTIFICATIVA"
    assert [b.clausula for b in projection.blocos] == [2, 2, 2, 2, None]
    assert all(b.path.startswith("memo/clausula/2/") for b in projection.blocos[:-1])
    assert projection.blocos[-1].path.startswith("memo/institucional/")
    assert projection.blocos[-1].bloqueio == "institucional"
    assert projection.blocos[0].bloqueio == "titulo"
    assert projection.blocos[3].ancora.caminho.indices == (2, 0, 0, 1, 0, 0, 0)


def test_projection_does_not_promote_heading_in_cell_to_document_clause(engine):
    projection = view(source(checkpoint([heading("1. OBJETO"),
        table([heading("9. OUTRO"), para("Célula")]), para("Corpo")])) )
    assert [b.clausula for b in projection.blocos] == [1, 1, 1, 1]


def test_bookmark_boundary_markers_identify_blocked_clause_heading_only(engine):
    first, second = heading("\ufffc1. OBJETO\ufffc"), heading("\ufffc2. JUSTIFICATIVA\ufffc")
    first["objects"] = [{"type": "bookmarkStart", "name": "gc_clause_1"},
                        {"type": "bookmarkEnd", "name": "gc_clause_1"}]
    second["objects"] = [{"type": "bookmarkStart", "name": "gc_clause_2"},
                         {"type": "bookmarkEnd", "name": "gc_clause_2"}]
    projection = view(source(checkpoint([
        first, para("Corpo elegível."), second, para("Outro corpo elegível."),
    ])))
    assert projection.apto_analise and projection.apto_autocorrecao
    assert [b.clausula for b in projection.blocos] == [1, 1, 2, 2]
    assert projection.blocos[0].conteudo == "## 1. OBJETO"
    assert projection.blocos[0].bloqueio == "titulo"


@pytest.mark.parametrize("text,style", [
    ("1. OBJ\ufffcETO", "GovDocsClausula"),
    ("\ufffc1. OBJETO", "GovDocsClausula"),
    ("1. OBJETO\ufffc", "GovDocsClausula"),
    ("Corpo \ufffc opaco", None),
])
def test_non_boundary_or_non_heading_object_marker_remains_uncovered(engine, text, style):
    block = heading(text, style) if style else para(text)
    projection = view(source(checkpoint([heading("1. OBJETO"), block])))
    assert not projection.apto_analise and not projection.apto_autocorrecao
    assert any(area.startswith("objeto:") for area in projection.areas_nao_cobertas)


def test_boundary_markers_with_non_bookmark_or_mismatched_objects_remain_uncovered(engine):
    for objects in ([{"type": "drawing", "name": "gc_clause_1"}],
                    [{"type": "bookmarkStart", "name": "gc_clause_1"},
                     {"type": "bookmarkEnd", "name": "gc_clause_2"}]):
        block = heading("\ufffc1. OBJETO\ufffc")
        block["objects"] = objects
        assert not view(source(checkpoint([block, para("Corpo.")]))).apto_analise


def test_fixed_without_structure_untyped_numbering_and_duplicate_heading_fail_closed(engine):
    for body in ([para("Texto sem títulos")], [heading("1. OBJETO"), para("9. EQUIPE")],
                 [heading("1. OBJETO"), para("Nome sem delimitação da cláusula fixa")],
                 [heading("1. OBJETO"), heading("1. OUTRO"), para("Corpo")]):
        assert not view(source(checkpoint(body)), "dfd").apto_autocorrecao


def test_unnumbered_signature_heading_cannot_break_fixed_policy_or_inherit_editable_clause(engine):
    projection = view(source(checkpoint([heading("8. PERÍODO"), para("Vigência de 12 meses."),
        heading("9. EQUIPE DE PLANEJAMENTO"), para("Equipe."), heading("ASSINATURAS"),
        para("Pessoa sintética."), para("____", "GovDocsAssinatura")])), "dfd")
    assert projection.blocos[4].clausula is None
    assert all(b.bloqueio is not None for b in projection.blocos[4:])


@pytest.mark.parametrize("target,new", [("Nome da pessoa.", "Nome de outra pessoa."),
    ("Cargo e portaria 123.", "Cargo e portaria 456."),
    ("Nome depois da linha.", "Nome modificado depois da linha.")])
def test_signature_region_without_locked_profile_resists_even_an_allowed_finding(engine, target, new):
    # memo has no FIXED_LOCKED clause: the view itself must enforce this region.
    docs = {"memo": source(checkpoint([heading("1. OBJETO"), para("Corpo autorizado."),
        heading("ASSINATURAS"), para("Nome da pessoa."), para("Cargo e portaria 123."),
        para("____", "GovDocsAssinatura"), para("Nome depois da linha."),
        heading("2. OUTRO"), para("Texto original.")]))}
    plan, report = plan_for(docs, [("memo", target, new)])
    assert report["findings"][0]["autoCorrectable"]
    with pytest.raises(patches.ErroAplicacao):
        apply(plan, docs, report)
    assert not engine[0]
    allowed_plan, allowed_report = plan_for(docs, [("memo", "Texto original.", "Texto corrigido.")])
    assert apply(allowed_plan, docs, allowed_report)["versao"] == 2


def test_signature_and_institutional_views_are_blocked_using_existing_governance(engine):
    projection = view(source(checkpoint([para("Instituição", "GovDocsTitulo"), heading("1. OBJETO"),
        para("Permitido"), heading("2. ASSINATURAS"), para("Quem assina"),
        heading("3. OUTRO"), para("____", "GovDocsAssinatura"), para("Nome após linha")])) )
    assert [b.bloqueio for b in projection.blocos] == ["institucional", "titulo", None,
        "clausula_bloqueada", "clausula_bloqueada", "titulo", "assinatura", "assinatura"]


def test_unknown_object_text_and_unaddressable_regions_prevent_claim_of_complete_analysis(engine):
    block = para("Imagem \ufffc")
    block["objects"] = [{"kind": "test-only-object"}]
    projection = view(source(checkpoint([heading("1. OBJETO"), block],
            footnoteSeparators={"separator": [para("Nota sem path")] })))
    assert not projection.apto_analise and not projection.apto_autocorrecao
    assert "footnoteSeparators.separator" in projection.areas_nao_cobertas
    assert any(area.startswith("objeto:") for area in projection.areas_nao_cobertas)


def test_empty_alt_image_only_header_and_footer_do_not_create_text_coverage_gap(engine):
    image = para("\ufffc", "Header")
    image["objects"] = [{"type": "image", "alt": ""}]
    footer = deepcopy(image)
    footer["props"] = {"style": "Footer"}
    projection = view(source(checkpoint(
        [heading("1. OBJETO"), para("Corpo elegível.")],
        parts={"1": {"kind": "header", "blocks": [image]},
               "2": {"kind": "footer", "blocks": [footer]}})))
    assert projection.apto_analise and projection.apto_autocorrecao
    institutional = [block for block in projection.blocos
                     if block.ancora.story_kind in {"header", "footer"}]
    assert len(institutional) == 2
    assert all(block.conteudo == "" and block.bloqueio == "institucional"
               for block in institutional)


@pytest.mark.parametrize("story,text,objects", [
    ("header", "\ufffc", [{"type": "image", "alt": "Texto alternativo"}]),
    ("header", "Marca \ufffc", [{"type": "image", "alt": ""}]),
    ("header", "\ufffc", [{"type": "drawing", "alt": ""}]),
    ("body", "\ufffc", [{"type": "image", "alt": ""}]),
])
def test_image_exception_remains_strict_and_fail_closed(engine, story, text, objects):
    block = para(text, "Header" if story == "header" else None)
    block["objects"] = objects
    if story == "body":
        content = checkpoint([heading("1. OBJETO"), block])
    else:
        content = checkpoint([heading("1. OBJETO"), para("Corpo elegível.")],
                             parts={"1": {"kind": story, "blocks": [block]}})
    projection = view(source(content))
    assert not projection.apto_analise and not projection.apto_autocorrecao
    assert any(area.startswith("objeto:") for area in projection.areas_nao_cobertas)


def test_adapter_applies_through_native_worker_preserves_id_and_original(engine, monkeypatch):
    docs = {"memo": source()}
    original = docs["memo"]
    plan, report = plan_for(docs, [("memo", "Texto original.", "Texto corrigido.")])
    calls = []
    validator = patches.corretor.validar_plano
    monkeypatch.setattr(patches.corretor, "validar_plano", lambda *args: (calls.append(args), validator(*args))[1])
    result = apply(plan, docs, report)
    assert len(calls) == 1 and len(engine[0]) == 1
    assert result["versao"] == 2 and result["documentos"]["memo"].indice.revision == 2
    assert result["documentos"]["memo"].indice.blocos[1].block_id == original.indice.blocos[1].block_id
    assert docs["memo"] is original and original.checkpoint == checkpoint()
    assert result["diff"]["documentos"]["memo"]["alterados"] == [plan["operations"][0]["path"]]
    operation = engine[0][0][2]["operations"][0]
    assert operation["path"] == [1] and operation["story"] == "body"
    assert operation["start_byte"] > 0 and operation["end_byte"] < len(b"Texto original.")


@pytest.mark.parametrize("old,new", [("Café íntegro.", "Café íntegro e válido."),
    ("Café íntegro.", "Café."), ("Café.", "Cafés."), ("ABC", "XABC"), ("ABC", "ABCX")])
def test_minimal_range_preserves_utf8_boundaries_and_exact_requested_text(engine, old, new):
    docs = {"memo": source(checkpoint([heading("1. OBJETO"), para(old)]))}
    plan, report = plan_for(docs, [("memo", old, new)])
    result = apply(plan, docs, report, max_proporcao_blocos=1)
    assert view(result["documentos"]["memo"]).blocos[1].conteudo == new


@pytest.mark.parametrize("change", ["native_hash", "revision", "bool_revision", "build", "doc_id", "bundle_hash",
                                      "bundle_version", "bundle_id", "missing_expected", "bad_expected"])
def test_all_source_bindings_and_expected_hash_are_mandatory(engine, change):
    docs = {"memo": source()}
    plan, report = plan_for(docs, [("memo", "Texto original.", "Texto corrigido.")])
    if change in {"native_hash", "build", "doc_id", "revision", "bool_revision"}:
        key, value = {"native_hash": ("sourceHash", "b" * 64), "revision": ("revision", 2),
            "bool_revision": ("revision", True), "build": ("engineManifestSha256", "b" * 64),
            "doc_id": ("documentId", OTHER)}[change]
        plan["sourceNative"]["memo"][key] = value
    elif change == "bundle_hash":
        plan["sourceBundleHash"] = "b" * 64
    elif change == "bundle_version":
        plan["sourceBundleVersion"] = 2
    elif change == "bundle_id":
        plan["bundleId"] = "other"
    elif change == "missing_expected":
        del plan["operations"][0]["expectedOldHash"]
    else:
        plan["operations"][0]["expectedOldHash"] = "b" * 64
    with pytest.raises(patches.ErroAplicacao):
        apply(plan, docs, report)
    assert not engine[0]


@pytest.mark.parametrize("case", ["blocked", "outside", "not_auto", "source_required", "duplicate", "add", "title",
                                    "mixed", "object", "preamble", "no_common", "control", "governance_change",
                                    "run_tracking", "para_tracking", "mark_tracking", "doc_tracking", "protected"])
def test_blocked_unsupported_and_scope_changes_never_return_a_checkpoint(engine, case):
    body = [heading("1. OBJETO"), para("Texto original."), para("Outro trecho."), para("Terceiro trecho.")]
    old, new = "Texto original.", "Texto corrigido."
    if case == "mixed":
        body[1]["runs"] = [{"len": 6}, {"len": 9, "props": {"bold": True}}]
    elif case == "run_tracking":
        body[1]["runs"][0]["props"] = {"ins": {"id": 1}}
    elif case == "para_tracking":
        body[1]["props"] = {"fmtChange": {"id": 1}}
    elif case == "mark_tracking":
        body[1]["mark"] = {"del": {"id": 1}}
    elif case == "object":
        body[1]["objects"] = [{"kind": "test-only"}]
    elif case == "preamble":
        body = [body[1], body[0], *body[2:]]
    elif case == "title":
        old, new = "## 1. OBJETO", "## 1. NOVO OBJETO"
    elif case == "no_common":
        new = "ABC"
    elif case == "control":
        new = "Texto\ncorrompido."
    elif case == "governance_change":
        new = "Texto original. ____"
    extra = ({"settings": {"trackChanges": True}} if case == "doc_tracking" else
             {"settings": {"protection": {"enforcement": True}}} if case == "protected" else {})
    docs = {"memo": source(checkpoint(body, **extra))}
    plan, report = plan_for(docs, [("memo", old, new)])
    if case == "blocked":
        report["findings"][0]["blockedPaths"] = [plan["operations"][0]["path"]]
    elif case == "outside":
        report["findings"][0]["allowedPaths"] = []
    elif case == "not_auto":
        report["findings"][0]["autoCorrectable"] = False
    elif case == "source_required":
        report["findings"][0]["sourceIds"] = ["formulario"]
    elif case == "duplicate":
        plan["operations"].append(deepcopy(plan["operations"][0]))
    elif case == "add":
        plan["operations"][0]["op"] = "add"
    with pytest.raises(patches.ErroAplicacao):
        apply(plan, docs, report, max_proporcao_blocos=1)
    if case != "governance_change":
        assert not engine[0]


def test_fixed_locked_and_parameterized_rules_are_the_existing_rules(engine):
    docs = {"dfd": source(checkpoint([heading("8. PERÍODO"), para("Vigência de 12 meses."),
        heading("9. EQUIPE DE PLANEJAMENTO"), para("Nome da equipe.")]))}
    for old, new in [("Nome da equipe.", "Outro nome."),
                     ("Vigência de 12 meses.", "Vigência de 24 meses a partir da ordem.")]:
        plan, report = plan_for(docs, [("dfd", old, new)])
        with pytest.raises(patches.ErroAplicacao):
            apply(plan, docs, report, max_proporcao_blocos=1)
    assert not engine[0]
    plan, report = plan_for(docs, [("dfd", "Vigência de 12 meses.", "Vigência de 24 meses.")])
    result = apply(plan, docs, report)
    assert "24 meses" in view(result["documentos"]["dfd"], "dfd").texto_analise


def test_table_cell_patch_keeps_geometry_other_cells_and_proven_container_identity(engine):
    docs = {"memo": source(checkpoint([heading("1. OBJETO"),
        table([para("Célula original.")], [para("Preservar célula.")]), para("Preservar corpo.")]))}
    old = docs["memo"]
    plan, report = plan_for(docs, [("memo", "Célula original.", "Célula corrigida.")])
    result = apply(plan, docs, report, max_proporcao_blocos=1)
    current = result["documentos"]["memo"]
    assert [b.block_id for b in current.indice.blocos] == [b.block_id for b in old.indice.blocos]
    assert json.loads(current.checkpoint)["document"]["body"][1]["grid"] == [100.0, 100.0]
    assert len(result["diff"]["documentos"]["memo"]["alterados"]) == 1


def test_confirmed_text_only_operation_preserves_duplicate_unchanged_blocks_and_stories(engine):
    docs = {"memo": source(checkpoint([heading("1. OBJETO"), para("Texto original."),
        para("Repetido"), para("Repetido"), para("")],
        parts={"1": {"kind": "header", "blocks": [para("Repetido"), para("")]}}))}
    original = docs["memo"]
    plan, report = plan_for(docs, [("memo", "Texto original.", "Texto corrigido.")])
    result = apply(plan, docs, report)
    current = result["documentos"]["memo"]
    assert [b.block_id for b in current.indice.blocos] == [b.block_id for b in original.indice.blocos]
    assert current.indice.invalidacoes == ()


@pytest.mark.parametrize("tamper", ["outside_text", "para_props", "run_props", "media", "passthrough", "table_geometry", "no_effect"])
def test_native_result_is_revalidated_and_every_outside_or_format_change_rejects(engine, monkeypatch, tamper):
    docs = {"memo": source(checkpoint([heading("1. OBJETO"), para("Texto original."),
        table([para("Preservar célula.")]), para("Preservar corpo.")]))}
    plan, report = plan_for(docs, [("memo", "Texto original.", "Texto corrigido.")])

    def faulty(content, **kwargs):
        value = json.loads(engine[1](content, **kwargs))
        if tamper == "outside_text":
            value["document"]["body"][3] = para("Vazamento secreto")
        elif tamper == "para_props":
            value["document"]["body"][1]["props"] = {"align": "center"}
        elif tamper == "run_props":
            value["document"]["body"][1]["runs"][0]["props"] = {"bold": True}
        elif tamper == "table_geometry":
            value["document"]["body"][2]["grid"] = [200.0]
        elif tamper == "no_effect":
            return content
        else:
            value[tamper]["unexpected"] = [1, 2, 3]
        return encode(value)

    monkeypatch.setattr(wordcraft_native, "aplicar_patch", faulty)
    original = docs["memo"].checkpoint
    with pytest.raises(patches.ErroAplicacao) as error:
        apply(plan, docs, report, max_proporcao_blocos=1)
    assert docs["memo"].checkpoint == original
    assert "secreto" not in str(error.value)


def test_budget_and_blocked_clause_use_the_same_diff_rules_before_native_call(engine):
    docs = {"memo": source()}
    plan, report = plan_for(docs, [("memo", "Texto original.", "Texto corrigido."),
                                  ("memo", "Outro trecho.", "Outro texto.")])
    with pytest.raises(patches.ErroAplicacao):
        apply(plan, docs, report)
    report["findings"].append({"findingId": "BLOCK", "autoCorrectable": False,
        "allowedPaths": [], "blockedPaths": [view(docs["memo"]).blocos[3].path], "sourceIds": []})
    with pytest.raises(patches.ErroAplicacao):
        apply(plan, docs, report, max_proporcao_blocos=1)
    assert not engine[0]


def test_later_invalid_operation_is_preflighted_and_no_partial_batch_escapes(engine):
    docs = {"memo": source(), "other": source(document_id=OTHER)}
    plan, report = plan_for(docs, [("memo", "Texto original.", "Texto corrigido."),
                                  ("other", "Texto original.", "Texto corrigido.")])
    plan["operations"][1]["expectedOldHash"] = "b" * 64
    with pytest.raises(patches.ErroAplicacao):
        apply(plan, docs, report)
    assert not engine[0]


def test_later_native_failure_discards_all_in_memory_results_without_logging_payload(engine, monkeypatch):
    docs = {"memo": source(), "other": source(document_id=OTHER)}
    originals = {key: doc.checkpoint for key, doc in docs.items()}
    plan, report = plan_for(docs, [("memo", "Texto original.", "Texto corrigido."),
                                  ("other", "Texto original.", "Texto corrigido.")])
    count = 0

    def fail_second(content, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise wordcraft_native.ModeloRecusado("synthetic-secret-payload")
        return engine[1](content, **kwargs)

    monkeypatch.setattr(wordcraft_native, "aplicar_patch", fail_second)
    with pytest.raises(patches.ErroAplicacao) as error:
        apply(plan, docs, report)
    assert count == 2 and {key: doc.checkpoint for key, doc in docs.items()} == originals
    assert "synthetic-secret" not in str(error.value)


def test_projection_never_accepts_stale_or_forged_index(engine):
    doc = source()
    with pytest.raises(nativos.ErroAncora):
        view(replace(doc, indice=replace(doc.indice, content_hash="b" * 64)))
    with pytest.raises(nativos.ErroAncora):
        view(replace(doc, indice=replace(doc.indice, engine_manifest_sha256="b" * 64)))
