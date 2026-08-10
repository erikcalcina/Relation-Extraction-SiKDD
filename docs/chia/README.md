# Chia dataset preparation — decisions and limitations

Status: **Phase 1 (profiling) and Phase 2 (conversion + splits) both complete.**

## What exists

| Artifact | Path |
| :--- | :--- |
| Phase 1 report | `profile_report.md` |
| Profiling script (rerunnable) | `scripts/profile_chia.py` |
| BigBIO cross-check | `scripts/crosscheck_bigbio.py` → `outputs/bigbio_counts.json` |
| Brat parser | `src/relation_extraction/data/chia_brat.py` |
| Converter / splitter | `src/relation_extraction/data/chia_convert.py` |
| Phase 2 CLI | `scripts/prepare_chia.py` |
| JSONL dataset | `data/processed/chia_{train,dev,test}.jsonl` |
| Split assignments | `data/splits/split.json` |
| Split statistics | `outputs/chia_split_stats.md` |
| Drop log | `outputs/chia_conversion_log.json` |
| Tests (42) | `tests/data/test_chia_brat.py`, `tests/data/test_chia_convert.py` |

> `data/**` and `outputs/**` are gitignored, so the JSONL, `split.json` and the
> stats are regenerated rather than committed. `split.json` is meant to be
> releasable — un-ignore it if you want the exact split under version control.

## Output format

One JSON object per line, one object per **criterion**:

```json
{
  "id": "NCT00050349_exc_6", "nct_id": "NCT00050349",
  "doc_key": "NCT00050349_exc", "text_type": "exclusion",
  "criterion_index": 6, "split": "test",
  "text": "Patients with any peripheral neuropathy or unresolved diarrhea greater than Grade 1 ",
  "entities": [
    {"id": "T23", "type": "Value", "start": 63, "end": 83,
     "text": "greater than 1", "span_text": "greater than Grade 1",
     "discontinuous": true, "fragments": [[63, 75], [82, 83]],
     "offset_status": "exact"}
  ],
  "relations": [
    {"id": "R8", "type": "Has_value", "arg1_id": "T22", "arg2_id": "T23",
     "boolean": false, "synthesised": false}
  ],
  "negative_pairs": [{"arg1_id": "T20", "arg2_id": "T22"}]
}
```

* `text` is what the annotators marked; `span_text` is the emitted contiguous
  span. They differ only for discontinuous entities, where the merged span
  over-covers.
* `boolean` marks `AND`/`OR`. `synthesised` marks `OR` derived from a `*`
  equivalence line rather than an `R` line.
* Entity ids are the original brat ids, so nesting and overlap are
  representable — nothing was flattened.

## Reproducing

```bash
# 1. Fetch the corpus (byte-identical to the figshare release; MD5s verified below)
mkdir -p data/raw && cd data/raw
curl -sSLO https://huggingface.co/datasets/bigbio/chia/resolve/main/data/chia_without_scope.zip
curl -sSLO https://huggingface.co/datasets/bigbio/chia/resolve/main/data/chia_with_scope.zip
python3 -c "import zipfile;[zipfile.ZipFile(f'chia_{v}_scope.zip').extractall(f'{v}_scope') for v in ('with','without')]"
cd ../..

# 2. Profile (stdlib only, ~3 s)
python3 scripts/profile_chia.py

# 3. Optional: cross-check against the BigBIO loader (needs datasets v2)
uv run --python 3.12 --with 'datasets==2.19.0' --with 'fsspec==2024.3.1' \
    python scripts/crosscheck_bigbio.py

# 4. Convert and split (~2 s)
python3 scripts/prepare_chia.py

# 5. Tests
uv run --python 3.12 --with pytest python -m pytest tests/ -q
```

Verified MD5s: `chia_with_scope.zip` `54b33164da88da88e47b2a009e150a82`,
`chia_without_scope.zip` `e5b4578b11139b80d64aeca0cc4a76b8` — both match the
published values, and file sizes match the published 2,512,094 / 2,397,117 bytes.

Seed: `20260810`, recorded in `scripts/profile_chia.py`. No Phase 1 step is
stochastic; the seed is fixed now so Phase 2's split is reproducible from the
same constant.

## Decisions made in Phase 1

These are implementation decisions. Everything that affects *what the experiment
measures* was deliberately left open — see §2 of the report.

1. **Parse the raw `.ann`/`.txt` files; do not build on `load_dataset`.** As
   instructed. Independently justified: the loader drops 44% of relations
   (below).
2. **Read `.txt` with `newline=""`.** 1,603 of 2,000 files use CRLF. Python's
   default universal-newline mode rewrites `\r\n` → `\n`, deleting one character
   per preceding line and shifting every later offset. This is the single most
   consequential decision in the parser and the reason the corpus is widely
   believed to have broken offsets: read raw, 99.97% of offsets are exactly
   correct; read the way `chia.py` does, 41.86% are.
