"""Verify and merge one adapter into the supplied Qwen3-VL base."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def shards(folder):
    return {path.name: sha(path) for path in sorted(folder.glob("model*.safetensors"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "adapter", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--base-sha256", nargs="+", required=True)
    parser.add_argument("--adapter-sha256", required=True)
    parser.add_argument("--merged-sha256", nargs="+")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("use a new output directory")
    original = shards(args.base)
    if list(original.values()) != args.base_sha256:
        raise ValueError("Base shard hashes differ")
    if sha(args.adapter / "adapter_model.safetensors") != args.adapter_sha256:
        raise ValueError("Adapter hash differs")

    from importlib.metadata import version
    import torch
    from peft import PeftModel
    from transformers import Qwen3VLForConditionalGeneration

    if version("peft") != "0.17.1" or torch.__version__ != "2.8.0+cu128":
        raise ValueError("Expected PEFT 0.17.1 and Torch 2.8.0+cu128")
    model = Qwen3VLForConditionalGeneration.from_pretrained(
        args.base, dtype=torch.bfloat16, attn_implementation="sdpa", device_map="cpu")
    merged = PeftModel.from_pretrained(model, args.adapter).merge_and_unload(safe_merge=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.out.parent) as temp:
        staged = Path(temp) / "merged"
        merged.save_pretrained(staged, safe_serialization=True)
        copied = {}
        for source in args.base.iterdir():
            if source.is_file() and source.suffix in {".json", ".jinja", ".txt"} and source.name not in {
                    "config.json", "model.safetensors.index.json"}:
                dest = staged / source.name
                shutil.copyfile(source, dest)
                copied[dest.name] = sha(dest)
                if copied[dest.name] != sha(source):
                    raise ValueError(f"Sidecar hash differs: {source.name}")
        result = shards(staged)
        if args.merged_sha256 and list(result.values()) != args.merged_sha256:
            raise ValueError(f"Merged shard hashes differ: {result}")
        receipt = {"base_sha256": original, "adapter_sha256": args.adapter_sha256,
                   "merged_sha256": result, "sidecar_sha256": copied}
        (staged / "merge_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        staged.rename(args.out)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
