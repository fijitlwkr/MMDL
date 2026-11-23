#!/usr/bin/env bash
# full 생성이 7번째 묶음(767~916)에서 GPU 유휴·CPU 100% 상태로 40분 넘게 멈춰 프로세스를 끈 뒤,
# 같은 출력 폴더에서 이어받는다(generate.py resume: 기존 766행 유지, 같은 config·seed).
set -Eeuo pipefail
cd /workspace/eval_pro_D3e1_20261123
export HF_HOME=/workspace/hf_cache HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
export PIP_CACHE_DIR=/workspace/pip_cache XDG_CACHE_HOME=/workspace/cache
export TRITON_CACHE_DIR=/workspace/triton_cache CUDA_CACHE_PATH=/workspace/cuda_cache
export TORCHINDUCTOR_CACHE_DIR=/workspace/torchinductor_cache VLLM_CACHE_ROOT=/workspace/vllm_cache
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=4
export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0
code=$PWD/package/code; config=$code/config_pro.yaml
model=/workspace/eval_D3e1_20261113/models/D3e1; data=/workspace/mmmu_cache
dir=$PWD/runs/pro_seed_3407/full; records=$PWD/records
rm -f "$records/exit" "$records/finished_utc"
trap 'rc=$?; kill "$sampler" 2>/dev/null || true; echo "$rc" > "$records/exit"; date -u -Is > "$records/finished_utc"' EXIT
printf "%s\n" generation_resume1 > "$records/stage"
nvidia-smi -i 0 --query-gpu=timestamp,index,memory.used,memory.total --format=csv,noheader,nounits -l 1 > "$dir/physical_gpu_memory_resume1.csv" &
sampler=$!
EXPECT_ROWS=1730 bash "$code/run_generate.sh" --config "$config" --model_path "$model" --data_root "$data" --out "$dir" > "$records/generation_resume1.log" 2>&1
python "$code/validate_raw.py" --config "$config" --raw "$dir/raw.jsonl" --expect 1730 >> "$records/generation_resume1.log" 2>&1
sha256sum "$dir/raw.jsonl" | tee -a "$records/generation_resume1.log"
printf "%s\n" complete > "$records/stage"
