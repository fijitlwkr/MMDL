#!/usr/bin/env bash
set -euo pipefail
export HF_HOME=/workspace/hf_cache HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
export PYTHONDONTWRITEBYTECODE=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4
export VLLM_ENABLE_V1_MULTIPROCESSING=0 VLLM_WORKER_MULTIPROC_METHOD=spawn VLLM_USE_FLASHINFER_SAMPLER=0
BASE=/workspace/train_C1
ROOT=$BASE/work/train_RL_20261106
export XDG_CACHE_HOME=$BASE/c1_cache TMPDIR=$BASE/c1_tmp
export TRITON_CACHE_DIR=$BASE/c1_cache/triton CUDA_CACHE_PATH=$BASE/c1_cache/cuda
export TORCHINDUCTOR_CACHE_DIR=$BASE/c1_cache/torchinductor VLLM_CACHE_ROOT=$BASE/c1_cache/vllm
REC=$ROOT/reports/c1_gpu_smoke_execution
mkdir -p "$ROOT/reports" "$XDG_CACHE_HOME" "$TMPDIR"
mkdir "$REC"
cd "$ROOT"
date -u -Iseconds > "$REC/c1_started_utc.txt"
df -h /workspace / > "$REC/c1_disk_before.txt"
nvidia-smi > "$REC/c1_nvidia_before.txt"
nvidia-smi --query-gpu=timestamp,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits -l 1 > "$REC/c1_gpu_memory.csv" &
MONITOR=$!
finish() {
    result=$?
    kill "$MONITOR" 2>/dev/null || true
    wait "$MONITOR" 2>/dev/null || true
    printf '%s\n' "$result" > "$REC/c1_exit.txt"
    date -u -Iseconds > "$REC/c1_ended_utc.txt"
}
trap finish EXIT
/workspace/train_D1/.venv-train/bin/python -B -u scripts/c1_smoke.py --run \
    --model-path /workspace/hf_cache/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/ebb281ec70b05090aa6165b016eac8ec08e71b17 \
    --image-root /workspace/train_D3_SD1 \
    --output "$ROOT/artifacts/c1_smoke" \
    --merge-python /workspace/train_D1/.venv-train/bin/python \
    --merge-script /workspace/train_D3_SD1/sources/e1/merge.py \
    --vllm-python /workspace/train_D1/.venv-eval/bin/python \
    > "$REC/c1_run.log" 2>&1
echo C1_SMOKE_COMPLETE_CHECK_TIME_GATE_BEFORE_FULL_TRAINING
