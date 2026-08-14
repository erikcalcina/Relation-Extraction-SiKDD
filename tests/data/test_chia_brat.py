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
    Entity,
    fix_entity_offsets,
    load_document,
    parse_ann,
    repair_entity,
    surface,
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
    assert ent.spans == ((0, 12), (19, 20))
    assert surface(doc.text, ent.spans) == "greater than 1"


def test_the_three_line_types_chia_uses_are_handled():
    """Chia contains only T, R and * lines -- nothing else is parsed."""
    parsed = parse_ann(
        "T1\tDrug 0 7\taspirin\n"
        "T2\tValue 8 12\t10mg\n"
        "R1\tHas_value Arg1:T1 Arg2:T2\t\n"
        "*\tOR T1 T2\n"
    )
    assert len(parsed["entities"]) == 2
    assert len(parsed["relations"]) == 1
    assert len(parsed["equivalences"]) == 1
    assert parsed["malformed"] == []


def test_unrecognised_lines_are_collected_not_skipped():
    parsed = parse_ann("E1\tEvent:T1 Theme:T2\nT1\tDrug\n")
    assert len(parsed["malformed"]) == 2
    assert parsed["entities"] == []


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


def test_synthesised_ids_never_collide_with_real_relation_ids(tmp_path):
    """BigBIO numbers from len(relations)+10 -- a count, not the highest id."""
    ann = ("T1\tDrug 0 1\ta\nT2\tDrug 2 3\tb\nT3\tDrug 4 5\tc\n"
           "R11\tSubsumes Arg1:T1 Arg2:T2\t\n*\tOR T1 T2 T3\n")
    doc = load_document(write_pair(tmp_path, "a b c\n", ann))

    ids = [r.id for r in doc.relations]
    assert len(ids) == len(set(ids)), ids


def test_dangling_relation_argument_is_passed_through_for_the_converter(tmp_path):
    """The parser filters nothing; the converter's drop log is the one gate."""
    ann = "T1\tDrug 0 7\taspirin\nR1\tHas_value Arg1:T1 Arg2:T99\t\n"
    doc = load_document(write_pair(tmp_path, "aspirin\n", ann))

    assert [r.arg2_id for r in doc.relations] == ["T99"]
    assert "T99" not in doc.entities


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
    assert doc.relations[0].norm_type in SCHEMA_RELATION_TYPES


# --------------------------------------------------------------------------
# Offset repair
# --------------------------------------------------------------------------


def test_fix_entity_offsets_shifts_right():
    text = "the quick brown fox"
    assert fix_entity_offsets(text, "brown", (8, 13)) == (10, 15)


def test_fix_entity_offsets_gives_up_gracefully():
    """Unfindable mentions come back unchanged rather than relocated at random."""
    assert fix_entity_offsets("abc", "zzz", (0, 3)) == (0, 3)


def test_fix_entity_offsets_never_wraps_past_the_start_of_the_document():
    """A left shift below 0 must not slice from the end via negative indexing.

    BigBIO's routine searches `doc_text[left - i : right - i]` unguarded, so a
    mention near the start can match near the *end* and come back with negative
    offsets that then "verify" against the same wrapped slice.
    """
    text = "ab" + "z" * 40 + "qq"
    start, end = fix_entity_offsets(text, "qq", (0, 2))
    assert start >= 0 and text[start:end] == "qq"


def test_repair_entity_reports_exact_when_already_correct():
    assert repair_entity("aspirin 10mg", ((0, 7),), "aspirin") == (((0, 7),), "exact")


def test_repair_entity_marks_unrepairable():
    _, status = repair_entity("nothing here", ((0, 4),), "zzzz")
    assert status == "unrepaired"


def test_misaligned_discontinuous_entity_is_flagged_not_guessed():
    """No repair is attempted for multi-span mentions; Chia needs none.

    All 1,796 discontinuous mentions verify exactly once the text is read
    without newline translation, so a mismatch here means something is wrong
    upstream and should surface rather than be silently relocated.
    """
    text = "xx greater than Grade 1 toxicity"
    _, status = repair_entity(text, ((0, 12), (19, 20)), "greater than 1")
    assert status == "unrepaired"


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
            if surface(doc.text, ent.spans) == ent.ann_text:
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


@requires_corpus
def test_corpus_contains_only_the_three_parsed_line_types():
    """The reason this parser is scoped the way it is -- asserted, not assumed."""
    tags = {line[0] for path in CORPUS.glob("*.ann")
            for line in path.read_text(encoding="utf-8").splitlines() if line}
    assert tags == {"T", "R", "*"}


@requires_corpus
def test_corpus_has_no_malformed_lines_and_no_duplicate_entity_ids():
    from relation_extraction.data.chia_brat import load_corpus

    for path in sorted(CORPUS.glob("*.ann")):
        parsed = parse_ann(path.read_text(encoding="utf-8"))
        assert parsed["malformed"] == [], path.name
        ids = [e["id"] for e in parsed["entities"]]
        assert len(ids) == len(set(ids)), path.name

    for doc in load_corpus(CORPUS):
        rel_ids = [r.id for r in doc.relations]
        assert len(rel_ids) == len(set(rel_ids)), doc.doc_key


def test_discontinuous_entity_enclosing_span():
    entity = Entity(
        id="T1",
        type="Condition",
        spans=((40, 50), (12, 24)),
        ann_text="example",
    )

    assert entity.start == 12
    assert entity.end == 50
