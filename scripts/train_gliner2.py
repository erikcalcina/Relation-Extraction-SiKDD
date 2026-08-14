from __future__ import annotations

import argparse
from pathlib import Path

import torch

from gliner2 import GLiNER2
from gliner2.training.trainer import (
    GLiNER2Trainer,
    TrainingConfig,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fine-tune GLiNER2 on the Chia relation extraction dataset."
    )

    parser.add_argument(
        "--model",
        default="fastino/gliner2-base-v1",
        help="Base GLiNER2 model.",
    )

    parser.add_argument(
        "--train-data",
        default="data/processed/gliner2/chia_train.jsonl",
    )

    parser.add_argument(
        "--eval-data",
        default="data/processed/gliner2/chia_dev.jsonl",
    )

    parser.add_argument(
        "--output-dir",
        default="outputs/finetune_base",
    )

    parser.add_argument(
        "--mode",
        choices=["lora", "full"],
        default="lora",
        help="LoRA or full fine-tuning.",
    )

    parser.add_argument(
        "--epochs",
        type=int,
        default=3,
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
    )

    parser.add_argument(
        "--gradient-accumulation-steps",
        type=int,
        default=4,
    )

    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run only a tiny training test.",
    )

    args = parser.parse_args()

    train_path = Path(args.train_data)
    eval_path = Path(args.eval_data)

    if not train_path.exists():
        raise FileNotFoundError(train_path)

    if not eval_path.exists():
        raise FileNotFoundError(eval_path)

    cuda_available = torch.cuda.is_available()
    device = "cuda" if cuda_available else "cpu"

    print()
    print("=" * 60)
    print("GLiNER2 Chia training")
    print("=" * 60)
    print(f"Model:       {args.model}")
    print(f"Mode:        {args.mode}")
    print(f"Device:      {device}")
    print(f"Train data:  {train_path}")
    print(f"Eval data:   {eval_path}")
    print(f"Output:      {args.output_dir}")
    print(f"Smoke test:  {args.smoke}")
    print()

    # ------------------------------------------------------------
    # Tiny smoke test:
    #
    # We use only a few examples and two optimizer steps.
    # The purpose is NOT to obtain a meaningful model.
    # It only checks whether the complete training pipeline works.
    # ------------------------------------------------------------

    if args.smoke:
        num_epochs = 1
        max_steps = 2
        max_train_samples = 32
        max_eval_samples = 32
        eval_strategy = "no"
        logging_steps = 1
        save_best = False
        early_stopping = False
    else:
        num_epochs = args.epochs
        max_steps = -1
        max_train_samples = -1
        max_eval_samples = -1
        eval_strategy = "epoch"
        logging_steps = 50
        save_best = True
        early_stopping = True

    use_lora = args.mode == "lora"

    config = TrainingConfig(
        output_dir=args.output_dir,
        experiment_name="chia_relation_extraction",

        # Training
        num_epochs=num_epochs,
        max_steps=max_steps,
        batch_size=args.batch_size,
        eval_batch_size=1,
        gradient_accumulation_steps=args.gradient_accumulation_steps,

        # Learning rates
        encoder_lr=1e-5,
        task_lr=5e-4,

        # Optimisation
        weight_decay=0.01,
        warmup_ratio=0.1,
        scheduler_type="linear",
        max_grad_norm=1.0,

        # IMPORTANT:
        # fp16 is useful on supported GPUs,
        # but should not be enabled for our CPU run.
        fp16=cuda_available,
        bf16=False,

        # Evaluation
        eval_strategy=eval_strategy,
        save_best=save_best,
        metric_for_best="eval_loss",
        greater_is_better=False,

        # Logging
        logging_steps=logging_steps,
        logging_first_step=True,
        report_to_wandb=False,

        # Early stopping
        early_stopping=early_stopping,
        early_stopping_patience=2,

        # Windows / CPU-safe DataLoader settings
        num_workers=0,
        pin_memory=cuda_available,

        # Reproducibility
        seed=20260810,

        # Smoke-test limits
        max_train_samples=max_train_samples,
        max_eval_samples=max_eval_samples,

        # LoRA
        use_lora=use_lora,
        lora_r=8,
        lora_alpha=16.0,
        lora_dropout=0.0,
        save_adapter_only=use_lora,
    )

    print("Loading model...")

    model = GLiNER2.from_pretrained(
        args.model
    )

    print("Model loaded.")
    print()
    print("Starting training...")
    print()

    trainer = GLiNER2Trainer(
        model=model,
        config=config,
    )

    results = trainer.train(
        train_data=str(train_path),
        eval_data=str(eval_path),
    )

    print()
    print("=" * 60)
    print("TRAINING FINISHED")
    print("=" * 60)
    print()
    print(results)
    print()
    print(f"Output directory: {args.output_dir}")


if __name__ == "__main__":
    main()