"""Rebuild D3 concise pairs while preserving its frozen development split."""

from collections import Counter
import json
import random

import build_dpo_pairs as d1
from classify_answers import ROOT, read_rows, write_rows
from d3_prepare import DEV, POOL, SPLIT, load_inputs, verify_inputs as verify_r1_inputs
from sample_m0 import SEED, example_for, sha


PAIRS = ROOT / "data/d3_pairs_v2_swift.jsonl"
INDEX = ROOT / "data/d3_pairs_v2_index.jsonl"


def verify_inputs():
    original = json.loads((ROOT / "reports/d3_artifacts_sha256.json").read_bytes())
    split = json.loads(SPLIT.read_bytes())
    assert verify_r1_inputs() == split["input_sha256"]
    expected = {**split["input_sha256"], **original}
    for name, digest in expected.items():
        assert sha(ROOT / name) == digest, name
    return expected


def make_pairs(pool, groups, samples, dev_rows):
    examples, refs = read_rows(d1.SWIFT), read_rows(d1.INDEX)
    base = []
    for data, ref in zip(examples, refs, strict=True):
        if ref["row"] in dev_rows:
            continue
        row_samples = {sample["repeat"]: sample for sample in samples[ref["row"]]}
        chosen, rejected = (row_samples[ref[key]] for key in ("chosen_repeat", "rejected_repeat"))
        base.append((data, {**ref, "kind": "base", "d1_pair": ref["pair"],
                            "chosen_output_tokens": chosen["output_tokens"], "rejected_output_tokens": rejected["output_tokens"]}))
    assert len(base) == 561
    concise = []
    for item in pool:
        row = item["row"]
        group = groups[row]
        if row in dev_rows or group["group"] != "excluded" or group["correct"] != 4:
            continue
        distinct = {}
        for sample in sorted(samples[row], key=lambda sample: sample["repeat"]):
            if sample["finish_reason"] == "stop" and sample["reward"] == 1:
                distinct.setdefault(sample["raw_text"], sample)
        candidates = list(distinct.values())
        chosen_candidates = [sample for sample in candidates if sample["output_tokens"] >= 200]
        if not chosen_candidates:
            continue
        chosen = min(chosen_candidates, key=lambda sample: (sample["output_tokens"], sample["repeat"]))
        rejected = min(candidates, key=lambda sample: (-sample["output_tokens"], sample["repeat"]))
        if rejected["output_tokens"] < chosen["output_tokens"] * 3 or rejected["output_tokens"] < 3000:
            continue
        assert chosen["raw_text"] != rejected["raw_text"]
        original = example_for(item, None)
        data = {"messages": original["messages"] + [{"role": "assistant", "content": chosen["raw_text"]}],
                "images": original["images"], "rejected_response": rejected["raw_text"], "rejected_add_eos": None}
        ref = {"row": row, "kind": "concise", "group": group["group"], "discipline": item["discipline"],
               "chosen_repeat": chosen["repeat"], "rejected_repeat": rejected["repeat"], "rejected_reason": "long_correct",
               "chosen_output_tokens": chosen["output_tokens"], "rejected_output_tokens": rejected["output_tokens"]}
        concise.append((data, ref))
    combined = base + concise
    random.Random(SEED).shuffle(combined)
    return [data for data, _ in combined], [{**ref, "pair": number} for number, (_, ref) in enumerate(combined)]


def main():
    for path in (PAIRS, INDEX):
        if path.exists():
            raise FileExistsError(path)
    verify_inputs()
    pool, groups, samples = load_inputs()
    split = json.loads(SPLIT.read_bytes())
    dev = {item["row"] for item in read_rows(DEV)}
    assert len(dev) == 300 and dev == set(split["development_rows"])
    assert set(split["training_rows"]) == {item["row"] for item in pool} - dev
    data, refs = make_pairs(pool, groups, samples, dev)
    write_rows(PAIRS, data)
    write_rows(INDEX, refs)
    counts = Counter(ref["kind"] for ref in refs)
    print("D3 v2 pairs", len(data), dict(counts), flush=True)
    print("COUNT_GATE", "STOP" if len(data) < 500 or counts["concise"] < 40 else "PASS", flush=True)
    verify_inputs()


if __name__ == "__main__":
    main()
