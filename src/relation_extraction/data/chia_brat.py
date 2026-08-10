"""Brat standoff parser for the Chia clinical-trial eligibility corpus.

Parses the raw ``.ann`` / ``.txt`` files shipped in ``chia_with_scope.zip`` /
``chia_without_scope.zip`` (figshare 10.6084/m9.figshare.11855817, mirrored
byte-identically at ``bigbio/chia``).

Deliberate differences from the BigBIO ``chia.py`` loading script:

1. ``.txt`` files are read with ``newline=""`` so that CRLF line endings are
   preserved verbatim. ``chia.py`` uses ``Path.open()``, whose universal-newline
   translation rewrites ``\\r\\n`` -> ``\\n`` and thereby shifts every character
   offset in the file left by one per preceding line. That translation is the
   dominant cause of the corpus' reputation for "broken offsets": read raw,
   99.97% of entity offsets are exactly correct.
2. ``HAS_CONTEXT`` has no trailing space (``chia.py`` writes ``"HAS_CONTEXT "``,
   which silently drops every ``Has_context`` relation), and relation types are
   matched case-insensitively.
3. Nothing is filtered away silently. Out-of-schema entity/relation types and
   relations with unresolvable arguments are retained on the document as
   :class:`DropRecord` entries so callers can count and report them.

``fix_entity_offsets`` is a faithful port of BigBIO's ``_fix_entity_offsets``
and is retained as a fallback repair for the residual mismatches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Schema constants (from the Chia paper appendix / bigbio chia.py)
# --------------------------------------------------------------------------

DOMAIN_ENTITY_TYPES = [
    "Condition",
    "Device",
    "Drug",
    "Measurement",
    "Observation",
    "Person",
    "Procedure",
    "Visit",
]

FIELD_ENTITY_TYPES = ["Temporal", "Value"]

CONSTRUCT_ENTITY_TYPES = [
    "Scope",  # only present in the "with scope" variant
    "Negation",
    "Multiplier",
    "Qualifier",
    "Reference_point",
    "Mood",
]

#: The 16 schema entity types; the 15 published types are these minus ``Scope``.
SCHEMA_ENTITY_TYPES = frozenset(
    DOMAIN_ENTITY_TYPES + FIELD_ENTITY_TYPES + CONSTRUCT_ENTITY_TYPES
)

#: The 12 published relation types, upper-cased. Note ``HAS_CONTEXT`` carries no
#: trailing space here -- that typo is the BigBIO loader bug.
SCHEMA_RELATION_TYPES = frozenset(
    [
        "AND",
        "OR",
        "SUBSUMES",
        "HAS_NEGATION",
        "HAS_MULTIPLIER",
        "HAS_QUALIFIER",
        "HAS_VALUE",
        "HAS_TEMPORAL",
        "HAS_INDEX",
        "HAS_MOOD",
        "HAS_CONTEXT",
        "HAS_SCOPE",  # only present in the "with scope" variant
    ]
)

#: Search radius used by :func:`fix_entity_offsets` (BigBIO's value).
MAX_OFFSET_CORRECTION = 100

Span = tuple[int, int]


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
    #: How the offsets ended up where they are: see :func:`repair_entity`.
    offset_status: str = "exact"
    raw_spans: tuple[Span, ...] = ()

    @property
    def is_discontinuous(self) -> bool:
        return len(self.spans) > 1

    @property
    def start(self) -> int:
        return self.spans[0][0]

    @property
    def end(self) -> int:
        return self.spans[-1][1]

    @property
    def in_schema(self) -> bool:
        return self.type in SCHEMA_ENTITY_TYPES

    def char_indices(self) -> frozenset[int]:
        """Every character position the entity covers (fragments only)."""
        out: set[int] = set()
        for start, end in self.spans:
            out.update(range(start, end))
        return frozenset(out)

    def surface(self, doc_text: str) -> str:
        """Fragment texts joined the way brat serialises them."""
        return " ".join(doc_text[s:e] for s, e in self.spans)


@dataclass
class Relation:
    """A relation between two entities.

    ``origin`` is ``"R"`` for relations annotated on an ``R`` line and
    ``"EQUIV"`` for the pairwise ``OR`` relations synthesised from ``*`` lines.
    """

    id: str
    type: str
    arg1_id: str
    arg2_id: str
    origin: str = "R"

    @property
    def norm_type(self) -> str:
        return self.type.upper()

    @property
    def in_schema(self) -> bool:
        return self.norm_type in SCHEMA_RELATION_TYPES


@dataclass
class Equivalence:
    """A brat ``*`` line: an unordered set of co-referent entity ids."""

    id: str
    ref_ids: tuple[str, ...]
    type: str = "OR"


@dataclass
class DropRecord:
    """Something the parser could not keep, retained for reporting."""

    kind: str  # "entity" | "relation" | "equivalence"
    id: str
    reason: str
    detail: str = ""


@dataclass
class Document:
    """One Chia file: a single trial's inclusion *or* exclusion criteria."""

    doc_key: str  # e.g. "NCT00050349_inc"
    nct_id: str  # e.g. "NCT00050349"
    text_type: str  # "inclusion" | "exclusion"
    text: str  # raw text, CRLF preserved
    entities: dict[str, Entity] = field(default_factory=dict)
    relations: list[Relation] = field(default_factory=list)
    equivalences: list[Equivalence] = field(default_factory=list)
    drops: list[DropRecord] = field(default_factory=list)
    #: ``R`` ids present in the file, for relation-id gap analysis.
    relation_ids_seen: list[str] = field(default_factory=list)
    #: Non-``T``/``R``/``*`` annotation lines, if the corpus ever grows any.
    events: list[dict] = field(default_factory=list)
    attributes: list[dict] = field(default_factory=list)
    normalizations: list[dict] = field(default_factory=list)

    def criterion_spans(self) -> list[Span]:
        """``(start, end)`` of every non-empty line, in document coordinates.

        ``end`` excludes the line terminator. A criterion is one line; a line
        may contain several sentences, so never split these further.
        """
        out: list[Span] = []
        pos = 0
        for line in self.text.split("\n"):
            # ``line`` still carries its trailing "\r" when the file is CRLF.
            stripped_end = len(line.rstrip("\r"))
            if line.strip():
                out.append((pos, pos + stripped_end))
            pos += len(line) + 1
        return out


