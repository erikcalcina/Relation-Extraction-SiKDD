from __future__ import annotations

from typing import Any


def get_entity_surface(
    entity: dict[str, Any],
    text: str,
) -> str:
    """
    Get the entity text directly from the criterion using its offsets.

    Example:
        text = "... adequate contraception ..."
        start = 54
        end = 76

    Result:
        "adequate contraception"
    """

    start = int(entity["start"])
    end = int(entity["end"])

    if start < 0:
        raise ValueError(
            f"Negative start offset for entity {entity['id']}: {start}"
        )

    if end > len(text):
        raise ValueError(
            f"End offset outside text for entity {entity['id']}: "
            f"{end} > {len(text)}"
        )

    if start >= end:
        raise ValueError(
            f"Invalid offsets for entity {entity['id']}: "
            f"{start}:{end}"
        )

    surface = text[start:end]

    if not surface:
        raise ValueError(
            f"Empty surface text for entity {entity['id']}"
        )

    return surface


def convert_relation(
    relation: dict[str, Any],
    entities_by_id: dict[str, dict[str, Any]],
    text: str,
) -> dict[str, Any]:
    """
    Convert one Chia relation into GLiNER2 format.

    Chia:

        {
            "type": "Has_negation",
            "arg1_id": "T4",
            "arg2_id": "T3"
        }

    GLiNER2:

        {
            "Has_negation": {
                "head": "adequate contraception",
                "tail": "do not"
            }
        }
    """

    arg1_id = relation["arg1_id"]
    arg2_id = relation["arg2_id"]

    if arg1_id not in entities_by_id:
        raise ValueError(
            f"Missing relation argument: {arg1_id}"
        )

    if arg2_id not in entities_by_id:
        raise ValueError(
            f"Missing relation argument: {arg2_id}"
        )

    head_entity = entities_by_id[arg1_id]
    tail_entity = entities_by_id[arg2_id]

    head_text = get_entity_surface(
        head_entity,
        text,
    )

    tail_text = get_entity_surface(
        tail_entity,
        text,
    )

    relation_type = relation["type"]

    return {
        relation_type: {
            "head": head_text,
            "tail": tail_text,
        }
    }


def convert_chia_instance_to_gliner2(
    instance: dict[str, Any],
) -> dict[str, Any]:
    """
    Convert one prepared Chia criterion into GLiNER2 training format.

    All gold relation types are retained, including AND and OR.
    """

    text = instance["text"]

    if not isinstance(text, str):
        raise ValueError(
            f"{instance.get('id')}: text is not a string"
        )

    if not text:
        raise ValueError(
            f"{instance.get('id')}: empty text"
        )

    entities_by_id = {
        entity["id"]: entity
        for entity in instance["entities"]
    }

    relations = []

    for relation in instance["relations"]:
        converted = convert_relation(
            relation=relation,
            entities_by_id=entities_by_id,
            text=text,
        )

        relations.append(converted)

    return {
        "input": text,
        "output": {
            "relations": relations,
        },
    }