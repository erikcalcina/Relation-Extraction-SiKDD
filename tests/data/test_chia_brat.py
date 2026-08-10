"""Tests for the Chia brat parser.

The corpus-level tests are skipped automatically when `data/raw/without_scope`
has not been downloaded.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from relation_extraction.data.chia_brat import (  # noqa: E402
    SCHEMA_RELATION_TYPES,
    fix_entity_offsets,
    load_document,
    normalise_criterion,
    parse_ann,
    repair_entity,
    sentence_spans,
)

CORPUS = ROOT / "data" / "raw" / "without_scope"
requires_corpus = pytest.mark.skipif(
    not CORPUS.exists(), reason="Chia corpus not downloaded"
)


def write_pair(tmp_path: Path, text: str, ann: str, stem: str = "NCT00000001_inc"):
    txt = tmp_path / f"{stem}.txt"
    txt.write_bytes(text.encode("utf-8"))
    (tmp_path / f"{stem}.ann").write_text(ann, encoding="utf-8")
    return txt


# --------------------------------------------------------------------------
# The CRLF regression -- the single most important behaviour in this module
# --------------------------------------------------------------------------


def test_crlf_is_not_translated(tmp_path):
    """Offsets must be interpreted against the bytes on disk, not a rewrite.

    Reading a CRLF file in universal-newline mode deletes one character per
    preceding line, which silently invalidates every downstream offset. This is
    the bug that gives Chia its reputation for broken offsets.
    """
    text = "aspirin daily\r\nserum creatinine > 2\r\n"
    # "serum creatinine" starts at 15 in the raw bytes, 14 after translation.
    doc = load_document(write_pair(tmp_path, text, "T1\tMeasurement 15 31\tserum creatinine\n"))

    assert "\r\n" in doc.text
    ent = doc.entities["T1"]
    assert ent.offset_status == "exact"
    assert doc.text[ent.start : ent.end] == "serum creatinine"


def test_criterion_spans_exclude_carriage_return(tmp_path):
    doc = load_document(write_pair(tmp_path, "first line\r\n\r\nsecond line\r\n", ""))
    spans = doc.criterion_spans()
    assert [doc.text[s:e] for s, e in spans] == ["first line", "second line"]


# --------------------------------------------------------------------------
# Standoff parsing
# --------------------------------------------------------------------------


def test_multi_span_offsets_are_parsed(tmp_path):
    text = "greater than Grade 1 toxicity\n"
    ann = "T1\tValue 0 12;19 20\tgreater than 1\n"
    doc = load_document(write_pair(tmp_path, text, ann))

    ent = doc.entities["T1"]
    assert ent.is_discontinuous
    assert ent.spans == ((0, 12), (19, 20))
    assert ent.surface(doc.text) == "greater than 1"


def test_all_brat_line_types_are_handled():
    parsed = parse_ann(
        "T1\tDrug 0 7\taspirin\n"
        "T2\tValue 8 12\t10mg\n"
        "R1\tHas_value Arg1:T1 Arg2:T2\t\n"
        "*\tOR T1 T2\n"
        "E1\tEvent:T1 Theme:T2\n"
        "A1\tOptional T1\n"
        "N1\tReference T1 UMLS:C0004057\taspirin\n"
    )
    assert len(parsed["text_bound_annotations"]) == 2
    assert len(parsed["relations"]) == 1
    assert len(parsed["equivalences"]) == 1
    assert len(parsed["events"]) == 1
    assert len(parsed["attributes"]) == 1
    assert len(parsed["normalizations"]) == 1
    assert parsed["malformed"] == []


def test_equivalence_expands_to_pairwise_relations(tmp_path):
    text = "a b c\n"
    ann = ("T1\tDrug 0 1\ta\nT2\tDrug 2 3\tb\nT3\tDrug 4 5\tc\n*\tOR T1 T2 T3\n")
    doc = load_document(write_pair(tmp_path, text, ann))

    synth = [r for r in doc.relations if r.origin == "EQUIV"]
    assert len(synth) == 3  # C(3, 2)
    assert {(r.arg1_id, r.arg2_id) for r in synth} == {
        ("T1", "T2"), ("T1", "T3"), ("T2", "T3")
    }
    assert all(r.type == "OR" for r in synth)


def test_equivalence_synthesis_can_be_disabled(tmp_path):
    ann = "T1\tDrug 0 1\ta\nT2\tDrug 2 3\tb\n*\tOR T1 T2\n"
    doc = load_document(write_pair(tmp_path, "a b\n", ann), synthesise_or=False)
    assert doc.relations == []
    assert len(doc.equivalences) == 1


def test_dangling_relation_argument_is_recorded_not_silently_dropped(tmp_path):
    ann = "T1\tDrug 0 7\taspirin\nR1\tHas_value Arg1:T1 Arg2:T99\t\n"
    doc = load_document(write_pair(tmp_path, "aspirin\n", ann))

    assert doc.relations == []
    assert [(d.kind, d.reason) for d in doc.drops] == [
        ("relation", "dangling_argument")
    ]


# --------------------------------------------------------------------------
# Relation type matching (trap 1 and trap 2)
# --------------------------------------------------------------------------


def test_has_context_has_no_trailing_space():
    """The BigBIO loader's `"HAS_CONTEXT "` typo drops every Has_context."""
    assert "HAS_CONTEXT" in SCHEMA_RELATION_TYPES
    assert "HAS_CONTEXT " not in SCHEMA_RELATION_TYPES


