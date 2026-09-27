#!/usr/bin/env python3
"""Analyze retry behavior from the completed MMMU GPT-judge run.

This script is read-only with respect to the original experiment artifacts. It
only writes retry_analysis.json and retry_analysis.md.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CALLS = SCRIPT_DIR / "outputs" / "judge_calls.jsonl"
DEFAULT_SUMMARY = SCRIPT_DIR / "outputs" / "judge_summary.json"
DEFAULT_PREDICTIONS = (
    SCRIPT_DIR.parent / "exp0_baseline" / "outputs" / "predictions.jsonl"
)
DEFAULT_JSON_OUTPUT = SCRIPT_DIR / "outputs" / "retry_analysis.json"
DEFAULT_MARKDOWN_OUTPUT = SCRIPT_DIR / "outputs" / "retry_analysis.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judge-calls", type=Path, default=DEFAULT_CALLS)
    parser.add_argument("--judge-summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            records.append(value)
    return records


def require_keys(record: dict[str, Any], keys: set[str], context: str) -> None:
    missing = sorted(keys - record.keys())
    if missing:
        raise ValueError(f"{context}: missing keys: {', '.join(missing)}")


def percentile(values: list[int], fraction: float) -> float:
    """Return a linearly interpolated percentile (same convention as numpy)."""
    if not values:
        raise ValueError("cannot calculate a percentile of an empty sequence")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def describe_tokens(values: list[int]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p75": percentile(values, 0.75),
        "p90": percentile(values, 0.90),
        "max": max(values),
    }


def rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def fmt_number(value: float | int) -> str:
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def markdown_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return lines


def main() -> None:
    args = parse_args()
    calls = read_jsonl(args.judge_calls)
    predictions = read_jsonl(args.predictions)
    summary = json.loads(args.judge_summary.read_text(encoding="utf-8"))

    if not isinstance(summary, dict) or not isinstance(summary.get("items"), list):
        raise ValueError("judge_summary.json must be an object containing an items list")

    attempt_records: list[dict[str, Any]] = []
    retry_events: list[dict[str, Any]] = []
    fallback_events: list[dict[str, Any]] = []
    for index, record in enumerate(calls, start=1):
        require_keys(record, {"question_id", "status"}, f"judge_calls line {index}")
        if "attempt" in record:
            require_keys(
                record,
                {
                    "attempt",
                    "prompt_tokens",
                    "completion_tokens",
                    "call_cost_usd",
                    "cumulative_cost_usd",
                },
                f"judge_calls attempt line {index}",
            )
            attempt_records.append(record)
        elif record["status"] == "retry_scheduled":
            require_keys(record, {"next_attempt", "reason"}, f"retry event line {index}")
            retry_events.append(record)
        elif record["status"] == "final_fallback_incorrect":
            fallback_events.append(record)

    by_question: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in attempt_records:
        by_question[str(record["question_id"])].append(record)
    for question_id, attempts in by_question.items():
        attempts.sort(key=lambda item: int(item["attempt"]))
        actual_numbers = [int(item["attempt"]) for item in attempts]
        expected_numbers = list(range(1, len(attempts) + 1))
        if actual_numbers != expected_numbers:
            raise ValueError(
                f"{question_id}: non-contiguous attempts {actual_numbers}; "
                f"expected {expected_numbers}"
            )

    expected_items = int(summary["expected_item_count"])
    completed_items = int(summary["completed_item_count"])
    if len(by_question) != expected_items or completed_items != expected_items:
        raise ValueError(
            "judge item count mismatch: "
            f"log={len(by_question)}, completed={completed_items}, expected={expected_items}"
        )
    if len(attempt_records) != int(summary["api_attempt_count"]):
        raise ValueError(
            "API attempt count mismatch: "
            f"log={len(attempt_records)}, summary={summary['api_attempt_count']}"
        )

    attempt_histogram = Counter(len(attempts) for attempts in by_question.values())
    retry_reason_counts = Counter(str(event["reason"]) for event in retry_events)
    retry_reasons_by_question: dict[str, list[str]] = defaultdict(list)
    for event in retry_events:
        retry_reasons_by_question[str(event["question_id"])].append(str(event["reason"]))
    retry_item_ids = {
        question_id for question_id, attempts in by_question.items() if len(attempts) > 1
    }
    expected_retry_event_count = sum(len(attempts) - 1 for attempts in by_question.values())
    if len(retry_events) != expected_retry_event_count:
        raise ValueError(
            "retry event count mismatch: "
            f"events={len(retry_events)}, expected from attempts={expected_retry_event_count}"
        )

    last_attempts = {
        question_id: attempts[-1] for question_id, attempts in by_question.items()
    }
    final_failure_ids = sorted(
        question_id
        for question_id, record in last_attempts.items()
        if record["status"] != "success"
    )
    summary_failure_ids = sorted(
        str(item["question_id"])
        for item in summary["items"]
        if item.get("status") == "judge_failed_final"
    )
    fallback_ids = sorted(str(event["question_id"]) for event in fallback_events)
    if final_failure_ids != summary_failure_ids or final_failure_ids != fallback_ids:
        raise ValueError(
            "final failure ID mismatch among last attempts, summary items, and fallback events"
        )

    prediction_by_id: dict[str, dict[str, Any]] = {}
    for index, prediction in enumerate(predictions, start=1):
        require_keys(
            prediction,
            {"question_id", "subject", "finish_reason"},
            f"predictions line {index}",
        )
        question_id = str(prediction["question_id"])
        if question_id in prediction_by_id:
            raise ValueError(f"duplicate prediction question_id: {question_id}")
        prediction_by_id[question_id] = prediction

    missing_predictions = sorted(set(by_question) - prediction_by_id.keys())
    if missing_predictions:
        raise ValueError(f"judge IDs absent from predictions: {missing_predictions}")

    per_question_attempts = [
        {
            "question_id": question_id,
            "subject": str(prediction_by_id[question_id]["subject"]),
            "attempts": len(by_question[question_id]),
            "attempt_statuses": [
                str(record["status"]) for record in by_question[question_id]
            ],
            "first_prompt_tokens": int(by_question[question_id][0]["prompt_tokens"]),
            "retry_reasons": retry_reasons_by_question.get(question_id, []),
        }
        for question_id in sorted(by_question)
    ]

    finish_reason_counts = Counter(
        str(prediction_by_id[question_id]["finish_reason"])
        for question_id in final_failure_ids
    )
    failure_details = [
        {
            "question_id": question_id,
            "subject": str(prediction_by_id[question_id]["subject"]),
            "finish_reason": str(prediction_by_id[question_id]["finish_reason"]),
            "attempts": len(by_question[question_id]),
            "last_status": str(last_attempts[question_id]["status"]),
        }
        for question_id in final_failure_ids
    ]

    subject_totals = Counter(
        str(prediction_by_id[question_id]["subject"]) for question_id in by_question
    )
    subject_retry_items = Counter(
        str(prediction_by_id[question_id]["subject"]) for question_id in retry_item_ids
    )
    subject_extra_attempts = Counter(
        {
            subject: sum(
                len(by_question[question_id]) - 1
                for question_id in by_question
                if str(prediction_by_id[question_id]["subject"]) == subject
            )
            for subject in subject_totals
        }
    )
    subject_rows = [
        {
            "subject": subject,
            "judged_items": subject_totals[subject],
            "retried_items": subject_retry_items[subject],
            "retry_item_rate": rate(subject_retry_items[subject], subject_totals[subject]),
            "extra_attempts": subject_extra_attempts[subject],
        }
        for subject in sorted(
            subject_totals,
            key=lambda name: (
                -subject_retry_items[name],
                -subject_extra_attempts[name],
                name,
            ),
        )
    ]

    prompt_tokens = {
        question_id: int(attempts[0]["prompt_tokens"])
        for question_id, attempts in by_question.items()
    }
    retried_token_values = [prompt_tokens[item] for item in retry_item_ids]
    single_token_values = [
        tokens for item, tokens in prompt_tokens.items() if item not in retry_item_ids
    ]
    longest_count = math.ceil(len(prompt_tokens) * 0.25)
    ordered_by_tokens = sorted(prompt_tokens, key=lambda item: prompt_tokens[item], reverse=True)
    longest_ids = set(ordered_by_tokens[:longest_count])
    remaining_ids = set(ordered_by_tokens[longest_count:])
    longest_retry_count = len(longest_ids & retry_item_ids)
    remaining_retry_count = len(remaining_ids & retry_item_ids)
    longest_items = [
        {
            "question_id": question_id,
            "subject": str(prediction_by_id[question_id]["subject"]),
            "prompt_tokens": prompt_tokens[question_id],
            "attempts": len(by_question[question_id]),
            "retried": question_id in retry_item_ids,
        }
        for question_id in ordered_by_tokens[:10]
    ]

    length_failures = finish_reason_counts.get("length", 0)
    length_failure_rate = rate(length_failures, len(final_failure_ids))
    analysis: dict[str, Any] = {
        "source_files": {
            "judge_calls": str(args.judge_calls),
            "judge_summary": str(args.judge_summary),
            "predictions": str(args.predictions),
        },
        "schema_observed": {
            "attempt_record_keys": sorted(
                set().union(*(record.keys() for record in attempt_records))
            ),
            "retry_record_keys": sorted(
                set().union(*(record.keys() for record in retry_events))
            ),
            "attempt_statuses": dict(sorted(Counter(
                str(record["status"]) for record in attempt_records
            ).items())),
        },
        "validation": {
            "expected_items": expected_items,
            "completed_items_summary": completed_items,
            "unique_questions_in_calls": len(by_question),
            "api_attempts_summary": int(summary["api_attempt_count"]),
            "api_attempt_records": len(attempt_records),
            "final_failures_last_attempt": len(final_failure_ids),
            "final_failures_summary": len(summary_failure_ids),
            "final_fallback_events": len(fallback_ids),
            "all_counts_and_ids_match": True,
        },
        "retry_analysis": {
            "items_with_retry": len(retry_item_ids),
            "retry_events": len(retry_events),
            "reason_counts": dict(sorted(retry_reason_counts.items())),
            "attempt_histogram": {
                str(attempts): count for attempts, count in sorted(attempt_histogram.items())
            },
            "prompt_tokens": {
                "single_attempt_items": describe_tokens(single_token_values),
                "retried_items": describe_tokens(retried_token_values),
                "longest_quartile": {
                    "definition": f"top {longest_count} of {len(prompt_tokens)} by first-attempt prompt_tokens",
                    "items": len(longest_ids),
                    "retried_items": longest_retry_count,
                    "retry_rate": rate(longest_retry_count, len(longest_ids)),
                },
                "remaining_items": {
                    "items": len(remaining_ids),
                    "retried_items": remaining_retry_count,
                    "retry_rate": rate(remaining_retry_count, len(remaining_ids)),
                },
                "ten_longest_items": longest_items,
            },
            "by_subject": subject_rows,
            "per_question": per_question_attempts,
        },
        "final_failures": {
            "count": len(final_failure_ids),
            "question_ids": final_failure_ids,
            "finish_reason_counts": dict(sorted(finish_reason_counts.items())),
            "items": failure_details,
            "length_count": length_failures,
            "length_rate": length_failure_rate,
        },
    }

    retry_reasons_rows = [
        [reason, count, f"{rate(count, len(retry_events)):.2%}"]
        for reason, count in sorted(retry_reason_counts.items())
    ]
    attempt_rows = [
        [attempts, count, f"{rate(count, len(by_question)):.2%}"]
        for attempts, count in sorted(attempt_histogram.items())
    ]
    finish_rows = [
        [reason, count, f"{rate(count, len(final_failure_ids)):.2%}"]
        for reason, count in sorted(finish_reason_counts.items())
    ]
    failure_rows = [
        [item["question_id"], item["subject"], item["finish_reason"]]
        for item in failure_details
    ]
    subject_table_rows = [
        [
            item["subject"],
            item["judged_items"],
            item["retried_items"],
            f"{item['retry_item_rate']:.2%}",
            item["extra_attempts"],
        ]
        for item in subject_rows
        if item["retried_items"]
    ]
    longest_rows = [
        [
            item["question_id"],
            item["subject"],
            item["prompt_tokens"],
            item["attempts"],
        ]
        for item in longest_items
    ]
    per_question_rows = [
        [
            item["question_id"],
            item["subject"],
            item["attempts"],
            item["first_prompt_tokens"],
            ", ".join(item["attempt_statuses"]),
            "; ".join(item["retry_reasons"]) or "—",
        ]
        for item in per_question_attempts
    ]

    single_stats = analysis["retry_analysis"]["prompt_tokens"]["single_attempt_items"]
    retried_stats = analysis["retry_analysis"]["prompt_tokens"]["retried_items"]
    longest_stats = analysis["retry_analysis"]["prompt_tokens"]["longest_quartile"]
    remaining_stats = analysis["retry_analysis"]["prompt_tokens"]["remaining_items"]
    markdown = [
        "# GPT-judge retry analysis",
        "",
        "기존 GPU/API 실행 결과를 다시 호출하지 않고 "
        "`judge_calls.jsonl`, `judge_summary.json`, `predictions.jsonl`만 읽어 분석했다.",
        "",
        "## 무결성 검증",
        "",
        f"- judge 대상: 로그 {len(by_question)}/{expected_items}, summary 완료 "
        f"{completed_items}/{expected_items}",
        f"- API 시도: 로그 {len(attempt_records)}회, summary "
        f"{summary['api_attempt_count']}회",
        f"- 최종 실패: 마지막 시도 기준 {len(final_failure_ids)}개, summary "
        f"{len(summary_failure_ids)}개, `final_fallback_incorrect` 이벤트 "
        f"{len(fallback_ids)}개 (ID까지 모두 일치)",
        "",
        "### 실제 로그 필드 해석",
        "",
        "- API 시도 레코드는 `question_id`, `attempt`, `status`, `prompt_tokens`, "
        "`completion_tokens`, `call_cost_usd`, `cumulative_cost_usd` 등을 가진다.",
        "- 별도 성공 boolean이나 `error_type` 키는 없고, 성공/실패는 `status`로 "
        "판별한다. 이번 API 시도 status는 `success`와 `invalid_response`뿐이다.",
        "- 재시도 이벤트는 `status=retry_scheduled`, `next_attempt`, `reason`으로 "
        "기록된다.",
        "",
        "## 재시도 사유 분포",
        "",
        *markdown_table(["기록된 reason", "재시도 이벤트", "비율"], retry_reasons_rows),
        "",
        "이번 실행에서 timeout, HTTP error, rate limit 레코드는 없었다. 기록된 재시도 "
        "53회는 모두 judge가 허용 선택지를 내지 않은 `invalid_response`였으며, "
        "해당 API 응답의 `judge_output`은 전부 `INVALID`, 기록된 reason은 "
        "`judge returned an invalid choice`였다.",
        "",
        "### 문항당 시도 횟수",
        "",
        *markdown_table(["시도 횟수", "문항 수", "86문항 중 비율"], attempt_rows),
        "",
        "## 재시도 집중 조건",
        "",
        *markdown_table(
            ["그룹", "문항", "평균 prompt tok", "중앙값", "p90", "최대"],
            [
                [
                    "1회 시도",
                    single_stats["count"],
                    fmt_number(single_stats["mean"]),
                    fmt_number(single_stats["median"]),
                    fmt_number(single_stats["p90"]),
                    fmt_number(single_stats["max"]),
                ],
                [
                    "재시도 발생",
                    retried_stats["count"],
                    fmt_number(retried_stats["mean"]),
                    fmt_number(retried_stats["median"]),
                    fmt_number(retried_stats["p90"]),
                    fmt_number(retried_stats["max"]),
                ],
            ],
        ),
        "",
        f"- 입력 토큰 최장 25%({longest_stats['items']}문항)의 재시도율은 "
        f"{longest_stats['retry_rate']:.2%}({longest_stats['retried_items']}/"
        f"{longest_stats['items']})이고, 나머지 {remaining_stats['items']}문항은 "
        f"{remaining_stats['retry_rate']:.2%}({remaining_stats['retried_items']}/"
        f"{remaining_stats['items']})였다.",
        f"- 재시도군의 평균/중앙 입력 토큰은 "
        f"{fmt_number(retried_stats['mean'])}/{fmt_number(retried_stats['median'])}, "
        f"단일 시도군은 {fmt_number(single_stats['mean'])}/"
        f"{fmt_number(single_stats['median'])}였다.",
        f"- 관찰: 최장 25%의 재시도율은 나머지 문항의 "
        f"{longest_stats['retry_rate'] / remaining_stats['retry_rate']:.2f}배여서, "
        "이번 표본에서는 재시도가 긴 입력에 뚜렷하게 집중됐다. 이는 관찰적 연관이며 "
        "입력 길이가 원인임을 단독으로 입증하지는 않는다.",
        "",
        "### 재시도가 발생한 과목",
        "",
        *markdown_table(
            ["과목", "judge 문항", "재시도 문항", "재시도율", "추가 호출"],
            subject_table_rows,
        ),
        "",
        "### 입력 토큰 상위 10문항",
        "",
        *markdown_table(["question_id", "과목", "prompt tok", "시도"], longest_rows),
        "",
        "과목별로는 `Energy_and_Power`가 6/10문항으로 재시도 문항 수가 가장 "
        "많았다. `Finance`(3/3), `Materials`(2/2), `Accounting`(1/1)은 비율이 "
        "100%지만 judge 대상 표본 수가 작다.",
        "",
        "## 최종 실패 문항과 finish_reason",
        "",
        *markdown_table(["finish_reason", "문항 수", "최종 실패 중 비율"], finish_rows),
        "",
        *markdown_table(["question_id", "과목", "finish_reason"], failure_rows),
        "",
        "## 결론",
        "",
        f"GPT-judge로도 구제되지 않은 최종 실패 {len(final_failure_ids)}개 중 "
        f"생성 길이 초과(`finish_reason=length`)는 {length_failures}개, "
        f"{length_failure_rate:.2%}였다.",
        "",
        "## 부록: 86문항별 API 시도",
        "",
        *markdown_table(
            ["question_id", "과목", "시도", "첫 prompt tok", "시도 status", "재시도 reason"],
            per_question_rows,
        ),
        "",
    ]

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.markdown_output.write_text("\n".join(markdown), encoding="utf-8")

    print(
        f"validated {len(by_question)} items, {len(attempt_records)} API attempts, "
        f"{len(final_failure_ids)} final failures"
    )
    print(f"wrote {args.json_output}")
    print(f"wrote {args.markdown_output}")


if __name__ == "__main__":
    main()
