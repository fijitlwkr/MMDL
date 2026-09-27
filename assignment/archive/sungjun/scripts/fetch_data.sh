#!/usr/bin/env bash
# =============================================================================
# scripts/fetch_data.sh — 평가에 필요한 "최소한"만 고정 revision 으로 내려받고 검증합니다.
#
# 하는 일
#   1) MMMU/MMMU 의 validation parquet 만 내려받습니다 (~341 MB).
#      전체 저장소는 3.66 GB / 92 parquet 이므로 ~3.3 GB 와 그만큼의 RunPod 과금 시간을
#      절약합니다. (FACTS.md 4)
#   2) Qwen/Qwen3-VL-4B-Instruct 를 고정 revision 으로 내려받습니다 (가중치 8.89 GB, 2 shard).
#   3) 두 저장소에 `hf cache verify` 를 실행해 체크섬을 확인합니다. 불일치 시 종료 코드가
#      0 이 아니므로 이 스크립트도 즉시 실패합니다. (FACTS.md 5)
#
# 왜 revision 을 고정하는가 (FACTS.md 6)
#   MMMU/MMMU 의 데이터 파일은 2026-02-12 / 2026-04-21 / 2026-07-10 에 실제로 바뀌었습니다.
#   즉 공개 점수 67.4 가 발표된 이후에 데이터셋이 변경되었습니다. 따라서 "MMMU/MMMU" 라는
#   문자열만으로는 재현 가능한 식별자가 아닙니다. sha 까지 적어야 합니다.
#   "main" 은 가변 브랜치 포인터입니다.
#
# 사용법
#   bash scripts/fetch_data.sh
#
# 환경변수
#   WORKSPACE=/workspace                영구 디스크
#   DATASET_ID / DATASET_REV            기본값은 FACTS.md 4/6 의 고정 sha
#   MODEL_ID / MODEL_REV                기본값은 FACTS.md 6 의 고정 sha
#   VERIFY_SHA256=1                     shard 1 의 sha256 를 FACTS.md 6 값과 직접 대조(수십 초 소요)
#   SKIP_DATASET=1 / SKIP_MODEL=1       한쪽만 다시 받을 때
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

trap 'echo "" >&2; echo "[실패] fetch_data.sh ${BASH_SOURCE[0]}:${LINENO} 에서 중단되었습니다." >&2' ERR

log()  { echo "[fetch] $*"; }
warn() { echo "[경고] $*" >&2; }
die()  { echo "[실패] $*" >&2; exit 1; }
rule() { echo "-----------------------------------------------------------------------"; }

# -----------------------------------------------------------------------------
# HuggingFace 환경변수 — python/hf CLI 가 시작되기 "전"에 export 합니다.
# FACTS.md 5: 모든 HF 환경변수는 import 시점에 읽힙니다. 또한 HF_DATASETS_CACHE 만
# 지정하면 Arrow 캐시만 옮겨지고 내려받은 parquet 은 컨테이너 디스크에 남습니다.
# (setup_pod.sh / run_baseline.sh 와 동일한 블록입니다. 각 스크립트를 독립 실행할 수
#  있어야 하므로 의도적인 중복입니다.)
# -----------------------------------------------------------------------------
WORKSPACE="${WORKSPACE:-/workspace}"
if [[ ! -d "$WORKSPACE" ]]; then
  mkdir -p "$WORKSPACE" 2>/dev/null || die "WORKSPACE 를 만들 수 없습니다: $WORKSPACE (WORKSPACE=... 로 지정 가능)"
fi
export HF_HOME="${HF_HOME:-$WORKSPACE/hf}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$HF_HOME/hub}"
export HF_DATASETS_CACHE="${HF_DATASETS_CACHE:-$HF_HOME/datasets}"
export HF_XET_HIGH_PERFORMANCE=1   # FACTS.md 5: 현재 유효한 전송 가속 스위치(hf-xet 경로)
unset HF_HUB_ENABLE_HF_TRANSFER    # FACTS.md 5: DEPRECATED, 아무 동작도 하지 않습니다.
mkdir -p "$HF_HOME" "$HF_HUB_CACHE" "$HF_DATASETS_CACHE"

