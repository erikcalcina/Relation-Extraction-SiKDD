#!/usr/bin/env python3
"""Cross-check: load `bigbio/chia` via `load_dataset` and dump its counts to JSON.

`bigbio/chia` is a script-based dataset. `datasets` v3+ refuses to execute
loading scripts, so this needs a pinned v2 and an explicit opt-in:

    uv run --python 3.12 --with 'datasets==2.19.0' --with 'fsspec==2024.3.1' \
        python scripts/crosscheck_bigbio.py --out outputs/bigbio_counts.json

The profiling script picks the JSON up automatically if it exists. Where the two
disagree, the raw parse in ``chia_brat.py`` is authoritative.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="chia_without_scope_source")
    ap.add_argument("--out", type=Path,
                    default=Path("outputs") / "bigbio_counts.json")
    args = ap.parse_args()

    import datasets

    ds = datasets.load_dataset("bigbio/chia", args.config, trust_remote_code=True)

    entity_types: collections.Counter = collections.Counter()
    relation_types: collections.Counter = collections.Counter()
    n_docs = n_entities = n_relations = 0
    nct_ids = set()

    for split in ds:
        for ex in ds[split]:
            n_docs += 1
            nct_ids.add(ex["document_id"])
            n_entities += len(ex["entities"])
            n_relations += len(ex["relations"])
            for ent in ex["entities"]:
                entity_types[ent["type"]] += 1
            for rel in ex["relations"]:
                relation_types[rel["type"].upper()] += 1

    payload = {
        "datasets_version": datasets.__version__,
        "config": args.config,
        "documents": n_docs,
        "trials": len(nct_ids),
        "entities": n_entities,
        "relations": n_relations,
        "entity_types": dict(entity_types.most_common()),
        "relation_types": dict(relation_types.most_common()),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
