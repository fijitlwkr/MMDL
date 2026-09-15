#!/usr/bin/env bash
# =============================================================================
# scripts/setup_pod.sh — RunPod 파드 1회 부트스트랩 (멱등: 몇 번 실행해도 안전)
#
# 하는 일 (순서가 곧 정확성입니다)
#   0) HF_HOME / HF_HUB_CACHE 를 /workspace 로 export  <-- python 이 시작되기 "전"에
#   1) Python 3.12 확인 및 venv 생성
#   2) torch 3종을 cu128 인덱스에서 "가장 먼저" 설치
#   3) 나머지 라이브러리를 requirements.lock.txt 제약 아래 설치
#   4) vLLM 을 "가장 마지막"에 설치
#   5) 다운로드 전용 hf CLI venv 생성 (hub 1.x 필요)
#   6) preflight: transformers >= 4.57.0 단언 + model_type / patch_size /
#      spatial_merge_size 를 눈으로 확인 (16 / 2 = 32 배수 증거)
#
# 사용법
#   bash scripts/setup_pod.sh                  # 전체 부트스트랩
#   bash scripts/setup_pod.sh --preflight-only # 설치 건너뛰고 점검만 (run_baseline.sh 가 호출)
#
# 환경변수로 조절 가능
#   WORKSPACE=/workspace          영구 디스크 경로
#   VENV_DIR=$WORKSPACE/venv      평가용 venv 경로
#   HF_CLI_VENV=$WORKSPACE/hfcli-venv   다운로드 전용 venv 경로
#   FORCE_REINSTALL=1             스택 재설치 강제
#   ALLOW_PYTHON_MISMATCH=1       Python 3.12 가 아니어도 진행 (비권장)
#   ALLOW_NO_GPU=1                GPU 가 안 보여도 진행 (CPU 에서 구조만 점검할 때)
#   SKIP_MODEL_CONFIG_CHECK=1     네트워크가 없을 때 config 점검만 건너뜀 (비권장)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

trap 'echo "" >&2; echo "[실패] setup_pod.sh ${BASH_SOURCE[0]}:${LINENO} 에서 중단되었습니다. 위의 마지막 메시지를 읽어 주십시오." >&2' ERR

log()  { echo "[setup] $*"; }
warn() { echo "[경고] $*" >&2; }
die()  { echo "[실패] $*" >&2; exit 1; }
rule() { echo "-----------------------------------------------------------------------"; }

PREFLIGHT_ONLY=0
for arg in "${@:-}"; do
  case "$arg" in
    "")                 ;;
    --preflight-only)   PREFLIGHT_ONLY=1 ;;
    -h|--help)          sed -n '2,30p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)                  die "알 수 없는 인자입니다: $arg  (--preflight-only 또는 --help 만 받습니다)" ;;
  esac
done

# -----------------------------------------------------------------------------
# 0) HuggingFace 환경변수 — python 이 시작되기 전에 export 해야 합니다.
#    FACTS.md 5: 모든 HF 환경변수는 "import 시점"에 읽힙니다. 파이썬 코드 안에서
#    os.environ 에 넣어도 이미 늦습니다. 또한 HF_DATASETS_CACHE 만 바꾸면 Arrow 캐시만
#    이동하고 "내려받은 parquet" 은 여전히 ~/.cache 에 쌓여 컨테이너 디스크를 채웁니다.
#    그래서 HF_HOME 과 HF_HUB_CACHE 를 둘 다 /workspace 로 지정합니다.
#    (이 블록은 fetch_data.sh / run_baseline.sh 에도 같은 내용으로 들어 있습니다.
#     세 스크립트를 각각 독립 실행할 수 있어야 하므로 의도적인 중복입니다.)
# -----------------------------------------------------------------------------
WORKSPACE="${WORKSPACE:-/workspace}"
if [[ ! -d "$WORKSPACE" ]]; then
  mkdir -p "$WORKSPACE" 2>/dev/null || die "WORKSPACE 경로를 만들 수 없습니다: $WORKSPACE