DATASET_ID="${DATASET_ID:-MMMU/MMMU}"
DATASET_REV="${DATASET_REV:-98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68}"   # FACTS.md 4/6
MODEL_ID="${MODEL_ID:-Qwen/Qwen3-VL-4B-Instruct}"
MODEL_REV="${MODEL_REV:-ebb281ec70b05090aa6165b016eac8ec08e71b17}"       # FACTS.md 6
SPLIT_GLOB="${SPLIT_GLOB:-*/validation-*.parquet}"                        # FACTS.md 4: 30개 subject 디렉터리의 validation parquet 만

# FACTS.md 6 의 검증된 값 (shard 2 의 sha256 은 원본에서 잘려 있어 대조할 수 없습니다)
SHARD1_NAME="model-00001-of-00002.safetensors"
SHARD1_SHA256="30a01a0556622645a3cce87b655bbbbbc1f170c196099f1b666c93202c3339a9"
SHARD1_BYTES="4967229296"

VENV_DIR="${VENV_DIR:-$WORKSPACE/venv}"
HF_CLI_VENV="${HF_CLI_VENV:-$WORKSPACE/hfcli-venv}"

find_python() {
  local cand
  if [[ -n "${PY_BIN:-}" ]]; then command -v "$PY_BIN" && return 0; fi
  for cand in python3.12 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then command -v "$cand"; return 0; fi
  done
  return 1
}
PY_HELPER="$(find_python)" || die "python3 을 찾을 수 없습니다."

hub_ge_110() {  # $1 = python 실행 파일. huggingface-hub >= 1.1.0 이면 0 을 반환합니다.
  "$1" - <<'PYCHK'
import sys
try:
    import importlib.metadata as md
    v = md.version("huggingface-hub")
except Exception:
    sys.exit(1)
parts = []
for chunk in v.split(".")[:3]:
    digits = "".join(ch for ch in chunk if ch.isdigit())
    parts.append(int(digits) if digits else 0)
while len(parts) < 3:
    parts.append(0)
sys.exit(0 if tuple(parts) >= (1, 1, 0) else 1)
PYCHK
}

# -----------------------------------------------------------------------------
# hf CLI 확보
#   `hf` 는 huggingface_hub v1 의 CLI 이름입니다. 구 `huggingface-cli` 는 1.31.0 에도
#   shim 으로 남아 있지만 DEPRECATED 이므로 쓰지 않습니다. (FACTS.md 5)
#   `hf cache verify` 는 hub >= 1.1.0 에서만 동작합니다. 그런데 Stack A 의 평가용 venv 는
#   transformers 4.57.1 때문에 hub <1.0 에 묶여 있으므로, 다운로드/검증 전용 venv 를
#   따로 씁니다. 두 venv 는 같은 HF_HOME 캐시를 공유합니다.
# -----------------------------------------------------------------------------
HF=""
if [[ -x "$VENV_DIR/bin/hf" ]] && hub_ge_110 "$VENV_DIR/bin/python"; then
  HF="$VENV_DIR/bin/hf"
  log "평가용 venv 의 hf CLI 를 사용합니다 (huggingface-hub >= 1.1.0): $HF"
elif [[ -x "$HF_CLI_VENV/bin/hf" ]] && hub_ge_110 "$HF_CLI_VENV/bin/python"; then
  HF="$HF_CLI_VENV/bin/hf"
  log "다운로드 전용 hf CLI 를 사용합니다: $HF"
else
  log "다운로드 전용 hf CLI venv 를 생성합니다: $HF_CLI_VENV  (huggingface-hub 1.31.0)"
  "$PY_HELPER" -m venv "$HF_CLI_VENV"
  "$HF_CLI_VENV/bin/python" -m pip install --upgrade pip
  "$HF_CLI_VENV/bin/python" -m pip install "huggingface_hub[hf_xet]==1.31.0"
  [[ -x "$HF_CLI_VENV/bin/hf" ]] || die "hf CLI 설치에 실패했습니다."
  HF="$HF_CLI_VENV/bin/hf"
fi
log "hf 버전: $("$HF" version 2>/dev/null || echo '(version 서브커맨드 없음)')"

