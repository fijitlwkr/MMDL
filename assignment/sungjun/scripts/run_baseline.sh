#!/usr/bin/env bash
# =============================================================================
# scripts/run_baseline.sh — MMMU validation 900문항 베이스라인 측정 전 과정
#
# 단계
#   0) git 상태 점검: dirty 면 "보고용 실행"을 거부합니다 (FACTS.md 12)
#   1) preflight  : scripts/setup_pod.sh --preflight-only 재사용
#   2) --dry-run  : 모델을 올리지 않고 프롬프트/토큰 예산만 점검 (9048 이 실제로 맞는지)
#   3) --limit 30 : 스모크 테스트 겸 "버릴 1회차" (캐시/컴파일 워밍업, FACTS.md 7)
#   4) 실제 측정  : 900문항 본 실행 (여기서 나온 시간만 보고서에 씁니다)
#   5) 보고서 생성: src/report.py
#   6) 비용 추정  : 경과 시간 x GPU_HOURLY_USD
#
# 사용법
#   GPU_HOURLY_USD=0.34 bash scripts/run_baseline.sh
#
# 주요 환경변수 (기본값은 교수님 슬라이드 16 권장 설정 = FACTS.md 0)
#   GPU_HOURLY_USD=0.34     GPU 시간당 단가(USD). FACTS.md 8 의 RTX 4090 Community 근사값.
#   BACKEND=vllm            vllm | hf   (hf 는 900문항에 2~6시간, FACTS.md 13)
#   TEMPLATE=anchored       official | llava | anchored
#   DATA_PATH=MMMU/MMMU     로컬 스냅샷 경로를 넣어도 됩니다
#   RUN_DIR=...             본 실행 결과 디렉터리(기본값은 인자에서 결정, 타임스탬프 아님)
#   SMOKE_LIMIT=30  SKIP_DRYRUN=1  SKIP_SMOKE=1
#   ALLOW_DIRTY=1           git dirty 사전 점검만 건너뜀(보고용 실행에는 쓰지 마십시오)
#   FORCE_OVERWRITE=1       이미 metrics.json 이 있는 RUN_DIR 에 덮어쓰기 허용
#   REPRO=1                 vLLM 재현성 환경변수 설정(기본 1)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log()  { echo "[run] $*"; }
warn() { echo "[경고] $*" >&2; }
die()  { echo "[실패] $*" >&2; exit 1; }
rule() { echo "======================================================================="; }

trap 'echo "" >&2; echo "[실패] run_baseline.sh ${BASH_SOURCE[0]}:${LINENO} 에서 중단되었습니다. 위 메시지를 먼저 읽어 주십시오." >&2' ERR

# -----------------------------------------------------------------------------
# HuggingFace 환경변수 — python 이 시작되기 "전"에 export 합니다.
# FACTS.md 5: 모든 HF 환경변수는 import 시점에 읽힙니다. 파이썬 안에서 바꿔도 늦습니다.
# HF_DATASETS_CACHE 만 지정하면 parquet 은 컨테이너 디스크에 남으므로 HF_HOME/HF_HUB_CACHE
# 를 함께 지정합니다.
# (setup_pod.sh / fetch_data.sh 와 동일한 블록 — 독립 실행을 위한 의도적 중복입니다.)
# -----------------------------------------------------------------------------
WORKSPACE="${WORKSPACE:-/workspace}"
if [[ ! -d "$WORKSPACE" ]]; then
  mkdir -p "$WORKSPACE" 2>/dev/null || die "WORKSPACE 를 만들 수 없습니다: $WORKSPACE"
fi
export HF_HOME="${HF_HOME:-$WORKSPACE/hf}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$HF_HOME/hub}"
export HF_DATASETS_CACHE="${HF_DATASETS_CACHE:-$HF_HOME/datasets}"
export HF_XET_HIGH_PERFORMANCE=1   # FACTS.md 5: 현재 유효한 전송 가속 스위치
unset HF_HUB_ENABLE_HF_TRANSFER    # FACTS.md 5: DEPRECATED, 동작하지 않습니다
export TOKENIZERS_PARALLELISM=false
mkdir -p "$HF_HOME" "$HF_HUB_CACHE" "$HF_DATASETS_CACHE"