RunPod 파드가 아니라면 WORKSPACE=\$HOME/mmdl-workspace 처럼 직접 지정해 주십시오."
fi
export HF_HOME="${HF_HOME:-$WORKSPACE/hf}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$HF_HOME/hub}"
export HF_DATASETS_CACHE="${HF_DATASETS_CACHE:-$HF_HOME/datasets}"
export HF_XET_HIGH_PERFORMANCE=1   # FACTS.md 5: 전송은 hf-xet 경로를 탑니다. 이것이 현재 유효한 가속 스위치입니다.
unset HF_HUB_ENABLE_HF_TRANSFER    # FACTS.md 5: 이 변수는 DEPRECATED 이고 아무 동작도 하지 않습니다. 혹시 상위 환경에 설정되어 있으면 제거합니다.
export TOKENIZERS_PARALLELISM=false # 멀티프로세스 경고 스팸을 막기 위함(성능 영향 없음).
mkdir -p "$HF_HOME" "$HF_HUB_CACHE" "$HF_DATASETS_CACHE"

MODEL_ID="${MODEL_ID:-Qwen/Qwen3-VL-4B-Instruct}"
MODEL_REV="${MODEL_REV:-ebb281ec70b05090aa6165b016eac8ec08e71b17}"  # FACTS.md 6: main 은 가변 포인터이므로 sha 로 고정합니다.

VENV_DIR="${VENV_DIR:-$WORKSPACE/venv}"
HF_CLI_VENV="${HF_CLI_VENV:-$WORKSPACE/hfcli-venv}"
LOCK_FILE="$REPO_ROOT/requirements.lock.txt"

rule
log "저장소   : $REPO_ROOT"
log "WORKSPACE: $WORKSPACE"
log "HF_HOME  : $HF_HOME"
log "venv     : $VENV_DIR"
rule

# -----------------------------------------------------------------------------
# 공통 유틸
# -----------------------------------------------------------------------------
py_sha256() {  # 외부 도구(sha256sum/shasum) 유무에 의존하지 않도록 python 으로 계산합니다.
  "$1" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$2"
}

find_python() {
  local cand
  if [[ -n "${PY_BIN:-}" ]]; then command -v "$PY_BIN" && return 0; fi
  for cand in python3.12 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then command -v "$cand"; return 0; fi
  done
  return 1
}

# -----------------------------------------------------------------------------
# 1) Python 3.12 + venv
# -----------------------------------------------------------------------------
ensure_venv() {
  local py_bin py_ver
  py_bin="$(find_python)" || die "python3 을 찾을 수 없습니다. 파드 이미지에 Python 3.12 가 있어야 합니다."
  py_ver="$("$py_bin" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
  log "시스템 python: $py_bin (버전 $py_ver)"
  if [[ "$py_ver" != "3.12" ]]; then
    if [[ "${ALLOW_PYTHON_MISMATCH:-0}" == "1" ]]; then
      warn "Python $py_ver 입니다. FACTS.md 5 의 기준은 3.12 입니다. ALLOW_PYTHON_MISMATCH=1 이므로 진행합니다."
      warn "vllm 0.11.0 / torch 2.8.0 휠이 이 버전용으로 없을 수 있습니다. 설치가 실패하면 3.12 로 돌아오십시오."
    else
      die "Python $py_ver 이 감지되었습니다. 이 스택은 Python 3.12 기준입니다(FACTS.md 5).
다른 인터프리터를 쓰려면 PY_BIN=/usr/bin/python3.12 로 지정하거나,
정말 강행하려면 ALLOW_PYTHON_MISMATCH=1 을 주십시오(권장하지 않습니다)."
    fi
  fi

  if [[ -x "$VENV_DIR/bin/python" ]]; then
    log "venv 가 이미 있습니다: $VENV_DIR  (재사용)"
  else
    log "venv 를 생성합니다: $VENV_DIR"
    "$py_bin" -m venv "$VENV_DIR"
  fi
}

