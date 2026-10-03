#!/usr/bin/env python3
"""Aggregate seed-robustness runs and test whether the submitted baseline was a lucky draw.

Reads  <runs_dir>/<arm>/item_results.jsonl  (made by score_runs.sh -> pack_runs.py). Arm groups by name:
  seed_*                      independent sampling seeds (the experiment variable)
  ctrl_repeat, rep_*          same-seed repeats (hardware / host / batch non-determinism; rep_* = earlier repo runs)
  rescore_*                   same raw, fresh Judge calls (Judge noise only)
Baseline = results/mmmu_team_baseline (sampling seed 3407). Arms with any unscored item are excluded (warned).
Stdlib only. Trigger thresholds are fixed in README s4 BEFORE results are seen.
"""
import argparse, json, math, statistics as st
from pathlib import Path

T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}
Z_TRIGGER, SD_TRIGGER_PP = 1.5, 1.0   # Tier-2 trigger thresholds (README s4)


def load(path):
    rows = {}
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        ok = r.get("final_correct", r.get("correct"))
        rows[r["id"]] = {"subject": r["subject"], "type": r["question_type"], "finish": r["finish_reason"],
                         "correct": None if ok is None else bool(ok)}
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
    return {"gains": g, "losses": l, "flips": g + l, "flip_pct": 100 * (g + l) / n, "diff_pp": diff,
            "ci95_pp": [diff - 1.96 * se, diff + 1.96 * se], "mcnemar_p": mcnemar_exact(g, l)}


