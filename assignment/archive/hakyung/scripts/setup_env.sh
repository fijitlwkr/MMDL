#!/usr/bin/env bash
set -euo pipefail
python -m pip install \
  --index-url https://download.pytorch.org/whl/cu128 \
  torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0
python -m pip install -r requirements.txt
python -m pip check
