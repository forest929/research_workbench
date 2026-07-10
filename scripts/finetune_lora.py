#!/usr/bin/env python3
"""
Submit a LoRA fine-tuning job on Nebius Token Factory using the conversation
dataset exported by scripts/export_lora_dataset.py.

Splits the dataset 85/15 into train/validation, uploads both files, creates
the fine-tuning job, and (by default) polls until it completes.

Usage:
    python scripts/finetune_lora.py [--input data/lora_training/conversations.jsonl]
                                     [--model meta-llama/Llama-3.3-70B-Instruct]
                                     [--no-wait]
"""

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from portfolio_architect.finetuning.nebius_ft import (
    upload_file,
    create_job,
    get_job,
    list_checkpoints,
)

DEFAULT_MODEL = "meta-llama/Llama-3.3-70B-Instruct"
VAL_FRACTION = 0.15
SEED = 42
POLL_INTERVAL_SECONDS = 20
HYPERPARAMETERS = {
    "lora": True,
    "lora_r": 16,
    "lora_alpha": 16,
    "lora_dropout": 0.05,
    "n_epochs": 3,
    "batch_size": 8,
    "learning_rate": 1e-5,
    "context_length": 8192,  # platform minimum; our examples are far shorter but this can't be reduced
}


def split_dataset(input_path: Path, out_dir: Path) -> tuple[Path, Path]:
    lines = input_path.read_text().splitlines()
    rng = random.Random(SEED)
    rng.shuffle(lines)
    n_val = max(1, round(len(lines) * VAL_FRACTION))
    val_lines = lines[:n_val]
    train_lines = lines[n_val:]

    train_path = out_dir / "train.jsonl"
    valid_path = out_dir / "valid.jsonl"
    train_path.write_text("\n".join(train_lines) + "\n")
    valid_path.write_text("\n".join(val_lines) + "\n")
    print(f"Split {len(lines)} examples -> {len(train_lines)} train / {len(val_lines)} validation")
    return train_path, valid_path


async def wait_for_completion(job_id: str) -> dict:
    last_status = None
    while True:
        job = await get_job(job_id)
        status = job["status"]
        if status != last_status:
            print(f"  status: {status}")
            last_status = status
        trained_tokens = job.get("trained_tokens")
        if trained_tokens:
            print(f"    trained_tokens={trained_tokens}", end="\r")
        if status in ("succeeded", "failed", "cancelled"):
            return job
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def print_status(job_id: str) -> None:
    job = await get_job(job_id)
    print(f"status: {job['status']}")
    if job.get("trained_tokens"):
        print(f"trained_tokens: {job['trained_tokens']}")
    if job.get("trained_steps") is not None:
        print(f"trained_steps: {job['trained_steps']} / {job.get('total_steps')}")
    if job["status"] == "succeeded":
        checkpoints = await list_checkpoints(job_id)
        if checkpoints:
            latest = checkpoints[-1]
            metrics = latest.get("metrics", {})
            print(f"latest checkpoint: {latest.get('id')}")
            print(f"  train_loss: {metrics.get('train_loss')}  valid_loss: {metrics.get('valid_loss')}")
    elif job["status"] == "failed":
        print(f"error: {job.get('error')}")


async def main(args) -> None:
    print("=" * 65)
    print("  LoRA Fine-Tuning — Nebius Token Factory")
    print("=" * 65)

    if args.status:
        await print_status(args.status)
        return

    input_path = Path(args.input)
    out_dir = input_path.parent

    print(f"\n1. Splitting dataset from {input_path}...")
    train_path, valid_path = split_dataset(input_path, out_dir)

    print("\n2. Uploading files...")
    train_file_id = await upload_file(train_path)
    valid_file_id = await upload_file(valid_path)
    print(f"  train_file_id: {train_file_id}")
    print(f"  valid_file_id: {valid_file_id}")

    print(f"\n3. Creating fine-tuning job (model={args.model})...")
    job = await create_job(
        training_file_id=train_file_id,
        validation_file_id=valid_file_id,
        model=args.model,
        hyperparameters=HYPERPARAMETERS,
        suffix=args.suffix,
        seed=SEED,
    )
    job_id = job["id"]
    print(f"  job_id: {job_id}")

    metadata = {
        "job_id": job_id,
        "model": args.model,
        "hyperparameters": HYPERPARAMETERS,
        "train_file_id": train_file_id,
        "valid_file_id": valid_file_id,
        "suffix": args.suffix,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    job_meta_path = out_dir / f"job_{job_id}.json"
    job_meta_path.write_text(json.dumps(metadata, indent=2))
    print(f"  Job metadata saved to {job_meta_path}")

    if args.no_wait:
        print(f"\n--no-wait set. Check status later with:")
        print(f"  python scripts/finetune_lora.py --status {job_id}")
        return

    print("\n4. Waiting for job to complete (polling every "
          f"{POLL_INTERVAL_SECONDS}s)...")
    final = await wait_for_completion(job_id)

    print(f"\n\nFinal status: {final['status']}")
    if final["status"] == "succeeded":
        checkpoints = await list_checkpoints(job_id)
        if checkpoints:
            latest = checkpoints[-1]
            print(f"Latest checkpoint: {latest.get('id')}")
            metrics = latest.get("metrics", {})
            print(f"  train_loss: {metrics.get('train_loss')}")
            print(f"  valid_loss: {metrics.get('valid_loss')}")
        else:
            print("No checkpoints listed.")
    elif final["status"] == "failed":
        print(f"Error: {final.get('error')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Submit a LoRA fine-tuning job on Nebius Token Factory")
    parser.add_argument("--input", default="data/lora_training/conversations.jsonl",
                        help="Input conversations JSONL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Base model to fine-tune")
    parser.add_argument("--suffix", default="womens-cancer-claims-v1", help="Job suffix/identifier")
    parser.add_argument("--no-wait", action="store_true", help="Submit the job and exit without polling")
    parser.add_argument("--status", metavar="JOB_ID", help="Print current status of an existing job and exit")
    args = parser.parse_args()

    asyncio.run(main(args))
