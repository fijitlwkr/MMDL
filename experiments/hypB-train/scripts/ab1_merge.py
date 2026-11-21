"""Verify and save the fixed fp32 sum of the A-step30 and D3-e1 LoRA deltas."""

import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import random
import re
import shutil

import torch
from safetensors import safe_open
from safetensors.torch import save_file

REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"
BASE_HASHES = {
    "model-00001-of-00002.safetensors": "30a01a0556622645a3cce87b655bbbbbc1f170c196099f1b666c93202c3339a9",
    "model-00002-of-00002.safetensors": "046296a2a387efb43b0c997d5833c789604d168834f6e0d3064bf7bb13d002a6",
}
MODULES = {
    f"model.language_model.layers.{layer}.{group}.{projection}_proj"
    for layer in range(36)
    for group, projections in (("self_attn", "q k v o"), ("mlp", "gate up down"))
    for projection in projections.split()
}
ADAPTER_KEY = re.compile(r"(?:base_model\.model\.)?(model\.language_model\..+)\.lora_([AB])\.weight")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")


class Adapter:
    def __init__(self, path, stack):
        config = json.loads((path / "adapter_config.json").read_bytes())
        assert config["peft_type"] == "LORA" and config["r"] == 16 and config["lora_alpha"] == 32
        assert Path(config["base_model_name_or_path"]).name == REVISION
        assert config["bias"] == "none"
        for field in ("use_rslora", "use_dora", "use_qalora", "use_bdlora", "fan_in_fan_out",
                      "rank_pattern", "alpha_pattern", "modules_to_save", "lora_bias",
                      "layer_replication", "target_parameters", "alora_invocation_tokens"):
            assert not config.get(field), (path, field)
        self.reader = stack.enter_context(safe_open(path / "adapter_model.safetensors", framework="pt"))
        self.keys = {}
        for key in self.reader.keys():
            match = ADAPTER_KEY.fullmatch(key)
            assert match, (path, key)
            module, factor = match.groups()
            assert (module, factor) not in self.keys
            self.keys[module, factor] = key
        assert set(self.keys) == {(module, factor) for module in MODULES for factor in "AB"}, path
        self.proof = {"modules": len(MODULES), "visual_merger_lm_head_modules": 0,
                      "rank": 16, "alpha": 32, "rslora": False, "dora": False,
                      "factor_dtypes": dict(Counter(self.reader.get_slice(key).get_dtype()
                                                    for key in self.keys.values())),
                      "sha256": {name: sha(path / name) for name in
                                 ("adapter_config.json", "adapter_model.safetensors")}}

    def delta(self, module, size):
        a, b = (self.reader.get_tensor(self.keys[module, factor]).float() for factor in "AB")
        assert a.shape == (16, size[1]) and b.shape == (size[0], 16), module
        return (b @ a).mul_(2)


def index(path):
    return json.loads((path / "model.safetensors.index.json").read_bytes())["weight_map"]


def max_ulp(left, right):
    assert left.dtype == right.dtype == torch.bfloat16 and left.shape == right.shape
    def ordered(tensor):
        bits = tensor.view(torch.int16).to(torch.int32)
        return torch.where(bits < 0, -32768 - bits, bits)
    return int((ordered(left) - ordered(right)).abs().max())


def run(args):
    assert args.base.name == REVISION
    assert {name: sha(args.base / name) for name in BASE_HASHES} == BASE_HASHES
    assert not args.output.exists()
    base_index, reference_index = index(args.base), index(args.reference)
    assert set(base_index) == set(reference_index)
    assert {f"{module}.weight" for module in MODULES} <= set(base_index)
    reference_hashes = {name: sha(args.reference / name) for name in sorted(set(reference_index.values()))}
    sample = set(random.Random(3407).sample(sorted(MODULES), 3))
    ulps, unchanged, residuals = {}, [], {}
    with ExitStack() as stack:
        a, b = (Adapter(path, stack) for path in (args.a, args.b))
        assert set(a.keys) == set(b.keys)
        reference = {
            name: stack.enter_context(safe_open(args.reference / name, framework="pt"))
            for name in reference_hashes
        }
        args.output.mkdir()
        for shard in BASE_HASHES:
            tensors = {}
            with safe_open(args.base / shard, framework="pt") as original:
                assert set(original.keys()) == {key for key, file in base_index.items() if file == shard}
                for key in original.keys():
                    weight = original.get_tensor(key)
                    assert weight.dtype == torch.bfloat16
                    module = key.removesuffix(".weight")
                    if module not in MODULES:
                        tensors[key] = weight
                        continue
                    base = weight.float()
                    db = b.delta(module, weight.shape)
                    reference_weight = reference[reference_index[key]].get_tensor(key)
                    ulps[key] = max_ulp((base + db).bfloat16(), reference_weight)
                    assert ulps[key] <= 1, (key, "D3-e1 differs from PEFT (bf16 ULP)", ulps[key])
                    da = a.delta(module, weight.shape)
                    delta = da + db
                    combined = (base + delta).bfloat16()
                    assert torch.isfinite(combined).all(), key
                    tensors[key] = combined
                    if module in sample:
                        observed = combined.float() - base
                        error = (observed - delta).abs()
                        target = base + delta
                        away = torch.where(target >= combined.float(), float("inf"), -float("inf"))
                        neighbor = torch.nextafter(combined, away.bfloat16()).float()
                        allowance = (neighbor - combined.float()).abs() / 2
                        allowance += torch.finfo(torch.float32).eps * (base.abs() + delta.abs())
                        assert (error <= allowance).all(), (key, "AB1 delta residual")
                        residuals[key] = {"max_abs_error": float(error.max()),
                                          "max_rounding_allowance": float(allowance.max())}
                save_file(tensors, args.output / shard, metadata={"format": "pt"})
                with safe_open(args.output / shard, framework="pt") as saved:
                    for key, weight in tensors.items():
                        assert torch.equal(saved.get_tensor(key).view(torch.int16), weight.view(torch.int16)), key
                        if key.removesuffix(".weight") not in MODULES:
                            unchanged.append(key)
            print("Verified shard", shard, flush=True)
        assert len(ulps) == 252 and len(unchanged) + 252 == len(base_index) and len(residuals) == 3
        copied = {}
        for source in args.base.iterdir():
            if source.is_file() and source.suffix in {".json", ".jinja", ".txt"}:
                shutil.copyfile(source, args.output / source.name)
                copied[source.name] = sha(args.output / source.name)
                assert copied[source.name] == sha(source), source.name
        result = {
            "status": "PASS", "base_sha256": BASE_HASHES, "adapter_a": a.proof, "adapter_b": b.proof,
            "mode": "fp32 M0 + (2 BA_A + 2 BA_B), saved bf16",
            "d3_peft_0_17_1_sha256": reference_hashes, "d3_max_ulp_by_tensor": ulps,
            "d3_max_ulp": max(ulps.values()), "untouched_base_tensors_bytes_equal": len(unchanged),
            "random_module_residuals": residuals, "random_module_seed": 3407,
            "copied_original_sha256": copied,
            "ab1_sha256": {name: sha(args.output / name) for name in BASE_HASHES},
        }
        write_json(args.receipt, result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("base", "a", "b", "reference", "output", "receipt"):
        parser.add_argument(f"--{argument}", type=Path, required=True)
    run(parser.parse_args())
