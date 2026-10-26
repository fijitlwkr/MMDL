"""OpenMedReason(neginb/OpenMedReason)에서 perception 유형 문항을 고르고 지각 단락을 추출한다.

사용:
  python omr_select.py --cache-dir <다운로드 폴더> --out-dir <결과 폴더> --shards 4 --n 900

처리:
  1. 질문 키워드로 perception 6유형(소견, 해부·위치, 정상/비정상, 마커, 공간 위치, 개수)만 남기고
     진단·치료·기전 질문은 뺀다.
  2. 질문 본문(보기 제외)이 --max-stem 자 넘는 긴 임상 지문은 뺀다.
  3. reasoning 에서 `<think>` 뒤 ~ "The relevant medical principle" 앞을 지각 단락으로 자른다.
  4. 유형별로 고르게 --n 건을 뽑아 candidates.csv 와 이미지(images/*.jpg), pHash 를 저장한다.
"""
import argparse
import csv
import os
import random
import re
import sys

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

from phash_utils import phash_from_bytes

REPO = "neginb/OpenMedReason"
SEED = 3407

TYPE_PATTERNS = {  # 유형 → 질문 키워드 (대소문자 무시)
    "marker": r"\b(arrow(head)?s?|asterisks?|circled?|boxe?d?|dashed|markers?|label(l?ed)?|pointer|outlined?)\b",
    "location": r"\b(where|which (region|quadrant|side|lobe|part|area|zone)|located|location|quadrant)\b",
    "count": r"\bhow many\b",
    "normal": r"normal or abnormal|normal vs|abnormal or normal",
    "findings": r"(primary|main|predominant|dominant|key) (imaging |visual |radiographic )?finding|best describes|most prominent|what is (seen|shown|visible)",
    "anatomy": r"\bwhich (organ|structure|bone|vessel|anatomic\w*|tissue|cell type)\b|what (organ|structure) is",
}
EXCLUDE = r"most likely diagnosis|next[- ]step|management|treatment|mechanism|pathophysiolog|prognosis|complication|drug|therap|differential|most appropriate|should be (performed|ordered)"
PERC_RE = re.compile(r"<think>\s*(.*?)\s*(?:The relevant (medical|clinical) principle|Next, I)", re.S)


def split_stem(q):
    """질문 본문과 보기 분리. 보기는 'A.' 로 시작하는 줄부터."""
    m = re.search(r"(?m)^\s*A[\.\)]", q)
    return (q[: m.start()].strip(), q[m.start():].strip()) if m else (q.strip(), "")


def classify(stem):
    if re.search(EXCLUDE, stem, re.I):
        return None
    for t, pat in TYPE_PATTERNS.items():
        if re.search(pat, stem, re.I):
            return t
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--shards", type=int, default=4, help="읽을 train parquet 개수(각 5,000행)")
    ap.add_argument("--n", type=int, default=900, help="최종 후보 수")
    ap.add_argument("--max-stem", type=int, default=300)
    ap.add_argument("--max-perc-words", type=int, default=120)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    img_dir = os.path.join(a.out_dir, "images")
    os.makedirs(img_dir, exist_ok=True)

    pool = {t: [] for t in TYPE_PATTERNS}
    stats = {"rows": 0, "excluded_kw": 0, "no_type": 0, "long_stem": 0, "no_perc": 0, "kept": 0}
    for s in range(a.shards):
        fn = f"data/train-{s:05d}-of-00031.parquet"
        path = hf_hub_download(REPO, fn, repo_type="dataset", cache_dir=a.cache_dir)
        pf = pq.ParquetFile(path)
        base = s * 5000
        for bi, batch in enumerate(pf.iter_batches(batch_size=500, columns=["image", "question", "reasoning", "answer"])):
            d = batch.to_pydict()
            for i in range(len(d["question"])):
                stats["rows"] += 1
                q, r, ans = d["question"][i], d["reasoning"][i], d["answer"][i]
                stem, opts = split_stem(q)
                if re.search(EXCLUDE, stem, re.I):
                    stats["excluded_kw"] += 1
                    continue
                t = classify(stem)
                if not t:
                    stats["no_type"] += 1
                    continue
                if len(stem) > a.max_stem:
                    stats["long_stem"] += 1
                    continue
                m = PERC_RE.search(r)
                if not m:
                    stats["no_perc"] += 1
                    continue
                perc = re.sub(r"\s+", " ", m.group(1)).strip()
                if len(perc.split()) > a.max_perc_words:
                    stats["no_perc"] += 1
                    continue
                row_id = base + bi * 500 + i
                pool[t].append({
                    "omr_row": row_id, "type": t, "stem": stem, "options": opts, "answer": ans,
                    "perception": perc, "image_bytes": d["image"][i]["bytes"],
                })
                stats["kept"] += 1
        print(f"shard {s}: kept so far", {t: len(v) for t, v in pool.items()}, flush=True)

    # 유형별 고르게 뽑기 (부족한 유형은 있는 만큼, 나머지는 다른 유형에서 채움)
    rng = random.Random(SEED)
    for v in pool.values():
        rng.shuffle(v)
    per = a.n // len(pool)
    chosen, leftovers = [], []
    for t, v in pool.items():
        chosen += v[:per]
        leftovers += v[per:]
    rng.shuffle(leftovers)
    chosen += leftovers[: max(0, a.n - len(chosen))]

    out_csv = os.path.join(a.out_dir, "candidates.csv")
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cand_id", "omr_row", "type", "stem", "options", "answer", "perception", "phash", "image_file"])
        for k, c in enumerate(chosen):
            fn = f"omr_{c['omr_row']:06d}.jpg"
            with open(os.path.join(img_dir, fn), "wb") as g:
                g.write(c["image_bytes"])
            w.writerow([k, c["omr_row"], c["type"], c["stem"], c["options"], c["answer"], c["perception"],
                        phash_from_bytes(c["image_bytes"]), fn])
    print("stats:", stats)
    print("chosen by type:", {t: sum(1 for c in chosen if c["type"] == t) for t in pool})
    print("→", out_csv, len(chosen), "rows")


if __name__ == "__main__":
    sys.exit(main())
