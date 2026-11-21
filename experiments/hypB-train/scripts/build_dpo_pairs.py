"""Build D1 preference pairs from the SHA-verified full K=4 run."""

from collections import Counter, defaultdict
import json
import random

from classify_answers import ROOT, WORKSPACE, read_rows, write_rows
from sample_m0 import SEED, example_for, read_raw, request_seed, seed_index, sha


SOURCE = ROOT / "runs/full_k4"
SWIFT = ROOT / "data/d1_pairs_swift.jsonl"
INDEX = ROOT / "data/d1_pairs_index.jsonl"
INPUTS = ("raw.jsonl", "groups.json", "r1_train.jsonl")
REJECT_ORDER = {"truncated": 0, "wrong": 1, "fallback_wrong": 1, "extract_fail": 2}


def verify_inputs():
    hashes = json.loads((SOURCE / "SHA256SUMS.json").read_bytes())
    for name in INPUTS:
        if sha(SOURCE / name) != hashes[name]:
            raise ValueError(f"Stage 3 input SHA-256 mismatch: {name}")
    return {name: hashes[name] for name in INPUTS}


def candidates(samples):
    seen = set()
    for sample in samples:
        text = sample["raw_text"]
        if text not in seen:
            seen.add(text)
            yield sample


def build_pairs():
    verify_inputs()
    train = read_rows(SOURCE / "r1_train.jsonl")
    groups = {group["row"]: group for group in json.loads((SOURCE / "groups.json").read_bytes())["groups"]
              if group["group"] in {"target", "retain"}}
    assert len(groups) == len(train) == 548 and {item["row"] for item in train} == groups.keys()
    by_row = defaultdict(list)
    raw = read_raw(SOURCE / "raw.jsonl")
    assert len(raw) == 6000
    for sample in raw:
        if sample["row"] in groups:
            by_row[sample["row"]].append(sample)
    rng = random.Random(SEED)
    pairs = []
    for item in train:
        row = item["row"]
        samples = sorted(by_row[row], key=lambda sample: sample["repeat"])
        assert [sample["repeat"] for sample in samples] == list(range(4))
        assert all(sample["seed"] == request_seed(seed_index(item), sample["repeat"])
                   and sample["prompt_tokens"] == item["prompt_tokens"] for sample in samples)
        chosen = list(candidates(sample for sample in samples if sample["reward"] == 1))
        rejected = list(candidates(sample for sample in samples if sample["reward"] == 0))
        assert all(s["finish_reason"] == "stop" and s["reward_reason"] in {"correct", "fallback_correct"} for s in chosen)
        assert all((s["finish_reason"] == "length") == (s["reward_reason"] == "truncated") for s in rejected)
        assert chosen and rejected and not ({s["raw_text"] for s in chosen} & {s["raw_text"] for s in rejected})
        rng.shuffle(chosen)
        rng.shuffle(rejected)
        rejected.sort(key=lambda sample: REJECT_ORDER[sample["reward_reason"]])
        pairs.extend((item, groups[row]["group"], good, bad) for good, bad in zip(chosen[:2], rejected[:2]))
    return pairs


def main():
    pairs = build_pairs()
    data, index = [], []
    verified_images = set()
    for ordinal, (item, group, chosen, rejected) in enumerate(pairs):
        example = example_for(item, None)
        for image in item["images"]:
            relative = image["path"]
            if relative not in verified_images:
                path = (WORKSPACE / relative).resolve(strict=True)
                assert path.is_relative_to(WORKSPACE) and path.stat().st_size == image["bytes"]
                assert sha(path) == image["sha256"], relative
                verified_images.add(relative)
        data.append({"messages": example["messages"] + [{"role": "assistant", "content": chosen["raw_text"]}],
                     "images": example["images"], "rejected_response": rejected["raw_text"],
                     "rejected_add_eos": False if rejected["finish_reason"] == "length" else None})
        index.append({"pair": ordinal, "row": item["row"], "group": group, "discipline": item["discipline"],
                      "chosen_repeat": chosen["repeat"], "rejected_repeat": rejected["repeat"],
                      "rejected_reason": rejected["reward_reason"]})
    for path in (SWIFT, INDEX):
        if path.exists():
            raise FileExistsError(path)
    write_rows(SWIFT, data)
    write_rows(INDEX, index)
    print(f"{len(pairs)} pairs, {len(verified_images)} verified images, {Counter(r['rejected_reason'] for r in index)}")


if __name__ == "__main__":
    main()