@pytest.mark.parametrize(
    "raw", ["Has_value", "HAS_VALUE", "has_value", "Has_context", "Subsumes"]
)
def test_relation_types_match_case_insensitively(tmp_path, raw):
    ann = f"T1\tDrug 0 1\ta\nT2\tValue 2 3\tb\nR1\t{raw} Arg1:T1 Arg2:T2\t\n"
    doc = load_document(write_pair(tmp_path, "a b\n", ann))
    assert doc.relations[0].in_schema


# --------------------------------------------------------------------------
# Offset repair
# --------------------------------------------------------------------------


def test_fix_entity_offsets_shifts_right():
    text = "the quick brown fox"
    assert fix_entity_offsets(text, "brown", (8, 13)) == (10, 15)


def test_fix_entity_offsets_gives_up_gracefully():
    """Unfindable mentions come back unchanged rather than relocated at random."""
    assert fix_entity_offsets("abc", "zzz", (0, 3)) == (0, 3)


def test_repair_entity_reports_exact_when_already_correct():
    assert repair_entity("aspirin 10mg", ((0, 7),), "aspirin") == (((0, 7),), "exact")


def test_repair_entity_global_shift_fixes_discontinuous_spans():
    """BigBIO cannot repair these at all; a single shared delta can."""
    text = "xx greater than Grade 1 toxicity"
    spans, status = repair_entity(text, ((0, 12), (19, 20)), "greater than 1")
    assert status == "global_shift"
    assert " ".join(text[s:e] for s, e in spans) == "greater than 1"


def test_repair_entity_marks_unrepairable():
    _, status = repair_entity("nothing here", ((0, 4),), "zzzz")
    assert status == "unrepaired"


# --------------------------------------------------------------------------
# Text utilities
# --------------------------------------------------------------------------


def test_normalise_criterion_collapses_whitespace_and_case():
    assert normalise_criterion("  Written   INFORMED\tconsent \n") == (
        "written informed consent"
    )


def test_sentence_spans_splits_within_a_line_only():
    text = "First one. Second one."
    assert [text[s:e] for s, e in sentence_spans(text, (0, len(text)))] == [
        "First one. ",
        "Second one.",
    ]


# --------------------------------------------------------------------------
# Corpus-level invariants
# --------------------------------------------------------------------------


@requires_corpus
def test_corpus_offsets_verify_against_the_text():
    """>=99.9% of in-schema entities must reproduce their mention text exactly."""
    from relation_extraction.data.chia_brat import SCHEMA_ENTITY_TYPES, load_corpus

    docs = load_corpus(CORPUS)
    total = exact = 0
    for doc in docs:
        for ent in doc.entities.values():
            if ent.type not in SCHEMA_ENTITY_TYPES:
                continue
            total += 1
            if ent.surface(doc.text) == ent.ann_text:
                exact += 1
    assert total == 40976
    assert exact / total > 0.999, f"only {exact}/{total} offsets verify"


@requires_corpus
def test_corpus_reconciles_on_documents_and_criteria():
    from relation_extraction.data.chia_brat import load_corpus

    docs = load_corpus(CORPUS)
    assert len(docs) == 2000
    assert len({d.nct_id for d in docs}) == 1000
    assert sum(len(d.criterion_spans()) for d in docs) == 12409
