#!/usr/bin/env python3
"""가설 A 결과 분석: E1~E3 × 시드 채점 결과를 E0(baseline 시드 실험)와 비교한다. API 호출·GPU 없음.

  python experiments/hypA-eval/analyze.py --runs <pack_runs.py 로 묶은 폴더> --e0 <baseline 시드 실험 결과 폴더> --out <출력 폴더>

--runs 안의 <e1|e2|e3>_seed_<시드>/, --e0 안의 seed_<시드>/ 에서 item_results.jsonl 과 raw.jsonl.gz 를 읽는다.
출력: summary.json, REPORT.md
  1. 실행별·조건별 정확도 (시드 평균·표준편차·범위)
  2. 의료 5과목과 나머지 과목의 정확도
  3. 답 형식: OMR 학습 응답 형식("Observation:"으로 시작)으로 답한 비율과 출력 토큰 중앙값
  4. E0 대비 정답 수 변화를 (의료/나머지) × (짧은 형식/긴 풀이)로 나눈 것. 같은 문항의 E0 시드 평균 정답률과 비교한다.
  5. 규칙 파서 점검: 규칙으로 채점된 객관식 중 답 끝 600자에서 마지막으로 밝힌 답 글자가 채점된 답과 다른 문항 수 (정규식 간이 점검)
"""
import argparse, collections, gzip, json, re, statistics as st
from pathlib import Path

MEDICAL = {"Basic_Medical_Science", "Clinical_Medicine", "Diagnostics_and_Laboratory_Medicine", "Pharmacy", "Public_Health"}
ARMS = ["e0", "e1", "e2", "e3"]
SEEDS = [42, 1234, 2026]
STATED = re.compile(r"(?:Final Answer|correct answer is|correct option is|Answer)\s*[:：]?\s*\**\s*(?:Option\s*)?\(?([A-I])\b", re.I)


def load_run(d):
    items = {r["id"]: r for r in map(json.loads, open(d / "item_results.jsonl", encoding="utf-8"))}
    with gzip.open(d / "raw.jsonl.gz", "rt", encoding="utf-8") as f:
        for r in map(json.loads, f):
            items[r["id"]]["raw_text"] = r["raw_text"]
    return items


def short_form(r):
    return r["raw_text"].lstrip().startswith("Observation:")


