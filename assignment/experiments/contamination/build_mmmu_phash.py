"""MMMU(dev/validation/test)와 MMMU-Pro 이미지 전체의 pHash 색인을 만든다.

사용:
  python build_mmmu_phash.py --cache-dir <다운로드 폴더> --out mmmu_phash.csv
  (--include-pro 를 주면 MMMU-Pro standard/vision 이미지도 포함)

출력 CSV 열: source, split, subject, id, image_idx, phash, width, height
`datasets` 라이브러리를 쓰지 않고 parquet 을 직접 읽는다.
"""
import argparse
import csv
import io
import os
import sys

import pyarrow.parquet as pq
from huggingface_hub import HfApi, hf_hub_download
from PIL import Image

from phash_utils import phash_from_pil

MMMU_REPO = "MMMU/MMMU"
MMMU_REV = "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68"  # 팀 고정 revision
PRO_REPO = "MMMU/MMMU_Pro"


def iter_parquet_files(repo, revision=None):
    api = HfApi()
    info = api.dataset_info(repo, revision=revision)
    return sorted(s.rfilename for s in info.siblings if s.rfilename.endswith(".parquet"))


def image_columns(schema):
    return [n for n in schema.names if n == "image" or n.startswith("image_")]


def process_file(repo, fname, revision, cache_dir, source, writer, done_ids):
    path = hf_hub_download(repo, fname, repo_type="dataset", revision=revision, cache_dir=cache_dir)
    pf = pq.ParquetFile(path)
    cols = image_columns(pf.schema_arrow)
    split = os.path.basename(fname).split("-")[0]
    subject = fname.split("/")[0]
    n = 0
    for batch in pf.iter_batches(batch_size=64, columns=["id"] + cols):
        d = batch.to_pydict()
        for i, iid in enumerate(d["id"]):
            key = (source, split, iid)
            if key in done_ids:
                continue
            for c in cols:
                img = d[c][i]
                if not img or not img.get("bytes"):
                    continue
                try:
                    im = Image.open(io.BytesIO(img["bytes"]))
                    h = phash_from_pil(im)
                    w, ht = im.size
                except Exception as e:  # 깨진 이미지는 기록만
                    h, w, ht = f"ERROR:{type(e).__name__}", 0, 0
                idx = c.replace("image_", "") if c != "image" else "1"
                writer.writerow([source, split, subject, iid, idx, h, w, ht])
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--include-pro", action="store_true")
    ap.add_argument("--only", default="", help="쉼표로 구분한 과목/구성 이름 필터(테스트용)")
    a = ap.parse_args()
    os.makedirs(a.cache_dir, exist_ok=True)

    done_ids = set()
    mode = "a" if os.path.exists(a.out) else "w"
    if mode == "a":  # 이어서 실행
        with open(a.out, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                done_ids.add((r["source"], r["split"], r["id"]))
    f = open(a.out, mode, newline="", encoding="utf-8")
    w = csv.writer(f)
    if mode == "w":
        w.writerow(["source", "split", "subject", "id", "image_idx", "phash", "width", "height"])

    jobs = [(MMMU_REPO, fn, MMMU_REV, "mmmu") for fn in iter_parquet_files(MMMU_REPO, MMMU_REV)]
    if a.include_pro:
        jobs += [(PRO_REPO, fn, None, "mmmu_pro") for fn in iter_parquet_files(PRO_REPO)]
    if a.only:
        keys = a.only.split(",")
        jobs = [j for j in jobs if any(k in j[1] for k in keys)]

    total = 0
    for k, (repo, fn, rev, src) in enumerate(jobs, 1):
        n = process_file(repo, fn, rev, a.cache_dir, src, w, done_ids)
        f.flush()
        total += n
        print(f"[{k}/{len(jobs)}] {src} {fn}: {n} images (total {total})", flush=True)
    f.close()
    print("done", total, "images →", a.out)


if __name__ == "__main__":
    sys.exit(main())
