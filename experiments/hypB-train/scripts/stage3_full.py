"""Prepare and validate the fixed R1 K=4 run around the existing sampler."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
import os
import random
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from classify_answers import read_rows, write_json, write_rows
from reward_v2 import reward
from sample_m0 import CONFIG, CONFIG_SHA, MARKERS, REWARD_V2_SHA, SEED, evaluate, read_raw, request_seed, seed_index, sha
from stage2_trial import A_PREFIX, BASE_REV, DATA, DATASET, DATASET_REV, IMAGE_ROOT, POOL, RECORDS, ROOT


RUN = DATA / "full_k4"
LOGS = RECORDS / "full_k4"
TRAIN = DATA / "r1_train.jsonl"
POOL_SHA = "81b0485c14e9859df3e78dd69bf123ae80e187b7a61b117aa2d3359a6a757c96"


def prepare():
    from huggingface_hub import hf_hub_download, try_to_load_from_cache

    assert sha(CONFIG) == CONFIG_SHA and sha(POOL) == POOL_SHA
    assert sha(ROOT / "scripts/reward_v2.py") == REWARD_V2_SHA
    rows = read_rows(POOL)
    assert Counter(row["origin"] for row in rows) == {"A": 1360, "B": 139, "C": 1}
    assert len({row["row"] for row in rows}) == 1500
    with (DATA / "A_image_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        a_manifest = {row["path"]: row for row in csv.DictReader(handle)}
    with (DATA / "images_B_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        bc_manifest = {row["row"]: row for row in csv.DictReader(handle)}
    assert bc_manifest.keys() == {row["row"] for row in rows if row["origin"] != "A"}

    def stage(row):
        origin = row["origin"]
        image, = row["images"]
        relative = image["path"]
        path = (IMAGE_ROOT / relative).resolve()
        assert path.is_relative_to(IMAGE_ROOT)
        if origin == "A":
            assert relative.startswith(A_PREFIX)
            name = relative.removeprefix(A_PREFIX)
            entry = a_manifest[name]
        else:
            entry = bc_manifest[row["row"]]
            assert relative == entry["path"] and origin == entry["origin"]
        size = int(entry["bytes"])
        assert entry["row"] == row["row"] and entry["sha256"] == image["sha256"]
        assert size == image["bytes"]
        source = "staged"
        if origin == "A" and not path.exists():
            cached = try_to_load_from_cache(DATASET, name, repo_type="dataset", revision=DATASET_REV)
            source = "pinned_cache"
            if not isinstance(cached, str) or not Path(cached).is_file():
                source = "pinned_download"
                try:
                    cached = hf_hub_download(DATASET, name, repo_type="dataset", revision=DATASET_REV,
                                             cache_dir=LOGS / "hf_image_download")
                except Exception as error:
                    status = getattr(getattr(error, "response", None), "status_code", None)
                    raise RuntimeError(f"HF image {name}: {type(error).__name__}, HTTP {status}") from None
            assert Path(cached).stat().st_size == size and sha(Path(cached)) == image["sha256"], name
            path.parent.mkdir(parents=True, exist_ok=True)
            pending = path.with_name(path.name + ".stage3.tmp")
            shutil.copyfile(cached, pending)
            pending.replace(path)
        assert path.stat().st_size == size and sha(path) == image["sha256"], relative
        return {"row": row["row"], "origin": origin, "path": relative, "source": source,
                "bytes": size, "sha256": image["sha256"]}

    images = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        for index, image in enumerate(executor.map(stage, rows), 1):
            images.append(image)
            if index % 150 == 0:
                print(f"IMAGE_HASH_OK {index}/1500", flush=True)
    assert len({image["path"] for image in images}) == 1500
    model = Path(os.environ["HF_HOME"]) / "hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots" / BASE_REV
    shards = {path.name: path.stat().st_size for path in model.glob("model-*.safetensors")}
    assert len(shards) == 2 and sum(shards.values()) == 8_875_719_344
    assert (model / "config.json").is_file() and (model / "tokenizer.json").is_file()
    write_json(LOGS / "image_verification.json", {"dataset": DATASET, "tag": "v1.1", "revision": DATASET_REV,
               "origins": Counter(image["origin"] for image in images),
               "sources": Counter(image["source"] for image in images), "images": images})
    write_json(LOGS / "model_reuse.json", {"revision": BASE_REV, "cache_path": str(model), "shards": shards})


def finish():
    pool = read_rows(POOL)
    pool_by_row = {row["row"]: row for row in pool}
    manifest = evaluate.read_json(RUN / "manifest.json")
    assert manifest["pool_sha256"] == sha(POOL) == POOL_SHA and manifest["config_sha256"] == CONFIG_SHA
    assert manifest["model"]["revision"] == BASE_REV and manifest["k"] == 4
    assert manifest["reward_version"] == "v2" and manifest["reward_sha256"] == REWARD_V2_SHA
    assert manifest["rows"] == list(pool_by_row)
    raw = read_raw(RUN / "raw.jsonl")
    expected = {(row, repeat) for row in pool_by_row for repeat in range(4)}
    for sample in raw:
        row, repeat = sample["row"], sample["repeat"]
        expected.remove((row, repeat))
        item = pool_by_row[row]
        assert sample["seed"] == request_seed(seed_index(item), repeat)
        assert sample["prompt_tokens"] == item["prompt_tokens"]
        finish_reason = sample["finish_reason"]
        assert finish_reason in ("stop", "length")
        assert 0 < sample["output_tokens"] <= 8192 and (finish_reason != "length" or sample["output_tokens"] == 8192)
        assert (sample["reward"], sample["reward_reason"]) == reward(sample["raw_text"], finish_reason, item)
        assert sample["marker_count"] == len(MARKERS.findall(sample["raw_text"]))
    assert not expected and len(raw) == 6000
    subprocess.run([sys.executable, "-B", str(ROOT / "scripts/build_groups.py"), str(RUN),
                    "--out", str(RUN / "groups.json")], check=True)
    groups = evaluate.read_json(RUN / "groups.json")
    included = {row["row"] for row in groups["groups"] if row["group"] in ("target", "retain")}
    training = [row for row in pool if row["row"] in included]
    assert len(training) == len(included) == groups["counts"].get("target", 0) + groups["counts"].get("retain", 0)
    random.Random(SEED).shuffle(training)
    pending = TRAIN.with_suffix(".jsonl.stage3.tmp")
    write_rows(pending, training)
    if TRAIN.exists():
        assert sha(pending) == sha(TRAIN), "Existing r1_train.jsonl differs"
        pending.unlink()
    else:
        pending.rename(TRAIN)
    print(f"VALIDATED {len(raw)} RESPONSES, {len(training)} TRAIN ITEMS", flush=True)


def package():
    files = [(RUN / name, name) for name in ("raw.jsonl", "manifest.json", "groups.json")]
    files += [(TRAIN, "r1_train.jsonl")]
    files += [(LOGS / name, f"records/{name}") for name in (
        "input_sha256.txt", "input_verification.log", "environment.log", "image_verification.json",
        "model_reuse.json", "prepare.log", "sampling.log", "gpu_memory.csv", "timing.log", "finish.log")]
    checks = LOGS / "SHA256SUMS.json"
    write_json(checks, {name: sha(path) for path, name in files})
    archive = LOGS / "full_k4_results.tar.gz"
    pending = archive.with_suffix(".gz.tmp")
    with tarfile.open(pending, "w:gz", compresslevel=1) as handle:
        for path, name in files + [(checks, checks.name)]:
            handle.add(path, arcname=name, recursive=False)
    pending.replace(archive)
    print(f"ARCHIVE_SHA256 {sha(archive)} {archive.stat().st_size}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("prepare", "finish", "package"))
    {"prepare": prepare, "finish": finish, "package": package}[parser.parse_args().step]()
