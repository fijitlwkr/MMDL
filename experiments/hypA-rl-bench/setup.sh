#!/usr/bin/env bash
# 가설 A RL 사전 테스트 1단계: 환경 설치·확인 + bench64 데이터 준비 + 모델 내려받기. 파드에서 한 번만 돌린다.
#   1. 팀 고정 버전(code/requirements.txt: vllm 0.11.0 / torch 2.8.0 / transformers 4.57.1 …) 설치
#   2. ms-swift 4.6.0 + trl 0.29.1 설치. 1번에서 깔린 버전을 바꾸지 못하게 pip freeze 를 제약(-c)으로 건다.
#      trl 은 swift GRPO 가 0.26 이상을 요구하고, swift 4.6.0 README 권장값이 0.29.1 이다.
#   3. pip check(swift 설치 전·후) + import 확인. 결과는 $OUT/setup/ 에 전문으로 남긴다.
#      swift 설치·import 실패, 또는 swift 설치 후 pip check 에 새 문제가 생기면 테스트 B 는 '불가'로 기록한다.
#   4. bench64(HF 비공개 데이터셋)를 받아 SHA256SUMS 로 검사하고 $OUT/bench64 에 푼다.
#   5. 모델을 config 의 고정 revision 으로 미리 받아 둔다(테스트 A·B 가 같은 경로를 쓴다).
#
#   bash experiments/hypA-rl-bench/setup.sh            # 결과: $OUT/setup/STATUS (A=ok|fail, B=ok|불가)
# HF 비공개 데이터셋을 받으므로 먼저 HF_HOME=$HF_HOME huggingface-cli login 이 필요하다.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${OUT:-/workspace/hypA_rl_bench}"
export HF_HOME="${HF_HOME:-/workspace/.cache/huggingface}"
BENCH_REPO="${BENCH_REPO:-MMDL-team4/hypA-rl-bench64}"
BENCH_REV="${BENCH_REV:-0a9240ad1f48a9e5c712338bb0b3e1180c9d25c8}"  # 하경님이 올린 버전 (2026-11-08 확인)
SWIFT_PKGS=(ms-swift==4.6.0 trl==0.29.1)
S="$OUT/setup"; mkdir -p "$S" "$HF_HOME"; cd "$REPO"
status() { echo "$1" >> "$S/STATUS"; echo "[STATUS] $1"; }
: > "$S/STATUS"

echo "=== 1. 팀 고정 버전 설치 ==="
python -m pip install -r code/requirements.txt 2>&1 | tee "$S/01_install_team.log"
if (( PIPESTATUS[0] != 0 )); then status "A=fail (팀 패키지 설치 실패, 01_install_team.log)"; status "B=불가"; exit 3; fi
python -c 'import hf_transfer' >/dev/null 2>&1 && export HF_HUB_ENABLE_HF_TRANSFER=1
python -m pip check > "$S/02_pip_check_before_swift.log" 2>&1
python -m pip freeze | grep -v -E '^(-e |.* @ )' > "$S/constraints.txt"

echo "=== 2. ms-swift 설치 (${SWIFT_PKGS[*]}) ==="
python -m pip install "${SWIFT_PKGS[@]}" -c "$S/constraints.txt" 2>&1 | tee "$S/03_install_swift.log"
SWIFT_INSTALL=${PIPESTATUS[0]}
python -m pip check > "$S/04_pip_check_after_swift.log" 2>&1
python -m pip freeze > "$S/pip_freeze.txt"
# swift 설치 전에는 없던 pip check 문제만 골라낸다
NEW_CONFLICTS="$(grep -v -x -F -f "$S/02_pip_check_before_swift.log" "$S/04_pip_check_after_swift.log" | grep -v '^No broken requirements found' || true)"
echo "$NEW_CONFLICTS" > "$S/05_pip_check_new_after_swift.log"

echo "=== 3. import 확인 ==="
python - "$S/06_imports.json" <<'PY' 2>&1 | tee "$S/06_imports.log"
import importlib.metadata, json, sys, traceback
out = {}
def check(name, stmt):
    try:
        exec(stmt, {})
        out[name] = "ok"
    except BaseException:
        out[name] = traceback.format_exc()
    print(f"{name}: {'ok' if out[name] == 'ok' else 'FAIL'}")
for mod in ["torch", "vllm", "transformers", "tokenizers", "qwen_vl_utils", "swift", "trl", "peft", "accelerate", "datasets"]:
    check(f"import {mod}", f"import {mod}")
