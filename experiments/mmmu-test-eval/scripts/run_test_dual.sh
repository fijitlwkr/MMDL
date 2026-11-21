#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 6 || ( "$1" != smoke && "$1" != full ) ]]; then
  echo "Usage: run_test_dual.sh smoke|full CODE_DIR CONFIG_TEST MODEL_DIR DATA_CACHE OUTPUT_ROOT" >&2
  exit 2
fi
mode=$1
code=$(realpath "$2")
config=$(realpath "$3")
model=$(realpath "$4")
data=$(realpath "$5")
root=$(realpath -m "$6")
scripts=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
: "${HF_HOME:?Set HF_HOME before running}"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=4
mapfile -t gpu_names < <(nvidia-smi --query-gpu=name --format=csv,noheader)
[[ "${#gpu_names[@]}" == 2 && "${gpu_names[0]}" == "NVIDIA GeForce RTX 4090" && "${gpu_names[1]}" == "NVIDIA GeForce RTX 4090" ]]
if [[ "$mode" == full ]]; then
  python "$scripts/test_shards.py" --config "$config" --smoke "$root/smoke"
fi
mkdir -p "$root"
mkdir "$root/$mode"
run_worker() (
  set -euo pipefail
  gpu=$1
  dir="$root/$mode/gpu$gpu"
  mkdir "$dir"
  mapfile -t plan < <(python "$scripts/test_shards.py" --config "$config" --gpu "$gpu")
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
run_worker 0 &
pid0=$!
run_worker 1 &
pid1=$!
rc0=0
rc1=0
wait "$pid0" || rc0=$?
wait "$pid1" || rc1=$?
printf 'gpu0=%s gpu1=%s\n' "$rc0" "$rc1"
if (( rc0 || rc1 )); then
  exit 1
fi
if [[ "$mode" == smoke ]]; then
  python "$scripts/test_shards.py" --config "$config" --smoke "$root/smoke"
else
  python "$scripts/test_shards.py" --config "$config" --merge "$root/full"
  python "$code/validate_raw.py" --config "$config" --raw "$root/full/raw.jsonl" --expect 10500
fi
