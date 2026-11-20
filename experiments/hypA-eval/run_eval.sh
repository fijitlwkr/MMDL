#!/usr/bin/env bash
# 가설 A 평가: 학습된 모델(E1~E3) × 시드(42, 1234, 2026)를 차례로 생성(추론)만 한다. 채점은 파드 밖에서 한다.
# baseline 시드 실험(exp/baseline-seed-robustness 의 run_all.sh)과 같은 방식이다.
#   - code/ 가 그 실험 때와 바이트까지 같은지 해시로 검사한다(E0 와 비교하려면 생성 코드가 같아야 한다).
#   - config 는 code/config.yaml 에서 sampling seed 만 바꾼다(engine seed 3407 고정). make_seed_config.py 가 그 외 변경을 막는다.
#   - arm 하나씩 순차 실행하고, 중간에 끊긴 arm 은 이어받지 않는다(배치 구성이 달라지므로).
# 다른 점: --model_path/--revision 으로 학습된 모델을 고정 버전으로 받고, arm 이 끝날 때마다 결과 폴더를 HF 데이터셋에 올린다.
# g10/g20/g30 (2026-11-17 추가): GRPO 30스텝 학습의 step10/20/30 LoRA 어댑터(MMDL-team4/hypA-grpo-pilot30-ckpt).
#   병합본이 없어서 arm 을 돌리기 전에 merge_adapter.py 로 베이스(config.yaml 의 고정 revision)에 병합해 $WORK/merged/<이름> 에
#   만들고, 그 로컬 폴더를 --model_path 로 넘긴다. 어댑터 저장소는 시작할 때 commit sha 로 고정하고(ADAPTER_REV 로 지정 가능)
#   그 sha 를 --revision 으로 기록한다. 병합에는 peft 가 필요하다(README 참고). 생성 코드·config·시드는 E1~E3 와 같다.
# g25/g50/g75/g100 (2026-11-20 추가): lr 1e-4 로 100스텝 다시 학습한 어댑터(MMDL-team4/hypA-grpo-step100-ckpt 의 step25~100).
#   어댑터 저장소는 arm 이름으로 정해진다(g10~g30 = 파일럿 저장소, g25~g100 = step100 저장소). 한 번 실행에 두 저장소를 섞을 수 없다.
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
# GRPO arm → 어댑터 묶음. pilot30 = 파일럿(lr 1e-5, 30스텝), step100 = 재학습(lr 1e-4, 100스텝)
grpo_family() { case "$1" in g10|g20|g30) echo pilot30;; g25|g50|g75|g100) echo step100;; *) return 1;; esac; }
family_repo() { case "$1" in pilot30) echo MMDL-team4/hypA-grpo-pilot30-ckpt;; step100) echo MMDL-team4/hypA-grpo-step100-ckpt;; *) return 1;; esac; }
is_grpo() { grpo_family "$1" >/dev/null 2>&1; }
# ADAPTER_REPO·ADAPTER_REV 는 arm 을 읽은 뒤 정한다(아래). 첫 실행 때 sha 로 고정해 adapter_rev_<묶음>.txt 에 저장, 이후 실행은 그 sha
model_repo() { case "$1" in e1) echo MMDL-team4/hypA-e1-matched-2k;; e2) echo MMDL-team4/hypA-e2-control-2k;;
  e3) echo MMDL-team4/hypA-e3-general-2k;; *) is_grpo "$1" && echo "$WORK/merged/$1";; esac; }
model_rev() { case "$1" in e1) echo 8a13d9e67dd5ff16c5407dd756962ecff725eabe;; e2) echo 7d4a8a58c427fdcbb6e9b0382e6176630770c57f;;
  e3) echo e591371e742f8e5cd4e7859d892305789c3b8516;; *) is_grpo "$1" && echo "$ADAPTER_REV";; esac; }

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
  model_repo "${spec%%:*}" >/dev/null || { echo "unknown model in arm '$spec' (e1/e2/e3/g10/g20/g30/g25/g50/g75/g100)" >&2; exit 2; }
  [[ "${spec#*:}" =~ ^[0-9]+$ ]] || { echo "bad seed in arm '$spec'" >&2; exit 2; }
