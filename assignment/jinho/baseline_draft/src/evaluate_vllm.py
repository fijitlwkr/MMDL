"""
Evaluation script for Qwen3-VL-4B-Instruct on MMMU validation set.
Strictly follows constraints in assignment_guidance.md and configuration in Inference Setup.png.
"""

import os
import sys
import time
import json
import argparse
from typing import List, Dict, Any

import torch
from tqdm import tqdm

from prompt_template import format_mmmu_prompt, extract_images_from_sample
from parser import parse_answer, is_correct

# 30 official MMMU subjects
MMMU_SUBJECTS = [
    "Accounting",
    "Agriculture",
    "Architecture_and_Engineering",
    "Art",
    "Art_Theory",
    "Basic_Medical_Science",
    "Biology",
    "Chemistry",
    "Clinical_Medicine",
    "Computer_Science",
    "Design",
    "Diagnostics_and_Laboratory_Medicine",
    "Economics",
    "Electronics",
    "Energy_and_Power",
    "Finance",
    "Geography",
    "History",
    "Literature",
    "Manage",
    "Marketing",
    "Materials",
    "Math",
    "Mechanical_Engineering",
    "Music",
    "Pharmacy",
    "Physics",
    "Psychology",
    "Public_Health",
    "Sociology",
]

# Fixed assignment constraints
PINNED_MODEL_REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"
PINNED_DATASET_REVISION = "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68"

# Default hyperparameters from Inference Setup.png
DEFAULT_MAX_MODEL_LENGTH = 9048
DEFAULT_MAX_NEW_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.8
DEFAULT_TOP_K = 20
DEFAULT_REPETITION_PENALTY = 1.0
DEFAULT_PRESENCE_PENALTY = 1.5
DEFAULT_MIN_PIXELS = 1280 * 28 * 28  # 1003520
DEFAULT_MAX_PIXELS = 5120 * 28 * 28  # 4014080


def parse_args():
    parser = argparse.ArgumentParser(description="MMMU Evaluation Pipeline for Qwen3-VL")
    parser.add_argument("--model_path", type=str, default="Qwen/Qwen3-VL-4B-Instruct",
                        help="HuggingFace model ID or local path")
    parser.add_argument("--model_revision", type=str, default=PINNED_MODEL_REVISION,
                        help="Exact pinned model revision")
    parser.add_argument("--data_root", type=str, default="MMMU/MMMU",
                        help="MMMU dataset repository or local path")
    parser.add_argument("--dataset_revision", type=str, default=PINNED_DATASET_REVISION,
                        help="Exact pinned dataset revision")
    parser.add_argument("--output_dir", type=str, default="results",
                        help="Directory to store evaluation outputs")
    parser.add_argument("--backend", type=str, choices=["auto", "vllm", "transformers"], default="auto",
                        help="Inference engine backend")
    parser.add_argument("--limit_samples", type=int, default=None,
                        help="Limit samples per subject for testing (leave None for full 30)")
    parser.add_argument("--subjects", type=str, nargs="+", default=None,
                        help="Specific subjects to evaluate (default: all 30)")
    return parser.parse_args()


class VLLMRunner:
    def __init__(self, model_path: str, revision: str, max_model_len: int):
        from vllm import LLM, SamplingParams
        print(f"[Init vLLM] Loading {model_path} (revision={revision}) with max_model_len={max_model_len}...")
        self.llm = LLM(
            model=model_path,
            revision=revision,
            dtype="bfloat16",
            max_model_len=max_model_len,
            trust_remote_code=True,
            limit_mm_per_prompt={"image": 7},
        )
        self.sampling_params = SamplingParams(
            temperature=DEFAULT_TEMPERATURE,
            top_p=DEFAULT_TOP_P,
            top_k=DEFAULT_TOP_K,
            repetition_penalty=DEFAULT_REPETITION_PENALTY,
            presence_penalty=DEFAULT_PRESENCE_PENALTY,
            max_tokens=DEFAULT_MAX_NEW_TOKENS,
        )

    def generate(self, prompts: List[str], images_list: List[List[Any]]) -> List[str]:
        inputs = []
        for prompt, imgs in zip(prompts, images_list):
            if imgs and len(imgs) > 0:
                image_tags = "".join(["<|image_pad|>" for _ in imgs])
                formatted_prompt = f"<|im_start|>user\n{image_tags}{prompt}<|im_end|>\n<|im_start|>assistant\n"
                inputs.append({
                    "prompt": formatted_prompt,
                    "multi_modal_data": {"image": imgs}
                })
            else:
                formatted_prompt = f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
                inputs.append({"prompt": formatted_prompt})

        outputs = self.llm.generate(inputs, sampling_params=self.sampling_params)
        return [out.outputs[0].text for out in outputs]