def group(name):
    if name.startswith("seed_"): return "seed"
    if name == "ctrl_repeat" or name.startswith("rep_"): return "repeat"
    if name.startswith("rescore_"): return "judge"
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", type=Path, default=Path("results/mmmu_team_baseline/scores/item_results.jsonl"))
    ap.add_argument("--runs_dir", type=Path, default=Path("results/baseline_seed_robustness"))
    ap.add_argument("--out", type=Path, default=Path("results/baseline_seed_robustness/analysis"))
    a = ap.parse_args()

    base = load(a.baseline)
    assert all(r["correct"] is not None for r in base.values()), "baseline has unscored items"
    arms, excluded = {}, []
    for p in sorted(a.runs_dir.iterdir()):
        f = p / "item_results.jsonl"
        if not f.exists():
            continue
        r = load(f)
        assert set(r) == set(base), f"{p.name}: question IDs differ from baseline"
        if any(x["correct"] is None for x in r.values()):
            excluded.append(p.name); continue
        arms[p.name] = r
    G = {g: {n: r for n, r in arms.items() if group(n) == g} for g in ("seed", "repeat", "judge", "other")}

    def row(name, r):
        return {"arm": name, "group": group(name) if name != "baseline_seed_3407" else "baseline", "accuracy": acc(r),
                "correct": sum(x["correct"] is True for x in r.values()),
                "mc": acc(r, lambda x: x["type"] == "multiple-choice"), "open": acc(r, lambda x: x["type"] == "open"),
                "length_finish": sum(x["finish"] == "length" for x in r.values()),
                "acc_on_length": acc(r, lambda x: x["finish"] == "length")}

    out = {"excluded_unscored": excluded,
           "runs": [row("baseline_seed_3407", base)] + [row(n, r) for n, r in arms.items()],
           "paired_vs_baseline": {n: paired(base, r) for n, r in arms.items()}}
    b = acc(base)
    seeds = [acc(r) for r in G["seed"].values()]
    k = len(seeds)
    trig = {"tier2_run_it": None, "tier2_reasons": [], "tier3_run_it": None}
    if k >= 2:
        m, s = st.mean(seeds), st.stdev(seeds)
        half = T975.get(k - 1, 1.96) * s * math.sqrt(1 + 1 / k)
        z = (b - m) / s if s else float("inf")
        inside = (m - half) <= b <= (m + half)
        out["baseline_vs_seeds"] = {"k": k, "seed_mean": m, "seed_sd": s, "seed_min": min(seeds), "seed_max": max(seeds),
                                    "baseline": b, "baseline_minus_mean_pp": b - m, "z": z,
                                    "pi95": [m - half, m + half], "inside_pi": inside,
                                    "n_seeds_ge_baseline": sum(x >= b for x in seeds)}
        allv = seeds + [b]
        out["all_seed_runs_incl_baseline"] = {"n": len(allv), "mean": st.mean(allv), "sd": st.stdev(allv), "range": [min(allv), max(allv)]}
        reasons = []
        if not inside: reasons.append("baseline outside the 95% prediction interval")
        if abs(z) > Z_TRIGGER: reasons.append(f"|z|={abs(z):.2f} > {Z_TRIGGER}")
        if s > SD_TRIGGER_PP: reasons.append(f"seed sd {s:.2f} pp > {SD_TRIGGER_PP} pp")
        trig.update(tier2_run_it=bool(reasons) and k < 5, tier2_reasons=reasons, tier3_run_it=(not inside) and "ctrl_repeat" not in G["repeat"])
        pool = [base] + list(G["seed"].values())
        always = sum(all(r[i]["correct"] for r in pool) for i in base)
        never = sum(not any(r[i]["correct"] for r in pool) for i in base)
        out["item_consistency"] = {"runs": len(pool), "always_correct": always, "always_wrong": never,
                                   "mixed": len(base) - always - never, "mixed_pct": 100 * (len(base) - always - never) / len(base)}
    out["triggers"] = trig
    rep = [acc(r) for r in G["repeat"].values()]
    if rep:
        allr = rep + [b]
        out["same_seed_repeats_incl_baseline"] = {"n": len(allr), "mean": st.mean(allr), "sd": st.stdev(allr) if len(allr) > 1 else None,
                                                  "range": [min(allr), max(allr)]}
    flips = {g: [out["paired_vs_baseline"][n]["flip_pct"] for n in G[g]] for g in ("seed", "repeat", "judge") if G[g]}
    out["mean_flip_pct_vs_baseline"] = {g: st.mean(v) for g, v in flips.items()}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))

    L = ["# Baseline seed robustness - analysis", ""]
    if excluded: L += [f"WARNING: excluded (unscored items remain): {', '.join(excluded)}", ""]
    L += ["| arm | group | acc % | correct/900 | MC % | open % | length-finish | acc on length-finish % |", "|---|---|---|---|---|---|---|---|"]
    for r in out["runs"]:
        L.append(f"| {r['arm']} | {r['group']} | {r['accuracy']:.2f} | {r['correct']} | {r['mc']:.2f} | {r['open']:.2f} | {r['length_finish']} | {r['acc_on_length']:.1f} |")
    L += ["", "## Paired vs baseline (same 900 questions)", "", "| arm | gains | losses | flips (%) | diff pp | 95% CI pp | McNemar p |", "|---|---|---|---|---|---|---|"]
    for n, p in out["paired_vs_baseline"].items():
        L.append(f"| {n} | {p['gains']} | {p['losses']} | {p['flips']} ({p['flip_pct']:.1f}) | {p['diff_pp']:+.2f} | [{p['ci95_pp'][0]:+.2f}, {p['ci95_pp'][1]:+.2f}] | {p['mcnemar_p']:.3f} |")
    if out["mean_flip_pct_vs_baseline"]:
        L += ["", "Mean flip % vs baseline by group: " + ", ".join(f"{g} {v:.1f}%" for g, v in out["mean_flip_pct_vs_baseline"].items())]
    if "baseline_vs_seeds" in out:
        o = out["baseline_vs_seeds"]
        L += ["", "## Is the baseline an outlier among independent sampling seeds?", "",
              f"- other seeds (k={o['k']}): mean {o['seed_mean']:.2f}, sd {o['seed_sd']:.2f}, range [{o['seed_min']:.2f}, {o['seed_max']:.2f}]",
              f"- baseline {o['baseline']:.2f} -> {o['baseline_minus_mean_pp']:+.2f} pp from their mean (z = {o['z']:.2f})",
              f"- 95% prediction interval for one new seed: [{o['pi95'][0]:.2f}, {o['pi95'][1]:.2f}] -> baseline inside: {o['inside_pi']}",
              f"- seeds scoring >= baseline: {o['n_seeds_ge_baseline']}/{o['k']}"]
        al = out["all_seed_runs_incl_baseline"]
        L.append(f"- all {al['n']} runs incl. baseline: mean {al['mean']:.2f} +- {al['sd']:.2f} (sd), range [{al['range'][0]:.2f}, {al['range'][1]:.2f}]")
        c = out["item_consistency"]
        L += ["", f"## Item-level consistency over {c['runs']} runs", "",
              f"- always correct {c['always_correct']}, always wrong {c['always_wrong']}, mixed {c['mixed']} ({c['mixed_pct']:.1f}%)"]
    if "same_seed_repeats_incl_baseline" in out:
        r = out["same_seed_repeats_incl_baseline"]
        L += ["", "## Same-seed repeats (baseline + repeats; different hosts/drivers for rep_*)", "",
              f"- n={r['n']}: mean {r['mean']:.2f}, sd {('%.2f' % r['sd']) if r['sd'] is not None else 'n/a'}, range [{r['range'][0]:.2f}, {r['range'][1]:.2f}]"]
    L += ["", "## Pre-registered triggers (README s4)", "",
          f"- Tier 2 (seed_777, seed_31337): {'RUN' if trig['tier2_run_it'] else 'not needed' if k >= 2 else 'n/a (need >=2 seeds)'}"
          + (f" - {'; '.join(trig['tier2_reasons'])}" if trig["tier2_reasons"] else ""),
          f"- Tier 3 (ctrl_repeat on this pod): {'RUN' if trig['tier3_run_it'] else 'not needed'}"]
    (a.out / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
