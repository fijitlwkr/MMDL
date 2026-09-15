#!/usr/bin/env bash
# Usage: source env.sh. Contains defaults only; no API keys are needed for rule-only scoring.
export BASELINE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export HF_HOME="${HF_HOME:-${BASELINE_ROOT}/.cache/huggingface}"
export BASELINE_MODEL="${BASELINE_MODEL:-Qwen/Qwen3-VL-4B-Instruct}"
export BASELINE_MODEL_REVISION="${BASELINE_MODEL_REVISION:-ebb281ec70b05090aa6165b016eac8ec08e71b17}"
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export TOKENIZERS_PARALLELISM=false
if [[ -x "${BASELINE_ROOT}/.venv/bin/python" ]]; then
  export BASELINE_PYTHON="${BASELINE_PYTHON:-${BASELINE_ROOT}/.venv/bin/python}"
else
  export BASELINE_PYTHON="${BASELINE_PYTHON:-python3}"
fi
