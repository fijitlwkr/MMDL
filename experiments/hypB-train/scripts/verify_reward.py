"""Offline comparison with frozen v2 outcomes and synthetic MMFR tests."""
from collections import Counter, defaultdict

from classify_answers import ROOT, WORKSPACE, read_rows, write_json
from reward import evaluate, extract, reward

RAW = WORKSPACE / "assignment/experiments/received_20260922/results/input/raw.jsonl"
SCORES = WORKSPACE / "work/team-evaluator-no-length/assignment/experiments/raw_evaluation/outputs/release-v2-latest"


def synthetic():
    train = read_rows(ROOT / "data/answer_types.jsonl")
    fixtures = []
    for kind in ("mc_letter", "mc_value", "numeric", "short_rule", "excluded"):
        item = next(r for r in train if r["role"] == "train" and r["format"] == kind
                    and (kind != "short_rule" or r["answer"].casefold() == "yes"))
        if kind.startswith("mc_"):
            good = item["answer"]
            bad = next(k for k in item["choices"] if k != good)
            tests = [(good, "stop", (1, "correct")), ("Final Answer: " + good, "stop", (1, "correct")),
                     (bad, "stop", (0, "wrong")), ("", "stop", (0, "extract_fail")),
                     (good, "length", (0, "truncated")), (bad, "length", (0, "truncated"))]
        elif kind == "excluded":
            tests = [(t, "stop", (0, "extract_fail")) for t in ("A", "31", "Final Answer: Yes", "")]
            tests.append(("A", "length", (0, "truncated")))
        else:
            good = item["answer"]
            tests = [(good, "stop", (1, "correct")), ("Final Answer: " + good, "stop", (1, "correct")),
                     ("Other Answers", "stop", (0, "wrong")), ("", "stop", (0, "extract_fail")),
                     (good, "length", (0, "truncated")), ("unrelated output", "stop", (0, "extract_fail"))]
        for response, finish, expected in tests:
            actual = reward(response, finish, item)
            assert actual == expected, (kind, response, expected, actual)
        fixtures.append({"format": kind, "row": item["row"], "passed": len(tests)})
    # These passing diagnostics expose v2 substring behavior; no new rule is selected.
    limitations = []
    for kind, gold, text in [("numeric", "31", "Final Answer: 131"),
                              ("short_rule", "yes", "The tentative answer was yes. Final Answer: no.")]:
        observed = reward(text, "stop", {"format": kind, "answer": gold})
        assert observed == (1, "correct")
        limitations.append({"format": kind, "gold": gold, "response": text, "observed": observed})
    return fixtures, limitations


def main():
    manifest = evaluate.read_json(SCORES / "manifest.json")
    assert manifest["code_sha256"] == evaluate.code_hashes()
    assert manifest["source_sha256"] == evaluate.sha(RAW.read_bytes())
    assert manifest["policy_id"] == evaluate.POLICY
    rows = read_rows(RAW)
    evaluate.validate_raw(rows)
    scores = evaluate.unique(read_rows(SCORES / "final_results.jsonl"), "v2")
    assert scores.keys() == {r["id"] for r in rows}
    auto, disagreements, judge = Counter(), [], defaultdict(Counter)
    for row in rows:
        archived = scores[row["id"]]
        assert type(archived["final_correct"]) is bool
        assert archived["raw_sha256"] == evaluate.sha(row["raw_text"].encode("utf-8"))
        mc = row["question_type"] == "multiple-choice"
        item = {"format": "mc_letter" if mc else "open_audit", "answer": row["gold"],
                "choices": {chr(65+i): option for i, option in enumerate(row["options"])}}
        text, finish = row["raw_text"], row["finish_reason"]
        answer, gold, route = extract(text, finish, item)
        value, reason = reward(text, finish, item)
        assert route == archived["route"]
        if route == "auto":
            auto["total"] += 1
            auto["extracted_match"] += answer == archived["auto_answer"]
            auto["ungated_correctness_match"] += (answer == gold) == archived["final_correct"]
            auto["reward_correctness_match"] += bool(value) == archived["final_correct"]
            if finish == "stop":
                auto["stop_total"] += 1
                auto["stop_correctness_match"] += bool(value) == archived["final_correct"]
            else:
                auto["length_total"] += 1
            if answer != archived["auto_answer"] or bool(value) != archived["final_correct"]:
                disagreements.append({"id": row["id"], "type": row["question_type"], "finish": finish,
                                      "v2_auto_answer": archived["auto_answer"], "r1_answer": answer,
                                      "v2_correct": archived["final_correct"], "reward": value,
                                      "reason": "length_gate" if finish == "length" and answer == archived["auto_answer"]
                                      else "extraction_or_correctness_disagreement"})
        else:
            judge[route][reason] += 1
            judge["all"][reason] += 1
            judge["ungated"][("extract_fail" if answer is None else "correct" if answer == gold else "wrong")] += 1
    assert auto["total"] == 555 and sum(judge["all"].values()) == 345
    fixtures, limitations = synthetic()
    result = {"raw_sha256": manifest["source_sha256"], "code_sha256": manifest["code_sha256"],
              "auto": auto, "judge": judge, "auto_disagreements": disagreements,
              "synthetic": fixtures, "provisional_open_behavior": limitations}
    write_json(ROOT / "reports/reward_check.json", result)
    print("auto", dict(auto), "Judge", {k: dict(v) for k, v in judge.items()})
    print("mismatches", Counter(r["reason"] for r in disagreements), "synthetic", fixtures)


if __name__ == "__main__":
    main()
