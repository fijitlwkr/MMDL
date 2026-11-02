#!/usr/bin/env bash
# 가설 A 채점: HF(MMDL-team4/hypA-eval-raw)의 E1~E3 × 시드 답안을 받아 팀 채점기(code/scoring/evaluate.py)로 채점한다.
# 맥에서 돌린다(GPU 불필요). 채점 방식은 baseline 시드 실험(score_runs.sh)과 같다: prepare(규칙 채점) → run(judge) → summarize.
#
#   bash experiments/hypA-eval/score_all.sh --work <작업 폴더>              # 받기 + 규칙 채점 + judge. OpenAI 키는 시작할 때 한 번 묻는다(화면·파일에 남지 않음)
#   bash experiments/hypA-eval/score_all.sh --work <작업 폴더> --no_judge   # 받기 + 규칙 채점만. API 호출 없음
#
# 작업 폴더는 재부팅에 지워지지 않는 곳에 둔다(유료 judge 응답이 여기 저장된다). 끝나면 pack_runs.py 로 커밋용 묶음을 만든다.
# 아직 HF 에 없는 실행은 건너뛰고, 채점이 끝난 실행(scoring/FINAL_OK)도 건너뛴다. 그래서 몇 번 다시 돌려도 된다.
# judge 호출이 실패하면 evaluate.py 가 그 실행만 멈춘다. 로그(<작업 폴더>/<실행>/score.log)를 보고 원인을 확인한 뒤 다시 돌린다.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PY:-python3}"
RESULT_REPO="${RESULT_REPO:-MMDL-team4/hypA-eval-raw}"
ARMS=(e1_seed_42 e1_seed_1234 e1_seed_2026 e2_seed_42 e2_seed_1234 e2_seed_2026 e3_seed_42 e3_seed_1234 e3_seed_2026)
STAGE=""; JUDGE=1
while (($#)); do case "$1" in
  --work) STAGE="$2"; shift 2;; --no_judge) JUDGE=0; shift;;
  *) echo "unknown arg $1" >&2; exit 2;; esac; done
[[ -n "$STAGE" ]] || { echo "need --work <dir>" >&2; exit 2; }

mkdir -p "$STAGE"
"$PY" - "$RESULT_REPO" "$STAGE" "${ARMS[@]}" <<'EOF' || { echo "HF 다운로드 실패" >&2; exit 3; }
import sys
from huggingface_hub import snapshot_download
repo, stage, arms = sys.argv[1], sys.argv[2], sys.argv[3:]
snapshot_download(repo, repo_type="dataset", local_dir=stage, local_dir_use_symlinks=False,
                  allow_patterns=[f"{a}/*" for a in arms])
EOF

if (( JUDGE )); then
  if [[ -z "${OPENAI_API_KEY:-}" ]]; then read -rs -p "OpenAI API key: " OPENAI_API_KEY; echo; fi
  [[ -n "$OPENAI_API_KEY" ]] || { echo "키가 비어 있음" >&2; exit 2; }
  export OPENAI_API_KEY
fi

cd "$REPO"
FAILED=()
for n in "${ARMS[@]}"; do d="$STAGE/$n"
  [[ -f "$d/raw.jsonl" && -f "$d/DONE" ]] || { echo "[없음] $n (아직 HF 에 없음)"; continue; }
  [[ -f "$d/scoring/FINAL_OK" ]] && { echo "[완료] $n"; continue; }
  echo "=== SCORE $n $(date -u +%FT%TZ) ==="
  # prepare 는 비어 있지 않은 --out 을 거부하므로 처음 한 번만 한다. 이후엔 run 이 저장된 응답을 재사용해 이어서 한다.
  if [[ ! -f "$d/scoring/manifest.json" ]]; then
    "$PY" code/scoring/evaluate.py prepare --raw "$d/raw.jsonl" --config "$d/config_used.yaml" --out "$d/scoring" >/dev/null \
      || { FAILED+=("$n:prepare"); continue; }
  fi
  (( JUDGE )) || continue
  "$PY" code/scoring/evaluate.py run --out "$d/scoring" 2>&1 | tee -a "$d/score.log"
  (( PIPESTATUS[0] == 0 )) || { FAILED+=("$n:judge"); echo "!! $n judge 실패 (로그: $d/score.log)"; continue; }
  "$PY" code/scoring/evaluate.py summarize --out "$d/scoring" >/dev/null && touch "$d/scoring/FINAL_OK"
done

echo
printf "%-14s %8s %8s %8s %8s\n" arm accuracy correct judge pending
for n in "${ARMS[@]}"; do s="$STAGE/$n/scoring/summary.json"; [[ -f "$s" ]] || continue
  "$PY" -c "
import json, sys
d = json.load(open(sys.argv[1])); o = d['overall']
acc = f\"{o['accuracy'] * 100:.2f}\" if o['accuracy'] is not None else '-'
print(f\"{sys.argv[2]:<14} {acc:>8} {o['correct']:>8} {d['judge_count']:>8} {o['pending']:>8}\")" "$s" "$n"
done
echo "실패: ${FAILED[*]:-없음}"; (( ${#FAILED[@]} )) && exit 1 || exit 0