download_into_var() {  # $1=설명, 나머지=hf download 인자. 스냅샷 경로를 전역 SNAP 에 담습니다.
  local desc="$1"; shift
  local tmp_out
  tmp_out="$(mktemp)"
  log "$desc 다운로드 시작 (이미 받은 파일은 건너뜁니다: 멱등)"
  "$HF" download "$@" | tee "$tmp_out"
  # hf 1.x 는 마지막 줄에 경로만 찍지 않고 "✓ Downloaded / path: <경로>" 형식으로 출력합니다.
  # path: 줄을 우선 취하고, 없으면(구버전) 마지막 줄을 씁니다.
  SNAP="$(grep -E '^[[:space:]]*path:' "$tmp_out" | tail -n 1 | sed -E 's/^[[:space:]]*path:[[:space:]]*//' | tr -d '\r')"
  [[ -n "$SNAP" ]] || SNAP="$(tail -n 1 "$tmp_out" | tr -d '\r')"
  # 파일 경로가 찍히는 경우도 있으므로 snapshots/<rev> 디렉터리까지만 남깁니다.
  SNAP="$(printf '%s' "$SNAP" | sed -E 's#(/snapshots/[0-9a-f]{40}).*#\1#')"
  rm -f "$tmp_out"
  [[ -n "$SNAP" && -d "$SNAP" ]] || die "$desc: hf download 가 스냅샷 경로를 출력하지 않았습니다(받은 값: '${SNAP:-}')."
}

