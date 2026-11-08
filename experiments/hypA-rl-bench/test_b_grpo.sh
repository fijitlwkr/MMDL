#!/usr/bin/env bash
# 가설 A RL 사전 테스트 B: ms-swift GRPO 스모크 테스트. setup.sh 다음에, 테스트 A 가 끝난 뒤(GPU 를 비운 뒤) 돌린다.
#   - 원본 Qwen3-VL-4B-Instruct + LoRA r16 (LLM 만 학습, ViT·merger(aligner) 고정), vLLM colocate.
#   - bench64 에서 고정 16문항(OMR 8 + Honey 8) × 8회 생성 = 스텝당 128개, 4스텝, max_completion_length 2048.
#   - 임시 보상 answer_in_response, overlong_filter 켬. 플러그인(test_b_plugin.py)이 보상·첫 프롬프트 덤프·overlong 로그를 남긴다.
#   - 이미지 크기는 code/config.yaml 의 min/max_pixels 를 swift 환경변수(IMAGE_MIN/MAX_TOKEN_NUM = 픽셀 ÷ 32²)로 넘긴다.
#   - 생성 설정은 평가와 같은 temp 0.7 / top_p 0.8 / top_k 20 / repetition_penalty 1.0.
#     presence_penalty 는 swift GRPO 가 vLLM 에 넘기지 않아 0 이다(prompt_dump.json 의 sampling_params 로 확인).
#   - 끝나면 프롬프트 비교(평가 코드 inputs.py 와) + 측정 결과 정리를 한다. 실패해도 로그와 에러 전문은 남는다.
#
#   bash experiments/hypA-rl-bench/test_b_grpo.sh
# GPU 메모리 40GB 이상(RTX 6000 Ada 48GB)이면 마이크로배치 4, vLLM 메모리 비율 0.45. 그보다 작으면(RTX 4090) 2, 0.35.
# PDBS, VLLM_MEM, STEPS 환경변수로 바꿀 수 있다.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXP="$REPO/experiments/hypA-rl-bench"
OUT="${OUT:-/workspace/hypA_rl_bench}"
export HF_HOME="${HF_HOME:-/workspace/.cache/huggingface}"
BENCH="${BENCH:-$OUT/bench64}"
MODEL_DIR="${MODEL_DIR:-$(cat "$OUT/setup/model_dir.txt" 2>/dev/null)}"
B="$OUT/test_b"
N_ITEMS=16; NUM_GEN=8; STEPS="${STEPS:-4}"
grep -q '^B=ok' "$OUT/setup/STATUS" 2>/dev/null || { echo "ABORT: $OUT/setup/STATUS 에 B=ok 가 없음 (setup.sh 결과 확인)" >&2; exit 5; }
[[ -d "$MODEL_DIR" ]] || { echo "ABORT: 모델 폴더 없음: '$MODEL_DIR'" >&2; exit 5; }
GPU_MIB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
if (( GPU_MIB >= 40000 )); then PDBS="${PDBS:-4}"; VLLM_MEM="${VLLM_MEM:-0.45}"; else PDBS="${PDBS:-2}"; VLLM_MEM="${VLLM_MEM:-0.35}"; fi
GA=$(( N_ITEMS * NUM_GEN / PDBS ))  # 한 스텝 = 마이크로배치 PDBS × GA = 128 응답 = 16문항 × 8
if [[ -d "$B" ]]; then mv "$B" "$B.partial.$(date -u +%Y%m%dT%H%M%SZ)"; fi
mkdir -p "$B"; cd "$REPO"

