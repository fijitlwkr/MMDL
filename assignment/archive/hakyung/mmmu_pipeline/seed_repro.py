"""Experiment F: compare full MMMU runs under three sampling seeds."""

import argparse
import json
import statistics
from collections import Counter
from itertools import combinations
from pathlib import Path

from .config import SUBJECTS, load_config
from .scoring import evaluate
from .subset import _exact_mcnemar_p_value, read_jsonl


def configure_condition(config, seed):
    if config.get("experiment", {}).get("kind") != "seed_reproducibility":
        raise ValueError("--seed is only valid for seed_reproducibility")
    value = int(seed)
    allowed = [int(item) for item in config["experiment"]["conditions"]]
    if value not in allowed:
        raise ValueError(f"seed must be one of {allowed}; got {value}")

    output_root = Path(config["output_dir"])
    config["experiment_output_root"] = str(output_root)
    config["output_dir"] = str(output_root / f"seed_{value}")
    config["sampling"]["engine_seed"] = value
    config["sampling"]["sampling_params_seed"] = value

    engine_seed = config["sampling"]["engine_seed"]
    sampling_params_seed = config["sampling"]["sampling_params_seed"]
    if engine_seed != sampling_params_seed:
        raise ValueError("engine_seed and sampling_params_seed must be identical")
    if engine_seed not in allowed:
        raise ValueError(
            f"engine_seed must be one of experiment.conditions {allowed}; got {engine_seed}"
        )

    config["active_condition"] = {
        "seed": value,
        "name": f"seed_{value}",
    }
    return config


def load_selection(config):
    """Use the complete 30 x 30 MMMU validation set."""
    return None


def _validate_condition_rows(rows, config, label):
    expected_total = (
        config["dataset"]["expected_subjects"]
        * config["dataset"]["expected_examples_per_subject"]
    )
    ids = [str(row.get("question_id")) for row in rows]
    if len(ids) != expected_total or len(set(ids)) != expected_total:
        raise RuntimeError(f"{label}: expected {expected_total} unique predictions")
    subject_counts = Counter(str(row.get("subject")) for row in rows)
    expected_per_subject = config["dataset"]["expected_examples_per_subject"]
    if set(subject_counts) != set(SUBJECTS):
        raise RuntimeError(f"{label}: predictions do not contain exactly 30 subjects")
    wrong_counts = {
        subject: subject_counts[subject]
        for subject in SUBJECTS
        if subject_counts[subject] != expected_per_subject
    }
    if wrong_counts:
        raise RuntimeError(f"{label}: unexpected per-subject counts: {wrong_counts}")


def _condition_stats(rows):
    result = evaluate([dict(row) for row in rows])
    return {
        "n": result["n_total"],
        "correct": sum(item["correct"] for item in result["details"]),
        "macro_accuracy": result["macro_accuracy"],
        "parse_failure_count": result["parse_failure_count"],
        "macro_parse_failure_rate": result["macro_parse_failure_rate"],
        "details": result["details"],
    }


def _load_and_validate_environments(config, output_root, seeds):
    environments = {}
    for seed in seeds:
        path = output_root / f"seed_{seed}" / "env.json"
        if not path.is_file():
            raise RuntimeError(f"Missing condition environment snapshot: {path}")
        environments[str(seed)] = json.loads(path.read_text(encoding="utf-8"))

    cuda_versions = {item.get("cuda_version") for item in environments.values()}
    driver_versions = {
        tuple(item.get("driver_versions", [])) for item in environments.values()
    }
    expected_cuda = config["comparison"]["expected_cuda_version"]
    expected_driver = config["comparison"]["expected_driver_version"]
    if cuda_versions != {expected_cuda}:
        raise RuntimeError(
            f"Expected every condition to use CUDA {expected_cuda}; found {sorted(cuda_versions)}"
        )
    if driver_versions != {(expected_driver,)}:
        raise RuntimeError(
            "Expected every condition to use driver "
            f"{expected_driver}; found {sorted(driver_versions)}"
        )
    return environments


def _transition(first_correct, second_correct, first_label, second_label):
    if first_correct and second_correct:
        return "both_correct"
    if first_correct:
        return f"seed_{first_label}_only_correct"
    if second_correct:
        return f"seed_{second_label}_only_correct"
    return "both_incorrect"