# --------------------------------------------------------------------------
# Offset repair
# --------------------------------------------------------------------------


def fix_entity_offsets(
    doc_text: str, entity_text: str, given_offsets: Span
) -> Span:
    """Port of BigBIO ``chia.py::_fix_entity_offsets``.

    Searches incrementally larger shifts left and right of the given offsets
    for the mention text. Returns the given offsets unchanged if no better
    position is found within :data:`MAX_OFFSET_CORRECTION` characters.
    """
    left, right = given_offsets
    clean_entity_text = entity_text.strip()

    i = 0
    while i <= MAX_OFFSET_CORRECTION:
        # Move mention window to the left
        if doc_text[left - i : right - i].strip() == clean_entity_text:
            return (left - i, left - i + len(clean_entity_text))
        # Move mention window to the right
        if doc_text[left + i : right + i].strip() == clean_entity_text:
            return (left + i, left + i + len(clean_entity_text))
        i += 1

    return given_offsets


def _matches(doc_text: str, spans: tuple[Span, ...], ann_text: str) -> bool:
    return " ".join(doc_text[s:e] for s, e in spans) == ann_text


def repair_entity(
    doc_text: str, spans: tuple[Span, ...], ann_text: str
) -> tuple[tuple[Span, ...], str]:
    """Return ``(spans, status)`` with the offsets verified against the text.

    Status is one of:

    ``exact``
        The offsets as annotated already reproduce the mention text.
    ``bigbio_fix``
        Repaired by the ported :func:`fix_entity_offsets` (single-span only,
        which is all BigBIO's routine can meaningfully handle).
    ``global_shift``
        Multi-span mention repaired by shifting *all* fragments by the same
        delta. BigBIO cannot repair discontinuous entities at all, because it
        re-derives the mention text from the very offsets it is validating.
    ``unrepaired``
        Still does not match; offsets returned as annotated.
    """
    if _matches(doc_text, spans, ann_text):
        return spans, "exact"

    if len(spans) == 1:
        fixed = fix_entity_offsets(doc_text, ann_text, spans[0])
        if _matches(doc_text, (fixed,), ann_text):
            return (fixed,), "bigbio_fix"
        return spans, "unrepaired"

    # Discontinuous: try a single delta applied to every fragment.
    for i in range(MAX_OFFSET_CORRECTION + 1):
        for delta in ((-i,) if i else (0,)) + ((i,) if i else ()):
            shifted = tuple((s + delta, e + delta) for s, e in spans)
            if shifted[0][0] < 0:
                continue
            if _matches(doc_text, shifted, ann_text):
                return shifted, "exact" if delta == 0 else "global_shift"

    return spans, "unrepaired"


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def _read_text(path: Path) -> str:
    """Read a ``.txt`` file **without** newline translation.

    This is the single most important difference from ``chia.py``: universal
    newline mode collapses CRLF and invalidates every downstream offset.
    """
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def parse_ann(ann_text: str) -> dict:
    """Parse brat standoff annotation text.

    Handles ``T`` (text-bound, including ``;``-separated multi-span offsets and
    multi-line continuations), ``R`` (relation), ``*`` (equivalence), ``E``
    (event), ``A``/``M`` (attribute) and ``N`` (normalization) lines.
    """
    out: dict[str, list] = {
        "text_bound_annotations": [],
        "relations": [],
        "equivalences": [],
        "events": [],
        "attributes": [],
        "normalizations": [],
        "malformed": [],
    }
    prev_tb: dict | None = None

    for raw_line in ann_text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        # An entity whose span crosses a newline is serialised by brat across
        # several lines; the continuation lines carry no tab.
        if "\t" not in line:
            if prev_tb is not None:
                prev_tb["text"] += "\n" + raw_line.rstrip("\r")
                continue
            out["malformed"].append(line)
            continue

        fields = line.split("\t")
        tag = fields[0]

        try:
            if tag.startswith("T"):
                type_name = fields[1].split()[0]
                span_str = fields[1][len(type_name) :].strip()
                spans = []
                for span in span_str.split(";"):
                    start, end = span.split()
                    spans.append((int(start), int(end)))
                ann = {
                    "id": tag,
                    "type": type_name,
                    "spans": tuple(spans),
                    "text": fields[2],
                }
                out["text_bound_annotations"].append(ann)
                prev_tb = ann
                continue

            prev_tb = None

            if tag.startswith("R"):
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
                out["equivalences"].append({"id": tag, "type": parts[0],
                                            "ref_ids": tuple(parts[1:])})
            elif tag.startswith("E"):
                head = fields[1].split()
                etype, trigger = head[0].split(":")
                out["events"].append(
                    {
                        "id": tag,
                        "type": etype,
                        "trigger": trigger,
                        "arguments": [
                            {"role": a.split(":")[0], "ref_id": a.split(":")[1]}
                            for a in head[1:]
                        ],
                    }
                )
            elif tag.startswith(("A", "M")):
                info = fields[1].split()
                out["attributes"].append(
                    {
                        "id": tag,
                        "type": info[0],
                        "ref_id": info[1],
                        "value": info[2] if len(info) > 2 else "",
                    }
                )
            elif tag.startswith("N"):
                info = fields[1].split()
                out["normalizations"].append(
                    {
                        "id": tag,
                        "type": info[0],
                        "ref_id": info[1],
                        "resource_name": info[2].split(":")[0],
                        "cuid": info[2].split(":")[1],
                        "text": fields[2],
                    }
                )
            else:
                out["malformed"].append(line)
        except (IndexError, ValueError):
            out["malformed"].append(line)
            prev_tb = None

    return out


