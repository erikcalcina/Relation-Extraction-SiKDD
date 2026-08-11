"""Tests for the Chia Phase 2 converter and splitter.

The corpus-level tests are skipped when the data has not been prepared.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from relation_extraction.data.chia_brat import load_document  # noqa: E402
from relation_extraction.data.chia_convert import (  # noqa: E402
    SPLIT_NAMES,
    DropLog,
    add_negatives,
    convert_document,
    make_splits,
)

PROCESSED = ROOT / "data" / "processed"
SPLIT_JSON = ROOT / "data" / "splits" / "split.json"
requires_prepared = pytest.mark.skipif(
    not (PROCESSED / "chia_train.jsonl").exists(),
    reason="run scripts/prepare_chia.py first",
)


def write_pair(tmp_path: Path, text: str, ann: str, stem="NCT00000001_inc"):
    txt = tmp_path / f"{stem}.txt"
    txt.write_bytes(text.encode("utf-8"))
    (tmp_path / f"{stem}.ann").write_text(ann, encoding="utf-8")
    return txt


# --------------------------------------------------------------------------
# Offset re-basing
# --------------------------------------------------------------------------


def test_offsets_are_rebased_to_the_criterion(tmp_path):
    text = "aspirin daily\r\nserum creatinine > 2\r\n"
    ann = (
        "T3\tDrug 0 7\taspirin\n"
        "T1\tMeasurement 15 31\tserum creatinine\n"
        "T2\tValue 32 35\t> 2\n"
    )
    doc = load_document(write_pair(tmp_path, text, ann))

    insts = convert_document(doc, DropLog())
    assert len(insts) == 2
    # Second criterion starts at raw offset 15; its entities must be re-based
    # to 0, and the "\r" must not leak into the criterion text.
    second = insts[1]
    assert second["text"] == "serum creatinine > 2"
    ent = second["entities"][0]
    assert (ent["start"], ent["end"]) == (0, 16)
    assert second["text"][ent["start"] : ent["end"]] == "serum creatinine"


def test_every_emitted_entity_offset_reproduces_its_text(tmp_path):
    text = "a stable dose of aspirin 10mg\n"
    ann = ("T1\tDrug 17 24\taspirin\nT2\tValue 25 29\t10mg\n"
           "R1\tHas_value Arg1:T1 Arg2:T2\t\n")
    doc = load_document(write_pair(tmp_path, text, ann))

    for inst in convert_document(doc, DropLog()):
        for ent in inst["entities"]:
            rebuilt = " ".join(inst["text"][s:e] for s, e in ent["fragments"])
            assert rebuilt == ent["text"]


def test_discontinuous_entity_merges_to_enclosing_span(tmp_path):
    text = "greater than Grade 1 toxicity\n"
    ann = "T1\tValue 0 12;19 20\tgreater than 1\n"
    doc = load_document(write_pair(tmp_path, text, ann))

    ent = convert_document(doc, DropLog())[0]["entities"][0]
    assert ent["discontinuous"] is True
    assert ent["fragments"] == [[0, 12], [19, 20]]
    assert (ent["start"], ent["end"]) == (0, 20)
    assert ent["span_text"] == "greater than Grade 1"  # over-covers, by design
    assert ent["text"] == "greater than 1"  # what the annotators marked


def test_cross_criterion_relation_is_dropped_and_logged(tmp_path):
    text = "aspirin\nserum creatinine\n"
    ann = ("T1\tDrug 0 7\taspirin\nT2\tMeasurement 8 24\tserum creatinine\n"
           "R1\tSubsumes Arg1:T1 Arg2:T2\t\n")
    doc = load_document(write_pair(tmp_path, text, ann))
    drops = DropLog()

    insts = convert_document(doc, drops)
    assert all(not i["relations"] for i in insts)
    assert drops.counts["relation: arguments in different criteria"] == 1


def test_empty_criteria_are_dropped_but_logged(tmp_path):
    text = "aspirin\nno annotations on this line\n"
    doc = load_document(write_pair(tmp_path, text, "T1\tDrug 0 7\taspirin\n"))
    drops = DropLog()

    insts = convert_document(doc, drops)
    assert len(insts) == 1
    assert drops.counts["criterion: no in-schema entities, yields no candidate pairs"] == 1


def test_empty_criteria_can_be_kept(tmp_path):
    text = "aspirin\nno annotations on this line\n"
    doc = load_document(write_pair(tmp_path, text, "T1\tDrug 0 7\taspirin\n"))
    assert len(convert_document(doc, DropLog(), keep_empty=True)) == 2


def test_relation_labels_stay_native(tmp_path):
    """No derived names, no merging -- the annotators' own string."""
    ann = ("T1\tMeasurement 0 1\ta\nT2\tValue 2 3\tb\n"
           "R1\tHas_value Arg1:T1 Arg2:T2\t\n")
    doc = load_document(write_pair(tmp_path, "a b\n", ann))

    rel = convert_document(doc, DropLog())[0]["relations"][0]
    assert rel["type"] == "Has_value"
    assert rel["boolean"] is False


def test_boolean_relations_are_flagged(tmp_path):
    ann = "T1\tDrug 0 1\ta\nT2\tDrug 2 3\tb\nR1\tAND Arg1:T1 Arg2:T2\t\n"
    doc = load_document(write_pair(tmp_path, "a b\n", ann))

    rel = convert_document(doc, DropLog())[0]["relations"][0]
    assert rel["type"] == "AND"
    assert rel["boolean"] is True


# --------------------------------------------------------------------------
# Negatives
# --------------------------------------------------------------------------


def _instance(entity_ids, relations):
    return {
        "entities": [{"id": i} for i in entity_ids],
        "relations": relations,
    }


