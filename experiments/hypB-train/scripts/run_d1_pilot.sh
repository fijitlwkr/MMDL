#!/usr/bin/env bash
set -euo pipefail
cd /workspace/train_D1
export HF_HOME=/workspace/hf_cache TZ=UTC
export TMPDIR=$PWD/tmp XDG_CACHE_HOME=$PWD/cache MODELSCOPE_CACHE=$PWD/cache/modelscope
export OMP_NUM_THREADS=4 PYTHONDONTWRITEBYTECODE=1
test "$(cat reports/setup.exit)" = 0
test ! -e artifacts/pilot
test ! -e artifacts/merged_pilot
monitor=
on_exit() {
    local status=$?
    if [[ -n "$monitor" ]]; then
        kill "$monitor" 2>/dev/null || true
        wait "$monitor" 2>/dev/null || true
    fi
    printf '%s\n' "$status" > reports/pilot.exit
}
trap on_exit EXIT
.venv-train/bin/python -u scripts/d1_pilot_artifacts.py prepare > reports/input.log 2>&1
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 MODELSCOPE_OFFLINE=1
printf 'timestamp,used_mib,total_mib,util_pct\n' > reports/gpu_memory.csv
nvidia-smi --query-gpu=timestamp,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits -l 1 \
    >> reports/gpu_memory.csv 2> reports/gpu_memory.err &
monitor=$!
printf 'PILOT_START %s\n' "$(date +%s)" >> reports/timing.log
.venv-train/bin/python -u scripts/d1_pilot.py pilot data/d1_pairs_swift.jsonl image_tree artifacts/pilot > reports/train.log 2>&1
printf 'PILOT_END %s\n' "$(date +%s)" >> reports/timing.log
kill -0 "$monitor"
kill "$monitor"
wait "$monitor" 2>/dev/null || true
monitor=
.venv-train/bin/python -u scripts/d1_pilot_artifacts.py merge > reports/merge.log 2>&1
.venv-eval/bin/python -u scripts/d1_pilot_artifacts.py load > reports/vllm_load.log 2>&1
.venv-train/bin/python -u scripts/d1_pilot_artifacts.py package
