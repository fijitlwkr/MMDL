#!/usr/bin/env bash
# Off-pod scoring (CPU only; needs python3 + PyYAML + internet + OPENAI_API_KEY). Never needs a GPU.
# Judge calls are SEQUENTIAL (~345/arm, ~1-3 s each, unmeasured) and have NO automatic retry: a failed call leaves
# an "unresolved attempt" and evaluate.py refuses to continue until errors.jsonl/api_attempts.jsonl are inspected.
# So each arm is scored independently; one failing arm does not stop the others.
#
#   export OPENAI_API_KEY=sk-...
#   bash experiments/baseline_seed_robustness/score_runs.sh --src <downloaded pack dir> --dest results/baseline_seed_robustness [--include_existing] [--no_judge]
#
# --include_existing adds, with NO GPU: rep_draft + rep_new_output (the two earlier same-seed 8192 runs already in the repo)
#                     and rescore_baseline (same raw as the submission, fresh Judge calls = Judge-noise control).
# --no_judge          offline "prepare" only (validates raw, MMMU-rule score; hybrid score stays pending).
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; EXP="$REPO/experiments/baseline_seed_robustness"
SRC=""; DEST="$REPO/results/baseline_seed_robustness"; EXISTING=0; JUDGE=1
while (($#)); do case "$1" in
  --src) SRC="$2"; shift 2;; --dest) DEST="$2"; shift 2;;
  --include_existing) EXISTING=1; shift;; --no_judge) JUDGE=0; shift;;
  *) echo "unknown arg $1" >&2; exit 2;; esac; done
[[ -n "$SRC" || $EXISTING -eq 1 ]] || { echo "need --src and/or --include_existing" >&2; exit 2; }
(( JUDGE )) && [[ -z "${OPENAI_API_KEY:-}" ]] && { echo "OPENAI_API_KEY not set (or use --no_judge)" >&2; exit 2; }
cd "$REPO"; STAGE="${STAGE_DIR:-/tmp/seed_scoring_stage}"; mkdir -p "$STAGE"
# staging area = arms to score (copied raw, never touches repo files)
[[ -n "$SRC" ]] && for d in "$SRC"/*/; do n="$(basename "$d")"; [[ -f "$d/raw.jsonl" || -f "$d/raw.jsonl.gz" ]] || continue
  mkdir -p "$STAGE/$n"; cp -r "$d"/. "$STAGE/$n/"; [[ -f "$STAGE/$n/raw.jsonl.gz" && ! -f "$STAGE/$n/raw.jsonl" ]] && gunzip -k "$STAGE/$n/raw.jsonl.gz"
  [[ -f "$STAGE/$n/config_used.yaml" ]] || cp code/config.yaml "$STAGE/$n/config_used.yaml"; done
if (( EXISTING )); then
  add() { mkdir -p "$STAGE/$1"; cp "$2/raw.jsonl" "$STAGE/$1/raw.jsonl"; cp code/config.yaml "$STAGE/$1/config_used.yaml"; touch "$STAGE/$1/NO_RAW"; }
  add rep_draft assignment/runs/draft
  add rep_new_output assignment/runs/new_output_run_max_new_tokens8192
  add rescore_baseline results/mmmu_team_baseline
fi
FAILED=()
for d in "$STAGE"/*/; do n="$(basename "$d")"; [[ -f "$d/raw.jsonl" ]] || continue
  [[ -f "$d/scoring/FINAL_OK" ]] && { echo "[skip] $n scored"; continue; }
  echo "=== SCORE $n $(date -u +%FT%TZ) ==="
  # prepare refuses a non-empty --out, so only run it the first time; later runs resume with `run` (cached responses are reused).
  if [[ ! -f "$d/scoring/manifest.json" ]]; then
    python code/scoring/evaluate.py prepare --raw "$d/raw.jsonl" --config "$d/config_used.yaml" --out "$d/scoring" >/dev/null || { FAILED+=("$n:prepare"); continue; }
  fi
  if (( JUDGE )); then
    python code/scoring/evaluate.py run --out "$d/scoring" || { FAILED+=("$n:judge"); echo "!! $n judge failed: inspect $d/scoring/errors.jsonl, DO NOT blindly re-run (see header)"; continue; }
    python code/scoring/evaluate.py summarize --out "$d/scoring" >/dev/null && touch "$d/scoring/FINAL_OK"
  fi
done
python "$EXP/pack_runs.py" --work "$STAGE" --dest "$DEST"
echo "Packed into $DEST. Failed: ${FAILED[*]:-none}"; (( ${#FAILED[@]} )) && exit 1 || exit 0