file_size() {  # 플랫폼에 따라 stat 옵션이 다르므로 python 으로 읽습니다.
  "$PY_HELPER" -c 'import os,sys;print(os.path.getsize(os.path.realpath(sys.argv[1])))' "$1"
}
file_sha256() {
  "$PY_HELPER" - "$1" <<'PYSHA'
import hashlib
import os
import sys

path = os.path.realpath(sys.argv[1])
h = hashlib.sha256()
with open(path, "rb") as fh:
    for chunk in iter(lambda: fh.read(16 * 1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PYSHA
}

DATASET_DIR=""
MODEL_DIR=""

# -----------------------------------------------------------------------------
# 1) 데이터셋 — validation parquet 만
# -----------------------------------------------------------------------------
if [[ "${SKIP_DATASET:-0}" == "1" ]]; then
  warn "SKIP_DATASET=1 이므로 데이터셋 다운로드를 건너뜁니다."
else
  rule
  log "[1/3] $DATASET_ID @ $DATASET_REV  (validation parquet 만, 약 341 MB)"
  rule
  # --include 는 반드시 마지막에 둡니다(뒤따르는 값을 모두 패턴으로 먹기 때문입니다).
  # README.md 를 함께 받는 이유: parquet 저장소의 config 목록(YAML)이 README 안에 있어
  # datasets 가 30개 config 를 해석할 때 필요합니다. 크기는 수 KB 입니다.
  download_into_var "데이터셋" \
      "$DATASET_ID" --repo-type dataset --revision "$DATASET_REV" \
      --include "$SPLIT_GLOB" --include "README.md"
  DATASET_DIR="$SNAP"
  log "데이터셋 스냅샷: $DATASET_DIR"
  n_parquet="$(find "$DATASET_DIR" -name 'validation-*.parquet' | wc -l | tr -d ' ')"
  log "받은 validation parquet 파일 수: $n_parquet  (기대값 30 — subject 당 1개, FACTS.md 4)"
  if [[ "$n_parquet" != "30" ]]; then
    die "validation parquet 이 30개가 아닙니다($n_parquet). MMMU 는 subject 당 config 가 1개이고
'all' config 가 없으므로 30개 디렉터리에서 정확히 30개가 나와야 합니다(FACTS.md 4).
패턴('$SPLIT_GLOB') 또는 revision 을 확인하십시오."
  fi
fi

# -----------------------------------------------------------------------------
# 2) 모델 — 고정 revision 전체
# -----------------------------------------------------------------------------
if [[ "${SKIP_MODEL:-0}" == "1" ]]; then
  warn "SKIP_MODEL=1 이므로 모델 다운로드를 건너뜁니다."
else
  rule
  log "[2/3] $MODEL_ID @ $MODEL_REV  (BF16 가중치 8.89 GB, 2 shard)"
  rule
  download_into_var "모델" "$MODEL_ID" --revision "$MODEL_REV"
  MODEL_DIR="$SNAP"
  log "모델 스냅샷: $MODEL_DIR"

  # shard 1 의 바이트 크기는 FACTS.md 6 에 검증된 값이 있으므로 항상 대조합니다(비용 0).
  if [[ -e "$MODEL_DIR/$SHARD1_NAME" ]]; then
    got_bytes="$(file_size "$MODEL_DIR/$SHARD1_NAME")"
    if [[ "$got_bytes" == "$SHARD1_BYTES" ]]; then
      log "[OK] $SHARD1_NAME 크기 $got_bytes B = FACTS.md 6 기록과 일치"
    else
      die "$SHARD1_NAME 크기가 다릅니다. 기대 $SHARD1_BYTES B, 실제 $got_bytes B.
revision 이 다른지, 다운로드가 중단되었는지 확인하십시오."
    fi
    if [[ "${VERIFY_SHA256:-0}" == "1" ]]; then
      log "VERIFY_SHA256=1: $SHARD1_NAME 의 sha256 을 직접 계산합니다(4.9 GB, 수십 초 소요)"
      got_sha="$(file_sha256 "$MODEL_DIR/$SHARD1_NAME")"
      if [[ "$got_sha" == "$SHARD1_SHA256" ]]; then
        log "[OK] sha256 $got_sha = FACTS.md 6 기록과 일치"
      else
        die "sha256 불일치! 기대 $SHARD1_SHA256 / 실제 $got_sha"
      fi
      warn "shard 2 의 sha256 은 FACTS.md 6 에서 값이 잘려 기록되어 있어 직접 대조할 수 없습니다."
      warn "shard 2 는 아래 'hf cache verify' 가 저장소 메타데이터 기준으로 검증합니다."
    fi
  else
    warn "$SHARD1_NAME 을 찾지 못했습니다. 파일 구성이 예상과 다릅니다. 아래 검증 결과를 확인하십시오."
  fi
fi

# -----------------------------------------------------------------------------
# 3) 체크섬 검증 — `hf cache verify` (FACTS.md 5)
# -----------------------------------------------------------------------------
rule
log "[3/3] hf cache verify 로 체크섬 검증 (불일치 시 종료 코드 != 0)"
rule
if [[ -n "$DATASET_DIR" ]]; then
  # --fail-on-missing-files 를 "일부러" 쓰지 않습니다. validation parquet 만 받은
  # 의도적인 부분 다운로드이므로, 없는 파일을 실패로 처리하면 항상 실패합니다.
  log "데이터셋 검증 (부분 다운로드이므로 --fail-on-missing-files 는 사용하지 않습니다)"
  "$HF" cache verify "$DATASET_ID" --repo-type dataset --revision "$DATASET_REV"
  log "[OK] 데이터셋 체크섬 검증 통과"
fi
if [[ -n "$MODEL_DIR" ]]; then
  # 모델은 전체를 받았으므로 누락 파일도 실패로 처리합니다.
  log "모델 검증 (--fail-on-missing-files: 전체를 받았으므로 누락은 오류입니다)"
  "$HF" cache verify "$MODEL_ID" --revision "$MODEL_REV" --fail-on-missing-files
  log "[OK] 모델 체크섬 검증 통과"
fi

rule
log "캐시 사용량"
du -shL "$HF_HUB_CACHE" 2>/dev/null || true
[[ -n "$DATASET_DIR" ]] && { du -shL "$DATASET_DIR" 2>/dev/null || true; }
[[ -n "$MODEL_DIR" ]]   && { du -shL "$MODEL_DIR"   2>/dev/null || true; }
log "참고: 전체 MMMU 저장소는 3.66 GB / 92 parquet 입니다. validation 만 받아 ~3.3 GB 를 절약했습니다(FACTS.md 4)."
rule

echo ""
echo "완료했습니다. 다음 단계에서 쓸 경로:"
[[ -n "$DATASET_DIR" ]] && echo "  데이터셋 : $DATASET_DIR"
[[ -n "$MODEL_DIR" ]]   && echo "  모델     : $MODEL_DIR"
echo ""
echo "src/eval_mmmu.py 의 --data-path 에는 둘 중 어느 쪽이든 넣을 수 있습니다."
echo "  (a) HF 저장소 id:  --data-path $DATASET_ID        <- 캐시에서 해결됩니다(기본 권장)"
echo "  (b) 로컬 경로   :  --data-path '$DATASET_DIR'"
echo "run_baseline.sh 는 기본적으로 (a) 를 사용하며 revision 을 함께 고정합니다."
echo ""
echo "다음: GPU_HOURLY_USD=0.34 bash scripts/run_baseline.sh"