python "$EXP/test_b_plugin.py" prepare --bench "$BENCH" --out "$B/train16.jsonl" --n "$N_ITEMS"
read -r MIN_TOK MAX_TOK < <(python -c "import sys, yaml; c = yaml.safe_load(open(sys.argv[1]))['image']; f = (c['image_patch_size'] * c['spatial_merge_size']) ** 2; print(c['min_pixels'] // f, c['max_pixels'] // f)" code/config.yaml)
export IMAGE_MIN_TOKEN_NUM="$MIN_TOK" IMAGE_MAX_TOKEN_NUM="$MAX_TOK" HYPA_B_OUT="$B"
echo "GPU ${GPU_MIB}MiB  micro_batch=$PDBS grad_accum=$GA vllm_mem=$VLLM_MEM steps=$STEPS  image tokens ${MIN_TOK}~${MAX_TOK}" | tee "$B/settings.txt"

nvidia-smi --query-gpu=timestamp,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits -l 1 > "$B/vram.csv" &
SMI=$!
T0=$(date +%s)
swift rlhf \
  --rlhf_type grpo \
  --model "$MODEL_DIR" --model_type qwen3_vl --template qwen3_vl --torch_dtype bfloat16 \
  --external_plugins "$EXP/test_b_plugin.py" --reward_funcs answer_in_response \
  --dataset "$B/train16.jsonl" --max_length 8192 --dataloader_num_workers 0 \
  --tuner_type lora --lora_rank 16 --lora_alpha 32 --target_modules all-linear \
  --freeze_llm false --freeze_vit true --freeze_aligner true \
  --num_generations "$NUM_GEN" --per_device_train_batch_size "$PDBS" --gradient_accumulation_steps "$GA" \
  --max_completion_length 2048 --overlong_filter true \
  --temperature 0.7 --top_p 0.8 --top_k 20 --repetition_penalty 1.0 \
  --use_vllm true --vllm_mode colocate --vllm_gpu_memory_utilization "$VLLM_MEM" --vllm_max_model_len 8192 \
  --vllm_limit_mm_per_prompt '{"image": 1, "video": 0}' --sleep_level 1 \
  --max_steps "$STEPS" --learning_rate 1e-5 --gradient_checkpointing true \
  --logging_steps 1 --save_steps "$STEPS" --save_only_model true --eval_strategy no \
  --log_completions true --report_to none --seed 3407 --data_seed 3407 \
  --output_dir "$B/swift" 2>&1 | tee "$B/b_run.log"
RC=${PIPESTATUS[0]}
kill "$SMI" 2>/dev/null
echo "$RC" > "$B/exit_code.txt"
echo "=== swift rlhf exit $RC, $(( ($(date +%s) - T0) / 60 )) min ==="

if [[ -f "$B/prompt_dump.json" ]]; then
  python "$EXP/test_b_plugin.py" compare --dump "$B/prompt_dump.json" --bench "$BENCH" --model_dir "$MODEL_DIR" \
    --out "$B/prompt_check.json" 2>&1 | tee "$B/prompt_check.log"
else
  echo "prompt_dump.json 없음 (생성 단계까지 못 갔거나 덤프 실패: plugin_errors.txt 확인)"
fi
python "$EXP/test_b_plugin.py" summarize --b_out "$B" --out "$B" 2>&1 | tee "$B/summarize.log"
# LoRA 가 비전 쪽에 붙지 않았는지: 저장된 어댑터 키 중 visual 이 들어간 것의 개수
python - "$B" <<'PY' 2>&1 | tee "$B/adapter_check.log"
import json, sys
from pathlib import Path
from safetensors import safe_open
files = sorted(Path(sys.argv[1]).glob("swift/**/adapter_model.safetensors"))
if not files:
    print("저장된 어댑터 없음"); sys.exit()
keys = list(safe_open(str(files[-1]), "pt").keys())
cfg = json.loads((files[-1].parent / "adapter_config.json").read_text())
print(json.dumps({"adapter": str(files[-1]), "lora_keys": len(keys), "visual_keys": sum("visual" in k for k in keys),
                  "r": cfg.get("r"), "lora_alpha": cfg.get("lora_alpha"), "target_modules": cfg.get("target_modules")}, indent=1))
PY
exit "$RC"
