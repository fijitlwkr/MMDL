"""Compare the pinned fallback with trial annotations and archived Judge scores offline."""

import csv
from collections import Counter

import reward as legacy
import reward_v2 as candidate
from verify_reward import RAW, ROOT, SCORES, evaluate, read_rows, write_json


OUT = ROOT / "runs/trial_100_rescore"
RECHECK = OUT / "recheck"


def sha(path):
    return evaluate.sha(path.read_bytes())


def trial():
    annotations = read_rows(OUT / "manual_trial_review.jsonl")
    pool = {row["row"]: row for row in read_rows(ROOT / "data/r1_pool.jsonl")}
    rows = read_rows(ROOT / "runs/trial_100/raw.jsonl")
    assert len(rows) == 400 and len({(r["row"], r["repeat"]) for r in rows}) == 400
    assert all(sum(1 for r in rows if r["row"] == key) == 4 for key in {r["row"] for r in rows})
    failed = [row for row in rows if row["reward_reason"] == "extract_fail"]
    assert len(annotations) == len(failed) == 118
    table = []
    for label, row in zip(annotations, failed, strict=True):
        assert (label["row"], label["repeat"]) == (row["row"], row["repeat"])
        item = pool[row["row"]]
        guess = candidate.fallback_extract(row["raw_text"], item["choices"])
        expected = label["human_answer"]
        status = "match" if guess == expected else "miss" if guess is None else "wrong_extraction"
        table.append({**label, "fallback_answer": guess, "status": status})
    with (RECHECK / "trial_extraction_check.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)

    old_counts, new_counts = Counter(), Counter()
    preserved = 0
    for row in rows:
        args = row["raw_text"], row["finish_reason"], pool[row["row"]]
        old = legacy.reward(*args)
        assert old == (row["reward"], row["reward_reason"]), (row["row"], row["repeat"])
        new = candidate.reward(*args)
        if old[1] != "extract_fail":
            assert old == new, (row["row"], row["repeat"])
            preserved += 1
        old_counts[old[1]] += 1
        new_counts[new[1]] += 1
    assert preserved == 282
    return {"formats": Counter(r["format"] for r in annotations), "comparison": Counter(r["status"] for r in table),
            "revision_observed": sum(r["reasoning_revision_observed"] for r in table),
            "disagreements": [r for r in table if r["status"] != "match"],
            "preserved": preserved, "original_reasons": old_counts, "verified_reasons": new_counts}


def judge():
    manifest = evaluate.read_json(SCORES / "manifest.json")
    assert manifest["source_sha256"] == sha(RAW) == "ef23f0c49d9b1ae6c62b9625fbd52cce474a0c035c1a644cfa737e0967daa313"
    assert manifest["code_sha256"] == evaluate.code_hashes() and manifest["policy_id"] == evaluate.POLICY
    rows = read_rows(RAW)
    evaluate.validate_raw(rows)
    scores_path = SCORES / "final_results.jsonl"
    scores = evaluate.unique(read_rows(scores_path), "v2")
    assert scores.keys() == {r["id"] for r in rows}
    table = []
    for row in rows:
        score = scores[row["id"]]
        if score["route"] == "auto":
            continue
        assert score["final_source"] == "judge" and type(score["final_correct"]) is bool
        text, finish = row["raw_text"], row["finish_reason"]
        assert score["raw_sha256"] == evaluate.sha(text.encode("utf-8"))
        mc = row["question_type"] == "multiple-choice"
        item = {"format": "mc_letter" if mc else "open_audit", "answer": row["gold"],
                "choices": {chr(65+i): option for i, option in enumerate(row["options"])}}
        original = legacy.reward(text, finish, item)
        value, reason = candidate.reward(text, finish, item)
        eligible = mc and original[1] == "extract_fail"
        extracted = reason in {"fallback_correct", "fallback_wrong"}
        letter = candidate.fallback_extract(text, item["choices"]) if extracted else None
        table.append({"id": row["id"], "type": row["question_type"], "finish": finish, "route": score["route"],
                      "gold": item["answer"], "judge_answer": score["final_answer"], "judge_correct": score["final_correct"],
                      "eligible": eligible, "fallback_answer": letter, "extracted": extracted,
                      "reward": value, "reason": reason})
    assert len(table) == 345
    with (RECHECK / "judge_comparison.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    return {"source_sha256": sha(RAW), "judge_results_sha256": sha(scores_path), "count": len(table)}


def synthetic():
    item = {"format": "mc_letter", "answer": "B", "choices": {"A": "Red", "B": "Green", "C": "Blue", "D": "Orange"}}
    fixtures = {
        "box": (r"\boxed{B}", r"\boxed{A}", r"\boxed{C and D}"),
        "answer": ("Answer: **B**", "Answer: **A**", "Answer: **C and D**"),
        "chinese": ("最终答案：**B. Green**", "答案：**A. Red**", "答案：**C/D**"),
        "bold": ("**B. Green**", "**A. Red**", "**C. Blue**\n**D. Orange**"),
        "content": ("Answer: **Green**", "Answer: **Red**", "Answer: **Blue**\nAnswer: **Orange**"),
        "korean": ("정답: **B**", "정답: **A**", "정답: **C, D**"),
    }
    checks = []
    for form, (good, bad, multi) in fixtures.items():
        for case, text, expected_letter in (("correct", good, "B"), ("wrong", bad, "A"), ("multiple", multi, None)):
            answer = candidate.fallback_extract(text, item["choices"])
            checks.append({"form": form, "case": case, "pass": answer == expected_letter})
        for text in (good, bad, multi):
            checks.append({"form": form, "case": "truncated", "pass": candidate.reward(text, "length", item) == (0, "truncated")})

    # Exercise the public reward on fixtures that really reach the fallback.
    for case, text, expected in (
        ("correct", "C and D are uncertain.\n\n" + r"Final Answer: \boxed{B}", (1, "fallback_correct")),
        ("wrong", r"Final Answer: \boxed{A}", (0, "fallback_wrong")),
        ("multiple", r"Final Answer: \boxed{C and D}", (0, "extract_fail")),
        ("invalid", r"Final Answer: \boxed{Z}", (0, "extract_fail")),
    ):
        actual = candidate.reward(text, "stop", item)
        checks.append({"form": "public_reward", "case": case, "pass": actual == expected})
    # A repeated label is valid; two different labels are still ambiguous.
    for letter in ("A", "B", "D"):
        choices = {**item["choices"], letter: letter}
        answer = candidate.fallback_extract(f"Answer: **{letter}. {letter}**", choices)
        checks.append({"form": "one_letter_option_content", "case": "diagnostic", "letter": letter,
                       "expected": letter, "actual": answer, "pass": answer == letter})
    checks.append({"form": "one_letter_option_content", "case": "distinct",
                   "pass": candidate.fallback_extract("Answer: **A. B**", item["choices"]) is None})
    return checks


def main():
    freeze = evaluate.read_json(RECHECK / "reward_v2_freeze.json")
    for path, digest in freeze["sha256"].items():
        assert sha(ROOT / path) == digest, path
    checks = synthetic()
    assert all(check["pass"] for check in checks), [check for check in checks if not check["pass"]]
    result = {"trial": trial(), "synthetic": checks}
    print("trial", result["trial"]["comparison"], flush=True)
    result["judge"] = judge()
    write_json(RECHECK / "verification.json", result)
    print("judge rows", result["judge"]["count"], "synthetics", Counter(r["pass"] for r in result["synthetic"]))


if __name__ == "__main__":
    main()