def build_comparison(config):
    output_root = Path(config.get("experiment_output_root", config["output_dir"]))
    seeds = [int(item) for item in config["experiment"]["conditions"]]
    environments = _load_and_validate_environments(config, output_root, seeds)

    condition_rows = {}
    for seed in seeds:
        path = output_root / f"seed_{seed}" / "predictions.jsonl"
        if not path.is_file():
            raise RuntimeError(f"Missing condition predictions: {path}")
        rows = read_jsonl(path)
        _validate_condition_rows(rows, config, f"seed={seed}")
        condition_rows[seed] = rows

    reference_ids = [str(row["question_id"]) for row in condition_rows[seeds[0]]]
    reference_id_set = set(reference_ids)
    for seed in seeds[1:]:
        actual_ids = {str(row["question_id"]) for row in condition_rows[seed]}
        if actual_ids != reference_id_set:
            raise RuntimeError(f"seed={seed}: prediction IDs do not match seed={seeds[0]}")

    stats = {seed: _condition_stats(rows) for seed, rows in condition_rows.items()}
    details = {
        seed: {str(item["question_id"]): item for item in item_stats["details"]}
        for seed, item_stats in stats.items()
    }
    rows_by_id = {
        seed: {str(row["question_id"]): row for row in rows}
        for seed, rows in condition_rows.items()
    }

    items = []
    for question_id in reference_ids:
        item = {
            "question_id": question_id,
            "subject": rows_by_id[seeds[0]][question_id]["subject"],
            "conditions": {},
        }
        for seed in seeds:
            score = details[seed][question_id]
            generation = rows_by_id[seed][question_id]
            item["conditions"][str(seed)] = {
                "correct": score["correct"],
                "parse_failure": score["parse_failure"],
                "finish_reason": generation["finish_reason"],
                "output_tokens": generation["output_tokens"],
            }
        items.append(item)

    pairwise = []
    for first_seed, second_seed in combinations(seeds, 2):
        transitions = Counter()
        flipped_items = []
        for item in items:
            first_correct = item["conditions"][str(first_seed)]["correct"]
            second_correct = item["conditions"][str(second_seed)]["correct"]
            transition = _transition(
                first_correct, second_correct, first_seed, second_seed
            )
            transitions[transition] += 1
            if first_correct != second_correct:
                flipped_items.append({
                    "question_id": item["question_id"],
                    "subject": item["subject"],
                    f"seed_{first_seed}_correct": first_correct,
                    f"seed_{second_seed}_correct": second_correct,
                    "transition": transition,
                })
        first_only = transitions[f"seed_{first_seed}_only_correct"]
        second_only = transitions[f"seed_{second_seed}_only_correct"]
        p_value = _exact_mcnemar_p_value(first_only, second_only)
        pairwise.append({
            "first_seed": first_seed,
            "second_seed": second_seed,
            "transitions": dict(transitions),
            "flipped_count": len(flipped_items),
            "flipped_items": flipped_items,
            "mcnemar": {
                "test": "exact two-sided McNemar (binomial)",
                f"seed_{first_seed}_only_correct": first_only,
                f"seed_{second_seed}_only_correct": second_only,
                "discordant": first_only + second_only,
                "exact_two_sided_p": p_value,
                "significant_at_0_05": p_value < 0.05,
            },
        })

    macro_accuracies = [stats[seed]["macro_accuracy"] for seed in seeds]
    public_stats = {
        str(seed): {key: value for key, value in stats[seed].items() if key != "details"}
        for seed in seeds
    }
    environment_summary = {
        "cuda_version": config["comparison"]["expected_cuda_version"],
        "driver_version": config["comparison"]["expected_driver_version"],
        "historical_exp0_cuda_version": config["comparison"]["historical_exp0_cuda_version"],
        "snapshots": {
            str(seed): str(output_root / f"seed_{seed}" / "env.json") for seed in seeds
        },
        "validated_condition_count": len(environments),
    }
    return {
        "conditions": public_stats,
        "pairwise": pairwise,
        "macro_accuracy_dispersion": {
            "method": "population standard deviation (statistics.pstdev)",
            "value": statistics.pstdev(macro_accuracies),
        },
        "environment": environment_summary,
        "caveat": (
            "Each seed was run only once. This compares outcomes across three seeds, but "
            "does not measure whether any one seed is reproducible across repeated runs."
        ),
        "items": items,
    }


