#!/usr/bin/env bash
# Run with bash on the GPU host (Linux, Python 3.12).
set -euo pipefail
cd "$(dirname "$0")"
python3.12 -m venv .venv-train
.venv-train/bin/python -m pip install -r requirements-train.txt
.venv-train/bin/python -m pip check
python3.12 -m venv .venv-eval
.venv-eval/bin/python -m pip install -r ../../../../code/requirements.txt
.venv-eval/bin/python -m pip check
mkdir -p artifacts
for env in train eval; do
    ".venv-$env/bin/python" -m pip freeze > "artifacts/$env-packages.txt"
done
