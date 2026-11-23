#!/usr/bin/env bash
set -euo pipefail
if [[ ( $# -ne 6 && $# -ne 7 ) || ( "$1" != smoke && "$1" != full ) ]]; then
  echo "Usage: run_test_dual.sh smoke|full CODE_DIR CONFIG_TEST MODEL_DIR DATA_CACHE OUTPUT_ROOT [1|2]" >&2
  exit 2
fi
mode=$1
code=$(realpath "$2")
config=$(realpath "$3")
model=$(realpath "$4")
data=$(realpath "$5")
root=$(realpath -m "$6")
gpu_count=${7:-2}
[[ "$gpu_count" == 1 || "$gpu_count" == 2 ]]
scripts=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
: "${HF_HOME:?Set HF_HOME before running}"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=4
mapfile -t gpu_names < <(nvidia-smi --query-gpu=name --format=csv,noheader)
[[ "${#gpu_names[@]}" == "$gpu_count" ]]
for name in "${gpu_names[@]}"; do
  [[ "$name" == "NVIDIA GeForce RTX 4090" ]]
done
if [[ "$mode" == full ]]; then
  python "$scripts/test_shards.py" --config "$config" --gpu-count "$gpu_count" --smoke "$root/smoke"
fi
mkdir -p "$root"
mkdir "$root/$mode"
run_worker() (
  set -euo pipefail
  gpu=$1
  dir="$root/$mode/gpu$gpu"
  mkdir "$dir"
  mapfile -t plan < <(python "$scripts/test_shards.py" --config "$config" --gpu-count "$gpu_count" --gpu "$gpu")
  [[ "${#plan[@]}" == 2 ]]
  export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES="$gpu"
  python -c 'import torch; assert torch.__version__=="2.8.0+cu128" and torch.cuda.device_count()==1; assert "RTX 4090" in torch.cuda.get_device_name(0)'
  nvidia-smi -i "$gpu" --query-gpu=timestamp,index,memory.used,memory.total --format=csv,noheader,nounits -l 1 > "$dir/physical_gpu_memory.csv" &
  sampler=$!
  trap 'rc=$?; kill "$sampler" 2>/dev/null || true; printf "%s\n" "$rc" > "$dir/worker.exit"' EXIT
  flags=()
  expected="${plan[1]}"
  if [[ "$mode" == smoke ]]; then
    expected=3
    flags=(--limit 3)
  fi
  EXPECT_ROWS="$expected" bash "$code/run_generate.sh" --config "$config" --model_path "$model" \
    --data_root "$data" --out "$dir" --subjects "${plan[0]}" "${flags[@]}" > "$dir/worker.log" 2>&1
)
pids=()
for (( gpu=0; gpu<gpu_count; gpu++ )); do
  run_worker "$gpu" &
  pids+=("$!")
done
failed=0
for gpu in "${!pids[@]}"; do
  rc=0
  wait "${pids[gpu]}" || rc=$?
  printf 'gpu%s=%s\n' "$gpu" "$rc"
  if (( rc )); then failed=1; fi
done
(( failed == 0 ))
if [[ "$mode" == smoke ]]; then
  python "$scripts/test_shards.py" --config "$config" --gpu-count "$gpu_count" --smoke "$root/smoke"
else
  python "$scripts/test_shards.py" --config "$config" --gpu-count "$gpu_count" --merge "$root/full"
  python "$code/validate_raw.py" --config "$config" --raw "$root/full/raw.jsonl" --expect 10500
fi
