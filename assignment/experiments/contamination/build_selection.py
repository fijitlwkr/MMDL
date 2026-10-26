"""후보(candidates.csv + candidates_topup.csv)에 필터를 적용해 학습 후보 목록을 만든다.

사용:
  python build_selection.py --out-dir omr_out

입력 (모두 out-dir 안):
  candidates.csv, candidates_topup.csv     omr_select.py / omr_topup.py 결과
  answer_labels.csv                        정답 종류 라벨 (cand_id, label, labeled_by)
  contamination_report*.csv                compare_phash.py 결과

필터:
  1. 정답 종류가 visual 또는 anatomy 인 것만 (diagnosis, other, normal 제외)
  2. 거부 응답 제외
  3. MMMU 중복 검사에서 exclude 인 것 제외 (review 는 표시만 하고 남김)
  4. 후보끼리 같은 그림(해밍 거리 ≤ 8)은 먼저 나온 하나만

출력: selection.csv (남은 후보 + label, mmmu_check 열), 단계별 개수 출력
"""
import argparse
import collections
import csv
import glob
import os
import re

REFUSAL = re.compile(r"sorry|can.t share|chain-of-thought", re.I)
KEEP_LABELS = {"visual", "anatomy"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--dup-le", type=int, default=8)
    a = ap.parse_args()
    d = a.out_dir

    rows = []
    for name in ["candidates.csv", "candidates_topup.csv"]:
        p = os.path.join(d, name)
        if os.path.exists(p):
            rows += list(csv.DictReader(open(p, encoding="utf-8")))
    labels = {r["cand_id"]: r["label"] for r in csv.DictReader(open(os.path.join(d, "answer_labels.csv"), encoding="utf-8"))}
    mmmu = {}
    for p in glob.glob(os.path.join(d, "contamination_report*.csv")):
        for r in csv.DictReader(open(p, encoding="utf-8")):
            mmmu[r["cand_id"]] = r["decision"]

    steps = [("전체 후보", len(rows))]
    rows = [r for r in rows if labels.get(r["cand_id"]) in KEEP_LABELS]
    steps.append(("정답 종류 visual/anatomy", len(rows)))
    rows = [r for r in rows if not REFUSAL.search(r["perception"])]
    steps.append(("거부 응답 제외", len(rows)))
    rows = [r for r in rows if mmmu.get(r["cand_id"]) != "exclude"]
    steps.append(("MMMU 중복 제외", len(rows)))
    kept, seen = [], []
    for r in rows:
        h = int(r["phash"], 16)
        if any(bin(h ^ x).count("1") <= a.dup_le for x in seen):
            continue
        seen.append(h)
        kept.append(r)
    steps.append(("후보끼리 같은 그림 제외", len(kept)))

    out = os.path.join(d, "selection.csv")
    fields = list(kept[0].keys()) + ["label", "mmmu_check"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in kept:
            r = dict(r)
            r["label"] = labels[r["cand_id"]]
            r["mmmu_check"] = mmmu.get(r["cand_id"], "")
            w.writerow(r)

    for name, n in steps:
        print(f"{name:24s} {n}")
    print("유형별:", dict(collections.Counter(r["type"] for r in kept)))
    print("정답 종류별:", dict(collections.Counter(labels[r["cand_id"]] for r in kept)))
    print("MMMU 눈 확인 필요(review):", sum(mmmu.get(r["cand_id"]) == "review" for r in kept))
    print("→", out)


if __name__ == "__main__":
    main()
