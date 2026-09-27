#!/usr/bin/env bash
# Step 2 - 0단계: 환경 설치 + 즉시 검증
# 실패 시 바로 멈춤 (비용 낭비 방지)
set -euo pipefail
cd "$(dirname "$0")"

source ./env.sh

echo "================================================================"
echo "[0/3] GPU / 드라이버 확인"
echo "================================================================"
nvidia-smi --query-gpu=name,memory.total,driver_version,power.limit --format=csv

echo
echo "================================================================"
echo "[1/3] 의존성 설치 (requirements.txt) - 수 분 걸릴 수 있음, 출력이 곧 진행 상황입니다"
echo "================================================================"
pip install -r requirements.txt

echo
echo "================================================================"
echo "[2/3] 설치/torch 검증"
echo "================================================================"
python3 -c "
import torch, vllm, transformers, datasets, qwen_vl_utils
print('torch          :', torch.__version__, '| cuda available:', torch.cuda.is_available())
print('vllm           :', vllm.__version__)
print('transformers   :', transformers.__version__)
print('datasets       :', datasets.__version__)
print('qwen_vl_utils  :', qwen_vl_utils.__version__ if hasattr(qwen_vl_utils, '__version__') else 'OK (버전 속성 없음, import 성공)')
"

echo
echo "================================================================"
echo "[3/3] 디스크 여유 확인"
echo "================================================================"
df -h / /workspace 2>/dev/null || df -h /

echo
echo "환경 설치 완료. 문제 없으면 build_dataset.py로 진행하세요."
