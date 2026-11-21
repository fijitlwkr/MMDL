#!/usr/bin/env bash
set -Eeuo pipefail
cd /workspace/train_AB2
export HF_HOME=/workspace/hf_cache HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
export PYTHONDONTWRITEBYTECODE=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=8 MKL_NUM_THREADS=8
export VLLM_ENABLE_V1_MULTIPROCESSING=0 VLLM_WORKER_MULTIPROC_METHOD=spawn VLLM_USE_FLASHINFER_SAMPLER=0
export XDG_CACHE_HOME=/workspace/train_C1/c1_cache
export TRITON_CACHE_DIR=$XDG_CACHE_HOME/triton CUDA_CACHE_PATH=$XDG_CACHE_HOME/cuda
export TORCHINDUCTOR_CACHE_DIR=$XDG_CACHE_HOME/torchinductor VLLM_CACHE_ROOT=$XDG_CACHE_HOME/vllm
export TMPDIR=/workspace/train_AB2/tmp
train=/workspace/train_D1/.venv-train/bin/python
eval_python=/workspace/train_D1/.venv-eval/bin/python
base=/workspace/hf_cache/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/ebb281ec70b05090aa6165b016eac8ec08e71b17
a=/workspace/train_AB2/adapter_A/step100
b=/workspace/eval_D3e1_20261113/adapter/D3e1
root=/workspace/train_AB2/work/train_RL_20261106
models=/workspace/train_AB2/models
records=$root/reports/ab2_merge
reference=/workspace/eval_D3e1_20261113/models/D3e1
intermediate=$models/D3-e1-method-check
ab2=$models/AB2
trap 'rc=$?; printf "%s stage=%s status=%s\n" "$(date -Is)" "$stage" "$rc" >&2' ERR
mark() { stage=$1; echo "$stage" > stage.txt; printf '%s %s\n' "$(date -Is)" "$stage"; }

mark preflight
test ! -e "$models"
test ! -e "$records"
test ! -e "$root/data/ab2_dev"
test ! -e "$root/runs/ab2_dev"
test ! -L "$root/runs/ab2_dev"
test ! -e "$root/reports/ab2_dev"
mkdir "$models" "$TMPDIR" "$records"
(cd "$root" && sha256sum -c reports/ab2_inputs.sha256)
sha256sum -c A_SHA256SUMS
printf '%s\n' \
  "53b1ee59b11807c6d6df008bdaca3d1be6b89195f780054f5929fb1fddc7671f  $b/adapter_model.safetensors" \
  "fe8ddf9b08ec8dab42a42a55072360d9dbe9a944b10d2a76a3441f34e7a32d58  $b/adapter_config.json" \
  "30a01a0556622645a3cce87b655bbbbbc1f170c196099f1b666c93202c3339a9  $base/model-00001-of-00002.safetensors" \
  "046296a2a387efb43b0c997d5833c789604d168834f6e0d3064bf7bb13d002a6  $base/model-00002-of-00002.safetensors" | sha256sum -c
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader > "$records/gpu.txt"
test "$(wc -l < "$records/gpu.txt")" -eq 1
grep -q 'NVIDIA GeForce RTX 4090,' "$records/gpu.txt"
"$train" -c 'from importlib.metadata import version; assert version("peft")=="0.17.1" and version("torch")=="2.8.0+cu128"; print({n:version(n) for n in ["torch","peft","transformers","safetensors"]})' > "$records/merge_versions.txt"
"$eval_python" -c 'from importlib.metadata import version; assert version("vllm")=="0.11.0" and version("torch")=="2.8.0+cu128"; print({n:version(n) for n in ["torch","vllm","transformers","tokenizers","qwen-vl-utils"]})' > "$records/eval_versions.txt"

"$eval_python" -B "$root/scripts/ab1_select.py" --self-test --out "$records/dev_self_test.json" > "$records/dev_self_test.log" 2>&1

mark sequential_merge
"$train" -u "$root/scripts/ab2_merge.py" --base "$base" --a "$a" --b "$b" --reference "$reference" \
    --intermediate "$intermediate" --output "$ab2" --records "$records" > "$records/sequential_merge.log" 2>&1
"$train" - "$intermediate" "$records" <<'PY'
import hashlib, json, shutil, sys
from pathlib import Path
intermediate, records = map(Path, sys.argv[1:])
assert intermediate.resolve() == intermediate == Path("/workspace/train_AB2/models/D3-e1-method-check")
with (records / "merge_receipt.json").open() as stream:
    values = json.load(stream)
assert values["status"] == "PASS"
hashes = values["d3_intermediate_sha256"]
for name, expected in hashes.items():
    with (intermediate / name).open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == expected
shutil.rmtree(intermediate)
with (records / "reference_cleanup.json").open("x") as stream:
    json.dump({"deleted": str(intermediate), "verified_sha256": hashes}, stream, indent=2)
PY

mark vllm_load
cd "$root"
PYTHONPATH="$root/scripts" "$eval_python" -u - "$ab2" "$records" > "$records/vllm_load.log" 2>&1 <<'PY'
import json, sys
from pathlib import Path
import yaml
from frozen_generation.vllm_engine import VLLMEngine
model, records = map(Path, sys.argv[1:])
config = yaml.safe_load(Path("scripts/frozen_generation/config.yaml").read_bytes())
engine = VLLMEngine(config, model)
with (records / "vllm_load.json").open("x") as stream:
    json.dump({"status": "PASS", "vllm": "0.11.0", "generation_requests": 0,
               "initialization_seconds": engine.init_seconds, "memory": engine.memory_report()}, stream, indent=2)
PY

cd /workspace/train_AB2
mark development
cd "$root"
mkdir -p runs
ln -s "$root/data/ab2_dev" runs/ab2_dev
nvidia-smi --query-gpu=timestamp,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits -l 1 > "$records/dev_vram.csv" &
monitor=$!
trap 'kill "$monitor" 2>/dev/null || true' EXIT
"$eval_python" -u scripts/d3_sample_dev.py --run --pool-jsonl data/r1_pool.jsonl --questions-jsonl data/d3_dev.jsonl \
    --repeat-start 4 --k 4 --reward-v2 --model-path "$ab2" --image-root /workspace/train_D3_SD1 \
    --out "$root/data/ab2_dev/AB2" > "$records/development.log" 2>&1
kill "$monitor" 2>/dev/null || true
trap - EXIT
cd /workspace/train_AB2
mark gate
cd "$root"
mkdir reports/ab2_dev
"$eval_python" -u scripts/ab1_select.py --m0 runs/d3sd1_dev/M0/raw.jsonl --d3 runs/d3sd1_dev/D3-e1/raw.jsonl \
    --ab1 runs/ab2_dev/AB2/raw.jsonl --out reports/ab2_dev/result.json
(cd runs/ab2_dev/AB2 && sha256sum raw.jsonl manifest.json > SHA256SUMS)
cd /workspace/train_AB2
mark complete
