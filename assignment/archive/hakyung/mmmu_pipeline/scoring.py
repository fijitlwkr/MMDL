import ast
import json
import re
from collections import defaultdict
from pathlib import Path


def _maybe_literal(value):
    if not isinstance(value, str):
        return value
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return value
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value
    return parsed if isinstance(parsed, list) else value


def parse_multi_choice_response(response, choices, index_to_answer):
    response = str(response)
    for char in [",", ".", "!", "?", ";", ":", "'"]:
        response = response.strip(char)
    response = " " + response + " "
    candidates = []
    index_answer = True
    bracketed = False
    for choice in choices:
        if f"({choice})" in response:
            candidates.append(choice)
            bracketed = True
    if not candidates:
        for choice in choices:
            if f" {choice} " in response:
                candidates.append(choice)
    if not candidates and len(response.split()) > 5:
        for index, answer in index_to_answer.items():
            if str(answer).lower() in response.lower():
                candidates.append(index)
                index_answer = False
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if index_answer:
        pattern = (lambda item: f"({item})") if bracketed else (lambda item: f" {item} ")
        return max(candidates, key=lambda item: response.rfind(pattern(item)))
    lowered = response.lower()
    return max(candidates, key=lambda item: lowered.rfind(str(index_to_answer[item]).lower()))


def _is_number(value):
    try:
        float(str(value).replace(",", ""))
        return True
    except (ValueError, TypeError):
        return False


def _normalize(value):
    value = str(value).strip()
    if _is_number(value):
        return [round(float(value.replace(",", "")), 2)]
    value = value.lower()
    return [" " + value, value + " "] if len(value) == 1 else [value]


def parse_open_response(response):
    text = str(response).strip().strip(".").lower()
    subresponses = re.split(r"\.\s(?=[A-Z])|\n", text)
    indicators = ["could be ", "so ", "is ", "thus ", "therefore ", "final ", "answer ", "result "]
    key_responses = []
    for index, item in enumerate(subresponses):
        local_indicators = indicators + (["="] if index == len(subresponses) - 1 else [])
        tails = [item.split(indicator)[-1].strip() for indicator in local_indicators if indicator in item]
        tails = [tail for tail in tails if tail not in [":", ",", ".", "!", "?", ";", "'"]]
        if tails:
            key_responses.append(min(tails, key=len))
    if not key_responses:
        key_responses = [text]
    candidates = list(key_responses)
    number_patterns = [
        r"-?\b\d{1,3}(?:,\d{3})+\b",
        r"-?\d+(?:\.\d+)?[eE][+-]?\d+",
        r"-?(?:\d+\.\d+|\.\d+|\d+\b)(?![eE][+-]?\d+)(?![,\d])",
    ]
    for item in key_responses:
        for pattern in number_patterns:
            candidates.extend(re.findall(pattern, item))
    normalized = []
    for candidate in candidates:
        normalized.extend(_normalize(candidate))
    return list(set(normalized))


def _score_open(gold, predictions):
    answers = gold if isinstance(gold, list) else [gold]
    normalized_answers = []
    for answer in answers:
        normalized_answers.extend(_normalize(answer))
    for prediction in predictions:
        if isinstance(prediction, str):
            if any(isinstance(answer, str) and answer in prediction for answer in normalized_answers):
                return True
        elif prediction in normalized_answers:
            return True
    return False


def score_generation(row):
    # Preserve raw_text verbatim; only the parser view drops a possible thinking prefix.
    parser_text = str(row.get("raw_text", "")).split("</think>")[-1].strip()
    gold = _maybe_literal(row.get("answer"))
    if row.get("question_type", "multiple-choice") == "multiple-choice":
        options = row.get("options", {})
        parsed = parse_multi_choice_response(parser_text, list(options), options)
        parse_failure = parsed is None
        correct = False if parse_failure else (parsed in gold if isinstance(gold, list) else parsed == gold)
    else:
        # The official open parser can interpret arbitrary non-empty text. Empty generation is its only
        # structurally detectable parse failure; semantic mismatch is an ordinary incorrect answer.
        parse_failure = not bool(parser_text)
        parsed = [] if parse_failure else parse_open_response(parser_text)
        correct = False if parse_failure else _score_open(gold, parsed)
    return parsed, bool(correct), bool(parse_failure)


def evaluate(rows):
    per_subject = defaultdict(list)
    details = []
    for row in rows:
        parsed, correct, parse_failure = score_generation(row)
        row["parse_failure"] = parse_failure
        per_subject[row["subject"]].append((correct, parse_failure))
        details.append({
            "question_id": row["question_id"],
            "subject": row["subject"],
            "parsed_prediction": parsed,
            "correct": correct,
            "parse_failure": parse_failure,
        })

    subject_results = {}
    for subject in sorted(per_subject):
        values = per_subject[subject]
        count = len(values)
        correct_count = sum(correct for correct, _ in values)
        failure_count = sum(failed for _, failed in values)
        subject_results[subject] = {
            "n": count,
            "correct": correct_count,
            "accuracy": correct_count / count,
            "parse_failures": failure_count,
            "parse_failure_rate": failure_count / count,
        }
    macro_accuracy = sum(item["accuracy"] for item in subject_results.values()) / len(subject_results)
    macro_parse_failure_rate = (
        sum(item["parse_failure_rate"] for item in subject_results.values()) / len(subject_results)
    )
    return {
        "n_total": len(rows),
        "n_subjects": len(subject_results),
        "subject_results": subject_results,
        "macro_accuracy": macro_accuracy,
        "macro_parse_failure_rate": macro_parse_failure_rate,
        "parse_failure_count": sum(item["parse_failures"] for item in subject_results.values()),
        "details": details,
    }


def write_results(result, json_path, markdown_path):
    Path(json_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "| No. | Subject | Data Num | Acc | Parse Failure Rate |",
        "|---|---|---|---|---|",
    ]
    for number, (subject, item) in enumerate(result["subject_results"].items(), start=1):
        lines.append(
            f"| {number} | {subject} | {item['n']} | {item['accuracy'] * 100:.1f} | "
            f"{item['parse_failure_rate'] * 100:.1f} |"
        )
    lines.append(
        f"| | **Overall (macro avg)** | **{result['n_total']}** | "
        f"**{result['macro_accuracy'] * 100:.2f}** | **{result['macro_parse_failure_rate'] * 100:.2f}** |"
    )
    Path(markdown_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