def acc(rows):
    rows = list(rows)
    return sum(bool(r["final_correct"]) for r in rows) / len(rows) * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--e0", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    runs = {("e0", s): load_run(a.e0 / f"seed_{s}") for s in SEEDS}
    runs.update({(arm, s): load_run(a.runs / f"{arm}_seed_{s}") for arm in ARMS[1:] for s in SEEDS})
    ids = sorted(runs[("e0", 42)])
    assert all(sorted(r) == ids for r in runs.values()), "실행마다 문항 목록이 다름"
    med = [i for i in ids if runs[("e0", 42)][i]["subject"] in MEDICAL]
    oth = [i for i in ids if i not in set(med)]
    e0_mean = {i: st.mean(bool(runs[("e0", s)][i]["final_correct"]) for s in SEEDS) for i in ids}
    out = {"seeds": SEEDS, "n_items": len(ids), "n_medical": len(med), "arms": {}}

    for arm in ARMS:
        rs = [runs[(arm, s)] for s in SEEDS]
        per_seed = [acc(r.values()) for r in rs]
        o = {"accuracy_by_seed": dict(zip(map(str, SEEDS), per_seed)), "mean": st.mean(per_seed), "sd": st.stdev(per_seed),
             "medical": st.mean(acc(r[i] for i in med) for r in rs), "other": st.mean(acc(r[i] for i in oth) for r in rs)}
        for name, sub in (("medical", med), ("other", oth)):
            o[f"short_form_share_{name}"] = st.mean(sum(short_form(r[i]) for i in sub) / len(sub) * 100 for r in rs)
            o[f"median_output_tokens_{name}"] = st.mean(st.median(r[i]["output_tokens"] for i in sub) for r in rs)
        # E0 대비 정답 수 변화: 그룹마다 (이 실행의 정답 수 − 같은 문항의 E0 시드 평균 정답 수), 시드 평균
        groups = collections.defaultdict(lambda: [0, 0.0, 0.0])
        for r in rs:
            for i in ids:
                g = ("medical" if i in set(med) else "other") + ("_short" if short_form(r[i]) else "_long")
                groups[g][0] += 1; groups[g][1] += bool(r[i]["final_correct"]); groups[g][2] += e0_mean[i]
        o["change_vs_e0"] = {g: {"items_per_seed": n / len(SEEDS), "accuracy": c / n * 100, "e0_accuracy_same_items": c0 / n * 100,
                                 "correct_change_per_seed": (c - c0) / len(SEEDS)} for g, (n, c, c0) in sorted(groups.items())}
        mism = []
        for s, r in zip(SEEDS, rs):
            k = 0
            for x in r.values():
                if x["question_type"] == "open" or x["final_status"] != "complete_rule":
                    continue
                m = list(STATED.finditer(x["raw_text"][-600:]))
                k += bool(m) and m[-1].group(1).upper() != x["final_answer"]
            mism.append(k)
        o["rule_parse_mismatch_by_seed"] = dict(zip(map(str, SEEDS), mism))
        out["arms"][arm] = o

    subjects = sorted({r["subject"] for r in runs[("e0", 42)].values()})
    out["subjects"] = {sub: {arm: st.mean(acc(runs[(arm, s)][i] for i in ids if runs[(arm, s)][i]["subject"] == sub) for s in SEEDS)
                             for arm in ARMS} for sub in subjects}

    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    A = out["arms"]
    L = ["# 가설 A 결과 분석", "", "`analyze.py` 가 만든 파일이다. E0 는 baseline 시드 실험(seed 42/1234/2026), 나머지는 `results/hypA_eval/`.", "",
         "## 1. 정확도 (%)", "", "| 조건 | seed 42 | seed 1234 | seed 2026 | 평균 | 표준편차 | E0 대비 |", "|---|---|---|---|---|---|---|"]
    for arm in ARMS:
        b = A[arm]["accuracy_by_seed"]
        L.append(f"| {arm.upper()} | {b['42']:.2f} | {b['1234']:.2f} | {b['2026']:.2f} | {A[arm]['mean']:.2f} | {A[arm]['sd']:.2f} | "
                 f"{A[arm]['mean'] - A['e0']['mean']:+.2f} |")
    L += ["", f"## 2. 의료 5과목({len(med)}문항)과 나머지({len(oth)}문항), 시드 평균 (%)", "",
          "| 조건 | 의료 | 나머지 | 의료 답 중 짧은 형식 | 나머지 답 중 짧은 형식 | 출력 토큰 중앙값 (의료 / 나머지) |", "|---|---|---|---|---|---|"]
    for arm in ARMS:
        x = A[arm]
        L.append(f"| {arm.upper()} | {x['medical']:.1f} | {x['other']:.1f} | {x['short_form_share_medical']:.0f}% | {x['short_form_share_other']:.0f}% | "
                 f"{x['median_output_tokens_medical']:.0f} / {x['median_output_tokens_other']:.0f} |")
    L += ["", "짧은 형식 = 답이 \"Observation:\"으로 시작(OMR 학습 응답 형식).", "",
          "## 3. E0 대비 정답 수 변화 (시드당 문항 수)", "",
          "같은 문항에서 E0 시드 평균 정답률과 비교했다. 형식은 각 실행의 답 기준이다.", "",
          "| 조건 | 의료·짧은 형식 | 의료·긴 풀이 | 나머지·짧은 형식 | 나머지·긴 풀이 | 합계 |", "|---|---|---|---|---|---|"]
    for arm in ARMS[1:]:
        c = A[arm]["change_vs_e0"]
        cell = lambda g: (f"{c[g]['correct_change_per_seed']:+.1f} ({c[g]['items_per_seed']:.0f}문항, "
                          f"{c[g]['e0_accuracy_same_items']:.0f}→{c[g]['accuracy']:.0f}%)") if g in c else "-"
        tot = sum(v["correct_change_per_seed"] for v in c.values())
        L.append(f"| {arm.upper()} | {cell('medical_short')} | {cell('medical_long')} | {cell('other_short')} | {cell('other_long')} | {tot:+.1f} |")
    L += ["", "## 4. 규칙 파서 간이 점검 (실행별 문항 수)", "",
          "규칙으로 채점된 객관식 중, 답 끝 600자에서 마지막으로 밝힌 답 글자가 채점된 답과 다른 문항. 정규식 기반이라 정확한 개수는 아니다.", "",
          "| 조건 | seed 42 | seed 1234 | seed 2026 |", "|---|---|---|---|"]
    for arm in ARMS:
        m = A[arm]["rule_parse_mismatch_by_seed"]
        L.append(f"| {arm.upper()} | {m['42']} | {m['1234']} | {m['2026']} |")
    L += ["", "## 5. 과목별 정확도 (시드 평균, %, E1~E3 평균의 E0 대비 변화순)", "", "| 과목 | E0 | E1 | E2 | E3 | 변화 |", "|---|---|---|---|---|---|"]
    rows = sorted(out["subjects"].items(), key=lambda kv: st.mean(kv[1][x] for x in ARMS[1:]) - kv[1]["e0"])
    for sub, v in rows:
        L.append(f"| {sub}{' (의료)' if sub in MEDICAL else ''} | {v['e0']:.1f} | {v['e1']:.1f} | {v['e2']:.1f} | {v['e3']:.1f} | "
                 f"{st.mean(v[x] for x in ARMS[1:]) - v['e0']:+.1f} |")
    L.append("\n과목당 30문항이라 과목 하나의 차이는 오차가 크다(1문항 = 3.3%p).")
    (a.out / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
