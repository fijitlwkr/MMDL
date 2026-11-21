#!/usr/bin/env bash
set -euo pipefail
cd /workspace/train_D1
export HF_HOME=/workspace/hf_cache TZ=UTC
export TMPDIR=$PWD/tmp XDG_CACHE_HOME=$PWD/cache MODELSCOPE_CACHE=$PWD/cache/modelscope
export OMP_NUM_THREADS=4 PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 MODELSCOPE_OFFLINE=1
logs=reports/full
test "$(cat reports/pilot.exit)" = 0
test ! -e artifacts/full
test ! -e artifacts/merged_full
monitor=
on_exit() {
    local status=$?
    if [[ -n "$monitor" ]]; then
        kill "$monitor" 2>/dev/null || true
        wait "$monitor" 2>/dev/null || true
    fi
    printf '%s\n' "$status" > "$logs/exit"
}
trap on_exit EXIT
sha256sum --strict -c "$logs/new_scripts.sha256" > "$logs/scripts_verification.log"
.venv-train/bin/python -u scripts/d1_full_artifacts.py verify > "$logs/input.log" 2>&1
nvidia-smi > "$logs/nvidia_smi.txt"
printf 'timestamp,used_mib,total_mib,util_pct\n' > "$logs/gpu_memory.csv"
nvidia-smi --query-gpu=timestamp,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits -l 1 \
    >> "$logs/gpu_memory.csv" 2> "$logs/gpu_memory.err" &
monitor=$!
printf 'TRAIN_START %s\n' "$(date +%s)" >> "$logs/timing.log"
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True .venv-train/bin/python -u scripts/d1_full.py full \
    data/d1_pairs_swift.jsonl image_tree artifacts/full > "$logs/train.log" 2>&1
printf 'TRAIN_END %s\n' "$(date +%s)" >> "$logs/timing.log"
kill -0 "$monitor"
kill "$monitor"
wait "$monitor" 2>/dev/null || true
monitor=
.venv-train/bin/python -u scripts/d1_full_artifacts.py merge > "$logs/merge.log" 2>&1
.venv-eval/bin/python -u scripts/d1_full_artifacts.py load > "$logs/vllm_load.log" 2>&1
.venv-train/bin/python -u scripts/d1_full_artifacts.py package
