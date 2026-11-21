"""Prepare the fixed D1 dataset order and run ms-swift DPO on one GPU."""

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import random


HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "dpo_config.json").read_text(encoding="utf-8"))
DATA_SHA256 = "d6ae9fa2a4b391ed533964beadb1f1ed4d887359df7f7fd3aa88c5433d4abbca"
LONGEST_PAIR = 114  # Zero-based in the fixed D1 JSONL.
PILOT_STEPS = 20


def image_env():
    os.environ.update(MIN_PIXELS="1003520", MAX_PIXELS="4014080",
                      IMAGE_MIN_TOKEN_NUM="980", IMAGE_MAX_TOKEN_NUM="3920",
                      SPATIAL_MERGE_SIZE="2")


def ordered_indices(size):
    order = list(range(size))
    random.Random(CONFIG["data_seed"]).shuffle(order)
    longest = order.index(LONGEST_PAIR)
    boundary = PILOT_STEPS * CONFIG["gradient_accumulation_steps"] - 1
    if longest > boundary:
        order[boundary], order[longest] = order[longest], order[boundary]
    return order


def arguments(**kwargs):
    from swift.llm import RLHFArguments

    @dataclass
    class D1Arguments(RLHFArguments):
        # Pass through to TRL's DPOConfig so its default cannot zero E1's LoRA dropout.
        disable_dropout: bool = False

    return D1Arguments(**kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["pilot", "full"])
    parser.add_argument("pairs", type=Path)
    parser.add_argument("image_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    pairs, image_root, output = args.pairs.resolve(), args.image_root.resolve(), args.output.resolve()
    if output.exists():
        parser.error("use a new output directory")
    payload = pairs.read_bytes()
    if hashlib.sha256(payload).hexdigest() != DATA_SHA256:
        parser.error("D1 pair dataset hash differs from the CPU-verified file")
    rows = payload.decode("utf-8").removesuffix("\n").split("\n")
    if len(rows) != 707 or not image_root.is_dir():
        parser.error("expected 707 pairs and the staged image root")
    os.chdir(image_root)
    image_env()
    import torch
    from swift.llm import rlhf_main

    if torch.cuda.device_count() != 1 or int(os.environ.get("WORLD_SIZE", "1")) != 1:
        parser.error("expose exactly one GPU for effective batch size 16")
    output.mkdir(parents=True)
    ordered = output / "ordered_train.jsonl"
    order = ordered_indices(len(rows))
    ordered.write_text("\n".join(rows[i] for i in order) + "\n", encoding="utf-8", newline="\n")
    print("Longest pair optimizer step:", order.index(LONGEST_PAIR) // CONFIG["gradient_accumulation_steps"] + 1,
          flush=True)
    pilot = args.stage == "pilot"
    schedule = {"max_steps": PILOT_STEPS, "save_strategy": "steps", "save_steps": PILOT_STEPS} if pilot else {"max_steps": -1}
    train_args = arguments(**{**CONFIG, **schedule, "dataset": [str(ordered)], "output_dir": str(output)})
    assert train_args.ref_model is None and not train_args.ref_adapters and not train_args.adapters
    assert train_args.resume_from_checkpoint is None
    assert not train_args.training_args.disable_dropout and not train_args.training_args.reference_free
    rlhf_main(train_args)


if __name__ == "__main__":
    main()
