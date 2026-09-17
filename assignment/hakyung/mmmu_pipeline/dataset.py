import ast
import json
import re
import string
from pathlib import Path

from .config import SUBJECTS


IMAGE_MARKER_RE = re.compile(r"<image\s*(\d+)>", flags=re.IGNORECASE)


def _parse_options(raw):
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return list(raw)
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        raise ValueError(f"Invalid MMMU options value: {raw!r}")
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"MMMU options must be a list: {raw!r}")
    return list(value)


def _prompt_text(row, options):
    # Qwen3-VL/evaluation/mmmu/run_mmmu.py::build_mmmu_prompt.
    prompt = ""
    hint = row.get("hint")
    if hint is not None and str(hint).strip() and str(hint).lower() != "nan":
        prompt += f"Hint: {hint}\n"
    prompt += f"Question: {row.get('question', '')}\n"
    if options:
        prompt += "Options:\n"
        for key, value in options.items():
            prompt += f"{key}. {value}\n"
        prompt += "Please select the correct answer from the options above. \n"
    return prompt.rstrip()


def _referenced_image_indices(text):
    # Keep marker occurrence order but do not send the same image twice.
    ordered = []
    seen = set()
    for match in IMAGE_MARKER_RE.finditer(text):
        index = int(match.group(1))
        if index not in seen:
            seen.add(index)
            ordered.append(index)
    return ordered


def _save_referenced_images(row, prompt, image_dir, question_id):
    paths = []
    for image_index in _referenced_image_indices(prompt):
        image = row.get(f"image_{image_index}")
        if image is None:
            raise ValueError(
                f"{question_id}: prompt references <image {image_index}> but image_{image_index} is empty"
            )
        path = image_dir / f"{question_id}_image_{image_index}.png"
        if not path.exists():
            image.save(path)
        paths.append(str(path.resolve()))
    return paths


def build_dataset(config, output_path, image_dir):
    from datasets import load_dataset

    output_path = Path(output_path)
    image_dir = Path(image_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    expected_per_subject = config["dataset"]["expected_examples_per_subject"]
    records = []

    for subject in SUBJECTS:
        dataset = load_dataset(
            config["dataset"]["name"],
            subject,
            split=config["dataset"]["split"],
            revision=config["dataset"]["revision"],
        )
        if len(dataset) != expected_per_subject:
            raise RuntimeError(
                f"{subject}: expected exactly {expected_per_subject} validation examples, got {len(dataset)}; "
                "subsampling is forbidden"
            )
        for ordinal, row in enumerate(dataset):
            source_id = row.get("id", row.get("index", ordinal))
            safe_source_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(source_id))
            question_id = f"{subject}__{safe_source_id}"
            option_values = _parse_options(row.get("options"))
            options = {
                string.ascii_uppercase[index]: str(value)
                for index, value in enumerate(option_values)
            }
            prompt = _prompt_text(row, options)
            image_paths = _save_referenced_images(row, prompt, image_dir, question_id)
            records.append({
                "question_id": question_id,
                "source_question_id": source_id,
                "subject": subject,
                "question_type": row.get("question_type", "multiple-choice"),
                "answer": row.get("answer"),
                "options": options,
                "prompt": prompt,
                "image_paths": image_paths,
            })
        print(f"[dataset] {subject}: {len(dataset)}")

    expected_total = config["dataset"]["expected_subjects"] * expected_per_subject
    if len(SUBJECTS) != config["dataset"]["expected_subjects"] or len(records) != expected_total:
        raise RuntimeError(f"Expected 30 subjects / 900 examples, got {len(SUBJECTS)} / {len(records)}")
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return records


def build_messages(record, config):
    content = [
        {
            "type": "image",
            "image": path,
            "min_pixels": config["image"]["min_pixels"],
            "max_pixels": config["image"]["max_pixels"],
        }
        for path in record["image_paths"]
    ]
    content.append({"type": "text", "text": record["prompt"]})
    # No system entry: config validation guarantees system_message is null.
    return [{"role": "user", "content": content}]
