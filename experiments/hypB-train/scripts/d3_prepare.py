"""Freeze D3 development rows and preference pairs from the R1 training pool."""

from collections import Counter, defaultdict
import json
import random

import build_dpo_pairs as d1
from build_groups import classify
from classify_answers import ROOT, read_rows, write_json, write_rows
from sample_m0 import SEED, example_for, read_raw, request_seed, seed_index, sha


POOL = ROOT / "data/r1_pool.jsonl"
SOURCE = ROOT / "runs/full_k4"
DEV = ROOT / "data/d3_dev.jsonl"
SPLIT = ROOT / "data/d3_split.json"
PAIRS = ROOT / "data/d3_pairs_swift.jsonl"
INDEX = ROOT / "data/d3_pairs_index.jsonl"


def verify_inputs():
    hashes = d1.verify_inputs()
    previous = json.loads((ROOT / "reports/d1_pair_validation.json").read_bytes())
    manifest = json.loads((SOURCE / "manifest.json").read_bytes())
    paths = {f"runs/full_k4/{name}": digest for name, digest in hashes.items()}
    paths["data/r1_pool.jsonl"] = manifest["pool_sha256"]
    paths.update({f"data/{name}": digest for name, digest in previous["sha256"].items()})
    paths["scripts/sample_m0.py"] = manifest["sampler_sha256"]
    paths["scripts/reward_v2.py"] = manifest["reward_sha256"]
    paths["scripts/reward.py"] = manifest["legacy_reward_sha256"]
    paths["scripts/frozen_generation/config.yaml"] = manifest["config_sha256"]
    for relative, expected in paths.items():
        assert sha(ROOT / relative) == expected, relative
    # Include the unchanged source files used by this CPU stage.
    for name in ("build_dpo_pairs.py", "check_dpo_pairs.py", "check_d2p_pairs.py", "build_groups.py", "dpo_config.json", "dpo_train.py"):
        relative = "scripts/" + name
        paths[relative] = sha(ROOT / relative)
    return paths


def stratum(group):
    if group["group"] == "excluded":
        assert group["correct"] in (0, 4)
        return f"excluded_correct_{group['correct']}"
    assert group["group"] in ("target", "retain")
    return group["group"]


