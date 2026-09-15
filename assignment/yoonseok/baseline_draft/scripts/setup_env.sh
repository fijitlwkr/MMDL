#!/usr/bin/env bash
set -euo pipefail
BASELINE_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${BASELINE_SCRIPT_DIR}/env.sh"
case "${1:-}" in
  --help|-h)
    echo 'Usage: bash scripts/setup_env.sh [--check-only]'
    echo 'Creates .venv, installs pinned requirements, then verifies imports and GPU access.'
    exit 0 ;;
  ''|--check-only) ;;
  *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
if [[ "${1:-}" != --check-only ]]; then
  python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), "Use Python 3.12"'
  python3 -m venv "${BASELINE_ROOT}/.venv"
  "${BASELINE_ROOT}/.venv/bin/python" -m pip install --upgrade pip
  "${BASELINE_ROOT}/.venv/bin/python" -m pip install -r "${BASELINE_ROOT}/requirements.txt"
fi
BASELINE_CHECK_PYTHON="${BASELINE_ROOT}/.venv/bin/python"
if [[ ! -x "${BASELINE_CHECK_PYTHON}" ]]; then
  echo 'No .venv found. Run bash scripts/setup_env.sh first.' >&2
  exit 1
fi
"${BASELINE_CHECK_PYTHON}" -m pip check
"${BASELINE_CHECK_PYTHON}" - <<'CHECK'
import importlib.metadata
import torch
import vllm
import transformers
import datasets
import qwen_vl_utils
for name in ['torch', 'vllm', 'transformers', 'datasets', 'qwen-vl-utils']:
    print(name, importlib.metadata.version(name))
if not torch.cuda.is_available():
    raise SystemExit('CUDA is unavailable; CPU parser checks work, but vLLM inference requires a GPU.')
print('GPU:', torch.cuda.get_device_name(0))
CHECK
"${BASELINE_CHECK_PYTHON}" "${BASELINE_ROOT}/src/mc_parsers.py" --self-test
mkdir -p "${BASELINE_ROOT}/logs"
"${BASELINE_CHECK_PYTHON}" -m pip freeze > "${BASELINE_ROOT}/logs/requirements-installed.txt"
echo 'Environment ready. source scripts/env.sh again before running the scripts.'
