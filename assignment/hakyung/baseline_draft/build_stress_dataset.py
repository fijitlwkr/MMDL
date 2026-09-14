"""
Step 2 - Group B (stress sanity test) 샘플 선정.
Group A(mc-only, 과목당 1문항)는 "환경이 도는가"만 확인하므로,
max_model_len=9048 truncation, 다중 이미지 처리, open-ended 경로는 우연히 걸리지 않으면 검증되지 않음.

선정 기준 3가지:
  - 이미지 개수가 가장 많은 문항 top-N (전체 900개 대상, 계산 가벼움)
  - open-ended 문항 top-N (전체 900개 대상, question_type != multiple-choice)
  - 입력이 실제로 가장 긴 문항 top-N: 문자 길이만으로는 이미지 토큰 수를 반영하지 못하므로,
    ①문자 길이(질문+옵션) 상위 후보(--token-shortlist-size)만 추린 뒤
    ②그 후보에 한해 실제 AutoProcessor(revision 고정)로 input_ids 길이를 계산해 top-N 선정.
    (이전에 "전체 900문항 중 최대 입력 약 5,627 토큰"을 측정했던 것과 같은 방식)

선정된 문항만 이미지까지 저장해서 별도 jsonl로 만든다.
"""
import argparse
import json
import os
import string

from datasets import load_dataset

from build_dataset import (
    DATASET_NAME,
    DATASET_REVISION,
    SUBJECTS,
    build_record,
    parse_options,
    strip_image_placeholders,
)

MODEL_NAME = "Qwen/Qwen3-VL-4B-Instruct"
MODEL_REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"
MIN_PIXELS = 1280 * 28 * 28
MAX_PIXELS = 5120 * 28 * 28


def _messages_for_token_count(row):
    """디스크에 이미지를 저장하지 않고, PIL 이미지를 process_vision_info에 직접 넘겨 토큰 수만 계산."""
    options = parse_options(row.get("options"))
    letters = list(string.ascii_uppercase)
    options_dict = {letters[i]: str(o) for i, o in enumerate(options)}
    question = strip_image_placeholders(row.get("question", ""))

    prompt = f"Question: {question}\n"
    if options_dict:
        prompt += "Options:\n"
        for k, v in options_dict.items():
            prompt += f"{k}. {v}\n"
        prompt += "Please select the correct answer from the options above. \n"
    prompt = prompt.rstrip()

    content = []
    for i in range(1, 8):
        img = row.get(f"image_{i}")
        if img is not None:
            content.append({"type": "image", "image": img, "min_pixels": MIN_PIXELS, "max_pixels": MAX_PIXELS})
    content.append({"type": "text", "text": prompt})
    return [{"role": "user", "content": content}]


def compute_token_length(row, processor):
    """build_mmmu_prompt()와 동일한 구조로 실제 processor를 통과시켜 input_ids 길이를 구함."""
    from qwen_vl_utils import process_vision_info

    messages = _messages_for_token_count(row)
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs, video_kwargs = process_vision_info(
        messages,
        image_patch_size=processor.image_processor.patch_size,
        return_video_kwargs=True,
        return_video_metadata=True,
    )
    inputs = processor(text=[text], images=image_inputs, videos=video_inputs, return_tensors="pt", **video_kwargs)
    return int(inputs["input_ids"].shape[-1])


def scan_and_select(top_n, token_shortlist_size):
    candidates = []
    for subject in SUBJECTS:
        ds = load_dataset(DATASET_NAME, subject, split="validation", revision=DATASET_REVISION)
        for row in ds:
            n_images = sum(1 for i in range(1, 8) if row.get(f"image_{i}") is not None)
            options = parse_options(row.get("options"))
            text_len_chars = len(row.get("question", "")) + sum(len(str(o)) for o in options)
            candidates.append({
                "subject": subject,
                "row": row,
                "n_images": n_images,
                "text_len_chars": text_len_chars,
                "token_len": None,
                "question_type": row.get("question_type"),
            })
        print(f"[1차 스캔] {subject}: {len(ds)}문항 (문자 길이/이미지 개수만, 가벼움)")

    by_images_full = sorted(candidates, key=lambda c: c["n_images"], reverse=True)[:top_n]
    open_ended_full = [c for c in candidates if c["question_type"] != "multiple-choice"][:top_n]

    # 문자 길이 상위 후보만 추려서 실제 토큰 길이를 계산 (900개 전부 processor에 돌리면 느림)
    by_chars_shortlist = sorted(candidates, key=lambda c: c["text_len_chars"], reverse=True)[:token_shortlist_size]

    print(f"\n[2차 스캔] 실제 processor 토큰 길이 계산 중 (문자 길이 상위 {len(by_chars_shortlist)}건만)...")
    from transformers import AutoProcessor
    processor = AutoProcessor.from_pretrained(MODEL_NAME, revision=MODEL_REVISION)
    for c in by_chars_shortlist:
        c["token_len"] = compute_token_length(c["row"], processor)
        print(f"  - [{c['subject']}] chars={c['text_len_chars']} -> 실제 tokens={c['token_len']}")

    by_tokens_top = sorted(by_chars_shortlist, key=lambda c: c["token_len"], reverse=True)[:top_n]

    selected = {}
    for c in by_images_full + by_tokens_top + open_ended_full:
        key = (c["subject"], c["row"].get("id", c["row"].get("index")))
        selected[key] = c

    return list(selected.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-n", type=int, default=2, help="각 기준(이미지多/실제토큰長/open-ended)별 선정 개수")
    ap.add_argument("--token-shortlist-size", type=int, default=20,
                     help="실제 processor 토큰 계산을 적용할 문자-길이 상위 후보 수")
    ap.add_argument("--out", type=str, default="data/mmmu_stress.jsonl")
    ap.add_argument("--img-dir", type=str, default="data/images_stress")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    os.makedirs(args.img_dir, exist_ok=True)

    selected = scan_and_select(args.top_n, args.token_shortlist_size)
    print(f"\n선정된 stress 샘플 수: {len(selected)}건 (중복 제거 후)")

    with open(args.out, "w", encoding="utf-8") as f:
        for c in selected:
            rec = build_record(c["row"], c["subject"], args.img_dir)
            rec["_stress_meta"] = {
                "n_images": c["n_images"],
                "text_len_chars": c["text_len_chars"],
                "token_len": c["token_len"],  # 숏리스트에 없었으면 None (이미지多/open-ended 기준으로만 선정된 경우)
                "question_type": c["question_type"],
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            token_display = c["token_len"] if c["token_len"] is not None else "N/A(숏리스트 미포함)"
            print(f"  - {rec['uid']}: images={c['n_images']}, chars={c['text_len_chars']}, "
                  f"tokens={token_display}, type={c['question_type']}")

    print(f"\n저장 완료 -> {args.out}")


if __name__ == "__main__":
    main()
