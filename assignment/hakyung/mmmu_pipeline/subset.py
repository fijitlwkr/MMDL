import json
import math
from collections import Counter
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


def load_truncation_selection(config):
    selection = config.get("selection")
    if selection is None:
        return None
    rows = read_jsonl(selection["source_predictions"])
    expected_source = selection["expected_source_examples"]
    if len(rows) != expected_source:
        raise RuntimeError(
            f"Expected {expected_source} source predictions, found {len(rows)}"
        )

    by_id = {}
    subject_counts = Counter()
    for line_number, row in enumerate(rows, start=1):
        missing = {"question_id", "subject", "finish_reason", "raw_text", "answer"} - row.keys()
        if missing:
            raise ValueError(
                f"source predictions line {line_number}: missing {sorted(missing)}"
            )
        question_id = str(row["question_id"])
        if question_id in by_id:
            raise ValueError(f"Duplicate source question_id: {question_id}")
        by_id[question_id] = row
        subject_counts[str(row["subject"])] += 1

    expected_per_subject = config["dataset"]["expected_examples_per_subject"]
    if set(subject_counts) != set(SUBJECTS):
        raise RuntimeError("Source predictions do not contain exactly the configured 30 subjects")
    wrong_subject_counts = {
        subject: subject_counts[subject]
        for subject in SUBJECTS
        if subject_counts[subject] != expected_per_subject
    }
    if wrong_subject_counts:
        raise RuntimeError(
            f"Source predictions are not 30 examples per subject: {wrong_subject_counts}"
        )

    reason = selection["finish_reason"]
    selected_rows = [row for row in rows if row["finish_reason"] == reason]
    expected_selected = selection["expected_examples"]
    if len(selected_rows) != expected_selected:
        raise RuntimeError(
            f"Expected {expected_selected} finish_reason={reason!r} rows, "
            f"found {len(selected_rows)}"
        )
    selected_ids = [str(row["question_id"]) for row in selected_rows]
    selected_subject_counts = Counter(str(row["subject"]) for row in selected_rows)
    return {
        "source_rows": rows,
        "source_by_id": by_id,
        "selected_rows": selected_rows,
        "selected_ids": selected_ids,
        "selected_id_set": set(selected_ids),
        "subject_counts": {
            subject: selected_subject_counts.get(subject, 0) for subject in SUBJECTS
        },
    }


def _exact_mcnemar_p_value(improved, regressed):
    discordant = improved + regressed
    if discordant == 0:
        return 1.0
    tail = sum(
        math.comb(discordant, value)
        for value in range(min(improved, regressed) + 1)
    ) / (2 ** discordant)
    return min(1.0, 2 * tail)


def build_comparison(config, selection_data, expanded_rows):
    original_rows = [dict(row) for row in selection_data["selected_rows"]]
    expanded_rows = [dict(row) for row in expanded_rows]
    original_result = evaluate(original_rows)
    expanded_result = evaluate(expanded_rows)
    original_details = {item["question_id"]: item for item in original_result["details"]}
    expanded_details = {item["question_id"]: item for item in expanded_result["details"]}
    expected_ids = selection_data["selected_id_set"]
    if set(original_details) != expected_ids or set(expanded_details) != expected_ids:
        raise RuntimeError("Original and expanded comparison IDs do not match the selected subset")

    transitions = Counter()
    items = []
    for question_id in selection_data["selected_ids"]:
        original = original_details[question_id]
        expanded = expanded_details[question_id]
        if original["correct"] and expanded["correct"]:
            transition = "both_correct"
        elif not original["correct"] and expanded["correct"]:
            transition = "improved"
        elif original["correct"] and not expanded["correct"]:
            transition = "regressed"
        else:
            transition = "both_incorrect"
        transitions[transition] += 1
        expanded_generation = next(
            row for row in expanded_rows if row["question_id"] == question_id
        )
        items.append({
            "question_id": question_id,
            "subject": original["subject"],
            "original_correct": original["correct"],
            "expanded_correct": expanded["correct"],
            "transition": transition,
            "original_finish_reason": selection_data["source_by_id"][question_id]["finish_reason"],
            "expanded_finish_reason": expanded_generation["finish_reason"],
        })

    total = len(items)
    original_correct = sum(item["original_correct"] for item in items)
    expanded_correct = sum(item["expanded_correct"] for item in items)
    per_subject = []
    for subject in SUBJECTS:
        subject_items = [item for item in items if item["subject"] == subject]
        if not subject_items:
            per_subject.append({
                "subject": subject,
                "n": 0,
                "original_correct": 0,
                "original_accuracy": None,
                "expanded_correct": 0,
                "expanded_accuracy": None,
                "accuracy_delta": None,
            })
            continue
        old_correct = sum(item["original_correct"] for item in subject_items)
        new_correct = sum(item["expanded_correct"] for item in subject_items)
        per_subject.append({
            "subject": subject,
            "n": len(subject_items),
            "original_correct": old_correct,
            "original_accuracy": old_correct / len(subject_items),
            "expanded_correct": new_correct,
            "expanded_accuracy": new_correct / len(subject_items),
            "accuracy_delta": (new_correct - old_correct) / len(subject_items),
        })

    full_original_rows = [dict(row) for row in selection_data["source_rows"]]
    full_original_result = evaluate(full_original_rows)
    full_original_correct = sum(
        item["correct"] for item in full_original_result["details"]
    )
    projected_correct = full_original_correct - original_correct + expanded_correct
    still_length_ids = sorted(
        item["question_id"]
        for item in items
        if item["expanded_finish_reason"] == "length"
    )
    improved = transitions["improved"]
    regressed = transitions["regressed"]
    p_value = _exact_mcnemar_p_value(improved, regressed)
    context = config["comparison_context"]
    return {
        "budgets": {
            "original": config["selection"]["source_generation_budget"],
            "expanded": config["generation_budget"],
        },
        "subset": {
            "n": total,
            "original_correct": original_correct,
            "original_accuracy": original_correct / total,
            "expanded_correct": expanded_correct,
            "expanded_accuracy": expanded_correct / total,
            "accuracy_delta": (expanded_correct - original_correct) / total,
            "transitions": dict(transitions),
            "mcnemar_exact_two_sided_p": p_value,
            "significant_at_0_05": p_value < 0.05,
        },
        "per_subject": per_subject,
        "remaining_truncation": {
            "count": len(still_length_ids),
            "rate": len(still_length_ids) / total,
            "question_ids": still_length_ids,
        },
        "full_900_projection": {
            "method": "replace the original 230 subset outcomes with expanded-budget outcomes",
            "original_correct": full_original_correct,
            "original_accuracy": full_original_correct / len(full_original_rows),
            "projected_correct": projected_correct,
            "projected_accuracy": projected_correct / len(full_original_rows),
            "accuracy_point_delta": (expanded_correct - original_correct) / len(full_original_rows),
        },
        "experiment_a_context": {
            "judge_final_failures": context["experiment_a_judge_final_failures"],
            "finish_reason_length": context["experiment_a_length_failures"],
            "length_share": (
                context["experiment_a_length_failures"]
                / context["experiment_a_judge_final_failures"]
            ),
        },
        "items": items,
    }


