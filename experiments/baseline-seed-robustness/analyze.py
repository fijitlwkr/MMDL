#!/usr/bin/env python3
"""Aggregate seed-robustness runs and test whether the submitted baseline was a lucky draw.

Input layout (each run dir holds a compact item_results.jsonl, see pack_runs.py):
  <runs_dir>/<arm>/item_results.jsonl      arms: seed_<N> | ctrl_repeat | ctrl_engine
Baseline = results/mmmu_team_baseline/scores/item_results.jsonl (sampling seed 3407).
No third-party dependencies (exact tests use math.comb).
"""
import argparse, json, math, statistics as st
from pathlib import Path

T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}


def load(path):
    rows = {}
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        ok = r.get("final_correct", r.get("correct"))
        rows[r["id"]] = {"subject": r["subject"], "type": r["question_type"], "finish": r["finish_reason"],
                         "correct": bool(ok) if ok is not None else None}
    return rows


def acc(rows, pred=lambda r: True):
    sel = [r for r in rows.values() if pred(r)]
    return 100 * sum(r["correct"] is True for r in sel) / len(sel) if sel else float("nan")


def mcnemar_exact(g, l):
    n = g + l
    if n == 0:
        return 1.0
    k = min(g, l)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def paired(base, other):
    ids = sorted(base)
    g = sum((not base[i]["correct"]) and other[i]["correct"] for i in ids)
    l = sum(base[i]["correct"] and (not other[i]["correct"]) for i in ids)
    n = len(ids)
    diff = (g - l) / n * 100
    se = math.sqrt(max(g + l - (g - l) ** 2 / n, 0)) / n * 100
    return {"gains": g, "losses": l, "flips": g + l, "diff_pp": diff,
            "ci95_pp": [diff - 1.96 * se, diff + 1.96 * se], "mcnemar_p": mcnemar_exact(g, l)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", type=Path, default=Path("results/mmmu_team_baseline/scores/item_results.jsonl"))
    ap.add_argument("--runs_dir", type=Path, default=Path("results/baseline_seed_robustness"))
    ap.add_argument("--out", type=Path, default=Path("results/baseline_seed_robustness/analysis"))
    a = ap.parse_args()

    base = load(a.baseline)
    arms = {p.name: load(p / "item_results.jsonl") for p in sorted(a.runs_dir.iterdir())
            if (p / "item_results.jsonl").exists()}
    for name, r in arms.items():
        assert set(r) == set(base), f"{name}: question IDs differ from baseline"
    seeds = {n: r for n, r in arms.items() if n.startswith("seed_")}
    ctrl = {n: r for n, r in arms.items() if n.startswith("ctrl_")}

    def row(name, r):
        return {"arm": name, "accuracy": acc(r), "correct": sum(x["correct"] is True for x in r.values()),
                "mc": acc(r, lambda x: x["type"] == "multiple-choice"), "open": acc(r, lambda x: x["type"] == "open"),
                "length_finish": sum(x["finish"] == "length" for x in r.values()),
                "acc_on_length": acc(r, lambda x: x["finish"] == "length"),
                "unscored": sum(x["correct"] is None for x in r.values())}

    table = [row("baseline_seed_3407", base)] + [row(n, r) for n, r in arms.items()]
    out = {"runs": table, "paired_vs_baseline": {n: paired(base, r) for n, r in arms.items()}}

    # (A) is the baseline an outlier w.r.t. the independent-seed distribution?
    others = [acc(r) for r in seeds.values()]
    b = acc(base)
    if len(others) >= 2:
        k, m, s = len(others), st.mean(others), st.stdev(others)
        t = T975.get(k - 1, 1.96)
        half = t * s * math.sqrt(1 + 1 / k)
        out["baseline_vs_other_seeds"] = {
            "k_other_seeds": k, "other_mean": m, "other_sd": s, "other_min": min(others), "other_max": max(others),
            "baseline": b, "baseline_minus_mean_pp": b - m, "z": (b - m) / s if s else None,
            "prediction_interval_95": [m - half, m + half], "inside_pi": (m - half) <= b <= (m + half),
            "n_other_seeds_ge_baseline": sum(x >= b for x in others), "baseline_is_max": b >= max(others)}
        allacc = others + [b]
        out["all_sampling_seeds_incl_baseline"] = {"n": len(allacc), "mean": st.mean(allacc), "sd": st.stdev(allacc),
                                                   "range": [min(allacc), max(allacc)]}
    # (B) item-level consistency across all sampling seeds incl. baseline
    pool = [base] + list(seeds.values())
    if len(pool) >= 2:
        always = sum(all(r[i]["correct"] for r in pool) for i in base)
        never = sum(not any(r[i]["correct"] for r in pool) for i in base)
        out["item_consistency"] = {"runs": len(pool), "always_correct": always, "always_wrong": never,
                                   "mixed": len(base) - always - never, "mixed_pct": 100 * (len(base) - always - never) / len(base)}
        subj = {}
        for sname in sorted({x["subject"] for x in base.values()}):
            vals = [acc(r, lambda x, s=sname: x["subject"] == s) for r in pool]
            subj[sname] = {"mean": st.mean(vals), "sd": st.stdev(vals)}
        out["subject_seed_sd_top5"] = dict(sorted(subj.items(), key=lambda kv: -kv[1]["sd"])[:5])
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))

    L = ["# Baseline seed robustness — analysis", "", "| arm | acc % | correct/900 | MC % | open % | length-finish | acc on length-finish % |", "|---|---|---|---|---|---|---|"]
    for r in table:
        L.append(f"| {r['arm']} | {r['accuracy']:.2f} | {r['correct']} | {r['mc']:.2f} | {r['open']:.2f} | {r['length_finish']} | {r['acc_on_length']:.1f} |")
    L += ["", "## Paired vs baseline (same 900 questions)", "", "| arm | gains | losses | flips | diff pp | 95% CI pp | McNemar p |", "|---|---|---|---|---|---|---|"]
    for n, p in out["paired_vs_baseline"].items():
        L.append(f"| {n} | {p['gains']} | {p['losses']} | {p['flips']} | {p['diff_pp']:+.2f} | [{p['ci95_pp'][0]:+.2f}, {p['ci95_pp'][1]:+.2f}] | {p['mcnemar_p']:.3f} |")
    if "baseline_vs_other_seeds" in out:
        o = out["baseline_vs_other_seeds"]
        L += ["", "## Is the baseline an outlier among independent sampling seeds?", "",
              f"- other seeds (k={o['k_other_seeds']}): mean {o['other_mean']:.2f}, sd {o['other_sd']:.2f}, range [{o['other_min']:.2f}, {o['other_max']:.2f}]",
              f"- baseline {o['baseline']:.2f} → {o['baseline_minus_mean_pp']:+.2f} pp from their mean (z = {o['z']:.2f})" if o['z'] is not None else "- sd = 0",
              f"- 95% prediction interval for a new seed: [{o['prediction_interval_95'][0]:.2f}, {o['prediction_interval_95'][1]:.2f}] → baseline inside: {o['inside_pi']}",
              f"- other seeds scoring ≥ baseline: {o['n_other_seeds_ge_baseline']}/{o['k_other_seeds']}; baseline is the maximum: {o['baseline_is_max']}"]
        al = out["all_sampling_seeds_incl_baseline"]
        L.append(f"- all {al['n']} sampling-seed runs incl. baseline: mean {al['mean']:.2f} ± {al['sd']:.2f} (sd), range [{al['range'][0]:.2f}, {al['range'][1]:.2f}]")
    if "item_consistency" in out:
        c = out["item_consistency"]
        L += ["", f"## Item-level consistency over {c['runs']} sampling-seed runs", "",
              f"- always correct {c['always_correct']}, always wrong {c['always_wrong']}, mixed {c['mixed']} ({c['mixed_pct']:.1f}%)", "",
              "Largest across-seed sd by subject (pp, 30 questions each → coarse):"] + [f"- {k}: mean {v['mean']:.1f}, sd {v['sd']:.1f}" for k, v in out["subject_seed_sd_top5"].items()]
    if ctrl:
        L += ["", "## Controls", "", "- ctrl_repeat = identical config & seeds as baseline (measures hardware/batch non-determinism, not seed effect)",
              "- ctrl_engine = only LLM(engine) seed changed (tests whether engine_seed influences outputs when every request carries its own seed)"]
    (a.out / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
