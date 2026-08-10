"""Phase 2: convert the Chia corpus to criterion-level JSONL and split it.

Design decisions are the user's, recorded in ``docs/chia/README.md``:

* **Native labels only.** Relation labels are the annotators' own strings
  (``Has_value``, ``Subsumes``, ``AND`` …). No merging, no derived
  argument-typed names, no invented categories.
* **`AND`/`OR` are kept but flagged** (``"boolean": true``) so an experiment can
  include or exclude them without regenerating the data, and they are counted
  separately everywhere.
* **Discontinuous entities merge to their enclosing span**, keeping the original
  fragments and a ``discontinuous`` flag.
* **Nested and overlapping entities are all kept.** No flattening.
* **One criterion (one line) is one instance**, justified by §1.4 of the profile
  report: only 6 of 34,719 relations cross a criterion boundary.
* **Splits are grouped by NCT id**, so every criterion from a trial —
  inclusion and exclusion — lands in the same split.
"""

from __future__ import annotations

import collections
import random
from dataclasses import dataclass, field
from pathlib import Path

from .chia_brat import (
    SCHEMA_ENTITY_TYPES,
    SCHEMA_RELATION_TYPES,
    Document,
    Entity,
)

#: Relation types that encode Boolean structure rather than a semantic relation.
#: Kept in the output, flagged, and counted separately.
BOOLEAN_RELATION_TYPES = frozenset({"AND", "OR"})

DEFAULT_SPLIT_FRACTIONS = (0.70, 0.10, 0.20)
SPLIT_NAMES = ("train", "dev", "test")


@dataclass
class DropLog:
    """Every record dropped or modified, with a reason."""

    counts: collections.Counter = field(default_factory=collections.Counter)
    examples: dict[str, list] = field(default_factory=lambda: collections.defaultdict(list))

    def add(self, reason: str, detail: str = "") -> None:
        self.counts[reason] += 1
        if len(self.examples[reason]) < 10 and detail:
            self.examples[reason].append(detail)

    def total(self) -> int:
        return sum(self.counts.values())


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------


def _local_fragments(
    entity: Entity, line_start: int, line_end: int
) -> list[list[int]] | None:
    """Re-base an entity's fragments against the criterion. None if it escapes."""
    out = []
    for start, end in entity.spans:
        if start < line_start or end > line_end:
            return None
        out.append([start - line_start, end - line_start])
    return out


