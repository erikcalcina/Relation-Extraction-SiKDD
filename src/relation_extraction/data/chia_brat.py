"""Brat standoff parser for the Chia clinical-trial eligibility corpus.

Parses the raw ``.ann``/``.txt`` files shipped in ``chia_without_scope.zip``
(figshare 10.6084/m9.figshare.11855817, mirrored byte-identically at
``bigbio/chia``).

Scoped deliberately to what Chia actually contains. Across its 2,000 ``.ann``
files there are only ``T`` (44,616), ``R`` (20,153) and ``*`` (5,015) lines: no
``E``/``A``/``M``/``N`` annotations and no multi-line continuations. A general
brat parser is not needed and is not provided.

Two deliberate differences from the BigBIO ``chia.py`` loading script:

1. ``.txt`` files are read with ``newline=""`` so CRLF line endings survive.
   ``chia.py`` uses ``Path.open()``, whose universal-newline translation
   rewrites ``\\r\\n`` -> ``\\n`` and shifts every later offset left by one per
   preceding line. That is the dominant cause of the corpus' reputation for
   "broken offsets": read raw, 99.98% of entity offsets are exactly correct.
2. ``HAS_CONTEXT`` carries no trailing space (``chia.py`` writes
   ``"HAS_CONTEXT "``, silently dropping every ``Has_context`` relation), and
   relation types are matched case-insensitively.

Nothing is filtered here. Relations whose arguments do not resolve are passed
through so that the converter's drop log is the single place things disappear.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

Span = tuple[int, int]

#: The 16 schema entity types; the 15 published types are these minus ``Scope``
#: (which appears only in the "with scope" corpus variant).
SCHEMA_ENTITY_TYPES = frozenset(
    [
        "Condition", "Device", "Drug", "Measurement", "Observation",
        "Person", "Procedure", "Visit",          # domain
        "Temporal", "Value",                      # field
        "Scope", "Negation", "Multiplier", "Qualifier", "Reference_point",
        "Mood",                                   # construct
    ]
)

#: The 12 published relation types, upper-cased. ``HAS_CONTEXT`` has no
#: trailing space here -- that typo is the BigBIO loader bug.
SCHEMA_RELATION_TYPES = frozenset(
    [
        "AND", "OR", "SUBSUMES", "HAS_NEGATION", "HAS_MULTIPLIER",
        "HAS_QUALIFIER", "HAS_VALUE", "HAS_TEMPORAL", "HAS_INDEX", "HAS_MOOD",
        "HAS_CONTEXT", "HAS_SCOPE",
    ]
)

#: Search radius used by :func:`fix_entity_offsets` (BigBIO's value).
MAX_OFFSET_CORRECTION = 100


def surface(doc_text: str, spans: tuple[Span, ...]) -> str:
    """Fragment texts joined the way brat serialises a mention."""
    return " ".join(doc_text[s:e] for s, e in spans)


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class Entity:
    """A brat text-bound annotation (``T`` line)."""

    id: str
    type: str
    spans: tuple[Span, ...]
    ann_text: str
    #: ``exact``, ``bigbio_fix`` or ``unrepaired`` -- see :func:`repair_entity`.
    offset_status: str = "exact"

    @property
    def start(self) -> int:
        return min(start for start, _ in self.spans)

    @property
    def end(self) -> int:
        return max(end for _, end in self.spans)


@dataclass
class Relation:
    """A relation between two entities.

    ``origin`` is ``"R"`` for an ``R`` line and ``"EQUIV"`` for the pairwise
    ``OR`` relations synthesised from a ``*`` line.
    """

    id: str
    type: str
    arg1_id: str
    arg2_id: str
    origin: str = "R"

    @property
    def norm_type(self) -> str:
        return self.type.upper()


@dataclass
class Document:
    """One Chia file: a single trial's inclusion *or* exclusion criteria."""

    doc_key: str  # e.g. "NCT00050349_inc"
    nct_id: str  # e.g. "NCT00050349"
    text_type: str  # "inclusion" | "exclusion"
    text: str  # raw text, CRLF preserved
    entities: dict[str, Entity] = field(default_factory=dict)
    relations: list[Relation] = field(default_factory=list)

    def criterion_spans(self) -> list[Span]:
        """``(start, end)`` of every non-empty line, in document coordinates.

        ``end`` excludes the line terminator. A criterion is one line; a line
        may contain several sentences, so never split these further.
        """
        out: list[Span] = []
        pos = 0
        for line in self.text.split("\n"):
            # ``line`` still carries its trailing "\r" when the file is CRLF.
            if line.strip():
                out.append((pos, pos + len(line.rstrip("\r"))))
            pos += len(line) + 1
        return out


# --------------------------------------------------------------------------
# Offset repair
# --------------------------------------------------------------------------


def fix_entity_offsets(doc_text: str, entity_text: str, given: Span) -> Span:
    """Port of BigBIO ``chia.py::_fix_entity_offsets``, with a bounds guard.

    Searches incrementally larger shifts left and right of ``given`` for the
    mention text, returning ``given`` unchanged if nothing is found within
    :data:`MAX_OFFSET_CORRECTION`. Unlike the original, a shift that would run
    off the front of the document is skipped rather than allowed to wrap around
    to the end via Python's negative indexing.
    """
    left, right = given
    wanted = entity_text.strip()
    width = right - left

    for i in range(MAX_OFFSET_CORRECTION + 1):
        for start in (left - i, left + i):
            if start >= 0 and doc_text[start : start + width].strip() == wanted:
                return (start, start + len(wanted))

    return given


