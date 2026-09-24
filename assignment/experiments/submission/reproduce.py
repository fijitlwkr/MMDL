"""Reproduce the submitted latest-raw scores from saved responses, without an API."""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
from pathlib import Path
import socket
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
RAW_SHA256 = "ef23f0c49d9b1ae6c62b9625fbd52cce474a0c035c1a644cfa737e0967daa313"
PRIMARY = "gpt-4.1-mini-2025-04-14"
COMPARISON = "gpt-4o-mini-2024-07-18"
OUTPUTS = ("scores.json", "item_results.jsonl", "subject_scores.json", "subject_scores.md",
           "changed_items.jsonl", "policy_comparison.jsonl", "comparisons.json")


def load_evaluator(path):
    spec = importlib.util.spec_from_file_location("submission_evaluator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_cache(e, path, rows, items, settings, parsers):
    """Verify all historical gate-on requests, including the 18 no longer needed."""
    saved = e.unique(e.read_rows(path), "Judge cache")
    candidates = [(row, item) for row, item in zip(rows, items)
                  if item["route"] != "auto" or row["finish_reason"] == "length"]
    e.require(set(saved) == {row["id"] for row, _ in candidates}, "Judge cache ID coverage mismatch")
    usage = Counter()
    parsed = {}
    for row, item in candidates:
        record = saved[row["id"]]
        request = e.make_request(row, item, settings, parsers, RAW_SHA256)
        e.require(record.get("request_sha256") == request["request_sha256"] and bool(record.get("received_at")),
                  "Judge request provenance mismatch: " + row["id"])
        response = record["response"]
        usage.update(e.response_usage(response, settings["model"]))
        choices = response.get("choices")
        e.require(isinstance(choices, list) and len(choices) == 1, "Expected one Judge choice")
        choice = choices[0]
        e.require(isinstance(choice.get("message"), dict), "Missing Judge message")
        content, finish = choice["message"].get("content"), choice.get("finish_reason")
        e.require(content is None or isinstance(content, str), "Invalid Judge text")
        e.require(isinstance(finish, str) and bool(finish), "Missing Judge finish_reason")
        answer = parsers.qwen_parse(content or "", item["choices"]) if finish == "stop" else None
        parsed[row["id"]] = {"final_answer": answer, "final_correct": answer == item["gt"] if answer else False,
                              "final_status": "complete_judge" if answer else "extraction_failure"}
    return saved, parsed, dict(usage)


def historical_results(items, parsed):
    results = []
    for item in items:
        route = "judge_length" if item["finish_reason"] == "length" else item["route"]
        result = ({"final_answer": item["auto_answer"], "final_correct": item["auto_answer"] == item["gt"],
                   "final_status": "complete_rule"} if route == "auto" else parsed[item["id"]])
        results.append({**item, "route": route, **result})
    return results


def compact_result(row, final):
    return {**{key: row[key] for key in ("id", "subject", "question_type", "finish_reason", "output_tokens", "gold")},
            "predicted": final["final_answer"], "correct": final["final_correct"],
            "status": final["final_status"], "route": final["route"],
            "reference_visible": final["reference_answer_visible"]}


def reproduce(args):
    e = load_evaluator(args.evaluator)
    out = args.out.resolve()
    sources = {"raw": args.input, "run_metadata": args.metadata, "scoring_config": args.config,
               "judge_4_1_mini": args.judge_cache, "judge_4o_mini": args.comparison_cache}
    e.require(not out.exists() or not any(out.iterdir()), "Use an empty output directory")
    e.require(all(not path.resolve().is_relative_to(out) for path in sources.values()), "Output must not contain source files")
    if args.expected:
        e.require(out != args.expected.resolve(), "Output must differ from expected results")
    hashes = {name: e.sha(path.read_bytes()) for name, path in sources.items()}
    e.require(hashes["raw"] == RAW_SHA256, "This submission expects the latest fixed raw snapshot")
    metadata = e.read_json(args.metadata)
    e.require(metadata["run"]["raw_file"]["sha256"] == RAW_SHA256, "Metadata/raw hash mismatch")
    _, settings, prices = e.load_scoring_config(args.config)
    e.require(settings == {"model": PRIMARY, "temperature": 0, "top_p": 1, "seed": 3407, "max_tokens": 8},
              "Scoring settings differ from the recorded experiment")
    _, comparison_settings, comparison_prices = e.load_scoring_config(args.config, COMPARISON)
    rows = e.read_rows(args.input)
    e.validate_raw(rows)
    parsers = e.load_parsers()
    items = [e.derive_item(row, parsers) for row in rows]
    saved, parsed, usage = validate_cache(e, args.judge_cache, rows, items, settings, parsers)
    _, parsed_4o, usage_4o = validate_cache(e, args.comparison_cache, rows, items, comparison_settings, parsers)
    with tempfile.TemporaryDirectory(prefix="mmmu-submission-") as temporary:
        run = Path(temporary) / "evaluation"
        e.prepare(args.input, run, args.config)
        # Reuse receipts without recording any new API attempts or changing old manifests.
        e.write_rows(run / "responses.jsonl", [saved[item["id"]] for item in items if item["route"] != "auto"])
        summary = e.summarize(run)
        finals = e.read_rows(run / "final_results.jsonl")
        mmmu_summary, mmmu_rows = e.mmmu_diagnostic(rows, parsers)
    e.require(summary["overall"]["pending"] == 0, "Incomplete saved-response replay")
    gate_on = historical_results(items, parsed)
    gate_on_4o = historical_results(items, parsed_4o)
    comparisons, changed = [], []
    candidate_counts = Counter()
    marker_added = marker_conflicts = 0
    joint = disagreements = 0
    for row, item, final, gated, other, mm in zip(rows, items, finals, gate_on, gate_on_4o, mmmu_rows):
        comparison = {"id": row["id"], "question_type": row["question_type"], "finish_reason": row["finish_reason"],
                      "no_gate_4_1": {k: final[k] for k in ("route", "final_answer", "final_correct", "final_status")},
                      "gate_on_4_1": {k: gated[k] for k in ("route", "final_answer", "final_correct", "final_status")},
                      "gate_on_4o": {k: other[k] for k in ("route", "final_answer", "final_correct", "final_status")},
                      "mmmu_rule": {"parsed": mm["parsed"], "correct": mm["final_correct"]}}
        comparisons.append(comparison)
        if final["route"] == "auto" and gated["route"] == "judge_length":
            changed.append(comparison)
        qwen = parsers.qwen_parse(row["raw_text"], item["choices"])
        is_open = row["question_type"] == "open"
        mm_answer = qwen if is_open else mm["parsed"]
        for name, failed in (("qwen", qwen is None), ("mmmu_mc_common_qwen_open", mm_answer is None),
                             ("hybrid100", item["route"] != "auto")):
            candidate_counts[name] += row["finish_reason"] == "length" or failed
        if not is_open and row["finish_reason"] == "stop":
            marker_added += qwen is None and item["route"] == "auto"
            marker_conflicts += item["route"] == "judge_conflict"
            if qwen is not None and mm_answer is not None:
                joint += 1
                disagreements += qwen != mm_answer
    judge_gains = sum(other["final_correct"] and not original["final_correct"] for original, other in zip(gate_on, gate_on_4o))
    judge_losses = sum(original["final_correct"] and not other["final_correct"] for original, other in zip(gate_on, gate_on_4o))
    judge_change = {"answer_disagreements": sum(original["final_answer"] != other["final_answer"]
                                                for original, other in zip(gate_on, gate_on_4o)),
                    "correctness_gains": judge_gains, "correctness_losses": judge_losses,
                    "delta_correct": judge_gains - judge_losses,
                    "delta_percentage_points": round(100 * (judge_gains - judge_losses) / len(rows), 6)}
    cost = lambda u, p: round((u["uncached_prompt_tokens"] * p["input"] + u["cached_tokens"] * p["cached_input"]
                               + u["completion_tokens"] * p["output"]) / 1_000_000, 10)
    scores = {"source_sha256": RAW_SHA256, "policy_id": e.POLICY, "judge_settings": settings,
              "final": e.aggregate(finals), "automatic_count": summary["automatic_count"],
              "judge_count": summary["judge_count"], "gate_on_4_1": e.aggregate(gate_on),
              "gate_on_4o": e.aggregate(gate_on_4o), "mmmu_rule": mmmu_summary,
              "controlled_judge_change_4_1_to_4o": judge_change,
              "official_reference_accuracy": 0.674, "gap_percentage_points": round(100 * (summary["macro_accuracy"] - 0.674), 6),
              "gate_ablation": {"routed_differently": len(changed),
                                "removal_gains": sum(r["no_gate_4_1"]["final_correct"] and not r["gate_on_4_1"]["final_correct"] for r in changed),
                                "removal_losses": sum(r["gate_on_4_1"]["final_correct"] and not r["no_gate_4_1"]["final_correct"] for r in changed)},
              "parser_comparison_gate_on_common_qwen_open": {"judge_candidates": dict(candidate_counts),
                  "marker_added_stop_mc": marker_added, "marker_conflicts_stop_mc": marker_conflicts,
                  "net_judge_reduction": marker_added - marker_conflicts,
                  "stop_mc_qwen_mmmu_joint_extractions": joint, "stop_mc_qwen_mmmu_disagreements": disagreements},
              "historical_full_cache": {PRIMARY: {"responses": len(parsed), "usage": usage, "estimated_cost_usd": cost(usage, prices)},
                                         COMPARISON: {"responses": len(parsed_4o), "usage": usage_4o, "estimated_cost_usd": cost(usage_4o, comparison_prices)}},
              "new_api_calls": 0, "new_api_cost_usd": 0, "input_sha256": hashes,
              "code_hash_normalization": "UTF-8 source with CRLF/CR normalized to LF",
              "evaluator_code_sha256": {name: e.sha((e.ROOT / name).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
                                        for name in e.code_hashes()},
              "reproduce_code_sha256": e.sha(Path(__file__).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n"))}
    subjects = {"source_sha256": RAW_SHA256, "policy_id": e.POLICY, "by_subject": summary["by_subject"],
                "overall": summary["overall"], "macro_accuracy": summary["macro_accuracy"]}
    table = ["# 최신 raw 과목별 정답률", "", "length 게이트 제거, GPT-4.1-mini 저장 응답 재집계.", "",
             "| 과목 | 정답 | 전체 | 정답률 |", "|---|---:|---:|---:|"]
    for subject, group in subjects["by_subject"].items():
        table.append(f"| {subject} | {group['correct']} | {group['total']} | {group['accuracy']:.2%} |")
    overall = subjects["overall"]
    table += [f"| **전체 / macro** | **{overall['correct']}** | **{overall['total']}** | **{overall['accuracy']:.2%}** |", "",
              "각 과목 30문항이므로 micro와 macro가 같다. 문항별 단일 실행 정오이며 반복 추론 정답률은 아니다.", ""]
    e.require(hashes == {name: e.sha(path.read_bytes()) for name, path in sources.items()}, "Input changed during replay")
    out.mkdir(parents=True, exist_ok=True)
    comparison_summary = {key: scores[key] for key in ("source_sha256", "gate_on_4_1", "gate_on_4o", "mmmu_rule",
                                                       "gate_ablation", "parser_comparison_gate_on_common_qwen_open",
                                                       "controlled_judge_change_4_1_to_4o")}
    comparison_summary["gate_off_4_1"] = scores["final"]
    for filename, value in (("scores.json", scores), ("subject_scores.json", subjects), ("comparisons.json", comparison_summary)):
        e.write_json(out / filename, value)
    e.write_rows(out / "item_results.jsonl", [compact_result(row, final) for row, final in zip(rows, finals)])
    e.write_rows(out / "policy_comparison.jsonl", comparisons)
    e.write_rows(out / "changed_items.jsonl", changed)
    e.atomic(out / "subject_scores.md", "\n".join(table))
    if args.expected:
        for filename in OUTPUTS:
            e.require((out / filename).read_bytes() == (args.expected / filename).read_bytes(), "Reproduction differs: " + filename)
    return scores


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evaluator", type=Path, default=ROOT.parent / "raw_evaluation/evaluate.py")
    ap.add_argument("--input", type=Path, default=ROOT / "input/raw.jsonl")
    ap.add_argument("--metadata", type=Path, default=ROOT / "input/run_metadata.json")
    ap.add_argument("--config", type=Path, default=ROOT / "input/scoring_config.yaml")
    ap.add_argument("--judge-cache", type=Path, default=ROOT / "judge/gpt-4.1-mini.jsonl")
    ap.add_argument("--comparison-cache", type=Path, default=ROOT / "judge/gpt-4o-mini.jsonl")
    ap.add_argument("--expected", type=Path, help="Compare all seven generated artifacts byte-for-byte with this directory")
    ap.add_argument("--out", required=True, type=Path, help="Empty output directory; source files are never overwritten")
    args = ap.parse_args()
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Offline reproduction: network disabled")), \
            patch("urllib.request.urlopen", side_effect=AssertionError("Offline reproduction: API disabled")):
        scores = reproduce(args)
    print(f"Reproduced {scores['final']['overall']['correct']}/900; new API calls: 0")


if __name__ == "__main__":
    main()