def test_negatives_exclude_gold_pairs():
    inst = _instance(
        ["T1", "T2"],
        [{"arg1_id": "T1", "arg2_id": "T2", "boolean": False}],
    )
    add_negatives([inst], seed=1, ratio=None, include_boolean=True)
    assert inst["negative_pairs"] == [{"arg1_id": "T2", "arg2_id": "T1"}]


def test_symmetric_boolean_relations_block_both_directions():
    """AND/OR are symmetric but expanded one way; the reverse is not a negative."""
    inst = _instance(
        ["T1", "T2"],
        [{"arg1_id": "T1", "arg2_id": "T2", "boolean": True}],
    )
    add_negatives([inst], seed=1, ratio=None, include_boolean=True)
    assert inst["negative_pairs"] == []


def test_negative_subsampling_is_seeded_and_reproducible():
    def build():
        inst = _instance(
            [f"T{i}" for i in range(6)],
            [{"arg1_id": "T0", "arg2_id": "T1", "boolean": False}],
        )
        add_negatives([inst], seed=42, ratio=2.0, include_boolean=True)
        return inst["negative_pairs"]

    first, second = build(), build()
    assert first == second
    assert len(first) == 2  # ratio 2.0 x 1 positive


def test_subsampling_keeps_a_negative_for_all_NA_criteria():
    """`ratio x 0 positives` must not erase the abstain examples entirely."""
    inst = _instance(["T1", "T2", "T3"], [])
    add_negatives([inst], seed=1, ratio=2.0, include_boolean=True)
    assert len(inst["negative_pairs"]) == 1


def test_offset_mismatch_raises_rather_than_asserting(tmp_path, monkeypatch):
    """The guarantee must survive `python -O`, which strips `assert`."""
    from relation_extraction.data import chia_convert

    doc = load_document(
        write_pair(tmp_path, "aspirin\n", "T1\tDrug 0 7\taspirin\n")
    )
    doc.entities["T1"].ann_text = "not what the text says"
    with pytest.raises(ValueError, match="offset mismatch"):
        chia_convert.convert_document(doc, DropLog())


# --------------------------------------------------------------------------
# Splits
# --------------------------------------------------------------------------


def test_splits_are_pairwise_disjoint_and_complete():
    ids = [f"NCT{i:08d}" for i in range(1000)]
    mapping = make_splits(ids, seed=7)

    groups = {name: {k for k, v in mapping.items() if v == name} for name in SPLIT_NAMES}
    assert set(mapping) == set(ids)
    assert not groups["train"] & groups["dev"]
    assert not groups["train"] & groups["test"]
    assert not groups["dev"] & groups["test"]
    assert (len(groups["train"]), len(groups["dev"]), len(groups["test"])) == (700, 100, 200)


def test_splits_are_deterministic_for_a_seed():
    ids = [f"NCT{i:08d}" for i in range(500)]
    assert make_splits(ids, seed=7) == make_splits(ids, seed=7)
    assert make_splits(ids, seed=7) != make_splits(ids, seed=8)


def test_split_fractions_must_sum_to_one():
    with pytest.raises(ValueError):
        make_splits(["NCT1", "NCT2"], seed=1, fractions=(0.5, 0.2, 0.2))


# --------------------------------------------------------------------------
# Corpus-level checks on the emitted files
# --------------------------------------------------------------------------


def _load(split: str) -> list[dict]:
    with (PROCESSED / f"chia_{split}.jsonl").open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


@requires_prepared
def test_emitted_offsets_all_verify():
    for split in SPLIT_NAMES:
        for inst in _load(split):
            for ent in inst["entities"]:
                rebuilt = " ".join(inst["text"][s:e] for s, e in ent["fragments"])
                assert rebuilt == ent["text"], f"{inst['id']}/{ent['id']}"
                assert ent["start"] == ent["fragments"][0][0]
                assert ent["end"] == ent["fragments"][-1][1]


@requires_prepared
def test_emitted_relations_reference_present_entities():
    for split in SPLIT_NAMES:
        for inst in _load(split):
            ids = {e["id"] for e in inst["entities"]}
            for rel in inst["relations"]:
                assert rel["arg1_id"] in ids and rel["arg2_id"] in ids, inst["id"]
            for pair in inst["negative_pairs"]:
                assert pair["arg1_id"] in ids and pair["arg2_id"] in ids, inst["id"]


@requires_prepared
def test_no_nct_id_appears_in_two_splits():
    groups = {split: {i["nct_id"] for i in _load(split)} for split in SPLIT_NAMES}
    assert not groups["train"] & groups["dev"]
    assert not groups["train"] & groups["test"]
    assert not groups["dev"] & groups["test"]


@requires_prepared
def test_inclusion_and_exclusion_of_a_trial_share_a_split():
    home: dict[str, str] = {}
    for split in SPLIT_NAMES:
        for inst in _load(split):
            assert home.setdefault(inst["nct_id"], split) == split, inst["nct_id"]


@requires_prepared
def test_negatives_never_collide_with_gold_relations():
    for split in SPLIT_NAMES:
        for inst in _load(split):
            gold = {(r["arg1_id"], r["arg2_id"]) for r in inst["relations"]}
            gold |= {
                (r["arg2_id"], r["arg1_id"])
                for r in inst["relations"] if r["boolean"]
            }
            for pair in inst["negative_pairs"]:
                assert (pair["arg1_id"], pair["arg2_id"]) not in gold, inst["id"]


@requires_prepared
def test_split_json_covers_every_trial_and_matches_the_files():
    payload = json.loads(SPLIT_JSON.read_text(encoding="utf-8"))
    assert payload["grouping"] == "nct_id"
    assert len(payload["assignments"]) == 1000
    for split in SPLIT_NAMES:
        for inst in _load(split):
            assert payload["assignments"][inst["nct_id"]] == split