def convert_document(
    doc: Document, drops: DropLog, *, keep_empty: bool = False
) -> list[dict]:
    """Split one file into criterion-level instances with re-based offsets."""
    instances: list[dict] = []
    criteria = doc.criterion_spans()

    # Assign every in-schema entity to the criterion that fully contains it.
    entity_home: dict[str, int] = {}
    for ent in doc.entities.values():
        if ent.type not in SCHEMA_ENTITY_TYPES:
            drops.add("entity: out-of-schema type", f"{doc.doc_key}/{ent.id} {ent.type}")
            continue
        if ent.offset_status == "unrepaired":
            drops.add(
                "entity: offsets could not be verified against the text",
                f"{doc.doc_key}/{ent.id} {ent.type} {ent.ann_text!r}",
            )
            continue
        home = None
        for idx, (line_start, line_end) in enumerate(criteria):
            if ent.start >= line_start and ent.end <= line_end:
                home = idx
                break
        if home is None:
            drops.add(
                "entity: span crosses a criterion boundary",
                f"{doc.doc_key}/{ent.id} {ent.type} {ent.ann_text!r}",
            )
            continue
        entity_home[ent.id] = home

    by_criterion: dict[int, list[Entity]] = collections.defaultdict(list)
    for ent_id, idx in entity_home.items():
        by_criterion[idx].append(doc.entities[ent_id])

    # Route relations to the criterion holding both arguments.
    rels_by_criterion: dict[int, list] = collections.defaultdict(list)
    for rel in doc.relations:
        if rel.norm_type not in SCHEMA_RELATION_TYPES:
            drops.add(
                f"relation: out-of-schema type ({rel.type})",
                f"{doc.doc_key}/{rel.id}",
            )
            continue
        home1 = entity_home.get(rel.arg1_id)
        home2 = entity_home.get(rel.arg2_id)
        if home1 is None or home2 is None:
            drops.add(
                "relation: argument was dropped",
                f"{doc.doc_key}/{rel.id} {rel.type}",
            )
            continue
        if home1 != home2:
            drops.add(
                "relation: arguments in different criteria",
                f"{doc.doc_key}/{rel.id} {rel.type}",
            )
            continue
        rels_by_criterion[home1].append(rel)

    for idx, (line_start, line_end) in enumerate(criteria):
        text = doc.text[line_start:line_end]
        entities = []
        for ent in sorted(by_criterion.get(idx, []), key=lambda e: (e.start, e.end)):
            fragments = _local_fragments(ent, line_start, line_end)
            if fragments is None:  # already screened above; belt and braces
                drops.add("entity: fragment escaped its criterion", ent.id)
                continue

            # Offset assertions -- fail loudly, per the brief.
            rebuilt = " ".join(text[s:e] for s, e in fragments)
            assert rebuilt == ent.ann_text, (
                f"offset mismatch in {doc.doc_key} criterion {idx} entity {ent.id}: "
                f"{rebuilt!r} != {ent.ann_text!r}"
            )
            start, end = fragments[0][0], fragments[-1][1]
            if len(fragments) == 1:
                assert text[start:end] == ent.ann_text, (
                    f"contiguous offset mismatch in {doc.doc_key} entity {ent.id}"
                )

            entities.append(
                {
                    "id": ent.id,
                    "type": ent.type,
                    # Discontinuous entities are merged to their enclosing span;
                    # `fragments` retains exactly what the annotators marked.
                    "start": start,
                    "end": end,
                    "text": ent.ann_text,
                    "span_text": text[start:end],
                    "discontinuous": len(fragments) > 1,
                    "fragments": fragments,
                    "offset_status": ent.offset_status,
                }
            )

        if not entities and not keep_empty:
            drops.add(
                "criterion: no in-schema entities, yields no candidate pairs",
                f"{doc.doc_key}[{idx}] {text[:60]!r}",
            )
            continue

        kept_ids = {e["id"] for e in entities}
        relations = []
        for rel in rels_by_criterion.get(idx, []):
            if rel.arg1_id not in kept_ids or rel.arg2_id not in kept_ids:
                drops.add("relation: argument was dropped", f"{doc.doc_key}/{rel.id}")
                continue
            relations.append(
                {
                    "id": rel.id,
                    # Native Chia label, exactly as annotated.
                    "type": rel.type,
                    "arg1_id": rel.arg1_id,
                    "arg2_id": rel.arg2_id,
                    "boolean": rel.norm_type in BOOLEAN_RELATION_TYPES,
                    "synthesised": rel.origin == "EQUIV",
                }
            )

        instances.append(
            {
                "id": f"{doc.doc_key}_{idx}",
                "nct_id": doc.nct_id,
                "doc_key": doc.doc_key,
                "text_type": doc.text_type,
                "criterion_index": idx,
                "text": text,
                "entities": entities,
                "relations": relations,
            }
        )

    return instances


# --------------------------------------------------------------------------
# Negatives
# --------------------------------------------------------------------------