def allocate(counts, total):
    population = sum(counts.values())
    result = {key: total * count // population for key, count in counts.items()}
    order = sorted(counts, key=lambda key: (-(total * counts[key] % population), key))
    for key in order[:total - sum(result.values())]:
        result[key] += 1
    assert sum(result.values()) == total and all(result[key] <= counts[key] for key in counts)
    return result


def load_inputs():
    verify_inputs()
    pool = read_rows(POOL)
    groups = {row["row"]: row for row in json.loads((SOURCE / "groups.json").read_bytes())["groups"]}
    assert len(pool) == len(groups) == 1500 and {row["row"] for row in pool} == groups.keys()
    by_row = defaultdict(list)
    for sample in read_raw(SOURCE / "raw.jsonl"):
        by_row[sample["row"]].append(sample)
    assert by_row.keys() == groups.keys()
    for item in pool:
        row = item["row"]
        samples = by_row[row]
        assert sorted(sample["repeat"] for sample in samples) == list(range(4))
        assert all(sample["seed"] == request_seed(seed_index(item), sample["repeat"])
                   and sample["prompt_tokens"] == item["prompt_tokens"] for sample in samples)
        assert groups[row] == {"row": row, **classify(samples)}
    return pool, groups, by_row


def split_rows(pool, groups):
    cells = defaultdict(list)
    for item in pool:
        cells[stratum(groups[item["row"]]), item["discipline"]].append(item)
    sizes = Counter(stratum(group) for group in groups.values())
    quotas = allocate(sizes, 300)
    rng = random.Random(SEED)
    chosen, table = set(), []
    for layer in sorted(sizes):
        counts = {domain: len(items) for (name, domain), items in cells.items() if name == layer}
        per_domain = allocate(counts, quotas[layer])
        for domain in sorted(counts):
            candidates = sorted(cells[layer, domain], key=lambda item: int(item["row"]))
            selected = rng.sample(candidates, per_domain[domain])
            chosen.update(item["row"] for item in selected)
            target = counts[domain] * 300 / 1500
            assert abs(len(selected) - target) <= 1, (layer, domain, len(selected), target)
            table.append({"stratum": layer, "discipline": domain, "pool": counts[domain],
                          "development": len(selected), "training": counts[domain] - len(selected),
                          "ideal_from_pool": target, "absolute_error": abs(len(selected) - target)})
    dev = [item for item in pool if item["row"] in chosen]
    train = [item for item in pool if item["row"] not in chosen]
    assert len(dev) == len(chosen) == 300 and len(train) == 1200
    return dev, train, table


def make_pairs(pool, groups, samples, dev_rows):
    examples, metadata = read_rows(d1.SWIFT), read_rows(d1.INDEX)
    assert len(examples) == len(metadata) == 707
    by_id = {item["row"]: item for item in pool}
    used = defaultdict(set)
    base, concise = [], []
    for data, ref in zip(examples, metadata, strict=True):
        if ref["row"] in dev_rows:
            continue
        item = by_id[ref["row"]]
        chosen = next(row for row in samples[item["row"]] if row["repeat"] == ref["chosen_repeat"])
        rejected = next(row for row in samples[item["row"]] if row["repeat"] == ref["rejected_repeat"])
        assert data["messages"][1]["content"] == chosen["raw_text"] and data["rejected_response"] == rejected["raw_text"]
        for response in (chosen, rejected):
            assert response["raw_text"] not in used[item["row"]], (item["row"], response["repeat"])
            used[item["row"]].add(response["raw_text"])
        base.append((data, {**ref, "kind": "base", "d1_pair": ref["pair"],
                            "chosen_output_tokens": chosen["output_tokens"], "rejected_output_tokens": rejected["output_tokens"]}))
    for item in pool:
        row = item["row"]
        if row in dev_rows:
            continue
        candidates = [sample for sample in samples[row] if sample["finish_reason"] == "stop" and sample["reward"] == 1
                      and sample["raw_text"] not in used[row]]
        if len(candidates) < 2:
            continue
        chosen = min(candidates, key=lambda sample: (sample["output_tokens"], sample["repeat"]))
        rejected = min(candidates, key=lambda sample: (-sample["output_tokens"], sample["repeat"]))
        if rejected["output_tokens"] < chosen["output_tokens"] * 2 or rejected["output_tokens"] < 2000:
            continue
        assert chosen["raw_text"] != rejected["raw_text"]
        original = example_for(item, None)
        data = {"messages": original["messages"] + [{"role": "assistant", "content": chosen["raw_text"]}],
                "images": original["images"], "rejected_response": rejected["raw_text"], "rejected_add_eos": None}
        ref = {"row": row, "kind": "concise", "group": groups[row]["group"], "discipline": item["discipline"],
               "chosen_repeat": chosen["repeat"], "rejected_repeat": rejected["repeat"], "rejected_reason": "long_correct",
               "chosen_output_tokens": chosen["output_tokens"], "rejected_output_tokens": rejected["output_tokens"]}
        concise.append((data, ref))
    merged = base + concise
    random.Random(SEED).shuffle(merged)
    return [data for data, _ in merged], [{**ref, "pair": ordinal} for ordinal, (_, ref) in enumerate(merged)]


def main():
    for path in (DEV, SPLIT, PAIRS, INDEX):
        if path.exists():
            raise FileExistsError(path)
    hashes = verify_inputs()
    pool, groups, samples = load_inputs()
    dev, train, table = split_rows(pool, groups)
    write_rows(DEV, dev)
    split = {"seed": SEED, "development_rows": [item["row"] for item in dev], "training_rows": [item["row"] for item in train],
             "cells": table, "input_sha256": hashes,
             "rule": "Two-stage largest remainder. Strata excluded_correct_0, excluded_correct_4, retain, target in lexical order; disciplines lexical; ties lexical. Row sorted numerically, then one Random(3407) sampled across cells. Outputs retain pool order."}
    write_json(SPLIT, split)
    data, index = make_pairs(pool, groups, samples, set(split["development_rows"]))
    write_rows(PAIRS, data)
    write_rows(INDEX, index)
    counts = Counter(row["kind"] for row in index)
    print("D3 split", len(dev), len(train), "pairs", dict(counts), "total", len(data), flush=True)
    print("COUNT_GATE", "STOP" if len(data) < 500 or counts["concise"] < 50 else "PASS", flush=True)


if __name__ == "__main__":
    main()
