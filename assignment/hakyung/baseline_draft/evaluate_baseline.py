"""
MMMU validation 900문항 전체 채점 + 과목별/macro accuracy 집계.

근거:
- assignment_guidance.md: 30개 과목 accuracy + 30과목 macro average 요구.
- MMMU-Benchmark/MMMU commit bb0b95a945998d91dfef37e969e07d49d1139438
  mmmu/utils/eval_utils.py의 parse_multi_choice_response / parse_open_response /
  eval_multi_choice / eval_open 로직을 기반으로 함.

프로젝트 차이:
- official MC parser가 후보를 하나도 찾지 못하면 random.choice()로 답을 강제 생성하지만,
  이 프로젝트에서는 재현성/파서 실패 가시성을 위해 None을 반환하고 오답으로 처리한다.
- open-ended parser/evaluator는 공식 로직을 그대로 따른다.
"""
import argparse
import ast
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np


def _maybe_literal(value):
    """HF answer가 list literal 문자열인 경우만 안전하게 list로 복원."""
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not (s.startswith("[") and s.endswith("]")):
        return value
    try:
        parsed = ast.literal_eval(s)
        return parsed if isinstance(parsed, list) else value
    except (ValueError, SyntaxError):
        return value


# ---------- MMMU official MC parser (random fallback만 제거) ----------
def parse_multi_choice_response(response, all_choices, index2ans):
    response = str(response)
    for char in [",", ".", "!", "?", ";", ":", "'"]:
        response = response.strip(char)
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
        for index, ans in index2ans.items():
            if str(ans).lower() in response.lower():
                candidates.append(index)
                index_ans = False

    if not candidates:
        return None  # official: random.choice(all_choices)

    if len(candidates) > 1:
        start_indexes = []
        if index_ans:
            if ans_with_brack:
                for can in candidates:
                    start_indexes.append(response.rfind(f"({can})"))
            else:
                for can in candidates:
                    start_indexes.append(response.rfind(f" {can} "))
        else:
            for can in candidates:
                start_indexes.append(response.lower().rfind(str(index2ans[can]).lower()))
        return candidates[int(np.argmax(start_indexes))]

    return candidates[0]


# ---------- MMMU official open-ended parser/evaluator ----------
def check_is_number(string):
    try:
        float(str(string).replace(",", ""))
        return True
    except (ValueError, TypeError):
        return False


def normalize_str(string):
    string = str(string).strip()
    if check_is_number(string):
        value = float(string.replace(",", ""))
        return [round(value, 2)]
    string = string.lower()
    if len(string) == 1:
        return [" " + string, string + " "]
    return [string]


def extract_numbers(string):
    pattern_commas = r"-?\b\d{1,3}(?:,\d{3})+\b"
    pattern_scientific = r"-?\d+(?:\.\d+)?[eE][+-]?\d+"
    pattern_simple = r"-?(?:\d+\.\d+|\.\d+|\d+\b)(?![eE][+-]?\d+)(?![,\d])"
    return (
        re.findall(pattern_commas, string)
        + re.findall(pattern_scientific, string)
        + re.findall(pattern_simple, string)
    )


def parse_open_response(response):
    def get_key_subresponses(text):
        text = str(text).strip().strip(".").lower()
        # 공식 코드의 regex/처리 순서를 보존한다.
        sub_responses = re.split(r"\.\s(?=[A-Z])|\n", text)
        indicators = [
            "could be ", "so ", "is ", "thus ", "therefore ",
            "final ", "answer ", "result ",
        ]
        key_responses = []
        for index, resp in enumerate(sub_responses):
            local_indicators = list(indicators)
            if index == len(sub_responses) - 1:
                local_indicators.append("=")
            shortest = None
            for indicator in local_indicators:
                if indicator in resp:
                    tail = resp.split(indicator)[-1].strip()
                    if shortest is None or len(tail) < len(shortest):
                        shortest = tail
            if shortest and shortest.strip() not in [":", ",", ".", "!", "?", ";", "'"]:
                key_responses.append(shortest)
        return key_responses if key_responses else [text]

    key_responses = get_key_subresponses(response)
    pred_list = key_responses.copy()
    for resp in key_responses:
        pred_list.extend(extract_numbers(resp))

    normalized = []
    for pred in pred_list:
        normalized.extend(normalize_str(pred))
    # 공식 코드처럼 중복 제거. 정답 판정은 순서 비의존.
    return list(set(normalized))


