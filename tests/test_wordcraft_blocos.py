"""Index algorithm contracts, with native validation isolated explicitly.

These tests do not certify that test JSON is a complete native document. The
real pinned engine is mandatory in the production API and exercised separately.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from src import wordcraft_blocos as anchors
from src.wordcraft_native import ModeloRecusado

DOCUMENT = "586e25cd-8ea4-45c8-b196-d76c0424d9e9"
OTHER_DOCUMENT = "313fa9a1-452c-4092-949c-6c1c0f825bab"
PIN = "a" * 64


def paragraph(text):
    # Same serialized Para shape seen in the real native synthetic corpus.
    return {"kind": "para", "text": text,
            "runs": [{"len": len(text.encode("utf-8"))}] if text else []}


def table(*rows):
    return {"kind": "table", "props": {}, "grid": [100.0],
            "rows": [{"props": {}, "cells": [{"props": {}, "blocks": blocks}
                                              for blocks in row]} for row in rows]}


def snapshot(body, *, parts=None, **extra):
    value = {"schema": "gc-wordcraft-snapshot/v1",
             "document": {"body": body, "parts": parts or {}, **extra},
             "media": {}, "passthrough": {}}
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def digest(content):
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def native(monkeypatch):
    calls = []

    def validate(content, **config):
        calls.append((content, config))

    monkeypatch.setattr(anchors, "validar", validate)
    config = {"node": Path("/test-only/node"), "bundle": Path("/test-only/bundle"),
              "manifest_sha256": PIN}
    return config, calls


def build(content, native, revision=1):
    return anchors.construir_indice(content, document_id=DOCUMENT, revision=revision,
                                    content_hash=digest(content), **native[0])


def reconcile(previous, previous_content, content, native, **kwargs):
    return anchors.reconciliar_indice(previous, previous_content, content,
                                      revision=previous.revision + 1, content_hash=digest(content),
                                      **native[0], **kwargs)


def at(index, path, part=None):
    return next(block for block in index.blocos
                if block.caminho == anchors.CaminhoNativo(part, path))


def resolve(index, block, **kwargs):
    expected = dict(document_id=DOCUMENT, revision=index.revision,
                    content_hash=index.content_hash, block_hash=block.content_hash)
    expected.update(kwargs)
    return anchors.resolver_ancora(index, block.block_id, **expected)


def test_initial_retry_is_deterministic_and_native_approval_is_mandatory(native, monkeypatch):
    content = snapshot([paragraph("Alfa"), paragraph("Beta")])
    first = build(content, native)
    assert build(content, native) == first
    assert native[1][0] == (content, native[0])
    assert len({b.block_id for b in first.blocos}) == 2
    assert content == snapshot([paragraph("Alfa"), paragraph("Beta")])
    assert all("Alfa" not in repr(block) for block in first.blocos)

    def reject(*args, **kwargs):
        raise ModeloRecusado("Rejeição sintética de teste")

    monkeypatch.setattr(anchors, "validar", reject)
    with pytest.raises(ModeloRecusado):
        build(content, native)


def test_insertion_shifts_native_path_but_keeps_unique_block_identity(native):
    old_content = snapshot([paragraph("Alfa"), paragraph("Beta")])
    old = build(old_content, native)
    content = snapshot([paragraph("Novo"), paragraph("Alfa"), paragraph("Beta")])
    new = reconcile(old, old_content, content, native)
    assert at(new, (1,)).block_id == at(old, (0,)).block_id
    assert at(new, (2,)).block_id == at(old, (1,)).block_id
    assert at(new, (0,)).block_id not in {b.block_id for b in old.blocos}
    assert not new.invalidacoes
    assert resolve(new, at(new, (1,))).indices == (1,)


def test_unique_reordering_never_reuses_the_old_positional_target(native):
    old_content = snapshot([paragraph("Alfa"), paragraph("Beta"), paragraph("Gama")])
    old = build(old_content, native)
    content = snapshot([paragraph("Gama"), paragraph("Alfa"), paragraph("Beta")])
    new = reconcile(old, old_content, content, native)
    assert at(new, (0,)).block_id == at(old, (2,)).block_id
    assert at(new, (1,)).block_id == at(old, (0,)).block_id
    assert resolve(new, at(new, (1,))).indices != at(old, (0,)).caminho.indices


def test_unproven_text_edit_invalidates_identity_instead_of_guessing_from_position(native):
    old_content = snapshot([paragraph("Texto original"), paragraph("Outro")])
    old = build(old_content, native)
    content = snapshot([paragraph("Texto editado"), paragraph("Outro")])
    new = reconcile(old, old_content, content, native)
    assert at(new, (0,)).block_id != at(old, (0,)).block_id
    assert at(new, (1,)).block_id == at(old, (1,)).block_id
    assert new.invalidacoes == (anchors.Invalidacao(at(old, (0,)).block_id, "sem_correspondencia"),)
    with pytest.raises(anchors.ErroAncora, match="ausente"):
        resolve(new, at(old, (0,)))


def test_backend_confirmed_edit_keeps_id_and_checks_all_exact_transition_context(native):
    old_content = snapshot([paragraph("Texto original")])
    old = build(old_content, native)
    content = snapshot([paragraph("Texto editado")])
    fresh = build(content, native, revision=2)
    source, target = at(old, (0,)), at(fresh, (0,))
    link = anchors.VinculoOperacional(source.block_id, source.caminho, target.caminho,
                                      source.content_hash, target.content_hash)
    calls = []

    def backend_receipt(transition, links):
        calls.append((transition, links))
        # Stand-in for a trusted backend operation receipt, not a browser hint.
        return transition.source_hash == digest(old_content) and transition.target_hash == digest(content)

    new = reconcile(old, old_content, content, native, vinculos=(link,),
                    confirmar_vinculos=backend_receipt)
    assert at(new, (0,)).block_id == source.block_id
    assert at(new, (0,)).content_hash == target.content_hash
    assert resolve(new, at(new, (0,))).indices == (0,)
    assert calls == [(anchors.TransicaoNativa(DOCUMENT, 1, digest(old_content), 2,
                                              digest(content), PIN), (link,))]
    with pytest.raises(anchors.ErroAncora, match="hash divergente"):
        resolve(new, source)


@pytest.mark.parametrize("confirmation", [None, False, 1, {"valid": True}])
def test_a_link_is_not_evidence_without_strict_backend_confirmation(native, confirmation):
    old_content, content = snapshot([paragraph("Antes")]), snapshot([paragraph("Depois")])
    old, fresh = build(old_content, native), build(content, native, revision=2)
    source, target = at(old, (0,)), at(fresh, (0,))
    link = anchors.VinculoOperacional(source.block_id, source.caminho, target.caminho,
                                      source.content_hash, target.content_hash)
    with pytest.raises(anchors.ErroAncora, match="backend não confirmou"):
        reconcile(old, old_content, content, native, vinculos=(link,),
                  confirmar_vinculos=None if confirmation is None else lambda *args: confirmation)


@pytest.mark.parametrize("field,value", [("source_hash", "b" * 64), ("target_hash", "c" * 64),
                                       ("origem", anchors.CaminhoNativo(None, (1,))),
                                       ("destino", anchors.CaminhoNativo(None, (2,)))])
def test_wrong_link_hash_or_path_is_rejected_before_a_verifier_can_accept_it(native, field, value):
    old_content, content = snapshot([paragraph("Antes")]), snapshot([paragraph("Depois")])
    old, fresh = build(old_content, native), build(content, native, revision=2)
    source, target = at(old, (0,)), at(fresh, (0,))
    link = anchors.VinculoOperacional(source.block_id, source.caminho, target.caminho,
                                      source.content_hash, target.content_hash)
    with pytest.raises(anchors.ErroAncora, match="relação única"):
        reconcile(old, old_content, content, native, vinculos=(replace(link, **{field: value}),),
                  confirmar_vinculos=lambda *args: pytest.fail("invalid candidate must not reach verifier"))


def test_duplicate_content_invalidates_old_ids_even_at_the_same_positions(native):
    old_content = snapshot([paragraph("Repetido"), paragraph("Repetido"), paragraph("Único")])
    old = build(old_content, native)
    # Native style/other metadata may change while duplicate paragraphs remain.
    content = snapshot([paragraph("Repetido"), paragraph("Repetido"), paragraph("Único")],
                       core={"title": "Revisão do título"})
    new = reconcile(old, old_content, content, native)
    assert at(new, (2,)).block_id == at(old, (2,)).block_id
    assert {at(new, (i,)).block_id for i in (0, 1)}.isdisjoint(
        {at(old, (i,)).block_id for i in (0, 1)})
    assert {i.block_id for i in new.invalidacoes} == {at(old, (i,)).block_id for i in (0, 1)}
    assert {i.motivo for i in new.invalidacoes} == {"ambigua"}


def test_duplicate_inserted_or_removed_never_steals_a_preexisting_id(native):
    one, two = snapshot([paragraph("Repetido")]), snapshot([paragraph("Repetido"), paragraph("Repetido")])
    old = build(one, native)
    duplicate = reconcile(old, one, two, native)
    assert at(old, (0,)).block_id not in {b.block_id for b in duplicate.blocos}
    final = reconcile(duplicate, two, one, native)
    assert at(final, (0,)).block_id not in {b.block_id for b in duplicate.blocos}
    assert all(item.motivo == "ambigua" for item in final.invalidacoes)


def test_removed_block_cannot_be_resolved_and_its_remaining_neighbor_keeps_identity(native):
    old_content = snapshot([paragraph("Remover"), paragraph("Manter")])
    old = build(old_content, native)
    content = snapshot([paragraph("Manter")])
    new = reconcile(old, old_content, content, native)
    assert at(new, (0,)).block_id == at(old, (1,)).block_id
    assert new.invalidacoes == (anchors.Invalidacao(at(old, (0,)).block_id, "sem_correspondencia"),)
    with pytest.raises(anchors.ErroAncora, match="ausente"):
        resolve(new, at(old, (0,)))


def test_nested_tables_and_header_footer_are_projected_as_real_native_paths(native):
    nested = table(([paragraph("Célula interna")],))
    outer = table(([paragraph("Célula externa"), nested, paragraph("Final da célula")],))
    parts = {"1": {"kind": "header", "blocks": [paragraph("Cabeçalho")]},
             "2": {"kind": "footer", "blocks": [paragraph("Rodapé")]}}
    content = snapshot([outer, paragraph("Final do corpo")], parts=parts)
    index = build(content, native)
    inner = at(index, (0, 0, 0, 1, 0, 0, 0))
    assert inner.tipo == "para"
    assert resolve(index, inner).posicao() == {"story": "body", "path": [0, 0, 0, 1, 0, 0, 0]}
    assert at(index, (0,), part=1).story_kind == "header"
    assert at(index, (0,), part=2).story_kind == "footer"
    assert at(index, (0,), part=1).caminho.posicao() == {"story": {"part": 1}, "path": [0]}
    # Prepending a body paragraph moves every nested path but not unique IDs.
    new_content = snapshot([paragraph("Inserido"), outer, paragraph("Final do corpo")], parts=parts)
    new = reconcile(index, content, new_content, native)
    assert at(new, (1, 0, 0, 1, 0, 0, 0)).block_id == inner.block_id
    assert at(new, (0,), part=1).block_id == at(index, (0,), part=1).block_id


def test_table_cell_edits_do_not_guess_unchanged_table_identity(native):
    old_content = snapshot([table(([paragraph("Antes")], [paragraph("Preservar")]))])
    old = build(old_content, native)
    content = snapshot([table(([paragraph("Depois")], [paragraph("Preservar")]))])
    new = reconcile(old, old_content, content, native)
    assert at(new, (0,)).block_id != at(old, (0,)).block_id
    assert at(new, (0, 0, 0, 0)).block_id != at(old, (0, 0, 0, 0)).block_id
    assert at(new, (0, 0, 1, 0)).block_id == at(old, (0, 0, 1, 0)).block_id


@pytest.mark.parametrize("field,value", [("revision", 0), ("revision", True), ("revision", 3),
                                       ("content_hash", "b" * 64)])
def test_stale_revision_or_source_hash_never_resolves_a_persistent_id(native, field, value):
    content = snapshot([paragraph("Alvo")])
    index = build(content, native)
    with pytest.raises(anchors.ErroAncora):
        resolve(index, at(index, (0,)), **{field: value})


def test_document_or_block_hash_is_not_optional_for_resolution(native):
    content = snapshot([paragraph("Alvo")])
    index = build(content, native)
    for override in ({"document_id": OTHER_DOCUMENT}, {"block_hash": "b" * 64}):
        with pytest.raises(anchors.ErroAncora):
            resolve(index, at(index, (0,)), **override)


def test_previous_index_must_match_the_original_native_bytes_and_engine_build(native):
    content = snapshot([paragraph("Alfa"), paragraph("Beta")])
    old = build(content, native)
    tampered = replace(old, blocos=(replace(old.blocos[0], caminho=anchors.CaminhoNativo(None, (1,))),
                                   old.blocos[1]))
    with pytest.raises(anchors.ErroAncora, match="não corresponde"):
        reconcile(tampered, content, content, native)
    duplicated_id = replace(old, blocos=(old.blocos[0], replace(old.blocos[1], block_id=old.blocos[0].block_id)))
    with pytest.raises(anchors.ErroAncora, match="não corresponde"):
        reconcile(duplicated_id, content, content, native)
    with pytest.raises(anchors.ErroAncora, match="build nativo mudou"):
        anchors.validar_indice(old, content, **{**native[0], "manifest_sha256": "b" * 64})
    with pytest.raises(anchors.ErroAncora, match="Bytes não correspondem"):
        reconcile(old, snapshot([paragraph("Outra base")]), content, native)


@pytest.mark.parametrize("revision", [1, 3, True])
def test_reconciliation_cannot_skip_or_replay_revisions(native, revision):
    content = snapshot([paragraph("Alvo")])
    old = build(content, native)
    with pytest.raises(anchors.ErroAncora):
        anchors.reconciliar_indice(old, content, content, revision=revision,
                                   content_hash=digest(content), **native[0])


def test_payload_digest_and_bound_are_checked_before_native_execution(native):
    for content, declared in [(b"", digest(b"")), (b"x" * (anchors.MAX_BYTES + 1), "a" * 64),
                              (snapshot([paragraph("Alvo")]), "b" * 64)]:
        with pytest.raises(anchors.ErroAncora, match="Bytes não correspondem"):
            anchors.construir_indice(content, document_id=DOCUMENT, revision=1,
                                      content_hash=declared, **native[0])
    assert not native[1]


def test_projection_rejects_duplicate_json_fields_even_if_native_decoder_accepted(native):
    content = b'{"schema":"gc-wordcraft-snapshot/v1","document":{"body":[],"body":[],"parts":{}},"media":{},"passthrough":{}}'
    with pytest.raises(anchors.ErroAncora, match="campos duplicados"):
        build(content, native)


def test_unaddressable_native_note_separators_are_explicit(native):
    content = snapshot([paragraph("Corpo")],
                       footnoteSeparators={"separator": [paragraph("Separador")],
                                           "continuationSeparator": None, "continuationNotice": None})
    index = build(content, native)
    assert index.areas_nao_enderecaveis == ("footnoteSeparators.separator",)
    assert len(index.blocos) == 1


def test_projection_budget_is_bounded_in_addition_to_the_native_byte_limit(native, monkeypatch):
    monkeypatch.setattr(anchors, "MAX_BLOCOS", 2)
    with pytest.raises(anchors.ErroAncora, match="Quantidade"):
        build(snapshot([paragraph("A"), paragraph("B"), paragraph("C")]), native)


def test_an_operational_link_cannot_assign_two_blocks_to_one_identity(native):
    old_content = snapshot([paragraph("Alfa"), paragraph("Beta")])
    content = snapshot([paragraph("Editado A"), paragraph("Editado B")])
    old, fresh = build(old_content, native), build(content, native, revision=2)
    source = at(old, (0,))
    links = tuple(anchors.VinculoOperacional(source.block_id, source.caminho, target.caminho,
                                             source.content_hash, target.content_hash)
                  for target in fresh.blocos)
    with pytest.raises(anchors.ErroAncora, match="relação única"):
        reconcile(old, old_content, content, native, vinculos=links, confirmar_vinculos=lambda *args: True)


def test_unavailable_operational_verifier_fails_closed_without_leaking_its_error(native):
    old_content, content = snapshot([paragraph("Antes")]), snapshot([paragraph("Depois")])
    old, fresh = build(old_content, native), build(content, native, revision=2)
    source, target = at(old, (0,)), at(fresh, (0,))
    link = anchors.VinculoOperacional(source.block_id, source.caminho, target.caminho,
                                      source.content_hash, target.content_hash)

    def unavailable(*args):
        raise RuntimeError("synthetic-private-receipt-detail")

    with pytest.raises(anchors.ErroAncora, match="Não foi possível confirmar") as error:
        reconcile(old, old_content, content, native, vinculos=(link,), confirmar_vinculos=unavailable)
    assert "synthetic-private-receipt-detail" not in str(error.value)


def test_proven_edit_disambiguates_only_the_block_named_by_the_backend(native):
    old_content = snapshot([paragraph("Duplicado"), paragraph("Duplicado")])
    content = snapshot([paragraph("Editado"), paragraph("Duplicado")])
    old, fresh = build(old_content, native), build(content, native, revision=2)
    source, target = at(old, (0,)), at(fresh, (0,))
    link = anchors.VinculoOperacional(source.block_id, source.caminho, target.caminho,
                                      source.content_hash, target.content_hash)
    new = reconcile(old, old_content, content, native, vinculos=(link,), confirmar_vinculos=lambda *args: True)
    assert at(new, (0,)).block_id == source.block_id
    assert at(new, (1,)).block_id != at(old, (1,)).block_id
    assert new.invalidacoes == (anchors.Invalidacao(at(old, (1,)).block_id, "ambigua"),)


def test_native_model_unknown_to_projection_has_no_silent_partial_index(native):
    with pytest.raises(anchors.ErroAncora, match="Tipo nativo sem adaptador"):
        build(snapshot([{"kind": "futureBlock", "text": "não ignorar"}]), native)
    with pytest.raises(anchors.ErroAncora, match="Story nativa sem adaptador"):
        build(snapshot([paragraph("Corpo")],
                       parts={"1": {"kind": "futureStory", "blocks": [paragraph("não ignorar")]}}), native)


def test_index_codec_roundtrip_preserves_ids_paths_and_invalidation_without_document_text(native):
    content = snapshot([paragraph("Conteúdo privado"), paragraph("Remover")])
    old = build(content, native)
    new = reconcile(old, content, snapshot([paragraph("Conteúdo privado")]), native)
    encoded = anchors.serializar_indice(new)
    assert anchors.desserializar_indice(encoded) == new
    assert anchors.serializar_indice(anchors.desserializar_indice(encoded)) == encoded
    assert b"Conte" not in encoded and b"Remover" not in encoded


@pytest.mark.parametrize("mutation", ["extra", "duplicate", "path", "story", "invalidation"])
def test_index_codec_rejects_forged_ambiguous_or_unaddressable_sidecars(native, mutation):
    index = build(snapshot([paragraph("A"), paragraph("B")]), native)
    value = json.loads(anchors.serializar_indice(index))
    if mutation == "extra":
        value["allow_command"] = "anything"
    elif mutation == "duplicate":
        value["blocos"][1]["block_id"] = value["blocos"][0]["block_id"]
    elif mutation == "path":
        value["blocos"][0]["indices"] = [0, 0]
    elif mutation == "story":
        value["blocos"][0]["story_kind"] = "header"
    else:
        value["invalidacoes"] = [{"block_id": value["blocos"][0]["block_id"], "motivo": "ambigua"}]
    with pytest.raises(anchors.ErroAncora, match="serializado"):
        anchors.desserializar_indice(json.dumps(value).encode())