class TransformersRunner:
    def __init__(self, model_path: str, revision: str):
        from transformers import AutoProcessor, AutoModelForVision2Seq
        print(f"[Init Transformers] Loading {model_path} (revision={revision})...")
        
        device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
        print(f"[Device] Using device: {device}")
        
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        
        self.processor = AutoProcessor.from_pretrained(
            model_path,
            revision=revision,
            trust_remote_code=True,
            min_pixels=DEFAULT_MIN_PIXELS,
            max_pixels=DEFAULT_MAX_PIXELS
        )
        self.model = AutoModelForVision2Seq.from_pretrained(
            model_path,
            revision=revision,
            torch_dtype=dtype,
            trust_remote_code=True
        ).to(device)
        self.device = device

    def generate(self, prompts: List[str], images_list: List[List[Any]]) -> List[str]:
        results = []
        for prompt, imgs in zip(prompts, images_list):
            messages = [{"role": "user", "content": []}]
            for img in imgs:
                messages[0]["content"].append({"type": "image", "image": img})
            messages[0]["content"].append({"type": "text", "text": prompt})

            text_input = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self.processor(
                text=[text_input],
                images=imgs if imgs else None,
                padding=True,
                return_tensors="pt"
            ).to(self.device)

            with torch.no_grad():
                gen_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=DEFAULT_MAX_NEW_TOKENS,
                    temperature=DEFAULT_TEMPERATURE,
                    top_p=DEFAULT_TOP_P,
                    top_k=DEFAULT_TOP_K,
                    repetition_penalty=DEFAULT_REPETITION_PENALTY,
                    do_sample=True,
                )
            
            gen_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, gen_ids)
            ]
            response = self.processor.batch_decode(
                gen_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0]
            results.append(response)
        return results