# -----------------------------------------------------------------------------
# 2)~4) 스택 설치 — 순서가 생명입니다 (requirements.lock.txt 헤더 참조)
# -----------------------------------------------------------------------------
install_stack() {
  local vpy="$VENV_DIR/bin/python"
  local stamp="$VENV_DIR/.mmdl_stack_stamp"
  local want_hash cur_hash
  [[ -f "$LOCK_FILE" ]] || die "requirements.lock.txt 가 없습니다: $LOCK_FILE"
  want_hash="$(py_sha256 "$vpy" "$LOCK_FILE")"

  if [[ -f "$stamp" && "${FORCE_REINSTALL:-0}" != "1" ]]; then
    cur_hash="$(cat "$stamp")"
    if [[ "$cur_hash" == "$want_hash" ]]; then
      log "스택이 이미 설치되어 있고 requirements.lock.txt 도 변경되지 않았습니다. 설치를 건너뜁니다."
      log "(강제로 다시 설치하려면 FORCE_REINSTALL=1 bash scripts/setup_pod.sh)"
      return 0
    fi
    warn "requirements.lock.txt 가 바뀌었습니다(해시 불일치). 스택을 다시 설치합니다."
  fi

  # pip 자체 업그레이드는 "스택 설치 전"에만 수행합니다. 스택 설치 후의 -U 는 금지입니다.
  log "[1/4] pip / setuptools / wheel 업그레이드 (스택 설치 전에만 수행)"
  "$vpy" -m pip install --upgrade pip setuptools wheel

  # torch 3종을 가장 먼저, cu128 전용 인덱스에서. PyPI 기본 휠은 다른 CUDA 빌드입니다.
  log "[2/4] torch 2.8.0 / torchvision 0.23.0 / torchaudio 2.8.0  (cu128 인덱스, 반드시 최초)"
  "$vpy" -m pip install \
      --index-url https://download.pytorch.org/whl/cu128 \
      -c "$LOCK_FILE" \
      torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0

  # 나머지 런타임. -c 로 lock 을 제약으로 걸어 전이 의존성이 핀을 넘지 못하게 합니다.
  log "[3/4] transformers / tokenizers / huggingface-hub / accelerate / safetensors / datasets / pillow"
  "$vpy" -m pip install -c "$LOCK_FILE" \
      transformers==4.57.1 \
      tokenizers==0.22.2 \
      huggingface-hub==0.35.3 \
      accelerate==1.11.0 \
      safetensors==0.6.2 \
      datasets==4.0.0 \
      pillow==11.3.0

  # vLLM 은 가장 마지막. -c 가 없으면 pip 가 transformers 를 5.x 로 끌어올려 Stack A 를 깨뜨립니다.
  log "[4/4] vllm 0.11.0  (반드시 마지막, -c 로 transformers 4.57.1 을 붙잡은 상태에서)"
  "$vpy" -m pip install -c "$LOCK_FILE" vllm==0.11.0

  # 의존성 정합성 점검. 여기서 경고가 나오면 위 순서가 깨졌을 가능성이 큽니다.
  if "$vpy" -m pip check; then
    log "pip check: 의존성 충돌 없음"
  else
    warn "pip check 가 충돌을 보고했습니다. 위 출력을 확인하십시오."
    warn "대개 원인은 (a) 설치 순서가 깨짐 (b) 누군가 pip install -U 를 실행함 입니다."
    warn "가장 빠른 복구: rm -rf '$VENV_DIR' 후 FORCE_REINSTALL=1 로 이 스크립트를 다시 실행."
  fi

  echo "$want_hash" > "$stamp"
  log "스택 설치 완료. 스탬프 기록: $stamp"
  warn "이 venv 안에서 'pip install -U' / '--upgrade' 는 이제부터 금지입니다(FACTS.md 5)."
}

