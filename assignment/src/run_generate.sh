#!/usr/bin/env bash
set -euo pipefail

# One-shot inference runner. Put --out on persistent pod storage.
# Automatic stop syntax is intentionally unverified: check `runpodctl --help`
# on RunPod before relying on `runpodctl stop pod "$RUNPOD_POD_ID"`.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_PATH=""; REVISION=""; DATA_ROOT=""; OUT=""; CONFIG="$SCRIPT_DIR/config.yaml"; LIMIT=""; SUBJECTS=""
INSTALL=0; STOP_POD=0; SKIP_GATE=0; PASSTHROUGH=(); STAGE="argument parsing"
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
usage() {
  cat <<EOF
Usage: $0 --out DIR [--model_path PATH] [--revision REVISION] [--data_root DIR]
       [--config PATH] [--install] [--stop_pod_when_done] [--skip_env_gate]
       [--limit N] [--subjects A,B] [--engine_override KEY=JSON ...]
Use a persistent pod volume for --out so raw.jsonl and logs survive restarts.
EOF
}
while (($#)); do
  case "$1" in
    --model_path|--revision|--data_root|--config|--limit|--subjects)
      [[ $# -ge 2 ]] || { echo "missing value for $1" >&2; exit 2; }
      key="$1"; value="$2"; shift 2
      case "$key" in
        --model_path) MODEL_PATH="$value";; --revision) REVISION="$value";;
        --data_root) DATA_ROOT="$value";; --config) CONFIG="$value";;
        --limit) LIMIT="$value"; PASSTHROUGH+=("$key" "$value");;
        --subjects) SUBJECTS="$value"; PASSTHROUGH+=("$key" "$value");;
        *) PASSTHROUGH+=("$key" "$value");;
      esac;;
    --out) [[ $# -ge 2 ]] || { echo "missing value for --out" >&2; exit 2; }; OUT="$2"; shift 2;;
    --install) INSTALL=1; shift;;
    --stop_pod_when_done) STOP_POD=1; shift;;
    --skip_env_gate) SKIP_GATE=1; shift;;
    --engine_override) [[ $# -ge 2 ]] || { echo "missing value for --engine_override" >&2; exit 2; }; PASSTHROUGH+=("$1" "$2"); shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2;;
  esac
done
[[ -n "$OUT" ]] || { echo "--out is required" >&2; usage >&2; exit 2; }
mkdir -p "$OUT/logs"
FAILED=0; FAIL_CODE=0
cleanup() {
  local code=$?
  if (( code != 0 || FAILED )); then
    FAILED=1; FAIL_CODE=$(( code != 0 ? code : FAIL_CODE ))
    { echo "stage=$STAGE"; echo "exit_code=$FAIL_CODE"; echo "time=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; nvidia-smi 2>&1 || true; df -h 2>&1 || true; } >"$OUT/logs/FAILED"
  fi
  if (( STOP_POD )); then
    sync || true
    if command -v runpodctl >/dev/null 2>&1 && [[ -n "${RUNPOD_POD_ID:-}" ]]; then runpodctl stop pod "$RUNPOD_POD_ID" || true; else echo "automatic pod stop unavailable: runpodctl or RUNPOD_POD_ID is missing"; fi
  fi
}
trap cleanup EXIT
STAGE="system snapshot"
{ echo "started_utc=$STARTED"; nvidia-smi 2>&1 || true; df -h; free -g; python --version 2>&1; } >"$OUT/logs/00_system.log"
STAGE="environment export"
export CONFIG_PATH="$CONFIG"
while IFS='=' read -r key value; do
  [[ -n "$key" ]] && export "$key=$value"
done < <(python -c 'import os,yaml; c=yaml.safe_load(open(os.environ["CONFIG_PATH"])); [print(k+"="+str(v)) for k,v in c["environment"]["env_vars"].items()]')
if [[ -z "${HF_HOME:-}" ]]; then echo "WARNING: HF_HOME is unset; using process defaults"; fi
if (( INSTALL )); then
  STAGE="install"
  if [[ ! -s "$SCRIPT_DIR/requirements.txt" ]]; then echo "requirements.txt is empty" | tee "$OUT/logs/01_install.log"; exit 3; fi
  python -m pip install -r "$SCRIPT_DIR/requirements.txt" 2>&1 | tee "$OUT/logs/01_install.log"
fi
if (( ! SKIP_GATE )); then
  STAGE="environment check"
  CHECK_ARGS=(--config "$CONFIG" --out "$OUT" --sections system,packages,vllm_import,gpu,qwen_vl_utils,model --download)
  [[ -n "$MODEL_PATH" ]] && CHECK_ARGS+=(--model_path "$MODEL_PATH"); [[ -n "$REVISION" ]] && CHECK_ARGS+=(--revision "$REVISION"); [[ -n "$DATA_ROOT" ]] && CHECK_ARGS+=(--data_root "$DATA_ROOT")
  set +e; python "$SCRIPT_DIR/check_env.py" "${CHECK_ARGS[@]}" 2>&1 | tee "$OUT/logs/02_env_check.log"; CHECK_CODE=${PIPESTATUS[0]}; set -e
  python "$SCRIPT_DIR/gate_env_check.py" "$OUT/env_check.json" | tee -a "$OUT/logs/02_env_check.log"
else
  echo "WARNING: --skip_env_gate is for local rehearsal only; environment was not gated" | tee "$OUT/logs/02_env_check.log"
fi
STAGE="generation"
GEN_ARGS=(--config "$CONFIG" --out "$OUT")
[[ -n "$MODEL_PATH" ]] && GEN_ARGS+=(--model_path "$MODEL_PATH"); [[ -n "$REVISION" ]] && GEN_ARGS+=(--revision "$REVISION"); [[ -n "$DATA_ROOT" ]] && GEN_ARGS+=(--data_root "$DATA_ROOT")
[[ -f "$OUT/raw.jsonl" ]] && echo "Resume: existing raw.jsonl found"
set +e; python "$SCRIPT_DIR/generate.py" "${GEN_ARGS[@]}" "${PASSTHROUGH[@]}" 2>&1 | tee "$OUT/logs/03_generate.log"; GEN_CODE=${PIPESTATUS[0]}; set -e
STAGE="raw validation"
VALIDATE_ARGS=(--raw "$OUT/raw.jsonl" --config "$CONFIG")
if [[ -n "${EXPECT_ROWS:-}" ]]; then
  VALIDATE_ARGS+=(--expect "$EXPECT_ROWS")
elif [[ -n "$LIMIT" ]]; then
  VALIDATE_ARGS+=(--expect "$LIMIT")
elif [[ -n "$SUBJECTS" ]]; then
  SUBJECT_COUNT=$(awk -F, '{print NF}' <<<"$SUBJECTS")
  ROWS_PER_SUBJECT=$(python -c 'import os,yaml; print(yaml.safe_load(open(os.environ["CONFIG_PATH"]))["dataset"]["expected_rows_per_subject"])')
  VALIDATE_ARGS+=(--expect "$((SUBJECT_COUNT * ROWS_PER_SUBJECT))")
fi
set +e; python "$SCRIPT_DIR/validate_raw.py" "${VALIDATE_ARGS[@]}" 2>&1 | tee "$OUT/logs/04_validate_raw.log"; VALIDATE_CODE=${PIPESTATUS[0]}; set -e
{ sha256sum "$OUT/raw.jsonl"; stat -c 'bytes=%s' "$OUT/raw.jsonl"; echo "started_utc=$STARTED"; echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; } | tee -a "$OUT/logs/04_validate_raw.log"
if (( GEN_CODE != 0 || VALIDATE_CODE != 0 )); then FAILED=1; FAIL_CODE=$(( GEN_CODE != 0 ? GEN_CODE : VALIDATE_CODE )); exit "$FAIL_CODE"; fi
STAGE="complete"; echo "SUCCESS: output=$OUT raw=$OUT/raw.jsonl logs=$OUT/logs"
