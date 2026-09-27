"""
Step 2 - 2단계: vLLM 추론.
프롬프트 템플릿/생성 파라미터는 Qwen3-VL 공식 evaluation/mmmu/run_mmmu.py::build_mmmu_prompt()
구조를 그대로 재사용 (MMMU 논문 Appendix B 템플릿과 구조 일치 확인됨).
모델 revision은 run_mmmu.py의 --model-path 우회 없이 vLLM에 직접 전달.
"""
import argparse
import json
import os

os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD", "spawn")

from vllm import LLM, SamplingParams
from qwen_vl_utils import process_vision_info
from transformers import AutoProcessor

MODEL_NAME = "Qwen/Qwen3-VL-4B-Instruct"
MODEL_REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"

# build_mmmu_prompt() 내부 하드코딩 상수와 동일 (공식 evaluator와 일치 확인됨)
MIN_PIXELS = 1280 * 28 * 28
MAX_PIXELS = 5120 * 28 * 28


def build_prompt_messages(rec):
    options = rec["options"]
    prompt = f"Question: {rec['question']}\n"
    if options:
        prompt += "Options:\n"
        for k, v in options.items():
            prompt += f"{k}. {v}\n"
        prompt += "Please select the correct answer from the options above. \n"
    prompt = prompt.rstrip()

    content = []
    for path in rec["image_paths"]:
        content.append({
            "type": "image",
            "image": path,
            "min_pixels": MIN_PIXELS,
            "max_pixels": MAX_PIXELS,
        })
    content.append({"type": "text", "text": prompt})

    return [{"role": "user", "content": content}]


def prepare_vllm_input(messages, processor):
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs, video_kwargs = process_vision_info(
        messages,
        image_patch_size=processor.image_processor.patch_size,
        return_video_kwargs=True,
        return_video_metadata=True,
    )
    mm_data = {}
    if image_inputs is not None:
        mm_data["image"] = image_inputs
    if video_inputs is not None:
        mm_data["video"] = video_inputs

    # 실제 프롬프트 토큰 수(비전 토큰 포함)를 여기서 미리 계산해서 요청별 max_tokens 산정에 사용.
    # Group B에서 문자 길이 프록시가 "텍스트는 짧지만 이미지가 많아 실제로는 긴" 입력을 놓치는 걸
    # 확인했기 때문에(짧은 텍스트+이미지 5장이 5,154 토큰으로 나옴), 900문항 전체는 이렇게
    # 요청 시점에 직접 재는 것이 별도 사전 스캔보다 안전하고 비용도 적게 듦.
    encoded = processor(text=[text], images=image_inputs, videos=video_inputs, return_tensors="pt", **video_kwargs)
    prompt_len = int(encoded["input_ids"].shape[-1])

    return {"prompt": text, "multi_modal_data": mm_data, "mm_processor_kwargs": video_kwargs}, prompt_len


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/mmmu_light.jsonl")
    ap.add_argument("--out", default="data/predictions_light.jsonl")
    ap.add_argument("--max-model-len", type=int, default=9048, help="수업 고정값")
    ap.add_argument("--max-new-tokens", type=int, default=3200,
                     help="Group A 실측(finish_reason='length' 7/30건, 그 중 6건이 파싱 실패와 겹침)에 근거해 "
                          "2048->3200으로 상향. max_model_len=9048, 실측 최대 입력 5627 토큰 기준 안전 여유 확보")
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.9)
    args = ap.parse_args()

    records = [json.loads(line) for line in open(args.data, encoding="utf-8")]
    print(f"입력 문항 수: {len(records)}")

    processor = AutoProcessor.from_pretrained(MODEL_NAME, revision=MODEL_REVISION)

    llm = LLM(
        model=MODEL_NAME,
        revision=MODEL_REVISION,
        tokenizer_revision=MODEL_REVISION,
        max_model_len=args.max_model_len,
        gpu_memory_utilization=args.gpu_memory_utilization,
        trust_remote_code=True,
        limit_mm_per_prompt={"image": 10},
        seed=42,  # run_mmmu.py 내부 하드코딩값과 동일 (README recipe의 3407과는 별개, env_config 문서 참고)
    )

    sampling_kwargs = dict(
        temperature=0.7,
        top_p=0.8,
        top_k=20,
        repetition_penalty=1.0,
        presence_penalty=1.5,
        stop_token_ids=[],
        seed=42,
    )

    SAFETY_MARGIN = 16  # 채팅 템플릿/특수토큰 오차 여유분
    vllm_inputs = []
    sampling_params_list = []
    long_input_flags = []
    for rec in records:
        messages = build_prompt_messages(rec)
        vllm_input, prompt_len = prepare_vllm_input(messages, processor)
        vllm_inputs.append(vllm_input)

        remaining_budget = args.max_model_len - prompt_len - SAFETY_MARGIN
        this_max_tokens = max(1, min(args.max_new_tokens, remaining_budget))
        if remaining_budget < args.max_new_tokens:
            long_input_flags.append((rec["uid"], prompt_len, this_max_tokens))

        sampling_params_list.append(SamplingParams(max_tokens=this_max_tokens, **sampling_kwargs))

    if long_input_flags:
        print(f"\n[경고] {len(long_input_flags)}건은 입력이 길어 max_new_tokens={args.max_new_tokens}를 그대로 못 씀 "
              f"(동적으로 축소 적용, max_model_len={args.max_model_len} 초과 방지):")
        for uid, plen, mt in long_input_flags:
            print(f"  - {uid}: prompt_len={plen}, 적용된 max_tokens={mt}")

    outputs = llm.generate(vllm_inputs, sampling_params_list)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for rec, out in zip(records, outputs):
            gen = out.outputs[0]
            raw = gen.text
            # run_mmmu.py: response_final = str(response).split("</think>")[-1].strip()
            # thinking 모델이 아니어도 안전하게 동일 처리 (</think> 없으면 raw와 동일해짐)
            final = str(raw).split("</think>")[-1].strip()
            f.write(json.dumps({
                "uid": rec["uid"],
                "subject": rec["subject"],
                "answer": rec["answer"],
                "options": rec["options"],
                "question_type": rec["question_type"],
                "prediction_raw": raw,
                "prediction_final": final,
                "finish_reason": gen.finish_reason,
                "n_generated_tokens": len(gen.token_ids) if gen.token_ids else None,
            }, ensure_ascii=False) + "\n")

    print(f"예측 {len(records)}건 저장 완료 -> {args.out}")


if __name__ == "__main__":
    main()
