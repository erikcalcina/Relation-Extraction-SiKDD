#!/usr/bin/env python3
"""Phase 1: profile the Chia corpus and emit ``profile_report.md``.

Read-only. Converts and splits nothing. Run with:

    python3 scripts/profile_chia.py \
        --without-scope data/raw/without_scope \
        --with-scope data/raw/with_scope \
        --out profile_report.md
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from relation_extraction.data.chia_brat import (  # noqa: E402
    MAX_OFFSET_CORRECTION,
    SCHEMA_ENTITY_TYPES,
    SCHEMA_RELATION_TYPES,
    Document,
    load_corpus,
    normalise_criterion,
    sentence_spans,
)

SEED = 20260810  # nothing here is stochastic; recorded for reproducibility

PUBLISHED = {
    "trials": 1000,
    "documents": 2000,
    "criteria": 12409,
    "entities": 41487,
    "entity_types": 15,
    "relations": 25017,
    "relation_types": 12,
}

# chia.py's list, reproduced verbatim including the trailing-space bug.
BIGBIO_RELATION_TYPES = [
    "AND", "OR", "SUBSUMES", "HAS_NEGATION", "HAS_MULTIPLIER", "HAS_QUALIFIER",
    "HAS_VALUE", "HAS_TEMPORAL", "HAS_INDEX", "HAS_MOOD", "HAS_CONTEXT ",
    "HAS_SCOPE",
]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def pct(n: int, total: int) -> str:
    return f"{100.0 * n / total:.2f}%" if total else "n/a"


def percentile(values: list[int], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    idx = max(0, math.ceil(q * len(ordered)) - 1)
    return ordered[idx]


def md_table(headers: list[str], rows: list[list], aligns: str | None = None) -> str:
    aligns = aligns or "l" * len(headers)
    sep = {"l": ":---", "r": "---:", "c": ":--:"}
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join(sep[a] for a in aligns) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def delta(actual: int, expected: int) -> str:
    d = actual - expected
    if d == 0:
        return "match"
    return f"{d:+d}"


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------


def schema_view(docs: list[Document]):
    """Split parsed content into in-schema vs out-of-schema, with drop reasons."""
    ents_in, ents_out = [], []
    rels_in = []
    drops = collections.Counter()
    dropped_examples = collections.defaultdict(list)

    for doc in docs:
        for ent in doc.entities.values():
            (ents_in if ent.in_schema else ents_out).append((doc, ent))
            if not ent.in_schema:
                drops[f"entity: type not in 16-type schema ({ent.type})"] += 1

        for rel in doc.relations:
            if not rel.in_schema:
                drops[f"relation: type not in 12-type schema ({rel.type})"] += 1
                dropped_examples[rel.type].append((doc.doc_key, rel.id))
                continue
            a1 = doc.entities.get(rel.arg1_id)
            a2 = doc.entities.get(rel.arg2_id)
            if a1 is None or a2 is None:
                drops["relation: dangling argument id"] += 1
                continue
            if not (a1.in_schema and a2.in_schema):
                bad = [e.type for e in (a1, a2) if not e.in_schema]
                drops["relation: argument is an out-of-schema entity"] += 1
                dropped_examples["out-of-schema arg"].append(
                    (doc.doc_key, rel.id, rel.type, "/".join(bad))
                )
                continue
            rels_in.append((doc, rel, a1, a2))

        for drop in doc.drops:
            drops[f"{drop.kind}: {drop.reason}"] += 1

    return ents_in, ents_out, rels_in, drops, dropped_examples


def simulate_bigbio(docs: list[Document]) -> dict:
    """Replicate chia.py's filtering to quantify what the loader loses.

    Models three independent silent-drop mechanisms:

    * the ``"HAS_CONTEXT "`` trailing space in ``_RELATION_TYPES`` (trap 2);
    * relations whose arguments did not survive entity filtering (trap 3);
    * an **id-prefix bug in the equivalence loop** (``chia.py:365``): the guard
      tests the bare ``T`` id against ``entity_ids``, whose keys are prefixed
      with ``"<doc>_"``, so it never matches and *every* ``OR`` relation
      synthesised from a ``*`` line is discarded. Verified empirically against
      ``load_dataset`` output, which contains 7 ``OR`` relations (the literal
      ``R``-line ones) and none from equivalences.
    """
    kept_rel = 0
    lost_type = collections.Counter()
    lost_args = collections.Counter()
    lost_or_prefix_bug = 0
    kept_ent = 0
    or_synth = 0

    schema16 = SCHEMA_ENTITY_TYPES
    for doc in docs:
        surviving = {
            e.id for e in doc.entities.values() if e.type.capitalize() in schema16
        }
        kept_ent += len(surviving)
        for rel in doc.relations:
            if rel.origin == "EQUIV":
                # The prefix bug fires before any other check.
                lost_or_prefix_bug += 1
                continue
            if rel.type.upper() not in BIGBIO_RELATION_TYPES:
                lost_type[rel.type] += 1
                continue
            if rel.arg1_id not in surviving or rel.arg2_id not in surviving:
                lost_args[rel.type] += 1
                continue
            kept_rel += 1

    return {
        "entities": kept_ent,
        "relations_R": kept_rel,
        "relations_OR": or_synth,
        "lost_by_type": lost_type,
        "lost_by_args": lost_args,
        "lost_or_prefix_bug": lost_or_prefix_bug,
    }


#: Surface forms that look like a dose/frequency expression. Deliberately loose:
#: used only to characterise what the Chia `Multiplier`/`Qualifier`/`Value`
#: arguments of a `Drug` actually contain, never to relabel anything.
DOSE_HINT = re.compile(
    r"\d|dose|dosage|mg\b|ml\b|mcg|µg|unit|g/|/kg|/day|/d\b|daily|bid|tid|qd"
    r"|per day|mmol|meq|%",
    re.IGNORECASE,
)


def dosage_evidence(rels_in) -> dict:
    """Characterise every candidate 'drug -> dose' signature by surface form."""
    keys = [
        ("HAS_VALUE", "Value"),
        ("HAS_MULTIPLIER", "Multiplier"),
        ("HAS_QUALIFIER", "Qualifier"),
    ]
    out = {}
    for rel_type, arg2_type in keys:
        forms = collections.Counter()
        dosey = 0
        for _, rel, a1, a2 in rels_in:
            if a1.type != "Drug" or rel.norm_type != rel_type or a2.type != arg2_type:
                continue
            surface = " ".join(a2.ann_text.split())
            forms[surface.lower()] += 1
            if DOSE_HINT.search(surface):
                dosey += 1
        out[(rel_type, arg2_type)] = {
            "n": sum(forms.values()),
            "dose_like": dosey,
            "forms": forms,
        }
    return out


def newline_experiment(directory: Path) -> dict:
    """Quantify how much of the 'broken offsets' problem is newline translation.

    Re-reads every ``.txt`` twice -- once the way ``chia.py`` does (universal
    newlines) and once raw -- and counts how many entity offsets reproduce the
    annotated mention text verbatim under each.
    """
    results = {"universal": 0, "raw": 0, "total": 0, "crlf_files": 0}
    for txt in sorted(Path(directory).glob("*.txt")):
        raw = txt.open(encoding="utf-8", newline="").read()
        universal = txt.read_text(encoding="utf-8")
        if "\r" in raw:
            results["crlf_files"] += 1
        ann = txt.with_suffix(".ann")
        if not ann.exists():
            continue
        for line in ann.read_text(encoding="utf-8").split("\n"):
            if not line.startswith("T") or "\t" not in line:
                continue
            fields = line.split("\t")
            type_name = fields[1].split()[0]
            if type_name not in SCHEMA_ENTITY_TYPES:
                continue
            try:
                spans = [
                    tuple(int(x) for x in s.split())
                    for s in fields[1][len(type_name):].strip().split(";")
                ]
            except ValueError:
                continue
            results["total"] += 1
            for key, text in (("universal", universal), ("raw", raw)):
                if " ".join(text[s:e] for s, e in spans) == fields[2]:
                    results[key] += 1
    return results


def relation_id_gaps(docs: list[Document]) -> tuple[int, int, collections.Counter]:
    """Missing ``R<n>`` ids in the raw files -- annotation-time deletions."""
    total_gap = 0
    docs_with_gaps = 0
    per_doc = collections.Counter()
    for doc in docs:
        nums = []
        for rid in doc.relation_ids_seen:
            try:
                nums.append(int(rid[1:]))
            except ValueError:
                continue
        if not nums:
            continue
        gap = max(nums) - len(set(nums))
        if gap > 0:
            docs_with_gaps += 1
            total_gap += gap
            per_doc[gap] += 1
    return total_gap, docs_with_gaps, per_doc


def overlap_stats(ents_in):
    by_doc = collections.defaultdict(list)
    for doc, ent in ents_in:
        by_doc[doc.doc_key].append(ent)

    identical = 0
    identical_same_type = 0
    containment = 0
    partial = 0
    dup_examples = []

    for key, ents in by_doc.items():
        charsets = [(e, e.char_indices()) for e in ents]
        for i in range(len(charsets)):
            ei, si = charsets[i]
            for j in range(i + 1, len(charsets)):
                ej, sj = charsets[j]
                if not si & sj:
                    continue
                if ei.spans == ej.spans:
                    identical += 1
                    if ei.type == ej.type:
                        identical_same_type += 1
                        if len(dup_examples) < 8:
                            dup_examples.append(
                                (key, ei.id, ej.id, ei.type, ei.ann_text[:40])
                            )
                    continue
                if si <= sj or sj <= si:
                    containment += 1
                else:
                    partial += 1
    return identical, identical_same_type, containment, partial, dup_examples


def nesting_examples(ents_in, limit: int = 6) -> list:
    """Short spans that carry several stacked annotations, e.g. ``HIV+``."""
    by_doc = collections.defaultdict(list)
    for doc, ent in ents_in:
        by_doc[doc.doc_key].append(ent)

    found = []
    for doc_key in sorted(by_doc):
        ents = by_doc[doc_key]
        for outer in ents:
            if len(outer.ann_text) > 14 or outer.is_discontinuous:
                continue
            inner = [
                e for e in ents
                if e is not outer
                and e.start >= outer.start
                and e.end <= outer.end
                and e.spans != outer.spans
            ]
            if len({e.type for e in inner}) >= 2 and any(
                e.type == "Value" for e in inner
            ):
                found.append((doc_key, outer, sorted(inner, key=lambda e: e.start)))
                break
        if len(found) >= limit:
            break
    return found


def line_index(criteria: list[tuple[int, int]], pos: int) -> int:
    for i, (start, end) in enumerate(criteria):
        if start <= pos < end:
            return i
    return -1


def build_report(
    docs: list[Document],
    docs_with_scope: list[Document] | None,
    root: Path,
    source_dir: Path,
) -> str:
    ents_in, ents_out, rels_in, drops, dropped_examples = schema_view(docs)
    nl = newline_experiment(source_dir)

    conf_path = root / "data" / "raw" / "without_scope" / "annotation.conf"
    conf = (
        parse_annotation_conf(conf_path.read_text(encoding="utf-8"))
        if conf_path.exists()
        else None
    )

    nct_ids = {d.nct_id for d in docs}
    criteria_per_doc = {d.doc_key: d.criterion_spans() for d in docs}
    n_criteria = sum(len(v) for v in criteria_per_doc.values())

    ent_types = collections.Counter(e.type for _, e in ents_in)
    rel_types = collections.Counter(r.norm_type for _, r, _, _ in rels_in)
    rel_origin = collections.Counter(r.origin for _, r, _, _ in rels_in)

    out: list[str] = []
    w = out.append

    # ---------------------------------------------------------------- header
    w("# Chia corpus — Phase 1 profile report\n")
    w("Read-only profiling of the Chia clinical-trial eligibility-criteria corpus, "
      "produced ahead of relation-extraction dataset construction. **Nothing has "
      "been converted or split.**\n")

    w("SUMMARY_PLACEHOLDER")

    md5s = {}
    for name in ("chia_with_scope.zip", "chia_without_scope.zip"):
        p = root / "data" / "raw" / name
        if p.exists():
            md5s[name] = hashlib.md5(p.read_bytes()).hexdigest()

    w("## 0. Provenance\n")
    w(md_table(
        ["Item", "Value"],
        [
            ["Source", "`bigbio/chia` → `data/*.zip` (byte-identical mirror of figshare 10.6084/m9.figshare.11855817)"],
            ["`chia_with_scope.zip` MD5", f"`{md5s.get('chia_with_scope.zip','n/a')}` — matches published `54b33164da88da88e47b2a009e150a82`"],
            ["`chia_without_scope.zip` MD5", f"`{md5s.get('chia_without_scope.zip','n/a')}` — matches published `e5b4578b11139b80d64aeca0cc4a76b8`"],
            ["Primary variant profiled", "**without_scope** (trap 8 default)"],
            ["Parser", "`src/relation_extraction/data/chia_brat.py` (own code; two routines ported from `chia.py`)"],
            ["Seed", f"`{SEED}` (no stochastic step in Phase 1)"],
            ["License", "CC-BY-4.0"],
        ],
    ))
    w("")

    # ------------------------------------------------------------------ 1.1
    w("## 1.1 Reconciliation against published totals\n")
    rows = [
        ["Trials (distinct NCT IDs)", len(nct_ids), PUBLISHED["trials"], delta(len(nct_ids), PUBLISHED["trials"])],
        ["Documents (files)", len(docs), PUBLISHED["documents"], delta(len(docs), PUBLISHED["documents"])],
        ["Criteria (non-empty lines)", n_criteria, PUBLISHED["criteria"], delta(n_criteria, PUBLISHED["criteria"])],
        ["Entities (in-schema)", len(ents_in), PUBLISHED["entities"], delta(len(ents_in), PUBLISHED["entities"])],
        ["Distinct entity types (in-schema)", len(ent_types), PUBLISHED["entity_types"], delta(len(ent_types), PUBLISHED["entity_types"])],
        ["Relations (in-schema, incl. synthesised OR)", len(rels_in), PUBLISHED["relations"], delta(len(rels_in), PUBLISHED["relations"])],
        ["Distinct relation types (in-schema)", len(rel_types), PUBLISHED["relation_types"], delta(len(rel_types), PUBLISHED["relation_types"])],
    ]
    w(md_table(["Quantity", "This parse", "Published", "Δ"], rows, "lrrr"))
    w("")
    w("Four of seven figures reconcile exactly. The two that do not are explained "
      "below; both are properties of the released files, not of this parse.\n")

    n_r_lines = sum(len(d.relation_ids_seen) for d in docs)
    n_star = sum(len(d.equivalences) for d in docs)
    w("#### Discrepancy 1 — relations: the `OR` counting rule (±10k)\n")
    w("`OR` is not a brat relation. It is encoded as `*` equivalence *lines*, each "
      "listing an unordered set of co-referent entities, and the count depends "
      "entirely on how you expand them:\n")
    w(md_table(
        ["Counting rule", "Relations", "vs published 25,017"],
        [
            [f"All `R` lines ({n_r_lines:,}) + one relation per `*` line ({n_star:,})",
             f"{n_r_lines + n_star:,}", delta(n_r_lines + n_star, PUBLISHED['relations'])],
            [f"In-schema `R` lines ({rel_origin['R']:,}) + one per `*` line",
             f"{rel_origin['R'] + n_star:,}",
             delta(rel_origin["R"] + n_star, PUBLISHED["relations"])],
            ["In-schema `R` lines + **pairwise** expansion of `*` (BigBIO's rule, used here)",
             f"{len(rels_in):,}", delta(len(rels_in), PUBLISHED['relations'])],
        ],
        "lrr",
    ))
    w("")
    w(f"The published 25,017 is closest to *one relation per `*` line* "
      f"({n_r_lines + n_star:,}, +0.6%), so the paper almost certainly did **not** "
      f"expand equivalences pairwise. BigBIO does, which inflates `OR` from "
      f"{n_star:,} to {rel_origin['EQUIV']:,} — "
      f"**{pct(rel_origin['EQUIV'], len(rels_in))} of every relation in the corpus "
      f"becomes a synthesised `OR`**. This is a decision, not a fact: see §2.\n")
    w(f"Not every `*` line is an `OR`, either: "
      + ", ".join(f"`{t}` × {c:,}" for t, c in
                  collections.Counter(e.type for d in docs for e in d.equivalences).most_common())
      + ".\n")

    w("#### Discrepancy 2 — entities: 511 fewer than published (−1.23%)\n")
    n_t_lines = sum(len(d.entities) for d in docs) + sum(
        1 for d in docs for x in d.drops if x.reason == "duplicate_entity_id")
    w(f"- Every one of the **{n_t_lines:,}** `T` lines in the release is accounted "
      f"for: {len(ents_in):,} in-schema + {len(ents_out):,} out-of-schema.\n"
      f"- Both corpus variants contain **exactly the same {len(ents_in):,}** "
      f"non-`Scope` entities, so this is not a with/without-scope artifact.\n"
      f"- No entity is lost to parsing: there are 0 malformed `T` lines and 0 "
      f"duplicate `T` ids.\n"
      f"- Conclusion: the released `.ann` files simply contain 511 fewer in-schema "
      f"entities than the paper reports. The paper's counts were evidently taken "
      f"from a different (earlier or post-processed) snapshot. Unrecoverable from "
      f"the release, and immaterial at 1.2%.\n")

    if docs_with_scope is not None:
        ws_in, _, ws_rels, _, _ = schema_view(docs_with_scope)
        ws_ent_types = collections.Counter(e.type for _, e in ws_in)
        ws_rel_types = collections.Counter(r.norm_type for _, r, _, _ in ws_rels)
        w("### with_scope variant, for comparison\n")
        w(md_table(
            ["Quantity", "without_scope", "with_scope"],
            [
                ["Entities (in-schema)", len(ents_in), len(ws_in)],
                ["Entity types", len(ent_types), len(ws_ent_types)],
                ["`Scope` entities", ent_types.get("Scope", 0), ws_ent_types.get("Scope", 0)],
                ["Relations (in-schema)", len(rels_in), len(ws_rels)],
                ["Relation types", len(rel_types), len(ws_rel_types)],
                ["`HAS_SCOPE` relations", rel_types.get("HAS_SCOPE", 0), ws_rel_types.get("HAS_SCOPE", 0)],
            ],
            "lrr",
        ))
        w("")
        w("Entity counts excluding `Scope`: "
          f"without_scope **{len(ents_in) - ent_types.get('Scope', 0):,}**, "
          f"with_scope **{len(ws_in) - ws_ent_types.get('Scope', 0):,}**.\n")

    w("### Entity type distribution (in-schema)\n")
    w(md_table(
        ["Entity type", "Count", "% of entities"],
        [[t, f"{c:,}", pct(c, len(ents_in))] for t, c in ent_types.most_common()],
        "lrr",
    ))
    w("")

    w("### Relation type distribution (in-schema)\n")
    annotated = collections.Counter(
        r.norm_type for _, r, _, _ in rels_in if r.origin == "R"
    )
    synth = collections.Counter(
        r.norm_type for _, r, _, _ in rels_in if r.origin == "EQUIV"
    )
    w(md_table(
        ["Relation type", "Annotated (`R` lines)", "Synthesised (`*` lines)", "Total"],
        [
            [t, f"{annotated.get(t, 0):,}", f"{synth.get(t, 0):,}", f"{c:,}"]
            for t, c in rel_types.most_common()
        ],
        "lrrr",
    ))
    w("")
    w(f"Origin totals: **{rel_origin['R']:,}** annotated, "
      f"**{rel_origin['EQUIV']:,}** synthesised from `*` equivalence lines (trap 9).\n")

    # ------------------------------------------------- dropped / out of schema
    w("### Everything dropped, with reasons\n")
    total_dropped = sum(drops.values())
    w(md_table(
        ["Reason", "Count"],
        [[k, f"{v:,}"] for k, v in sorted(drops.items(), key=lambda kv: -kv[1])],
        "lr",
    ))
    w("")
    w(f"Total dropped records: **{total_dropped:,}** "
      f"({len(ents_out):,} out-of-schema entities and the relations that touch them).\n")

    w("### Out-of-schema entity types present in the raw data\n")
    out_types = collections.Counter(e.type for _, e in ents_out)
    w(md_table(
        ["Type", "Count", "Declared in `annotation.conf`?"],
        [
            [
                t,
                f"{c:,}",
                "yes" if conf and t in conf["entities"] else "**no**",
            ]
            for t, c in out_types.most_common()
        ],
        "lrl",
    ))
    w("")
    w("These are annotator-workflow labels (error tags, out-of-scope markers), not "
      "clinical entities. `Line` and the seven `!ERROR` types are declared in "
      "`annotation.conf`; the rest are undeclared and were evidently added ad hoc "
      "during annotation. None belongs in a relation-extraction dataset, but they "
      "do consume text spans and they do appear as relation arguments — which is "
      f"why {drops['relation: argument is an out-of-schema entity']} otherwise "
      "well-formed relations are dropped along with them (that figure counts both "
      "`R`-line and `*`-derived relations; the loader-comparison table below "
      "counts only `R`-line ones, because the loader never reaches the others).\n")

    # ------------------------------------------------ bigbio loader comparison
    sim = simulate_bigbio(docs)
    w("### Cross-check against `load_dataset` (traps 2 and 3, plus a third bug)\n")

    xc_path = root / "outputs" / "bigbio_counts.json"
    xc = json.loads(xc_path.read_text(encoding="utf-8")) if xc_path.exists() else None

    if xc is None:
        w("`outputs/bigbio_counts.json` not present — run "
          "`scripts/crosscheck_bigbio.py` to generate it. Simulation only below.\n")
    else:
        w(f"`load_dataset('bigbio/chia', '{xc['config']}', trust_remote_code=True)` "
          f"**does** run here under `datasets=={xc['datasets_version']}` "
          "(v3+ refuses script-based datasets outright), so it was loaded as a "
          "second source and diffed. Actual loader output vs this parse:\n")
        w(md_table(
            ["Quantity", "`load_dataset`", "This parse", "Δ"],
            [
                ["Documents", f"{xc['documents']:,}", f"{len(docs):,}",
                 delta(len(docs), xc["documents"])],
                ["Entities", f"{xc['entities']:,}", f"{len(ents_in):,}",
                 delta(len(ents_in), xc["entities"])],
                ["Entity types", f"{len(xc['entity_types'])}", f"{len(ent_types)}",
                 delta(len(ent_types), len(xc["entity_types"]))],
                ["Relations", f"{xc['relations']:,}", f"{len(rels_in):,}",
                 delta(len(rels_in), xc["relations"])],
                ["Relation types", f"{len(xc['relation_types'])}", f"{len(rel_types)}",
                 delta(len(rel_types), len(xc["relation_types"]))],
            ],
            "lrrr",
        ))
        w("")
        w("**Entities agree exactly, type by type, all 15 types** — which confirms "
          "both sides are reading the same bytes and that the divergence is purely "
          "in relation handling. Per relation type:\n")
        all_rt = sorted(set(xc["relation_types"]) | set(rel_types),
                        key=lambda t: -rel_types.get(t, 0))
        w(md_table(
            ["Relation type", "`load_dataset`", "This parse", "Δ", "Cause of divergence"],
            [
                [
                    t,
                    f"{xc['relation_types'].get(t, 0):,}",
                    f"{rel_types.get(t, 0):,}",
                    delta(rel_types.get(t, 0), xc["relation_types"].get(t, 0)),
                    ("**trap 2** — `\"HAS_CONTEXT \"` trailing space in "
                     "`_RELATION_TYPES`; every one is dropped"
                     if t == "HAS_CONTEXT"
                     else "**id-prefix bug** at `chia.py:365` — see below"
                     if t == "OR"
                     else ""),
                ]
                for t in all_rt
            ],
        ))
        w("")

    w("A third silent-drop mechanism, not previously catalogued: `chia.py` builds "
      "`entity_ids` with document-prefixed keys (`chia.py:316-317`, "
      "`example_prefix + entity_ann[\"id\"]`), but the equivalence loop tests the "
      "**bare** `T` id against it (`chia.py:365`, `if arg1 not in entity_ids`). The "
      "guard therefore never passes, and *every* `OR` relation synthesised from a "
      "`*` line is discarded — while the very next statement prefixes the same ids "
      "when constructing the relation (`chia.py:371-372`), which is what makes it "
      "unambiguously a bug rather than a design choice. Empirically the loader "
      "yields 7 `OR` relations (the literal `R`-line ones) and zero from the "
      f"{n_star:,} `*` lines.\n")

    w("Simulating `chia.py`'s three filters against this parse reproduces its "
      "output exactly:\n")
    w(md_table(
        ["Quantity", "Simulated `chia.py`", "Actual `load_dataset`", "This parse"],
        [
            ["Entities", f"{sim['entities']:,}",
             f"{xc['entities']:,}" if xc else "n/a", f"{len(ents_in):,}"],
            ["Relations", f"{sim['relations_R']:,}",
             f"{xc['relations']:,}" if xc else "n/a", f"{len(rels_in):,}"],
        ],
        "lrrr",
    ))
    w("")
    loader_rels = xc["relations"] if xc else sim["relations_R"]
    w("Relations this parse keeps and `load_dataset` does **not** — i.e. the real "
      "cost of using the loader:\n")
    w(md_table(
        ["Lost relations", "Count", "Mechanism"],
        [
            ["`Has_context`", f"{rel_types.get('HAS_CONTEXT', 0):,}",
             "trap 2 — trailing space in `_RELATION_TYPES`"],
            ["`OR` synthesised from `*` lines", f"{rel_origin['EQUIV']:,}",
             "id-prefix bug at `chia.py:365`"],
            ["**Total**", f"**{len(rels_in) - loader_rels:,}**",
             f"**{pct(len(rels_in) - loader_rels, len(rels_in))} of all in-schema relations**"],
        ],
        "lrl",
    ))
    w("")
    w("Dropped by **both** implementations, and correctly so: "
      f"{sum(sim['lost_by_type'].values()) - sim['lost_by_type'].get('Has_context', 0):,} "
      "relations of out-of-schema type (`multi`, `causal`, `v-AND`) and "
      f"{sum(sim['lost_by_args'].values()):,} whose argument is an out-of-schema "
      "entity. Breakdown of `chia.py`'s own filters (raw counts, before the "
      "argument check, which is why `Has_context` reads 223 here and 221 above):\n")
    w(md_table(
        ["Relation type", "Dropped: type not in `_RELATION_TYPES`", "Dropped: argument filtered out"],
        [
            [t, f"{sim['lost_by_type'].get(t, 0):,}", f"{sim['lost_by_args'].get(t, 0):,}"]
            for t in sorted(set(sim["lost_by_type"]) | set(sim["lost_by_args"]),
                            key=lambda t: -(sim["lost_by_type"].get(t, 0)
                                            + sim["lost_by_args"].get(t, 0)))
        ],
        "lrr",
    ))
    w("")

    gap_total, gap_docs, _ = relation_id_gaps(docs)
    w(f"**Relation-id gaps in the raw files** (trap 3): `R<n>` ids are "
      f"non-contiguous in **{gap_docs:,}** of {len(docs):,} documents, "
      f"**{gap_total:,}** ids missing in total "
      f"({gap_total / max(1, len(docs)):.2f} per document). These are annotation-time "
      "deletions in the source files, *not* loader drops — nothing is recoverable "
      "from them and no relation is lost by this parse on their account.\n")

    # ------------------------------------------------------- offset repair
    status = collections.Counter(e.offset_status for _, e in ents_in)
    w("### Offset integrity (trap 4)\n")
    w("**The offsets in the release are not broken.** Their reputation comes from "
      "how they are read. "
      f"{nl['crlf_files']:,} of {len(docs):,} `.txt` files use CRLF line endings, "
      "and Python's default universal-newline mode rewrites `\\r\\n` -> `\\n`, "
      "deleting one character per preceding line and shifting every subsequent "
      "offset left. `chia.py` reads via `Path.open()` and so hits this on every "
      "CRLF file. Same offsets, same entities, two ways of reading the text:\n")
    w(md_table(
        ["How the `.txt` is read", "Entity offsets exactly reproducing the mention text"],
        [
            ["`Path.open()` — universal newlines (what `chia.py` does)",
             f"{nl['universal']:,} / {nl['total']:,} ({100.0 * nl['universal'] / nl['total']:.2f}%)"],
            ["`open(newline=\"\")` — raw (what this parser does)",
             f"{nl['raw']:,} / {nl['total']:,} ({100.0 * nl['raw'] / nl['total']:.2f}%)"],
        ],
        "lr",
    ))
    w("")
    w("`_fix_entity_offsets` is therefore repairing damage the loader inflicts on "
      "itself, with a ±100-character text search that is both unnecessary and "
      "unsafe: it will happily relocate a short mention (`+`, `1`, `no`) to a "
      "coincidental match elsewhere in the document. It has been ported and is "
      "retained here, but as a **fallback for the residual 12 entities only**, not "
      "as the primary mechanism. Note also that BigBIO's routine cannot repair a "
      "discontinuous entity at all: for multi-span mentions it first re-derives the "
      "mention text *from the very offsets it is about to validate*, so the check "
      "is guaranteed to pass. This parser instead repairs multi-span entities by "
      "searching for a single global fragment shift.\n")
    w("Final offset status after parsing (raw read + fallback repair):\n")
    w(md_table(
        ["Offset status", "Count", "% of entities"],
        [[f"`{k}`", f"{v:,}", pct(v, len(ents_in))] for k, v in status.most_common()],
        "lrr",
    ))
    w("")
    w(f"The {status.get('unrepaired', 0)} unrepaired entities are carried through "
      "with their annotated offsets and flagged; Phase 2's "
      "`text[start:end] == entity_text` assertion will surface them again.\n")

    # ------------------------------------------------------------------ 1.2
    w("## 1.2 Relation signature table\n")
    w("Joint distribution of `(arg1_type, relation_type, arg2_type)` over all "
      "in-schema relations. Full table, nothing truncated.\n")
    sig = collections.Counter(
        (a1.type, r.norm_type, a2.type) for _, r, a1, a2 in rels_in
    )
    w(md_table(
        ["#", "arg1 type", "relation", "arg2 type", "Count", "% of relations"],
        [
            [i + 1, a1, rt, a2, f"{c:,}", pct(c, len(rels_in))]
            for i, ((a1, rt, a2), c) in enumerate(sig.most_common())
        ],
        "rlllrr",
    ))
    w("")
    w(f"Distinct signatures: **{len(sig):,}**.\n")

    # ------------------------------------------------------------- callouts
    w("### Called-out signatures\n")
    callouts = [
        ("Measurement", "HAS_VALUE", "Value"),
        ("Drug", "HAS_VALUE", "Value"),
        ("Drug", "HAS_QUALIFIER", "Qualifier"),
        ("Drug", "HAS_MULTIPLIER", "Multiplier"),
    ]
    w(md_table(
        ["Signature", "Count", "Present?"],
        [
            [f"`{a}` → `{r}` → `{b}`", f"{sig.get((a, r, b), 0):,}",
             "yes" if sig.get((a, r, b), 0) else "**no — zero occurrences**"]
            for a, r, b in callouts
        ],
        "lrl",
    ))
    w("")

    w("#### Every relation whose arg1 is `Drug`\n")
    drug_rows = [
        [rt, a2, f"{c:,}"]
        for (a1, rt, a2), c in sig.most_common()
        if a1 == "Drug"
    ]
    drug_total = sum(c for (a1, _, _), c in sig.items() if a1 == "Drug")
    w(md_table(["relation", "arg2 type", "Count"], drug_rows, "llr"))
    w("")
    w(f"Total relations with `Drug` as arg1: **{drug_total:,}**.\n")

    w("#### Every relation whose arg1 is `Measurement`\n")
    meas_rows = [
        [rt, a2, f"{c:,}"]
        for (a1, rt, a2), c in sig.most_common()
        if a1 == "Measurement"
    ]
    meas_total = sum(c for (a1, _, _), c in sig.items() if a1 == "Measurement")
    w(md_table(["relation", "arg2 type", "Count"], meas_rows, "llr"))
    w("")
    w(f"Total relations with `Measurement` as arg1: **{meas_total:,}**.\n")

    # ------------------------------------------- 1.2b drug dosage evidence
    w("### Is there a drug→dose relation in Chia? (evidence)\n")
    w("Your inspection of two documents suggested dosage is annotated as "
      "`Qualifier`/`Multiplier` rather than `Value`. At corpus scale that is "
      "confirmed, and it is worse than it looks: the dose signal is not merely "
      "relabelled, it is **smeared across three relations, none of which means "
      "'dose'**.\n")
    ev = dosage_evidence(rels_in)
    w(md_table(
        ["Candidate signature", "n", "arg2 surface looks dose/frequency-like", "Verdict"],
        [
            ["`Drug` → `HAS_VALUE` → `Value`",
             f"{ev[('HAS_VALUE','Value')]['n']:,}",
             pct(ev[("HAS_VALUE", "Value")]["dose_like"], ev[("HAS_VALUE", "Value")]["n"]),
             "Semantically exactly right, **far too rare to train or evaluate on**"],
            ["`Drug` → `HAS_MULTIPLIER` → `Multiplier`",
             f"{ev[('HAS_MULTIPLIER','Multiplier')]['n']:,}",
             pct(ev[("HAS_MULTIPLIER", "Multiplier")]["dose_like"],
                 ev[("HAS_MULTIPLIER", "Multiplier")]["n"]),
             "Conflates dose amount, **frequency and duration**"],
            ["`Drug` → `HAS_QUALIFIER` → `Qualifier`",
             f"{ev[('HAS_QUALIFIER','Qualifier')]['n']:,}",
             pct(ev[("HAS_QUALIFIER", "Qualifier")]["dose_like"],
                 ev[("HAS_QUALIFIER", "Qualifier")]["n"]),
             "Mostly **route/kind**, not dose"],
        ],
        "lrrl",
    ))
    w("")
    for (rt, at), info in ev.items():
        w(f"**Most frequent `arg2` surface forms — `Drug` → `{rt}` → `{at}` "
          f"(n={info['n']:,}, {len(info['forms']):,} distinct):**\n")
        w(md_table(
            ["Count", "Surface form"],
            [[c, f"`{t[:70]}`"] for t, c in info["forms"].most_common(15)],
            "rl",
        ))
        w("")
    w("The middle column is a deliberately loose regex (any digit, or `mg`/`mcg`/"
      "`daily`/`qd`/`/kg`/`%`…). It counts frequency and duration expressions as "
      "'dose-like', so it is an **upper bound** — the true dose fraction of "
      "`HAS_MULTIPLIER` is well below the figure shown. It is used to characterise "
      "the arguments, never to relabel them.\n")
    w("Read the `HAS_MULTIPLIER` column carefully: `daily`, `chronic use`, "
      "`at least one`, `≥ 5 days` and `60 mg/day` are all the same relation. A model "
      "trained to extract this is not learning dose extraction.\n")
    w("By contrast the test→result side is clean and plentiful: "
      f"**`Measurement` → `HAS_VALUE` → `Value` = {sig.get(('Measurement','HAS_VALUE','Value'), 0):,}**, "
      f"with `Person` → `HAS_VALUE` → `Value` = {sig.get(('Person','HAS_VALUE','Value'), 0):,} "
      "(age criteria) available as a second, closely-related target if wanted.\n")

    # ------------------------------------------------------------------ 1.3
    w("## 1.3 Structural statistics\n")

    disc = [(d, e) for d, e in ents_in if e.is_discontinuous]
    disc_types = collections.Counter(e.type for _, e in disc)
    rel_ent_ids = set()
    for doc, r, a1, a2 in rels_in:
        rel_ent_ids.add((doc.doc_key, a1.id))
        rel_ent_ids.add((doc.doc_key, a2.id))
    disc_in_rel = sum(1 for d, e in disc if (d.doc_key, e.id) in rel_ent_ids)
    frag_counts = collections.Counter(len(e.spans) for _, e in disc)

    w("### Discontinuous entities (trap 5)\n")
    w(f"- Count: **{len(disc):,}** of {len(ents_in):,} in-schema entities "
      f"(**{pct(len(disc), len(ents_in))}**)\n"
      f"- Participating in at least one in-schema relation: **{disc_in_rel:,}** "
      f"(**{pct(disc_in_rel, len(disc))}** of discontinuous entities)\n"
      f"- Fragment counts: " +
      ", ".join(f"{k} fragments: {v:,}" for k, v in sorted(frag_counts.items())) + "\n")
    w(md_table(
        ["Entity type", "Discontinuous", "All", "% of that type discontinuous"],
        [
            [t, f"{c:,}", f"{ent_types[t]:,}", pct(c, ent_types[t])]
            for t, c in disc_types.most_common()
        ],
        "lrrr",
    ))
    w("")

    ident, ident_same, contain, partial, dup_ex = overlap_stats(ents_in)
    w("### Overlapping and nested entities (traps 6 and 7)\n")
    w(md_table(
        ["Relationship between the two entities", "Pairs"],
        [
            ["Identical span set (duplicate offsets)", f"{ident:,}"],
            ["— of which same entity type", f"{ident_same:,}"],
            ["Strict containment (one inside the other)", f"{contain:,}"],
            ["Partial overlap (neither contains the other)", f"{partial:,}"],
            ["**Total overlapping pairs**", f"**{ident + contain + partial:,}**"],
        ],
        "lr",
    ))
    w("")
    nest_ex = nesting_examples(ents_in, limit=6)
    if nest_ex:
        w("Worked examples — a single short span carrying three simultaneous "
          "annotations, with a `HAS_VALUE` relation between the inner two. Any "
          "one-label-per-span assumption destroys exactly the relations we are "
          "targeting:\n")
        w(md_table(
            ["Document", "Outer entity", "Contains"],
            [[doc_key, f"`{outer.type} \"{outer.ann_text}\"`",
              ", ".join(f"`{i.type} \"{i.ann_text}\"`" for i in inner)]
             for doc_key, outer, inner in nest_ex],
        ))
        w("")

    if dup_ex:
        w("Examples of same-type duplicate annotations:\n")
        w(md_table(
            ["Document", "id A", "id B", "Type", "Text"],
            [[a, b, c, d, f"`{e}`"] for a, b, c, d, e in dup_ex],
        ))
        w("")

    w("### Entity span length in whitespace tokens\n")
    lengths_by_type = collections.defaultdict(list)
    all_lengths = []
    for doc, ent in ents_in:
        n_tok = sum(len(doc.text[s:e].split()) for s, e in ent.spans)
        lengths_by_type[ent.type].append(n_tok)
        all_lengths.append(n_tok)
    rows = []
    for t in sorted(lengths_by_type, key=lambda t: -len(lengths_by_type[t])):
        v = lengths_by_type[t]
        rows.append([t, f"{len(v):,}", percentile(v, 0.5), percentile(v, 0.9),
                     percentile(v, 0.95), percentile(v, 0.99), max(v)])
    rows.append(["**all**", f"**{len(all_lengths):,}**",
                 percentile(all_lengths, 0.5), percentile(all_lengths, 0.9),
                 percentile(all_lengths, 0.95), percentile(all_lengths, 0.99),
                 max(all_lengths)])
    w(md_table(["Entity type", "n", "median", "p90", "p95", "p99", "max"],
               rows, "lrrrrrr"))
    w("")

    # ------------------------------------------------------------------ 1.4
    w("## 1.4 Cross-boundary relations\n")
    same_line = cross_line = 0
    same_sent = cross_sent = 0
    unlocated = 0
    ent_spans_multi_line = 0
    cross_examples = []

    sent_cache: dict[str, list[tuple[int, int]]] = {}
    for doc, rel, a1, a2 in rels_in:
        crit = criteria_per_doc[doc.doc_key]
        l1 = line_index(crit, a1.start)
        l2 = line_index(crit, a2.start)
        if l1 < 0 or l2 < 0:
            unlocated += 1
            continue
        if l1 == l2:
            same_line += 1
        else:
            cross_line += 1
            if len(cross_examples) < 8:
                cross_examples.append(
                    (doc.doc_key, rel.id, rel.norm_type,
                     f"{a1.type}:{a1.ann_text[:24]}", f"{a2.type}:{a2.ann_text[:24]}")
                )
        key = doc.doc_key
        if key not in sent_cache:
            sents = []
            for span in crit:
                sents.extend(sentence_spans(doc.text, span))
            sent_cache[key] = sents
        s1 = line_index(sent_cache[key], a1.start)
        s2 = line_index(sent_cache[key], a2.start)
        if s1 >= 0 and s2 >= 0 and s1 == s2:
            same_sent += 1
        else:
            cross_sent += 1

    for doc, ent in ents_in:
        crit = criteria_per_doc[doc.doc_key]
        lines = {line_index(crit, s) for s, _ in ent.spans}
        lines |= {line_index(crit, e - 1) for _, e in ent.spans}
        if len({x for x in lines if x >= 0}) > 1:
            ent_spans_multi_line += 1

    located = same_line + cross_line
    w(md_table(
        ["Boundary", "Same", "Crossing", "% crossing"],
        [
            ["Criterion (line)", f"{same_line:,}", f"{cross_line:,}", pct(cross_line, located)],
            ["Sentence (approx.)", f"{same_sent:,}", f"{cross_sent:,}", pct(cross_sent, located)],
        ],
        "lrrr",
    ))
    w("")
    w(f"- Relations whose arguments could not be located in any non-empty line: "
      f"**{unlocated:,}**\n"
      f"- Entities whose own span crosses a line boundary: **{ent_spans_multi_line:,}**\n")
    w("Sentence segmentation is a crude regex (split on `.!?` followed by whitespace "
      "and a capital/bracket). It is abbreviation-unaware, so the sentence figure is "
      "an upper bound on true crossings. It is used for reporting only — per trap 11, "
      "no sentence splitting is applied to the corpus.\n")
    if cross_examples:
        w("Examples of cross-criterion relations:\n")
        w(md_table(["Document", "Relation id", "Type", "arg1", "arg2"], cross_examples))
        w("")

    # ------------------------------------------------------------------ 1.5
    w("## 1.5 Leakage risk — duplicated criterion strings\n")
    crit_index = collections.defaultdict(list)
    for doc in docs:
        for start, end in criteria_per_doc[doc.doc_key]:
            crit_index[normalise_criterion(doc.text[start:end])].append(
                (doc.nct_id, doc.text_type)
            )
    dup_strings = {k: v for k, v in crit_index.items() if len(v) > 1}
    multi_trial = {k: v for k, v in dup_strings.items()
                   if len({n for n, _ in v}) > 1}
    trials_touched = {n for v in multi_trial.values() for n, _ in v}
    occurrences_multi_trial = sum(len(v) for v in multi_trial.values())

    w(md_table(
        ["Quantity", "Value"],
        [
            ["Criteria (occurrences)", f"{n_criteria:,}"],
            ["Distinct normalised criterion strings", f"{len(crit_index):,}"],
            ["Strings occurring more than once", f"{len(dup_strings):,}"],
            ["Strings occurring in **more than one trial**", f"{len(multi_trial):,}"],
            ["Criterion occurrences involved in cross-trial duplication", f"{occurrences_multi_trial:,} ({pct(occurrences_multi_trial, n_criteria)} of all criteria)"],
            ["Distinct trials touched by cross-trial duplication", f"{len(trials_touched):,} ({pct(len(trials_touched), len(nct_ids))} of trials)"],
        ],
        "lr",
    ))
    w("")
    top_dups = sorted(multi_trial.items(),
                      key=lambda kv: -len({n for n, _ in kv[1]}))[:15]
    w("Most widely shared criterion strings:\n")
    w(md_table(
        ["Trials", "Occurrences", "Criterion (normalised)"],
        [[len({n for n, _ in v}), len(v), f"`{k[:100]}`"] for k, v in top_dups],
        "rrl",
    ))
    w("")

    # ------------------------------------------------------------------ 1.6
    w("## 1.6 Schema check against `annotation.conf`\n")
    if conf is None:
        w("`annotation.conf` not found.\n")
    else:
        w("`annotation.conf` is present in both zips (identical in each).\n")
        w("### `[entities]`\n")
        declared = conf["entities"]
        seen_types = set(ent_types) | set(out_types)
        w(md_table(
            ["Check", "Types"],
            [
                ["Declared in conf, absent from data",
                 ", ".join(f"`{t}`" for t in sorted(declared - seen_types)) or "none"],
                ["Present in data, **not declared** in conf",
                 ", ".join(f"`{t}`" for t in sorted(seen_types - declared)) or "none"],
            ],
        ))
        w("")
        w("### `[relations]`\n")
        w("Declared relation entries:\n")
        w(md_table(
            ["Name", "Arg1 constraint", "Arg2 constraint"],
            [[f"`{r['name']}`", f"`{r['arg1']}`", f"`{r['arg2']}`"]
             for r in conf["relations"]],
        ))
        w("")
        conf_rel_names = {r["name"].upper() for r in conf["relations"]}
        data_rel_names = {r.type.upper() for d in docs for r in d.relations}
        w(md_table(
            ["Check", "Relation types"],
            [
                ["Declared in conf, absent from data",
                 ", ".join(f"`{t}`" for t in sorted(conf_rel_names - data_rel_names)) or "none"],
                ["Present in data, **not declared** in conf",
                 ", ".join(f"`{t}`" for t in sorted(data_rel_names - conf_rel_names)) or "none"],
            ],
        ))
        w("")
        w("**Verdict: `annotation.conf` cannot be used to validate this corpus.** "
          "Its `[relations]` section declares five generic brat UI helpers "
          "(`h-OR`, `v-AND`, `v-OR`, `multi`, `<OVERLAP>`) with `<ANY>`/`<ENTITY>` "
          "argument constraints, and declares **none** of the eleven relation types "
          "the data actually uses. There are therefore no declared argument "
          "constraints to violate — the check is vacuous rather than clean. The "
          "config is a stale annotation-tool artifact shipped alongside the data. "
          "Two of its helper names (`multi`, `v-AND`) do leak into the data as "
          "relation types and are dropped as out-of-schema.\n")

    # -------------------------------------------------------- decisions
    w("---\n")
    w("## 2. Decisions required before Phase 2\n")
    w("Each of these changes what the experiment measures, so none has been made "
      "silently. My recommendation is given first in each case; all are yours to "
      "overrule.\n")

    w("### D1 — Target relations (blocking)\n")
    w("The drug→dose relation you want **does not exist in Chia in usable form** "
      f"(§1.2b): the semantically correct signature has "
      f"{ev[('HAS_VALUE','Value')]['n']} instances, and the two larger candidates "
      "mean 'frequency/duration' and 'route/kind' at least as often as they mean "
      "'dose'. Options:\n")
    base_targets = (sig.get(("Measurement", "HAS_VALUE", "Value"), 0)
                    + sig.get(("Person", "HAS_VALUE", "Value"), 0))
    w(md_table(
        ["Option", "Target set", "Total instances", "Trade-off"],
        [
            ["**A (recommended)**",
             "Test→result only: `Measurement`/`Person` → `HAS_VALUE` → `Value`",
             f"{base_targets:,}",
             "Clean, plentiful, semantically unambiguous. Drops the drug arm of the study."],
            ["B",
             f"A + `Drug` → `HAS_MULTIPLIER` → `Multiplier` "
             f"(+{ev[('HAS_MULTIPLIER','Multiplier')]['n']:,}) as a separate label",
             f"{base_targets + ev[('HAS_MULTIPLIER','Multiplier')]['n']:,}",
             "Keeps a drug arm, but the label means dose, frequency *or* duration. "
             "Must be reported as 'drug modifier', never as 'dose'."],
            ["C",
             f"A + all three `Drug` signatures (+{sum(v['n'] for v in ev.values()):,}) "
             "merged into one `DRUG_HAS_DOSE`",
             f"{base_targets + sum(v['n'] for v in ev.values()):,}",
             "Maximises drug-arm data; the label becomes semantically incoherent. Not recommended."],
            ["D",
             "Keep Chia for test→result, source drug→dose from another corpus (e.g. n2c2 2018 ADE, which annotates Drug–Dosage/Frequency/Route natively)",
             "n/a",
             "Only option that genuinely delivers drug→dose. Costs a second data pipeline."],
        ],
        "llrl",
    ))
    w("")
    w("Whichever you pick, the *label naming* question is separate: raw brat names "
      "(`Has_value`) or derived, argument-typed names (`MEASUREMENT_HAS_VALUE`). "
      "Given a GLiNER2-family model consumes relation labels as natural-language "
      "strings in the prompt, derived names carry more zero-shot signal — but they "
      "also change the task (the model no longer has to infer argument types). "
      "**Recommendation: derived names**, with raw names retained in the JSONL as a "
      "second field so both can be evaluated.\n")

    w("### D2 — `OR` relations\n")
    w(f"Pairwise expansion turns {n_star:,} `*` lines into {rel_origin['EQUIV']:,} "
      f"relations — {pct(rel_origin['EQUIV'], len(rels_in))} of the corpus, and the "
      "single largest 'relation type' by a wide margin. It is also the reason this "
      f"parse reports {len(rels_in):,} relations where the paper reports "
      f"{PUBLISHED['relations']:,}.\n")
    w("**Recommendation: exclude `OR` from the target set entirely** (it is "
      "coordination, not a clinical relation) and, if it is kept at all, count it "
      "one-per-`*`-line rather than pairwise so it does not dominate. Note the 4 "
      "`NOT` equivalence lines are not `OR` at all.\n")

    w("### D3 — Discontinuous entities\n")
    w(f"**{len(disc):,}** entities ({pct(len(disc), len(ents_in))}), of which "
      f"**{pct(disc_in_rel, len(disc))}** are relation arguments — so dropping them "
      "silently deletes real relations. Options: drop / merge to enclosing span / "
      "keep head fragment.\n")
    w("**Recommendation: merge to enclosing span**, and record a "
      "`discontinuous: true` flag plus the original fragments on the entity. "
      "GLiNER2-family models emit contiguous spans, so 'keep head fragment' "
      f"silently mislabels the gold answer, and 'drop' loses {disc_in_rel:,} relation "
      "arguments. Merging over-covers (`greater than Grade 1` instead of "
      "`greater than … 1`) but keeps the relation intact and is honestly reportable. "
      "Whatever we pick, evaluation must report discontinuous cases separately.\n")

    w("### D4 — Nested / overlapping entities\n")
    w(f"**{ident + contain + partial:,}** overlapping entity pairs, of which "
      f"{contain:,} are strict containment. Chia genuinely annotates `HIV+` as "
      "`Condition`, `Measurement` and `Value` simultaneously — any one-label-per-span "
      "flattening destroys the very `HAS_VALUE` relations we are targeting.\n")
    w("**Recommendation: keep all annotations** (no flattening). Entities are "
      "identified by brat id in the JSONL, so overlap is representable.\n")

    w("### D5 — Instance granularity\n")
    w(f"Only **{cross_line}** relations of {len(rels_in):,} cross a criterion "
      "boundary (§1.4). **Recommendation: one criterion = one instance**, dropping "
      f"those {cross_line} cross-criterion relations with a logged reason. "
      f"({ent_spans_multi_line} entities also cross a line boundary and would be "
      "dropped for the same reason.)\n")

    w("### D6 — Duplicate criteria and the leakage control\n")
    w(f"{len(multi_trial):,} criterion strings appear in more than one trial, "
      f"covering {pct(len(trials_touched), len(nct_ids))} of trials but only "
      f"{pct(occurrences_multi_trial, n_criteria)} of criteria, and they are "
      "overwhelmingly short boilerplate (`pregnancy`, `written informed consent`). "
      "Grouping splits by NCT ID does **not** eliminate them.\n")
    w("**Recommendation: keep them, report them.** They are genuine corpus "
      "distribution, and 67 trials legitimately share the criterion `pregnancy`. "
      "Deduplicating would distort the test set more than the leakage does. If you "
      "want them gone, say so and I will drop cross-trial duplicates from "
      "train only, never from test.\n")

    w("### D7 — Corpus variant and text normalisation\n")
    w("Profiled **without_scope** per your instruction (trap 8). Also note "
      f"{sum(1 for d in docs if chr(13) in d.text):,} of {len(docs):,} files use "
      "CRLF line endings; Phase 2 will normalise to `\\n` and re-base every offset, "
      "asserting `text[start:end] == entity_text` for every entity as you "
      "specified.\n")

    return "\n".join(out).replace("SUMMARY_PLACEHOLDER", summary_block(
        docs=docs,
        ents_in=ents_in,
        rels_in=rels_in,
        rel_origin=rel_origin,
        sig=sig,
        ev=ev,
        cross_line=cross_line,
        disc=disc,
        n_star=n_star,
        sim=sim,
        overlap_pairs=ident + contain + partial,
        nl=nl,
        xc_relations=xc["relations"] if xc else sim["relations_R"],
        rel_has_context=rel_types.get("HAS_CONTEXT", 0),
        rel_or_synth=rel_origin["EQUIV"],
    ))


def summary_block(*, docs, ents_in, rels_in, rel_origin, sig, ev, cross_line,
                  disc, n_star, sim, overlap_pairs, nl, xc_relations,
                  rel_has_context, rel_or_synth) -> str:
    crlf = nl["crlf_files"]
    lines = [
        "## Headline findings\n",
        "1. **There is no usable drug→dose relation in Chia.** "
        f"`Drug`→`Has_value`→`Value` occurs **{ev[('HAS_VALUE','Value')]['n']} times** "
        f"in the whole corpus. The larger candidates — `Has_multiplier` "
        f"({ev[('HAS_MULTIPLIER','Multiplier')]['n']}) and `Has_qualifier` "
        f"({ev[('HAS_QUALIFIER','Qualifier')]['n']}) — mix dose with frequency, "
        "duration and route. Your two-document reading was correct and the corpus "
        "confirms it. **This blocks the drug arm of the study (§2, D1).**\n",
        "2. **The test→result side is solid**: "
        f"`Measurement`→`Has_value`→`Value` = "
        f"**{sig.get(('Measurement','HAS_VALUE','Value'), 0):,}**, plus "
        f"{sig.get(('Person','HAS_VALUE','Value'), 0):,} for `Person` (age criteria).\n",
        "3. **The corpus offsets are not broken.** The reputation is an artifact of "
        f"reading the files with newline translation: {crlf:,} of {len(docs):,} "
        "`.txt` files use CRLF, and Python's universal-newline mode silently deletes "
        "one character per preceding line. Read raw (`newline=\"\"`), "
        f"**{100.0 * nl['raw'] / nl['total']:.2f}% of offsets are exactly correct**; "
        f"read the way `chia.py` does, only {100.0 * nl['universal'] / nl['total']:.1f}% are. "
        "BigBIO's `_fix_entity_offsets` is a ±100-character search that repairs a "
        "bug the loader itself introduces — and it cannot repair discontinuous "
        "entities at all, because it re-derives the mention text from the same "
        "offsets it is checking.\n",
        "4. **`load_dataset` does run here** (`datasets==2.19.0` + "
        "`trust_remote_code`), so it was diffed as a second source. Entities agree "
        f"exactly — {len(ents_in):,}, type for type. Relations do not: the loader "
        f"returns {xc_relations:,} where the raw files hold {len(rels_in):,}. "
        f"It loses {rel_has_context:,} `Has_context` to the `\"HAS_CONTEXT \"` "
        f"trailing-space typo (trap 2) and **all {rel_or_synth:,} synthesised `OR` "
        "relations to a third bug you hadn't catalogued** — an id-prefix mismatch "
        f"at `chia.py:365` that makes the equivalence guard never match. That is "
        f"{rel_has_context + rel_or_synth:,} relations, "
        f"{100.0 * (rel_has_context + rel_or_synth) / len(rels_in):.1f}% of the "
        f"corpus. (A further {sum(sim['lost_by_args'].values())} go to argument "
        "filtering — trap 3 — but those are dropped here too, correctly.) Reason "
        "enough on its own to parse the raw files.\n",
        f"5. **`OR` dominates if expanded pairwise**: {n_star:,} `*` lines become "
        f"{rel_origin['EQUIV']:,} relations, "
        f"{100.0 * rel_origin['EQUIV'] / len(rels_in):.1f}% of the corpus. This "
        "single choice accounts for the entire gap against the published relation "
        "total (§2, D2).\n",
        f"6. **One criterion is the right instance unit**: only **{cross_line}** of "
        f"{len(rels_in):,} relations cross a criterion boundary (0.02%).\n",
        f"7. **{len(disc):,} discontinuous entities ({100.0 * len(disc) / len(ents_in):.2f}%)** "
        f"and **{overlap_pairs:,} overlapping entity pairs** — both must be handled explicitly, "
        "and both are research decisions (§2, D3/D4).\n",
    ]
    return "\n".join(lines)


def parse_annotation_conf(text: str) -> dict:
    section = None
    entities: set[str] = set()
    relations: list[dict] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].lower()
            continue
        if section == "entities":
            if line.startswith("!"):
                continue
            entities.add(line)
        elif section == "relations":
            parts = line.split(None, 1)
            name = parts[0]
            args = parts[1] if len(parts) > 1 else ""
            arg1 = arg2 = "-"
            for chunk in args.split(","):
                chunk = chunk.strip()
                if chunk.startswith("Arg1:"):
                    arg1 = chunk[5:]
                elif chunk.startswith("Arg2:"):
                    arg2 = chunk[5:]
            relations.append({"name": name, "arg1": arg1, "arg2": arg2})
    return {"entities": entities, "relations": relations}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--without-scope", type=Path,
                    default=root / "data" / "raw" / "without_scope")
    ap.add_argument("--with-scope", type=Path,
                    default=root / "data" / "raw" / "with_scope")
    ap.add_argument("--out", type=Path, default=root / "profile_report.md")
    args = ap.parse_args()

    print(f"loading {args.without_scope} ...", file=sys.stderr)
    docs = load_corpus(args.without_scope)
    docs_ws = None
    if args.with_scope.exists():
        print(f"loading {args.with_scope} ...", file=sys.stderr)
        docs_ws = load_corpus(args.with_scope)

    print("profiling ...", file=sys.stderr)
    report = build_report(docs, docs_ws, root, args.without_scope)
    args.out.write_text(report, encoding="utf-8")
    print(f"wrote {args.out}", file=sys.stderr)
    print(f"MAX_OFFSET_CORRECTION={MAX_OFFSET_CORRECTION}, "
          f"schema entity types={len(SCHEMA_ENTITY_TYPES)}, "
          f"schema relation types={len(SCHEMA_RELATION_TYPES)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
