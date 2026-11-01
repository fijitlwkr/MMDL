#!/usr/bin/env bash
export HF_HOME=/workspace/hf_cache XDG_CACHE_HOME=/workspace/cache TMPDIR=/workspace/tmp MODELSCOPE_CACHE=/workspace/cache/modelscope MPLCONFIGDIR=/workspace/cache/matplotlib
export HF_HUB_OFFLINE=1 OMP_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false CUDA_VISIBLE_DEVICES=0
cd /workspace/MMDL/assignment/experiments/hypB_train/yoonseok
date -u +%Y-%m-%dT%H:%M:%SZ > artifacts/full_20261101/E1_started.txt
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv,noheader,nounits --loop=1 > artifacts/full_20261101/E1_memory.csv &
monitor=$!
trap 'kill "$monitor" 2>/dev/null || true' EXIT
.venv-train/bin/python -u full.py E1 full /workspace/hf_cache/hub/datasets--MMDL-team4--hypB-train-data/snapshots/1833bac3be047aa8bd146492436323bb7c14092a full_E1_20261101 > artifacts/full_20261101/E1_train.txt 2>&1
code=$?
date -u +%Y-%m-%dT%H:%M:%SZ > artifacts/full_20261101/E1_finished.txt
echo "$code" > artifacts/full_20261101/E1_train.exit
exit "$code"
