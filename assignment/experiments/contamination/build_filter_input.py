"""text_only_filter.py 에 넣을 문항 목록을 만든다 (질문 글만, 이미지 없음).

사용:
  python build_filter_input.py --out-dir omr_out --drop-ids 792

입력 (모두 out-dir 안):
  selection.csv                          build_selection.py 결과 (이미 검사 끝난 후보)
  candidates_pool.csv                    omr_topup.py --out-name candidates_pool.csv 결과 (새 후보)
  contamination_report_pool.csv          새 후보의 MMMU 중복 검사 결과

새 후보는 MMMU 검사에서 keep 인 것만 쓴다. review(해밍 거리 9~12)는 눈 확인을 못 했으므로 뺀다.
새 후보 중 기존 후보나 서로 같은 그림(해밍 거리 ≤ 8)은 먼저 나온 하나만 남긴다.
출력: filter_input.csv (cand_id, source, type, stem, options, answer)
"""
import argparse
import collections
import csv
import os
import re

REFUSAL = re.compile(r"sorry|can.t share|chain-of-thought", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--drop-ids", nargs="*", default=[], help="사람 검수로 뺄 cand_id")
    ap.add_argument("--dup-le", type=int, default=8)
    a = ap.parse_args()
    d = a.out_dir
    rd = lambda name: list(csv.DictReader(open(os.path.join(d, name), encoding="utf-8")))

    sel = [r for r in rd("selection.csv") if r["cand_id"] not in set(a.drop_ids)]
    mmmu = {r["cand_id"]: r["decision"] for r in rd("contamination_report_pool.csv")}
    pool = rd("candidates_pool.csv")
    steps = [("기존 후보(selection)", len(sel)), ("새 후보", len(pool))]
    pool = [r for r in pool if mmmu.get(r["cand_id"]) == "keep"]
    steps.append(("새 후보 MMMU keep", len(pool)))
    pool = [r for r in pool if not REFUSAL.search(r["perception"])]
    steps.append(("새 후보 거부 응답 제외", len(pool)))
    seen = [int(r["phash"], 16) for r in sel]
    kept = []
    for r in pool:
        h = int(r["phash"], 16)
        if any(bin(h ^ x).count("1") <= a.dup_le for x in seen):
            continue
        seen.append(h)
        kept.append(r)
    steps.append(("새 후보 같은 그림 제외", len(kept)))

    out = os.path.join(d, "filter_input.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cand_id", "source", "type", "stem", "options", "answer"])
        for src, rows in (("selection", sel), ("pool", kept)):
            for r in rows:
                w.writerow([r["cand_id"], src, r["type"], r["stem"], r["options"], r["answer"]])
    for name, n in steps:
        print(f"{name:22s} {n}")
    print("유형별:", dict(collections.Counter(r["type"] for r in sel + kept)))
    print("→", out, len(sel) + len(kept), "rows")


if __name__ == "__main__":
    main()
