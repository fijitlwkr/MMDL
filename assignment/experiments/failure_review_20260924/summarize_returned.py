"""Validate returned chat-review labels and summarize them without changing scores."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from prepare import ROOT, SOURCE, RAW_SHA, ANSWER_STATES, ERROR_TYPES, read_rows, require, sha, write_json, write_rows

RETURNED = ROOT / "returned_20260924"
POLICIES = ("no_gate_4_1", "gate_on_4_1", "gate_on_4o")
DISPUTED = {
    "validation_Electronics_18": "B 선택 후 다른 수치를 재검토하다 종료; 확정 평가기 오류 여부 재판정",
    "validation_Math_13": "E 선택 후 재검토하지만 명시 철회 없음; 답 확정 기준 재판정",
    "validation_Energy_and_Power_14": "의도된 선택 B·2.37m와 계산 답 2.14m를 병기; 답 확정 기준 재판정",
}


def validate_labels(rows, ids, raw, failure):
    require(len(rows) == len(ids) and len({r["id"] for r in rows}) == len(rows), "Count/duplicate mismatch")
    require({r["id"] for r in rows} == set(ids), "ID coverage mismatch")
    for r in rows:
        item = raw[r["id"]]
        state, answer, quote = r["answer_status"], r["extracted_answer"], r["evidence_quote"]
        require(state in ANSWER_STATES and isinstance(answer, str), "Invalid answer state/type")
        require(bool(answer.strip()) == (state in ("explicit", "inferable")), "State/answer mismatch")
        if answer and item["question_type"] == "multiple-choice":
            require(answer in [chr(65 + i) for i in range(len(item["options"]))], "Invalid MC answer")
        require(isinstance(quote, str) and bool(quote.strip()) and quote in item["raw_text"], "Quote not verbatim: " + r["id"])
        if failure:
            require(r["primary_type"] in ERROR_TYPES, "Invalid failure category")


def summarize(out):
    require(not out.exists() or not any(out.iterdir()), "Use a new empty output directory")
    require(out.parent == RETURNED, "Output must be a direct child of returned_20260924")
    paths = {kind: RETURNED / "input" / f"{kind}_labels_existing.jsonl" for kind in ("failure60", "gate18")}
    coordinator = ROOT / "packets/coordinator"
    source_paths = {"raw": SOURCE / "input/raw.jsonl", "item_results": SOURCE / "results/item_results.jsonl",
                    "selection_manifest": coordinator / "manifest.json", "failure_key": coordinator / "failure60_selection_key.jsonl",
                    "gate_key": coordinator / "gate18_answer_key.jsonl",
                    "judge_4_1": SOURCE / "judge/gpt-4.1-mini.jsonl", "judge_4o": SOURCE / "judge/gpt-4o-mini.jsonl", **paths}
    hashes = {name: sha(path) for name, path in source_paths.items()}
    require(hashes["raw"] == RAW_SHA, "Wrong raw snapshot")
    manifest = json.loads(source_paths["selection_manifest"].read_text(encoding="utf-8"))
    require(hashes["item_results"] == manifest["input_sha256"]["item_results"], "Wrong score snapshot")
    raw_rows, results = read_rows(source_paths["raw"]), read_rows(source_paths["item_results"])
    raw, scores = {r["id"]: r for r in raw_rows}, {r["id"]: r for r in results}
    require(len(raw_rows) == len(raw) == len(results) == len(scores) == 900 and set(raw) == set(scores), "Source ID mismatch")
    require(sum(r["correct"] for r in results) == 600, "Wrong policy score")
    failure_keys, gate_keys = read_rows(source_paths["failure_key"]), read_rows(source_paths["gate_key"])
    labels = {kind: read_rows(path) for kind, path in paths.items()}
    for kind, rows in labels.items():
        validate_labels(rows, manifest[kind + "_ids"], raw, kind == "failure60")
    require(len(failure_keys) == 60 and {r["id"] for r in failure_keys} == set(manifest["failure60_ids"]), "Failure key mismatch")
    require(len(gate_keys) == 18 and {r["id"] for r in gate_keys} == set(manifest["gate18_ids"]), "Gate key mismatch")
    require(all(r["no_gate_4_1"]["final_correct"] == scores[r["id"]]["correct"] and
                r["no_gate_4_1"]["final_answer"] == scores[r["id"]]["predicted"] for r in gate_keys), "Gate score mismatch")
    population = Counter(r["subject"] for r in results if not r["correct"])
    sampled = Counter(r["subject"] for r in failure_keys)
    require(len(sampled) == 30 and all(n == 2 for n in sampled.values()), "Wrong stratified sample")
    for r in failure_keys:
        require(not scores[r["id"]]["correct"] and r["subject"] == scores[r["id"]]["subject"], "Wrong sampled item")
        require(r["policy_error_population"] == population[r["subject"]] and r["sample_size"] == 2 and
                r["population_weight_per_item"] == population[r["subject"]] / 2, "Wrong population weight")
    by_id = {r["id"]: r for r in failure_keys}
    joined = []
    for r in labels["failure60"]:
        key = by_id[r["id"]]
        joined.append({**r, "subject": key["subject"], "question_type": raw[r["id"]]["question_type"],
                       "population_weight_per_item": key["population_weight_per_item"],
                       "policy_error_population": key["policy_error_population"], "sample_size": 2,
                       "quote_verbatim": True, "review_origin": "user_forwarded_chat_review",
                       "human_verification_status": "not_attested", "prior_exposure": None,
                       "adjudication_note": DISPUTED.get(r["id"]), "source_sha256": RAW_SHA})
    weighted = Counter()
    for r in joined:
        weighted[r["primary_type"]] += r["population_weight_per_item"]
    require(sum(weighted.values()) == 300, "Weight total mismatch")
    counts = Counter(r["primary_type"] for r in joined)
    categories = [{"primary_type": kind, "sample_count": counts[kind], "weighted_count": weighted[kind],
                   "weighted_percent": 100 * weighted[kind] / 300} for kind in sorted(ERROR_TYPES, key=lambda k: -weighted[k])]
    gate = {r["id"]: r for r in labels["gate18"]}
    comparison = [{**gate[r["id"]], "question_type": raw[r["id"]]["question_type"], "quote_verbatim": True,
                   "prior_exposure": True, "prior_exposure_source": "user_statement_in_chat",
                   "review_origin": "user_forwarded_chat_review", "human_verification_status": "not_attested",
                   "source_sha256": RAW_SHA, "adjudication_note": DISPUTED.get(r["id"]),
                   **{p: r[p] for p in POLICIES}} for r in gate_keys]
    explicit = [r for r in comparison if r["answer_status"] == "explicit"]
    unresolved = [r for r in comparison if r["answer_status"] in ("ambiguous", "no_answer")]
    require(len(explicit) == 5 and len(unresolved) == 13 and all(r["question_type"] == "multiple-choice" for r in explicit), "Unexpected returned gate cohort")
    policies = {p: {"explicit_matched": sum(r[p]["final_answer"] == r["extracted_answer"] for r in explicit),
                    "explicit_total": len(explicit), "unresolved_assigned": sum(r[p]["final_answer"] is not None for r in unresolved),
                    "unresolved_scored_correct": sum(r[p]["final_correct"] for r in unresolved),
                    "unresolved_total": len(unresolved), "policy_correct_in_gate18": sum(r[p]["final_correct"] for r in comparison)} for p in POLICIES}
    gains = [r["id"] for r in comparison if r["no_gate_4_1"]["final_correct"] and not r["gate_on_4_1"]["final_correct"]]
    losses = [r["id"] for r in comparison if not r["no_gate_4_1"]["final_correct"] and r["gate_on_4_1"]["final_correct"]]
    summary = {"status": "provisional_returned_labels_not_adjudicated", "input_sha256": hashes,
               "script_sha256_lf": hashlib.sha256(Path(__file__).read_text(encoding="utf-8").encode()).hexdigest(),
               "validation": {"failure60_count": 60, "gate18_count": 18, "duplicate_missing_extra_ids": 0, "verbatim_quotes": 78},
               "failure60": {"categories": categories, "answer_states": dict(Counter(r["answer_status"] for r in joined)),
                             "weight_total": 300, "estimand": "original 300 policy-scored errors; returned labels unchanged"},
               "gate18": {"answer_states": {s: sum(r["answer_status"] == s for r in comparison) for s in ANSWER_STATES},
                          "policies": policies, "gate_removal_gain_ids": gains, "gate_removal_loss_ids": losses,
                          "all_gain_ids_unresolved_in_returned_labels": all(gate[id_]["answer_status"] in ("ambiguous", "no_answer") for id_ in gains)},
               "adjudication_needed": DISPUTED, "score_changed": False, "new_api_calls": 0, "new_inference_runs": 0}
    lines = ["# 모델 실패 60문항: 1차 분류·가중 집계 — 2026-09-24", "",
             "반환된 챗 검토의 라벨을 그대로 집계한 잠정 결과다. 원문 인용 존재 확인은 원인 분류의 정확성이나 사람 검증 완료를 뜻하지 않는다. 원본 라벨·기존 600/900 점수·채점 정책은 변경하지 않았다.", "",
             "## 파일 검증", "", "- failure60 60/60, gate18 18/18: 누락·추가·중복 0. 인용문 78/78이 raw_text에 문자 그대로 존재한다.",
             "- 객관식 선택지 범위, 답 상태와 답 유무, 30과목×2 표본 및 전체 가중치 300을 확인했다.",
             "- 입력의 extracted_answer를 보존했다. 검토자·이미지 확인·상세 분류 근거는 파일에 없다. gate18 사전 노출 true는 사용자 진술을 출처로 별도 기록했다.", "",
             "## failure60: 받은 분류의 잠정 가중 요약", "",
             "과목별 기존 오답 수/2를 각 표본의 가중치로 사용했다. 가중 건수는 300건 전체를 실제로 검토한 건수가 아닌 추정량이다. 미확정도 분모에서 빼지 않았다.", "",
             "| 유형 | 표본 건수 | 가중 건수 | 가중 비율 |", "|---|---:|---:|---:|"]
    names = {"knowledge": "지식", "visual_reading": "이미지 해석", "calculation_reasoning": "계산·추론", "uncertain": "불확실", "repetition_incomplete": "반복·미완결", "evaluation_issue": "평가기 문제 후보"}
    lines += [f"| {names[r['primary_type']]} | {r['sample_count']} | {r['weighted_count']:g} | {r['weighted_percent']:.2f}% |" for r in categories]
    lines += ["| 합계 | 60 | 300 | 100.00% |", "", "답 상태는 explicit 43 / ambiguous 6 / no_answer 11이다. 원인 유형의 불확실 5건과 답 상태 미확정 17건은 다른 집계다. 과목당 2건의 작은 표본이며, 900문항 전체 오류율로 확대하지 않는다.", "",
              "## 실험 해석과 개선 방향", "",
              f"- 지식·개념 적용과 이미지 해석이 주원인으로 분류된 표본은 {counts['knowledge'] + counts['visual_reading']}건이며, 가중 비율의 합은 {100 * (weighted['knowledge'] + weighted['visual_reading']) / 300:.2f}%다. 도표·도식의 정보를 읽는 과정과 전공 개념 적용을 함께 학습하는 개선안을 검토할 근거다.",
              "- 43/60건은 답을 명확하게 제시했다. 답 형식 학습과 함께 문제풀이 내용의 정확성을 다룰 필요가 있다.",
              "- 반복·미완결 4건은 주된 원인으로 선택된 건수다. 다른 유형에 반복이 동반될 수 있으므로 전체 900건의 자동 반복 탐지 결과와 같은 빈도로 해석하지 않는다.", "",
              "일부 라벨의 인용은 최종 답 문구만 포함한다. 발표 대표 사례에는 이미지 또는 개념을 어떻게 잘못 해석했는지 설명하는 근거를 보강해야 한다. 이 분석은 파인튜닝 효과를 측정한 결과가 아니다.", "",
              "## 평가기 문제 후보 1건", "",
              "Electronics_18은 B 선택 뒤 `0.75 e^{-2t}` 가능성을 재검토하다 중단했다. 두 Judge의 저장 결과는 Z(stop)이다. 이 1건의 evaluation_issue를 확정 오채점이나 확정 오류율 1%로 쓰지 않는다. 반환 라벨은 바꾸지 않고 재판정 필요 표시만 추가했다.", "",
              "이 사례의 별도 원문 대조 근거: [응답 전문](../../packets/failure60/batch_03.md#validation_electronics_18), [4.1 캐시](../../../submission_20260923/judge/gpt-4.1-mini.jsonl), [4o 캐시](../../../submission_20260923/judge/gpt-4o-mini.jsonl). 캐시 파일 해시도 집계 JSON에 기록했다.", "",
              "## 파일과 재현", "", "[집계 JSON](summary.json), [60건 가중치 연결](failure60_joined.jsonl), [18건 판정 대조](gate18_comparison.jsonl). 수신 원본은 ../input/에 바이트 그대로 보관했다.", "",
              "저장소 루트에서 Python 표준 라이브러리만 사용한다. 기존 결과 폴더는 덮어쓰지 않는다.", "", "```bash",
              "python assignment/experiments/failure_review_20260924/summarize_returned.py --self-test",
              "python assignment/experiments/failure_review_20260924/summarize_returned.py --out assignment/experiments/failure_review_20260924/returned_20260924/replay",
              "```", "", "새 API·재추론 0회. 라벨의 원인 분류와 이미지 대조를 새로 수행한 것은 아니다."]
    out.mkdir(parents=True, exist_ok=True)
    write_rows(out / "failure60_joined.jsonl", joined)
    write_rows(out / "gate18_comparison.jsonl", comparison)
    write_json(out / "summary.json", summary)
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    require(all(sha(path) == hashes[name] for name, path in source_paths.items()), "Inputs changed")
    print(json.dumps({"validation": summary["validation"], "weighted_categories": categories, "gate18": policies}, ensure_ascii=False))


def self_test():
    raw = {"x": {"question_type": "multiple-choice", "options": ["one", "two"], "raw_text": "Answer: B"}}
    row = {"id": "x", "answer_status": "explicit", "extracted_answer": "B", "evidence_quote": "Answer: B", "primary_type": "knowledge"}
    validate_labels([row], ["x"], raw, True)
    for bad in ([row, row], [{**row, "extracted_answer": "C"}], [{**row, "answer_status": "no_answer"}], [{**row, "evidence_quote": "invented"}]):
        try:
            validate_labels(bad, ["x"], raw, True)
        except (ValueError, AssertionError):
            continue
        raise AssertionError("Invalid returned label accepted")
    print("Self-test passed: duplicates, MC range, answer state, verbatim evidence.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        require(args.out is not None, "Specify an empty output directory")
        summarize(args.out.resolve())
