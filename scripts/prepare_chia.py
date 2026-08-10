#!/usr/bin/env python3
"""Phase 2: convert Chia to criterion-level JSONL and split it by trial.

    python3 scripts/prepare_chia.py

Writes:
    data/processed/chia_{train,dev,test}.jsonl
    data/splits/split.json          -- NCT id -> split, releasable artifact
    outputs/chia_split_stats.md     -- split statistics table
    outputs/chia_conversion_log.json -- every dropped record, with reasons
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from relation_extraction.data.chia_brat import load_corpus  # noqa: E402
from relation_extraction.data.chia_convert import (  # noqa: E402
    BOOLEAN_RELATION_TYPES,
    DEFAULT_SPLIT_FRACTIONS,
    SPLIT_NAMES,
    DropLog,
    add_negatives,
    convert_document,
    make_splits,
    split_statistics,
)

SEED = 20260810


def md_table(headers: list[str], rows: list[list], aligns: str | None = None) -> str:
    aligns = aligns or "l" * len(headers)
    sep = {"l": ":---", "r": "---:"}
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join(sep[a] for a in aligns) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def build_stats_report(stats: dict, neg_stats: dict, args, drops: DropLog) -> str:
    out: list[str] = []
    w = out.append

    w("# Chia — split statistics\n")
    w(f"Seed `{args.seed}`; split fractions "
      f"{args.train_frac}/{args.dev_frac}/{args.test_frac} at **trial level** "
      "(all criteria from one NCT id, inclusion and exclusion, share a split).\n")
    w("Labels are Chia's native relation strings, unmodified. `AND` and `OR` are "
      "retained but flagged `\"boolean\": true` in the JSONL and counted "
      "separately below, so they can be included or excluded at experiment time "
      "without regenerating the data.\n")

    w("## Totals\n")
    keys = [
        ("trials", "Trials"),
        ("documents", "Documents"),
        ("criteria", "Criteria (instances)"),
        ("entities", "Entities"),
        ("discontinuous_entities", "— discontinuous (merged to enclosing span)"),
        ("semantic_relations", "**Semantic relations**"),
        ("boolean_relations", "Boolean relations (`AND`/`OR`)"),
        ("relations", "All relations"),
        ("negative_pairs", "Negative (NA) pairs"),
    ]
    rows = []
    for key, label in keys:
        vals = [stats[s][key] for s in SPLIT_NAMES]
        rows.append([label] + [f"{v:,}" for v in vals] + [f"{sum(vals):,}"])
    w(md_table(["Quantity", "train", "dev", "test", "total"], rows, "lrrrr"))
    w("")

    pcts = []
    total_trials = sum(stats[s]["trials"] for s in SPLIT_NAMES)
    for s in SPLIT_NAMES:
        pcts.append(f"{100.0 * stats[s]['trials'] / total_trials:.1f}%")
    w(f"Trial-level split actually achieved: "
      + " / ".join(f"{s} {p}" for s, p in zip(SPLIT_NAMES, pcts)) + ".\n")

    w("## Relations per type and split\n")
    all_types = collections.Counter()
    for s in SPLIT_NAMES:
        all_types.update(stats[s]["relation_types"])
    rows = []
    for rtype, total in all_types.most_common():
        flag = " *(Boolean)*" if rtype.upper() in BOOLEAN_RELATION_TYPES else ""
        rows.append(
            [f"`{rtype}`{flag}"]
            + [f"{stats[s]['relation_types'].get(rtype, 0):,}" for s in SPLIT_NAMES]
            + [f"{total:,}"]
        )
    w(md_table(["Relation type", "train", "dev", "test", "total"], rows, "lrrrr"))
    w("")

    w("## Entities per type and split\n")
    all_ents = collections.Counter()
    for s in SPLIT_NAMES:
        all_ents.update(stats[s]["entity_types"])
    rows = [
        [f"`{etype}`"]
        + [f"{stats[s]['entity_types'].get(etype, 0):,}" for s in SPLIT_NAMES]
        + [f"{total:,}"]
        for etype, total in all_ents.most_common()
    ]
    w(md_table(["Entity type", "train", "dev", "test", "total"], rows, "lrrrr"))
    w("")

    w("## Negative (NA) pairs\n")
    w("**Candidate rule:** every ordered pair of distinct entities within the same "
      "criterion that is not linked by a gold relation. Ordered, because Chia's "
      "relations are directed. `AND`/`OR` pairs count as *related* and are "
      "therefore excluded from the negatives, so toggling the Boolean relations "
      "off at experiment time can never silently turn a positive into a "
      "negative.\n")
    w(f"**Subsampling:** {'none — every candidate is kept' if args.neg_ratio is None else f'{args.neg_ratio} x positives per instance, seeded'}. "
      "The identical procedure and seed are applied to all three splits.\n")
    w(md_table(
        ["Quantity", "Value"],
        [
            ["Candidate negative pairs", f"{neg_stats['candidates']:,}"],
            ["Negative pairs kept", f"{neg_stats['kept']:,}"],
        ],
        "lr",
    ))
    w("")

    w("## Dropped records\n")
    if drops.total() == 0:
        w("Nothing dropped.\n")
    else:
        w(md_table(
            ["Reason", "Count", "Example"],
            [
                [r, f"{c:,}", f"`{drops.examples[r][0]}`" if drops.examples[r] else ""]
                for r, c in drops.counts.most_common()
            ],
            "lrl",
        ))
        w("")
        w(f"Total: **{drops.total():,}** records dropped, all logged in "
          "`outputs/chia_conversion_log.json`.\n")
    return "\n".join(out)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path,
                    default=root / "data" / "raw" / "without_scope")
    ap.add_argument("--processed-dir", type=Path, default=root / "data" / "processed")
    ap.add_argument("--splits-dir", type=Path, default=root / "data" / "splits")
    ap.add_argument("--outputs-dir", type=Path, default=root / "outputs")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--train-frac", type=float, default=DEFAULT_SPLIT_FRACTIONS[0])
    ap.add_argument("--dev-frac", type=float, default=DEFAULT_SPLIT_FRACTIONS[1])
    ap.add_argument("--test-frac", type=float, default=DEFAULT_SPLIT_FRACTIONS[2])
    ap.add_argument("--neg-ratio", type=float, default=None,
                    help="negatives per positive, per instance; default keeps all")
    ap.add_argument("--keep-empty-criteria", action="store_true",
                    help="emit criteria with no in-schema entities (they yield no "
                         "candidate pairs, so they are dropped by default)")
    args = ap.parse_args()

    print(f"loading {args.source} ...", file=sys.stderr)
    docs = load_corpus(args.source)

    drops = DropLog()
    instances: list[dict] = []
    for doc in docs:
        instances.extend(
            convert_document(doc, drops, keep_empty=args.keep_empty_criteria)
        )
    print(f"converted {len(instances):,} criterion instances", file=sys.stderr)

    fractions = (args.train_frac, args.dev_frac, args.test_frac)
    split_map = make_splits(
        [d.nct_id for d in docs], seed=args.seed, fractions=fractions
    )

    by_split: dict[str, list[dict]] = {name: [] for name in SPLIT_NAMES}
    for inst in instances:
        inst["split"] = split_map[inst["nct_id"]]
        by_split[inst["split"]].append(inst)

    # The leakage control, tested rather than assumed.
    id_sets = {name: {i["nct_id"] for i in by_split[name]} for name in SPLIT_NAMES}
    for i, a in enumerate(SPLIT_NAMES):
        for b in SPLIT_NAMES[i + 1:]:
            shared = id_sets[a] & id_sets[b]
            assert not shared, f"NCT leakage between {a} and {b}: {sorted(shared)[:5]}"
    assert sum(len(v) for v in by_split.values()) == len(instances)
    print("split disjointness asserted: train/dev/test share no NCT id",
          file=sys.stderr)

    neg_stats = collections.Counter()
    for name in SPLIT_NAMES:
        s = add_negatives(
            by_split[name], seed=args.seed, ratio=args.neg_ratio,
            include_boolean=True,
        )
        neg_stats.update(s)

    args.processed_dir.mkdir(parents=True, exist_ok=True)
    args.splits_dir.mkdir(parents=True, exist_ok=True)
    args.outputs_dir.mkdir(parents=True, exist_ok=True)

    for name in SPLIT_NAMES:
        path = args.processed_dir / f"chia_{name}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for inst in by_split[name]:
                handle.write(json.dumps(inst, ensure_ascii=False) + "\n")
        print(f"wrote {path} ({len(by_split[name]):,} instances)", file=sys.stderr)

    split_path = args.splits_dir / "split.json"
    split_path.write_text(
        json.dumps(
            {
                "seed": args.seed,
                "fractions": {"train": args.train_frac, "dev": args.dev_frac,
                              "test": args.test_frac},
                "grouping": "nct_id",
                "source": str(args.source.name),
                "assignments": dict(sorted(split_map.items())),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {split_path}", file=sys.stderr)

    stats = split_statistics(by_split)
    report = build_stats_report(stats, dict(neg_stats), args, drops)
    stats_path = args.outputs_dir / "chia_split_stats.md"
    stats_path.write_text(report, encoding="utf-8")

    log_path = args.outputs_dir / "chia_conversion_log.json"
    log_path.write_text(
        json.dumps(
            {
                "seed": args.seed,
                "total_dropped": drops.total(),
                "counts": dict(drops.counts.most_common()),
                "examples": {k: v for k, v in drops.examples.items()},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {stats_path} and {log_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
