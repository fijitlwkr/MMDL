"""Experiment D: compare inline and prefix image placement on multi-image questions."""

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path

from .config import SUBJECTS, load_config
from .dataset import (
    IMAGE_MARKER_RE,
    _referenced_image_indices,
    build_dataset,
    build_messages as _prefix_build_messages,
)
from .scoring import evaluate
from .subset import _exact_mcnemar_p_value, read_jsonl


def configure_condition(config, image_layout):
    if config.get("experiment", {}).get("kind") != "image_layout_multi_image":
        raise ValueError("--image-layout is only valid for image_layout_multi_image")
    allowed = list(config["experiment"]["conditions"])
    if image_layout not in allowed:
        raise ValueError(f"image_layout must be one of {allowed}; got {image_layout!r}")
    output_root = Path(config["output_dir"])
    config["experiment_output_root"] = str(output_root)
    config["output_dir"] = str(output_root / image_layout)
    config["image"]["layout"] = image_layout
    config["active_condition"] = {
        "image_layout": image_layout,
        "name": image_layout,
    }
    return config


def _question_text_from_record(record):
    """Recover only the question field from dataset._prompt_text's stable envelope."""
    prompt = record["prompt"]
    question_prefix = "Question: "
    if prompt.startswith(question_prefix):
        question_and_options = prompt[len(question_prefix):]
    else:
        separator = "\n" + question_prefix
        if separator not in prompt:
            raise RuntimeError(f"{record['question_id']}: prompt has no Question field")
        question_and_options = prompt.rsplit(separator, 1)[1]
    if record["options"]:
        options_separator = "\nOptions:\n"
        if options_separator not in question_and_options:
            raise RuntimeError(f"{record['question_id']}: prompt has no Options block")
        return question_and_options.rsplit(options_separator, 1)[0]
    return question_and_options


def _manifest_from_config(config):
    selected_ids = list(config["selection"]["question_ids"])
    return {
        "method": config["selection"]["method"],
        "source_examples": config["selection"]["expected_source_examples"],
        "selected_examples": config["selection"]["expected_examples"],
        "subject_counts": config["selection"]["expected_subject_counts"],
        "question_ids": selected_ids,
    }


def load_multi_image_selection(config):
    """Validate the fixed 23 IDs using build_dataset's own question_id construction."""
    expected = _manifest_from_config(config)
    expected_ids = expected["question_ids"]
    if len(expected_ids) != expected["selected_examples"]:
        raise RuntimeError(
            f"Expected {expected['selected_examples']} fixed question IDs, got {len(expected_ids)}"
        )
    if len(set(expected_ids)) != len(expected_ids):
        raise RuntimeError("Fixed multi-image question IDs contain duplicates")

    # build_dataset is deliberately called for all 900 examples. This both reuses its
    # exact question_id logic and makes it possible to reject a missing or extra
    # multi-image question, rather than merely checking that the fixed IDs exist.
    with tempfile.TemporaryDirectory(prefix="mmmu-expd-selection-") as temporary_dir:
        temporary_root = Path(temporary_dir)
        records = build_dataset(
            config,
            temporary_root / "dataset.jsonl",
            temporary_root / "images",
        )
        actual_records = []
        for record in records:
            question_text = _question_text_from_record(record)
            distinct_markers = {
                int(match.group(1)) for match in IMAGE_MARKER_RE.finditer(question_text)
            }
            if len(distinct_markers) >= 2:
                actual_records.append(record)

    actual_ids = [record["question_id"] for record in actual_records]
    if len(records) != expected["source_examples"]:
        raise RuntimeError(
            f"Expected {expected['source_examples']} MMMU records, got {len(records)}"
        )
    if actual_ids != expected_ids:
        missing = sorted(set(expected_ids) - set(actual_ids))
        unexpected = sorted(set(actual_ids) - set(expected_ids))
        raise RuntimeError(
            "Multi-image subset differs from the fixed 23-ID manifest: "
            f"actual_count={len(actual_ids)}, missing={missing}, unexpected={unexpected}"
        )

    actual_counts = Counter(record["subject"] for record in actual_records)
    nonzero_counts = {
        subject: actual_counts[subject] for subject in SUBJECTS if actual_counts[subject]
    }
    if nonzero_counts != expected["subject_counts"]:
        raise RuntimeError(
            "Multi-image subject distribution differs from the fixed manifest: "
            f"{nonzero_counts}"
        )
    all_subject_counts = {
        subject: actual_counts.get(subject, 0) for subject in SUBJECTS
    }
    return {
        "source_count": len(records),
        "selected_ids": actual_ids,
        "selected_id_set": set(actual_ids),
        "subject_counts": all_subject_counts,
        "manifest": expected,
    }


