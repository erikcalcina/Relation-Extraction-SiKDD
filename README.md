# Relation-Extraction-SiKDD

Relation extraction using [GLiNER2](https://github.com/urchade/GLiNER), covering:

- Fine-tuning on a custom labeled dataset
- Zero-shot inference/evaluation
- Few-shot inference/evaluation

## Project layout

```
src/relation_extraction/
├── data/          # dataset loading, GLiNER2-format conversion, preprocessing, splits
├── models/         # GLiNER2 wrapper (load/save, zero-shot & few-shot inference helpers)
├── training/        # fine-tuning loop
├── evaluation/       # metrics + zero-shot / few-shot / fine-tuned eval runners
└── utils/          # logging, seeding, I/O helpers

scripts/            # CLI entry points: prepare_data.py, train.py, evaluate.py
configs/            # YAML configs (data.yaml, train.yaml, eval.yaml)
data/               # raw/, processed/, splits/ (gitignored, populated locally)
outputs/            # checkpoints, predictions, eval results (gitignored)
tests/              # pytest, mirrors src/relation_extraction/
```

See `docs/superpowers/specs/2026-08-10-repo-scaffold-design.md` for the full
design rationale.

## Dataset

The relation-extraction corpus is [Chia](https://doi.org/10.6084/m9.figshare.11855817)
(clinical trial eligibility criteria, CC-BY-4.0). Profiling results are in
[`profile_report.md`](profile_report.md); every preparation decision and known
limitation is recorded in [`docs/chia/README.md`](docs/chia/README.md).

## Setup

This project uses [uv](https://docs.astral.sh/uv/) for dependency and
environment management.

```bash
uv sync
```

This creates a `.venv` in the project root and installs all dependencies into
it — no manual `python -m venv` step needed. Scripts can then be run with
`uv run`, which uses that `.venv` automatically. Alternatively, activate it
once per shell session (`source .venv/bin/activate`) to run scripts with
plain `python` instead.

## Usage

Scripts are config-driven via YAML files in `configs/`:

Dataset preparation is implemented. One command downloads, verifies, extracts
and converts the corpus — stdlib only, so it needs no venv and no `uv sync`:

```bash
python3 scripts/setup_chia.py
```

It takes about 3 seconds from cold, skips any step whose output already
exists, and is deterministic — re-running reproduces every artifact byte for
byte. See [`docs/chia/README.md`](docs/chia/README.md) for the flags and for
the by-hand equivalent.

Training and evaluation will be config-driven via YAML in `configs/`, added as
the corresponding modules are implemented:

```bash
uv run scripts/train.py --config configs/train.yaml
uv run scripts/evaluate.py --config configs/eval.yaml
```

## Testing

```bash
uv run pytest
```
