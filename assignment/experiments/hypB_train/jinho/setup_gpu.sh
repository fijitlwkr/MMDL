#!/usr/bin/env bash
# Run with bash on the GPU host (Linux, Python 3.12).
set -euo pipefail

echo "=== 1. Checking and installing system dependencies ==="
if command -v apt-get >/dev/null 2>&1; then
    # Ensure python3.12-venv and basic build tools are installed
    if ! dpkg -s python3.12-venv >/dev/null 2>&1 || ! dpkg -s git-lfs >/dev/null 2>&1; then
        echo "Installing system packages (python3.12-venv, git-lfs, curl)..."
        apt-get update -qq && apt-get install -y -qq python3.12-venv python3.12-dev git-lfs curl
    fi
fi

cd "$(dirname "$0")"

echo "=== 2. Setting up .venv-train (ms-swift & training stack) ==="
if [ ! -d ".venv-train" ]; then
    echo "Creating .venv-train and installing packages..."
    python3.12 -m venv .venv-train
    .venv-train/bin/python -m pip install --upgrade pip setuptools wheel
    .venv-train/bin/python -m pip install -r requirements-train.txt
    .venv-train/bin/python -m pip check
else
    echo ".venv-train already exists, skipping installation."
fi

echo "=== 3. Setting up .venv-eval (vLLM 0.11.0 stack) ==="
if [ ! -d ".venv-eval" ]; then
    echo "Creating .venv-eval and installing packages..."
    python3.12 -m venv .venv-eval
    .venv-eval/bin/python -m pip install --upgrade pip setuptools wheel
    .venv-eval/bin/python -m pip install -r ../../../../code/requirements.txt
    .venv-eval/bin/python -m pip check
else
    echo ".venv-eval already exists, skipping installation."
fi

echo "=== 4. Saving installed packages manifest ==="
mkdir -p artifacts
for env in train eval; do
    ".venv-$env/bin/python" -m pip freeze > "artifacts/$env-packages.txt"
done

echo "=== Setup completed successfully! Everything is ready for training. ==="
