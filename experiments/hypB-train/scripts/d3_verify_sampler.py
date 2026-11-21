"""Check the dev dry-run seed namespace against the original 6,000 samples."""

import json

from classify_answers import ROOT, read_rows, write_json
from d3_prepare import DEV, SOURCE, SPLIT
from sample_m0 import read_raw, request_seed, seed_index, sha


def main():
    path = ROOT / "reports/d3_dev_dry_run.json"
    result = json.loads(path.read_bytes())
    dev = read_rows(DEV)
    split = json.loads(SPLIT.read_bytes())
    assert len(dev) == 300 and {item["row"] for item in dev} == set(split["development_rows"])
    old = read_raw(SOURCE / "raw.jsonl")
    old_seeds = {sample["seed"] for sample in old}
    new_seeds = {request_seed(seed_index(item), repeat) for item in dev for repeat in range(4, 8)}
    assert len(old_seeds) == len(old) == 6000 and len(new_seeds) == 1200
    assert not new_seeds & old_seeds
    references = {sample["row"]: sample for sample in old}
    assert len(result["rows"]) >= 5 and not result["model_loaded"]
    for evidence, item in zip(result["rows"], dev, strict=False):
        row = item["row"]
        assert evidence["row"] == row and evidence["prompt_tokens"] == item["prompt_tokens"] == references[row]["prompt_tokens"]
        assert evidence["request_seeds"] == [request_seed(seed_index(item), repeat) for repeat in range(4, 8)]
    assert result["questions_sha256"] == sha(DEV)
    result["seed_validation"] = {"original_seeds": len(old_seeds), "new_seeds": len(new_seeds),
                                  "overlap_original": 0, "overlap_other_dev_questions": 0, "repeats": [4, 5, 6, 7]}
    write_json(path, result)
    print("D3 dev seed check PASS: 1,200 new seeds, no overlap with 6,000 R1 seeds")


if __name__ == "__main__":
    main()
