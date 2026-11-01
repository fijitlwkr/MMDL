#!/usr/bin/env bash
# Phase 2 only. Generates validation results without Judge/API calls or pod shutdown.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
OUT="${1:?Usage: bash run_gpu.sh /workspace/NEW_OUTPUT_ROOT}"
case "$ROOT" in /workspace/*) ;; *) echo "Checkout must be under /workspace" >&2; exit 2;; esac
case "$OUT" in /workspace/*) ;; *) echo "Outputs must be under /workspace" >&2; exit 2;; esac
test ! -e "$OUT" || { echo "Use a new output root" >&2; exit 2; }
export HF_HOME=/workspace/hf_cache
export XDG_CACHE_HOME=/workspace/cache PIP_CACHE_DIR=/workspace/pip_cache TMPDIR=/workspace/tmp
export PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false
export PATH="/workspace/hypB-eval-env/bin:$PATH"
mkdir -p "$OUT" "$HF_HOME" "$XDG_CACHE_HOME" "$TMPDIR"
nvidia-smi --query-gpu=name --format=csv,noheader | grep -F 'RTX 4090'
python "$HERE/verify_code.py" > "$OUT/code_verification.txt"
python -m pip freeze > "$OUT/packages.txt"
for RUN in E1 E2; do
    DIR="$OUT/$RUN"
    mkdir -p "$DIR"
    python "$HERE/prepare_model.py" "$RUN" "$DIR/merged" > "$DIR/merge.log" 2>&1
    python "$ROOT/code/check_env.py" --config "$ROOT/code/config.yaml" --out "$DIR/gates" --model_path "$DIR/merged" --data_root /workspace/mmmu_cache --download > "$DIR/env_gate.log" 2>&1
    python "$ROOT/code/gate_env_check.py" "$DIR/gates/env_check.json"
    python "$ROOT/code/preflight.py" --config "$ROOT/code/config.yaml" --model_path "$DIR/merged" --data_root /workspace/mmmu_cache --out "$DIR/preflight" > "$DIR/preflight.log" 2>&1
    python - "$DIR/preflight/preflight.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))["summary"]
assert s["processed"] == s["selected"] == 900 and not s["partial"]
assert not s["validation_failures"] and s["exceeds_count"] == 0
PY
    python "$HERE/verify_code.py"
    START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    bash "$ROOT/code/run_generate.sh" --model_path "$DIR/merged" --data_root /workspace/mmmu_cache --out "$DIR/generation" > "$DIR/generate.log" 2>&1
    FINISH="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    python "$ROOT/code/validate_raw.py" --raw "$DIR/generation/raw.jsonl" --config "$ROOT/code/config.yaml" --expect 900 > "$DIR/raw_validation.log" 2>&1
    python "$HERE/run_metrics.py" "$DIR/generation" --started "$START" --finished "$FINISH" --out "$DIR/generation_summary.json"
    python "$HERE/verify_code.py"
done
echo "E1 and E2 generation complete. Preserve both raw files and hashes for the local copy."
