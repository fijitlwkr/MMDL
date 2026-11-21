"""Reproduce the D3-e1 PEFT merge, then add the pinned A step30 adapter."""

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import random
import shutil

from safetensors import safe_open
import torch
from transformers import Qwen3VLForConditionalGeneration

from ab1_merge import Adapter, BASE_HASHES, MODULES, REVISION, index, sha, write_json

REFERENCE_HASHES = {
    "model-00001-of-00002.safetensors": "5501198916f4184c8f02036b71097efa881e69d57c3b4d5a941e3aefc2a6fb21",
    "model-00002-of-00002.safetensors": "2e8b706c5670049157ccd5273439a599bd2721d7d34c19016f7a7e0549e89540",
}
TARGETS = {f"{module}.weight" for module in MODULES}


class Weights:
    def __init__(self, model_path, stack):
        self.files = index(model_path)
        self.readers = {
            name: stack.enter_context(safe_open(model_path / name, framework="pt"))
            for name in set(self.files.values())
        }

    def __getitem__(self, key):
        return self.readers[self.files[key]].get_tensor(key)


def bits_equal(left, right):
    return (left.dtype == right.dtype == torch.bfloat16 and
            torch.equal(left.view(torch.int16), right.view(torch.int16)))


def shard_hashes(path):
    return {p.name: sha(p) for p in sorted(path.glob("*.safetensors"))}


def add_adapter(state, adapter):
    for key in sorted(TARGETS):
        weight = state[key]
        assert weight.dtype == torch.bfloat16
        delta = adapter.delta(key.removesuffix(".weight"), weight.shape).to(weight.dtype)
        weight.add_(delta)
        assert torch.isfinite(weight).all(), key


@torch.inference_mode()
def run(args):
    assert args.base.name == REVISION
    assert shard_hashes(args.base) == BASE_HASHES
    assert shard_hashes(args.reference) == REFERENCE_HASHES
    assert not args.intermediate.exists() and not args.output.exists()
    with ExitStack() as stack:
        a, b = (Adapter(path, stack) for path in (args.a, args.b))
        assert set(a.keys) == set(b.keys)
        print("PASS: A/B LoRA layouts match (252 modules each)", flush=True)
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            args.base, dtype=torch.bfloat16, attn_implementation="sdpa", device_map="cpu"
        )
        state = model.state_dict()
        add_adapter(state, b)
        model.save_pretrained(args.intermediate, safe_serialization=True)
        intermediate_hashes = shard_hashes(args.intermediate)
        write_json(args.records / "d3_intermediate_sha256.json", intermediate_hashes)
        assert intermediate_hashes == REFERENCE_HASHES, ("D3-e1 intermediate shard hash mismatch", intermediate_hashes)
        intermediate = Weights(args.intermediate, stack)
        reference = Weights(args.reference, stack)
        assert set(intermediate.files) == set(reference.files)
        for key in sorted(reference.files):
            assert bits_equal(intermediate[key], reference[key]), key
        print(f"PASS: D3-e1 shard hashes and {len(reference.files)} tensors match", flush=True)

        add_adapter(state, a)
        model.save_pretrained(args.output, safe_serialization=True)
        merged = Weights(args.output, stack)
        original = Weights(args.base, stack)
        assert set(merged.files) == set(intermediate.files) == set(original.files)
        untouched = sorted(set(original.files) - TARGETS)
        for key in untouched:
            assert bits_equal(merged[key], original[key]), key
        sample = random.Random(3407).sample(sorted(TARGETS), 3)
        for key in sample:
            previous = intermediate[key]
            delta = a.delta(key.removesuffix(".weight"), previous.shape).bfloat16()
            expected = torch.add(previous, delta)
            final = merged[key]
            assert bits_equal(final, expected), key
            assert bits_equal(final - previous, expected - previous), key
        copied = {}
        for path in args.base.iterdir():
            if path.is_file() and path.suffix in {".json", ".jinja", ".txt"} and path.name not in {
                    "config.json", "model.safetensors.index.json"}:
                shutil.copyfile(path, args.output / path.name)
                copied[path.name] = sha(args.output / path.name)
                assert copied[path.name] == sha(path), path.name
        result = {
            "status": "PASS", "base_sha256": BASE_HASHES, "adapter_a": a.proof, "adapter_b": b.proof,
            "merge_order": ["D3-e1", "A-step30"], "delta_rounding": "fp32 matmul and scale, then bf16 before add",
            "d3_intermediate_sha256": intermediate_hashes, "d3_reference_sha256": REFERENCE_HASHES,
            "d3_tensors_bit_equal": len(reference.files), "untouched_tensors_bit_equal": len(untouched),
            "checked_a_step_modules": sample, "checked_a_step_seed": 3407,
            "copied_original_sha256": copied, "ab1_sha256": shard_hashes(args.output),
        }
        write_json(args.records / "merge_receipt.json", result)
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("base", "a", "b", "reference", "intermediate", "output", "records"):
        parser.add_argument(f"--{arg}", required=True, type=Path)
    run(parser.parse_args())
