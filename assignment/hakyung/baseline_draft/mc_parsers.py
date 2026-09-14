"""
Step 2 - 4단계: 파서 비교 실험.
- Parser A: VLMEvalKit / Qwen3-VL 공식 run_mmmu.py의 can_infer (규칙 단계만, judge 제외)
- Parser B: MMMU 원저자 공식 레포(MMMU-Benchmark/MMMU, commit bb0b95a945998d91dfef37e969e07d49d1139438)의
            mmmu/utils/eval_utils.py::parse_multi_choice_response (규칙만, 실패 시 원래는 random.choice이나
            비교 실험에서는 "실패"로 취급하기 위해 None 반환하도록 일부 수정)
            검증 방법: 아래 URL은 git commit SHA가 경로에 고정되어 있어 언제 다시 열어도 항상 동일한
            내용을 반환함(브랜치 head 참조가 아님) — 이 파일의 로직과 대조해서 재현성 검증 가능:
            https://raw.githubusercontent.com/MMMU-Benchmark/MMMU/bb0b95a945998d91dfef37e969e07d49d1139438/mmmu/utils/eval_utils.py

목적: "누가 더 정확한가"가 아니라 "규칙 기반 단계에서 서로 다른 문항에서 실패하는가"를 확인.
"""
import argparse
import json
import string

import numpy as np


# ------------------------------------------------------------------
# Parser A: VLMEvalKit 방식 (Qwen3-VL 공식 run_mmmu.py/eval_utils.py 원본 로직)
# ------------------------------------------------------------------
def can_infer_option(answer, choices):
    if "Failed to obtain answer via API" in answer:
        return False

    reject_to_answer = [
        "Sorry, I can't help with images of people yet.",
        "I can't process this file.",
        "I'm sorry, but without the image provided",
        "Cannot determine the answer",
    ]
    for err in reject_to_answer:
        if err in answer:
            return "Z"

    def count_choice(splits, choice_set, prefix="", suffix=""):
        return sum(1 for c in choice_set if prefix + c + suffix in splits)

    answer_mod = answer
    for c in ".()[],:;!*#{}":
        answer_mod = answer_mod.replace(c, " ")

    splits = [x.strip() for x in answer_mod.split()]
    count = count_choice(splits, choices)

    if count == 1:
        for ch in choices:
            if "A" in splits and len(splits) > 3:
                return False
            if ch in splits:
                return ch
    elif count == 0 and count_choice(splits, {"Z", ""}) == 1:
        return "Z"
    return False


def can_infer_text(answer, choices):
    answer = answer.lower()
    cands = [k for k, v in choices.items() if str(v).lower() in answer]
    return cands[0] if len(cands) == 1 else False


def can_infer_vlmevalkit(answer, choices):
    answer = str(answer)
    ret = can_infer_option(answer, choices)
    return ret if ret else can_infer_text(answer, choices)


# ------------------------------------------------------------------
# Parser B: MMMU 공식 레포 방식 (MMMU-Benchmark/MMMU/mmmu/utils/eval_utils.py 기반)
# 원본과의 차이: 후보가 0개일 때 원본은 random.choice로 즉시 확정하지만,
#                이 비교 실험에서는 "규칙 기반 실패"를 측정하기 위해 None을 반환하도록 수정.
# ------------------------------------------------------------------
def parse_multi_choice_response_official(response, all_choices, index2ans):
    for ch in [",", ".", "!", "?", ";", ":", "'"]:
        response = response.strip(ch)
    response = " " + response + " "

    index_ans = True
    ans_with_brack = False
    candidates = []

    for choice in all_choices:
        if f"({choice})" in response:
            candidates.append(choice)
            ans_with_brack = True

    if not candidates:
        for choice in all_choices:
            if f" {choice} " in response:
                candidates.append(choice)

    if not candidates and len(response.split()) > 5:
        for idx, ans in index2ans.items():
            if str(ans).lower() in response.lower():
                candidates.append(idx)
                index_ans = False

    if not candidates:
        return None  # 원본: random.choice(all_choices)

    if len(candidates) > 1:
        starts = []
        if index_ans:
            for c in candidates:
                starts.append(response.rfind(f"({c})") if ans_with_brack else response.rfind(f" {c} "))
        else:
            for c in candidates:
                starts.append(response.lower().rfind(str(index2ans[c]).lower()))
        return candidates[int(np.argmax(starts))]

    return candidates[0]


