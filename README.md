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

```bash
uv run scripts/prepare_data.py --config configs/data.yaml
uv run scripts/train.py --config configs/train.yaml
uv run scripts/evaluate.py --config configs/eval.yaml
```

(Scripts and configs are added as the corresponding modules are implemented.)

## Testing

```bash
uv run pytest
```
