#!/usr/bin/env bash
# 반드시 `source env.sh`로 불러올 것 (bash env.sh로 실행하면 하위 프로세스에만 적용되고
# 상위 셸/스크립트로 전파되지 않아 HF_HOME이 실제로 안 먹힘)
export HF_HOME=/workspace/.cache/huggingface
mkdir -p "$HF_HOME"
echo "HF_HOME=$HF_HOME (Container disk가 아니라 Volume disk에 캐시 — pod stop 후에도 유지됨)"

# 일부 RunPod 호스트에서 CUDA_VISIBLE_DEVICES가 빈 문자열("")로 세팅되어 있는 경우가 있음.
# CUDA는 빈 값을 "보이는 디바이스 0개"로 해석해 torch.cuda 초기화가 실패함 -> 비어있으면 unset.
if [ -n "${CUDA_VISIBLE_DEVICES+x}" ] && [ -z "$CUDA_VISIBLE_DEVICES" ]; then
  echo "CUDA_VISIBLE_DEVICES가 빈 문자열로 설정되어 있어 unset 처리함 (그대로 두면 GPU 0개로 인식됨)"
  unset CUDA_VISIBLE_DEVICES
fi
