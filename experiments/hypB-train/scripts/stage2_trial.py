"""Verify staged inputs, run the fixed M0 trial, and package its evidence."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time

from classify_answers import ROOT, read_rows, write_json
from reward import reward
from sample_m0 import CONFIG, CONFIG_SHA, MARKERS, read_raw, request_seed, seed_index, sha

DATA = ROOT / "data"
RECORDS = ROOT / "records"
IMAGE_ROOT = ROOT / "image_tree"
RUN = DATA / "trial_100_run"
POOL = DATA / "r1_pool.jsonl"
TRIAL = DATA / "trial_100.jsonl"
DATASET = "MMDL-team4/hypB-train-data"
DATASET_REV = "1833bac3be047aa8bd146492436323bb7c14092a"
A_PREFIX = "work/train_data_B_20261023/final_v5_tech_20261025/"
BASE_REV = "ebb281ec70b05090aa6165b016eac8ec08e71b17"


def verify_inputs():
    manifest = json.loads((ROOT / "input_sha256.json").read_text(encoding="utf-8"))
    for name, expected in manifest.items():
        path = (ROOT / name).resolve(strict=True)
        assert path.is_relative_to(ROOT) and sha(path) == expected, name
    assert sha(CONFIG) == CONFIG_SHA
    assert sha(POOL) == "81b0485c14e9859df3e78dd69bf123ae80e187b7a61b117aa2d3359a6a757c96"
    assert sha(TRIAL) == "651d813f6fb75d534c3ef8a24640233e1f76d38bbe2537af70cca47805497e5f"
    pool = {r["row"]: r for r in read_rows(POOL)}
    assert len(pool) == 1500
    trial = read_rows(TRIAL)
    assert len(trial) == len({r["row"] for r in trial}) == 100
    assert all(r["pool_sha256"] == sha(POOL) and r["row"] in pool for r in trial)
    with (DATA / "images_B_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        images = list(csv.DictReader(handle))
    assert len(images) == 140 and Counter(r["origin"] for r in images) == {"B": 139, "C": 1}
    assert {r["row"] for r in images} == {r["row"] for r in pool.values() if r["origin"] in ("B","C")}
    for row in images:
        entry, = pool[row["row"]]["images"]
        assert entry["path"] == row["path"] and entry["sha256"] == row["sha256"]
        image = (IMAGE_ROOT / row["path"]).resolve(strict=True)
        assert image.is_relative_to(IMAGE_ROOT) and sha(image) == row["sha256"]
        assert image.stat().st_size == int(row["bytes"])
    write_json(RECORDS / "input_verification.json",
               {"status": "PASS", "verified_files": len(manifest), "bc_images": len(images),
                "pool_sha256": sha(POOL), "trial_sha256": sha(TRIAL), "config_sha256": sha(CONFIG),
                "manifest_sha256": sha(ROOT / "input_sha256.json")})
    return [pool[r["row"]] for r in trial]


def prepare_images(selected):
    from huggingface_hub import HfApi, hf_hub_download, try_to_load_from_cache

    with (DATA / "A_image_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        manifest = {r["path"]: r for r in csv.DictReader(handle)}
    wanted = {}
    for row in selected:
        if row["origin"] != "A":
            continue
        for image in row["images"]:
            assert image["path"].startswith(A_PREFIX)
            name = image["path"].removeprefix(A_PREFIX)
            check = manifest[name]
            assert check["row"] == row["row"] and check["sha256"] == image["sha256"]
            assert int(check["bytes"]) == image["bytes"]
            wanted[name] = image
    assert len(wanted) == 88
    try:
        info = HfApi().dataset_info(DATASET, revision="v1.1")
    except Exception as error:
        raise RuntimeError(f"HF dataset metadata failed ({type(error).__name__})") from None
    assert info.sha == DATASET_REV and wanted.keys() <= {s.rfilename for s in info.siblings}
    print("DATASET_REVISION_VERIFIED", DATASET_REV, "A_IMAGES", len(wanted), flush=True)

    def stage(name):
        entry = wanted[name]
        path = (IMAGE_ROOT / entry["path"]).resolve()
        assert path.is_relative_to(IMAGE_ROOT)
        found = try_to_load_from_cache(DATASET, name, repo_type="dataset", revision=DATASET_REV)
        cache_hit = isinstance(found, str) and Path(found).is_file()
        if not cache_hit:
            try:
                found = hf_hub_download(DATASET, name, repo_type="dataset", revision=DATASET_REV,
                                        cache_dir=ROOT / "hf_image_download")
            except Exception as error:
                status = getattr(getattr(error, "response", None), "status_code", None)
                raise RuntimeError(f"HF image failed: {name}, {type(error).__name__}, HTTP {status}") from None
        source = Path(found)
        assert source.stat().st_size == entry["bytes"] and sha(source) == entry["sha256"], name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
        assert sha(path) == entry["sha256"], name
        return {"file": name, "cached_at_pinned_revision": cache_hit, "sha256": entry["sha256"],
                "bytes": entry["bytes"]}

    rows = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        for row in executor.map(stage, sorted(wanted)):
            rows.append(row)
            if len(rows) % 10 == 0 or len(rows) == len(wanted):
                print(f"A_IMAGE_HASH_OK {len(rows)}/{len(wanted)}", flush=True)
    write_json(RECORDS / "A_image_verification.json",
               {"status": "PASS", "dataset": DATASET, "revision": DATASET_REV, "images": rows})


def run_trial(selected):
    base = Path("/workspace/hf_cache/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots") / BASE_REV
    sizes = {p.name: p.stat().st_size for p in base.glob("model-*.safetensors")}
    assert len(sizes) == 2 and sum(sizes.values()) == 8_875_719_344
    assert (base / "config.json").is_file() and (base / "tokenizer.json").is_file()
    write_json(RECORDS / "model_reuse.json", {"revision": BASE_REV, "cache_path": str(base), "shards": sizes})
    stop = threading.Event()
    metrics = []

    def monitor():
        while not stop.is_set():
            started = time.monotonic()
            cmd = ["nvidia-smi", "--query-gpu=index,memory.used,memory.total,utilization.gpu",
                   "--format=csv,noheader,nounits"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=True)
            gpu, used, total, util = (int(x.strip()) for x in result.stdout.strip().split(","))
            metrics.append((started, gpu, used, total, util))
            with (RECORDS / "gpu_memory.csv").open("a", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerow(metrics[-1])
            stop.wait(1)

    assert not RUN.exists()
    (RECORDS / "gpu_memory.csv").write_text("monotonic_seconds,gpu,used_mib,total_mib,util_pct\n",
                                           encoding="utf-8")
    cmd = [sys.executable, "-B", str(ROOT / "scripts/sample_m0.py"), "--run", "--pool-jsonl", str(POOL),
           "--image-root", str(IMAGE_ROOT), "--stratified-trial", "--limit", "100", "--k", "4",
           "--out", str(RUN)]
    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    started = time.monotonic()
    try:
        with (RECORDS / "sampling.log").open("w", encoding="utf-8") as handle:
            subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT, check=True)
    finally:
        elapsed = time.monotonic() - started
        stop.set()
        monitor_thread.join()
    assert len(metrics) > 10 and len({x[1] for x in metrics}) == 1
    text = (RECORDS / "sampling.log").read_text(encoding="utf-8")
    times = re.findall(r"Completed 400/400 responses \(([0-9.]+)s\)", text)
    assert len(times) == 1
    expected = {(r["row"], j): r for r in selected for j in range(4)}
    raw = read_raw(RUN / "raw.jsonl")
    for row in raw:
        key = row["row"], row["repeat"]
        item = expected.pop(key)
        assert row["seed"] == request_seed(seed_index(item), row["repeat"])
        assert row["prompt_tokens"] == item["prompt_tokens"]
        assert 0 < row["output_tokens"] <= 8192
        assert row["finish_reason"] in ("stop", "length")
        assert row["finish_reason"] != "length" or row["output_tokens"] == 8192
        assert (row["reward"], row["reward_reason"]) == reward(row["raw_text"], row["finish_reason"], item)
        assert row["marker_count"] == len(MARKERS.findall(row["raw_text"]))
    assert len(raw) == 400 and not expected
    subprocess.run([sys.executable, "-B", str(ROOT / "scripts/build_groups.py"), str(RUN),
                    "--pool-jsonl", str(POOL), "--out", str(RUN / "groups.json")], check=True)
    write_json(RECORDS / "trial_run_summary.json",
               {"status": "PASS", "responses": 400, "seconds_in_sampling": float(times[0]),
                "seconds_including_engine_init": elapsed, "peak_gpu_used_mib": max(x[2] for x in metrics),
                "nvidia_smi_samples": len(metrics), "raw_sha256": sha(RUN / "raw.jsonl")})


def package():
    recorded = ("torch_before.json", "torch_after.json", "pip_check.txt", "packages.json",
                "install_block_sha256.txt", "install_console.log", "input_verification.json",
                "A_image_verification.json", "model_reuse.json", "gpu_memory.csv", "sampling.log",
                "trial_run_summary.json", "trial_console.log")
    files = [(RUN / name, name) for name in ("raw.jsonl", "manifest.json", "groups.json")]
    files += [(RECORDS / name, f"records/{name}") for name in recorded]
    files.append((RECORDS / "base_install/logs/01_install.log", "records/01_install.log"))
    manifest = {name: sha(path) for path, name in files}
    write_json(RECORDS / "trial_results_sha256.json", manifest)
    archive = ROOT / "trial_100_results.tar.gz"
    with tarfile.open(archive, "x:gz", compresslevel=1) as handle:
        for path, name in files + [(RECORDS / "trial_results_sha256.json", "SHA256SUMS.json")]:
            handle.add(path, arcname=name, recursive=False)
    print("ARCHIVE_SHA256", sha(archive), archive.stat().st_size, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("verify", "images", "sample", "package"))
    step = parser.parse_args().step
    if step == "verify":
        verify_inputs()
        print("SCP_INPUTS_VERIFIED", flush=True)
    elif step == "images":
        prepare_images(verify_inputs())
    elif step == "sample":
        run_trial(verify_inputs())
    else:
        package()
