#!/usr/bin/env bash
# Merge in the existing venv; generate with the image Python and main installer.
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
mkdir -p "$OUT/records" "$HF_HOME" "$XDG_CACHE_HOME" "$TMPDIR"
finish() { printf '%s\n' "$?" > "$OUT/records/$MODE.exit"; }
trap finish EXIT
stage() { printf '%s\n' "$1" > "$OUT/records/$MODE.stage"; }
cd "$ROOT"
python3.12 - <<'PY'
import importlib.metadata as m, subprocess, sys, torch
from pathlib import Path
print(m.version('torch'), torch.__version__)
assert m.version('torch') == torch.__version__ == '2.8.0+cu128'
assert Path(subprocess.check_output(['python','-c','import sys; print(sys.executable)'],text=True).strip()).resolve() == Path(sys.executable).resolve()
PY
python3.12 "$HERE/verify_code.py"
python3.12 -m pip freeze > "$OUT/records/packages_generation_$MODE.txt"
nvidia-smi > "$OUT/records/nvidia-smi_$MODE.txt"
for RUN in "${RUNS[@]}"; do
    if [[ "$MODE" == smoke ]]; then DIR="$OUT/smoke_E1"; else DIR="$OUT/$RUN"; fi
    test ! -e "$DIR" || { echo "Use a fresh run folder: $DIR" >&2; exit 2; }
    mkdir -p "$DIR"
    stage merge
    git rev-parse HEAD > "$DIR/code_commit.txt"
    /workspace/hypB-eval-env/bin/python "$HERE/prepare_model.py" "$RUN" "$DIR/merged" > "$DIR/merge.log" 2>&1
    stage model_hash
    (cd "$DIR/merged" && sha256sum *.safetensors) > "$DIR/merged_safetensors.sha256"
    stage environment_gate
    python3.12 "$ROOT/code/check_env.py" --config "$ROOT/code/config.yaml" --out "$DIR/gates" --model_path "$DIR/merged" --data_root /workspace/mmmu_cache --download > "$DIR/env_gate.log" 2>&1
    python3.12 "$ROOT/code/gate_env_check.py" "$DIR/gates/env_check.json"
    stage preflight
    python3.12 "$ROOT/code/preflight.py" --config "$ROOT/code/config.yaml" --model_path "$DIR/merged" --data_root /workspace/mmmu_cache --out "$DIR/preflight" > "$DIR/preflight.log" 2>&1
    python3.12 - "$DIR/preflight/preflight.json" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))['summary']
assert s['processed']==s['selected']==900 and not s['partial']
assert not s['validation_failures'] and s['exceeds_count']==0
PY
    stage generation
    EXTRA=()
    if [[ "$MODE" == smoke ]]; then EXTRA=(--limit 3); EXPECTED=3; else EXPECTED=900; fi
    START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    bash "$ROOT/code/run_generate.sh" --install --model_path "$DIR/merged" --data_root /workspace/mmmu_cache --out "$DIR/generation" "${EXTRA[@]}" > "$DIR/generate.log" 2>&1
    FINISH="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    python3.12 -c "import importlib.metadata as m, torch; print(m.version('torch'), torch.__version__); assert m.version('torch') == torch.__version__ == '2.8.0+cu128'" > "$DIR/torch_after_generation.txt"
    python3.12 -m pip check > "$DIR/pip_check_after_generation.txt"
    stage validation
    python3.12 "$ROOT/code/validate_raw.py" --raw "$DIR/generation/raw.jsonl" --config "$ROOT/code/config.yaml" --expect "$EXPECTED" > "$DIR/raw_validation.log" 2>&1
    sha256sum "$DIR/generation/raw.jsonl" > "$DIR/raw.sha256"
    if [[ "$MODE" != smoke ]]; then
        python3.12 "$HERE/run_metrics.py" "$DIR/generation" --started "$START" --finished "$FINISH" --out "$DIR/generation_summary.json"
    fi
    python3.12 "$HERE/verify_code.py"
done
stage complete