def repair_entity(
    doc_text: str, spans: tuple[Span, ...], ann_text: str
) -> tuple[tuple[Span, ...], str]:
    """Return ``(spans, status)`` with the offsets verified against the text.

    ``exact``
        The offsets as annotated already reproduce the mention text. This is
        44,602 of the corpus' 44,616 mentions, including every discontinuous
        one, provided the text was read without newline translation.
    ``bigbio_fix``
        Repaired by :func:`fix_entity_offsets` (11 mentions).
    ``unrepaired``
        Still does not match (3 mentions); offsets returned as annotated. The
        converter drops and logs these rather than emitting bad offsets.
    """
    if surface(doc_text, spans) == ann_text:
        return spans, "exact"

    if len(spans) == 1:
        fixed = fix_entity_offsets(doc_text, ann_text, spans[0])
        if surface(doc_text, (fixed,)) == ann_text:
            return (fixed,), "bigbio_fix"

    return spans, "unrepaired"


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def parse_ann(ann_text: str) -> dict:
    """Parse the ``T`` / ``R`` / ``*`` lines of a Chia ``.ann`` file.

    ``T`` offsets may be ``;``-separated for a discontinuous mention. Any line
    that is neither parseable nor one of those three tags is collected under
    ``"malformed"`` rather than skipped.
    """
    out: dict[str, list] = {
        "entities": [], "relations": [], "equivalences": [], "malformed": [],
    }

    for raw_line in ann_text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        fields = line.split("\t")
        tag = fields[0]
        try:
            if tag.startswith("T"):
                type_name, _, span_str = fields[1].partition(" ")
                out["entities"].append(
                    {
                        "id": tag,
                        "type": type_name,
                        "spans": tuple(
                            (int(a), int(b))
                            for a, b in (p.split() for p in span_str.split(";"))
                        ),
                        "text": fields[2],
                    }
                )
            elif tag.startswith("R"):
                parts = fields[1].split()
                out["relations"].append(
                    {
                        "id": tag,
                        "type": parts[0],
                        "arg1": parts[1].split(":", 1)[1],
                        "arg2": parts[2].split(":", 1)[1],
                    }
                )
            elif tag.startswith("*"):
                parts = fields[1].split()
                out["equivalences"].append(
                    {"type": parts[0], "ref_ids": tuple(parts[1:])}
                )
            else:
                out["malformed"].append(line)
        except (IndexError, ValueError):
            out["malformed"].append(line)

    return out


def _next_synthetic_id(relations: list[dict]) -> int:
    """First ``R`` number safe to assign to a synthesised relation.

    BigBIO numbers these from ``len(relations) + 10``; that is the *count*, not
    the highest id, so a file with gaps in its ``R`` numbering could collide.
    Chia has no such file, so taking the max with ``highest + 1`` keeps the
    existing numbering byte-for-byte while removing the trap.
    """
    highest = max(
        (int(r["id"][1:]) for r in relations if r["id"][1:].isdigit()), default=0
    )
    return max(len(relations) + 10, highest + 1)


def load_document(txt_path: Path) -> Document:
    """Load one ``.txt``/``.ann`` pair into a :class:`Document`."""
    stem = txt_path.with_suffix("").name
    # Reading without newline translation is what keeps the offsets valid.
    with txt_path.open(encoding="utf-8", newline="") as handle:
        text = handle.read()

    ann_path = txt_path.with_suffix(".ann")
    parsed = parse_ann(
        ann_path.read_text(encoding="utf-8") if ann_path.exists() else ""
    )

    entities: dict[str, Entity] = {}
    for ann in parsed["entities"]:
        if ann["id"] in entities:
            continue  # duplicate T id; never occurs in Chia
        spans, status = repair_entity(text, ann["spans"], ann["text"])
        entities[ann["id"]] = Entity(
            ann["id"], ann["type"], spans, ann["text"], status
        )

    relations = [
        Relation(r["id"], r["type"], r["arg1"], r["arg2"])
        for r in parsed["relations"]
    ]

    # Expand each `*` equivalence set into pairwise relations.
    next_id = _next_synthetic_id(parsed["relations"])
    for eq in parsed["equivalences"]:
        refs = eq["ref_ids"]
        for i, arg1 in enumerate(refs):
            for arg2 in refs[i + 1 :]:
                relations.append(
                    Relation(f"R{next_id}", eq["type"], arg1, arg2, origin="EQUIV")
                )
                next_id += 1

    return Document(
        doc_key=stem,
        nct_id=stem.split("_")[0],
        text_type="inclusion" if "_inc" in stem else "exclusion",
        text=text,
        entities=entities,
        relations=relations,
    )


def load_corpus(directory: Path) -> list[Document]:
    """Load every ``.txt``/``.ann`` pair under ``directory``, sorted by name."""
    return [load_document(p) for p in sorted(Path(directory).glob("*.txt"))]
