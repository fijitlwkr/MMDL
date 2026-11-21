"""Apply the fixed AB1 development gate using the C1 scoring helpers."""

import argparse
from collections import Counter
import json
from pathlib import Path

from c1_select import DEV, SPLIT, SOURCE, STRATUM, read_rows, run_reward, sha, stratum, validate_raw


def decide(correct, protected):
    return {"overall_pass": correct > 882, "protected_pass": protected >= 582,
            "passed": correct > 882 and protected >= 582}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for name in ("m0", "d3", "ab1", "out"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args()
    if args.self_test:
        cases = [(883, 582, True), (882, 600, False), (900, 581, False), (860, 600, False)]
        for correct, protected, expected in cases:
            assert decide(correct, protected)["passed"] == expected
        result = {"status": "PASS", "synthetic_only": True, "cases": cases}
    else:
        items = {row["row"]: row for row in read_rows(DEV)}
        assert len(items) == 300 and set(items) == set(json.loads(SPLIT.read_bytes())["development_rows"])
        groups = {row["row"]: row for row in json.loads((SOURCE / "groups.json").read_bytes())["groups"]}
        layers = {row: stratum(groups[row]) for row in items}
        assert sum(value == STRATUM for value in layers.values()) == 158
        score, identity = run_reward(True)
        expected_hashes = {
            "M0": "0d23d51016620d84e56fe834400339fc8dd7e7232f959b1dd4d15a8f77250cd2",
            "D3-e1": "65e0ec75dda1b42fcd2964e2f0c203cb8bded43a3ad3bb30ca81c3a56f10aeb8",
        }
        measurements, raw_hashes, common, reference = {}, {}, None, {}
        for name, path in (("M0", args.m0), ("D3-e1", args.d3), ("AB1", args.ab1)):
            raw_hashes[name] = sha(path)
            if name in expected_hashes:
                assert raw_hashes[name] == expected_hashes[name], name
            manifest = json.loads((path.parent / "manifest.json").read_bytes())
            assert manifest["k"] == 4 and manifest["repeat_start"] == 4
            assert manifest["questions_sha256"] == sha(DEV)
            assert manifest["reward_sha256"] == identity["reward_sha256"]
            frozen = {k: v for k, v in manifest.items() if k != "model_path"}
            if common is None:
                common = frozen
            assert common == frozen, (name, "generation conditions differ")
            result = validate_raw(path, items, layers, score)
            rows = read_rows(path)
            pairs = {(r["row"], r["repeat"]): r for r in rows}
            for baseline, old in reference.items():
                assert set(pairs) == set(old)
                for pair, row in pairs.items():
                    assert (row["seed"], row["prompt_tokens"]) == (old[pair]["seed"], old[pair]["prompt_tokens"])
                result[f"versus_{baseline}"] = {
                    "gained": sum(not old[p]["reward"] and pairs[p]["reward"] for p in pairs),
                    "lost": sum(old[p]["reward"] and not pairs[p]["reward"] for p in pairs),
                }
            if name != "AB1":
                reference[name] = pairs
            counts = Counter({row: 0 for row in items})
            for row in rows:
                counts[row["row"]] += row["reward"]
            result["questions_by_correct_count"] = dict(Counter(counts.values()))
            result["length_count"] = sum(row["finish_reason"] == "length" for row in rows)
            result["direction_overuse_count"] = sum(row["marker_count"] >= 21 for row in rows)
            measurements[name] = result
        assert [measurements[n]["correct"] for n in ("M0", "D3-e1")] == [861, 882]
        ab1 = measurements["AB1"]
        result = {"measurements": measurements, "decision": decide(ab1["correct"], ab1["by_stratum"][STRATUM]["correct"]),
                  "raw_sha256": raw_hashes, "reward": identity, "seed_and_prompt_tokens_equal": True}
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
