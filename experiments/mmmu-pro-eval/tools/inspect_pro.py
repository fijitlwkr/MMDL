"""MMMU-Pro standard (10 options) 메타데이터 점검 (CPU, 생성 전).

이미지 열은 읽지 않는다. 고정 revision의 parquet에서 텍스트 열만 받아
문항 수, 과목별 수, ID 집합 해시, 선택지 수, MMMU validation과의 겹침을 기록한다.
결과(pro_metadata.json)로 config_pro.yaml의 과목 목록·과목별 수·ID 해시를 고정한다.
모델 출력·정답 분포는 보지 않는다(정답 열은 형식 검사에만 쓴다).

사용: python -I inspect_pro.py --mmmu-val-raw <MMMU validation raw.jsonl> --out pro_metadata.json
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

REPO = "MMMU/MMMU_Pro"
REVISION = "0d7426df4ccb3d8704a992fe6850abee7c262127"
CONFIG = "standard (10 options)"
FILES = ["test-00000-of-00002.parquet", "test-00001-of-00002.parquet"]
TEXT_COLUMNS = ["id", "question", "options", "img_type", "answer", "topic_difficulty", "subject"]
EXPECTED_ROWS = 1730


def ids_digest(ids):
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


def norm(text):
    text = re.sub(r"<image\s*\d+>", " ", str(text or ""))
    return re.sub(r"\s+", " ", text).strip().lower()


def load_pro_rows():
    from huggingface_hub import HfFileSystem
    import pyarrow.parquet as pq

    fs = HfFileSystem()
    rows = []
    for name in FILES:
        path = f"datasets/{REPO}@{REVISION}/{CONFIG}/{name}"
        with fs.open(path, "rb") as handle:
            parquet = pq.ParquetFile(handle)
            columns = [field.name for field in parquet.schema_arrow]
            table = parquet.read(columns=TEXT_COLUMNS)
        rows.extend(table.to_pylist())
    return rows, columns


def load_val_questions(path):
    """MMMU validation raw(우리 평가 raw)에서 id → 질문 텍스트."""
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        prompt = row["prompt"]
        if not prompt.startswith("Question: "):
            raise ValueError(f"{row['id']}: prompt does not start with 'Question: '")
        question = prompt[len("Question: "):].split("\nOptions:\n", 1)[0]
        out[row["id"]] = question
    if len(out) != 900:
        raise ValueError(f"MMMU validation raw must have 900 rows, got {len(out)}")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mmmu-val-raw", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    rows, columns = load_pro_rows()
    ids = [row["id"] for row in rows]
    problems = []
    if len(rows) != EXPECTED_ROWS:
        problems.append(f"rows {len(rows)} != {EXPECTED_ROWS}")
    if len(set(ids)) != len(ids):
        problems.append("duplicate ids")

    option_counts, answer_bad, option_parse_bad = Counter(), [], []
    for row in rows:
        try:
            options = ast.literal_eval(row["options"])
            assert isinstance(options, list) and all(isinstance(x, str) for x in options)
        except Exception:
            option_parse_bad.append(row["id"])
            continue
        option_counts[len(options)] += 1
        letters = [chr(65 + i) for i in range(len(options))]
        if row["answer"] not in letters:
            answer_bad.append(row["id"])

    subject_counts = Counter(row["subject"] for row in rows)
    prefix_counts = Counter(row["id"].split("_", 1)[0] for row in rows)

    val_questions = load_val_questions(args.mmmu_val_raw)
    val_norm = {}
    for vid, question in val_questions.items():
        val_norm.setdefault(norm(question), []).append(vid)
    overlap_id = sorted(row["id"] for row in rows if row["id"] in val_questions)
    overlap_text = []
    for row in rows:
        key = norm(row["question"])
        if len(key) >= 30 and key in val_norm:
            overlap_text.append({"pro_id": row["id"], "val_ids": val_norm[key]})
    overlap_union = sorted(set(overlap_id) | {item["pro_id"] for item in overlap_text})

    result = {
        "repo": REPO, "revision": REVISION, "config": CONFIG, "files": FILES,
        "columns": columns, "rows": len(rows), "ids_sha256": ids_digest(ids),
        "id_examples": ids[:5], "id_prefix_counts": dict(prefix_counts),
        "subjects": sorted(subject_counts), "subject_counts": dict(sorted(subject_counts.items())),
        "option_count_distribution": dict(sorted(option_counts.items())),
        "options_parse_failures": option_parse_bad, "answer_not_in_options": answer_bad,
        "mmmu_validation_overlap": {
            "rule": "Pro id가 MMMU validation id와 같거나, <image N> 태그를 뺀 정규화 질문(30자 이상)이 validation 질문과 같음",
            "by_id": len(overlap_id), "by_text": len(overlap_text), "union": len(overlap_union),
            "ids": overlap_union, "text_matches": overlap_text,
            "val_raw_sha256": hashlib.sha256(args.mmmu_val_raw.read_bytes()).hexdigest()},
        "problems": problems,
    }
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("rows", "ids_sha256", "id_prefix_counts", "subject_counts",
                                              "option_count_distribution", "problems")}, ensure_ascii=False))
    print("options_parse_failures", len(option_parse_bad), "answer_not_in_options", len(answer_bad))
    print("validation overlap: id", len(overlap_id), "text", len(overlap_text), "union", len(overlap_union))
    return 1 if problems or option_parse_bad or answer_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
