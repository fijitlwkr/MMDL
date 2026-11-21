#!/usr/bin/env python3
"""같은 900문항을 문항별로 짝지어 E0 seed 42 와 비교한다(McNemar 정확 검정). API 호출·GPU 없음.

  python experiments/hypA-eval/paired.py --runs <pack_runs.py 로 묶은 폴더> --e0 <baseline 시드 실험 결과 폴더> \
      --arms g30,g25,g50,g75,g100 --out <출력 폴더>

--runs 안의 <조건>_seed_42/item_results.jsonl, --e0 안의 seed_<시드>/item_results.jsonl 을 읽는다. 출력: PAIRED.md
  1. 조건별 정확도, E0 seed 42 대비 맞힘/틀림 문항 수, 차이와 95% CI, McNemar p, 잘림(length) 수
  2. 의료 5과목 150문항만 같은 비교
  3. --chain 의 이웃한 체크포인트끼리 정답 여부가 다른 문항 수(같은 학습의 체크포인트만. 기본 g25,g50,g75,g100)
"""
import argparse, json, math
from pathlib import Path

MEDICAL = {"Basic_Medical_Science", "Clinical_Medicine", "Diagnostics_and_Laboratory_Medicine", "Pharmacy", "Public_Health"}


def load(p):
    return {r["id"]: r for r in map(json.loads, open(p, encoding="utf-8"))}


def ok(r):
    return bool(r["final_correct"])


def mcnemar(a, b, ids):
    gain = sum(ok(b[i]) and not ok(a[i]) for i in ids)
    loss = sum(ok(a[i]) and not ok(b[i]) for i in ids)
    n = len(ids); d = (gain - loss) / n * 100
    se = math.sqrt(gain + loss - (gain - loss) ** 2 / n) / n * 100
    k, m = min(gain, loss), gain + loss
    p = min(1.0, 2 * sum(math.comb(m, j) for j in range(k + 1)) / 2 ** m) if m else 1.0
    return gain, loss, d, d - 1.96 * se, d + 1.96 * se, p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--e0", type=Path, required=True)
    ap.add_argument("--arms", default="g30,g25,g50,g75,g100")
    ap.add_argument("--chain", default="g25,g50,g75,g100")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    arms = a.arms.split(",")
    e0 = {s: load(a.e0 / f"seed_{s}" / "item_results.jsonl") for s in (42, 1234, 2026)}
    runs = {arm: load(a.runs / f"{arm}_seed_42" / "item_results.jsonl") for arm in arms}
    ids = sorted(e0[42])
    assert len(ids) == 900 and all(set(r) == set(ids) for r in runs.values())
    med = [i for i in ids if e0[42][i]["subject"] in MEDICAL]

    L = [f"# 문항별 비교 (seed 42)", "",
         f"`paired.py --arms {a.arms}` 가 만든 파일이다. 기준은 E0 seed 42. 같은 문항의 정답 여부를 짝지어 McNemar 정확 검정(양측)을 했다.", "",
         "## 1. 전체 900문항", "",
         "| 조건 | 정확도 | E0 대비 | 맞힘 / 틀림 | 95% CI | p | 잘림(length) |", "|---|---|---|---|---|---|---|"]
    ln = lambda d: sum(r["finish_reason"] == "length" for r in d.values())
    L.append(f"| E0 | {sum(map(ok, e0[42].values())) / 9:.2f} | - | - | - | - | {ln(e0[42])} |")
    for arm in arms:
        g, l, d, lo, hi, p = mcnemar(e0[42], runs[arm], ids)
        L.append(f"| {arm.upper()} | {sum(map(ok, runs[arm].values())) / 9:.2f} | {d:+.2f} | {g} / {l} | [{lo:+.2f}, {hi:+.2f}] | {p:.2f} | {ln(runs[arm])} |")
    L += ["", "E0 다른 시드: " + ", ".join(f"seed {s} {sum(map(ok, e0[s].values())) / 9:.2f}" for s in (1234, 2026)) +
          ". E0 seed 42 와 정답 여부가 다른 문항: " + ", ".join(f"seed {s} {sum(ok(e0[42][i]) != ok(e0[s][i]) for i in ids)}" for s in (1234, 2026)) + ".", ""]

    L += ["## 2. 의료 5과목 150문항", "", "| 조건 | 정답 수 | 맞힘 / 틀림 | p |", "|---|---|---|---|",
          "| E0 | " + " / ".join(f"{sum(ok(e0[s][i]) for i in med)}" for s in (42, 1234, 2026)) + " (seed 42 / 1234 / 2026) | - | - |"]
    for arm in arms:
        g, l, d, lo, hi, p = mcnemar(e0[42], runs[arm], med)
        L.append(f"| {arm.upper()} | {sum(ok(runs[arm][i]) for i in med)} | {g} / {l} | {p:.2f} |")

    chain = [c for c in a.chain.split(",") if c in runs]
    L += ["", "## 3. 같은 학습의 이웃한 체크포인트끼리", "", "| 비교 | 정답 여부가 다른 문항 | 차이 | p |", "|---|---|---|---|"]
    for x, y in zip(chain, chain[1:]):
        g, l, d, lo, hi, p = mcnemar(runs[x], runs[y], ids)
        L.append(f"| {x.upper()} → {y.upper()} | {g + l} | {d:+.2f} | {p:.2f} |")
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "PAIRED.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