done
mkdir -p "$WORK"; cd "$REPO"
# 비공개 모델에 접근되는지 먼저 확인한다(토큰은 이 HF_HOME 기준으로 찾는다)
MODELS="$(for spec in ${ARMS//,/ }; do echo "${spec%%:*}"; done | sort -u)"
FAMILIES="$(for m in $MODELS; do grpo_family "$m" 2>/dev/null || true; done | sort -u)"
if [[ -n "$FAMILIES" ]]; then
  [[ "$(wc -w <<<"$FAMILIES")" -eq 1 ]] || { echo "ABORT: 파일럿(g10~g30)과 step100(g25~g100) arm 은 따로 실행" >&2; exit 2; }
  ADAPTER_REPO="${ADAPTER_REPO:-$(family_repo "$FAMILIES")}"
  ADAPTER_REV="${ADAPTER_REV:-$(cat "$WORK/adapter_rev_$FAMILIES.txt" 2>/dev/null || echo main)}"
fi
for m in $MODELS; do
  is_grpo "$m" && continue
  python -c "import sys; from huggingface_hub import HfApi; HfApi().model_info(sys.argv[1], revision=sys.argv[2])" \
    "$(model_repo "$m")" "$(model_rev "$m")" >/dev/null 2>&1 \
    || { echo "ABORT: $(model_repo "$m") 에 접근할 수 없음. 'HF_HOME=$HF_HOME huggingface-cli login' 을 했는지 확인" >&2; exit 4; }
done
# GRPO 어댑터: 저장소 sha 고정 → 필요한 step 을 모두 병합(이미 MERGE_OK 면 건너뜀). 병합이 실패하면 GPU 평가 전에 멈춘다.
if grep -qE '^g' <<<"$MODELS"; then
  python -c "import peft" 2>/dev/null || { echo "ABORT: peft 가 없음. README 의 peft 설치 명령을 먼저 실행" >&2; exit 4; }
  ADAPTER_REV="$(python -c "import sys; from huggingface_hub import HfApi; print(HfApi().model_info(sys.argv[1], revision=sys.argv[2]).sha)" \
    "$ADAPTER_REPO" "$ADAPTER_REV" 2>/dev/null)" \
    || { echo "ABORT: $ADAPTER_REPO 에 접근할 수 없음. 'HF_HOME=$HF_HOME huggingface-cli login' 을 했는지 확인" >&2; exit 4; }
  mkdir -p "$WORK"; echo "$ADAPTER_REV" > "$WORK/adapter_rev_$FAMILIES.txt"
  echo "adapter repo $ADAPTER_REPO @ $ADAPTER_REV"
  for m in $MODELS; do
    is_grpo "$m" || continue
    MERGE_EXTRA=(); [[ "${SKIP_BASE_CHECK:-0}" == 1 ]] && MERGE_EXTRA+=(--skip_base_check)
    python -u "$EXP/merge_adapter.py" --adapter_repo "$ADAPTER_REPO" --adapter_rev "$ADAPTER_REV" --subfolder "step${m#g}" \
      --config "$REPO/code/config.yaml" --out "$(model_repo "$m")" "${MERGE_EXTRA[@]}" 2>&1 | tee "$WORK/merge_$m.log"
    [[ -f "$(model_repo "$m")/MERGE_OK" ]] || { echo "ABORT: $m 병합 실패 ($WORK/merge_$m.log)" >&2; exit 5; }
    grep -q "\"adapter_rev\": \"$ADAPTER_REV\"" "$(model_repo "$m")/merge_info.json" \
      || { echo "ABORT: $(model_repo "$m") 는 다른 어댑터 버전으로 병합됨. 폴더를 지우고 다시 실행" >&2; exit 5; }
  done
fi
T0=$(date +%s)

for spec in ${ARMS//,/ }; do
  IFS=: read -r M S <<<"$spec"
  MREPO="$(model_repo "$M")"; MREV="$(model_rev "$M")"
  NAME="${M}_seed_${S}"; OUT="$WORK/$NAME"
  if [[ -f "$OUT/DONE" ]]; then echo "[skip] $NAME already DONE"; continue; fi
  if [[ -d "$OUT" ]]; then mv "$OUT" "$OUT.partial.$(date -u +%Y%m%dT%H%M%SZ)"; fi
  mkdir -p "$OUT"
  if is_grpo "$M"; then cp "$MREPO/merge_info.json" "$OUT/merge_info.json"; fi
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