def write_subset_summary(config, selection_data, output_dir):
    summary = {
        "source_predictions": config["selection"]["source_predictions"],
        "source_examples": len(selection_data["source_rows"]),
        "selection": {
            "finish_reason": config["selection"]["finish_reason"],
            "count": len(selection_data["selected_rows"]),
            "rate": len(selection_data["selected_rows"]) / len(selection_data["source_rows"]),
        },
        "subject_counts": selection_data["subject_counts"],
        "question_ids": selection_data["selected_ids"],
    }
    output_dir = Path(output_dir)
    (output_dir / "subset_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Truncation subset",
        "",
        f"- Source examples: {summary['source_examples']}",
        f"- `finish_reason={config['selection']['finish_reason']}`: "
        f"{summary['selection']['count']} ({summary['selection']['rate']:.2%})",
        "",
        "| Subject | Count |",
        "|---|---:|",
    ]
    lines.extend(
        f"| {subject} | {count} |"
        for subject, count in selection_data["subject_counts"].items()
    )
    (output_dir / "subset_summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def write_comparison(comparison, output_dir):
    output_dir = Path(output_dir)
    (output_dir / "comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    subset = comparison["subset"]
    remaining = comparison["remaining_truncation"]
    projection = comparison["full_900_projection"]
    context = comparison["experiment_a_context"]
    lines = [
        "# MMMU truncation budget comparison",
        "",
        "| Budget | Correct / subset | Accuracy |",
        "|---|---:|---:|",
        f"| Original (2048 / 9048) | {subset['original_correct']} / {subset['n']} | "
        f"{subset['original_accuracy']:.2%} |",
        f"| Expanded (8192 / 16384) | {subset['expanded_correct']} / {subset['n']} | "
        f"{subset['expanded_accuracy']:.2%} |",
        "",
        f"Accuracy delta: {subset['accuracy_delta']:+.2%}; paired exact McNemar "
        f"p={subset['mcnemar_exact_two_sided_p']:.6g} "
        f"(significant at 0.05: {subset['significant_at_0_05']}).",
        "",
        "| Outcome transition | Items |",
        "|---|---:|",
        f"| Incorrect → correct | {subset['transitions'].get('improved', 0)} |",
        f"| Correct → incorrect | {subset['transitions'].get('regressed', 0)} |",
        f"| Both correct | {subset['transitions'].get('both_correct', 0)} |",
        f"| Both incorrect | {subset['transitions'].get('both_incorrect', 0)} |",
        "",
        "## Per-subject comparison",
        "",
        "| Subject | N | Original | Expanded | Delta |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in comparison["per_subject"]:
        if item["n"] == 0:
            lines.append(f"| {item['subject']} | 0 | — | — | — |")
        else:
            lines.append(
                f"| {item['subject']} | {item['n']} | {item['original_accuracy']:.2%} | "
                f"{item['expanded_accuracy']:.2%} | {item['accuracy_delta']:+.2%} |"
            )
    lines.extend([
        "",
        "## Remaining truncation",
        "",
        f"`finish_reason=length` after expansion: {remaining['count']}/{subset['n']} "
        f"({remaining['rate']:.2%}).",
        "",
        "## Potential full-set impact",
        "",
        f"Replacing only these subset outcomes projects the 900-item score from "
        f"{projection['original_correct']}/900 ({projection['original_accuracy']:.2%}) to "
        f"{projection['projected_correct']}/900 ({projection['projected_accuracy']:.2%}), "
        f"a {projection['accuracy_point_delta']:+.2%} point change. This is a replacement "
        "projection, not a fresh 900-item rerun.",
        "",
        f"Experiment A left {context['judge_final_failures']} judge failures, of which "
        f"{context['finish_reason_length']} ({context['length_share']:.2%}) had "
        "`finish_reason=length`; the observed subset result indicates how much generation-budget "
        "expansion can address that failure mode.",
        "",
    ])
    (output_dir / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
