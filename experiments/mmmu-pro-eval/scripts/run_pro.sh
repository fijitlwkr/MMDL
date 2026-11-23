#!/usr/bin/env bash
# MMMU-Pro standard (10 options), RTX 4090 1장, 전체 과목을 한 프로세스로 생성한다.
set -euo pipefail
if [[ $# -ne 6 || ( "$1" != smoke && "$1" != full ) ]]; then
  echo "Usage: run_pro.sh smoke|full CODE_DIR CONFIG_PRO MODEL_DIR DATA_CACHE OUTPUT_ROOT" >&2
  exit 2
fi
mode=$1
code=$(realpath "$2")
config=$(realpath "$3")
model=$(realpath "$4")
data=$(realpath "$5")
root=$(realpath -m "$6")
: "${HF_HOME:?Set HF_HOME before running}"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=4
mapfile -t gpu_names < <(nvidia-smi --query-gpu=name --format=csv,noheader)
[[ "${#gpu_names[@]}" -ge 1 && "${gpu_names[0]}" == "NVIDIA GeForce RTX 4090" ]]
total=$(python -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["dataset"]["expected_total_rows"])' "$config")
if [[ "$mode" == full ]]; then
  [[ -f "$root/smoke/logs/04_validate_raw.log" ]] || { echo "run smoke first" >&2; exit 3; }
fi
dir="$root/$mode"
mkdir -p "$root"
mkdir "$dir"
export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0
python -c 'import torch; assert torch.__version__=="2.8.0+cu128" and torch.cuda.device_count()==1; assert "RTX 4090" in torch.cuda.get_device_name(0)'
nvidia-smi -i 0 --query-gpu=timestamp,index,memory.used,memory.total --format=csv,noheader,nounits -l 1 > "$dir/physical_gpu_memory.csv" &
sampler=$!
trap 'kill "$sampler" 2>/dev/null || true' EXIT
flags=()
expected="$total"
if [[ "$mode" == smoke ]]; then
  expected=3
  flags=(--limit 3)
fi
EXPECT_ROWS="$expected" bash "$code/run_generate.sh" --config "$config" --model_path "$model" \
  --data_root "$data" --out "$dir" "${flags[@]}" 2>&1 | tee "$dir/worker.log"
python "$code/validate_raw.py" --config "$config" --raw "$dir/raw.jsonl" --expect "$expected"
sha256sum "$dir/raw.jsonl"