# ------------------------------------------------------------------
# 비교 루틴
# ------------------------------------------------------------------
def compare(preds_path):
    rows = [json.loads(line) for line in open(preds_path, encoding="utf-8")]
    rows = [r for r in rows if r.get("question_type", "multiple-choice") == "multiple-choice"]

    fail_a, fail_b = [], []
    correct_a, correct_b = 0, 0
    extracted_a, extracted_b = 0, 0
    disagreements = []

    for r in rows:
        choices = r["options"]
        gt = r.get("answer")
        # </think> 이후 최종 답만 사용 (run_mmmu.py의 response_final과 동일 처리)
        text = r.get("prediction_final", r.get("prediction_raw", ""))

        a = can_infer_vlmevalkit(text, choices)
        a_ok = bool(a) and a != "Z"
        if not a_ok:
            fail_a.append(r["uid"])
        else:
            extracted_a += 1
            if a == gt:
                correct_a += 1

        b = parse_multi_choice_response_official(text, list(choices.keys()), choices)
        b_ok = b is not None
        if not b_ok:
            fail_b.append(r["uid"])
        else:
            extracted_b += 1
            if b == gt:
                correct_b += 1

        if a_ok and b_ok and a != b:
            disagreements.append({"uid": r["uid"], "vlmevalkit": a, "mmmu_official": b, "gt": gt})

    n = len(rows)
    fail_a_set, fail_b_set = set(fail_a), set(fail_b)
    both = fail_a_set & fail_b_set
    only_a = fail_a_set - fail_b_set
    only_b = fail_b_set - fail_a_set

    print(f"평가 대상 (multiple-choice만): {n}문항")
    print("--- 규칙 기반 실패율 (보조 지표) ---")
    print(f"VLMEvalKit 규칙 실패 : {len(fail_a)}건 ({len(fail_a)/n:.1%})")
    print(f"MMMU 공식 규칙 실패  : {len(fail_b)}건 ({len(fail_b)/n:.1%})")
    print(f"  - 둘 다 실패                 : {len(both)}건")
    print(f"  - VLMEvalKit만 실패(MMMU 성공): {len(only_a)}건")
    print(f"  - MMMU만 실패(VLMEvalKit 성공): {len(only_b)}건")
    print("--- GT 대비 정확도 (핵심 지표) ---")
    print(f"VLMEvalKit: extraction_failure={len(fail_a)}/{n}, "
          f"extracted_accuracy={correct_a}/{extracted_a}"
          f"{f' ({correct_a/extracted_a:.1%})' if extracted_a else ''}")
    print(f"MMMU 공식 : extraction_failure={len(fail_b)}/{n}, "
          f"extracted_accuracy={correct_b}/{extracted_b}"
          f"{f' ({correct_b/extracted_b:.1%})' if extracted_b else ''}")
    print(f"A/B 둘 다 추출 성공했지만 서로 다른 답을 낸 문항: {len(disagreements)}건")

    return {
        "n": n,
        "vlmevalkit": {
            "fail_uids": sorted(fail_a_set),
            "extracted": extracted_a,
            "correct": correct_a,
        },
        "mmmu_official": {
            "fail_uids": sorted(fail_b_set),
            "extracted": extracted_b,
            "correct": correct_b,
        },
        "both_fail_uids": sorted(both),
        "only_vlmevalkit_fail_uids": sorted(only_a),
        "only_mmmu_fail_uids": sorted(only_b),
        "disagreements": disagreements,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", default="data/predictions_light.jsonl")
    ap.add_argument("--out", default="data/parser_compare.json")
    args = ap.parse_args()

    result = compare(args.preds)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n상세 결과 저장 -> {args.out}")


if __name__ == "__main__":
    main()