def write_comparison(comparison, output_root):
    output_root = Path(output_root)
    json_path = output_root / "comparison.json"
    markdown_path = output_root / "comparison.md"
    existing = [str(path) for path in (json_path, markdown_path) if path.exists()]
    if existing:
        raise RuntimeError(f"Refusing to overwrite comparison outputs: {existing}")
    json_path.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    stats = comparison["conditions"]
    lines = [
        "# Seed reproducibility comparison",
        "",
        "All conditions are fresh runs over the complete 900-question MMMU validation set.",
        "",
        "| Seed | Correct / 900 | Macro accuracy | Parse failures |",
        "|---:|---:|---:|---:|",
    ]
    for seed, item in stats.items():
        lines.append(
            f"| {seed} | {item['correct']} / {item['n']} | "
            f"{item['macro_accuracy']:.2%} | {item['parse_failure_count']} |"
        )

    dispersion = comparison["macro_accuracy_dispersion"]
    lines.extend([
        "",
        "## Seed-to-seed dispersion",
        "",
        f"Macro accuracy standard deviation: {dispersion['value']:.6f} "
        f"({dispersion['method']}).",
        "",
        "## Pairwise exact McNemar tests",
        "",
        "| Seeds | Flips | First only correct | Second only correct | Exact p-value | Significant (0.05) |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for pair in comparison["pairwise"]:
        first = pair["first_seed"]
        second = pair["second_seed"]
        test = pair["mcnemar"]
        lines.append(
            f"| {first} vs {second} | {pair['flipped_count']} | "
            f"{test[f'seed_{first}_only_correct']} | "
            f"{test[f'seed_{second}_only_correct']} | "
            f"{test['exact_two_sided_p']:.6g} | {test['significant_at_0_05']} |"
        )

    for pair in comparison["pairwise"]:
        first = pair["first_seed"]
        second = pair["second_seed"]
        lines.extend([
            "",
            f"### Flips: seed {first} vs seed {second}",
            "",
            "| Question ID | Subject | First correct | Second correct | Transition |",
            "|---|---|---:|---:|---|",
        ])
        if not pair["flipped_items"]:
            lines.append("| — | — | — | — | No flips |")
        for item in pair["flipped_items"]:
            lines.append(
                f"| {item['question_id']} | {item['subject']} | "
                f"{item[f'seed_{first}_correct']} | "
                f"{item[f'seed_{second}_correct']} | {item['transition']} |"
            )

    significant_pairs = [
        f"{pair['first_seed']} vs {pair['second_seed']}"
        for pair in comparison["pairwise"]
        if pair["mcnemar"]["significant_at_0_05"]
    ]
    conclusion = (
        "Statistically significant accuracy differences at alpha=0.05 were detected for: "
        + ", ".join(significant_pairs) + "."
        if significant_pairs
        else "No seed pair showed a statistically significant accuracy difference at alpha=0.05."
    )
    environment = comparison["environment"]
    lines.extend([
        "",
        "## Environment",
        "",
        f"세 조건 모두 동일 환경(CUDA {environment['cuda_version']}, driver "
        f"{environment['driver_version']})에서 실행되었다. 과거 exp0의 seed=42도 동일 환경"
        f"(CUDA {environment['historical_exp0_cuda_version']})에서 실행되어, 이번 세 조건과 "
        f"exp0 결과를 함께 직접 비교할 수 있다.",
        "",
        "## Conclusion",
        "",
        conclusion,
        "",
        "각 seed는 1회만 실행했으므로, 이 실험은 세 seed 간 결과가 다른지만 보여준다. "
        "특정 seed 자체가 반복 실행에도 안정적인지(재현성)는 측정하지 못하며, 이를 "
        "측정하려면 동일 seed의 반복 실행이 필요하지만 이번 실험 예산에는 포함되지 않았다.",
        "",
    ])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path


def maybe_write_comparison(config):
    output_root = Path(config["experiment_output_root"])
    prediction_paths = [
        output_root / f"seed_{seed}" / "predictions.jsonl"
        for seed in config["experiment"]["conditions"]
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
    parser = argparse.ArgumentParser(description="Run or compare Experiment F sampling seeds")
    parser.add_argument("--config", required=True)
    parser.add_argument("--seed", type=int, choices=[42, 3407, 1234])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--compare-only", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    if args.compare_only:
        if args.seed is not None or args.dry_run:
            parser.error("--compare-only cannot be combined with --seed or --dry-run")
        comparison = build_comparison(config)
        json_path, markdown_path = write_comparison(comparison, config["output_dir"])
        print(f"Comparison JSON: {json_path}")
        print(f"Comparison report: {markdown_path}")
        return
    if args.seed is None:
        parser.error("Experiment F requires --seed=42, --seed=3407, or --seed=1234")

    configure_condition(config, args.seed)
    from run_mmmu_eval import dry_run, run

    if args.dry_run:
        dry_run(config, config_path)
    else:
        run(config, config_path)


if __name__ == "__main__":
    main()
