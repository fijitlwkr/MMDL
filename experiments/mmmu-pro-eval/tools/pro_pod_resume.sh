#!/usr/bin/env bash
# pro_pod_pipeline.sh가 unit_tests 단계에서 멈춘 뒤 이어서 실행한다.
# 허용 실패: test 평가 패키지 REGRESSION_GATE.json에 원래부터 실패로 기록된 2개(테스트용 /tmp/preflight-venv 부재)만.
set -Eeuo pipefail
cd /workspace/eval_pro_D3e1_20261123
export HF_HOME=/workspace/hf_cache
export PIP_CACHE_DIR=/workspace/pip_cache XDG_CACHE_HOME=/workspace/cache
export TRITON_CACHE_DIR=/workspace/triton_cache CUDA_CACHE_PATH=/workspace/cuda_cache
export TORCHINDUCTOR_CACHE_DIR=/workspace/torchinductor_cache VLLM_CACHE_ROOT=/workspace/vllm_cache
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=4
pkg=$PWD/package; code=$pkg/code; config=$code/config_pro.yaml
model=/workspace/eval_D3e1_20261113/models/D3e1; data=/workspace/mmmu_cache
out=$PWD/runs/pro_seed_3407; records=$PWD/records
mark() { printf "%s\n" "$1" > "$records/stage"; printf "%s %s\n" "$(date -u -Is)" "$1"; }
rm -f "$records/exit" "$records/finished_utc"
trap 'rc=$?; echo "$rc" > "$records/exit"; date -u -Is > "$records/finished_utc"' EXIT

mark unit_tests_check
python3.12 -B - "$records/unit_tests.log" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
failed = sorted(set(re.findall(r"^FAILED (\S+)", text, re.M)))
known = ["package/code/tests/test_step3b.py::test_runner_hf_transfer_export_log[True]",
         "package/code/tests/test_step3b.py::test_runner_pip_retry_behavior"]
assert re.search(r"^2 failed, 63 passed", text, re.M), "unexpected test totals"
assert failed == known, failed
print("unit tests: only the 2 known environment failures (same as test package REGRESSION_GATE)")
PY

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