# -----------------------------------------------------------------------------
# 5) 다운로드 전용 hf CLI venv
#    왜 별도 venv 인가: `hf` CLI 와 `hf cache verify` 는 huggingface_hub >= 1.1.0 에만
#    있습니다. 그런데 Stack A 의 transformers 4.57.1 은 hub <1.0 을 요구합니다(FACTS.md 5).
#    평가용 venv 에 hub 1.x 를 넣을 수 없으므로, 다운로드/검증 전용 venv 를 따로 둡니다.
#    두 venv 는 같은 HF_HOME 캐시를 공유하므로 파일은 한 번만 내려받습니다.
# -----------------------------------------------------------------------------
ensure_hf_cli() {
  local vpy="$VENV_DIR/bin/python"
  # 이미 평가용 venv 의 hub 가 1.1.0 이상이면(=Stack B 를 쓰는 경우) 그걸 그대로 씁니다.
  if [[ -x "$VENV_DIR/bin/hf" ]] && "$vpy" - <<'PYCHK'
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
  then
    log "평가용 venv 의 huggingface-hub 가 1.1.0 이상입니다. 별도 CLI venv 없이 $VENV_DIR/bin/hf 를 사용합니다."
    return 0
  fi

  if [[ -x "$HF_CLI_VENV/bin/hf" ]]; then
    log "다운로드 전용 hf CLI venv 가 이미 있습니다: $HF_CLI_VENV  (재사용)"
    return 0
  fi

  local py_bin
  py_bin="$(find_python)" || die "python3 을 찾을 수 없습니다."
  log "다운로드 전용 hf CLI venv 를 생성합니다: $HF_CLI_VENV  (huggingface-hub 1.31.0)"
  "$py_bin" -m venv "$HF_CLI_VENV"
  "$HF_CLI_VENV/bin/python" -m pip install --upgrade pip
  # hf-xet 엑스트라: HF_XET_HIGH_PERFORMANCE=1 이 실제 효과를 내는 전송 백엔드입니다.
  "$HF_CLI_VENV/bin/python" -m pip install "huggingface_hub[hf_xet]==1.31.0"
  [[ -x "$HF_CLI_VENV/bin/hf" ]] || die "hf CLI 가 설치되지 않았습니다. huggingface_hub 1.31.0 설치 로그를 확인하십시오."
  log "hf CLI 준비 완료: $HF_CLI_VENV/bin/hf"
}

