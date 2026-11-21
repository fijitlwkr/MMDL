#!/usr/bin/env bash
set -euo pipefail

export HF_HOME=/workspace/hf_cache
cd /workspace/train_RL_20261106
logs=records/full_k4
exec 9>"$logs/runner.lock"
flock -n 9
test -s "$logs/image_verification.json"
test -s "$logs/model_reuse.json"
sha256sum --strict -c "$logs/input_sha256.txt" >>"$logs/input_verification.log"

started=$(date +%s)
monitor_pid=
on_exit() {
    local status=$?
    if [[ -n "$monitor_pid" ]]; then
        kill "$monitor_pid" 2>/dev/null || true
        wait "$monitor_pid" 2>/dev/null || true
    fi
    printf '%s %s\n' "$(date +%s)" "$status" >"$logs/exit_status.tmp"
    mv "$logs/exit_status.tmp" "$logs/exit_status"
    exit "$status"
}
trap on_exit EXIT
printf 'START %s\n' "$started" >>"$logs/timing.log"
printf '%s %s\n' "$$" "$started" >"$logs/runner.pid"

if [[ ! -s "$logs/gpu_memory.csv" ]]; then
    printf 'timestamp,gpu,used_mib,total_mib,util_pct\n' >"$logs/gpu_memory.csv"
fi
nvidia-smi --query-gpu=timestamp,index,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits -l 1 \
    >>"$logs/gpu_memory.csv" 2>"$logs/gpu_memory.err" 9>&- &
monitor_pid=$!
python3.12 -B -u scripts/sample_m0.py --run --pool-jsonl data/r1_pool.jsonl --image-root image_tree \
    --k 4 --reward-v2 --out data/full_k4 >>"$logs/sampling.log" 2>&1
printf 'SAMPLER_END %s\n' "$(date +%s)" >>"$logs/timing.log"
kill -0 "$monitor_pid"
kill "$monitor_pid"
wait "$monitor_pid" 2>/dev/null || true
monitor_pid=
python3.12 -B -u scripts/stage3_full.py finish >"$logs/finish.log" 2>&1
python3.12 -B -u scripts/stage3_full.py package >"$logs/package.log" 2>&1
