"""Reproduce the 147 labeling items and split them 4 ways (A/B/C/D).

Flow: 900 -> baseline wrong 300 -> wrong in all 4 runs 192 -> baseline finish=stop 150
      -> minus 3 extraction_failure = 147.
Split: sort by response word count desc (tie: id asc), deal A B C D D C B A for the
first 144, then the last 3 go to A, B, D (C also checks the extra items below).

Usage: python make_split.py --repo . --out results/error_analysis
"""
import argparse, csv, json, random
from pathlib import Path

SEEDS = ["seed_42", "seed_1234", "seed_2026"]
SAMPLE_SEED = 3407
LENGTH_SAMPLE = 10


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default="results/error_analysis")
    a = ap.parse_args()
    repo, out = Path(a.repo), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    base = {r["id"]: r for r in jl(repo / "results/mmmu_team_baseline/scores/item_results.jsonl")}
    seeds = {s: {r["id"]: r for r in jl(repo / f"results/baseline_seed_robustness/{s}/item_results.jsonl")} for s in SEEDS}
    raw = {r["id"]: r for r in jl(repo / "results/mmmu_team_baseline/raw.jsonl")}
    rep = {r["id"]: r for r in jl(repo / "assignment/experiments/repetition/results/per_item.jsonl")}

    assert len(base) == 900 and all(len(v) == 900 for v in seeds.values())
    wrong = [i for i, r in base.items() if not r["correct"]]
    always = [i for i in wrong if all(not seeds[s][i]["final_correct"] for s in SEEDS)]
    stop = [i for i in always if base[i]["finish_reason"] == "stop"]
    length = [i for i in always if base[i]["finish_reason"] == "length"]
    extr = [i for i in stop if base[i]["status"] == "extraction_failure"]
    items = [i for i in stop if base[i]["status"] != "extraction_failure"]
    assert (len(wrong), len(always), len(stop), len(length), len(extr), len(items)) == (300, 192, 150, 42, 3, 147), \
        (len(wrong), len(always), len(stop), len(length), len(extr), len(items))
    assert len(wrong) - len(always) == 108

    words = {i: len(raw[i]["raw_text"].split()) for i in items}
    order = sorted(items, key=lambda i: (-words[i], i))
    pattern = "ABCD" "DCBA"
    member = {}
    for k, i in enumerate(order[:144]):
        member[i] = pattern[k % 8]
    for i, m in zip(order[144:], "ABD"):
        member[i] = m
    rows = [{"id": i, "subject": base[i]["subject"], "words": words[i], "member": member[i]} for i in order]
    rows.sort(key=lambda r: (r["member"], r["id"]))
    with open(out / "split.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "subject", "words", "member"])
        w.writeheader(); w.writerows(rows)

    # extra items for C: 3 stop-extraction failures + 10 random of the 42 length items
    sample = set(random.Random(SAMPLE_SEED).sample(sorted(length), LENGTH_SAMPLE))
    extra = []
    for i in sorted(extr):
        extra.append({"id": i, "kind": "stop_extraction_failure", "repetition_flag": "", "check": "yes"})
    for i in sorted(length):
        extra.append({"id": i, "kind": "length_ended", "repetition_flag": bool(rep[i]["repetition_flag_20pct"]),
                      "check": "yes" if i in sample else "no"})
    with open(out / "extra_for_C.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "kind", "repetition_flag", "check"])
        w.writeheader(); w.writerows(extra)

    # empty label templates
    cols = ["id", "primary_type", "confidence", "evidence_quote", "reason", "images_checked", "self_check", "label_by"]
    for m in "ABCD":
        with open(out / f"labels_{m}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(cols)
            for r in rows:
                if r["member"] == m:
                    w.writerow([r["id"], "", "", "", "", "", "", m])

    n = {m: sum(1 for r in rows if r["member"] == m) for m in "ABCD"}
    ww = {m: sum(r["words"] for r in rows if r["member"] == m) for m in "ABCD"}
    print("flow: 900 ->", len(wrong), "->", len(always), "->", len(stop), "->", len(items))
    print("count:", n); print("words:", ww)
    print("length repetition candidates:", sum(1 for e in extra if e["repetition_flag"] is True))


if __name__ == "__main__":
    main()
