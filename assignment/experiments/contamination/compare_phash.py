"""후보 이미지 pHash 를 MMMU 색인과 비교해 제외/확인/통과를 매긴다.

사용:
  python compare_phash.py --index mmmu_phash.csv --candidates candidates.csv --out contamination_report.csv
  (--phash-col 로 후보 CSV 의 pHash 열 이름 지정. 기본 phash. Honey 는 image_phashes 열을 그대로 쓰면 됨)
"""
import argparse
import csv
import sys
from collections import Counter

from phash_utils import classify, load_index, nearest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--phash-col", default="phash")
    ap.add_argument("--exclude-le", type=int, default=8)
    ap.add_argument("--review-le", type=int, default=12)
    a = ap.parse_args()

    index = [(i, h) for i, h in load_index(a.index) if not h.startswith("ERROR")]
    print("index size:", len(index))
    cnt = Counter()
    with open(a.candidates, newline="", encoding="utf-8") as f, open(a.out, "w", newline="", encoding="utf-8") as g:
        rd = csv.DictReader(f)
        fields = rd.fieldnames + ["nearest_mmmu", "hamming", "decision"]
        w = csv.DictWriter(g, fieldnames=fields)
        w.writeheader()
        for r in rd:
            ref, d = nearest(r[a.phash_col], index)
            dec = classify(d, a.exclude_le, a.review_le)
            cnt[dec] += 1
            r.update({"nearest_mmmu": ref, "hamming": d, "decision": dec})
            w.writerow(r)
    print("decisions:", dict(cnt), "→", a.out)


if __name__ == "__main__":
    sys.exit(main())
