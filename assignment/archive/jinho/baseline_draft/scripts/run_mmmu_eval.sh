#!/usr/bin/env bash
set -e

# Script Directory Resolution
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$( dirname "$SCRIPT_DIR" )"

# Default Arguments
MODEL_PATH="Qwen/Qwen3-VL-4B-Instruct"
DATA_ROOT="MMMU/MMMU"
OUTPUT_DIR="$PROJECT_ROOT/data"
EXTRA_ARGS=()

# Parse Command Line Arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --model_path)
            MODEL_PATH="$2"
            shift 2
            ;;
        --data_root)
            DATA_ROOT="$2"
            shift 2
            ;;
        --output_dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

echo "=========================================================="
echo "Starting MMMU Baseline Evaluation Pipeline"
echo "Project Root : $PROJECT_ROOT"
echo "Model Path   : $MODEL_PATH"
echo "Data Root    : $DATA_ROOT"
echo "Output Dir   : $OUTPUT_DIR"
echo "=========================================================="

export PYTHONPATH="$PROJECT_ROOT/src:$PYTHONPATH"

python3 "$PROJECT_ROOT/src/evaluate_vllm.py" \
    --model_path "$MODEL_PATH" \
    --data_root "$DATA_ROOT" \
    --output_dir "$OUTPUT_DIR" \
    "${EXTRA_ARGS[@]}"

echo "=========================================================="
echo "MMMU Baseline Evaluation Finished Successfully!"
echo "=========================================================="