3. **Port `_fix_entity_offsets` verbatim, but demote it to a fallback.** It
   repairs 9 of the 12 residual mismatches. It is not used as the primary
   mechanism because a ±100-character text search can relocate a short mention
   (`+`, `1`, `no`) to a coincidental match.
4. **Repair discontinuous entities with a global fragment shift.** BigBIO's
   routine cannot repair them at all — for multi-span mentions it re-derives the
   mention text from the very offsets it is validating, so its check always
   passes. Ours searches for a single delta applied to all fragments.
5. **`HAS_CONTEXT` without the trailing space; relation types matched
   case-insensitively.** As instructed.
6. **Filter nothing silently.** Out-of-schema types, dangling arguments and
   malformed lines are retained as `DropRecord`s and reported with counts and
   reasons.
7. **A criterion is a non-empty line; a document is a whole file.** This
   reproduces the published 12,409 criteria exactly. No sentence splitting is
   applied to the corpus.
8. **Profile `without_scope`** per the trap-8 default, with `with_scope` loaded
   alongside for reconciliation only.
9. **Synthesise `OR` from `*` lines pairwise** *for profiling*, so the choice is
   visible and quantified. Whether to keep it is decision D2.

## Decisions made in Phase 2

Decisions 1–5 are the user's, given after reviewing the Phase 1 report. The rest
follow from them or from §1.4 of that report.

1. **Native Chia labels only.** Relation labels are the annotators' own strings
   (`Has_value`, `Has_temporal`, `Has_index`, `Has_mood`, `Has_context`,
   `Has_negation`, `Has_multiplier`, `Has_qualifier`, `Subsumes`, `AND`, `OR`).
   No derived argument-typed names, no merged signatures, no invented
   categories. The gold standard is exactly what the annotators produced.
2. **`AND` and `OR` are kept but flagged** `"boolean": true`, and counted
   separately in every table, so an experiment can include or exclude them
   without regenerating the data. All 15,192 `OR` relations are retained
   (pairwise expansion of the `*` lines).
3. **The drug→dose relation is dropped from this study entirely** — it will be
   done on a separate corpus later. Nothing in the pipeline targets it; `Drug`
   relations are present only because they are part of the native label set.
4. **Discontinuous entities merge to their enclosing span**, with the original
   `fragments` and a `discontinuous` flag retained so the decision is
   reversible. 1,780 entities affected.
5. **Nested and overlapping entities are all kept.** No flattening — that would
   destroy the `HAS_VALUE` relations inside spans like `HIV+`.
6. **One criterion = one instance**, justified by §1.4: only 6 of 34,719
   relations cross a criterion boundary, and those 6 are dropped and logged.
7. **Offsets are re-based to the criterion and asserted.** Every emitted entity
   must satisfy `" ".join(text[s:e] for fragments) == entity_text`, and
   contiguous entities additionally `text[start:end] == entity_text`. The
   converter raises rather than warns. Criterion text carries no `\r`.
8. **Splits are 70/10/20 grouped by NCT id**, seed `20260810`. Inclusion and
   exclusion criteria of a trial always share a split. Pairwise disjointness is
   asserted in the converter *and* re-tested against the written files.
9. **Negative (NA) pairs: every ordered pair of distinct entities inside a
   criterion that is not linked by a gold relation.** Ordered, because Chia's
   relations are directed. `AND`/`OR` block **both** directions, since they are
   symmetric (`annotation.conf` declares `OR` `symmetric-transitive`) but are
   expanded one way only — without this, 18,822 gold pairs would have been
   emitted as negatives in reverse. No subsampling by default; `--neg-ratio`
   applies the identical seeded procedure to all three splits.
10. **Criteria with no in-schema entities are dropped** (1,642 of them). They
    yield no candidate pairs. `--keep-empty-criteria` retains them.
11. **Out-of-schema entity and relation types are excluded** — the 3,640
    annotator-workflow entity labels (`Parsing_Error`, `Non-query-able`, …) and
    the 553 out-of-schema relations (`multi`, `causal`, `v-AND`, `NOT`), plus the
    86 relations that referenced them.

## Dataset as built

| | train | dev | test | total |
| :--- | ---: | ---: | ---: | ---: |
| Trials | 693 | 100 | 200 | 993 |
| Criteria (instances) | 7,714 | 1,052 | 2,001 | 10,767 |
| Entities | 29,284 | 4,097 | 7,592 | 40,973 |
| Semantic relations | 11,311 | 1,600 | 2,933 | 15,844 |
| Boolean (`AND`/`OR`) | 13,194 | 2,025 | 3,650 | 18,869 |
| Negative pairs | 127,745 | 18,230 | 35,513 | 181,488 |

Full per-type breakdowns are in `outputs/chia_split_stats.md`. 5,930 source
records were dropped in total, every one logged with a reason in
`outputs/chia_conversion_log.json`.

## Known limitations

