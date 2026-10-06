"""Download MMMU images for the labeling items from the pinned dataset revision.

Reads image_manifest.json (pinned parquet URL + sha256 per subject), verifies each
parquet's sha256, and writes only the needed images as <id>_image_<n>.png.
Images already extracted in assignment/experiments/failure_review/images are reused.
Needs: pip install pyarrow  (network access to huggingface.co)

Usage: python fetch_images.py --repo . --ids results/error_analysis/split.csv \
         --extra results/error_analysis/extra_for_C.csv --out data/error_analysis_images
"""
import argparse, csv, hashlib, io, json, shutil, urllib.request
from collections import defaultdict
from pathlib import Path


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--ids", default="results/error_analysis/split.csv")
    ap.add_argument("--extra", default="results/error_analysis/extra_for_C.csv")
    ap.add_argument("--out", default="data/error_analysis_images")
    ap.add_argument("--cache", default="data/error_analysis_images/.parquet_cache")  # inside git-ignored data/*_images/
    a = ap.parse_args()
    repo, out, cache = Path(a.repo), Path(a.out), Path(a.cache)
    out.mkdir(parents=True, exist_ok=True); cache.mkdir(parents=True, exist_ok=True)

    manifest = json.load(open(repo / "assignment/experiments/failure_review/image_manifest.json"))
    src = {s["subject"]: s for s in manifest["source_files"]}
    old_dir = repo / "assignment/experiments/failure_review/images"
    old = {Path(m["path"]).name: m for m in manifest["images"]}

    ids = [r["id"] for r in csv.DictReader(open(a.ids, encoding="utf-8"))]
    ids += [r["id"] for r in csv.DictReader(open(a.extra, encoding="utf-8")) if r["check"] == "yes"]
    raw = {}
    for l in open(repo / "results/mmmu_team_baseline/raw.jsonl", encoding="utf-8"):
        r = json.loads(l)
        raw[r["id"]] = r
    need = defaultdict(list)  # subject -> [(id, n)]
    for i in ids:
        for n in raw[i].get("image_indices") or []:
            name = f"{i}_image_{n}.png"
            dst = out / name
            if dst.exists():
                continue
            if name in old and (old_dir / name).exists() and sha256((old_dir / name).read_bytes()) == old[name]["sha256"]:
                shutil.copy(old_dir / name, dst); continue
            need[raw[i]["subject"]].append((i, n))
    print("images to extract from parquet:", sum(len(v) for v in need.values()))
    if not need:
        return
    import pyarrow.parquet as pq  # imported late so reuse-only runs need no pyarrow
    for subj, wants in sorted(need.items()):
        s = src[subj]
        pf = cache / Path(s["path"]).parent.name / Path(s["path"]).name
        pf.parent.mkdir(parents=True, exist_ok=True)
        if not pf.exists():
            urllib.request.urlretrieve(s["url"], pf)
        if sha256(pf.read_bytes()) != s["sha256"]:
            pf.unlink(); raise SystemExit(f"sha256 mismatch: {subj}")
        tbl = pq.read_table(pf).to_pylist()
        by_id = {r["id"]: r for r in tbl}
        for i, n in wants:
            cell = by_id[i][f"image_{n}"]
            if not cell or not cell.get("bytes"):
                raise SystemExit(f"empty image slot: {i} image_{n}")
            data = cell["bytes"]
            try:  # keep original bytes when already PNG; otherwise convert
                from PIL import Image
                im = Image.open(io.BytesIO(data))
                if im.format != "PNG":
                    buf = io.BytesIO(); im.save(buf, "PNG"); data = buf.getvalue()
            except ImportError:
                pass
            (out / f"{i}_image_{n}.png").write_bytes(data)
    missing = [f"{i}_image_{n}" for i in ids for n in raw[i].get("image_indices") or [] if not (out / f"{i}_image_{n}.png").exists()]
    print("done; missing:", missing)


if __name__ == "__main__":
    main()
