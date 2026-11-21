"""Fixed MMMU test GPU assignment and completed-shard verification."""

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys

import yaml

GPU0 = """Agriculture Architecture_and_Engineering Art Art_Theory Basic_Medical_Science
Biology Clinical_Medicine Design Electronics Finance Geography Marketing Materials Music Public_Health""".split()


def load(path):
    return json.loads(path.read_bytes())


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def plan(config):
    dataset = yaml.safe_load(config.read_bytes())["dataset"]
    counts, subjects = dataset["expected_rows_by_subject"], dataset["subjects"]
    if dataset["split"] != "test" or sum(counts.values()) != 10500 or dataset["expected_total_rows"] != 10500:
        raise ValueError("Expected the fixed test dataset configuration")
    if set(counts) != set(subjects) or not set(GPU0) < set(subjects) or len(subjects) != 30:
        raise ValueError("Unexpected subject list")
    shards = [GPU0, [subject for subject in subjects if subject not in GPU0]]
    if [sum(counts[s] for s in group) for group in shards] != [5321, 5179]:
        raise ValueError("Unexpected GPU shard counts")
    return counts, subjects, shards


def merge(root, config):
    counts, subjects, shards = plan(config)
    config_sha = sha(config)
    expected_ids = [f"test_{subject}_{i}" for subject in subjects for i in range(1, counts[subject] + 1)]
    combined = root / "raw.jsonl"
    receipt = root / "merge_receipt.json"
    if combined.exists() or receipt.exists():
        raise FileExistsError("Combined output already exists")
    lines, settings, stats = {}, [], {}
    for gpu, shard in enumerate(shards):
        folder = root / f"gpu{gpu}"
        raw = folder / "raw.jsonl"
        env = load(folder / "env.json")
        meta = load(folder / "run_metadata.json")
        assert (folder / "worker.exit").read_text().strip() == "0"
        assert env["config_sha256"] == meta["code_and_reproduction"]["config"]["sha256"] == config_sha
        assert env["subjects"] == shard and env["limit"] is None and not env["dry_run"]
        assert len(env["invocations"]) == 1 and not env["engine_overrides"]
        settings.append({key: meta[key] for key in ("model", "generation", "prompt", "image_processing", "environment")})
        assert settings[-1]["environment"]["parallelism"]["tensor_parallel_size"] == 1
        assert settings[-1]["environment"]["env_vars"].pop("CUDA_VISIBLE_DEVICES") == str(gpu)
        digest = sha(raw)
        assert digest == meta["run"]["raw_file"]["sha256"]
        expected = {f"test_{subject}_{i}" for subject in shard for i in range(1, counts[subject] + 1)}
        seen, finishes, tokens, input_tokens = set(), Counter(), [], 0
        with raw.open("rb") as stream:
            for line in stream:
                assert line.endswith(b"\n")
                row = json.loads(line)
                qid = row["id"]
                assert qid in expected and qid not in lines and row["status"] == "ok" and not row["synthetic"]
                assert row["finish_reason"] in {"stop", "length"}
                assert row["precomputed_prompt_tokens"] == row["num_prompt_tokens"] > 0
                assert 0 < row["output_tokens"] == len(row["output_token_ids"]) <= row["max_new_tokens"] == 8192
                assert row["finish_reason"] != "length" or row["output_tokens"] == 8192
                seen.add(qid)
                lines[qid] = line
                finishes[row["finish_reason"]] += 1
                tokens.append(row["output_tokens"])
                input_tokens += row["num_prompt_tokens"]
        assert seen == expected and sum(tokens) == meta["run"]["token_stats"]["total"]
        with (folder / "physical_gpu_memory.csv").open(encoding="utf-8") as stream:
            samples = [int(row[2]) for row in csv.reader(stream) if len(row) == 4 and int(row[1]) == gpu]
        assert samples
        stats[f"gpu{gpu}"] = {"rows": len(seen), "raw_sha256": digest, "length": finishes["length"],
                             "output_tokens_total": sum(tokens), "output_tokens_mean": statistics.mean(tokens),
                             "output_tokens_median": statistics.median(tokens), "prompt_tokens_total": input_tokens,
                             "duration_seconds": meta["run"]["duration_seconds"], "max_vram_mib": max(samples)}
    assert settings[0] == settings[1], "Shard generation settings differ"
    assert set(lines) == set(expected_ids) and len(lines) == 10500
    with combined.open("xb") as stream:
        stream.writelines(lines[qid] for qid in expected_ids)
    result = {"status": "PASS", "rows": len(lines), "errors": 0, "subject_counts": counts,
              "config_sha256": config_sha, "raw_sha256": sha(combined), "gpu_shards": stats}
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--gpu", type=int, choices=(0, 1))
    modes.add_argument("--merge", type=Path)
    modes.add_argument("--smoke", type=Path)
    args = parser.parse_args()
    if args.merge:
        merge(args.merge, args.config)
    elif args.smoke:
        _, _, groups = plan(args.config)
        for gpu, group in enumerate(groups):
            folder = args.smoke / f"gpu{gpu}"
            assert (folder / "worker.exit").read_text().strip() == "0"
            rows = [json.loads(line) for line in (folder / "raw.jsonl").read_bytes().splitlines()]
            assert len(rows) == len({row["id"] for row in rows}) == 3
            for row in rows:
                assert row["subject"] in group and row["status"] == "ok" and not row["synthetic"]
                assert row["precomputed_prompt_tokens"] == row["num_prompt_tokens"] > 0
                assert row["output_tokens"] > 0 and row["finish_reason"] in {"stop", "length"}
        print("Smoke verified: 3 rows per GPU")
    else:
        counts, _, shards = plan(args.config)
        group = shards[args.gpu]
        print(",".join(group))
        print(sum(counts[subject] for subject in group))


if __name__ == "__main__":
    main()
