"""Estimate per-category and per-subject generation time for a run.

Generation mixed subjects inside concurrent vLLM batches, so per-subject wall-clock time was
not measured. This script splits the recorded generation time (env.json: invocations[].generate_seconds) by
each group's share of output tokens. Prefill (image/text input) cost is not modelled.
Standard library only. Run from the repository root.
"""
import argparse, collections, hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from categories import CATEGORIES, SUBJECT_TO_CATEGORY

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--run", type=Path, default=Path("results/mmmu_team_baseline"))
ap.add_argument("--out", type=Path)
args = ap.parse_args()

raw_path, env_path = args.run / "raw.jsonl", args.run / "env.json"
env = json.loads(env_path.read_text(encoding="utf-8"))
inv = env["invocations"]  # one entry per invocation (a resumed run has several)
gen_s = round(sum(i["generate_seconds"] for i in inv), 3)
rows = [json.loads(line) for line in raw_path.open(encoding="utf-8")]
assert len(rows) == 900
tok = collections.Counter()
for r in rows:
    tok[r["subject"]] += r["output_tokens"]
total = sum(tok.values())

def entry(t):
    return {"output_tokens": t, "share_pct": round(100 * t / total, 1),
            "estimated_seconds": round(gen_s * t / total), "estimated_minutes": round(gen_s * t / total / 60, 1)}

out = {
    "method": "generate_seconds x (group output tokens / all output tokens); prefill not modelled",
    "inputs": {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in (raw_path, env_path)},
    "generate_seconds": gen_s, "duration_seconds": round(sum(i["duration_seconds"] for i in inv), 3),
    "invocations": len(inv), "output_tokens_total": total,
    "by_category": {c: entry(sum(tok[s] for s in subs)) for c, subs in CATEGORIES.items()},
    "by_subject": {s: entry(tok[s]) | {"category": SUBJECT_TO_CATEGORY[s]} for s in sorted(tok)},
}
print(json.dumps({k: out[k] for k in ("generate_seconds", "by_category")}, ensure_ascii=False, indent=2))
if args.out:
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
