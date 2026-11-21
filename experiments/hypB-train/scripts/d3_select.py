"""Measure frozen D3 development raw files and apply the fixed selection rule."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics

from classify_answers import ROOT, read_rows, write_json
from d3_prepare import DEV, SPLIT, SOURCE, stratum
from sample_m0 import MARKERS, read_raw, request_seed, run_reward, seed_index, sha


NAMES = ("M0", "epoch1", "epoch2")


def metrics(rows, layers):
    total = len(rows)
    counts = defaultdict(lambda: [0, 0])
    for row in rows:
        counts[layers[row["row"]]][0] += row["reward"]
        counts[layers[row["row"]]][1] += 1
    correct = sum(row["reward"] for row in rows)
    return {"responses": total, "correct": correct, "reward_mean": correct / total,
            "length_rate": sum(row["finish_reason"] == "length" for row in rows) / total,
            "mean_output_tokens": statistics.mean(row["output_tokens"] for row in rows),
            "direction_overuse_rate": sum(row["marker_count"] >= 21 for row in rows) / total,
            "by_stratum": {name: {"correct": values[0], "responses": values[1], "reward_mean": values[0] / values[1]}
                           for name, values in sorted(counts.items())}}


def select(measurements):
    assert set(measurements) == set(NAMES)
    total = measurements["M0"]["responses"]
    assert total > 0 and all(value["responses"] == total for value in measurements.values())
    baseline = measurements["M0"]["correct"]
    eligible = [name for name in NAMES[1:] if measurements[name]["correct"] >= baseline]
    if not eligible:
        chosen, reason = None, "Neither checkpoint reaches the M0 reward mean"
    elif len(eligible) == 1:
        chosen, reason = eligible[0], "Only this checkpoint reaches the M0 reward mean"
    elif abs(measurements["epoch1"]["correct"] - measurements["epoch2"]["correct"]) * 200 < total:
        chosen, reason = "epoch1", "Both qualify and their reward means differ by less than 0.5 percentage points"
    else:
        chosen = max(eligible, key=lambda name: measurements[name]["correct"])
        reason = "Both qualify; select the higher reward mean"
    return {"selected": chosen, "eligible": eligible, "reason": reason,
            "difference_threshold_pp": 0.5, "other_metrics_used_for_selection": False}


def validate_raw(path, items, layers, score):
    values = read_raw(path)
    expected = {(row, repeat) for row in items for repeat in range(4, 8)}
    seen = set()
    for sample in values:
        pair = sample["row"], sample["repeat"]
        assert pair in expected and pair not in seen, (path, pair)
        seen.add(pair)
        item = items[sample["row"]]
        assert sample["seed"] == request_seed(seed_index(item), sample["repeat"])
        assert sample["prompt_tokens"] == item["prompt_tokens"]
        assert sample["finish_reason"] in ("stop", "length") and 0 < sample["output_tokens"] <= 8192
        assert sample["finish_reason"] != "length" or sample["output_tokens"] == 8192
        assert (sample["reward"], sample["reward_reason"]) == score(sample["raw_text"], sample["finish_reason"], item)
        assert sample["marker_count"] == len(MARKERS.findall(sample["raw_text"]))
    assert seen == expected and len(values) == 1200
    return metrics(values, layers)


def self_test():
    cases = (("epoch1_higher", (600, 660, 640), "epoch1"),
             ("epoch2_higher", (600, 640, 660), "epoch2"),
             ("neither_qualifies", (600, 599, 598), None),
             ("within_half_point", (600, 640, 645), "epoch1"),
             ("exact_half_point", (600, 640, 646), "epoch2"),
             ("only_epoch2_qualifies", (600, 599, 600), "epoch2"))
    tests = []
    for name, rewards, expected in cases:
        values = {}
        for model, count in zip(NAMES, rewards, strict=True):
            fake = [{"row": str(index), "reward": int(index < count), "finish_reason": "stop",
                     "output_tokens": 10, "marker_count": 0} for index in range(1200)]
            values[model] = metrics(fake, {str(index): "synthetic" for index in range(1200)})
        actual = select(values)
        assert actual["selected"] == expected, (name, actual)
        tests.append({"case": name, "correct_counts": dict(zip(NAMES, rewards)), "expected": expected,
                      "actual": actual["selected"], "passed": True})
    write_json(ROOT / "reports/d3_selection_tests.json", {"status": "PASS", "synthetic": True, "tests": tests})
    print("D3 selection synthetic tests PASS", len(tests))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", nargs="*", type=Path, help="M0 epoch1 epoch2 development raw, in that order")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        if args.raw or args.out:
            parser.error("Synthetic checks do not accept real input or an output path")
        self_test()
        return
    if len(args.raw) != 3:
        parser.error("Supply the three development raw files: M0 epoch1 epoch2")
    split = json.loads(SPLIT.read_bytes())
    items = {item["row"]: item for item in read_rows(DEV)}
    assert len(items) == 300 and set(items) == set(split["development_rows"])
    groups = {group["row"]: group for group in json.loads((SOURCE / "groups.json").read_bytes())["groups"]}
    layers = {row: stratum(groups[row]) for row in items}
    score, reward_identity = run_reward(True)
    measurements = {name: validate_raw(path, items, layers, score) for name, path in zip(NAMES, args.raw, strict=True)}
    result = {"measurements": measurements, "selection": select(measurements), "reward": reward_identity,
              "development_sha256": sha(DEV), "raw_sha256": {name: sha(path) for name, path in zip(NAMES, args.raw, strict=True)}}
    if args.out:
        if args.out.exists():
            raise FileExistsError(args.out)
        write_json(args.out, result)
    print("model\treward_mean\tlength_rate\tmean_output_tokens\tdirection_overuse_rate")
    for name, value in measurements.items():
        print(name, *(value[key] for key in ("reward_mean", "length_rate", "mean_output_tokens", "direction_overuse_rate")), sep="\t")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
