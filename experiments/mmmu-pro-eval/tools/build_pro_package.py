"""MMMU test 평가 패키지(exp/mmmu-test-eval)를 복사해 MMMU-Pro standard (10 options)용 패키지를 만든다.

원본 패키지는 건드리지 않는다. 바꾸는 것은 아래 REPLACEMENTS(각각 정확히 1회 일치해야 함)와
새로 만드는 파일(config_pro.yaml, scripts/run_pro.sh)뿐이다. 생성·이미지·프롬프트·채점 규칙 코드는 그대로다.
config_pro.yaml은 config_test.yaml에서 dataset 블록만 pro_metadata.json 값으로 바꾼다.

사용: python -I build_pro_package.py --base <experiments/mmmu-test-eval> --metadata pro_metadata.json --out <새 폴더>
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil

PRO_REVISION = "0d7426df4ccb3d8704a992fe6850abee7c262127"

COMMON_LOADER = '''

def ids_digest(ids: list[str]) -> str:
    import hashlib

    return hashlib.sha256("\\n".join(sorted(ids)).encode("utf-8")).hexdigest()


def _load_pro_samples(setting: dict, data_root: str | None, selected: list[str],
                      expected: dict[str, int]) -> list[Sample]:
    """MMMU-Pro standard: one config, one split; every row is multiple-choice."""
    from collections import Counter
    from datasets import load_dataset

    if not setting.get("expected_ids_sha256"):
        raise ValueError("dataset.expected_ids_sha256 must be pinned before loading MMMU-Pro")
    dataset = load_dataset(setting["repo_id"], setting["config_name"], split=setting["split"],
                           revision=setting["revision"], cache_dir=data_root)
    if len(dataset) != setting["expected_total_rows"]:
        raise ValueError(f"expected {setting['expected_total_rows']} rows, got {len(dataset)}")
    ids = dataset.data.column("id").to_pylist()
    if len(set(ids)) != len(ids) or ids_digest(ids) != setting["expected_ids_sha256"]:
        raise ValueError("MMMU-Pro IDs differ from the pinned ID set")
    subjects = dataset.data.column("subject").to_pylist()
    if dict(Counter(subjects)) != expected:
        raise ValueError("MMMU-Pro subject counts differ from the configuration")
    image_columns = sorted((int(match.group(1)), name) for name in dataset.column_names
                           if (match := IMAGE_COLUMN.fullmatch(name)))
    image_present = {name: [not missing for missing in dataset.data.column(name).is_null().to_pylist()]
                     for _, name in image_columns}
    metadata = dataset.remove_columns([name for _, name in image_columns])
    wanted = set(selected)
    samples = []
    for subject in setting["subjects"]:
        if subject not in wanted:
            continue
        for index in (i for i, value in enumerate(subjects) if value == subject):
            row = metadata[index]
            raw = row["options"]
            if not isinstance(raw, str):
                raise TypeError(f"{row['id']}: options is not a string")
            options = _parse_options(raw, "multiple-choice")
            if row["answer"] not in [chr(65 + i) for i in range(len(options))]:
                raise ValueError(f"{row['id']}: answer is not an option letter")
            present = [number for number, name in image_columns if image_present[name][index]]
            samples.append(Sample(id=row["id"], subject=subject, subfield=None,
                                  topic_difficulty=row.get("topic_difficulty"), img_type=row.get("img_type"),
                                  question_type="multiple-choice", question=row["question"],
                                  options=options, options_raw=raw, answer=row["answer"],
                                  image_indices=present, dataset=dataset, row_index=index))
    return samples


def load_samples('''

REPLACEMENTS = [
    ("code/common.py",
     "\n\ndef load_samples(",
     COMMON_LOADER),
    ("code/common.py",
     "    selected_set = set(selected)\n    samples = []\n",
     "    selected_set = set(selected)\n"
     "    if setting.get(\"format\") == \"mmmu_pro\":\n"
     "        samples = _load_pro_samples(setting, data_root, selected, expected)\n"
     "        if len(selected_set) == len(setting[\"subjects\"]) and len(samples) != setting[\"expected_total_rows\"]:\n"
     "            raise ValueError(f\"expected {setting['expected_total_rows']} total rows, got {len(samples)}\")\n"
     "        return samples\n"
     "    samples = []\n"),
    ("code/metadata.py",
     "    if ds.get(\"repo_id\") != \"MMMU/MMMU\":\n"
     "        errors.append(f\"unexpected dataset repo_id: {ds.get('repo_id')}\")\n"
     "    if ds.get(\"revision\") != \"98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68\":\n"
     "        errors.append(f\"unexpected dataset revision: {ds.get('revision')}\")\n",
     "    pinned_datasets = {(\"MMMU/MMMU\", \"98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68\"),\n"
     f"                       (\"MMMU/MMMU_Pro\", \"{PRO_REVISION}\")}}\n"
     "    if (ds.get(\"repo_id\"), ds.get(\"revision\")) not in pinned_datasets:\n"
     "        errors.append(f\"unexpected dataset: {ds.get('repo_id')} @ {ds.get('revision')}\")\n"),
    ("code/scoring/evaluate.py",
     "    expected_ids = {f\"{split}_{subject}_{number}\": subject\n"
     "                    for subject, count in expected.items() for number in range(1, count + 1)}\n",
     "    if dataset.get(\"format\") == \"mmmu_pro\":\n"
     "        pinned = dataset.get(\"expected_ids_sha256\")\n"
     "        require(bool(pinned) and sha(\"\\n\".join(sorted(row[\"id\"] for row in rows)).encode(\"utf-8\")) == pinned,\n"
     "                \"IDs differ from the pinned MMMU-Pro ID set\")\n"
     "        require(set(kinds) == {\"multiple-choice\"}, \"MMMU-Pro rows must be multiple-choice\")\n"
     "        expected_ids = {row[\"id\"]: row[\"subject\"] for row in rows}\n"
     "    else:\n"
     "        expected_ids = {f\"{split}_{subject}_{number}\": subject\n"
     "                        for subject, count in expected.items() for number in range(1, count + 1)}\n"),
    # Final Answer 보완 규칙의 문자 범위: MMMU 최대 9지(A~I) → Pro 최대 12지(A~L).
    # marker()가 실제 선택지에 있는 글자만 받으므로 선택지 9개 이하 문항의 결과는 바뀌지 않는다.
    ("code/scoring/frozen/parsers.py",
     "\\s*\\*{0,2}\\s*\\(?([A-I])\\)?\\b\"\n",
     "\\s*\\*{0,2}\\s*\\(?([A-L])\\)?\\b\"\n"),
    ("scripts/prepare_test_scoring.py",
     "    for name in (\"code\", \"config\", \"raw\", \"out\"):\n"
     "        parser.add_argument(f\"--{name}\", type=Path, required=True)\n",
     "    for name in (\"code\", \"config\", \"raw\", \"out\"):\n"
     "        parser.add_argument(f\"--{name}\", type=Path, required=True)\n"
     "    parser.add_argument(\"--expect-total\", type=int, default=10500)\n"),
    ("scripts/prepare_test_scoring.py",
     "    assert manifest[\"total\"] == 10500 and len(requests) == manifest[\"judge_count\"]\n",
     "    assert manifest[\"total\"] == args.expect_total and len(requests) == manifest[\"judge_count\"]\n"),
]

RUN_PRO = r'''#!/usr/bin/env bash
# MMMU-Pro standard (10 options), RTX 4090 1장, 전체 과목을 한 프로세스로 생성한다.
set -euo pipefail
if [[ $# -ne 6 || ( "$1" != smoke && "$1" != full ) ]]; then
  echo "Usage: run_pro.sh smoke|full CODE_DIR CONFIG_PRO MODEL_DIR DATA_CACHE OUTPUT_ROOT" >&2
  exit 2
fi
mode=$1
code=$(realpath "$2")
config=$(realpath "$3")
model=$(realpath "$4")
data=$(realpath "$5")
root=$(realpath -m "$6")
: "${HF_HOME:?Set HF_HOME before running}"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=4
mapfile -t gpu_names < <(nvidia-smi --query-gpu=name --format=csv,noheader)
[[ "${#gpu_names[@]}" -ge 1 && "${gpu_names[0]}" == "NVIDIA GeForce RTX 4090" ]]
total=$(python -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["dataset"]["expected_total_rows"])' "$config")
if [[ "$mode" == full ]]; then
  [[ -f "$root/smoke/logs/04_validate_raw.log" ]] || { echo "run smoke first" >&2; exit 3; }
fi
dir="$root/$mode"
mkdir -p "$root"
mkdir "$dir"
export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0
python -c 'import torch; assert torch.__version__=="2.8.0+cu128" and torch.cuda.device_count()==1; assert "RTX 4090" in torch.cuda.get_device_name(0)'
nvidia-smi -i 0 --query-gpu=timestamp,index,memory.used,memory.total --format=csv,noheader,nounits -l 1 > "$dir/physical_gpu_memory.csv" &
sampler=$!
trap 'kill "$sampler" 2>/dev/null || true' EXIT
flags=()
expected="$total"
if [[ "$mode" == smoke ]]; then
  expected=3
  flags=(--limit 3)
fi
EXPECT_ROWS="$expected" bash "$code/run_generate.sh" --config "$config" --model_path "$model" \
  --data_root "$data" --out "$dir" "${flags[@]}" 2>&1 | tee "$dir/worker.log"
python "$code/validate_raw.py" --config "$config" --raw "$dir/raw.jsonl" --expect "$expected"
sha256sum "$dir/raw.jsonl"
'''


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pro_dataset_block(meta: dict) -> str:
    lines = ["dataset:", "  format: mmmu_pro", "  repo_id: MMMU/MMMU_Pro", f"  revision: {meta['revision']}",
             f"  config_name: \"{meta['config']}\"", "  split: test", "  expected_rows_by_subject:"]
    lines += [f"    {json.dumps(subject)}: {count}" for subject, count in sorted(meta["subject_counts"].items())]
    lines += [f"  expected_total_rows: {meta['rows']}", f"  expected_ids_sha256: {meta['ids_sha256']}", "  subjects:"]
    lines += [f"    - {json.dumps(subject)}" for subject in sorted(meta["subject_counts"])]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    meta = json.loads(args.metadata.read_text(encoding="utf-8"))
    assert meta["revision"] == PRO_REVISION and meta["config"] == "standard (10 options)"
    assert not meta["problems"] and not meta["options_parse_failures"] and not meta["answer_not_in_options"]
    assert sum(meta["subject_counts"].values()) == meta["rows"]

    shutil.copytree(args.base, args.out, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    diffs = []
    for rel, old, new in REPLACEMENTS:
        path = args.out / rel
        original = path.read_bytes().decode("utf-8")
        crlf = "\r\n" in original
        text = original.replace("\r\n", "\n")
        assert text.count(old) == 1, f"{rel}: expected exactly one match"
        updated = text.replace(old, new)
        path.write_bytes((updated.replace("\n", "\r\n") if crlf else updated).encode("utf-8"))
        diffs.append("".join(difflib.unified_diff(text.splitlines(True), updated.splitlines(True),
                                                  "a/" + rel, "b/" + rel)))

    test_cfg = (args.out / "code/config_test.yaml").read_bytes().decode("utf-8").replace("\r\n", "\n")
    start, end = test_cfg.index("dataset:\n"), test_cfg.index("environment:\n")
    pro_cfg = test_cfg[:start] + pro_dataset_block(meta) + test_cfg[end:]
    (args.out / "code/config_pro.yaml").write_bytes(pro_cfg.encode("utf-8"))
    (args.out / "scripts/run_pro.sh").write_bytes(RUN_PRO.encode("utf-8"))
    diffs.append("".join(difflib.unified_diff(test_cfg.splitlines(True), pro_cfg.splitlines(True),
                                              "a/code/config_test.yaml", "b/code/config_pro.yaml")))

    report = ["# PRO_CHANGES", "",
              "- base: `experiments/mmmu-test-eval` (branch `exp/mmmu-test-eval`)",
              f"- metadata sha256: `{sha(args.metadata.read_bytes())}`",
              "- 생성·이미지·프롬프트·채점 규칙 코드는 그대로다. 아래 diff가 전부다(+ 새 파일 `scripts/run_pro.sh`).", "",
              "```diff", *diffs, "```", ""]
    (args.out / "PRO_CHANGES.md").write_bytes("\n".join(report).encode("utf-8"))
    hashes = {p.relative_to(args.out).as_posix(): sha(p.read_bytes())
              for p in sorted(args.out.rglob("*")) if p.is_file()}
    (args.out / "PRO_FILE_HASHES.json").write_bytes((json.dumps(hashes, indent=1) + "\n").encode("utf-8"))
    print(f"built {args.out} ({len(hashes)} files)")


if __name__ == "__main__":
    main()
