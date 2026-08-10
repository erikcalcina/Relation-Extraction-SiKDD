# Chia corpus — Phase 1 profile report

Read-only profiling of the Chia clinical-trial eligibility-criteria corpus, produced ahead of relation-extraction dataset construction. **Nothing has been converted or split.**

## Headline findings

1. **There is no usable drug→dose relation in Chia.** `Drug`→`Has_value`→`Value` occurs **12 times** in the whole corpus. The larger candidates — `Has_multiplier` (228) and `Has_qualifier` (259) — mix dose with frequency, duration and route. Your two-document reading was correct and the corpus confirms it. **This blocks the drug arm of the study (§2, D1).**

2. **The test→result side is solid**: `Measurement`→`Has_value`→`Value` = **2,799**, plus 752 for `Person` (age criteria).

3. **The corpus offsets are not broken.** The reputation is an artifact of reading the files with newline translation: 1,603 of 2,000 `.txt` files use CRLF, and Python's universal-newline mode silently deletes one character per preceding line. Read raw (`newline=""`), **99.97% of offsets are exactly correct**; read the way `chia.py` does, only 41.9% are. BigBIO's `_fix_entity_offsets` is a ±100-character search that repairs a bug the loader itself introduces — and it cannot repair discontinuous entities at all, because it re-derives the mention text from the same offsets it is checking.

4. **`load_dataset` does run here** (`datasets==2.19.0` + `trust_remote_code`), so it was diffed as a second source. Entities agree exactly — 40,976, type for type. Relations do not: the loader returns 19,309 where the raw files hold 34,719. It loses 221 `Has_context` to the `"HAS_CONTEXT "` trailing-space typo (trap 2) and **all 15,189 synthesised `OR` relations to a third bug you hadn't catalogued** — an id-prefix mismatch at `chia.py:365` that makes the equivalence guard never match. That is 15,410 relations, 44.4% of the corpus. (A further 72 go to argument filtering — trap 3 — but those are dropped here too, correctly.) Reason enough on its own to parse the raw files.

5. **`OR` dominates if expanded pairwise**: 5,015 `*` lines become 15,189 relations, 43.7% of the corpus. This single choice accounts for the entire gap against the published relation total (§2, D2).

6. **One criterion is the right instance unit**: only **6** of 34,719 relations cross a criterion boundary (0.02%).

7. **1,781 discontinuous entities (4.35%)** and **4,181 overlapping entity pairs** — both must be handled explicitly, and both are research decisions (§2, D3/D4).

## 0. Provenance

| Item | Value |
| :--- | :--- |
| Source | `bigbio/chia` → `data/*.zip` (byte-identical mirror of figshare 10.6084/m9.figshare.11855817) |
| `chia_with_scope.zip` MD5 | `54b33164da88da88e47b2a009e150a82` — matches published `54b33164da88da88e47b2a009e150a82` |
| `chia_without_scope.zip` MD5 | `e5b4578b11139b80d64aeca0cc4a76b8` — matches published `e5b4578b11139b80d64aeca0cc4a76b8` |
| Primary variant profiled | **without_scope** (trap 8 default) |
| Parser | `src/relation_extraction/data/chia_brat.py` (own code; two routines ported from `chia.py`) |
| Seed | `20260810` (no stochastic step in Phase 1) |
| License | CC-BY-4.0 |

## 1.1 Reconciliation against published totals

| Quantity | This parse | Published | Δ |
| :--- | ---: | ---: | ---: |
| Trials (distinct NCT IDs) | 1000 | 1000 | match |
| Documents (files) | 2000 | 2000 | match |
| Criteria (non-empty lines) | 12409 | 12409 | match |
| Entities (in-schema) | 40976 | 41487 | -511 |
| Distinct entity types (in-schema) | 15 | 15 | match |
| Relations (in-schema, incl. synthesised OR) | 34719 | 25017 | +9702 |
| Distinct relation types (in-schema) | 11 | 12 | -1 |

Four of seven figures reconcile exactly. The two that do not are explained below; both are properties of the released files, not of this parse.

#### Discrepancy 1 — relations: the `OR` counting rule (±10k)

`OR` is not a brat relation. It is encoded as `*` equivalence *lines*, each listing an unordered set of co-referent entities, and the count depends entirely on how you expand them:

