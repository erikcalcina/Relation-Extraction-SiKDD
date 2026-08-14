from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from gliner2_adapter import (
    convert_chia_instance_to_gliner2,
)


SPLITS = ("train", "dev", "test")


def load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file."""

    examples = []

    with path.open(
        "r",
        encoding="utf-8",
    ) as f:

        for line_number, line in enumerate(
            f,
            start=1,
        ):
            line = line.strip()

            if not line:
                continue

            try:
                example = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in {path}, "
                    f"line {line_number}"
                ) from exc

            examples.append(example)

    return examples


def count_relations(
    examples: list[dict],
) -> Counter:
    """Count relation labels in canonical Chia examples."""

    counts = Counter()

    for example in examples:
        for relation in example["relations"]:
            counts[relation["type"]] += 1

    return counts


def validate_converted_example(
    example: dict,
) -> None:
    """
    Basic validation of one GLiNER2 example.

    We check that every head and tail really occurs
    inside the original input text.
    """

    text = example["input"]

    output = example.get("output")

    if not isinstance(output, dict):
        raise ValueError(
            "Missing or invalid output field"
        )

    relations = output.get("relations")

    if not isinstance(relations, list):
        raise ValueError(
            "output.relations must be a list"
        )

    for relation in relations:

        if len(relation) != 1:
            raise ValueError(
                f"Invalid relation structure: {relation}"
            )

        relation_type, arguments = next(
            iter(relation.items())
        )

        if not relation_type:
            raise ValueError(
                "Empty relation type"
            )

        head = arguments.get("head")
        tail = arguments.get("tail")

        if not head:
            raise ValueError(
                f"{relation_type}: empty head"
            )

        if not tail:
            raise ValueError(
                f"{relation_type}: empty tail"
            )

        if head not in text:
            raise ValueError(
                f"{relation_type}: "
                f"head not found in input: {head!r}"
            )

        if tail not in text:
            raise ValueError(
                f"{relation_type}: "
                f"tail not found in input: {tail!r}"
            )


def convert_split(
    input_path: Path,
    output_path: Path,
    *,
    drop_empty: bool,
) -> dict:
    """
    Convert one Chia split to GLiNER2 JSONL.
    """

    chia_examples = load_jsonl(
        input_path
    )

    original_relation_counts = (
        count_relations(chia_examples)
    )

    converted_count = 0
    skipped_empty = 0
    converted_relations = 0

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as output_file:

        for instance in chia_examples:

            converted = (
                convert_chia_instance_to_gliner2(
                    instance
                )
            )

            relations = (
                converted["output"]["relations"]
            )

            if not relations and drop_empty:
                skipped_empty += 1
                continue

            validate_converted_example(
                converted
            )

            converted_relations += len(
                relations
            )

            output_file.write(
                json.dumps(
                    converted,
                    ensure_ascii=False,
                )
                + "\n"
            )

            converted_count += 1

    return {
        "input_examples": len(
            chia_examples
        ),
        "output_examples": converted_count,
        "skipped_empty": skipped_empty,
        "original_relations": sum(
            original_relation_counts.values()
        ),
        "converted_relations": (
            converted_relations
        ),
        "relation_counts": dict(
            sorted(
                original_relation_counts.items()
            )
        ),
    }


def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Convert prepared Chia data "
            "to GLiNER2 relation-training JSONL."
        )
    )

    parser.add_argument(
        "--input-dir",
        default="data/processed",
        help=(
            "Directory containing "
            "chia_train.jsonl, chia_dev.jsonl "
            "and chia_test.jsonl"
        ),
    )

    parser.add_argument(
        "--output-dir",
        default="data/processed/gliner2",
        help="Output directory",
    )

    parser.add_argument(
        "--drop-empty",
        action="store_true",
        help=(
            "Drop criteria that contain no gold relations. "
            "Default: keep them."
        ),
    )

    args = parser.parse_args()

    input_dir = Path(
        args.input_dir
    )

    output_dir = Path(
        args.output_dir
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    all_stats = {}

    print()
    print(
        "======================================"
    )
    print(
        "Chia -> GLiNER2 conversion"
    )
    print(
        "======================================"
    )
    print()

    for split in SPLITS:

        input_path = (
            input_dir
            / f"chia_{split}.jsonl"
        )

        output_path = (
            output_dir
            / f"chia_{split}.jsonl"
        )

        if not input_path.exists():
            raise FileNotFoundError(
                f"Missing input file: "
                f"{input_path}"
            )

        print(
            f"Converting {split}..."
        )

        stats = convert_split(
            input_path=input_path,
            output_path=output_path,
            drop_empty=args.drop_empty,
        )

        all_stats[split] = stats

        print(
            f"  input examples:     "
            f"{stats['input_examples']}"
        )

        print(
            f"  output examples:    "
            f"{stats['output_examples']}"
        )

        print(
            f"  skipped empty:      "
            f"{stats['skipped_empty']}"
        )

        print(
            f"  original relations: "
            f"{stats['original_relations']}"
        )

        print(
            f"  converted relations:"
            f" {stats['converted_relations']}"
        )

        print()

    stats_path = (
        output_dir
        / "conversion_stats.json"
    )

    with stats_path.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            all_stats,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(
        "======================================"
    )
    print(
        "Conversion completed successfully."
    )
    print(
        "======================================"
    )

    print()

    for split in SPLITS:
        print(
            output_dir
            / f"chia_{split}.jsonl"
        )

    print()
    print(
        f"Statistics: {stats_path}"
    )


if __name__ == "__main__":
    main()