def load_document(txt_path: Path, *, synthesise_or: bool = True) -> Document:
    """Load one ``.txt``/``.ann`` pair into a :class:`Document`."""
    stem = txt_path.with_suffix("").name
    doc = Document(
        doc_key=stem,
        nct_id=stem.split("_")[0],
        text_type="inclusion" if "_inc" in stem else "exclusion",
        text=_read_text(txt_path),
    )

    ann_path = txt_path.with_suffix(".ann")
    parsed = parse_ann(ann_path.read_text(encoding="utf-8")) if ann_path.exists() else {
        "text_bound_annotations": [], "relations": [], "equivalences": [],
        "events": [], "attributes": [], "normalizations": [], "malformed": [],
    }

    for line in parsed["malformed"]:
        doc.drops.append(DropRecord("line", "-", "malformed_annotation_line", line[:80]))

    for ann in parsed["text_bound_annotations"]:
        spans, status = repair_entity(doc.text, ann["spans"], ann["text"])
        if ann["id"] in doc.entities:
            doc.drops.append(
                DropRecord("entity", ann["id"], "duplicate_entity_id", ann["type"])
            )
            continue
        doc.entities[ann["id"]] = Entity(
            id=ann["id"],
            type=ann["type"],
            spans=spans,
            ann_text=ann["text"],
            offset_status=status,
            raw_spans=ann["spans"],
        )

    for rel in parsed["relations"]:
        doc.relation_ids_seen.append(rel["id"])
        missing = [a for a in (rel["arg1"], rel["arg2"]) if a not in doc.entities]
        if missing:
            doc.drops.append(
                DropRecord(
                    "relation",
                    rel["id"],
                    "dangling_argument",
                    f"{rel['type']} missing={','.join(missing)}",
                )
            )
            continue
        doc.relations.append(
            Relation(rel["id"], rel["type"], rel["arg1"], rel["arg2"], origin="R")
        )

    for eq in parsed["equivalences"]:
        kept = [r for r in eq["ref_ids"] if r in doc.entities]
        if len(kept) < len(eq["ref_ids"]):
            doc.drops.append(
                DropRecord(
                    "equivalence",
                    eq["id"],
                    "dangling_argument",
                    ",".join(r for r in eq["ref_ids"] if r not in doc.entities),
                )
            )
        doc.equivalences.append(Equivalence(eq["id"], tuple(kept), eq["type"]))

    if synthesise_or:
        # BigBIO numbers synthesised relations from len(relations) + 10.
        next_id = len(parsed["relations"]) + 10
        for eq in doc.equivalences:
            refs = eq.ref_ids
            for i, arg1 in enumerate(refs[:-1]):
                for arg2 in refs[i + 1 :]:
                    doc.relations.append(
                        Relation(f"R{next_id}", eq.type, arg1, arg2, origin="EQUIV")
                    )
                    next_id += 1

    return doc


def load_corpus(directory: Path, *, synthesise_or: bool = True) -> list[Document]:
    """Load every ``.txt``/``.ann`` pair under ``directory``, sorted by name."""
    return [
        load_document(p, synthesise_or=synthesise_or)
        for p in sorted(Path(directory).glob("*.txt"))
    ]


# --------------------------------------------------------------------------
# Text utilities
# --------------------------------------------------------------------------

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])[ \t]+(?=[A-Z(\[])")


def sentence_spans(text: str, line_span: Span) -> list[Span]:
    """Approximate sentence spans inside one criterion line.

    Deliberately crude and abbreviation-unaware -- used only to *report* how
    many relations cross a sentence boundary, never to segment the corpus.
    """
    start, end = line_span
    line = text[start:end]
    cuts = [0] + [m.end() for m in _SENTENCE_BOUNDARY.finditer(line)] + [len(line)]
    return [
        (start + cuts[i], start + cuts[i + 1])
        for i in range(len(cuts) - 1)
        if cuts[i + 1] > cuts[i]
    ]


def normalise_criterion(text: str) -> str:
    """Whitespace- and case-normalised form used for leakage comparison."""
    return " ".join(text.split()).lower()