def write_or_validate_manifest(selection_data, output_root):
    path = Path(output_root) / "subset_manifest.json"
    expected = selection_data["manifest"]
    if path.exists():
        actual = json.loads(path.read_text(encoding="utf-8"))
        if actual != expected:
            raise RuntimeError(f"Existing subset manifest does not match fixed selection: {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def _image_content(path, config):
    return {
        "type": "image",
        "image": path,
        "min_pixels": config["image"]["min_pixels"],
        "max_pixels": config["image"]["max_pixels"],
    }


def build_inline_messages(record, config):
    """Replace each first image marker occurrence with its image content block."""
    prompt = record["prompt"]
    indices = _referenced_image_indices(prompt)
    if len(indices) != len(record["image_paths"]):
        raise RuntimeError(f"{record['question_id']}: image marker/path count mismatch")
    paths_by_index = dict(zip(indices, record["image_paths"], strict=True))
    emitted = set()
    content = []
    cursor = 0
    for match in IMAGE_MARKER_RE.finditer(prompt):
        image_index = int(match.group(1))
        if cursor < match.start():
            content.append({"type": "text", "text": prompt[cursor:match.start()]})
        if image_index not in emitted:
            content.append(_image_content(paths_by_index[image_index], config))
            emitted.add(image_index)
        cursor = match.end()
    if cursor < len(prompt):
        content.append({"type": "text", "text": prompt[cursor:]})
    if emitted != set(indices):
        raise RuntimeError(f"{record['question_id']}: not all referenced images were placed inline")
    return [{"role": "user", "content": content}]


def install_layout_builder(config):
    layout = config["image"]["layout"]
    if layout not in {"inline", "prefix"}:
        raise ValueError(f"Unsupported image layout: {layout!r}")
    # run_mmmu_eval.run imports this symbol after the registry pre_run hook.
    from . import dataset

    dataset.build_messages = (
        build_inline_messages if layout == "inline" else _prefix_build_messages
    )


def _validate_condition_rows(rows, selected_ids, label):
    ids = [str(row.get("question_id")) for row in rows]
    if len(ids) != len(selected_ids) or len(set(ids)) != len(ids):
        raise RuntimeError(f"{label}: expected {len(selected_ids)} unique predictions")
    if set(ids) != set(selected_ids):
        raise RuntimeError(f"{label}: prediction IDs do not match subset manifest")


def _condition_stats(rows):
    result = evaluate([dict(row) for row in rows])
    return {
        "n": result["n_total"],
        "correct": sum(item["correct"] for item in result["details"]),
        "accuracy": sum(item["correct"] for item in result["details"]) / result["n_total"],
        "parse_failure_count": result["parse_failure_count"],
        "parse_failure_rate": result["parse_failure_count"] / result["n_total"],
        "details": result["details"],
    }


def build_comparison(config):
    output_root = Path(config.get("experiment_output_root", config["output_dir"]))
    manifest_path = output_root / "subset_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"Missing subset manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_manifest = _manifest_from_config(config)
    if manifest != expected_manifest:
        raise RuntimeError("Subset manifest differs from the fixed 23-question selection")

    selected_ids = manifest["question_ids"]
    condition_rows = {}
    for layout in config["experiment"]["conditions"]:
        path = output_root / layout / "predictions.jsonl"
        if not path.is_file():
            raise RuntimeError(f"Missing condition predictions: {path}")
        rows = read_jsonl(path)
        _validate_condition_rows(rows, selected_ids, layout)
        condition_rows[layout] = rows

    stats = {layout: _condition_stats(rows) for layout, rows in condition_rows.items()}
    details = {
        layout: {item["question_id"]: item for item in item_stats["details"]}
        for layout, item_stats in stats.items()
    }
    rows_by_id = {
        layout: {str(row["question_id"]): row for row in rows}
        for layout, rows in condition_rows.items()
    }
    transitions = Counter()
    items = []
    flipped_items = []
    for question_id in selected_ids:
        inline = details["inline"][question_id]
        prefix = details["prefix"][question_id]
        if inline["correct"] and prefix["correct"]:
            transition = "both_correct"
        elif inline["correct"] and not prefix["correct"]:
            transition = "inline_only_correct"
        elif not inline["correct"] and prefix["correct"]:
            transition = "prefix_only_correct"
        else:
            transition = "both_incorrect"
        transitions[transition] += 1
        item = {
            "question_id": question_id,
            "subject": rows_by_id["inline"][question_id]["subject"],
            "inline_correct": inline["correct"],
            "prefix_correct": prefix["correct"],
            "inline_parse_failure": inline["parse_failure"],
            "prefix_parse_failure": prefix["parse_failure"],
            "transition": transition,
        }
        items.append(item)
        if inline["correct"] != prefix["correct"]:
            flipped_items.append(item)

    inline_only = transitions["inline_only_correct"]
    prefix_only = transitions["prefix_only_correct"]
    p_value = _exact_mcnemar_p_value(prefix_only, inline_only)
    public_stats = {
        layout: {key: value for key, value in item.items() if key != "details"}
        for layout, item in stats.items()
    }
    return {
        "manifest": manifest,
        "conditions": public_stats,
        "transitions": dict(transitions),
        "flipped_count": len(flipped_items),
        "flipped_question_ids": [item["question_id"] for item in flipped_items],
        "mcnemar": {
            "test": "exact two-sided McNemar (binomial)",
            "inline_only_correct": inline_only,
            "prefix_only_correct": prefix_only,
            "discordant": inline_only + prefix_only,
            "exact_two_sided_p": p_value,
            "significant_at_0_05": p_value < 0.05,
        },
        "caveat": "The sample size is small (n=23), so statistical power is low.",
        "items": items,
    }


def write_comparison(comparison, output_root):
    output_root = Path(output_root)
    json_path = output_root / "comparison.json"
    markdown_path = output_root / "comparison.md"
    existing = [str(path) for path in [json_path, markdown_path] if path.exists()]
    if existing:
        raise RuntimeError(f"Refusing to overwrite comparison outputs: {existing}")
    json_path.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    stats = comparison["conditions"]
    test = comparison["mcnemar"]
    manifest = comparison["manifest"]
    lines = [
        "# Image layout comparison",
        "",
        f"Multi-image subset: {manifest['selected_examples']}/"
        f"{manifest['source_examples']} questions.",
        "",
        "| Layout | Correct / 23 | Accuracy | Parse failures |",
        "|---|---:|---:|---:|",
    ]
    for layout in ["inline", "prefix"]:
        item = stats[layout]
        lines.append(
            f"| {layout} | {item['correct']} / {item['n']} | {item['accuracy']:.2%} | "
            f"{item['parse_failure_count']} ({item['parse_failure_rate']:.2%}) |"
        )
    lines.extend([
        "",
        "## Paired outcome changes",
        "",
        f"Flipped questions: {comparison['flipped_count']}.",
        "",
        f"- Inline only correct: {test['inline_only_correct']}",
        f"- Prefix only correct: {test['prefix_only_correct']}",
        f"- Exact two-sided McNemar p-value: {test['exact_two_sided_p']:.6g}",
        "",
        "| Question ID | Subject | Inline correct | Prefix correct |",
        "|---|---|---:|---:|",
    ])
    flipped = set(comparison["flipped_question_ids"])
    for item in comparison["items"]:
        if item["question_id"] in flipped:
            lines.append(
                f"| {item['question_id']} | {item['subject']} | "
                f"{item['inline_correct']} | {item['prefix_correct']} |"
            )
    conclusion = (
        "The layouts have a statistically significant accuracy difference at alpha=0.05."
        if test["significant_at_0_05"]
        else "No statistically significant accuracy difference between the layouts was detected at alpha=0.05."
    )
    lines.extend([
        "",
        "## Conclusion",
        "",
        conclusion,
        "",
        "Caveat: the sample size is small (n=23), so statistical power is low; "
        "a non-significant result is not evidence that the layouts are equivalent.",
        "",
    ])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path


def maybe_write_comparison(config):
    output_root = Path(config["experiment_output_root"])
    prediction_paths = [
        output_root / layout / "predictions.jsonl"
        for layout in config["experiment"]["conditions"]
    ]
    missing = [str(path) for path in prediction_paths if not path.is_file()]
    if missing:
        print("Comparison pending; missing: " + ", ".join(missing))
        return None
    comparison = build_comparison(config)
    paths = write_comparison(comparison, output_root)
    print(f"Comparison:      {paths[1]}")
    return paths


def main():
    parser = argparse.ArgumentParser(description="Run or compare Experiment D image layouts")
    parser.add_argument("--config", required=True)
    parser.add_argument("--image-layout", choices=["inline", "prefix"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--compare-only", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    if args.compare_only:
        if args.image_layout is not None or args.dry_run:
            parser.error("--compare-only cannot be combined with --image-layout or --dry-run")
        comparison = build_comparison(config)
        json_path, markdown_path = write_comparison(comparison, config["output_dir"])
        print(f"Comparison JSON: {json_path}")
        print(f"Comparison report: {markdown_path}")
        return
    if args.image_layout is None:
        parser.error("Experiment D requires --image-layout=inline or --image-layout=prefix")

    configure_condition(config, args.image_layout)
    from run_mmmu_eval import dry_run, run

    if args.dry_run:
        dry_run(config, config_path)
    else:
        run(config, config_path)


if __name__ == "__main__":
    main()
