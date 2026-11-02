#!/usr/bin/env bash
# Merge adapter and run 900-item MMMU generation for E1 and E2
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
OUT="${1:?Usage: bash run_gpu.sh /workspace/OUTPUT_ROOT [smoke|E1|E2|all]}"
MODE="${2:-all}"

case "$ROOT" in /workspace/*) ;; *) exit 2;; esac
case "$OUT" in /workspace/*) ;; *) exit 2;; esac
case "$MODE" in smoke) RUNS=(E1);; E1|E2) RUNS=("$MODE");; all) RUNS=(E1 E2);; *) exit 2;; esac

export HF_HOME=/workspace/hf_cache
export XDG_CACHE_HOME=/workspace/cache PIP_CACHE_DIR=/workspace/pip_cache TMPDIR=/workspace/tmp
export TRITON_CACHE_DIR=/workspace/triton_cache CUDA_CACHE_PATH=/workspace/cuda_cache
export PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false

TRAIN_DIR="$ROOT/assignment/experiments/hypB_train/jinho"
EVAL_PY="$TRAIN_DIR/.venv-eval/bin/python"
if [ ! -x "$EVAL_PY" ]; then
    EVAL_PY="python3.12"
fi

mkdir -p "$OUT/records" "$HF_HOME" "$XDG_CACHE_HOME" "$TMPDIR"
finish() { printf '%s\n' "$?" > "$OUT/records/$MODE.exit"; }
trap finish EXIT
stage() { printf '%s\n' "$1" > "$OUT/records/$MODE.stage"; }

cd "$ROOT"
stage verify_code
"$EVAL_PY" "$HERE/verify_code.py"
"$EVAL_PY" -m pip freeze > "$OUT/records/packages_generation_$MODE.txt"
nvidia-smi > "$OUT/records/nvidia-smi_$MODE.txt"

for RUN in "${RUNS[@]}"; do
    if [[ "$MODE" == smoke ]]; then DIR="$OUT/smoke_E1"; else DIR="$OUT/$RUN"; fi
    test ! -e "$DIR" || { echo "Use a fresh run folder: $DIR" >&2; exit 2; }
    mkdir -p "$DIR"

    stage "merge_$RUN"
    git rev-parse HEAD > "$DIR/code_commit.txt"

    LOCAL_ADAPTER="$TRAIN_DIR/artifacts/full_$RUN/checkpoint-188"
    if [ -d "$LOCAL_ADAPTER" ]; then
        echo "Found local checkpoint at $LOCAL_ADAPTER, using local merge..."
        "$EVAL_PY" "$HERE/prepare_model.py" "$RUN" "$DIR/merged" --local-adapter "$LOCAL_ADAPTER" > "$DIR/merge.log" 2>&1
    else
        echo "Using HF adapter for $RUN..."
        "$EVAL_PY" "$HERE/prepare_model.py" "$RUN" "$DIR/merged" > "$DIR/merge.log" 2>&1
    fi

    stage "model_hash_$RUN"
    (cd "$DIR/merged" && sha256sum *.safetensors) > "$DIR/merged_safetensors.sha256"

    stage "environment_gate_$RUN"
    "$EVAL_PY" "$ROOT/code/check_env.py" --config "$ROOT/code/config.yaml" --out "$DIR/gates" --model_path "$DIR/merged" --data_root /workspace/mmmu_cache --download > "$DIR/env_gate.log" 2>&1
    "$EVAL_PY" "$ROOT/code/gate_env_check.py" "$DIR/gates/env_check.json"

    stage "preflight_$RUN"
    "$EVAL_PY" "$ROOT/code/preflight.py" --config "$ROOT/code/config.yaml" --model_path "$DIR/merged" --data_root /workspace/mmmu_cache --out "$DIR/preflight" > "$DIR/preflight.log" 2>&1
    "$EVAL_PY" - "$DIR/preflight/preflight.json" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))['summary']
assert s['processed']==s['selected']==900 and not s['partial']
assert not s['validation_failures'] and s['exceeds_count']==0
PY

    stage "generation_$RUN"
    EXTRA=()
    if [[ "$MODE" == smoke ]]; then EXTRA=(--limit 3); EXPECTED=3; else EXPECTED=900; fi
    START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    bash "$ROOT/code/run_generate.sh" --install --model_path "$DIR/merged" --data_root /workspace/mmmu_cache --out "$DIR/generation" "${EXTRA[@]}" > "$DIR/generate.log" 2>&1
    FINISH="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    stage "validation_$RUN"
    "$EVAL_PY" "$ROOT/code/validate_raw.py" --raw "$DIR/generation/raw.jsonl" --config "$ROOT/code/config.yaml" --expect "$EXPECTED" > "$DIR/raw_validation.log" 2>&1
    sha256sum "$DIR/generation/raw.jsonl" > "$DIR/raw.sha256"

    if [[ "$MODE" != smoke ]]; then
        "$EVAL_PY" "$HERE/run_metrics.py" "$DIR/generation" --started "$START" --finished "$FINISH" --out "$DIR/generation_summary.json"
    fi
    "$EVAL_PY" "$HERE/verify_code.py"
done
stage complete
echo "=== Generation for $MODE completed successfully! ==="