def add_negatives(
    instances: list[dict],
    *,
    seed: int,
    ratio: float | None,
    include_boolean: bool,
) -> dict:
    """Attach NA (unrelated) entity pairs to every instance.

    Candidate rule: **every ordered pair of distinct entities inside the same
    criterion that is not linked by a gold relation.** Ordered, because Chia's
    relations are directed and ``(a, b)`` carrying no relation is a different
    fact from ``(b, a)`` carrying one.

    ``include_boolean`` controls whether an ``AND``/``OR`` pair counts as
    "already related" (and so is excluded from the negatives) or is treated as
    unrelated. Default is to treat them as related, so that toggling the Boolean
    relations off at experiment time never silently turns a positive into a
    negative.

    ``ratio`` subsamples negatives to ``ratio x positives`` per instance; None
    keeps every candidate. The **identical** procedure and seed are applied to
    all three splits.
    """
    rng = random.Random(seed)
    stats = collections.Counter()

    for inst in instances:
        linked = set()
        n_pos = 0
        for rel in inst["relations"]:
            if rel["boolean"] and not include_boolean:
                continue
            linked.add((rel["arg1_id"], rel["arg2_id"]))
            if rel["boolean"]:
                # AND/OR are symmetric (annotation.conf declares OR
                # "symmetric-transitive") and are expanded in one direction
                # only, so the reverse pair must not become a negative.
                linked.add((rel["arg2_id"], rel["arg1_id"]))
            n_pos += 1

        ids = [e["id"] for e in inst["entities"]]
        candidates = [
            (a, b) for a in ids for b in ids if a != b and (a, b) not in linked
        ]
        stats["candidates"] += len(candidates)

        if ratio is not None:
            keep = int(round(ratio * n_pos))
            if keep < len(candidates):
                candidates = rng.sample(candidates, keep)

        inst["negative_pairs"] = [{"arg1_id": a, "arg2_id": b} for a, b in candidates]
        stats["kept"] += len(candidates)

    return dict(stats)


# --------------------------------------------------------------------------
# Splitting
# --------------------------------------------------------------------------


def make_splits(
    nct_ids: list[str],
    *,
    seed: int,
    fractions: tuple[float, float, float] = DEFAULT_SPLIT_FRACTIONS,
) -> dict[str, str]:
    """Assign every trial to exactly one split. Grouping is by NCT id."""
    assert abs(sum(fractions) - 1.0) < 1e-9, f"fractions must sum to 1: {fractions}"

    ordered = sorted(set(nct_ids))  # sort first so the shuffle is deterministic
    random.Random(seed).shuffle(ordered)

    n = len(ordered)
    n_train = int(round(fractions[0] * n))
    n_dev = int(round(fractions[1] * n))
    bounds = {
        "train": ordered[:n_train],
        "dev": ordered[n_train : n_train + n_dev],
        "test": ordered[n_train + n_dev :],
    }

    # Assert pairwise disjointness rather than assuming it.
    for i, a in enumerate(SPLIT_NAMES):
        for b in SPLIT_NAMES[i + 1 :]:
            overlap = set(bounds[a]) & set(bounds[b])
            assert not overlap, f"{a}/{b} share {len(overlap)} trials: {sorted(overlap)[:5]}"
    assert sum(len(v) for v in bounds.values()) == n, "split sizes do not sum to n"
    assert set().union(*(set(v) for v in bounds.values())) == set(ordered)

    return {nct: name for name, group in bounds.items() for nct in group}


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------


def split_statistics(instances_by_split: dict[str, list[dict]]) -> dict:
    """Per-split totals plus per-relation-type counts, Boolean kept separate."""
    out: dict[str, dict] = {}
    for name in SPLIT_NAMES:
        insts = instances_by_split[name]
        rel_types: collections.Counter = collections.Counter()
        n_bool = n_sem = 0
        n_ent = n_disc = 0
        ent_types: collections.Counter = collections.Counter()
        for inst in insts:
            n_ent += len(inst["entities"])
            n_disc += sum(1 for e in inst["entities"] if e["discontinuous"])
            for ent in inst["entities"]:
                ent_types[ent["type"]] += 1
            for rel in inst["relations"]:
                rel_types[rel["type"]] += 1
                if rel["boolean"]:
                    n_bool += 1
                else:
                    n_sem += 1
        out[name] = {
            "trials": len({i["nct_id"] for i in insts}),
            "documents": len({i["doc_key"] for i in insts}),
            "criteria": len(insts),
            "entities": n_ent,
            "discontinuous_entities": n_disc,
            "relations": n_bool + n_sem,
            "semantic_relations": n_sem,
            "boolean_relations": n_bool,
            "negative_pairs": sum(len(i.get("negative_pairs", [])) for i in insts),
            "relation_types": dict(rel_types.most_common()),
            "entity_types": dict(ent_types.most_common()),
        }
    return out