# -----------------------------------------------------------------------------
# 6) preflight — 학생이 자기 눈으로 16 / 2 / 32 를 확인하는 단계
# -----------------------------------------------------------------------------
preflight() {
  local vpy="$VENV_DIR/bin/python"
  [[ -x "$vpy" ]] || die "venv 가 없습니다: $VENV_DIR
먼저 'bash scripts/setup_pod.sh' 를 --preflight-only 없이 실행하십시오."
  rule
  log "preflight 시작"
  rule
  MODEL_ID="$MODEL_ID" MODEL_REV="$MODEL_REV" \
  SKIP_MODEL_CONFIG_CHECK="${SKIP_MODEL_CONFIG_CHECK:-0}" \
  ALLOW_NO_GPU="${ALLOW_NO_GPU:-0}" \
  "$vpy" - <<'PYPRE'
# -*- coding: utf-8 -*-
"""preflight: 스택과 모델 설정이 FACTS.md 와 일치하는지 단언합니다."""
import importlib.metadata as md
import os
import sys

FAIL = []


def ver(pkg):
    try:
        return md.version(pkg)
    except Exception:
        return None


def vtuple(v):
    """'4.57.1' -> (4,57,1). rc/dev 접미사는 숫자만 취합니다."""
    out = []
    for chunk in str(v).split(".")[:3]:
        digits = "".join(ch for ch in chunk if ch.isdigit())
        out.append(int(digits) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


print("=== [1] 파이썬 / 패키지 버전 ===")
print(f"python                : {sys.version.split()[0]}  (기준 3.12)")
PKGS = ["torch", "torchvision", "torchaudio", "transformers", "tokenizers",
        "huggingface-hub", "accelerate", "safetensors", "datasets", "pillow",
        "vllm", "numpy", "qwen-vl-utils", "flash-attn"]
for p in PKGS:
    print(f"{p:<22}: {ver(p)}")

# --- transformers >= 4.57.0 단언 (FACTS.md 5) --------------------------------
tv = ver("transformers")
if tv is None:
    FAIL.append("transformers 가 설치되지 않았습니다.")
elif vtuple(tv) < (4, 57, 0):
    FAIL.append(
        f"transformers {tv} 는 Qwen3-VL 을 지원하지 않습니다. "
        "최소 4.57.0 (2025-10-03, PR #40795) 이 필요합니다. (FACTS.md 5)"
    )
else:
    print(f"\n[OK] transformers {tv} >= 4.57.0  -> Qwen3-VL 지원 릴리스입니다. (FACTS.md 5)")

# --- flash-attn 설치 여부 경고 (FACTS.md 5) ---------------------------------
if ver("flash-attn") is not None:
    print("[경고] flash-attn 이 설치되어 있습니다. 이 과제에는 불필요하며 sdist 컴파일로 "
          "30~60분을 낭비합니다. attn_implementation=\"sdpa\" 로 충분합니다. (FACTS.md 5)")

# --- torch / CUDA 3종 구분 (FACTS.md 9) -------------------------------------
print("\n=== [2] CUDA 버전 3종 (학생들이 가장 많이 혼동하는 지점) ===")
try:
    import torch
    print(f"torch.__version__        : {torch.__version__}")
    print(f"torch.version.cuda       : {torch.version.cuda}   <- 실제로 중요한 값(휠이 빌드된 CUDA)")
    avail = torch.cuda.is_available()
    print(f"torch.cuda.is_available(): {avail}")
    if avail:
        n = torch.cuda.device_count()
        for i in range(n):
            props = torch.cuda.get_device_properties(i)
            vram_mib = int(props.total_memory // (1024 * 1024))
            print(f"  GPU{i}: {props.name}  VRAM {vram_mib} MiB  sm_{props.major}{props.minor}")
    else:
        msg = ("GPU 를 찾을 수 없습니다(torch.cuda.is_available() == False). "
               "RunPod GPU 파드인지 확인하십시오. CPU 에서 구조만 점검하려면 ALLOW_NO_GPU=1 을 주십시오.")
        if os.environ.get("ALLOW_NO_GPU") == "1":
            print(f"[경고] {msg}")
        else:
            FAIL.append(msg)
except Exception as exc:  # noqa: BLE001
    FAIL.append(f"torch import 실패: {exc!r}")

print("""
  해설 (FACTS.md 9):
   - nvidia-smi 헤더의 CUDA  = 드라이버가 지원하는 '최대' 런타임 버전입니다.
   - nvcc --version          = 로컬 툴킷. 보통 설치조차 안 되어 있고, 미리 빌드된 휠과 무관합니다.
   - torch.version.cuda      = 실제로 중요한 값. 휠이 어떤 CUDA 로 빌드되었는지입니다.
   예) nvidia-smi 가 13.0 인데 torch.version.cuda 가 12.9 인 것은 정상이며 손댈 필요 없습니다.
       CUDA 12.x 는 드라이버 >= 525, 13.x 는 >= 580 이 필요합니다.""")

# --- 모델 설정: 32 배수의 증거 (FACTS.md 1) ---------------------------------
print("\n=== [3] 모델 설정 — 32 배수(patch_size 16 x spatial_merge_size 2) 증거 ===")
if os.environ.get("SKIP_MODEL_CONFIG_CHECK") == "1":
    print("[경고] SKIP_MODEL_CONFIG_CHECK=1 이므로 모델 config 점검을 건너뜁니다. "
          "보고서를 쓰기 전에 반드시 한 번은 직접 확인하십시오.")
else:
    repo = os.environ["MODEL_ID"]
    rev = os.environ["MODEL_REV"]
    try:
        from transformers import AutoConfig
        cfg = AutoConfig.from_pretrained(repo, revision=rev)
    except Exception as exc:  # noqa: BLE001
        FAIL.append(
            f"모델 config 를 읽지 못했습니다: {exc!r}\n"
            f"  - 네트워크가 막혀 있으면 먼저 'bash scripts/fetch_data.sh' 로 캐시를 채우십시오.\n"
            f"  - 비공개 저장소 토큰이 필요하면 HF_TOKEN 을 export 하십시오.\n"
            f"  - 점검만 건너뛰려면 SKIP_MODEL_CONFIG_CHECK=1 (권장하지 않습니다)."
        )
        cfg = None
    if cfg is not None:
        vc = getattr(cfg, "vision_config", None)
        if vc is None:
            FAIL.append("config 에 vision_config 가 없습니다. 모델 revision 이 잘못되었을 수 있습니다.")
        else:
            def g(key):
                if isinstance(vc, dict):
                    return vc.get(key)
                return getattr(vc, key, None)

            model_type = getattr(cfg, "model_type", None)
            patch = g("patch_size")
            merge = g("spatial_merge_size")
            print(f"repo / revision        : {repo} @ {rev}")
            print(f"config.model_type      : {model_type}          (기대값 qwen3_vl)")
            print(f"vision_config.patch_size        : {patch}   (기대값 16)")
            print(f"vision_config.spatial_merge_size: {merge}   (기대값 2)")
            if model_type != "qwen3_vl":
                FAIL.append(f"model_type 이 {model_type!r} 입니다. 기대값은 'qwen3_vl' 입니다. (FACTS.md 5)")
            if patch != 16:
                FAIL.append(f"patch_size 가 {patch} 입니다. 기대값은 16 입니다. (FACTS.md 1)")
            if merge != 2:
                FAIL.append(f"spatial_merge_size 가 {merge} 입니다. 기대값은 2 입니다. (FACTS.md 1)")
            if patch and merge:
                factor = int(patch) * int(merge)
                px_per_token = factor * factor
                print(f"\n  => smart_resize 배수 = patch_size x spatial_merge_size = {patch} x {merge} = {factor}")
                print(f"  => 비전 토큰 1개가 덮는 픽셀 = {factor}x{factor} = {px_per_token} px")
                print(f"     (Qwen2/2.5-VL 은 14x2 = 28 배수, 784 px/token 이었습니다. 28 이 아닙니다!)")
                minp = 1280 * 28 * 28
                maxp = 5120 * 28 * 28
                print(f"\n  교수님 슬라이드 값을 이 모델 기준으로 환산하면 (FACTS.md 1):")
                print(f"     min_pixels = 1280*28*28 = {minp:,} px -> 하한 {minp // px_per_token:,} 비전 토큰 (1280 이 아닙니다)")
                print(f"     max_pixels = 5120*28*28 = {maxp:,} px -> 상한 {maxp // px_per_token:,} 비전 토큰 (5120 이 아닙니다)")
                print("     '* 28 * 28' 은 Qwen2.5-VL 관례이며, Qwen3-VL 에서는 토큰 수를 뜻하지 않습니다.")

print("\n=== [4] vLLM ===")
vv = ver("vllm")
if vv is None:
    print("[경고] vllm 이 설치되지 않았습니다. --backend hf 로만 실행할 수 있고, 900문항에 2~6시간이 걸립니다. (FACTS.md 13)")
elif vtuple(vv) < (0, 11, 0):
    FAIL.append(f"vllm {vv} 에는 Qwen3VLForConditionalGeneration 이 없습니다. 최소 0.11.0 이 필요합니다. (FACTS.md 5)")
else:
    print(f"[OK] vllm {vv} >= 0.11.0  -> Qwen3VLForConditionalGeneration 이 registry 에 등록된 릴리스입니다.")
    print("     trust_remote_code 는 필요하지 않습니다(아키텍처가 네이티브 등록되어 있습니다).")

print()
if FAIL:
    print("=== preflight 실패 ===")
    for i, f in enumerate(FAIL, 1):
        print(f"  ({i}) {f}")
    sys.exit(1)
print("=== preflight 통과: 이 환경으로 측정해도 좋습니다. ===")
PYPRE
  rule
}

# -----------------------------------------------------------------------------
# main
# -----------------------------------------------------------------------------
if [[ "$PREFLIGHT_ONLY" == "1" ]]; then
  log "--preflight-only: 설치 단계를 건너뛰고 점검만 수행합니다."
  preflight
  exit 0
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  log "nvidia-smi 요약 (드라이버가 지원하는 최대 CUDA 런타임 버전입니다. FACTS.md 9)"
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv || true
else
  warn "nvidia-smi 가 없습니다. GPU 파드가 맞는지 확인하십시오."
fi

ensure_venv
install_stack
ensure_hf_cli
preflight

rule
log "부트스트랩 완료."
echo ""
echo "다음 단계:"
echo "  1) 데이터/모델 내려받기 :  bash scripts/fetch_data.sh"
echo "  2) 베이스라인 측정      :  GPU_HOURLY_USD=0.34 bash scripts/run_baseline.sh"
echo ""
echo "대화형 셸에서 직접 python 을 쓸 때는 아래 4줄을 먼저 붙여넣으십시오."
echo "(HF 환경변수는 import 시점에 읽히므로 python 실행 '전'에 export 해야 합니다. FACTS.md 5)"
echo ""
echo "  export HF_HOME=\"$HF_HOME\""
echo "  export HF_HUB_CACHE=\"$HF_HUB_CACHE\""
echo "  export HF_XET_HIGH_PERFORMANCE=1"
echo "  source \"$VENV_DIR/bin/activate\""
echo ""
warn "RunPod 은 GPU 사용률과 무관하게 파드 시작부터 종료까지 초 단위로 과금합니다(FACTS.md 8)."
warn "작업이 끝나면 파드를 반드시 terminate 하십시오. stop 상태에서도 볼륨 디스크 요금(\$0.20/GB/월)이 계속 나갑니다."
rule
