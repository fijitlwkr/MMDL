"""omr_select.py 로 뽑은 후보에 더해, 아직 안 쓴 행에서 유형별로 추가 후보를 뽑는다.

사용:
  python omr_topup.py --cache-dir data_cache --out-dir omr_out --shards 4 \
      --quota findings=260,marker=140,anatomy=20,count=20,location=15

--exclude 로 준 후보 CSV(기본 candidates.csv)의 omr_row 는 건너뛰고, 같은 필터(시그널 단어, 긴 질문,
지각 단락 추출, 거부 응답)를 적용한다. 결과는 --out-name(기본 candidates_topup.csv)과 images/ 에 저장한다.
--no-images 면 이미지는 저장하지 않고 pHash 만 계산한다(최종 선정 후 export_omr.py 로 꺼냄).
"""
import argparse
import csv
import os
import random
import re
import sys

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

from omr_select import PERC_RE, REPO, SEED, classify, split_stem
from phash_utils import phash_from_bytes

REFUSAL = re.compile(r"sorry|can.t share|chain-of-thought", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--shards", type=int, default=4)
    ap.add_argument("--quota", required=True, help="유형=건수, 쉼표 구분")
    ap.add_argument("--max-stem", type=int, default=300)
    ap.add_argument("--max-perc-words", type=int, default=120)
    ap.add_argument("--exclude", nargs="+", default=["candidates.csv"], help="이미 뽑은 후보 CSV (out-dir 기준)")
    ap.add_argument("--out-name", default="candidates_topup.csv")
    ap.add_argument("--seed-offset", type=int, default=1)
    ap.add_argument("--no-images", action="store_true")
    a = ap.parse_args()
    quota = {k: int(v) for k, v in (x.split("=") for x in a.quota.split(","))}

    prev = [r for name in a.exclude for r in csv.DictReader(open(os.path.join(a.out_dir, name), encoding="utf-8"))]
    used = {int(r["omr_row"]) for r in prev}
    next_id = 1 + max(int(r["cand_id"]) for r in prev)

    pool = {t: [] for t in quota}
    for s in range(a.shards):
        fn = f"data/train-{s:05d}-of-00031.parquet"
        path = hf_hub_download(REPO, fn, repo_type="dataset", cache_dir=a.cache_dir)
        pf = pq.ParquetFile(path)
        row = s * 5000
        for batch in pf.iter_batches(batch_size=500, columns=["image", "question", "reasoning", "answer"]):
            d = batch.to_pydict()
            for i in range(len(d["question"])):
                rid = row
                row += 1
                if rid in used:
                    continue
                stem, opts = split_stem(d["question"][i])
                t = classify(stem)
                if t not in quota or len(stem) > a.max_stem:
                    continue
                m = PERC_RE.search(d["reasoning"][i])
                if not m:
                    continue
                perc = re.sub(r"\s+", " ", m.group(1)).strip()
                if REFUSAL.search(perc) or len(perc.split()) > a.max_perc_words:
                    continue
                pool[t].append({"omr_row": rid, "type": t, "stem": stem, "options": opts,
                                "answer": d["answer"][i], "perception": perc,
                                "image_bytes": d["image"][i]["bytes"]})

    rng = random.Random(SEED + a.seed_offset)
    chosen = []
    for t, n in quota.items():
        rng.shuffle(pool[t])
        chosen += pool[t][:n]
        print(f"{t}: pool {len(pool[t])}, take {min(n, len(pool[t]))}")

    img_dir = os.path.join(a.out_dir, "images")
    out_csv = os.path.join(a.out_dir, a.out_name)
    if os.path.exists(out_csv):
        sys.exit(f"{out_csv} 이 이미 있음. 다른 --out-name 을 쓸 것")
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cand_id", "omr_row", "type", "stem", "options", "answer", "perception", "phash", "image_file"])
        for k, c in enumerate(chosen):
            fn = f"omr_{c['omr_row']:06d}.jpg"
            if not a.no_images:
                with open(os.path.join(img_dir, fn), "wb") as g:
                    g.write(c["image_bytes"])
            w.writerow([next_id + k, c["omr_row"], c["type"], c["stem"], c["options"], c["answer"],
                        c["perception"], phash_from_bytes(c["image_bytes"]), fn])
    print("→", out_csv, len(chosen), "rows")


if __name__ == "__main__":
    sys.exit(main())
