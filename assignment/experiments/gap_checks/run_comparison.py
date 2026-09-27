"""Compare two full 8192-token runs to see what a re-run changes.

Both raws are scored with the same deterministic MMMU rule (no Judge) produced by
`code/scoring/evaluate.py prepare`, so differences come from generation only.
Also compares each category's share of output tokens (the basis of time_estimate.py).
Run from the repository root. Needs PyYAML (code/scoring/requirements.txt).
"""
import argparse, collections, hashlib, json, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from categories import CATEGORIES

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--a", type=Path, default=Path("assignment/runs/draft/raw.jsonl"), help="earlier run raw")
ap.add_argument("--b", type=Path, default=Path("results/mmmu_team_baseline/raw.jsonl"), help="final run raw")
ap.add_argument("--evaluator", type=Path, default=Path("code/scoring/evaluate.py"))
ap.add_argument("--config", type=Path, default=Path("code/config.yaml"))
ap.add_argument("--out", type=Path)
args = ap.parse_args()

def rule_scores(raw, tmp):
    out = Path(tmp) / hashlib.sha256(str(raw).encode()).hexdigest()[:8]
    subprocess.run([sys.executable, str(args.evaluator), "prepare", "--raw", str(raw),
                    "--config", str(args.config), "--out", str(out)], check=True, capture_output=True)
    return {r["id"]: r for r in map(json.loads, (out / "mmmu_results.jsonl").open(encoding="utf-8"))}

def generate_seconds(raw):
    env = json.loads((raw.parent / "env.json").read_text(encoding="utf-8"))
    return round(sum(i["generate_seconds"] for i in env["invocations"]), 3)

def token_share(raw):
    tok = collections.Counter()
    for r in map(json.loads, raw.open(encoding="utf-8")):
        tok[r["subject"]] += r["output_tokens"]
    total = sum(tok.values())
    return {c: round(100 * sum(tok[s] for s in subs) / total, 1) for c, subs in CATEGORIES.items()}

with tempfile.TemporaryDirectory() as tmp:
    A, B = rule_scores(args.a, tmp), rule_scores(args.b, tmp)
assert A.keys() == B.keys() and len(A) == 900
sa, sb = collections.Counter(), collections.Counter()
for i in A:
    sa[A[i]["subject"]] += bool(A[i]["final_correct"]); sb[B[i]["subject"]] += bool(B[i]["final_correct"])
diff = {s: sb[s] - sa[s] for s in sorted(sb)}
ta, tb = token_share(args.a), token_share(args.b)
out = {
    "scorer": "MMMU rule only (no Judge), identical for both runs",
    "inputs": {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.a, args.b)},
    "total_correct": {"a": sum(sa.values()), "b": sum(sb.values())},
    "item_correctness_flips": sum(A[i]["final_correct"] != B[i]["final_correct"] for i in A),
    "subjects_changed": sum(v != 0 for v in diff.values()),
    "max_subject_change_items": max(abs(v) for v in diff.values()),
    "subject_correct_diff_b_minus_a": diff,
    "category_accuracy_pct": {c: {"a": round(100 * sum(sa[s] for s in subs) / (30 * len(subs)), 1),
                                  "b": round(100 * sum(sb[s] for s in subs) / (30 * len(subs)), 1)}
                              for c, subs in CATEGORIES.items()},
    "category_token_share_pct": {c: {"a": ta[c], "b": tb[c]} for c in CATEGORIES},
    "max_token_share_gap_pp": round(max(abs(ta[c] - tb[c]) for c in CATEGORIES), 1),
    "generate_seconds": {"a": generate_seconds(args.a), "b": generate_seconds(args.b)},
}
print(json.dumps({k: v for k, v in out.items() if k not in ("inputs", "subject_correct_diff_b_minus_a")},
                 ensure_ascii=False, indent=2))
if args.out:
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
