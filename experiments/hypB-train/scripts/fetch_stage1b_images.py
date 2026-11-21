"""Receive only the approved parquet image ranges; checkpoint each row group."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image

from prepare_pool_stage1b import MMFR, OUT, REPORTS, REVISION, ROOT

sys.path.insert(0, str(MMFR))
from stage1 import ColumnFile, pq

PLAN = REPORTS / "stage1b_image_transfer_plan.json"
APPROVED_SHA = "5af5f899226972570496a02c8b86ebe157280387155639a92841181b47b94ce1"
APPROVED_BYTES = 1_102_724_846
IMAGES = ROOT / "data/images_B"


def json_atomic(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)


def fetch(url, offset, count, total):
    end = offset + count - 1
    request = Request(url + f"?r1_image_range={offset}-{end}",
                      headers={"Range": f"bytes={offset}-{end}", "Accept-Encoding": "identity"})
    with urlopen(request, timeout=90) as response:
        if response.status != 206 or response.headers.get("Content-Range") != f"bytes {offset}-{end}/{total}":
            raise ValueError("Range rejected before reading response body")
        body = response.read(count)
    if len(body) != count:
        raise ValueError(f"Incomplete image range ({len(body)}/{count} bytes)")
    return body


class ImageRangeFile(ColumnFile):
    def __init__(self, source, group):
        self.length, self.position = source["size"], 0
        path = MMFR / "cache" / (Path(source["path"]).name + ".footer")
        self.parts = [(0, b"PAR1"), (source["footer_start"], path.read_bytes()[4:])]
        ranges = []
        for item in sorted(group["columns"], key=lambda c: c["start"]):
            assert item["column"] in ("image.bytes", "image.path")
            offset, count = item["start"], item["size"]
            if ranges and sum(ranges[-1]) == offset:
                ranges[-1] = (ranges[-1][0], ranges[-1][1] + count)
            else:
                ranges.append((offset, count))
        for offset, count in ranges:
            self.parts.append((offset, fetch(source["url"], offset, count, self.length)))
        self.received = sum(count for _, count in ranges)


def store_image(target, raw):
    result = {**target}
    if not raw:
        return {**result, "status": "image_missing"}
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            size, kind = image.size, image.format
            if float(np.asarray(image.convert("L")).std()) < 2:
                return {**result, "status": "image_blank"}
    except (OSError, ValueError, Image.DecompressionBombError):
        return {**result, "status": "image_decode_failed"}
    extensions = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "GIF": "gif", "TIFF": "tiff", "BMP": "bmp"}
    if kind not in extensions:
        return {**result, "status": "image_unsupported_format"}
    path = IMAGES / f"{target['origin']}_{target['row']}.{extensions[kind]}"
    path.write_bytes(raw)
    return {**result, "status": "image_ok", "path": path.relative_to(ROOT / "data").as_posix(),
            "bytes": len(raw), "sha256": sha256(raw).hexdigest(), "width": size[0], "height": size[1], "format": kind}


def process(source, group):
    checkpoint = OUT / "image_receipts" / f"{Path(source['path']).stem}_{group['group']}.json"
    if checkpoint.exists():
        result = json.loads(checkpoint.read_text(encoding="utf-8"))
        assert result["range_bytes"] == group["bytes"]
        for row in result["rows"]:
            if row["status"] == "image_ok":
                assert sha256((ROOT / "data" / row["path"]).read_bytes()).hexdigest() == row["sha256"]
        return result
    with ImageRangeFile(source, group) as virtual:
        pf = pq.ParquetFile(virtual, pre_buffer=False)
        column = pf.read_row_group(group["group"], columns=["image"], use_threads=False).column("image")
        records = []
        for target in group["targets"]:
            value = column[target["row_group_offset"]].as_py()
            records.append(store_image(target, (value or {}).get("bytes")))
        assert virtual.received == group["bytes"]
    result = {"range_bytes": group["bytes"], "rows": records}
    json_atomic(checkpoint, result)
    return result


def main():
    plan_bytes = PLAN.read_bytes()
    assert sha256(plan_bytes).hexdigest() == APPROVED_SHA
    plan = json.loads(plan_bytes)
    assert plan["revision"] == REVISION and plan["range_bytes"] == APPROVED_BYTES
    source = json.loads((MMFR / "download_plan.json").read_text(encoding="utf-8"))
    assert source["revision"] == REVISION
    sources = {item["path"]: item for item in source["files"]}
    jobs = [(sources[file["path"]], g) for file in plan["files"] for g in file["groups"]]
    assert sum(group["bytes"] for _, group in jobs) == APPROVED_BYTES
    IMAGES.mkdir(exist_ok=True)
    (OUT / "image_receipts").mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        # Submit in waves so a range error does not launch the remaining transfer.
        results = []
        for i in range(0, len(jobs), 6):
            wave = jobs[i:i + 6]
            results.extend(pool.map(lambda job: process(*job), wave))
            done = len(results)
            if done <= 6 or done % 24 == 0 or done == len(jobs):
                print(f"{done}/{len(jobs)} row groups, {sum(r['range_bytes'] for r in results):,} bytes", flush=True)
    rows = [row for result in results for row in result["rows"]]
    assert len({row["row"] for row in rows}) == len(rows) == 388
    json_atomic(REPORTS / "stage1b_image_receipt.json",
                {"range_bytes_received": sum(r["range_bytes"] for r in results),
                 "saved_image_bytes": sum(row.get("bytes", 0) for row in rows), "rows": rows})


if __name__ == "__main__":
    main()