| Counting rule | Relations | vs published 25,017 |
| :--- | ---: | ---: |
| All `R` lines (20,153) + one relation per `*` line (5,015) | 25,168 | +151 |
| In-schema `R` lines (19,530) + one per `*` line | 24,545 | -472 |
| In-schema `R` lines + **pairwise** expansion of `*` (BigBIO's rule, used here) | 34,719 | +9702 |

The published 25,017 is closest to *one relation per `*` line* (25,168, +0.6%), so the paper almost certainly did **not** expand equivalences pairwise. BigBIO does, which inflates `OR` from 5,015 to 15,189 — **43.75% of every relation in the corpus becomes a synthesised `OR`**. This is a decision, not a fact: see §2.

Not every `*` line is an `OR`, either: `OR` × 5,011, `NOT` × 4.

#### Discrepancy 2 — entities: 511 fewer than published (−1.23%)

- Every one of the **44,616** `T` lines in the release is accounted for: 40,976 in-schema + 3,640 out-of-schema.
- Both corpus variants contain **exactly the same 40,976** non-`Scope` entities, so this is not a with/without-scope artifact.
- No entity is lost to parsing: there are 0 malformed `T` lines and 0 duplicate `T` ids.
- Conclusion: the released `.ann` files simply contain 511 fewer in-schema entities than the paper reports. The paper's counts were evidently taken from a different (earlier or post-processed) snapshot. Unrecoverable from the release, and immaterial at 1.2%.

### with_scope variant, for comparison

| Quantity | without_scope | with_scope |
| :--- | ---: | ---: |
| Entities (in-schema) | 40976 | 45230 |
| Entity types | 15 | 16 |
| `Scope` entities | 0 | 4254 |
| Relations (in-schema) | 34719 | 33830 |
| Relation types | 11 | 12 |
| `HAS_SCOPE` relations | 0 | 1513 |

Entity counts excluding `Scope`: without_scope **40,976**, with_scope **40,976**.

### Entity type distribution (in-schema)

| Entity type | Count | % of entities |
| :--- | ---: | ---: |
| Condition | 12,039 | 29.38% |
| Qualifier | 4,157 | 10.14% |
| Value | 4,002 | 9.77% |
| Drug | 3,801 | 9.28% |
| Procedure | 3,595 | 8.77% |
| Temporal | 3,580 | 8.74% |
| Measurement | 3,305 | 8.07% |
| Person | 1,666 | 4.07% |
| Observation | 1,216 | 2.97% |
| Reference_point | 934 | 2.28% |
| Negation | 843 | 2.06% |
| Multiplier | 671 | 1.64% |
| Mood | 616 | 1.50% |
| Device | 386 | 0.94% |
| Visit | 165 | 0.40% |

### Relation type distribution (in-schema)

| Relation type | Annotated (`R` lines) | Synthesised (`*` lines) | Total |
| :--- | ---: | ---: | ---: |
| OR | 7 | 15,189 | 15,196 |
| HAS_VALUE | 3,806 | 0 | 3,806 |
| AND | 3,677 | 0 | 3,677 |
| HAS_QUALIFIER | 3,535 | 0 | 3,535 |
| HAS_TEMPORAL | 3,331 | 0 | 3,331 |
| SUBSUMES | 2,050 | 0 | 2,050 |
| HAS_INDEX | 905 | 0 | 905 |
| HAS_NEGATION | 843 | 0 | 843 |
| HAS_MULTIPLIER | 632 | 0 | 632 |
| HAS_MOOD | 523 | 0 | 523 |
| HAS_CONTEXT | 221 | 0 | 221 |

Origin totals: **19,530** annotated, **15,189** synthesised from `*` equivalence lines (trap 9).

### Everything dropped, with reasons

| Reason | Count |
| :--- | ---: |
| entity: type not in 16-type schema (Non-query-able) | 786 |
| entity: type not in 16-type schema (Parsing_Error) | 608 |
| relation: type not in 12-type schema (multi) | 508 |
| entity: type not in 16-type schema (Post-eligibility) | 485 |
| entity: type not in 16-type schema (Non-representable) | 304 |
| entity: type not in 16-type schema (Undefined_semantics) | 265 |
| entity: type not in 16-type schema (Informed_consent) | 258 |
| entity: type not in 16-type schema (Subjective_judgement) | 241 |
| entity: type not in 16-type schema (Pregnancy_considerations) | 190 |
| entity: type not in 16-type schema (Context_Error) | 143 |
| entity: type not in 16-type schema (Line) | 100 |
| entity: type not in 16-type schema (Competing_trial) | 96 |
| relation: argument is an out-of-schema entity | 86 |
| entity: type not in 16-type schema (Grammar_Error) | 82 |
| entity: type not in 16-type schema (Not_a_criteria) | 76 |
| relation: type not in 12-type schema (causal) | 37 |
| entity: type not in 16-type schema (Intoxication_considerations) | 5 |
| relation: type not in 12-type schema (NOT) | 4 |
| relation: type not in 12-type schema (v-AND) | 4 |
| entity: type not in 16-type schema (c-Requires_causality) | 1 |

Total dropped records: **4,279** (3,640 out-of-schema entities and the relations that touch them).

### Out-of-schema entity types present in the raw data

| Type | Count | Declared in `annotation.conf`? |
| :--- | ---: | :--- |
| Non-query-able | 786 | yes |
| Parsing_Error | 608 | **no** |
| Post-eligibility | 485 | yes |
| Non-representable | 304 | yes |
| Undefined_semantics | 265 | **no** |
| Informed_consent | 258 | yes |
| Subjective_judgement | 241 | **no** |
| Pregnancy_considerations | 190 | yes |
| Context_Error | 143 | **no** |
| Line | 100 | yes |
| Competing_trial | 96 | yes |
| Grammar_Error | 82 | **no** |
| Not_a_criteria | 76 | **no** |
| Intoxication_considerations | 5 | yes |
| c-Requires_causality | 1 | **no** |

These are annotator-workflow labels (error tags, out-of-scope markers), not clinical entities. `Line` and the seven `!ERROR` types are declared in `annotation.conf`; the rest are undeclared and were evidently added ad hoc during annotation. None belongs in a relation-extraction dataset, but they do consume text spans and they do appear as relation arguments — which is why 86 otherwise well-formed relations are dropped along with them (that figure counts both `R`-line and `*`-derived relations; the loader-comparison table below counts only `R`-line ones, because the loader never reaches the others).

### Cross-check against `load_dataset` (traps 2 and 3, plus a third bug)

`load_dataset('bigbio/chia', 'chia_without_scope_source', trust_remote_code=True)` **does** run here under `datasets==2.19.0` (v3+ refuses script-based datasets outright), so it was loaded as a second source and diffed. Actual loader output vs this parse:

| Quantity | `load_dataset` | This parse | Δ |
| :--- | ---: | ---: | ---: |
| Documents | 2,000 | 2,000 | match |
| Entities | 40,976 | 40,976 | match |
| Entity types | 15 | 15 | match |
| Relations | 19,309 | 34,719 | +15410 |
| Relation types | 10 | 11 | +1 |

**Entities agree exactly, type by type, all 15 types** — which confirms both sides are reading the same bytes and that the divergence is purely in relation handling. Per relation type:

| Relation type | `load_dataset` | This parse | Δ | Cause of divergence |
| :--- | :--- | :--- | :--- | :--- |
| OR | 7 | 15,196 | +15189 | **id-prefix bug** at `chia.py:365` — see below |
| HAS_VALUE | 3,806 | 3,806 | match |  |
| AND | 3,677 | 3,677 | match |  |
| HAS_QUALIFIER | 3,535 | 3,535 | match |  |
| HAS_TEMPORAL | 3,331 | 3,331 | match |  |
| SUBSUMES | 2,050 | 2,050 | match |  |
| HAS_INDEX | 905 | 905 | match |  |
| HAS_NEGATION | 843 | 843 | match |  |
| HAS_MULTIPLIER | 632 | 632 | match |  |
| HAS_MOOD | 523 | 523 | match |  |
| HAS_CONTEXT | 0 | 221 | +221 | **trap 2** — `"HAS_CONTEXT "` trailing space in `_RELATION_TYPES`; every one is dropped |

A third silent-drop mechanism, not previously catalogued: `chia.py` builds `entity_ids` with document-prefixed keys (`chia.py:316-317`, `example_prefix + entity_ann["id"]`), but the equivalence loop tests the **bare** `T` id against it (`chia.py:365`, `if arg1 not in entity_ids`). The guard therefore never passes, and *every* `OR` relation synthesised from a `*` line is discarded — while the very next statement prefixes the same ids when constructing the relation (`chia.py:371-372`), which is what makes it unambiguously a bug rather than a design choice. Empirically the loader yields 7 `OR` relations (the literal `R`-line ones) and zero from the 5,015 `*` lines.

Simulating `chia.py`'s three filters against this parse reproduces its output exactly:

| Quantity | Simulated `chia.py` | Actual `load_dataset` | This parse |
| :--- | ---: | ---: | ---: |
| Entities | 40,976 | 40,976 | 40,976 |
| Relations | 19,309 | 19,309 | 34,719 |

Relations this parse keeps and `load_dataset` does **not** — i.e. the real cost of using the loader:

| Lost relations | Count | Mechanism |
| :--- | ---: | :--- |
| `Has_context` | 221 | trap 2 — trailing space in `_RELATION_TYPES` |
| `OR` synthesised from `*` lines | 15,189 | id-prefix bug at `chia.py:365` |
| **Total** | **15,410** | **44.38% of all in-schema relations** |

Dropped by **both** implementations, and correctly so: 549 relations of out-of-schema type (`multi`, `causal`, `v-AND`) and 72 whose argument is an out-of-schema entity. Breakdown of `chia.py`'s own filters (raw counts, before the argument check, which is why `Has_context` reads 223 here and 221 above):

| Relation type | Dropped: type not in `_RELATION_TYPES` | Dropped: argument filtered out |
| :--- | ---: | ---: |
| multi | 508 | 0 |
| Has_context | 223 | 0 |
| AND | 0 | 38 |
| causal | 37 | 0 |
| Has_temporal | 0 | 13 |
| Subsumes | 0 | 11 |
| Has_negation | 0 | 6 |
| v-AND | 4 | 0 |
| Has_mood | 0 | 4 |

**Relation-id gaps in the raw files** (trap 3): `R<n>` ids are non-contiguous in **41** of 2,000 documents, **57** ids missing in total (0.03 per document). These are annotation-time deletions in the source files, *not* loader drops — nothing is recoverable from them and no relation is lost by this parse on their account.

### Offset integrity (trap 4)

**The offsets in the release are not broken.** Their reputation comes from how they are read. 1,603 of 2,000 `.txt` files use CRLF line endings, and Python's default universal-newline mode rewrites `\r\n` -> `\n`, deleting one character per preceding line and shifting every subsequent offset left. `chia.py` reads via `Path.open()` and so hits this on every CRLF file. Same offsets, same entities, two ways of reading the text:

| How the `.txt` is read | Entity offsets exactly reproducing the mention text |
| :--- | ---: |
| `Path.open()` — universal newlines (what `chia.py` does) | 17,154 / 40,976 (41.86%) |
| `open(newline="")` — raw (what this parser does) | 40,964 / 40,976 (99.97%) |

`_fix_entity_offsets` is therefore repairing damage the loader inflicts on itself, with a ±100-character text search that is both unnecessary and unsafe: it will happily relocate a short mention (`+`, `1`, `no`) to a coincidental match elsewhere in the document. It has been ported and is retained here, but as a **fallback for the residual 12 entities only**, not as the primary mechanism. Note also that BigBIO's routine cannot repair a discontinuous entity at all: for multi-span mentions it first re-derives the mention text *from the very offsets it is about to validate*, so the check is guaranteed to pass. This parser instead repairs multi-span entities by searching for a single global fragment shift.

Final offset status after parsing (raw read + fallback repair):

| Offset status | Count | % of entities |
| :--- | ---: | ---: |
| `exact` | 40,964 | 99.97% |
| `bigbio_fix` | 9 | 0.02% |
| `unrepaired` | 3 | 0.01% |

The 3 unrepaired entities are carried through with their annotated offsets and flagged; Phase 2's `text[start:end] == entity_text` assertion will surface them again.

## 1.2 Relation signature table

Joint distribution of `(arg1_type, relation_type, arg2_type)` over all in-schema relations. Full table, nothing truncated.

| # | arg1 type | relation | arg2 type | Count | % of relations |
| ---: | :--- | :--- | :--- | ---: | ---: |
| 1 | Condition | OR | Condition | 7,341 | 21.14% |
| 2 | Drug | OR | Drug | 2,885 | 8.31% |
| 3 | Measurement | HAS_VALUE | Value | 2,799 | 8.06% |
| 4 | Condition | HAS_QUALIFIER | Qualifier | 2,445 | 7.04% |
| 5 | Condition | HAS_TEMPORAL | Temporal | 1,323 | 3.81% |
| 6 | Temporal | HAS_INDEX | Reference_point | 889 | 2.56% |
| 7 | Procedure | HAS_TEMPORAL | Temporal | 857 | 2.47% |
| 8 | Person | HAS_VALUE | Value | 752 | 2.17% |
| 9 | Qualifier | OR | Qualifier | 688 | 1.98% |
| 10 | Procedure | OR | Procedure | 655 | 1.89% |
| 11 | Condition | AND | Drug | 645 | 1.86% |
| 12 | Condition | SUBSUMES | Condition | 625 | 1.80% |
| 13 | Measurement | OR | Measurement | 620 | 1.79% |
| 14 | Drug | HAS_TEMPORAL | Temporal | 532 | 1.53% |
| 15 | Condition | AND | Procedure | 514 | 1.48% |
| 16 | Procedure | HAS_QUALIFIER | Qualifier | 465 | 1.34% |
| 17 | Condition | AND | Condition | 459 | 1.32% |
| 18 | Condition | AND | Measurement | 408 | 1.18% |
| 19 | Condition | HAS_NEGATION | Negation | 380 | 1.09% |
| 20 | Procedure | AND | Condition | 315 | 0.91% |
| 21 | Condition | OR | Procedure | 313 | 0.90% |
| 22 | Measurement | HAS_TEMPORAL | Temporal | 286 | 0.82% |
| 23 | Procedure | HAS_MOOD | Mood | 273 | 0.79% |
| 24 | Drug | HAS_QUALIFIER | Qualifier | 259 | 0.75% |
| 25 | Drug | SUBSUMES | Drug | 247 | 0.71% |
| 26 | Condition | SUBSUMES | Measurement | 236 | 0.68% |
| 27 | Drug | HAS_MULTIPLIER | Multiplier | 228 | 0.66% |
| 28 | Measurement | SUBSUMES | Measurement | 206 | 0.59% |
| 29 | Device | OR | Device | 203 | 0.58% |
| 30 | Procedure | AND | Drug | 198 | 0.57% |
| 31 | Person | OR | Person | 196 | 0.56% |
| 32 | Observation | OR | Observation | 189 | 0.54% |
| 33 | Condition | HAS_MULTIPLIER | Multiplier | 182 | 0.52% |
| 34 | Procedure | OR | Condition | 176 | 0.51% |
| 35 | Condition | HAS_MOOD | Mood | 167 | 0.48% |
| 36 | Observation | HAS_TEMPORAL | Temporal | 166 | 0.48% |
| 37 | Condition | OR | Measurement | 165 | 0.48% |
| 38 | Condition | OR | Observation | 155 | 0.45% |
| 39 | Value | OR | Value | 153 | 0.44% |
| 40 | Measurement | HAS_QUALIFIER | Qualifier | 152 | 0.44% |
| 41 | Measurement | OR | Condition | 150 | 0.43% |
| 42 | Procedure | HAS_NEGATION | Negation | 148 | 0.43% |
| 43 | Procedure | SUBSUMES | Procedure | 134 | 0.39% |
| 44 | Drug | HAS_NEGATION | Negation | 125 | 0.36% |
| 45 | Procedure | AND | Procedure | 125 | 0.36% |
| 46 | Temporal | OR | Temporal | 118 | 0.34% |
| 47 | Condition | HAS_CONTEXT | Observation | 112 | 0.32% |
| 48 | Condition | OR | Drug | 111 | 0.32% |
| 49 | Observation | HAS_VALUE | Value | 108 | 0.31% |
| 50 | Procedure | HAS_MULTIPLIER | Multiplier | 108 | 0.31% |
| 51 | Observation | HAS_QUALIFIER | Qualifier | 95 | 0.27% |
| 52 | Drug | OR | Procedure | 91 | 0.26% |
| 53 | Observation | OR | Condition | 90 | 0.26% |
| 54 | Value | SUBSUMES | Value | 76 | 0.22% |
| 55 | Procedure | HAS_VALUE | Value | 71 | 0.20% |
| 56 | Observation | HAS_NEGATION | Negation | 70 | 0.20% |
| 57 | Procedure | OR | Drug | 69 | 0.20% |
| 58 | Drug | AND | Drug | 68 | 0.20% |
| 59 | Device | OR | Condition | 64 | 0.18% |
| 60 | Drug | OR | Condition | 61 | 0.18% |
| 61 | Drug | AND | Condition | 60 | 0.17% |
| 62 | Procedure | AND | Measurement | 59 | 0.17% |
| 63 | Person | AND | Condition | 58 | 0.17% |
| 64 | Qualifier | HAS_TEMPORAL | Temporal | 55 | 0.16% |
| 65 | Qualifier | HAS_NEGATION | Negation | 53 | 0.15% |
| 66 | Measurement | AND | Condition | 53 | 0.15% |
| 67 | Qualifier | SUBSUMES | Qualifier | 51 | 0.15% |
| 68 | Observation | HAS_MULTIPLIER | Multiplier | 51 | 0.15% |
| 69 | Procedure | SUBSUMES | Drug | 50 | 0.14% |
| 70 | Procedure | HAS_CONTEXT | Observation | 49 | 0.14% |
| 71 | Condition | OR | Device | 49 | 0.14% |
| 72 | Condition | HAS_VALUE | Value | 46 | 0.13% |
| 73 | Observation | AND | Procedure | 46 | 0.13% |
| 74 | Qualifier | SUBSUMES | Measurement | 45 | 0.13% |
| 75 | Measurement | OR | Procedure | 44 | 0.13% |
| 76 | Condition | SUBSUMES | Procedure | 43 | 0.12% |
| 77 | Drug | HAS_MOOD | Mood | 39 | 0.11% |
| 78 | Procedure | AND | Visit | 38 | 0.11% |
| 79 | Device | HAS_QUALIFIER | Qualifier | 38 | 0.11% |
| 80 | Temporal | AND | Condition | 37 | 0.11% |
| 81 | Measurement | AND | Measurement | 37 | 0.11% |
| 82 | Drug | OR | Observation | 36 | 0.10% |
| 83 | Mood | OR | Mood | 34 | 0.10% |
| 84 | Observation | AND | Condition | 34 | 0.10% |
| 85 | Person | AND | Measurement | 32 | 0.09% |
| 86 | Person | HAS_TEMPORAL | Temporal | 31 | 0.09% |
| 87 | Observation | HAS_MOOD | Mood | 30 | 0.09% |
| 88 | Measurement | AND | Procedure | 30 | 0.09% |
| 89 | Procedure | AND | Device | 30 | 0.09% |
| 90 | Observation | AND | Drug | 28 | 0.08% |
| 91 | Qualifier | AND | Condition | 28 | 0.08% |
| 92 | Temporal | SUBSUMES | Temporal | 28 | 0.08% |
| 93 | Drug | OR | Device | 27 | 0.08% |
| 94 | Condition | SUBSUMES | Drug | 27 | 0.08% |
| 95 | Procedure | OR | Device | 27 | 0.08% |
| 96 | Measurement | HAS_MULTIPLIER | Multiplier | 26 | 0.07% |
| 97 | Measurement | AND | Person | 25 | 0.07% |
| 98 | Person | AND | Procedure | 24 | 0.07% |
| 99 | Value | HAS_TEMPORAL | Temporal | 24 | 0.07% |
| 100 | Condition | OR | Person | 24 | 0.07% |
| 101 | Device | SUBSUMES | Device | 24 | 0.07% |
| 102 | Qualifier | OR | Condition | 24 | 0.07% |
| 103 | Condition | AND | Device | 23 | 0.07% |
| 104 | Qualifier | AND | Procedure | 23 | 0.07% |
| 105 | Device | OR | Procedure | 23 | 0.07% |
| 106 | Person | OR | Condition | 22 | 0.06% |
| 107 | Person | SUBSUMES | Person | 22 | 0.06% |
| 108 | Observation | AND | Measurement | 21 | 0.06% |
| 109 | Procedure | OR | Observation | 21 | 0.06% |
| 110 | Value | HAS_QUALIFIER | Qualifier | 20 | 0.06% |
| 111 | Qualifier | HAS_QUALIFIER | Qualifier | 19 | 0.05% |
| 112 | Device | HAS_TEMPORAL | Temporal | 19 | 0.05% |
| 113 | Multiplier | OR | Multiplier | 18 | 0.05% |
| 114 | Condition | OR | Qualifier | 18 | 0.05% |
| 115 | Device | HAS_NEGATION | Negation | 18 | 0.05% |
| 116 | Observation | SUBSUMES | Condition | 17 | 0.05% |
| 117 | Device | OR | Drug | 17 | 0.05% |
| 118 | Value | SUBSUMES | Measurement | 16 | 0.05% |
| 119 | Person | HAS_CONTEXT | Observation | 16 | 0.05% |
| 120 | Observation | OR | Drug | 16 | 0.05% |
| 121 | Observation | SUBSUMES | Observation | 16 | 0.05% |
| 122 | Mood | HAS_NEGATION | Negation | 16 | 0.05% |
| 123 | Temporal | HAS_QUALIFIER | Qualifier | 16 | 0.05% |
| 124 | Procedure | OR | Measurement | 16 | 0.05% |
| 125 | Mood | HAS_TEMPORAL | Temporal | 15 | 0.04% |
| 126 | Temporal | OR | Mood | 15 | 0.04% |
| 127 | Condition | AND | Person | 15 | 0.04% |
| 128 | Person | HAS_QUALIFIER | Qualifier | 15 | 0.04% |
| 129 | Qualifier | SUBSUMES | Condition | 15 | 0.04% |
| 130 | Observation | HAS_CONTEXT | Observation | 15 | 0.04% |
| 131 | Qualifier | AND | Drug | 15 | 0.04% |
| 132 | Qualifier | HAS_MULTIPLIER | Multiplier | 14 | 0.04% |
| 133 | Condition | OR | Temporal | 14 | 0.04% |
| 134 | Visit | OR | Visit | 14 | 0.04% |
| 135 | Observation | SUBSUMES | Measurement | 14 | 0.04% |
| 136 | Measurement | HAS_NEGATION | Negation | 13 | 0.04% |
| 137 | Multiplier | SUBSUMES | Multiplier | 13 | 0.04% |
| 138 | Drug | AND | Procedure | 12 | 0.03% |
| 139 | Temporal | OR | Qualifier | 12 | 0.03% |
| 140 | Observation | OR | Procedure | 12 | 0.03% |
| 141 | Drug | HAS_VALUE | Value | 12 | 0.03% |
| 142 | Temporal | AND | Procedure | 11 | 0.03% |
| 143 | Procedure | SUBSUMES | Measurement | 11 | 0.03% |
| 144 | Temporal | HAS_TEMPORAL | Temporal | 11 | 0.03% |
| 145 | Temporal | AND | Drug | 11 | 0.03% |
| 146 | Procedure | SUBSUMES | Condition | 11 | 0.03% |
| 147 | Qualifier | AND | Qualifier | 11 | 0.03% |
| 148 | Person | AND | Person | 11 | 0.03% |
| 149 | Measurement | OR | Device | 11 | 0.03% |
| 150 | Condition | SUBSUMES | Qualifier | 10 | 0.03% |
| 151 | Drug | HAS_CONTEXT | Observation | 10 | 0.03% |
| 152 | Measurement | OR | Observation | 10 | 0.03% |
| 153 | Qualifier | HAS_VALUE | Value | 9 | 0.03% |
| 154 | Value | AND | Procedure | 9 | 0.03% |
| 155 | Temporal | OR | Condition | 9 | 0.03% |
| 156 | Observation | AND | Visit | 9 | 0.03% |
| 157 | Value | AND | Condition | 8 | 0.02% |
| 158 | Reference_point | AND | Procedure | 8 | 0.02% |
| 159 | Qualifier | AND | Measurement | 8 | 0.02% |
| 160 | Measurement | OR | Value | 8 | 0.02% |
| 161 | Reference_point | AND | Drug | 8 | 0.02% |
| 162 | Condition | SUBSUMES | Observation | 8 | 0.02% |
| 163 | Measurement | OR | Drug | 8 | 0.02% |
| 164 | Device | OR | Observation | 8 | 0.02% |
| 165 | Mood | OR | Observation | 7 | 0.02% |
| 166 | Qualifier | OR | Procedure | 7 | 0.02% |
| 167 | Condition | SUBSUMES | Temporal | 7 | 0.02% |
| 168 | Temporal | OR | Procedure | 7 | 0.02% |
| 169 | Person | AND | Device | 7 | 0.02% |
| 170 | Observation | AND | Device | 7 | 0.02% |
| 171 | Qualifier | OR | Temporal | 7 | 0.02% |
| 172 | Observation | AND | Person | 7 | 0.02% |
| 173 | Multiplier | AND | Condition | 6 | 0.02% |
| 174 | Reference_point | OR | Reference_point | 6 | 0.02% |
| 175 | Value | HAS_NEGATION | Negation | 6 | 0.02% |
| 176 | Temporal | OR | Observation | 6 | 0.02% |
| 177 | Visit | HAS_TEMPORAL | Temporal | 6 | 0.02% |
| 178 | Temporal | OR | Reference_point | 6 | 0.02% |
| 179 | Multiplier | OR | Qualifier | 6 | 0.02% |
| 180 | Visit | AND | Condition | 6 | 0.02% |
| 181 | Multiplier | AND | Measurement | 6 | 0.02% |
| 182 | Multiplier | HAS_TEMPORAL | Temporal | 6 | 0.02% |
| 183 | Measurement | HAS_CONTEXT | Observation | 6 | 0.02% |
| 184 | Procedure | OR | Temporal | 6 | 0.02% |
| 185 | Qualifier | SUBSUMES | Value | 6 | 0.02% |
| 186 | Visit | HAS_CONTEXT | Observation | 6 | 0.02% |
| 187 | Device | HAS_MULTIPLIER | Multiplier | 6 | 0.02% |
| 188 | Person | HAS_MULTIPLIER | Multiplier | 6 | 0.02% |
| 189 | Qualifier | OR | Drug | 5 | 0.01% |
| 190 | Condition | AND | Visit | 5 | 0.01% |
| 191 | Qualifier | SUBSUMES | Procedure | 5 | 0.01% |
| 192 | Condition | SUBSUMES | Person | 5 | 0.01% |
| 193 | Person | AND | Visit | 5 | 0.01% |
| 194 | Condition | SUBSUMES | Value | 5 | 0.01% |
| 195 | Procedure | HAS_INDEX | Reference_point | 5 | 0.01% |
| 196 | Multiplier | HAS_QUALIFIER | Qualifier | 5 | 0.01% |
| 197 | Temporal | HAS_NEGATION | Negation | 5 | 0.01% |
| 198 | Person | OR | Observation | 5 | 0.01% |
| 199 | Multiplier | HAS_NEGATION | Negation | 5 | 0.01% |
| 200 | Procedure | OR | Qualifier | 4 | 0.01% |
| 201 | Observation | OR | Mood | 4 | 0.01% |
| 202 | Value | AND | Drug | 4 | 0.01% |
| 203 | Value | OR | Condition | 4 | 0.01% |
| 204 | Multiplier | HAS_MULTIPLIER | Multiplier | 4 | 0.01% |
| 205 | Person | HAS_NEGATION | Negation | 4 | 0.01% |
| 206 | Visit | AND | Visit | 4 | 0.01% |
| 207 | Mood | OR | Condition | 4 | 0.01% |
| 208 | Value | SUBSUMES | Person | 4 | 0.01% |
| 209 | Procedure | SUBSUMES | Temporal | 4 | 0.01% |
| 210 | Observation | OR | Temporal | 4 | 0.01% |
| 211 | Condition | SUBSUMES | Device | 4 | 0.01% |
| 212 | Measurement | HAS_MOOD | Mood | 4 | 0.01% |
| 213 | Device | AND | Condition | 4 | 0.01% |
| 214 | Device | AND | Device | 4 | 0.01% |
| 215 | Drug | HAS_INDEX | Reference_point | 4 | 0.01% |
| 216 | Drug | OR | Measurement | 4 | 0.01% |
| 217 | Value | AND | Person | 4 | 0.01% |
| 218 | Device | OR | Person | 4 | 0.01% |
| 219 | Observation | SUBSUMES | Procedure | 3 | 0.01% |
| 220 | Temporal | HAS_VALUE | Value | 3 | 0.01% |
| 221 | Negation | OR | Qualifier | 3 | 0.01% |
| 222 | Mood | AND | Procedure | 3 | 0.01% |
| 223 | Measurement | SUBSUMES | Condition | 3 | 0.01% |
| 224 | Drug | OR | Visit | 3 | 0.01% |
| 225 | Mood | SUBSUMES | Condition | 3 | 0.01% |
| 226 | Qualifier | SUBSUMES | Multiplier | 3 | 0.01% |
| 227 | Condition | OR | Mood | 3 | 0.01% |
| 228 | Mood | OR | Procedure | 3 | 0.01% |
| 229 | Measurement | SUBSUMES | Procedure | 3 | 0.01% |
| 230 | Reference_point | AND | Condition | 3 | 0.01% |
| 231 | Value | HAS_INDEX | Reference_point | 3 | 0.01% |
| 232 | Procedure | SUBSUMES | Observation | 3 | 0.01% |
| 233 | Person | AND | Observation | 3 | 0.01% |
| 234 | Mood | HAS_QUALIFIER | Qualifier | 3 | 0.01% |
| 235 | Drug | AND | Device | 3 | 0.01% |
| 236 | Temporal | HAS_MOOD | Mood | 3 | 0.01% |
| 237 | Measurement | AND | Drug | 3 | 0.01% |
| 238 | Drug | AND | Measurement | 3 | 0.01% |
| 239 | Device | HAS_VALUE | Value | 3 | 0.01% |
| 240 | Measurement | SUBSUMES | Qualifier | 3 | 0.01% |
| 241 | Multiplier | HAS_MOOD | Mood | 3 | 0.01% |
| 242 | Condition | HAS_INDEX | Reference_point | 3 | 0.01% |
| 243 | Observation | SUBSUMES | Device | 3 | 0.01% |
| 244 | Temporal | HAS_CONTEXT | Observation | 2 | 0.01% |
| 245 | Qualifier | OR | Multiplier | 2 | 0.01% |
| 246 | Value | AND | Measurement | 2 | 0.01% |
| 247 | Value | OR | Procedure | 2 | 0.01% |
| 248 | Value | OR | Measurement | 2 | 0.01% |
| 249 | Value | HAS_MULTIPLIER | Multiplier | 2 | 0.01% |
| 250 | Mood | AND | Drug | 2 | 0.01% |
| 251 | Drug | OR | Mood | 2 | 0.01% |
| 252 | Value | HAS_VALUE | Value | 2 | 0.01% |
| 253 | Qualifier | SUBSUMES | Temporal | 2 | 0.01% |
| 254 | Visit | OR | Drug | 2 | 0.01% |
| 255 | Temporal | OR | Drug | 2 | 0.01% |
| 256 | Mood | OR | Temporal | 2 | 0.01% |
| 257 | Person | OR | Measurement | 2 | 0.01% |
| 258 | Multiplier | OR | Temporal | 2 | 0.01% |
| 259 | Condition | SUBSUMES | Mood | 2 | 0.01% |
| 260 | Qualifier | HAS_CONTEXT | Observation | 2 | 0.01% |
| 261 | Negation | AND | Condition | 2 | 0.01% |
| 262 | Device | OR | Measurement | 2 | 0.01% |
| 263 | Device | HAS_CONTEXT | Observation | 2 | 0.01% |
| 264 | Condition | SUBSUMES | Multiplier | 2 | 0.01% |
| 265 | Device | HAS_MOOD | Mood | 2 | 0.01% |
| 266 | Multiplier | AND | Person | 2 | 0.01% |
| 267 | Drug | SUBSUMES | Condition | 2 | 0.01% |
| 268 | Observation | OR | Measurement | 2 | 0.01% |
| 269 | Observation | SUBSUMES | Temporal | 2 | 0.01% |
| 270 | Observation | OR | Device | 2 | 0.01% |
| 271 | Measurement | AND | Device | 2 | 0.01% |
| 272 | Measurement | SUBSUMES | Value | 2 | 0.01% |
| 273 | Temporal | HAS_MULTIPLIER | Multiplier | 2 | 0.01% |
| 274 | Device | AND | Procedure | 2 | 0.01% |
| 275 | Observation | OR | Person | 2 | 0.01% |
| 276 | Multiplier | SUBSUMES | Value | 2 | 0.01% |
| 277 | Multiplier | SUBSUMES | Drug | 2 | 0.01% |
| 278 | Visit | HAS_QUALIFIER | Qualifier | 2 | 0.01% |
| 279 | Multiplier | SUBSUMES | Measurement | 2 | 0.01% |
| 280 | Procedure | AND | Person | 2 | 0.01% |
| 281 | Drug | AND | Visit | 2 | 0.01% |
| 282 | Drug | OR | Person | 2 | 0.01% |
| 283 | Observation | AND | Observation | 2 | 0.01% |
| 284 | Person | OR | Procedure | 2 | 0.01% |
| 285 | Reference_point | SUBSUMES | Reference_point | 2 | 0.01% |
| 286 | Temporal | SUBSUMES | Condition | 2 | 0.01% |
| 287 | Procedure | AND | Reference_point | 2 | 0.01% |
| 288 | Value | AND | Temporal | 1 | 0.00% |
| 289 | Multiplier | AND | Procedure | 1 | 0.00% |
| 290 | Qualifier | OR | Value | 1 | 0.00% |
| 291 | Drug | OR | Value | 1 | 0.00% |
| 292 | Temporal | AND | Measurement | 1 | 0.00% |
| 293 | Temporal | OR | Negation | 1 | 0.00% |
| 294 | Visit | SUBSUMES | Visit | 1 | 0.00% |
| 295 | Mood | AND | Condition | 1 | 0.00% |
| 296 | Mood | AND | Visit | 1 | 0.00% |
| 297 | Negation | HAS_QUALIFIER | Qualifier | 1 | 0.00% |
| 298 | Condition | AND | Qualifier | 1 | 0.00% |
| 299 | Negation | HAS_MULTIPLIER | Multiplier | 1 | 0.00% |
| 300 | Person | SUBSUMES | Observation | 1 | 0.00% |
| 301 | Measurement | SUBSUMES | Observation | 1 | 0.00% |
| 302 | Procedure | SUBSUMES | Device | 1 | 0.00% |
| 303 | Visit | AND | Drug | 1 | 0.00% |
| 304 | Visit | OR | Condition | 1 | 0.00% |
| 305 | Negation | SUBSUMES | Condition | 1 | 0.00% |
| 306 | Procedure | OR | Multiplier | 1 | 0.00% |
| 307 | Multiplier | OR | Condition | 1 | 0.00% |
| 308 | Temporal | OR | Multiplier | 1 | 0.00% |
| 309 | Multiplier | HAS_VALUE | Value | 1 | 0.00% |
| 310 | Visit | AND | Temporal | 1 | 0.00% |
| 311 | Visit | OR | Mood | 1 | 0.00% |
| 312 | Visit | OR | Procedure | 1 | 0.00% |
| 313 | Temporal | AND | Temporal | 1 | 0.00% |
| 314 | Temporal | SUBSUMES | Multiplier | 1 | 0.00% |
| 315 | Negation | HAS_CONTEXT | Observation | 1 | 0.00% |
| 316 | Value | SUBSUMES | Qualifier | 1 | 0.00% |
| 317 | Value | SUBSUMES | Condition | 1 | 0.00% |
| 318 | Procedure | OR | Value | 1 | 0.00% |
| 319 | Qualifier | SUBSUMES | Drug | 1 | 0.00% |
| 320 | Temporal | SUBSUMES | Value | 1 | 0.00% |
| 321 | Value | OR | Person | 1 | 0.00% |
| 322 | Visit | HAS_MULTIPLIER | Multiplier | 1 | 0.00% |
| 323 | Device | SUBSUMES | Procedure | 1 | 0.00% |
| 324 | Qualifier | SUBSUMES | Device | 1 | 0.00% |
| 325 | Negation | OR | Negation | 1 | 0.00% |
| 326 | Mood | OR | Qualifier | 1 | 0.00% |
| 327 | Procedure | AND | Temporal | 1 | 0.00% |
| 328 | Person | HAS_MOOD | Mood | 1 | 0.00% |
| 329 | Device | AND | Drug | 1 | 0.00% |
| 330 | Negation | OR | Condition | 1 | 0.00% |
| 331 | Drug | SUBSUMES | Temporal | 1 | 0.00% |
| 332 | Qualifier | HAS_INDEX | Reference_point | 1 | 0.00% |
| 333 | Negation | OR | Procedure | 1 | 0.00% |
| 334 | Temporal | OR | Measurement | 1 | 0.00% |
| 335 | Condition | OR | Value | 1 | 0.00% |
| 336 | Temporal | AND | Visit | 1 | 0.00% |
| 337 | Person | OR | Visit | 1 | 0.00% |
| 338 | Drug | OR | Multiplier | 1 | 0.00% |
| 339 | Observation | SUBSUMES | Drug | 1 | 0.00% |
| 340 | Visit | OR | Observation | 1 | 0.00% |
| 341 | Negation | AND | Procedure | 1 | 0.00% |
| 342 | Visit | HAS_MOOD | Mood | 1 | 0.00% |
| 343 | Multiplier | OR | Drug | 1 | 0.00% |
| 344 | Negation | AND | Drug | 1 | 0.00% |
| 345 | Mood | HAS_MULTIPLIER | Multiplier | 1 | 0.00% |
| 346 | Qualifier | AND | Device | 1 | 0.00% |
| 347 | Visit | OR | Qualifier | 1 | 0.00% |
| 348 | Visit | AND | Measurement | 1 | 0.00% |
| 349 | Drug | OR | Qualifier | 1 | 0.00% |
| 350 | Procedure | OR | Mood | 1 | 0.00% |
| 351 | Mood | OR | Device | 1 | 0.00% |
| 352 | Mood | SUBSUMES | Observation | 1 | 0.00% |
| 353 | Observation | SUBSUMES | Qualifier | 1 | 0.00% |
| 354 | Temporal | SUBSUMES | Procedure | 1 | 0.00% |
| 355 | Qualifier | OR | Mood | 1 | 0.00% |
| 356 | Measurement | OR | Person | 1 | 0.00% |
| 357 | Value | OR | Drug | 1 | 0.00% |
| 358 | Drug | SUBSUMES | Measurement | 1 | 0.00% |
| 359 | Observation | SUBSUMES | Person | 1 | 0.00% |

Distinct signatures: **359**.

### Called-out signatures

| Signature | Count | Present? |
| :--- | ---: | :--- |
| `Measurement` → `HAS_VALUE` → `Value` | 2,799 | yes |
| `Drug` → `HAS_VALUE` → `Value` | 12 | yes |
| `Drug` → `HAS_QUALIFIER` → `Qualifier` | 259 | yes |
| `Drug` → `HAS_MULTIPLIER` → `Multiplier` | 228 | yes |

#### Every relation whose arg1 is `Drug`

| relation | arg2 type | Count |
| :--- | :--- | ---: |
| OR | Drug | 2,885 |
| HAS_TEMPORAL | Temporal | 532 |
| HAS_QUALIFIER | Qualifier | 259 |
| SUBSUMES | Drug | 247 |
| HAS_MULTIPLIER | Multiplier | 228 |
| HAS_NEGATION | Negation | 125 |
| OR | Procedure | 91 |
| AND | Drug | 68 |
| OR | Condition | 61 |
| AND | Condition | 60 |
| HAS_MOOD | Mood | 39 |
| OR | Observation | 36 |
| OR | Device | 27 |
| AND | Procedure | 12 |
| HAS_VALUE | Value | 12 |
| HAS_CONTEXT | Observation | 10 |
| HAS_INDEX | Reference_point | 4 |
| OR | Measurement | 4 |
| OR | Visit | 3 |
| AND | Device | 3 |
| AND | Measurement | 3 |
| OR | Mood | 2 |
| SUBSUMES | Condition | 2 |
| AND | Visit | 2 |
| OR | Person | 2 |
| OR | Value | 1 |
| SUBSUMES | Temporal | 1 |
| OR | Multiplier | 1 |
| OR | Qualifier | 1 |
| SUBSUMES | Measurement | 1 |

Total relations with `Drug` as arg1: **4,722**.

#### Every relation whose arg1 is `Measurement`

| relation | arg2 type | Count |
| :--- | :--- | ---: |
| HAS_VALUE | Value | 2,799 |
| OR | Measurement | 620 |
| HAS_TEMPORAL | Temporal | 286 |
| SUBSUMES | Measurement | 206 |
| HAS_QUALIFIER | Qualifier | 152 |
| OR | Condition | 150 |
| AND | Condition | 53 |
| OR | Procedure | 44 |
| AND | Measurement | 37 |
| AND | Procedure | 30 |
| HAS_MULTIPLIER | Multiplier | 26 |
| AND | Person | 25 |
| HAS_NEGATION | Negation | 13 |
| OR | Device | 11 |
| OR | Observation | 10 |
| OR | Value | 8 |
| OR | Drug | 8 |
| HAS_CONTEXT | Observation | 6 |
| HAS_MOOD | Mood | 4 |
| SUBSUMES | Condition | 3 |
| SUBSUMES | Procedure | 3 |
| AND | Drug | 3 |
| SUBSUMES | Qualifier | 3 |
| AND | Device | 2 |
| SUBSUMES | Value | 2 |
| SUBSUMES | Observation | 1 |
| OR | Person | 1 |

Total relations with `Measurement` as arg1: **4,506**.

### Is there a drug→dose relation in Chia? (evidence)

Your inspection of two documents suggested dosage is annotated as `Qualifier`/`Multiplier` rather than `Value`. At corpus scale that is confirmed, and it is worse than it looks: the dose signal is not merely relabelled, it is **smeared across three relations, none of which means 'dose'**.

| Candidate signature | n | arg2 surface looks dose/frequency-like | Verdict |
| :--- | ---: | ---: | :--- |
| `Drug` → `HAS_VALUE` → `Value` | 12 | 100.00% | Semantically exactly right, **far too rare to train or evaluate on** |
| `Drug` → `HAS_MULTIPLIER` → `Multiplier` | 228 | 68.86% | Conflates dose amount, **frequency and duration** |
| `Drug` → `HAS_QUALIFIER` → `Qualifier` | 259 | 15.44% | Mostly **route/kind**, not dose |

**Most frequent `arg2` surface forms — `Drug` → `HAS_VALUE` → `Value` (n=12, 12 distinct):**

| Count | Surface form |
| ---: | :--- |
| 1 | `for more than 2 weeks` |
| 1 | `<=400 micrograms (mcg)` |
| 1 | `≤0.5 mg/kg/day` |
| 1 | `<10mg` |
| 1 | `>15 mg/day` |
| 1 | `50-90 mg/kg/day` |
| 1 | `= 1mg/kg/d` |
| 1 | `>30mg/day` |
| 1 | `>20mg/day` |
| 1 | `> 6mg/day` |
| 1 | `> 750mg/day` |
| 1 | `1.5` |

**Most frequent `arg2` surface forms — `Drug` → `HAS_MULTIPLIER` → `Multiplier` (n=228, 172 distinct):**

| Count | Surface form |
| ---: | :--- |
| 13 | `daily` |
| 7 | `chronic use` |
| 5 | `chronic` |
| 4 | `at least one` |
| 4 | `regular use` |
| 3 | `more than one` |
| 3 | `long-term use` |
| 3 | `stable doses` |
| 3 | `maximum dosage` |
| 2 | `60 mg/day` |
| 2 | `regular` |
| 2 | `2` |
| 2 | `> 40 mg qd` |
| 2 | `≥ 5 days` |
| 2 | `one or more` |

**Most frequent `arg2` surface forms — `Drug` → `HAS_QUALIFIER` → `Qualifier` (n=259, 148 distinct):**

| Count | Surface form |
| ---: | :--- |
| 33 | `other` |
| 20 | `stable dose` |
| 9 | `oral` |
| 8 | `investigational` |
| 7 | `stable` |
| 7 | `chronic` |
| 6 | `systemic` |
| 6 | `any` |
| 3 | `low dose` |
| 3 | `stable doses` |
| 3 | `licensed` |
| 3 | `strong` |
| 3 | `another` |
| 3 | `lower the seizure threshold` |
| 2 | `inhaled` |

The middle column is a deliberately loose regex (any digit, or `mg`/`mcg`/`daily`/`qd`/`/kg`/`%`…). It counts frequency and duration expressions as 'dose-like', so it is an **upper bound** — the true dose fraction of `HAS_MULTIPLIER` is well below the figure shown. It is used to characterise the arguments, never to relabel them.

Read the `HAS_MULTIPLIER` column carefully: `daily`, `chronic use`, `at least one`, `≥ 5 days` and `60 mg/day` are all the same relation. A model trained to extract this is not learning dose extraction.

By contrast the test→result side is clean and plentiful: **`Measurement` → `HAS_VALUE` → `Value` = 2,799**, with `Person` → `HAS_VALUE` → `Value` = 752 (age criteria) available as a second, closely-related target if wanted.

## 1.3 Structural statistics

### Discontinuous entities (trap 5)

- Count: **1,781** of 40,976 in-schema entities (**4.35%**)
- Participating in at least one in-schema relation: **1,725** (**96.86%** of discontinuous entities)
- Fragment counts: 2 fragments: 1,729, 3 fragments: 51, 4 fragments: 1

| Entity type | Discontinuous | All | % of that type discontinuous |
| :--- | ---: | ---: | ---: |
| Condition | 898 | 12,039 | 7.46% |
| Procedure | 170 | 3,595 | 4.73% |
| Value | 136 | 4,002 | 3.40% |
| Qualifier | 121 | 4,157 | 2.91% |
| Measurement | 119 | 3,305 | 3.60% |
| Observation | 105 | 1,216 | 8.63% |
| Drug | 89 | 3,801 | 2.34% |
| Temporal | 55 | 3,580 | 1.54% |
| Multiplier | 42 | 671 | 6.26% |
| Device | 28 | 386 | 7.25% |
| Mood | 9 | 616 | 1.46% |
| Visit | 4 | 165 | 2.42% |
| Person | 3 | 1,666 | 0.18% |
| Reference_point | 2 | 934 | 0.21% |

### Overlapping and nested entities (traps 6 and 7)

| Relationship between the two entities | Pairs |
| :--- | ---: |
| Identical span set (duplicate offsets) | 192 |
| — of which same entity type | 30 |
| Strict containment (one inside the other) | 2,056 |
| Partial overlap (neither contains the other) | 1,933 |
| **Total overlapping pairs** | **4,181** |

Worked examples — a single short span carrying three simultaneous annotations, with a `HAS_VALUE` relation between the inner two. Any one-label-per-span assumption destroys exactly the relations we are targeting:

| Document | Outer entity | Contains |
| :--- | :--- | :--- |
| NCT00050349_exc | `Condition "HIV+"` | `Measurement "HIV"`, `Value "+"` |
| NCT00679341_exc | `Qualifier "Grade ≥ 3"` | `Measurement "Grade"`, `Value "≥ 3"` |
| NCT00720031_exc | `Condition "HIV+"` | `Measurement "HIV"`, `Value "+"` |
| NCT00917891_inc | `Condition "HIV-negative"` | `Measurement "HIV"`, `Value "negative"` |
| NCT01082549_inc | `Qualifier "stage IV"` | `Measurement "stage"`, `Value "IV"` |
| NCT01700790_inc | `Condition "HIV positive"` | `Measurement "HIV"`, `Value "positive"` |

Examples of same-type duplicate annotations:

| Document | id A | id B | Type | Text |
| :--- | :--- | :--- | :--- | :--- |
| NCT00343668_inc | T7 | T14 | Measurement | `longest diameter` |
| NCT01352598_inc | T31 | T32 | Condition | `prostate cancer` |
| NCT01711801_inc | T20 | T21 | Condition | `surgically sterilized` |
| NCT02101554_inc | T9 | T12 | Drug | `morphine` |
| NCT02150590_exc | T4 | T11 | Condition | `COPD` |
| NCT02225548_exc | T87 | T95 | Condition | `hepatic impairment` |
| NCT02558504_exc | T20 | T23 | Observation | `Pregnant` |
| NCT02668978_exc | T14 | T15 | Drug | `Brilliant Blue FCF (E133)` |

### Entity span length in whitespace tokens

| Entity type | n | median | p90 | p95 | p99 | max |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| Condition | 12,039 | 2 | 3 | 4 | 6 | 17 |
| Qualifier | 4,157 | 1 | 3 | 5 | 9 | 31 |
| Value | 4,002 | 2 | 5 | 6 | 9 | 16 |
| Drug | 3,801 | 1 | 3 | 3 | 6 | 14 |
| Procedure | 3,595 | 2 | 3 | 4 | 6 | 19 |
| Temporal | 3,580 | 3 | 7 | 8 | 11 | 16 |
| Measurement | 3,305 | 2 | 4 | 5 | 8 | 18 |
| Person | 1,666 | 1 | 1 | 2 | 3 | 7 |
| Observation | 1,216 | 2 | 5 | 6 | 9 | 13 |
| Reference_point | 934 | 2 | 5 | 6 | 7 | 15 |
| Negation | 843 | 1 | 2 | 2 | 4 | 4 |
| Multiplier | 671 | 3 | 5 | 6 | 7 | 11 |
| Mood | 616 | 2 | 3 | 4 | 6 | 9 |
| Device | 386 | 2 | 4 | 4 | 6 | 8 |
| Visit | 165 | 2 | 5 | 7 | 10 | 11 |
| **all** | **40,976** | 2 | 4 | 5 | 8 | 31 |

## 1.4 Cross-boundary relations

| Boundary | Same | Crossing | % crossing |
| :--- | ---: | ---: | ---: |
| Criterion (line) | 34,713 | 6 | 0.02% |
| Sentence (approx.) | 34,382 | 337 | 0.97% |

- Relations whose arguments could not be located in any non-empty line: **0**
- Entities whose own span crosses a line boundary: **2**

Sentence segmentation is a crude regex (split on `.!?` followed by whitespace and a capital/bracket). It is abbreviation-unaware, so the sentence figure is an upper bound on true crossings. It is used for reporting only — per trap 11, no sentence splitting is applied to the corpus.

Examples of cross-criterion relations:

| Document | Relation id | Type | arg1 | arg2 |
| :--- | :--- | :--- | :--- | :--- |
| NCT03026088_exc | R112 | OR | Measurement:Serum Alanine Aminotrans | Measurement:Serum Aspartate Aminotra |
| NCT03212352_inc | R10 | HAS_TEMPORAL | Measurement:crown-rump length | Temporal:At least one week after  |
| NCT03212352_inc | R17 | HAS_TEMPORAL | Observation:fetal growth | Temporal:At least one week after  |
| NCT03212352_inc | R27 | OR | Temporal:at least one week later | Temporal:At least one week after  |
| NCT03212352_inc | R28 | OR | Measurement:crown-rump length | Condition:discrepancy |
| NCT03212352_inc | R30 | OR | Observation:fetal growth | Condition:discrepancy |

## 1.5 Leakage risk — duplicated criterion strings

| Quantity | Value |
| :--- | ---: |
| Criteria (occurrences) | 12,409 |
| Distinct normalised criterion strings | 11,790 |
| Strings occurring more than once | 299 |
| Strings occurring in **more than one trial** | 269 |
| Criterion occurrences involved in cross-trial duplication | 851 (6.86% of all criteria) |
| Distinct trials touched by cross-trial duplication | 442 (44.20% of trials) |

Most widely shared criterion strings:

| Trials | Occurrences | Criterion (normalised) |
| ---: | ---: | :--- |
| 67 | 67 | `pregnancy` |
| 43 | 47 | `na` |
| 15 | 15 | `written informed consent` |
| 12 | 12 | `signed informed consent` |
| 12 | 12 | `pregnancy or lactation` |
| 11 | 11 | `pregnant or lactating women` |
| 10 | 10 | `diabetes mellitus` |
| 9 | 9 | `age > 18 years` |
| 8 | 8 | `pregnant women` |
| 8 | 8 | `informed consent` |
| 8 | 8 | `age 18 years or older` |
| 7 | 7 | `pregnant` |
| 6 | 6 | `18 years of age or older` |
| 6 | 6 | `diabetes` |
| 6 | 6 | `congestive heart failure` |

## 1.6 Schema check against `annotation.conf`

`annotation.conf` is present in both zips (identical in each).

### `[entities]`

| Check | Types |
| :--- | :--- |
| Declared in conf, absent from data | `Scope` |
| Present in data, **not declared** in conf | `Context_Error`, `Grammar_Error`, `Not_a_criteria`, `Parsing_Error`, `Subjective_judgement`, `Undefined_semantics`, `c-Requires_causality` |

### `[relations]`

Declared relation entries:

| Name | Arg1 constraint | Arg2 constraint |
| :--- | :--- | :--- |
| `h-OR` | `<ENTITY>` | `<ENTITY>` |
| `v-AND` | `<ANY>` | `<ANY>` |
| `v-OR` | `<ANY>` | `<ANY>` |
| `multi` | `<ANY>` | `<ANY>` |
| `<OVERLAP>` | `<ANY>` | `<ANY>` |

| Check | Relation types |
| :--- | :--- |
| Declared in conf, absent from data | `<OVERLAP>`, `H-OR`, `V-OR` |
| Present in data, **not declared** in conf | `AND`, `CAUSAL`, `HAS_CONTEXT`, `HAS_INDEX`, `HAS_MOOD`, `HAS_MULTIPLIER`, `HAS_NEGATION`, `HAS_QUALIFIER`, `HAS_TEMPORAL`, `HAS_VALUE`, `NOT`, `OR`, `SUBSUMES` |

**Verdict: `annotation.conf` cannot be used to validate this corpus.** Its `[relations]` section declares five generic brat UI helpers (`h-OR`, `v-AND`, `v-OR`, `multi`, `<OVERLAP>`) with `<ANY>`/`<ENTITY>` argument constraints, and declares **none** of the eleven relation types the data actually uses. There are therefore no declared argument constraints to violate — the check is vacuous rather than clean. The config is a stale annotation-tool artifact shipped alongside the data. Two of its helper names (`multi`, `v-AND`) do leak into the data as relation types and are dropped as out-of-schema.

---

## 2. Decisions required before Phase 2

Each of these changes what the experiment measures, so none has been made silently. My recommendation is given first in each case; all are yours to overrule.

### D1 — Target relations (blocking)

The drug→dose relation you want **does not exist in Chia in usable form** (§1.2b): the semantically correct signature has 12 instances, and the two larger candidates mean 'frequency/duration' and 'route/kind' at least as often as they mean 'dose'. Options:

| Option | Target set | Total instances | Trade-off |
| :--- | :--- | ---: | :--- |
| **A (recommended)** | Test→result only: `Measurement`/`Person` → `HAS_VALUE` → `Value` | 3,551 | Clean, plentiful, semantically unambiguous. Drops the drug arm of the study. |
| B | A + `Drug` → `HAS_MULTIPLIER` → `Multiplier` (+228) as a separate label | 3,779 | Keeps a drug arm, but the label means dose, frequency *or* duration. Must be reported as 'drug modifier', never as 'dose'. |
| C | A + all three `Drug` signatures (+499) merged into one `DRUG_HAS_DOSE` | 4,050 | Maximises drug-arm data; the label becomes semantically incoherent. Not recommended. |
| D | Keep Chia for test→result, source drug→dose from another corpus (e.g. n2c2 2018 ADE, which annotates Drug–Dosage/Frequency/Route natively) | n/a | Only option that genuinely delivers drug→dose. Costs a second data pipeline. |

Whichever you pick, the *label naming* question is separate: raw brat names (`Has_value`) or derived, argument-typed names (`MEASUREMENT_HAS_VALUE`). Given a GLiNER2-family model consumes relation labels as natural-language strings in the prompt, derived names carry more zero-shot signal — but they also change the task (the model no longer has to infer argument types). **Recommendation: derived names**, with raw names retained in the JSONL as a second field so both can be evaluated.

### D2 — `OR` relations

Pairwise expansion turns 5,015 `*` lines into 15,189 relations — 43.75% of the corpus, and the single largest 'relation type' by a wide margin. It is also the reason this parse reports 34,719 relations where the paper reports 25,017.

**Recommendation: exclude `OR` from the target set entirely** (it is coordination, not a clinical relation) and, if it is kept at all, count it one-per-`*`-line rather than pairwise so it does not dominate. Note the 4 `NOT` equivalence lines are not `OR` at all.

### D3 — Discontinuous entities

**1,781** entities (4.35%), of which **96.86%** are relation arguments — so dropping them silently deletes real relations. Options: drop / merge to enclosing span / keep head fragment.

**Recommendation: merge to enclosing span**, and record a `discontinuous: true` flag plus the original fragments on the entity. GLiNER2-family models emit contiguous spans, so 'keep head fragment' silently mislabels the gold answer, and 'drop' loses 1,725 relation arguments. Merging over-covers (`greater than Grade 1` instead of `greater than … 1`) but keeps the relation intact and is honestly reportable. Whatever we pick, evaluation must report discontinuous cases separately.

### D4 — Nested / overlapping entities

**4,181** overlapping entity pairs, of which 2,056 are strict containment. Chia genuinely annotates `HIV+` as `Condition`, `Measurement` and `Value` simultaneously — any one-label-per-span flattening destroys the very `HAS_VALUE` relations we are targeting.

**Recommendation: keep all annotations** (no flattening). Entities are identified by brat id in the JSONL, so overlap is representable.

### D5 — Instance granularity

Only **6** relations of 34,719 cross a criterion boundary (§1.4). **Recommendation: one criterion = one instance**, dropping those 6 cross-criterion relations with a logged reason. (2 entities also cross a line boundary and would be dropped for the same reason.)

### D6 — Duplicate criteria and the leakage control

269 criterion strings appear in more than one trial, covering 44.20% of trials but only 6.86% of criteria, and they are overwhelmingly short boilerplate (`pregnancy`, `written informed consent`). Grouping splits by NCT ID does **not** eliminate them.

**Recommendation: keep them, report them.** They are genuine corpus distribution, and 67 trials legitimately share the criterion `pregnancy`. Deduplicating would distort the test set more than the leakage does. If you want them gone, say so and I will drop cross-trial duplicates from train only, never from test.

### D7 — Corpus variant and text normalisation

Profiled **without_scope** per your instruction (trap 8). Also note 1,603 of 2,000 files use CRLF line endings; Phase 2 will normalise to `\n` and re-base every offset, asserting `text[start:end] == entity_text` for every entity as you specified.
