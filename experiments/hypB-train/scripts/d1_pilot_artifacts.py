"""Prepare pinned D1 inputs, then merge, load, and package the pilot evidence."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import shutil
import tarfile

from dpo_train import CONFIG, DATA_SHA256


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DATA = ROOT / "data"
IMAGES = ROOT / "image_tree"
PILOT = ROOT / "artifacts/pilot"
CHECKPOINT = PILOT / "checkpoint-20"
MERGED = ROOT / "artifacts/merged_pilot"
HF = Path("/workspace/hf_cache/hub")
BASE = HF / "models--Qwen--Qwen3-VL-4B-Instruct/snapshots" / CONFIG["model_revision"]
DATASET = "MMDL-team4/hypB-train-data"
REVISION = "1833bac3be047aa8bd146492436323bb7c14092a"
A_PREFIX = "work/train_data_B_20261023/final_v5_tech_20261025/"


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare():
    from huggingface_hub import hf_hub_download, try_to_load_from_cache

    sums = json.loads((DATA / "d1_input_sha256.json").read_bytes())
    for name, expected in sums.items():
        path = (ROOT / name).resolve(strict=True)
        assert path.is_relative_to(ROOT) and sha(path) == expected, name
    assert sums["data/d1_pairs_swift.jsonl"] == DATA_SHA256
    items = json.loads((DATA / "d1_image_manifest.json").read_bytes())
    expected_paths = {item["path"] for item in items}
    with (DATA / "d1_pairs_swift.jsonl").open(encoding="utf-8") as handle:
        pairs = [json.loads(line) for line in handle]
    assert len(pairs) == 707 and len(expected_paths) == len(items) == 548
    assert {path for pair in pairs for path in pair["images"]} == expected_paths

    def stage(item):
        path = (IMAGES / item["path"]).resolve()
        assert path.is_relative_to(IMAGES)
        src = "scp"
        if item["origin"] == "A":
            assert item["path"].startswith(A_PREFIX)
            name = item["path"].removeprefix(A_PREFIX)
            found = try_to_load_from_cache(DATASET, name, repo_type="dataset", revision=REVISION)
            src = "pinned_cache"
            if not isinstance(found, str) or not Path(found).is_file():
                src = "pinned_download"
                try:
                    found = hf_hub_download(DATASET, name, repo_type="dataset", revision=REVISION,
                                            cache_dir=ROOT / "cache/d1_hf_images")
                except Exception as error:
                    status = getattr(getattr(error, "response", None), "status_code", None)
                    raise RuntimeError(f"HF image {name}: {type(error).__name__}, HTTP {status}") from None
            source = Path(found)
            assert source.stat().st_size == item["bytes"] and sha(source) == item["sha256"], name
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                partial = path.with_suffix(".png.partial")
                shutil.copyfile(source, partial)
                partial.rename(path)
        assert path.stat().st_size == item["bytes"] and sha(path) == item["sha256"], item["path"]
        return {**item, "verified_source": src}

    verified = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        for index, row in enumerate(executor.map(stage, items), 1):
            verified.append(row)
            if index % 100 == 0 or index == 548:
                print(f"D1_IMAGES_VERIFIED {index}/548", flush=True)
    shards = {p.name: p.stat().st_size for p in BASE.glob("model-*.safetensors")}
    assert len(shards) == 2 and sum(shards.values()) == 8_875_719_344
    assert (BASE / "config.json").is_file() and (BASE / "tokenizer.json").is_file()
    save(REPORTS / "input_verification.json", {"files": sums, "dataset_revision": REVISION,
         "origins": Counter(r["origin"] for r in verified), "sources": Counter(r["verified_source"] for r in verified),
         "images": verified, "model_revision": CONFIG["model_revision"], "model_shards": shards})


def merge():
    import torch
    from peft import PeftModel
    from safetensors import safe_open
    from transformers import Qwen3VLForConditionalGeneration

    assert not MERGED.exists()
    adapter = CHECKPOINT / "adapter_model.safetensors"
    with safe_open(adapter, framework="pt", device="cpu") as tensors:
        names = list(tensors.keys())
    assert len(names) == 504 and all("language_model.layers." in name and ".lora_" in name for name in names)
    base = Qwen3VLForConditionalGeneration.from_pretrained(BASE, dtype=torch.bfloat16,
                                                            attn_implementation="sdpa", device_map="cpu")
    model = PeftModel.from_pretrained(base, CHECKPOINT).merge_and_unload(safe_merge=True)
    model.save_pretrained(MERGED, safe_serialization=True)
    for path in BASE.iterdir():
        if path.suffix in {".json", ".jinja", ".txt"} and path.name not in {"config.json", "model.safetensors.index.json"}:
            shutil.copyfile(path, MERGED / path.name)
    hashes = {path.name: sha(path) for path in sorted(MERGED.glob("*.safetensors"))}
    assert hashes
    save(REPORTS / "merge.json", {"adapter_sha256": sha(adapter), "adapter_tensors": len(names), "merged_shards": hashes})


def load():
    import yaml
    from frozen_generation.vllm_engine import VLLMEngine

    config = ROOT / "scripts/frozen_generation/config.yaml"
    assert sha(config) == "3946c9a93cd5ab1cc5a8010fc00473e8a71f1c589e0a5f664edb70a3097234dc"
    assert version("vllm") == "0.11.0"
    engine = VLLMEngine(yaml.safe_load(config.read_text(encoding="utf-8")), MERGED)
    save(REPORTS / "vllm_load.json", {"version": version("vllm"), "initialization_seconds": engine.init_seconds,
                                      "generation_requests": 0, "config_sha256": sha(config)})


def package():
    required = ("args.json", "logging.jsonl", "pilot_observations.jsonl")
    assert all((PILOT / name).is_file() for name in required)
    assert (CHECKPOINT / "adapter_model.safetensors").is_file() and (CHECKPOINT / "adapter_config.json").is_file()
    paths = {f"reports/{path.name}": path for path in REPORTS.iterdir() if path.is_file() and path.suffix != ".gz"}
    paths.update({f"reports/{name}": PILOT / name for name in required})
    paths.update({f"adapter/{path.relative_to(CHECKPOINT).as_posix()}": path for path in CHECKPOINT.rglob("*") if path.is_file()})
    sums = ROOT / "artifact_sha256.json"
    save(sums, {name: sha(path) for name, path in paths.items()})
    archive = ROOT / "d1_pilot_results.tar.gz"
    with tarfile.open(archive, "x:gz", compresslevel=1) as handle:
        for name, path in paths.items():
            handle.add(path, arcname=name, recursive=False)
        handle.add(sums, arcname=sums.name)
    print("ARCHIVE_SHA256", sha(archive), archive.stat().st_size, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("prepare", "merge", "load", "package"))
    {"prepare": prepare, "merge": merge, "load": load, "package": package}[parser.parse_args().step]()
