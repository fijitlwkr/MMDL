#!/usr/bin/env bash
set -euo pipefail
export HF_HOME=/workspace/hf_cache PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4
export MIN_PIXELS=1003520 MAX_PIXELS=4014080 IMAGE_MIN_TOKEN_NUM=980 IMAGE_MAX_TOKEN_NUM=3920 SPATIAL_MERGE_SIZE=2
WORK=/workspace/train_D3_SD1
TASK=$WORK/work/train_RL_20261106
export TMPDIR=$WORK/tmp XDG_CACHE_HOME=$WORK/cache MODELSCOPE_CACHE=$WORK/cache/modelscope
export TRITON_CACHE_DIR=$WORK/cache/triton CUDA_CACHE_PATH=$WORK/cache/cuda VLLM_CACHE_ROOT=$WORK/cache/vllm
mkdir -p "$TMPDIR" "$MODELSCOPE_CACHE" "$TASK/reports/d3sd1_stage0"
cd "$WORK"
TRAIN=/workspace/train_D1/.venv-train/bin/python
EVAL=/workspace/train_D1/.venv-eval/bin/python
LOG=$TASK/reports/d3sd1_stage0
finish() { result=$?; printf '%s\n' "$result" > "$LOG/exit"; date -u -Iseconds > "$LOG/finished_utc.txt"; }
trap finish EXIT
date -u -Iseconds > "$LOG/started_utc.txt"
echo inputs > "$LOG/stage"
"$TRAIN" -B -u "$TASK/scripts/d3sd1_stage_inputs.py" > "$LOG/inputs.log" 2>&1
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 MODELSCOPE_OFFLINE=1
echo sft_tokenization > "$LOG/stage"
"$TRAIN" -B -u "$TASK/scripts/d3sd1_stage0.py" sft > "$LOG/sft_tokens.log" 2>&1
echo development_smoke > "$LOG/stage"
"$EVAL" -B -u "$TASK/scripts/d3_sample_dev.py" --run --pool-jsonl "$TASK/data/r1_pool.jsonl" --questions-jsonl "$TASK/data/d3_dev.jsonl" --image-root "$WORK" --repeat-start 4 --k 4 --limit 2 --reward-v2 --model-path /workspace/hf_cache/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/ebb281ec70b05090aa6165b016eac8ec08e71b17 --out "$TASK/data/d3sd1_smoke_M0" > "$LOG/smoke.log" 2>&1
echo smoke_verification > "$LOG/stage"
"$TRAIN" -B -u "$TASK/scripts/d3sd1_stage0.py" smoke > "$LOG/smoke_check.log" 2>&1
echo complete > "$LOG/stage"
echo D3_SD1_STAGE0_PASS