check("torch.cuda", "import torch; assert torch.cuda.is_available(), 'CUDA not available'")
check("vllm.LLM", "from vllm import LLM, SamplingParams")
check("swift GRPO", "from swift.rlhf_trainers import GRPOConfig, GRPOTrainer")
check("swift ORM", "from swift.rewards import ORM, orms")
versions = {}
for dist in ["torch", "vllm", "transformers", "tokenizers", "qwen-vl-utils", "ms-swift", "trl", "peft", "accelerate",
             "datasets", "huggingface-hub", "deepspeed", "flash-attn"]:
    try:
        versions[dist] = importlib.metadata.version(dist)
    except Exception:
        versions[dist] = None
try:
    import torch
    versions["cuda"] = torch.version.cuda
    versions["gpu"] = torch.cuda.get_device_name(0)
    versions["gpu_total_gib"] = round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1)
except Exception:
    pass
print(json.dumps(versions, indent=1))
json.dump({"imports": out, "versions": versions}, open(sys.argv[1], "w"), indent=1)
PY
nvidia-smi > "$S/nvidia_smi.txt" 2>&1

TEAM_IMPORTS_OK=$(python -c "import json,sys; d=json.load(open(sys.argv[1]))['imports']; print(int(all(d[k]=='ok' for k in ['import torch','import vllm','import transformers','import qwen_vl_utils','torch.cuda','vllm.LLM'])))" "$S/06_imports.json")
SWIFT_IMPORTS_OK=$(python -c "import json,sys; d=json.load(open(sys.argv[1]))['imports']; print(int(all(d[k]=='ok' for k in ['import swift','import trl','import peft','swift GRPO','swift ORM'])))" "$S/06_imports.json")

echo "=== 4. bench64 받기·검사 ==="
python - "$BENCH_REPO" "$BENCH_REV" "$OUT" <<'PY' 2>&1 | tee "$S/07_bench64.log"
import hashlib, sys, tarfile
from pathlib import Path
from huggingface_hub import snapshot_download
repo, rev, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
src = Path(snapshot_download(repo, repo_type="dataset", revision=rev, local_dir=out / "bench64_download"))
sums = dict(reversed(line.split(maxsplit=1)) for line in (src / "SHA256SUMS").read_text().splitlines() if line.strip())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(src / "bench64.tar.gz") == sums.pop("bench64.tar.gz"), "bench64.tar.gz checksum mismatch"
dest = out / "bench64"; dest.mkdir(parents=True, exist_ok=True)
with tarfile.open(src / "bench64.tar.gz") as tar:
    for m in tar.getmembers():
        assert not m.name.startswith("/") and ".." not in Path(m.name).parts, f"unsafe path {m.name}"
    tar.extractall(dest)
bad = [name for name, h in sums.items() if not (dest / name).is_file() or sha(dest / name) != h]
assert not bad, f"checksum mismatch: {bad}"
rows = (dest / "bench64.jsonl").read_text(encoding="utf-8").splitlines()
print(f"OK {len(sums)} files verified, {len(rows)} rows -> {dest}")
PY
BENCH_OK=$(( PIPESTATUS[0] == 0 ))

echo "=== 5. 모델 받기 (config 의 고정 revision) ==="
python - "$REPO/code" "$REPO/code/config.yaml" "$S/model_dir.txt" <<'PY' 2>&1 | tee "$S/08_model.log"
import sys, yaml
sys.path.insert(0, sys.argv[1])
from inputs import resolve_model_dir
cfg = yaml.safe_load(open(sys.argv[2]))
path = resolve_model_dir(cfg["model"]["repo_id"], cfg["model"]["revision"], weights=True)
open(sys.argv[3], "w").write(f"{path}\n")
print("model_dir", path)
PY
MODEL_OK=$(( PIPESTATUS[0] == 0 ))

if (( TEAM_IMPORTS_OK && BENCH_OK && MODEL_OK )); then status "A=ok"; else status "A=fail (06_imports / 07_bench64 / 08_model 로그 확인)"; fi
if (( SWIFT_INSTALL != 0 )); then status "B=불가 (ms-swift 설치 실패, 03_install_swift.log)"
elif (( ! SWIFT_IMPORTS_OK )); then status "B=불가 (swift import 실패, 06_imports.json)"
elif [[ -n "${NEW_CONFLICTS//[[:space:]]/}" ]]; then status "B=불가 (swift 설치 후 pip check 새 충돌, 05_pip_check_new_after_swift.log)"
elif (( ! (BENCH_OK && MODEL_OK) )); then status "B=불가 (데이터·모델 준비 실패)"
else status "B=ok"; fi
echo "=== setup 끝. 결과: $S/STATUS ==="; cat "$S/STATUS"