def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    try:
        from datasets import load_dataset
    except ImportError:
        print("Error: 'datasets' package is required. Please install via 'pip install datasets'.")
        sys.exit(1)

    # Determine backend
    if args.backend == "auto":
        try:
            import vllm
            backend_choice = "vllm" if torch.cuda.is_available() else "transformers"
        except ImportError:
            backend_choice = "transformers"
    else:
        backend_choice = args.backend

    print(f"=== MMMU Baseline Evaluation ===")
    print(f"Model: {args.model_path} (revision: {args.model_revision})")
    print(f"Dataset: {args.data_root} (revision: {args.dataset_revision})")
    print(f"Backend: {backend_choice}")
    print(f"Decoding Settings: temp={DEFAULT_TEMPERATURE}, top_p={DEFAULT_TOP_P}, top_k={DEFAULT_TOP_K}, "
          f"presence_penalty={DEFAULT_PRESENCE_PENALTY}, max_new_tokens={DEFAULT_MAX_NEW_TOKENS}")
    print(f"Image Budget: min_pixels={DEFAULT_MIN_PIXELS}, max_pixels={DEFAULT_MAX_PIXELS}")

    # Initialize runner
    if backend_choice == "vllm":
        runner = VLLMRunner(args.model_path, args.model_revision, DEFAULT_MAX_MODEL_LENGTH)
    else:
        runner = TransformersRunner(args.model_path, args.model_revision)

    target_subjects = args.subjects if args.subjects else MMMU_SUBJECTS
    all_predictions = []
    subject_results = {}
    total_correct = 0
    total_samples = 0

    start_time = time.time()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    for sub_idx, subject in enumerate(target_subjects, start=1):
        print(f"\n[{sub_idx}/{len(target_subjects)}] Evaluating subject: {subject}...")
        try:
            dataset = load_dataset(
                args.data_root,
                subject,
                split="validation",
                revision=args.dataset_revision
            )
        except Exception as e:
            print(f"Error loading subject {subject}: {e}")
            continue

        if args.limit_samples:
            dataset = dataset.select(range(min(args.limit_samples, len(dataset))))

        prompts = []
        images_list = []
        samples_info = []

        for sample in dataset:
            prompt = format_mmmu_prompt(sample["question"], sample.get("options", []))
            imgs = extract_images_from_sample(sample)
            prompts.append(prompt)
            images_list.append(imgs)
            samples_info.append({
                "id": sample.get("id", ""),
                "subject": subject,
                "question": sample["question"],
                "ground_truth": sample.get("answer", ""),
            })

        # Run inference
        outputs = runner.generate(prompts, images_list)

        sub_correct = 0
        sub_total = len(samples_info)

        for info, out_text in zip(samples_info, outputs):
            pred_choice = parse_answer(out_text)
            gt = info["ground_truth"]
            correct = is_correct(pred_choice, gt)
            if correct:
                sub_correct += 1

            record = {
                "id": info["id"],
                "subject": subject,
                "ground_truth": gt,
                "prediction": pred_choice,
                "is_correct": correct,
                "raw_output": out_text
            }
            all_predictions.append(record)

        sub_acc = (sub_correct / sub_total * 100) if sub_total > 0 else 0.0
        subject_results[subject] = {
            "data_num": sub_total,
            "correct": sub_correct,
            "wrong": sub_total - sub_correct,
            "accuracy": round(sub_acc, 2)
        }
        total_correct += sub_correct
        total_samples += sub_total
        print(f"--> {subject}: {sub_correct}/{sub_total} ({sub_acc:.2f}%)")

    total_time = time.time() - start_time
    peak_vram_gb = 0.0
    if torch.cuda.is_available():
        peak_vram_gb = torch.cuda.max_memory_allocated() / (1024 ** 3)

    # Calculate overall macro average
    if len(subject_results) > 0:
        overall_macro_avg = sum(s["accuracy"] for s in subject_results.values()) / len(subject_results)
    else:
        overall_macro_avg = 0.0

    summary = {
        "model_path": args.model_path,
        "model_revision": args.model_revision,
        "dataset_revision": args.dataset_revision,
        "backend": backend_choice,
        "total_samples": total_samples,
        "total_correct": total_correct,
        "overall_macro_average": round(overall_macro_avg, 2),
        "official_score": 67.4,
        "gap": round(overall_macro_avg - 67.4, 2),
        "total_runtime_seconds": round(total_time, 2),
        "peak_vram_gb": round(peak_vram_gb, 2),
        "subjects": subject_results
    }

    # Save outputs
    raw_pred_path = os.path.join(args.output_dir, "raw_predictions.jsonl")
    with open(raw_pred_path, "w", encoding="utf-8") as f:
        for item in all_predictions:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    summary_path = os.path.join(args.output_dir, "summary_results.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 50)
    print(f"EVALUATION COMPLETE")
    print(f"Total Samples: {total_samples}")
    print(f"Total Correct: {total_correct}")
    print(f"Overall Score (Macro Average): {overall_macro_avg:.2f}% (Official: 67.4%, Gap: {summary['gap']:+.2f}%)")
    print(f"Total Runtime: {total_time:.2f}s | Peak VRAM: {peak_vram_gb:.2f} GB")
    print(f"Saved raw predictions to: {raw_pred_path}")
    print(f"Saved summary to: {summary_path}")
    print("=" * 50)


if __name__ == "__main__":
    main()
