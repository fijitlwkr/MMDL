"""Expected score change if extraction failures used Qwen's random fallback instead of counting as wrong.

Qwen3-VL eval_utils.py (commit 96588727, see code/scoring/frozen/vendor/qwen_eval_utils.py) picks
random.choice(choices + ['Z']) when answer extraction fails. Our policy marks such items wrong.
Standard library only. Run from the repository root.
"""
import argparse, hashlib, json
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--run", type=Path, default=Path("results/mmmu_team_baseline"))
ap.add_argument("--out", type=Path, help="write summary JSON here")
args = ap.parse_args()

raw_path, items_path = args.run / "raw.jsonl", args.run / "scores" / "item_results.jsonl"
raw = {r["id"]: r for r in map(json.loads, raw_path.open(encoding="utf-8"))}
items = [json.loads(line) for line in items_path.open(encoding="utf-8")]
assert len(raw) == len(items) == 900, "expected 900 rows"

failed = [it for it in items if it["predicted"] in (None, "", "Z")]
def p_correct(it):
    # open questions are scored as A=reference vs B=Other Answers, so the draw is over A/B/Z
    n = 2 if it["question_type"] == "open" else len(raw[it["id"]]["options"])
    return 1 / (n + 1)

expected = sum(p_correct(it) for it in failed)
correct = sum(bool(it["correct"]) for it in items)
summary = {
    "inputs": {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in (raw_path, items_path)},
    "current_correct": correct,
    "current_accuracy_pct": round(100 * correct / len(items), 2),
    "extraction_failures": {"total": len(failed),
                            "multiple_choice": sum(it["question_type"] == "multiple-choice" for it in failed),
                            "open": sum(it["question_type"] == "open" for it in failed)},
    "expected_extra_correct_with_random_fallback": round(expected, 2),
    "expected_accuracy_pct_with_random_fallback": round(100 * (correct + expected) / len(items), 2),
    "expected_delta_pp": round(100 * expected / len(items), 2),
}
print(json.dumps(summary, ensure_ascii=False, indent=2))
if args.out:
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
