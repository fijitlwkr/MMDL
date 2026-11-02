#!/usr/bin/env bash
# 가설 A 평가: 학습된 모델(E1~E3) × 시드(42, 1234, 2026)를 차례로 생성(추론)만 한다. 채점은 파드 밖에서 한다.
# baseline 시드 실험(exp/baseline-seed-robustness 의 run_all.sh)과 같은 방식이다.
#   - code/ 가 그 실험 때와 바이트까지 같은지 해시로 검사한다(E0 와 비교하려면 생성 코드가 같아야 한다).
#   - config 는 code/config.yaml 에서 sampling seed 만 바꾼다(engine seed 3407 고정). make_seed_config.py 가 그 외 변경을 막는다.
#   - arm 하나씩 순차 실행하고, 중간에 끊긴 arm 은 이어받지 않는다(배치 구성이 달라지므로).
# 다른 점: --model_path/--revision 으로 학습된 모델을 고정 버전으로 받고, arm 이 끝날 때마다 결과 폴더를 HF 데이터셋에 올린다.
#
#   bash experiments/hypA-eval/run_eval.sh --arms e1:42            # 첫 실행: E1 시드 42 하나
#   bash experiments/hypA-eval/run_eval.sh --arms e1:1234,e1:2026  # 이어서 원하는 arm 만
#   bash experiments/hypA-eval/run_eval.sh                         # --arms 를 빼면 9개 전부
# 비공개 모델을 받고 결과를 올리려면 먼저 huggingface-cli login (쓰기 토큰)이 필요하다.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXP="$REPO/experiments/hypA-eval"
WORK="${WORK:-/workspace/hypA_eval}"
export HF_HOME="${HF_HOME:-/workspace/.cache/huggingface}"
DATA_ROOT="${DATA_ROOT:-/workspace/.cache/hf_datasets}"
RESULT_REPO="${RESULT_REPO:-MMDL-team4/hypA-eval-raw}"
CODE_FREEZE="0e7ffcddf5c821bf6975e2373a2f60dc75ea61e0bbbfb7037e1e6f92b0157537"  # baseline 시드 실험 때 code/ 해시
ENGINE_SEED=3407
model_repo() { case "$1" in e1) echo MMDL-team4/hypA-e1-matched-2k;; e2) echo MMDL-team4/hypA-e2-control-2k;;
  e3) echo MMDL-team4/hypA-e3-general-2k;; *) return 1;; esac; }
model_rev() { case "$1" in e1) echo 8a13d9e67dd5ff16c5407dd756962ecff725eabe;; e2) echo 7d4a8a58c427fdcbb6e9b0382e6176630770c57f;;
  e3) echo e591371e742f8e5cd4e7859d892305789c3b8516;; *) return 1;; esac; }

ARMS="e1:42,e1:1234,e1:2026,e2:42,e2:1234,e2:2026,e3:42,e3:1234,e3:2026"; INSTALL=0; UPLOAD=1; SKIP_FREEZE=0
while (($#)); do case "$1" in
  --arms) ARMS="$2"; shift 2;;
  --install) INSTALL=1; shift;;
  --no_upload) UPLOAD=0; shift;;
  --skip_freeze_check) SKIP_FREEZE=1; shift;;
  *) echo "unknown arg $1" >&2; exit 2;; esac; done

if (( ! SKIP_FREEZE )); then
  NOW="$(cd "$REPO" && find code -type f ! -path '*/tests/*' ! -path '*/__pycache__/*' ! -name '*.pyc' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1)"
  [[ "$NOW" == "$CODE_FREEZE" ]] || { echo "ABORT: code/ 가 baseline 시드 실험 때와 다름 ($NOW)" >&2; exit 3; }
fi
for spec in ${ARMS//,/ }; do
  model_repo "${spec%%:*}" >/dev/null || { echo "unknown model in arm '$spec' (e1/e2/e3)" >&2; exit 2; }
  [[ "${spec#*:}" =~ ^[0-9]+$ ]] || { echo "bad seed in arm '$spec'" >&2; exit 2; }
done
mkdir -p "$WORK"; cd "$REPO"
# 비공개 모델에 접근되는지 먼저 확인한다(토큰은 이 HF_HOME 기준으로 찾는다)
for m in $(for spec in ${ARMS//,/ }; do echo "${spec%%:*}"; done | sort -u); do
  python -c "import sys; from huggingface_hub import HfApi; HfApi().model_info(sys.argv[1], revision=sys.argv[2])" \
    "$(model_repo "$m")" "$(model_rev "$m")" >/dev/null 2>&1 \
    || { echo "ABORT: $(model_repo "$m") 에 접근할 수 없음. 'HF_HOME=$HF_HOME huggingface-cli login' 을 했는지 확인" >&2; exit 4; }
done
T0=$(date +%s)

for spec in ${ARMS//,/ }; do
  IFS=: read -r M S <<<"$spec"
  MREPO="$(model_repo "$M")"; MREV="$(model_rev "$M")"
  NAME="${M}_seed_${S}"; OUT="$WORK/$NAME"
  if [[ -f "$OUT/DONE" ]]; then echo "[skip] $NAME already DONE"; continue; fi
  if [[ -d "$OUT" ]]; then mv "$OUT" "$OUT.partial.$(date -u +%Y%m%dT%H%M%SZ)"; fi
  mkdir -p "$OUT"
  python "$EXP/make_seed_config.py" --base "$REPO/code/config.yaml" --out "$OUT/config_used.yaml" \
    --sampling-seed "$S" --engine-seed "$ENGINE_SEED"
  ARGS=(--config "$OUT/config_used.yaml" --out "$OUT" --data_root "$DATA_ROOT"
        --model_path "$MREPO" --revision "$MREV")
  if (( INSTALL )); then ARGS+=(--install); INSTALL=0; fi
  A0=$(date +%s)
  echo "=== $(date -u +%FT%TZ) START $NAME model=$MREPO@${MREV:0:7} sampling_seed=$S ==="
  bash code/run_generate.sh "${ARGS[@]}"
  touch "$OUT/DONE"
  echo "$(( ($(date +%s) - A0) / 60 ))" > "$OUT/arm_minutes.txt"
  echo "=== $(date -u +%FT%TZ) END $NAME  $(cat "$OUT/arm_minutes.txt") min (누적 $(( ($(date +%s) - T0) / 60 )) min) ==="
  if (( UPLOAD )); then
    python - "$OUT" "$RESULT_REPO" "$NAME" <<'PY'
import sys, time
from huggingface_hub import HfApi
out, repo, name = sys.argv[1:4]
api = HfApi()
for i in range(5):
    try:
        api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
        api.upload_folder(folder_path=out, repo_id=repo, repo_type="dataset", path_in_repo=name,
                          commit_message=f"Add {name} generation output")
        print(f"[uploaded] {repo}/{name}")
        break
    except Exception as e:
        print(f"[upload retry {i + 1}/5] {str(e)[:200]}")
        time.sleep(60)
else:
    print(f"!!! 업로드 실패. {out} 을 직접 받아 두세요 !!!")
PY
  fi
done
echo "=== $(date -u +%FT%TZ) 끝. 결과: $WORK (HF: $RESULT_REPO). 파드는 직접 Terminate 하세요. ==="
