import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .config import SUBJECTS
from .scoring import evaluate


def read_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            rows.append(row)
    return rows


def configure_condition(config, presence_penalty):
    if config.get("experiment", {}).get("kind") != "presence_penalty_stratified":
        raise ValueError("--presence-penalty is only valid for presence_penalty_stratified")
    value = float(presence_penalty)
    allowed = [float(item) for item in config["experiment"]["conditions"]]
    if value not in allowed:
        raise ValueError(f"presence_penalty must be one of {allowed}; got {value}")
    output_root = Path(config["output_dir"])
    label = str(value).replace(".", "_")
    config["experiment_output_root"] = str(output_root)
    config["output_dir"] = str(output_root / f"presence_penalty_{label}")
    config["sampling"]["presence_penalty"] = value
    config["active_condition"] = {
        "presence_penalty": value,
        "name": f"presence_penalty_{label}",
    }
    return config


def build_stratified_selection(config):
    selection = config["selection"]
    if selection["seed"] in {
        config["sampling"]["engine_seed"],
        config["sampling"]["sampling_params_seed"],
    }:
        raise ValueError("Stratified sampling seed must be independent from model sampling seeds")
    source_rows = read_jsonl(selection["source_predictions"])
    if len(source_rows) != selection["expected_source_examples"]:
        raise RuntimeError(
            f"Expected {selection['expected_source_examples']} source predictions, "
            f"found {len(source_rows)}"
        )

    by_subject = defaultdict(list)
    seen_ids = set()
    for line_number, row in enumerate(source_rows, start=1):
        missing = {
            "question_id", "subject", "raw_text", "finish_reason", "output_tokens",
            "answer", "question_type", "options",
        } - row.keys()
        if missing:
            raise ValueError(
                f"source predictions line {line_number}: missing {sorted(missing)}"
            )
        question_id = str(row["question_id"])
        if question_id in seen_ids:
            raise ValueError(f"Duplicate source question_id: {question_id}")
        seen_ids.add(question_id)
        by_subject[str(row["subject"])].append(row)

    expected_per_subject = config["dataset"]["expected_examples_per_subject"]
    if set(by_subject) != set(SUBJECTS):
        raise RuntimeError("Source predictions do not contain exactly the configured 30 subjects")
    wrong_counts = {
        subject: len(by_subject[subject])
        for subject in SUBJECTS
        if len(by_subject[subject]) != expected_per_subject
    }
    if wrong_counts:
        raise RuntimeError(f"Source subject counts are not fixed at 30: {wrong_counts}")

    sample_size = selection["expected_examples"]
    base_count, remainder = divmod(sample_size, len(SUBJECTS))
    rng = random.Random(selection["seed"])
    seven_item_subjects = set(rng.sample(SUBJECTS, remainder))
    allocations = {
        subject: base_count + (subject in seven_item_subjects) for subject in SUBJECTS
    }

    selected_rows = []
    selected_ids_by_subject = {}
    for subject in SUBJECTS:
        candidates = sorted(by_subject[subject], key=lambda row: str(row["question_id"]))
        chosen = rng.sample(candidates, allocations[subject])
        chosen.sort(key=lambda row: str(row["question_id"]))
        selected_rows.extend(chosen)
        selected_ids_by_subject[subject] = [str(row["question_id"]) for row in chosen]

    selected_ids = [str(row["question_id"]) for row in selected_rows]
    if len(selected_ids) != sample_size or len(set(selected_ids)) != sample_size:
        raise RuntimeError("Stratified selection did not produce 200 unique question IDs")
    if Counter(allocations.values()) != Counter({7: 20, 6: 10}):
        raise RuntimeError(f"Unexpected per-subject allocation: {allocations}")

    manifest = {
        "method": selection["method"],
        "sampling_seed": selection["seed"],
        "model_engine_seed": config["sampling"]["engine_seed"],
        "sampling_params_seed": config["sampling"]["sampling_params_seed"],
        "source_predictions": selection["source_predictions"],
        "source_examples": len(source_rows),
        "selected_examples": len(selected_ids),
        "allocation_rule": "20 subjects x 7 items + 10 subjects x 6 items",
        "subject_counts": allocations,
        "question_ids_by_subject": selected_ids_by_subject,
        "question_ids": selected_ids,
    }
    return {
        "source_rows": source_rows,
        "selected_rows": selected_rows,
        "selected_ids": selected_ids,
        "selected_id_set": set(selected_ids),
        "manifest": manifest,
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


def _condition_stats(rows):
    copied = [dict(row) for row in rows]
    result = evaluate(copied)
    correct = sum(item["correct"] for item in result["details"])
    output_tokens = [int(row["output_tokens"]) for row in copied]
    length_count = sum(row["finish_reason"] == "length" for row in copied)
    return {
        "n": len(copied),
        "correct": correct,
        "accuracy": correct / len(copied),
        "mean_output_tokens": statistics.fmean(output_tokens),
        "median_output_tokens": statistics.median(output_tokens),
        "parse_failure_count": result["parse_failure_count"],
        "parse_failure_rate": result["parse_failure_count"] / len(copied),
        "length_count": length_count,
        "length_rate": length_count / len(copied),
        "details": result["details"],
    }


def _validate_condition_rows(rows, selected_ids, label):
    ids = [str(row.get("question_id")) for row in rows]
    if len(ids) != len(selected_ids) or len(set(ids)) != len(ids):
        raise RuntimeError(f"{label}: expected {len(selected_ids)} unique predictions")
    if set(ids) != set(selected_ids):
        raise RuntimeError(f"{label}: prediction IDs do not match subset manifest")


def build_three_way_comparison(config):
    selection_data = build_stratified_selection(config)
    output_root = Path(config["output_dir"])
    manifest_path = output_root / "subset_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"Missing subset manifest: {manifest_path}")
    actual_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if actual_manifest != selection_data["manifest"]:
        raise RuntimeError("Subset manifest differs from the fixed stratified sample")

    condition_paths = {
        "0": output_root / "presence_penalty_0_0" / "predictions.jsonl",
        "0.5": output_root / "presence_penalty_0_5" / "predictions.jsonl",
    }
    condition_rows = {}
    for label, path in condition_paths.items():
        if not path.is_file():
            raise RuntimeError(f"Missing condition predictions: {path}")
        rows = read_jsonl(path)
        _validate_condition_rows(rows, selection_data["selected_ids"], label)
        condition_rows[label] = rows

    selected_ids = selection_data["selected_id_set"]
    reference_rows = [
        row for row in selection_data["source_rows"] if str(row["question_id"]) in selected_ids
    ]
    _validate_condition_rows(reference_rows, selection_data["selected_ids"], "1.5 reference")
    condition_rows["1.5"] = reference_rows

    stats = {label: _condition_stats(rows) for label, rows in condition_rows.items()}
    detail_maps = {
        label: {item["question_id"]: item for item in item["details"]}
        for label, item in stats.items()
    }
    per_subject = []
    for subject in SUBJECTS:
        row = {"subject": subject, "n": selection_data["manifest"]["subject_counts"][subject]}
        for label in ["0", "0.5", "1.5"]:
            subject_details = [
                item for item in stats[label]["details"] if item["subject"] == subject
            ]
            row[label] = {
                "correct": sum(item["correct"] for item in subject_details),
                "accuracy": sum(item["correct"] for item in subject_details) / len(subject_details),
                "parse_failures": sum(item["parse_failure"] for item in subject_details),
            }
        per_subject.append(row)

    items = []
    rows_by_condition = {
        label: {str(row["question_id"]): row for row in rows}
        for label, rows in condition_rows.items()
    }
    for question_id in selection_data["selected_ids"]:
        item = {
            "question_id": question_id,
            "subject": rows_by_condition["1.5"][question_id]["subject"],
            "conditions": {},
        }
        for label in ["0", "0.5", "1.5"]:
            generation = rows_by_condition[label][question_id]
            score = detail_maps[label][question_id]
            item["conditions"][label] = {
                "correct": score["correct"],
                "parse_failure": score["parse_failure"],
                "finish_reason": generation["finish_reason"],
                "output_tokens": generation["output_tokens"],
            }
        items.append(item)

    public_stats = {
        label: {key: value for key, value in item.items() if key != "details"}
        for label, item in stats.items()
    }
    lengths = [stats[label]["mean_output_tokens"] for label in ["0", "0.5", "1.5"]]
    parse_rates = [stats[label]["parse_failure_rate"] for label in ["0", "0.5", "1.5"]]
    truncation_rates = [stats[label]["length_rate"] for label in ["0", "0.5", "1.5"]]
    exp0_length_count = sum(
        row["finish_reason"] == "length" for row in selection_data["source_rows"]
    )
    if exp0_length_count != config["comparison"]["exp0_length_count"]:
        raise RuntimeError(
            f"Expected {config['comparison']['exp0_length_count']} exp0 truncations, "
            f"found {exp0_length_count}"
        )
    return {
        "manifest": selection_data["manifest"],
        "conditions": public_stats,
        "per_subject": per_subject,
        "trend_checks": {
            "lower_penalty_has_non_longer_mean_response": lengths[0] <= lengths[1] <= lengths[2],
            "lower_penalty_has_non_higher_parse_failure_rate": (
                parse_rates[0] <= parse_rates[1] <= parse_rates[2]
            ),
            "lower_penalty_has_non_higher_length_rate": (
                truncation_rates[0] <= truncation_rates[1] <= truncation_rates[2]
            ),
        },
        "truncation_context": {
            "exp0_full_length_count": exp0_length_count,
            "exp0_full_examples": len(selection_data["source_rows"]),
            "exp0_full_length_rate": exp0_length_count / len(selection_data["source_rows"]),
            "note": (
                "Experiment B changes generation budget for truncation cases; "
                "Experiment C holds the original budget fixed and varies presence_penalty."
            ),
        },
        "items": items,
    }


def write_three_way_comparison(comparison, output_root):
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
    trend = comparison["trend_checks"]
    context = comparison["truncation_context"]
    lines = [
        "# Presence penalty comparison",
        "",
        f"Stratified subset seed: `{comparison['manifest']['sampling_seed']}` "
        f"(model/sampling seed: `{comparison['manifest']['model_engine_seed']}`)",
        "",
        "| presence_penalty | Correct / 200 | Accuracy | Mean output tokens | "
        "Parse failures | Length truncations |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for label in ["0", "0.5", "1.5"]:
        item = stats[label]
        reference = " (exp0 reused)" if label == "1.5" else ""
        lines.append(
            f"| {label}{reference} | {item['correct']} / {item['n']} | "
            f"{item['accuracy']:.2%} | {item['mean_output_tokens']:.2f} | "
            f"{item['parse_failure_count']} ({item['parse_failure_rate']:.2%}) | "
            f"{item['length_count']} ({item['length_rate']:.2%}) |"
        )
    lines.extend([
        "",
        "## Per-subject accuracy",
        "",
        "| Subject | N | penalty 0 | penalty 0.5 | penalty 1.5 |",
        "|---|---:|---:|---:|---:|",
    ])
    for item in comparison["per_subject"]:
        lines.append(
            f"| {item['subject']} | {item['n']} | {item['0']['accuracy']:.2%} | "
            f"{item['0.5']['accuracy']:.2%} | {item['1.5']['accuracy']:.2%} |"
        )
    lines.extend([
        "",
        "## Trend check",
        "",
        f"- Lower penalty → non-longer mean response: "
        f"`{trend['lower_penalty_has_non_longer_mean_response']}`",
        f"- Lower penalty → non-higher parse failure rate: "
        f"`{trend['lower_penalty_has_non_higher_parse_failure_rate']}`",
        f"- Lower penalty → non-higher length truncation rate: "
        f"`{trend['lower_penalty_has_non_higher_length_rate']}`",
        "",
        "Conclusion: the hypothesis that lower presence_penalty shortens responses and reduces "
        "both parse failures and length truncation is "
        + (
            "supported by all three observed monotonic checks."
            if all(trend.values())
            else "not supported by all three observed monotonic checks; see the numeric table above."
        ),
        "",
        f"exp0 had {context['exp0_full_length_count']}/{context['exp0_full_examples']} "
        f"({context['exp0_full_length_rate']:.2%}) length truncations. Experiment B tests "
        "whether increasing the token budget rescues that group; this experiment instead keeps "
        "the original 2048/9048 budget and measures whether lowering presence_penalty reduces "
        "response length, parse failures, and truncation.",
        "",
    ])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path