def eval_multi_choice(gold_i, pred_i):
    if pred_i is None:
        return False
    if isinstance(gold_i, list):
        return pred_i in gold_i
    return gold_i == pred_i


def eval_open(gold_i, pred_i):
    if isinstance(gold_i, list):
        norm_answers = []
        for answer in gold_i:
            norm_answers.extend(normalize_str(answer))
    else:
        norm_answers = normalize_str(gold_i)

    for pred in pred_i:
        if isinstance(pred, str):
            for norm_ans in norm_answers:
                if isinstance(norm_ans, str) and norm_ans in pred:
                    return True
        else:
            if pred in norm_answers:
                return True
    return False


def score_row(row):
    qtype = row.get("question_type", "multiple-choice")
    text = row.get("prediction_final", row.get("prediction_raw", ""))
    gold = _maybe_literal(row.get("answer"))

    if qtype == "multiple-choice":
        options = row.get("options", {})
        choices = list(options.keys())
        pred = parse_multi_choice_response(text, choices, options)
        hit = eval_multi_choice(gold, pred)
        return pred, hit, pred is None

    pred = parse_open_response(text)
    hit = eval_open(gold, pred)
    return pred, hit, False


def evaluate(preds_path):
    rows = [json.loads(line) for line in open(preds_path, encoding="utf-8")]
    if not rows:
        raise ValueError("prediction 파일이 비어 있습니다.")

    by_subject = defaultdict(list)
    details = []
    mc_failures = []
    type_counts = defaultdict(int)

    for row in rows:
        pred, hit, parse_failed = score_row(row)
        subject = row["subject"]
        qtype = row.get("question_type", "multiple-choice")
        type_counts[qtype] += 1
        by_subject[subject].append(bool(hit))
        if parse_failed:
            mc_failures.append(row["uid"])
        details.append({
            "uid": row["uid"],
            "subject": subject,
            "question_type": qtype,
            "gold": row.get("answer"),
            "parsed_pred": pred,
            "hit": bool(hit),
            "mc_parse_failed": bool(parse_failed),
            "finish_reason": row.get("finish_reason"),
            "n_generated_tokens": row.get("n_generated_tokens"),
        })

    subject_results = {}
    for subject in sorted(by_subject):
        hits = by_subject[subject]
        subject_results[subject] = {
            "n": len(hits),
            "correct": sum(hits),
            "accuracy": sum(hits) / len(hits),
        }

    macro = sum(v["accuracy"] for v in subject_results.values()) / len(subject_results)
    micro = sum(d["hit"] for d in details) / len(details)

    return {
        "n_total": len(details),
        "n_subjects": len(subject_results),
        "question_type_counts": dict(type_counts),
        "mc_parse_failure_count": len(mc_failures),
        "mc_parse_failure_uids": mc_failures,
        "subject_results": subject_results,
        "macro_accuracy": macro,
        "micro_accuracy": micro,
        "macro_equals_micro": abs(macro - micro) < 1e-12,
        "details": details,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", default="data/predictions_val.jsonl")
    ap.add_argument("--out", default="data/eval_val.json")
    args = ap.parse_args()

    result = evaluate(args.preds)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"평가 문항: {result['n_total']} / 과목: {result['n_subjects']}")
    print(f"question_type: {result['question_type_counts']}")
    print(f"MC parser failure: {result['mc_parse_failure_count']}")
    print("\n과목별 accuracy")
    for subject, r in result["subject_results"].items():
        print(f"  {subject:36s} {r['correct']:2d}/{r['n']:2d} = {r['accuracy']*100:6.2f}")
    print(f"\nMacro accuracy: {result['macro_accuracy']*100:.2f}")
    print(f"Micro accuracy: {result['micro_accuracy']*100:.2f}")
    print(f"macro == micro: {result['macro_equals_micro']}")
    print(f"상세 결과 저장 -> {out}")

    if result["n_total"] != 900 or result["n_subjects"] != 30:
        print("[경고] 과제 요구값(900문항, 30과목)과 다릅니다. 최종 제출 점수로 사용하지 마세요.")


if __name__ == "__main__":
    main()
