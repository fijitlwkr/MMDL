"""Build SD1 self-response SFT data: M0's own completed, correct responses on non-development questions."""

from collections import Counter
import json
import random
import statistics

from classify_answers import ROOT, read_rows, write_json, write_rows
from d3_prepare import DEV, SPLIT, load_inputs, verify_inputs
from sample_m0 import SEED, example_for, sha

TRAIN = ROOT / "data/sd1_train_swift.jsonl"
INDEX = ROOT / "data/sd1_train_index.jsonl"
REPORT = ROOT / "reports/sd1_data_validation.json"
CAP = 2
LIMIT = 10_240


def build(pool, groups, samples, dev_rows):
    rng = random.Random(SEED)
    rows = []
    for item in pool:
        row = item["row"]
        if row in dev_rows:
            continue
        distinct = {}
        for sample in sorted(samples[row], key=lambda sample: sample["repeat"]):
            if sample["finish_reason"] == "stop" and sample["reward"] == 1:
                distinct.setdefault(sample["raw_text"], sample)
        candidates = list(distinct.values())
        if len(candidates) > CAP:
            candidates = sorted(rng.sample(candidates, CAP), key=lambda sample: sample["repeat"])
        original = example_for(item, None)
        for sample in candidates:
            assert sample["prompt_tokens"] == item["prompt_tokens"]
            data = {"messages": original["messages"] + [{"role": "assistant", "content": sample["raw_text"]}],
                    "images": original["images"]}
            ref = {"row": row, "repeat": sample["repeat"], "group": groups[row]["group"], "correct_of_4": groups[row]["correct"],
                   "discipline": item["discipline"], "reward_reason": sample["reward_reason"],
                   "prompt_tokens": item["prompt_tokens"], "output_tokens": sample["output_tokens"],
                   "marker_count": sample["marker_count"]}
            rows.append((data, ref))
    random.Random(SEED).shuffle(rows)
    return [data for data, _ in rows], [{**ref, "example": number} for number, (_, ref) in enumerate(rows)]


def main():
    for path in (TRAIN, INDEX, REPORT):
        if path.exists():
            raise FileExistsError(path)
    inputs = verify_inputs()
    pool, groups, samples = load_inputs()
    split = json.loads(SPLIT.read_bytes())
    dev = {item["row"] for item in read_rows(DEV)}
    assert len(dev) == 300 and dev == set(split["development_rows"])
    data, refs = build(pool, groups, samples, dev)
    assert not any(ref["row"] in dev for ref in refs)
    assert len({(ref["row"], ref["repeat"]) for ref in refs}) == len(refs)
    totals = [ref["prompt_tokens"] + ref["output_tokens"] + 1 for ref in refs]
    outputs = [ref["output_tokens"] for ref in refs]
    if max(totals) > LIMIT:
        raise SystemExit("SD1 sequence exceeds 10,240; stop")
    write_rows(TRAIN, data)
    write_rows(INDEX, refs)
    per_item = Counter(Counter(ref["row"] for ref in refs).values())
    result = {"input_sha256": inputs, "cap_per_question": CAP, "examples": len(refs), "questions": len({ref["row"] for ref in refs}),
              "examples_per_question": dict(per_item), "by_group": dict(Counter(ref["group"] for ref in refs)),
              "by_correct_of_4": dict(Counter(str(ref["correct_of_4"]) for ref in refs)),
              "by_discipline": dict(Counter(ref["discipline"] for ref in refs)),
              "by_reward_reason": dict(Counter(ref["reward_reason"] for ref in refs)),
              "output_tokens": {"mean": statistics.mean(outputs), "median": statistics.median(outputs), "max": max(outputs)},
              "longest_total_tokens": max(totals), "marker_21_or_more": sum(ref["marker_count"] >= 21 for ref in refs),
              "steps_per_epoch": -(-len(refs) // 16),
              "sha256": {path.name: sha(path) for path in (TRAIN, INDEX)}}
    write_json(REPORT, result)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
