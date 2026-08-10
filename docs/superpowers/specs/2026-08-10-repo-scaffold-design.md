# Repo Scaffold Design: Relation-Extraction-SiKDD

## Context

This is a new, empty repository. The project will use **GLiNER2** to perform
relation extraction, covering three usage modes:

- **Fine-tuning** GLiNER2 on a custom, already-labeled dataset (to be
  provided/pointed to later).
- **Zero-shot** inference/evaluation with the pretrained model.
- **Few-shot** inference/evaluation.

This design covers only the repository scaffold: folder layout, tooling, and
conventions. No model or training code is written yet — that comes in a
follow-up implementation plan.

## Package name

`relation_extraction`, importable as `relation_extraction.<module>`.

## Directory structure

```
Relation-Extraction-SiKDD/
├── src/relation_extraction/
│   ├── data/          # dataset loading, GLiNER2-format conversion, preprocessing, splits
│   ├── models/         # GLiNER2 wrapper (load/save, zero-shot & few-shot inference helpers)
│   ├── training/        # fine-tuning loop
│   ├── evaluation/       # metrics + zero-shot / few-shot / fine-tuned eval runners
│   └── utils/          # logging, seeding, I/O helpers
├── scripts/            # thin CLI entry points: prepare_data.py, train.py, evaluate.py
├── configs/            # YAML configs (data.yaml, train.yaml, eval.yaml)
├── data/
│   ├── raw/            # provided labeled dataset (gitignored, .gitkeep only)
│   ├── processed/       # GLiNER2-format converted data (gitignored)
│   └── splits/          # train/val/test split files (gitignored)
├── notebooks/           # exploration
├── tests/              # pytest, mirrors src/ layout
├── outputs/             # checkpoints, predictions, eval results (gitignored)
└── docs/               # project docs
```

### Rationale

- `src/` layout with an installable package keeps imports clean
  (`relation_extraction.data...`) and avoids path hacks in scripts,
  notebooks, and tests.
- `scripts/` stay thin (argparse + calls into the package) so logic is
  testable and reusable outside the CLI.
- `data/` and `outputs/` are gitignored, tracked only via `.gitkeep`, since
  datasets and checkpoints do not belong in git.
- `evaluation/` explicitly separates zero-shot, few-shot, and fine-tuned
  evaluation paths, since all three are required, while sharing common
  metrics code.

## Tooling

### Environment / dependencies (uv)

- `pyproject.toml` — project metadata and dependencies:
  - Runtime: `gliner2`, `torch`, `pyyaml`, `numpy`, `scikit-learn` (eval
    metrics)
  - Dev: `pytest`, `ruff`
- `uv.lock` — generated on first `uv sync`
- `.python-version` — pinned to 3.11

### Configuration

Kept intentionally minimal — plain YAML files in `configs/`, loaded with
`pyyaml`, no Hydra or other config framework. Each script (`train.py`,
`evaluate.py`, `prepare_data.py`) accepts `--config path/to/x.yaml` via
argparse, with optional CLI overrides for common fields.

- `configs/train.yaml`: model name/checkpoint, data paths, hyperparameters
  (learning rate, epochs, batch size), output directory.
- `configs/eval.yaml`: mode (`zero_shot` / `few_shot` / `finetuned`),
  checkpoint path, few-shot example count, data split to evaluate on.

### Testing

- `tests/` mirrors `src/relation_extraction/` (`tests/data/`,
  `tests/evaluation/`, etc.).
- Since no real logic exists yet, the initial scaffold includes one smoke
  test proving the package imports and pytest runs. Real unit tests are
  added alongside each module as it's built.

### Error handling

- Config loading validates required keys up front and fails fast with a
  clear message, rather than failing deep inside the training loop.
- Data loading raises clearly if `data/raw` is empty or missing expected
  files — no silent fallbacks.

### Other root files

- `README.md` — project overview, setup (`uv sync`), how to run data prep,
  training, and evaluation.
- `.gitignore` — `data/`, `outputs/`, `__pycache__`, `.venv`, checkpoints,
  `*.pt`, `*.bin`.
- No CI configuration or Makefile for now, per the preference to keep
  tooling minimal at this stage.

## Out of scope (for this scaffold)

- Actual GLiNER2 integration code (model wrapper, training loop, eval
  logic) — placeholder modules only.
- Experiment tracking (e.g. Weights & Biases) — explicitly deferred.
- CI/CD.
- Dataset acquisition/format — dataset will be provided later; `data/`
  conventions are set up generically to receive it.
