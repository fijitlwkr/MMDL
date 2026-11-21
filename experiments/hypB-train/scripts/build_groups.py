"""Classify a complete M0 sampling run and optionally compose a draft mix."""
import argparse
from collections import Counter, defaultdict
import math
import random
from pathlib import Path

from classify_answers import ROOT, read_rows
from sample_m0 import SEED, evaluate, read_raw, request_seed, seed_index, sha


def classify(samples):
    correct = sum(r["reward"] for r in samples)
    length = sum(r["finish_reason"] == "length" for r in samples)
    turns = sum(r["marker_count"] >= 21 for r in samples)
    target_condition = bool(correct and (length or turns))
    if correct in (0, len(samples)):
        group = "excluded"
    else:
        group = "target" if target_condition else "retain"
    return {"group": group, "correct": correct, "length": length, "direction_overuse": turns,
            "target_condition": target_condition, "constant_reward_overlap": group == "excluded" and target_condition}


def compose(groups, target_ratio, retain_ratio):
    if min(target_ratio, retain_ratio) < 1:
        raise ValueError("Ratio components must be positive")
    divisor = math.gcd(target_ratio, retain_ratio)
    target_ratio, retain_ratio = target_ratio // divisor, retain_ratio // divisor
    target = [r for r in groups if r["group"] == "target"]
    retain = [r for r in groups if r["group"] == "retain"]
    units = min(len(target) // target_ratio, len(retain) // retain_ratio)
    rng = random.Random(SEED)
    selection = rng.sample(target, units * target_ratio) + rng.sample(retain, units * retain_ratio)
    rng.shuffle(selection)
    return [r["row"] for r in selection]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pool-jsonl", type=Path, default=ROOT / "data/r1_pool.jsonl")
    parser.add_argument("--ratio", nargs=2, type=int, metavar=("TARGET", "RETAIN"),
                        help="Explicit draft composition, for example --ratio 7 3")
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(ROOT.resolve() / "data"):
        parser.error("--out must be inside R1 data/")
    manifest = evaluate.read_json(args.run / "manifest.json")
    if out in {(args.run / name).resolve() for name in ("manifest.json", "raw.jsonl")}:
        parser.error("--out must be separate from raw and manifest")
    combined = "pool_sha256" in manifest
    types = args.pool_jsonl if combined else ROOT / "data/answer_types.jsonl"
    hash_key = "pool_sha256" if combined else "answer_types_sha256"
    protected = {types.resolve(), (ROOT / "data/answer_types.jsonl").resolve(),
                 (ROOT / "data/r1_pool.jsonl").resolve(), (ROOT / "data/trial_100.jsonl").resolve()}
    if out in protected or sha(types) != manifest[hash_key]:
        parser.error("Answer type snapshot mismatch or output collision")
    eligible = {str(r["row"]): seed_index(r) for r in read_rows(types)
                if combined or (r["role"] == "train" and r["format"] != "excluded")}
    if not set(manifest["rows"]) <= eligible.keys():
        raise ValueError("Run contains rows outside the eligible train pool")
    k = manifest["k"]
    expected = {(row, repeat) for row in manifest["rows"] for repeat in range(k)}
    by_row = defaultdict(list)
    seen = set()
    for record in read_raw(args.run / "raw.jsonl"):
        row, repeat = record["row"], record["repeat"]
        pair = row, repeat
        if pair not in expected or pair in seen or record["seed"] != request_seed(eligible[row], repeat):
            raise ValueError(f"Unexpected or duplicate sample {pair}")
        finish = record["finish_reason"]
        if (record["reward"] not in (0, 1) or finish not in ("stop", "length")
                or (finish == "length" and record["reward"]) or record["marker_count"] < 0):
            raise ValueError(f"Invalid sample reward or termination: {pair}")
        seen.add(pair)
        by_row[row].append(record)
    if seen != expected:
        raise ValueError(f"Incomplete sampling run: {len(seen)}/{len(expected)}")
    groups = [{"row": row, **classify(by_row[row])} for row in manifest["rows"]]
    counts = Counter(r["group"] for r in groups)
    result = {"k": k, "seed": SEED, "counts": counts, "groups": groups,
              "target_below_300": counts["target"] < 300}
    if args.ratio is not None:
        result["ratio"] = args.ratio
        result["selection"] = compose(groups, *args.ratio)
    out.parent.mkdir(parents=True, exist_ok=True)
    evaluate.write_json(out, result)
    print(dict(counts))


if __name__ == "__main__":
    main()