1. **511 entities fewer than published** (40,976 vs 41,487, −1.23%). Every one of
   the 44,616 `T` lines in the release is accounted for, both corpus variants
   agree exactly on non-`Scope` entities, and there are no malformed or duplicate
   `T` ids — so the released files simply contain fewer entities than the paper
   reports. Not recoverable from the release.
2. **The published relation total depends on an undocumented counting rule.**
   25,017 is closest to *one relation per `*` line* (25,168, +0.6%); pairwise
   expansion gives 34,719. The paper does not state which it used.
3. **`annotation.conf` cannot validate this corpus.** Its `[relations]` section
   declares five generic brat UI helpers with `<ANY>` constraints and none of the
   eleven relation types the data actually uses, so §1.6's constraint check is
   vacuous rather than clean.
4. **Sentence-boundary figures are approximate.** The splitter is a regex and is
   abbreviation-unaware, so the 337 cross-sentence relations are an upper bound.
   Used for reporting only.
5. **3 entities have offsets that cannot be repaired** and are carried through
   flagged. Phase 2's `text[start:end] == entity_text` assertion will surface
   them again.
6. **The "dose-like" figures in §1.2b are an upper bound.** The heuristic counts
   frequency and duration expressions (`daily`, `≥ 5 days`) as dose-like.
7. **Cross-trial duplicate criteria are not removed.** 269 normalised criterion
   strings appear in more than one trial (6.86% of criteria, touching 44% of
   trials), almost all short boilerplate. Grouping splits by NCT id does not
   eliminate them. This is a residual leakage channel, quantified and accepted.
8. **7 trials and 1,642 criteria carry no in-schema entities** and so do not
   appear in the dataset. Split percentages are exact at trial level (69.8 /
   10.1 / 20.1) but drift slightly at criterion level (71.6 / 9.8 / 18.6),
   because trials differ in size. Grouping by trial is the leakage control and
   takes precedence over exact criterion proportions.
9. **`OR` still dominates**: 15,192 of 34,713 relations (43.8%). Retained per
   decision 2, but any experiment that trains on all relations without excluding
   the Boolean ones is largely measuring coordination detection. Filter on
   `"boolean": false` to get the 15,844 semantic relations.
10. **Negatives outnumber semantic positives ~11.5:1** when every candidate is
    kept. Use `--neg-ratio` to change this; the procedure and seed stay
    identical across splits either way.
11. **`span_text` over-covers for the 1,780 discontinuous entities.** Evaluation
    should report those cases separately — `discontinuous: true` makes that a
    one-line filter.

## Bugs found in `bigbio/chia`'s loading script

Reproduced by simulation *and* confirmed against actual `load_dataset` output
(`datasets==2.19.0`, `trust_remote_code=True`). Entity counts agree exactly,
type for type; relations do not.

| Bug | Effect | Location |
| :--- | :--- | :--- |
| `"HAS_CONTEXT "` has a trailing space in `_RELATION_TYPES`, and membership is tested by exact match after `.upper()` | all 221 `Has_context` relations silently dropped | `chia.py:118` |
| Relations whose arguments did not survive entity filtering are discarded | 72 relations dropped | `chia.py:347` |
| **`entity_ids` is keyed by document-prefixed ids, but the equivalence loop tests the bare `T` id against it** — so the guard never matches | **all 15,189 `OR` relations synthesised from `*` lines silently dropped**; the loader emits 7 `OR` (the literal `R`-line ones) and none from equivalences | `chia.py:365` vs `chia.py:316` |

The third was not in the original trap list. Together the loader returns 19,309
relations where the raw files hold 34,719 — **44.38% lost**.

Separately, `chia.py` reads `.txt` files with `Path.open()`, which triggers the
CRLF problem in decision 2 above and is why `_fix_entity_offsets` exists at all.

## How the §2 decisions were resolved

The evidence for each is in §2 of `profile_report.md`; the outcome is what the
pipeline implements.

| # | Decision | Resolution |
| :--- | :--- | :--- |
| D1 | Target relations — **there is no usable drug→dose relation in Chia** (`Drug`→`Has_value`→`Value` = 12 instances) | Native label set, unmodified. Drug→dose dropped from this study; to be done on a separate corpus later |
| D2 | Keep `OR`? Pairwise or one-per-`*`-line? | Keep all, pairwise, flagged `boolean` so it is excludable at experiment time |
| D3 | Discontinuous entities: drop / merge / head fragment | Merge to enclosing span, flagged, fragments retained |
| D4 | Nested entities: keep all or flatten | Keep all |
| D5 | Instance granularity | One criterion = one instance |
| D6 | Cross-trial duplicate criteria | Kept and quantified |
| D7 | Label naming: raw or derived | **Raw only** |

## Licence

Chia is CC-BY-4.0. Kury et al., *Scientific Data* 7 (2020),
doi [`10.1038/s41597-020-00620-0`](https://doi.org/10.1038/s41597-020-00620-0);
data doi [`10.6084/m9.figshare.11855817`](https://doi.org/10.6084/m9.figshare.11855817).
