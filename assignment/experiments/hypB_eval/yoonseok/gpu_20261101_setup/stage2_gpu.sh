#!/usr/bin/env bash
# Stage 2 invocation record: separate smoke test and fresh E1/E2 generations.
set -euo pipefail
export HF_HOME=/workspace/hf_cache
export XDG_CACHE_HOME=/workspace/cache PIP_CACHE_DIR=/workspace/pip_cache TMPDIR=/workspace/tmp
export TRITON_CACHE_DIR=/workspace/triton_cache CUDA_CACHE_PATH=/workspace/cuda_cache
export PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false
export PATH=/workspace/hypB-eval-env/bin:$PATH
ROOT=/workspace/MMDL
HERE="$ROOT/assignment/experiments/hypB_eval/yoonseok"
OUT=/workspace/hypB_eval_20261101
MODE="${1:?Specify smoke, E1, or E2}"
case "$MODE" in smoke) RUN=E1; DIR="$OUT/smoke_E1";; E1|E2) RUN="$MODE"; DIR="$OUT/$MODE";; *) exit 2;; esac
test ! -e "$DIR"
mkdir -p "$DIR"
finish() { printf '%s\n' "$?" > "$OUT/records/$MODE.exit"; }
trap finish EXIT
stage() { printf '%s\n' "$1" > "$OUT/records/$MODE.stage"; }
cd "$ROOT"
stage merge
python "$HERE/verify_code.py"
git rev-parse HEAD > "$DIR/code_commit.txt"
python "$HERE/prepare_model.py" "$RUN" "$DIR/merged" > "$DIR/merge.log" 2>&1
stage model_hash
python - "$DIR" <<'PY'
import hashlib,json,sys
from pathlib import Path
p=Path(sys.argv[1]); rows=[]
for f in sorted((p/'merged').rglob('*')):
    if not f.is_file(): continue
    h=hashlib.sha256()
    with f.open('rb') as source:
        for block in iter(lambda:source.read(8*1024*1024),b''): h.update(block)
    rows.append({'path':f.relative_to(p/'merged').as_posix(),'bytes':f.stat().st_size,'sha256':h.hexdigest()})
body=(json.dumps(rows,sort_keys=True,indent=2)+'\n').encode()
(p/'merged_files.json').write_bytes(body)
(p/'merged_files.sha256').write_text(hashlib.sha256(body).hexdigest()+'\n')
PY
stage environment_gate
python "$ROOT/code/check_env.py" --config "$ROOT/code/config.yaml" --out "$DIR/gates" --model_path "$DIR/merged" --data_root /workspace/mmmu_cache --download > "$DIR/env_gate.log" 2>&1
python "$ROOT/code/gate_env_check.py" "$DIR/gates/env_check.json"
stage preflight
python "$ROOT/code/preflight.py" --config "$ROOT/code/config.yaml" --model_path "$DIR/merged" --data_root /workspace/mmmu_cache --out "$DIR/preflight" > "$DIR/preflight.log" 2>&1
python - "$DIR/preflight/preflight.json" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))['summary']
assert s['processed']==s['selected']==900 and not s['partial']
assert not s['validation_failures'] and s['exceeds_count']==0
PY
stage generation
python "$HERE/verify_code.py"
START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
EXTRA=()
if [[ "$MODE" == smoke ]]; then EXTRA=(--limit 3); fi
bash "$ROOT/code/run_generate.sh" --model_path "$DIR/merged" --data_root /workspace/mmmu_cache --out "$DIR/generation" "${EXTRA[@]}" > "$DIR/generate.log" 2>&1
FINISH="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
stage validation
if [[ "$MODE" == smoke ]]; then EXPECTED=3; else EXPECTED=900; fi
python "$ROOT/code/validate_raw.py" --raw "$DIR/generation/raw.jsonl" --config "$ROOT/code/config.yaml" --expect "$EXPECTED" > "$DIR/raw_validation.log" 2>&1
sha256sum "$DIR/generation/raw.jsonl" > "$DIR/raw.sha256"
if [[ "$MODE" != smoke ]]; then
    python "$HERE/run_metrics.py" "$DIR/generation" --started "$START" --finished "$FINISH" --out "$DIR/generation_summary.json"
fi
python "$HERE/verify_code.py"
stage complete
