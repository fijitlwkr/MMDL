#!/usr/bin/env bash
# MMMU-Pro standard (10 options), D3-e1, RTX 4090 x1. test_pod_pipeline.sh와 같은 순서.
set -Eeuo pipefail
cd /workspace/eval_pro_D3e1_20261123
export HF_HOME=/workspace/hf_cache
export PIP_CACHE_DIR=/workspace/pip_cache XDG_CACHE_HOME=/workspace/cache
export TRITON_CACHE_DIR=/workspace/triton_cache CUDA_CACHE_PATH=/workspace/cuda_cache
export TORCHINDUCTOR_CACHE_DIR=/workspace/torchinductor_cache VLLM_CACHE_ROOT=/workspace/vllm_cache
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=4
pkg=$PWD/package
code=$pkg/code
config=$code/config_pro.yaml
model=/workspace/eval_D3e1_20261113/models/D3e1
base=/workspace/hf_cache/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/ebb281ec70b05090aa6165b016eac8ec08e71b17
data=/workspace/mmmu_cache
out=$PWD/runs/pro_seed_3407
records=$PWD/records
mkdir "$records"
mkdir runs
mark() { stage=$1; printf "%s\n" "$stage" > "$records/stage"; printf "%s %s\n" "$(date -u -Is)" "$stage"; }
trap 'rc=$?; echo "$rc" > "$records/exit"; date -u -Is > "$records/finished_utc"' EXIT

mark integrity
python3.12 -B - "$pkg" <<'PY'
import hashlib, json, sys
from pathlib import Path
pkg = Path(sys.argv[1])
expected = json.loads((pkg / "PRO_FILE_HASHES.json").read_bytes())
bad = [k for k, v in expected.items() if k != "PRO_FILE_HASHES.json" and hashlib.sha256((pkg / k).read_bytes()).hexdigest() != v]
assert not bad, bad
print("package files OK", len(expected))
PY
nvidia-smi -L > "$records/gpu.txt"
test "$(grep -c 'NVIDIA GeForce RTX 4090' "$records/gpu.txt")" -eq 1
test "$(wc -l < "$records/gpu.txt")" -eq 1
df -B1 /workspace > "$records/disk.txt"
test "$(awk 'END {print $4}' "$records/disk.txt")" -ge 35000000000
printf '%s\n' \
  "30a01a0556622645a3cce87b655bbbbbc1f170c196099f1b666c93202c3339a9  $base/model-00001-of-00002.safetensors" \
  "046296a2a387efb43b0c997d5833c789604d168834f6e0d3064bf7bb13d002a6  $base/model-00002-of-00002.safetensors" \
  "53b1ee59b11807c6d6df008bdaca3d1be6b89195f780054f5929fb1fddc7671f  /workspace/eval_D3e1_20261113/adapter/D3e1/adapter_model.safetensors" \
  "5501198916f4184c8f02036b71097efa881e69d57c3b4d5a941e3aefc2a6fb21  $model/model-00001-of-00002.safetensors" \
  "2e8b706c5670049157ccd5273439a599bd2721d7d34c19016f7a7e0549e89540  $model/model-00002-of-00002.safetensors" | sha256sum -c | tee "$records/model_sha256.txt"
python3.12 - "$base" "$model" <<'PY'
from pathlib import Path
import sys,hashlib,json
base,model=map(Path,sys.argv[1:])
hashes={}
for p in base.iterdir():
    if p.is_file() and p.suffix in {'.json','.jinja','.txt'} and p.name not in {'config.json','model.safetensors.index.json'}:
        value=hashlib.sha256(p.read_bytes()).hexdigest()
        assert value==hashlib.sha256((model/p.name).read_bytes()).hexdigest(), p.name
        hashes[p.name]=value
with Path('records/model_sidecars.json').open('x') as f:json.dump(hashes,f,indent=2)
PY

mark setup
bash "$pkg/scripts/setup_test_generation.sh" "$code" "$records/environment" > "$records/setup.log" 2>&1

mark unit_tests
PYTHONPATH=$PWD/pytest_runtime python -B -m pytest -q -p no:cacheprovider "$code/tests" "$code/scoring/tests" > "$records/unit_tests.log" 2>&1 || { tail -30 "$records/unit_tests.log"; exit 7; }
tail -1 "$records/unit_tests.log"

mark data
python -B - "$config" "$data" <<'PY' > "$records/data.log" 2>&1
import sys, yaml
from datasets import load_dataset
cfg = yaml.safe_load(open(sys.argv[1]))["dataset"]
ds = load_dataset(cfg["repo_id"], cfg["config_name"], split=cfg["split"], revision=cfg["revision"], cache_dir=sys.argv[2])
print(len(ds), ds.column_names)
assert len(ds) == cfg["expected_total_rows"]
PY
tail -1 "$records/data.log"
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1

mark preflight
python -B "$code/preflight.py" --config "$config" --model_path "$model" --data_root "$data" --out "$records/preflight" > "$records/preflight.log" 2>&1
python -B - <<'PY'
from pathlib import Path
import json
p=json.loads(Path('records/preflight/preflight.json').read_bytes())['summary']
report={k:p[k] for k in ('processed','selected','partial','exceeds_count','total_tokens')}
report["validation_failures"]=len(p['validation_failures'])
print(json.dumps(report),flush=True)
assert p['processed']==p['selected']==1730 and not p['partial']
assert not p['exceeds_count'] and not p['validation_failures'], "Pro inputs exceed fixed prompt budget or fail validation"
PY

mark smoke
bash "$pkg/scripts/run_pro.sh" smoke "$code" "$config" "$model" "$data" "$out" > "$records/smoke.log" 2>&1
echo 0 > "$records/smoke.exit"

mark generation
bash "$pkg/scripts/run_pro.sh" full "$code" "$config" "$model" "$data" "$out" > "$records/generation.log" 2>&1
mark complete
