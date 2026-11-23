"""Shared MMMU sample, prompt, and raw record definitions.

Prompt source: https://github.com/QwenLM/Qwen3-VL
Commit: f8dca99056bb6352cf6ab36d4ea1848a09c54b5b
License: Apache-2.0
Changes from evaluation/mmmu/run_mmmu.py: use the Hugging Face validation schema
instead of the VLMEvalKit TSV; generate option letters from list positions; omit
the optional hint because this dataset has no hint column; preserve image markers;
pass image objects in memory instead of saving images to disk. CoT stays disabled.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import re
from typing import Any


IMAGE_COLUMN = re.compile(r"image_(\d+)$")
IMAGE_MARKER = re.compile(r"<image\s*\d+>")


@dataclass
class Sample:
    id: str
    subject: str
    subfield: str | None
    topic_difficulty: str | None
    img_type: str | None
    question_type: str
    question: str
    options: list[str]
    options_raw: str
    answer: str
    image_indices: list[int]
    dataset: Any = field(default=None, repr=False, compare=False)
    row_index: int = field(default=0, repr=False, compare=False)

    def images(self) -> dict[int, Any]:
        """Decode only this sample's images when its chunk is prepared."""
        if self.dataset is None:
            return {}
        row = self.dataset[self.row_index]
        return {index: row[f"image_{index}"] for index in self.image_indices}


def _parse_options(raw: str, kind: str) -> list[str]:
    parsed = ast.literal_eval(raw)
    if not isinstance(parsed, (list, tuple)) or not all(isinstance(item, str) for item in parsed):
        raise ValueError(f"options must parse to a list of strings: {raw!r}")
    if kind == "open":
        if parsed:
            raise ValueError("open question has nonempty options")
        return []
    return list(parsed)


def expected_subject_counts(setting: dict) -> dict[str, int]:
    table = setting.get("expected_rows_by_subject")
    if table is None:
        return {subject: setting["expected_rows_per_subject"] for subject in setting["subjects"]}
    if (set(table) != set(setting["subjects"])
            or any(type(n) is not int or n <= 0 for n in table.values())
            or sum(table.values()) != setting["expected_total_rows"]):
        raise ValueError("expected_rows_by_subject must match the subject list and total")
    return table


def ids_digest(ids: list[str]) -> str:
    import hashlib

    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


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


def load_samples(cfg: dict, data_root: str | None, subjects: list[str] | None = None) -> list[Sample]:
    from datasets import load_dataset

    setting = cfg["dataset"]
    expected = expected_subject_counts(setting)
    selected = subjects or setting["subjects"]
    unknown = set(selected) - set(setting["subjects"])
    if unknown:
        raise ValueError(f"unknown subjects: {sorted(unknown)}")
    selected_set = set(selected)
    if setting.get("format") == "mmmu_pro":
        samples = _load_pro_samples(setting, data_root, selected, expected)
        if len(selected_set) == len(setting["subjects"]) and len(samples) != setting["expected_total_rows"]:
            raise ValueError(f"expected {setting['expected_total_rows']} total rows, got {len(samples)}")
        return samples
    samples = []
    for subject in setting["subjects"]:
        if subject not in selected_set:
            continue
        dataset = load_dataset(setting["repo_id"], subject, split=setting["split"],
                               revision=setting["revision"], cache_dir=data_root)
        if len(dataset) != expected[subject]:
            raise ValueError(f"{subject}: expected {expected[subject]} rows, got {len(dataset)}")
        if setting["split"] == "test":
            ids = dataset.data.column("id").to_pylist()
            if set(ids) != {f"test_{subject}_{i}" for i in range(1, expected[subject] + 1)}:
                raise ValueError(f"{subject}: unexpected test IDs")
            missing = sum(answer is None or str(answer).strip() in ("", "?")
                          for answer in dataset.data.column("answer").to_pylist())
            if missing:
                raise ValueError(f"{subject}: {missing} test answers are missing")
        image_columns = sorted((int(match.group(1)), name) for name in dataset.column_names
                               if (match := IMAGE_COLUMN.fullmatch(name)))
        image_present = {name: [not missing for missing in dataset.data.column(name).is_null().to_pylist()]
                         for _, name in image_columns}
        metadata = dataset.remove_columns([name for _, name in image_columns])
        for index in range(len(dataset)):
            row = metadata[index]
            raw = row["options"]
            if not isinstance(raw, str):
                raise TypeError(f"{subject} row {index}: options is not a string")
            present = [number for number, name in image_columns if image_present[name][index]]
            samples.append(Sample(id=row["id"], subject=subject, subfield=row.get("subfield"),
                                  topic_difficulty=row.get("topic_difficulty"), img_type=row.get("img_type"),
                                  question_type=row["question_type"], question=row["question"],
                                  options=_parse_options(raw, row["question_type"]), options_raw=raw,
                                  answer=row["answer"], image_indices=present,
                                  dataset=dataset, row_index=index))
    if len(selected_set) == len(setting["subjects"]) and len(samples) != setting["expected_total_rows"]:
        raise ValueError(f"expected {setting['expected_total_rows']} total rows, got {len(samples)}")
    return samples


