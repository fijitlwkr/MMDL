#!/usr/bin/env bash
set -euo pipefail
WORK=/workspace/train_D3_SD1
TASK=$WORK/work/train_RL_20261106
PY=/workspace/train_D1/.venv-train/bin/python
export HF_HOME=/workspace/hf_cache PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 MODELSCOPE_OFFLINE=1
export TMPDIR=$WORK/tmp XDG_CACHE_HOME=$WORK/cache MODELSCOPE_CACHE=$WORK/cache/modelscope
export MIN_PIXELS=1003520 MAX_PIXELS=4014080 IMAGE_MIN_TOKEN_NUM=980 IMAGE_MAX_TOKEN_NUM=3920 SPATIAL_MERGE_SIZE=2
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
cd "$WORK"
test "$(cat "$TASK/reports/d3sd1_stage0/exit")" = 0
test "$(cat "$TASK/reports/d3sd1_stage0/stage")" = complete
GLOBAL=$TASK/reports/d3sd1_training
test ! -e "$GLOBAL"
mkdir "$GLOBAL"
exec 9>"$GLOBAL/runner.lock"
flock -n 9
monitor=
finish() { result=$?; if [[ -n "$monitor" ]]; then kill "$monitor" 2>/dev/null || true; wait "$monitor" 2>/dev/null || true; fi; printf '%s\n' "$result" > "$GLOBAL/exit"; date -u -Iseconds > "$GLOBAL/finished_utc.txt"; }
trap finish EXIT
date -u -Iseconds > "$GLOBAL/started_utc.txt"
for RUN in d3_full sd1_a sd1_b; do
    echo "$RUN" > "$GLOBAL/stage"
    LOG=$TASK/reports/$RUN
    test ! -e "$LOG"
    mkdir "$LOG"
    nvidia-smi > "$LOG/nvidia-smi.txt"
    "$PY" -B -m pip freeze > "$LOG/packages.txt"
    "$PY" -B -m pip check > "$LOG/pip_check.txt"
    printf 'timestamp,used_mib,total_mib,util_pct\n' > "$LOG/gpu_memory.csv"
    nvidia-smi --query-gpu=timestamp,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits -l 1 >> "$LOG/gpu_memory.csv" 2> "$LOG/gpu_memory.err" 9>&- &
    monitor=$!
    date -u -Iseconds > "$LOG/started_utc.txt"
    if [[ "$RUN" == d3_full ]]; then
        "$PY" -B -u "$TASK/scripts/d3_full.py" "$TASK/scripts/d3_config_v2.json" "$TASK/data/d3_pairs_v2_swift.jsonl" "$WORK" "$TASK/artifacts/$RUN" > "$LOG/train.log" 2>&1
    else
        CONFIG=sd1_config_a.json
        if [[ "$RUN" == sd1_b ]]; then CONFIG=sd1_config_b.json; fi
        "$PY" -B -u "$TASK/scripts/sd1_train.py" "$TASK/scripts/$CONFIG" "$TASK/data/sd1_train_swift.jsonl" "$WORK" "$TASK/artifacts/$RUN" > "$LOG/train.log" 2>&1
    fi
    date -u -Iseconds > "$LOG/finished_utc.txt"
    kill -0 "$monitor"
    kill "$monitor"
    wait "$monitor" 2>/dev/null || true
    monitor=
    "$PY" -B -u "$TASK/scripts/d3sd1_check_training.py" "$RUN" > "$LOG/check.log" 2>&1
    printf '0\n' > "$LOG/exit"
done
echo complete > "$GLOBAL/stage"
echo D3_SD1_ALL_TRAINING_PASS
