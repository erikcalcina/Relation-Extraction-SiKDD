from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from gliner2 import GLiNER2
from tqdm import tqdm



RELATION_LABELS = [
    "Has_value",
    "Has_qualifier",
    "Has_temporal",
    "Subsumes",
    "Has_index",
    "Has_negation",
    "Has_multiplier",
    "Has_mood",
    "Has_context",
    "AND",
    "OR",
]

RELATION_DESCRIPTIONS = {
    "Has_value": (
        "The target argument is a value associated with the source entity."
    ),
    "Has_qualifier": (
        "The target argument is a qualifier associated with the source entity."
    ),
    "Has_temporal": (
        "The target argument provides temporal information associated with the source entity."
    ),
    "Subsumes": (
        "A hierarchical relationship in which one concept or group of concepts "
        "specifies or clarifies another concept."
    ),
    "Has_index": (
        "The target argument is a reference point associated with the source entity."
    ),
    "Has_negation": (
        "The target argument is a negation modifier associated with the source entity."
    ),
    "Has_multiplier": (
        "The target argument is a multiplier associated with the source entity."
    ),
    "Has_mood": (
        "The target argument is a mood modifier associated with the source entity."
    ),
    "Has_context": (
        "The target argument is an observation providing context that is not "
        "represented by the other type-specific relationships."
    ),
    "AND": (
        "A Boolean AND relationship between two independent entities."
    ),
    "OR": (
        "A Boolean OR relationship between two independent entities."
    ),
}


def build_description_schema():
    return {
        "json_structures": [],
        "classifications": [],
        "entities": {},
        "relations": [
            {
                f"{label} [DESCRIPTION] {description}": {
                    "head": "",
                    "tail": "",
                }
            }
            for label, description in RELATION_DESCRIPTIONS.items()
        ],
        "json_descriptions": {},
        "entity_descriptions": {},
    }


DESCRIPTION_SCHEMA = build_description_schema()

def load_jsonl(path: Path) -> list[dict]:
    """Load our prepared Chia JSONL file."""
    examples = []

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if line:
                examples.append(json.loads(line))

    return examples


def get_gold_relations(example: dict) -> Counter:
    """
    Convert Chia gold relations into a comparable form.

    Relation representation:
    (
        relation_type,
        head_start,
        head_end,
        tail_start,
        tail_end,
    )
    """

    entities = {
        entity["id"]: entity
        for entity in example["entities"]
    }

    gold = Counter()

    for relation in example["relations"]:
        head = entities[relation["arg1_id"]]
        tail = entities[relation["arg2_id"]]

        key = (
            relation["type"],
            head["start"],
            head["end"],
            tail["start"],
            tail["end"],
        )

        gold[key] += 1

    return gold


def get_predicted_relations(result: dict) -> Counter:
    predicted = Counter()

    for relation_type in RELATION_LABELS:
        relations = result.get(relation_type, [])

        for relation in relations:
            head = relation["head"]
            tail = relation["tail"]

            key = (
                relation_type,
                head["start"],
                head["end"],
                tail["start"],
                tail["end"],
            )

            predicted[key] += 1

    return predicted


def calculate_metrics(tp: int, fp: int, fn: int) -> dict:
    """Calculate precision, recall and F1."""

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--model",
        default="fastino/gliner2-base-v1",
        help="GLiNER2 model to evaluate",
    )

    parser.add_argument(
        "--data",
        default="data/processed/chia_test.jsonl",
        help="Path to Chia test JSONL",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Evaluate only first N examples",
    )

    parser.add_argument(
        "--output-dir",
        default="outputs/zero_shot_chia_descriptions",
        help="Where results will be saved",
    )

    args = parser.parse_args()

    data_path = Path(args.data)
    output_dir = Path(args.output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading dataset: {data_path}")

    examples = load_jsonl(data_path)

    if args.limit is not None:
        examples = examples[: args.limit]

    print(f"Examples: {len(examples)}")
    print(f"Model: {args.model}")
    print()
    print("Relation labels:")

    for label in RELATION_LABELS:
        print(f"  - {label}")

    print()
    print("Loading GLiNER2 model...")

    model = GLiNER2.from_pretrained(args.model)

    print("Model loaded.")
    print()

    total_tp = 0
    total_fp = 0
    total_fn = 0

    per_label = defaultdict(
        lambda: {
            "tp": 0,
            "fp": 0,
            "fn": 0,
        }
    )

    predictions_path = output_dir / "predictions.jsonl"

    with predictions_path.open("w", encoding="utf-8") as output_file:

        for example in tqdm(examples, desc="Zero-shot evaluation"):

            text = example["text"]

            # ZERO-SHOT:
            # model receives only the names of relation labels.
            result = model.extract(
                text,
                DESCRIPTION_SCHEMA,
                include_spans=True,
                format_results=False,
            )

            gold = get_gold_relations(example)
            predicted = get_predicted_relations(result)

            correct = gold & predicted

            false_positive = predicted - gold
            false_negative = gold - predicted

            tp = sum(correct.values())
            fp = sum(false_positive.values())
            fn = sum(false_negative.values())

            total_tp += tp
            total_fp += fp
            total_fn += fn

            # Metrics for every relation type separately
            for relation in correct.elements():
                per_label[relation[0]]["tp"] += 1

            for relation in false_positive.elements():
                per_label[relation[0]]["fp"] += 1

            for relation in false_negative.elements():
                per_label[relation[0]]["fn"] += 1

            output_record = {
                "id": example["id"],
                "text": text,
                "gold": [
                    list(relation)
                    for relation in gold.elements()
                ],
                "prediction": result,
                "tp": tp,
                "fp": fp,
                "fn": fn,
            }

            output_file.write(
                json.dumps(
                    output_record,
                    ensure_ascii=False,
                )
                + "\n"
            )

    micro_metrics = calculate_metrics(
        total_tp,
        total_fp,
        total_fn,
    )

    per_label_metrics = {}

    for label in RELATION_LABELS:
        counts = per_label[label]

        per_label_metrics[label] = calculate_metrics(
            counts["tp"],
            counts["fp"],
            counts["fn"],
        )

    final_results = {
        "model": args.model,
        "experiment": "zero_shot_chia_relation_descriptions",
        "examples": len(examples),
        "relation_labels": RELATION_LABELS,
        "micro": micro_metrics,
        "per_relation": per_label_metrics,
    }

    metrics_path = output_dir / "metrics.json"

    with metrics_path.open("w", encoding="utf-8") as f:
        json.dump(
            final_results,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print("=============================")
    print("ZERO-SHOT RESULTS")
    print("================================")
    print(f"Examples:  {len(examples)}")
    print(f"TP:        {micro_metrics['tp']}")
    print(f"FP:        {micro_metrics['fp']}")
    print(f"FN:        {micro_metrics['fn']}")
    print()
    print(f"Precision: {micro_metrics['precision']:.4f}")
    print(f"Recall:    {micro_metrics['recall']:.4f}")
    print(f"F1:        {micro_metrics['f1']:.4f}")
    print()
    print(f"Predictions saved to: {predictions_path}")
    print(f"Metrics saved to:     {metrics_path}")


if __name__ == "__main__":
    main()