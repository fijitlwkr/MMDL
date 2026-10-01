#!/usr/bin/env bash
# Seed-robustness sweep for the SUBMITTED baseline. Run on one RunPod RTX 4090 pod, from the repo root,
# on branch exp/baseline-seed-robustness. Never touches code/ ; only adds files under WORK and results/.
#
#   bash experiments/baseline_seed_robustness/run_all.sh --tier 1 --install
#   bash experiments/baseline_seed_robustness/run_all.sh --tier 2
#
# Arms: name:sampling_seed:engine_seed   (baseline = 3407:3407, already submitted)
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXP="$REPO/experiments/baseline_seed_robustness"
WORK="${WORK:-/workspace/seedexp}"
export HF_HOME="${HF_HOME:-/workspace/.cache/huggingface}"
DATA_ROOT="${DATA_ROOT:-/workspace/.cache/hf_datasets}"
TIER=1; INSTALL=0; STOP_AT_END=0; SKIP_FREEZE=0
while (($#)); do case "$1" in
  --tier) TIER="$2"; shift 2;;
  --install) INSTALL=1; shift;;
  --stop_pod_at_end) STOP_AT_END=1; shift;;
  --skip_freeze_check) SKIP_FREEZE=1; shift;;
  *) echo "unknown arg $1" >&2; exit 2;; esac; done

TIER1=("ctrl_repeat:3407:3407" "seed_42:42:3407" "seed_1234:1234:3407" "seed_2026:2026:3407")
TIER2=("seed_777:777:3407" "seed_31337:31337:3407" "ctrl_engine:3407:1")
case "$TIER" in 1) ARMS=("${TIER1[@]}");; 2) ARMS=("${TIER2[@]}");; all) ARMS=("${TIER1[@]}" "${TIER2[@]}");; *) echo "--tier 1|2|all" >&2; exit 2;; esac

# Guard 1: generation/scoring code must be byte-identical to the frozen baseline code.
if (( ! SKIP_FREEZE )); then
  NOW="$(cd "$REPO" && find code -type f ! -path '*/tests/*' ! -path '*/__pycache__/*' ! -name '*.pyc' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1)"
  WANT="$(tr -d ' \n' < "$EXP/CODE_FREEZE.sha256")"
  [[ "$NOW" == "$WANT" ]] || { echo "ABORT: code/ differs from frozen baseline code ($NOW != $WANT)" >&2; exit 3; }
fi
# Guard 2: the judge needs a key; without it we still generate and score later with --skip_generate.
[[ -n "${OPENAI_API_KEY:-}" ]] || echo "WARNING: OPENAI_API_KEY not set -> generation only; score later (see README step 6)."
mkdir -p "$WORK"; cd "$REPO"

for spec in "${ARMS[@]}"; do
  IFS=: read -r NAME SSEED ESEED <<<"$spec"
  OUT="$WORK/$NAME"
  if [[ -f "$OUT/DONE" ]]; then echo "[skip] $NAME already DONE"; continue; fi
  # A resumed run changes batch composition -> never resume; discard partial output.
  if [[ -d "$OUT" ]]; then mv "$OUT" "$OUT.partial.$(date -u +%Y%m%dT%H%M%SZ)"; fi
  mkdir -p "$OUT"
  python "$EXP/make_seed_config.py" --out "$OUT/config_used.yaml" --sampling-seed "$SSEED" --engine-seed "$ESEED"
  ARGS=(--config "$OUT/config_used.yaml" --out "$OUT" --data_root "$DATA_ROOT")
  if (( INSTALL )); then ARGS+=(--install); INSTALL=0; fi
  echo "=== $(date -u +%FT%TZ) START $NAME sampling_seed=$SSEED engine_seed=$ESEED ==="
  bash code/run_generate.sh "${ARGS[@]}"
  python code/scoring/evaluate.py prepare --raw "$OUT/raw.jsonl" --config "$OUT/config_used.yaml" --out "$OUT/scoring"
  if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    python code/scoring/evaluate.py run --out "$OUT/scoring"
    python code/scoring/evaluate.py summarize --out "$OUT/scoring"
    touch "$OUT/DONE"
  else
    touch "$OUT/GENERATED_NOT_SCORED"
  fi
  echo "=== $(date -u +%FT%TZ) END $NAME ==="
done

python "$EXP/pack_runs.py" --work "$WORK" --dest "$WORK/pack"
echo "Packed results: $WORK/pack  -> download, then copy into results/baseline_seed_robustness/ on your PC."
if (( STOP_AT_END )) && command -v runpodctl >/dev/null && [[ -n "${RUNPOD_POD_ID:-}" ]]; then
  sync; runpodctl stop pod "$RUNPOD_POD_ID" || true   # syntax not verified in this repo: check `runpodctl --help`
fi
