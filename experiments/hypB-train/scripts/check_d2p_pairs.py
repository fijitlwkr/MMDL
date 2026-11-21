"""D2' 쌍 독립 검증: D1과 같은 규칙으로 쌍을 다시 만들어 받은 파일과 대조하고, reward_v2 재계산·ms-swift 토큰 일치를 확인한다.
기존 build_dpo_pairs.py / check_dpo_pairs.py는 수정하지 않고, 입력 경로만 D2'로 바꿔 재사용한다."""
from collections import defaultdict
import json, random

import build_dpo_pairs as B
import check_dpo_pairs as C
from classify_answers import ROOT, read_rows
from sample_m0 import SEED, read_raw, request_seed, seed_index, sha

SOURCE = ROOT / "runs/d2p_k4"
INPUTS = ("raw.jsonl", "groups.json", "d2p_train.jsonl")


def verify_inputs():
    hashes = json.loads((SOURCE / "SHA256SUMS.json").read_bytes())
    for name in INPUTS:
        if sha(SOURCE / name) != hashes[name]:
            raise ValueError(f"D2' input SHA-256 mismatch: {name}")
    return {name: hashes[name] for name in INPUTS}


def build_pairs():  # build_dpo_pairs.build_pairs 와 같은 규칙, 입력만 D2'
    verify_inputs()
    train = read_rows(SOURCE / "d2p_train.jsonl")
    groups = {g["row"]: g for g in json.loads((SOURCE / "groups.json").read_bytes())["groups"]
              if g["group"] in {"target", "retain"}}
    assert len(groups) == len(train) and {i["row"] for i in train} == groups.keys()
    by_row = defaultdict(list)
    raw = read_raw(SOURCE / "raw.jsonl")
    assert len(raw) == 6000
    for s in raw:
        if s["row"] in groups:
            by_row[s["row"]].append(s)
    rng = random.Random(SEED)
    pairs = []
    for item in train:
        row = item["row"]
        samples = sorted(by_row[row], key=lambda s: s["repeat"])
        assert [s["repeat"] for s in samples] == list(range(4))
        assert all(s["seed"] == request_seed(seed_index(item), s["repeat"])
                   and s["prompt_tokens"] == item["prompt_tokens"] for s in samples)
        chosen = list(B.candidates(s for s in samples if s["reward"] == 1))
        rejected = list(B.candidates(s for s in samples if s["reward"] == 0))
        assert all(s["finish_reason"] == "stop" and s["reward_reason"] in {"correct", "fallback_correct"} for s in chosen)
        assert all((s["finish_reason"] == "length") == (s["reward_reason"] == "truncated") for s in rejected)
        assert chosen and rejected and not ({s["raw_text"] for s in chosen} & {s["raw_text"] for s in rejected})
        rng.shuffle(chosen)
        rng.shuffle(rejected)
        rejected.sort(key=lambda s: B.REJECT_ORDER[s["reward_reason"]])
        pairs.extend((item, groups[row]["group"], good, bad) for good, bad in zip(chosen[:2], rejected[:2]))
    return pairs


C.SOURCE = SOURCE
C.SWIFT = ROOT / "data/d2p_pairs_swift.jsonl"
C.INDEX = ROOT / "data/d2p_pairs_index.jsonl"
C.RESULT = ROOT / "reports/d2p_pair_validation.json"
C.verify_inputs = verify_inputs
C.build_pairs = build_pairs

if __name__ == "__main__":
    C.check()