# 재현성 환경변수 (FACTS.md 7)
#   오프라인(LLM 클래스) 실행에서 시드가 실제로 먹으려면 V1 멀티프로세싱을 끄고 같은
#   하드웨어/같은 vLLM 버전이어야 합니다. 그래도 temperature=0.7 이므로 비트 단위
#   재현은 불가능합니다 — 팀원 간 1~2 pp 차이는 잡음입니다(두 독립 실행 차이의 95% 구간 +/- 4.33 pp).
# [금지] transformers.enable_full_determinism() 이나 CUDA_LAUNCH_BLOCKING=1 은 쓰지 않습니다.
#   모든 CUDA 런치를 직렬화해서 교수님이 요구한 경과 시간 표를 무의미하게 만듭니다(FACTS.md 7).
if [[ "${REPRO:-1}" == "1" ]]; then
  export VLLM_ENABLE_V1_MULTIPROCESSING=0
  log "REPRO=1: VLLM_ENABLE_V1_MULTIPROCESSING=0 (FACTS.md 7)"
fi

# -----------------------------------------------------------------------------
# 래퍼 로그 — 저장소 "밖"에 둡니다. 저장소 안에 만들면 방금 만든 로그 때문에
# git 이 dirty 가 되어 다음 실행이 스스로를 거부하게 됩니다.
# 실행별 공식 로그는 src/eval_mmmu.py 가 RUN_DIR/run.log 로 남깁니다.
# -----------------------------------------------------------------------------
LOG_DIR="${LOG_DIR:-$WORKSPACE/logs}"
case "$LOG_DIR" in
  "$REPO_ROOT"|"$REPO_ROOT"/*)
    # WORKSPACE 를 저장소 안으로 지정한 경우입니다. 로그 파일 하나 때문에 git 이 dirty 가
    # 되어 0단계 점검이 스스로를 거부하게 됩니다.
    echo "[경고] 래퍼 로그 경로가 저장소 안입니다: $LOG_DIR" >&2
    echo "[경고] 이 로그 파일 때문에 git 이 dirty 로 판정되어 보고용 실행이 거부됩니다." >&2
    echo "[경고] LOG_DIR 또는 WORKSPACE 를 저장소 밖(예: /workspace)으로 지정하십시오." >&2
    ;;
esac
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run_baseline-$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$LOG_FILE") 2>&1
log "래퍼 로그: $LOG_FILE"

# -----------------------------------------------------------------------------
# 실험 설정 — 기본값은 교수님 슬라이드 16 권장값(FACTS.md 0)과 Qwen 권장 시드입니다.
# 여기 보이는 값이 그대로 src/eval_mmmu.py 에 전달되고 config.json 에 기록됩니다.
# -----------------------------------------------------------------------------
MODEL_ID="${MODEL_ID:-Qwen/Qwen3-VL-4B-Instruct}"
MODEL_REV="${MODEL_REV:-ebb281ec70b05090aa6165b016eac8ec08e71b17}"   # FACTS.md 6
DATASET_ID="${DATASET_ID:-MMMU/MMMU}"
DATASET_REV="${DATASET_REV:-98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68}" # FACTS.md 4/6
DATA_PATH="${DATA_PATH:-$DATASET_ID}"   # 교수님 요구사항: 데이터 경로를 입력으로 받는 스크립트
SPLIT="${SPLIT:-validation}"
BACKEND="${BACKEND:-vllm}"
TEMPLATE="${TEMPLATE:-anchored}"
SUBJECTS="${SUBJECTS:-}"

MAX_MODEL_LEN="${MAX_MODEL_LEN:-9048}"        # FACTS.md 3: 900문항 중 0개가 초과합니다(최악 5,616 + 2,048 = 7,664)
MAX_NEW_TOKENS="${MAX_NEW_TOKENS:-2048}"
TEMPERATURE="${TEMPERATURE:-0.7}"
TOP_P="${TOP_P:-0.8}"
TOP_K="${TOP_K:-20}"
REPETITION_PENALTY="${REPETITION_PENALTY:-1.0}"
PRESENCE_PENALTY="${PRESENCE_PENALTY:-1.5}"   # FACTS.md 2: vLLM 경로에서만 적용됩니다(transformers 에는 이 인자가 없습니다)
MIN_PIXELS="${MIN_PIXELS:-1280*28*28}"        # FACTS.md 1: Qwen3-VL 에서는 980 비전 토큰 하한으로 환산됩니다
MAX_PIXELS="${MAX_PIXELS:-5120*28*28}"        # FACTS.md 1: 3,920 비전 토큰 상한으로 환산됩니다
SEED="${SEED:-3407}"                          # FACTS.md 7: Qwen README 가 Instruct 모델에 권장하는 시드
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"          # FACTS.md 8: 24GB 에서 KV ~10.8 GiB. 프로파일링에서 OOM 이면 0.85
MAX_NUM_SEQS="${MAX_NUM_SEQS:-32}"

GPU_HOURLY_USD="${GPU_HOURLY_USD:-}"
if [[ -z "$GPU_HOURLY_USD" ]]; then
  GPU_HOURLY_USD="0.34"
  warn "GPU_HOURLY_USD 가 지정되지 않아 0.34 (FACTS.md 8 의 RTX 4090 Community 근사값)을 사용합니다."
  warn "RunPod 단가는 수시로 바뀝니다. 보고서에는 실제 결제 화면의 단가를 쓰십시오."
fi

OUT_ROOT="${OUT_ROOT:-$REPO_ROOT/outputs}"
RUN_TAG="${RUN_TAG:-baseline-${BACKEND}-${TEMPLATE}-seed${SEED}}"
RUN_DIR="${RUN_DIR:-$OUT_ROOT/$RUN_TAG}"      # 타임스탬프를 쓰지 않습니다: 같은 인자면 같은 경로여야 비교가 쉽습니다
DRY_DIR="$OUT_ROOT/dryrun-${TEMPLATE}"
SMOKE_LIMIT="${SMOKE_LIMIT:-30}"
SMOKE_DIR="$OUT_ROOT/smoke-${TEMPLATE}-limit${SMOKE_LIMIT}"
REPORT_OUT="${REPORT_OUT:-$RUN_DIR/report.md}"

EVAL_PY="$REPO_ROOT/src/eval_mmmu.py"
REPORT_PY="$REPO_ROOT/src/report.py"
VENV_DIR="${VENV_DIR:-$WORKSPACE/venv}"
VPY="$VENV_DIR/bin/python"

# -----------------------------------------------------------------------------
# 0) git 위생 — 보고용 실행은 clean 한 트리에서만 (FACTS.md 12)
#    이유: env.json 에 git.commit / git.dirty 가 기록됩니다. dirty 인 상태의 커밋 해시는
#    실제로 돌린 코드를 가리키지 못하므로, 그 숫자는 재현 불가능한 숫자가 됩니다.
# -----------------------------------------------------------------------------
rule
log "[0/6] git 상태 점검"
rule
GIT_OK=1
if ! git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  GIT_OK=0
  warn "여기는 git 저장소가 아닙니다: $REPO_ROOT"
  warn "과제는 '각 팀원이 자기 계정으로 커밋' 과 재현성을 요구합니다. git init 후 팀 저장소에 연결하십시오."
else
  GIT_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo '(커밋 없음)')"
  GIT_BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '(브랜치 없음)')"
  log "commit: $GIT_COMMIT"
  log "branch: $GIT_BRANCH"
  GIT_DIRT="$(git -C "$REPO_ROOT" status --porcelain)"
  if [[ -n "$GIT_DIRT" ]]; then
    GIT_OK=0
    warn "작업 트리가 깨끗하지 않습니다. 변경/미추적 파일 목록:"
    echo "$GIT_DIRT" | sed 's/^/    /'
  else
    log "[OK] 작업 트리가 깨끗합니다."
  fi
fi
if [[ "$GIT_OK" != "1" ]]; then
  if [[ "${ALLOW_DIRTY:-0}" == "1" ]]; then
    warn "ALLOW_DIRTY=1 이므로 사전 점검을 건너뜁니다. 이 실행 결과는 '보고용' 으로 쓸 수 없습니다."
    warn "주의: src/eval_mmmu.py 도 env.json 에 git.dirty 를 기록하며 스스로 거부할 수 있습니다(FACTS.md 12)."
  else
    die "보고용 실행을 거부합니다 (FACTS.md 12).
해결 방법:
  1) 변경을 커밋하십시오          : git add -A && git commit -m '...'
  2) 이전 실행 결과물도 커밋 대상 : outputs/ 의 env.json/metrics.json/timing.json/predictions.jsonl 은 커밋합니다
  3) 잠시 치워두려면              : git stash -u
  4) 보고서와 무관한 탐색적 실행이라면 ALLOW_DIRTY=1 을 앞에 붙이십시오."
  fi
fi

# -----------------------------------------------------------------------------
# 사전 조건 확인
# -----------------------------------------------------------------------------
[[ -x "$VPY" ]] || die "평가용 venv 가 없습니다: $VENV_DIR
먼저 'bash scripts/setup_pod.sh' 를 실행하십시오."
[[ -f "$EVAL_PY" ]]   || die "평가 스크립트가 없습니다: $EVAL_PY"
[[ -f "$REPORT_PY" ]] || die "보고서 스크립트가 없습니다: $REPORT_PY"

safe_rm() {  # OUT_ROOT 밖을 지우는 사고를 구조적으로 막습니다.
  local target="${1:-}"
  [[ -n "$target" ]] || die "내부 오류: 삭제 대상이 비어 있습니다."
  case "$target" in
    "$OUT_ROOT"/?*) rm -rf "$target" ;;
    *) die "내부 오류: $OUT_ROOT 밖의 경로를 지우려 했습니다: $target" ;;
  esac
}

fmt_hms() { awk -v s="${1:-0}" 'BEGIN{t=int(s+0.5); printf "%dh %02dm %02ds", t/3600, (t%3600)/60, t%60}'; }
usd()     { awk -v s="${1:-0}" -v r="${2:-0}" 'BEGIN{printf "%.2f", s*r/3600.0}'; }

mkdir -p "$OUT_ROOT"

# 본 실행 결과를 말없이 덮어쓰지 않습니다(덮어쓰면 팀 비교용 기록이 사라집니다).
if [[ -f "$RUN_DIR/metrics.json" && "${FORCE_OVERWRITE:-0}" != "1" ]]; then
  die "이미 완료된 측정 결과가 있습니다: $RUN_DIR/metrics.json
그 위에 덮어쓰지 않습니다. 아래 중 하나를 선택하십시오.
  - 새 경로로 실행        : RUN_DIR=$OUT_ROOT/baseline-2 bash scripts/run_baseline.sh
  - 일부러 덮어쓰기       : FORCE_OVERWRITE=1 bash scripts/run_baseline.sh
  - 보고서만 다시 생성    : $VPY $REPORT_PY --run-dir '$RUN_DIR' --out '$REPORT_OUT'"
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  log "GPU: $(nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || true)"
else
  warn "nvidia-smi 가 없습니다. GPU 파드인지 확인하십시오."
fi

if [[ "$BACKEND" == "hf" ]]; then
  warn "BACKEND=hf 입니다. 900문항에 2~6시간이 걸리고(FACTS.md 13), presence_penalty=1.5 는"
  warn "transformers GenerationConfig 에 존재하지 않으므로 적용되지 않습니다(FACTS.md 2)."
  warn "시간과 비용 모두 vLLM 이 압도적으로 유리합니다. 특별한 이유가 없다면 BACKEND=vllm 을 쓰십시오."
fi

rule
log "실험 설정 요약"
rule
cat <<SUMMARY
  모델        : $MODEL_ID @ $MODEL_REV
  데이터      : $DATA_PATH  (revision $DATASET_REV, split $SPLIT)
  백엔드      : $BACKEND        템플릿: $TEMPLATE
  생성 설정   : max_model_len=$MAX_MODEL_LEN max_new_tokens=$MAX_NEW_TOKENS
                temperature=$TEMPERATURE top_p=$TOP_P top_k=$TOP_K
                repetition_penalty=$REPETITION_PENALTY presence_penalty=$PRESENCE_PENALTY
  픽셀 예산   : min_pixels=$MIN_PIXELS  max_pixels=$MAX_PIXELS
                (Qwen3-VL 기준 환산: 980 / 3,920 비전 토큰. FACTS.md 1)
  시드/메모리 : seed=$SEED gpu_memory_utilization=$GPU_MEM_UTIL max_num_seqs=$MAX_NUM_SEQS
  결과 경로   : $RUN_DIR
SUMMARY
[[ -n "$SUBJECTS" ]] && log "subject 필터: $SUBJECTS  (전체 900문항이 아니므로 보고용이 아닙니다)"

COMMON_ARGS=(
  --data-path "$DATA_PATH"
  --model "$MODEL_ID"
  --model-revision "$MODEL_REV"
  --dataset-revision "$DATASET_REV"
  --backend "$BACKEND"
  --split "$SPLIT"
  --template "$TEMPLATE"
  --max-model-len "$MAX_MODEL_LEN"
  --max-new-tokens "$MAX_NEW_TOKENS"
  --temperature "$TEMPERATURE"
  --top-p "$TOP_P"
  --top-k "$TOP_K"
  --repetition-penalty "$REPETITION_PENALTY"
  --presence-penalty "$PRESENCE_PENALTY"
  --min-pixels "$MIN_PIXELS"
  --max-pixels "$MAX_PIXELS"
  --seed "$SEED"
  --gpu-memory-utilization "$GPU_MEM_UTIL"
  --max-num-seqs "$MAX_NUM_SEQS"
)
[[ -n "$SUBJECTS" ]] && COMMON_ARGS+=( --subjects "$SUBJECTS" )

T_SCRIPT_START=$SECONDS

# -----------------------------------------------------------------------------
# 1) preflight — setup_pod.sh 의 점검 로직을 그대로 재사용합니다(중복 구현 방지).
# -----------------------------------------------------------------------------
rule
log "[1/6] preflight (스택 버전 + model_type/patch_size/spatial_merge_size 확인)"
rule
WORKSPACE="$WORKSPACE" VENV_DIR="$VENV_DIR" MODEL_ID="$MODEL_ID" MODEL_REV="$MODEL_REV" \
  bash "$SCRIPT_DIR/setup_pod.sh" --preflight-only

# -----------------------------------------------------------------------------
# 2) --dry-run — 모델을 올리지 않고 프롬프트와 토큰 예산만 확인합니다.
#    FACTS.md 3: 900문항 중 9048 을 넘는 문항은 0개여야 합니다. 여기서 초과가 보고되면
#    본 실행은 의미가 없으므로 즉시 멈추고 픽셀 예산을 다시 보십시오.
# -----------------------------------------------------------------------------
if [[ "${SKIP_DRYRUN:-0}" == "1" ]]; then
  warn "SKIP_DRYRUN=1 이므로 토큰 예산 점검을 건너뜁니다."
else
  rule
  log "[2/6] --dry-run 토큰 예산 점검 (모델 로딩 없음)"
  rule
  safe_rm "$DRY_DIR"   # 진단용 임시 산출물입니다. 매번 새로 만듭니다.
  T0=$SECONDS
  "$VPY" "$EVAL_PY" "${COMMON_ARGS[@]}" --dry-run --out "$DRY_DIR"
  log "[2/6] 완료 — 소요 $(fmt_hms $((SECONDS - T0)))"
fi

# -----------------------------------------------------------------------------
# 3) 스모크 테스트 겸 "버릴 1회차"
#    FACTS.md 7 타이밍 위생: 첫 실행은 콜드 캐시이고 vLLM 의 torch.compile / CUDA 그래프
#    캡처 시간이 섞입니다. 이 --limit 실행으로 전부 워밍업한 뒤, 4단계의 시간만 보고서에
#    사용합니다. 즉 이 단계의 정확도/시간은 "버리는 값" 입니다.
# -----------------------------------------------------------------------------
if [[ "${SKIP_SMOKE:-0}" == "1" ]]; then
  warn "SKIP_SMOKE=1 이므로 스모크/워밍업을 건너뜁니다. 본 실행 시간에 엔진 시작 비용이 섞일 수 있습니다(FACTS.md 7)."
else
  rule
  log "[3/6] 스모크 테스트 --limit $SMOKE_LIMIT  (워밍업 겸용, 결과는 버립니다)"
  rule
  safe_rm "$SMOKE_DIR"
  T0=$SECONDS
  "$VPY" "$EVAL_PY" "${COMMON_ARGS[@]}" --limit "$SMOKE_LIMIT" --out "$SMOKE_DIR"
  log "[3/6] 완료 — 소요 $(fmt_hms $((SECONDS - T0)))"
  log "스모크 결과 요약(참고용, 보고서에 쓰지 마십시오):"
  if [[ -f "$SMOKE_DIR/metrics.json" ]]; then
    "$VPY" - "$SMOKE_DIR/metrics.json" <<'PYSMOKE'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    m = json.load(fh)
ov = m.get("overall", {})
print(f"    n={ov.get('n')} correct={ov.get('correct')} accuracy={ov.get('accuracy')}")
print(f"    n_unparseable={m.get('n_unparseable')}  <- 0 이 아니면 파서 폴백(무작위 추측)이 일어났다는 뜻입니다")
PYSMOKE
  fi
fi

# -----------------------------------------------------------------------------
# 4) 본 실행 — 이 단계의 시간과 정확도만 보고서에 씁니다.
# -----------------------------------------------------------------------------
rule
log "[4/6] 본 실행: $SPLIT 전체 ($BACKEND). vLLM 기준 예상 15~45분 (FACTS.md 13)"
log "     결과 경로: $RUN_DIR"
rule
mkdir -p "$RUN_DIR"
T0=$SECONDS
"$VPY" "$EVAL_PY" "${COMMON_ARGS[@]}" --out "$RUN_DIR"
T_MAIN=$((SECONDS - T0))
log "[4/6] 완료 — 래퍼 기준 소요 $(fmt_hms "$T_MAIN")"

[[ -f "$RUN_DIR/metrics.json" ]] || die "metrics.json 이 생성되지 않았습니다: $RUN_DIR
$RUN_DIR/run.log 를 확인하십시오."

# -----------------------------------------------------------------------------
# 5) 보고서 생성
# -----------------------------------------------------------------------------
rule
log "[5/6] 보고서 생성 -> $REPORT_OUT"
rule
mkdir -p "$(dirname "$REPORT_OUT")"
"$VPY" "$REPORT_PY" --run-dir "$RUN_DIR" --out "$REPORT_OUT"
log "보고서를 만들었습니다: $REPORT_OUT"

# -----------------------------------------------------------------------------
# 6) 결과 요약 + 비용 추정
# -----------------------------------------------------------------------------
T_TOTAL=$((SECONDS - T_SCRIPT_START))
rule
log "[6/6] 결과 요약"
rule
"$VPY" - "$RUN_DIR" <<'PYFINAL'
import json
import os
import sys

run_dir = sys.argv[1]


def load(name):
    path = os.path.join(run_dir, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


metrics = load("metrics.json") or {}
timing = load("timing.json") or {}

ov = metrics.get("overall", {})
acc = ov.get("accuracy")
ref = (metrics.get("published_reference") or {}).get("mmmu_val")
print("정확도")
print(f"  전체            : n={ov.get('n')}  correct={ov.get('correct')}  accuracy={acc}")
if acc is not None and ref is not None:
    a = float(acc)
    # accuracy 가 0~1 스케일이면 백분율로 환산해 공개 점수와 같은 단위로 비교합니다.
    a_pct = a * 100.0 if a <= 1.0 else a
    print(f"  공개 점수       : {ref} (Qwen3-VL 기술 보고서)")
    print(f"  차이            : {a_pct - float(ref):+.2f} pp")
    print("  해석 (FACTS.md 7): n=900, p=0.674 에서 표준오차는 1.56 pp 이고")
    print("                    두 독립 실행 차이의 95% 구간은 +/- 4.33 pp 입니다.")
    print("                    1~2 pp 차이는 샘플링 잡음이며 버그가 아닙니다.")
print(f"  MC / open       : {metrics.get('multiple_choice', {}).get('accuracy')}"
      f" / {metrics.get('open_ended', {}).get('accuracy')}")
print(f"  n_unparseable   : {metrics.get('n_unparseable')}"
      "   <- 공식 파서가 무작위 추측으로 떨어진 횟수(FACTS.md 4c)")
print(f"  집계 방식       : {metrics.get('aggregation')}")

print("\n시간")
total_wall = timing.get("total_wall_s")
print(f"  total_wall_s    : {total_wall}")
print(f"  model_load_s    : {timing.get('model_load_s')}   <- 첫 subject 에 엔진 시작 비용이 섞이지 않도록 분리 기록")
print(f"  inference_s     : {timing.get('inference_s')}")
print(f"  scoring_s       : {timing.get('scoring_s')}")
PYFINAL

# 비용 계산에는 timing.json 의 total_wall_s(평가 스크립트가 직접 측정한 값)를 씁니다.
# 래퍼가 잰 $T_MAIN 은 파이썬 기동 시간까지 포함하므로 예비값으로만 사용합니다.
RUN_WALL="$("$VPY" -c 'import json,sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    v = d.get("total_wall_s")
except Exception:
    v = None
print("" if v is None else v)' "$RUN_DIR/timing.json" 2>/dev/null || true)"
[[ -n "$RUN_WALL" ]] || { RUN_WALL="$T_MAIN"; warn "timing.json 에서 total_wall_s 를 읽지 못해 래퍼 측정값을 사용합니다."; }

rule
log "비용 추정 (GPU_HOURLY_USD=$GPU_HOURLY_USD)"
rule
printf '  본 측정(900문항) : %s  ->  약 $%s\n' "$(fmt_hms "$RUN_WALL")" "$(usd "$RUN_WALL" "$GPU_HOURLY_USD")"
printf '  이 스크립트 전체 : %s  ->  약 $%s\n' "$(fmt_hms "$T_TOTAL")" "$(usd "$T_TOTAL" "$GPU_HOURLY_USD")"
cat <<'COSTNOTE'

  [중요] 위 금액은 "하한" 입니다 (FACTS.md 8).
   - RunPod 은 GPU 사용률과 무관하게 파드 시작부터 종료까지 초 단위로 과금합니다.
     즉 실제 청구액은 (파드 생성 ~ terminate) 전체 시간 기준이며, 셋업/다운로드/대기
     시간까지 포함됩니다. 셋업 ~15분 + 평가 20~40분 => 4090 Community 기준 대략 $0.30~$0.60.
   - stop(정지) 상태에서도 볼륨 디스크 요금($0.20/GB/월)은 계속 나갑니다.
     네트워크 볼륨은 $0.07/GB/월(1TB 미만)이며 실행 여부와 무관하게 과금됩니다.
   - 단가는 수시로 변합니다. 보고서에는 결제 화면의 실제 단가와 실제 과금 시간을 쓰십시오.
COSTNOTE

rule
log "완료했습니다. 다음에 할 일"
rule
cat <<NEXT
  1) 결과물을 확인하고 커밋하십시오(재현성 증거입니다):
       $RUN_DIR/env.json  ENVIRONMENT.md  config.json  metrics.json  timing.json
       $RUN_DIR/predictions.jsonl   (최악의 경우에도 ~7.4 MB, Git LFS 불필요 — FACTS.md 12)
       $RUN_DIR/run.log
  2) 보고서 초안: $REPORT_OUT
     제출 경로는 assignment/assignment1.md 입니다. 예:
       cp '$REPORT_OUT' '$REPO_ROOT/assignment/assignment1.md'
  3) 팀원 4명의 결과를 한 표로 비교하려면:
       $VPY $REPORT_PY --run-dir '$RUN_DIR' --compare <팀원1 run_dir> <팀원2 run_dir> ...
  4) 파드를 terminate 하십시오. 지금도 과금되고 있습니다.
NEXT
log "래퍼 로그: $LOG_FILE"