def build_prompt(sample: Sample, cfg: dict) -> str:
    prompt = f"Question: {sample.question}\n"
    if sample.options:
        prompt += "Options:\n"
        for index, option in enumerate(sample.options):
            prompt += f"{chr(ord('A') + index)}. {option}\n"
        prompt += "Please select the correct answer from the options above. \n"
    return prompt.rstrip()


def build_messages(sample: Sample, cfg: dict, images: dict[int, Any]) -> list[dict]:
    content = [{"type": "image", "image": images[index],
                "min_pixels": cfg["image"]["min_pixels"], "max_pixels": cfg["image"]["max_pixels"]}
               for index in sorted(images)]
    content.append({"type": "text", "text": build_prompt(sample, cfg)})
    return [{"role": "user", "content": content}]


def select_smoke(samples: list[Sample], n: int) -> list[Sample]:
    if n < 0:
        raise ValueError("limit must be nonnegative")
    selected = []
    seen = set()

    def include(sample):
        if sample is not None and sample.id not in seen and len(selected) < n:
            selected.append(sample)
            seen.add(sample.id)

    include(next((sample for sample in samples if sample.question_type == "open"), None))
    include(max(samples, key=lambda sample: len(sample.image_indices), default=None))
    include(next((sample for sample in samples if len(sample.image_indices) in (2, 3)), None))
    include(next((sample for sample in samples if any(IMAGE_MARKER.search(option) for option in sample.options)), None))
    for sample in samples:
        include(sample)
    return selected


RAW_FIELDS = {
    "schema_version": str,
    "synthetic": bool,
    "id": str,
    "subject": str,
    "subfield": (str, type(None)),
    "topic_difficulty": (str, type(None)),
    "img_type": (str, type(None)),
    "question_type": str,
    "gold": str,
    "options": list,
    "options_raw": str,
    "image_indices": (list, type(None)),  # Image numbers owned by the question, ascending; also retained for skips.
    "prompt": (str, type(None)),
    "status": str,
    "reason": (str, type(None)),
    "error": (str, type(None)),
    "raw_text": (str, type(None)),
    "output_token_ids": (list, type(None)),
    "output_tokens": (int, type(None)),
    "finish_reason": (str, type(None)),
    "stop_reason": (str, int, type(None)),
    "max_new_tokens": int,
    "num_prompt_tokens": (int, type(None)),
    "precomputed_prompt_tokens": (int, type(None)),
}


def make_record(sample: Sample, cfg: dict, **values) -> dict:
    base = dict.fromkeys(RAW_FIELDS)
    base.update(schema_version=cfg["schema"]["version"], synthetic=False, id=sample.id,
                subject=sample.subject, subfield=sample.subfield, topic_difficulty=sample.topic_difficulty,
                img_type=sample.img_type, question_type=sample.question_type, gold=sample.answer,
                options=sample.options, options_raw=sample.options_raw, image_indices=sorted(sample.image_indices),
                prompt=build_prompt(sample, cfg), status="error", max_new_tokens=cfg["budget"]["max_new_tokens"],
                raw_text="", output_token_ids=[], output_tokens=0)
    if set(values) - set(RAW_FIELDS):
        raise ValueError(f"unknown record fields: {sorted(set(values) - set(RAW_FIELDS))}")
    base.update(values)
    return base


def validate_record(record: dict) -> None:
    missing = set(RAW_FIELDS) - set(record)
    extra = set(record) - set(RAW_FIELDS)
    if missing or extra:
        raise ValueError(f"record fields: missing={sorted(missing)}, extra={sorted(extra)}")
    for name, allowed in RAW_FIELDS.items():
        value = record[name]
        if name in ("output_tokens", "max_new_tokens", "num_prompt_tokens", "precomputed_prompt_tokens"):
            valid = value is None or (type(value) is int and value >= 0)
        elif name == "synthetic":
            valid = type(value) is bool
        elif name in ("options", "image_indices", "output_token_ids") and value is not None:
            item_type = str if name == "options" else int
            valid = type(value) is list and all(type(item) is item_type for item in value)
        elif name == "stop_reason":
            valid = value is None or type(value) in (str, int)
        else:
            valid = type(value) in (allowed if isinstance(allowed, tuple) else (allowed,))
        if not valid:
            raise TypeError(f"{name}: invalid value {value!r}")
    if record["status"] not in ("ok", "skip", "error"):
        raise ValueError(f"invalid status: {record['status']!r}")


def check_invariants(record: dict) -> list[str]:
    violations = []
    status = record["status"]
    if status == "ok":
        if record["output_token_ids"] is None or record["output_tokens"] != len(record["output_token_ids"]):
            violations.append("output_token_count")
    if record["finish_reason"] == "length" and record["output_tokens"] != record["max_new_tokens"]:
        violations.append("length_token_count")
    if status == "skip":
        if any(record[name] not in (None, "", [], 0) for name in
               ("raw_text", "output_token_ids", "output_tokens", "finish_reason", "stop_reason", "num_prompt_tokens")):
            violations.append("skip_output_not_null")
        if record["reason"] is None:
            violations.append("skip_reason_missing")
    if status == "error" and record["error"] is None:
        violations.append("error_missing")
    return violations
