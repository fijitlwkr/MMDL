#!/usr/bin/env bash
# GENERATION ONLY sweep for the seed-robustness experiment (GPU pod). Scoring is done later by score_runs.sh,
# off the pod, because the Judge calls are sequential (~345 per arm) and would keep the GPU idle (billed).
# Run from the repo root on branch exp/baseline-seed-robustness. Never modifies code/.
#
#   bash experiments/baseline_seed_robustness/run_all.sh --tier 1 --install      # required arms
#   bash experiments/baseline_seed_robustness/run_all.sh --tier 2                # only if the Tier-2 trigger fires
#   bash experiments/baseline_seed_robustness/run_all.sh --tier 3                # only if the Tier-3 trigger fires
#   add  --stop_grace_min N   -> safety net: N minutes after the LAST arm, the pod is stopped via runpodctl (only if
#                                runpodctl and RUNPOD_POD_ID exist; otherwise a loud warning says it was NOT stopped).
#   Each finished arm is packed immediately into $WORK/pack so it can be downloaded while the next arm still runs.
#
# Arm = name:sampling_seed:engine_seed.  Baseline (submitted) = sampling 3407 / engine 3407.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXP="$REPO/experiments/baseline_seed_robustness"
WORK="${WORK:-/workspace/seedexp}"
export HF_HOME="${HF_HOME:-/workspace/.cache/huggingface}"
DATA_ROOT="${DATA_ROOT:-/workspace/.cache/hf_datasets}"
TIER=1; INSTALL=0; GRACE=""; SKIP_FREEZE=0
while (($#)); do case "$1" in
  --tier) TIER="$2"; shift 2;;
  --install) INSTALL=1; shift;;
  --stop_grace_min) GRACE="$2"; shift 2;;
  --skip_freeze_check) SKIP_FREEZE=1; shift;;
  *) echo "unknown arg $1" >&2; exit 2;; esac; done

TIER1=("seed_42:42:3407" "seed_1234:1234:3407" "seed_2026:2026:3407")   # required
TIER2=("seed_777:777:3407" "seed_31337:31337:3407")                     # conditional (README s4)
TIER3=("ctrl_repeat:3407:3407")                                         # conditional (README s4)
[[ -z "$GRACE" || "$GRACE" =~ ^[0-9]+$ ]] || { echo "--stop_grace_min needs a non-negative integer" >&2; exit 2; }
case "$TIER" in 1) ARMS=("${TIER1[@]}");; 2) ARMS=("${TIER2[@]}");; 3) ARMS=("${TIER3[@]}");;
  *) echo "--tier 1|2|3" >&2; exit 2;; esac

# Guard: generation code must be byte-identical to the frozen baseline code.
if (( ! SKIP_FREEZE )); then
  NOW="$(cd "$REPO" && find code -type f ! -path '*/tests/*' ! -path '*/__pycache__/*' ! -name '*.pyc' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1)"
  WANT="$(tr -d ' \n' < "$EXP/CODE_FREEZE.sha256")"
  [[ "$NOW" == "$WANT" ]] || { echo "ABORT: code/ differs from frozen baseline code ($NOW != $WANT)" >&2; exit 3; }
fi
mkdir -p "$WORK"; cd "$REPO"
T0=$(date +%s); DONE_N=0; RAN_N=0; TOTAL_N=${#ARMS[@]}

for spec in "${ARMS[@]}"; do
  IFS=: read -r NAME SSEED ESEED <<<"$spec"
  OUT="$WORK/$NAME"
  if [[ -f "$OUT/DONE" ]]; then echo "[skip] $NAME already DONE"; DONE_N=$((DONE_N+1)); continue; fi
  # A resumed run changes batch composition -> never resume; keep the partial output aside.
  if [[ -d "$OUT" ]]; then mv "$OUT" "$OUT.partial.$(date -u +%Y%m%dT%H%M%SZ)"; fi
  mkdir -p "$OUT"
  python "$EXP/make_seed_config.py" --out "$OUT/config_used.yaml" --sampling-seed "$SSEED" --engine-seed "$ESEED"
  ARGS=(--config "$OUT/config_used.yaml" --out "$OUT" --data_root "$DATA_ROOT")
  if (( INSTALL )); then ARGS+=(--install); INSTALL=0; fi
  A0=$(date +%s)
  echo "=== $(date -u +%FT%TZ) START $NAME sampling_seed=$SSEED engine_seed=$ESEED ==="
  bash code/run_generate.sh "${ARGS[@]}"
  touch "$OUT/DONE"
  python "$EXP/pack_runs.py" --work "$WORK" --dest "$WORK/pack" --raw_only >/dev/null && echo "[packed] $WORK/pack/$NAME is ready to download"
  DONE_N=$((DONE_N+1)); RAN_N=$((RAN_N+1)); A1=$(date +%s)
  AVG=$(( (A1 - T0) / RAN_N )); LEFT=$(( (TOTAL_N - DONE_N) * AVG ))   # average over arms run in THIS invocation only
  echo "=== $(date -u +%FT%TZ) END $NAME  arm=$(( (A1-A0)/60 )) min | done $DONE_N/$TOTAL_N | ETA ~$(( LEFT/60 )) min ==="
done

echo "=== $(date -u +%FT%TZ) ALL ARMS FINISHED. Download $WORK/pack now (tar czf ...), score locally, then STOP/TERMINATE the pod. ==="
if [[ -n "$GRACE" ]]; then
  if command -v runpodctl >/dev/null && [[ -n "${RUNPOD_POD_ID:-}" ]]; then
    echo "SAFETY NET: pod $RUNPOD_POD_ID will be stopped in $GRACE min (Ctrl+C cancels the timer; stop it yourself from the console)."
    sleep $(( GRACE * 60 )); sync
    runpodctl stop pod "$RUNPOD_POD_ID" || echo "!!! runpodctl stop FAILED - POD IS STILL RUNNING AND BILLING. Stop it from the console now. !!!"
  else
    echo "!!! SAFETY NET UNAVAILABLE (runpodctl or RUNPOD_POD_ID missing): POD WILL NOT STOP BY ITSELF. Stop it from the console. !!!"
  fi
else
  echo "No auto-stop requested: the pod keeps billing until YOU stop it."
fi
