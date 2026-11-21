"""Validate D3 v2 separation, response ownership, rewards, and DPO tokenization."""

from collections import Counter, defaultdict
import importlib.metadata
import json
import math
import os
import statistics

import check_dpo_pairs as d1
from classify_answers import ROOT, WORKSPACE, read_rows, write_json
from d3_prepare import DEV, POOL, SOURCE, SPLIT, load_inputs, stratum
from d3_prepare_v2 import INDEX, PAIRS, verify_inputs
from reward_v2 import reward
from sample_m0 import CONFIG, example_for, load_processor, prompt_input, sha


RESULT = ROOT / "reports/d3_pair_v2_validation.json"
LIMIT = 10240


def main():
    os.chdir(WORKSPACE)
    cache = ROOT / "data/d3_cpu_cache_v2"
    cache.mkdir(exist_ok=True)
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1",
                      MODELSCOPE_OFFLINE="1", MODELSCOPE_CACHE=os.path.relpath(cache, WORKSPACE),
                      MIN_PIXELS="1003520", MAX_PIXELS="4014080", IMAGE_MIN_TOKEN_NUM="980",
                      IMAGE_MAX_TOKEN_NUM="3920", SPATIAL_MERGE_SIZE="2")
    import torch
    import yaml
    from swift.llm import get_model_tokenizer, get_template, load_dataset

    torch.set_num_threads(4)
    before = verify_inputs()
    pool, groups, samples = load_inputs()
    by_row = {item["row"]: item for item in pool}
    raw_by_pair = {(row, sample["repeat"]): sample for row, values in samples.items() for sample in values}
    split = json.loads(SPLIT.read_bytes())
    dev = set(split["development_rows"])
    train = set(split["training_rows"])
    assert len(dev) == 300 and len(train) == 1200 and not dev & train and dev | train == by_row.keys()
    assert read_rows(DEV) == [item for item in pool if item["row"] in dev]
    pool_lines = {json.loads(line)["row"]: line for line in POOL.read_bytes().splitlines()}
    assert all(pool_lines[json.loads(line)["row"]] == line for line in DEV.read_bytes().splitlines())
    for cell in split["cells"]:
        keys = {row for row, item in by_row.items() if stratum(groups[row]) == cell["stratum"] and item["discipline"] == cell["discipline"]}
        assert cell["pool"] == len(keys) and cell["development"] == len(keys & dev)
        assert cell["absolute_error"] == abs(len(keys & dev) - len(keys) / 5) <= 1
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    processor = load_processor(d1.PROCESSOR.resolve(strict=True), cfg)
    tokenizer = processor.tokenizer
    data, index = read_rows(PAIRS), read_rows(INDEX)
    old_data, old_index = read_rows(d1.SWIFT), read_rows(d1.INDEX)
    old_lines = d1.SWIFT.read_bytes().splitlines()
    new_lines = PAIRS.read_bytes().splitlines()
    expected_base = {ref["pair"] for ref in old_index if ref["row"] not in dev}
    base_found, used, images, lengths = set(), defaultdict(set), set(), []
    by_kind_group_domain, reasons = Counter(), Counter()
    for ordinal, (example, ref) in enumerate(zip(data, index, strict=True)):
        row = ref["row"]
        item = by_row[row]
        assert ref["pair"] == ordinal and row in train and row not in dev
        assert ref["group"] == groups[row]["group"] and ref["discipline"] == item["discipline"]
        chosen = raw_by_pair[row, ref["chosen_repeat"]]
        rejected = raw_by_pair[row, ref["rejected_repeat"]]
        assert chosen["finish_reason"] == "stop" and chosen["reward"] == 1
        for response in (chosen, rejected):
            assert response["raw_text"] not in used[row], (row, response["repeat"])
            used[row].add(response["raw_text"])
            assert reward(response["raw_text"], response["finish_reason"], item) == (response["reward"], response["reward_reason"])
        original = example_for(item, None)
        assert example["messages"] == original["messages"] + [{"role": "assistant", "content": chosen["raw_text"]}]
        assert example["images"] == original["images"] and example["rejected_response"] == rejected["raw_text"]
        assert example["rejected_add_eos"] is (False if rejected["finish_reason"] == "length" else None)
        assert ref["chosen_output_tokens"] == chosen["output_tokens"] and ref["rejected_output_tokens"] == rejected["output_tokens"]
        if ref["kind"] == "base":
            number = ref["d1_pair"]
            assert number not in base_found and example == old_data[number] and new_lines[ordinal] == old_lines[number]
            assert all(ref[key] == old_index[number][key] for key in ("row", "group", "discipline", "chosen_repeat", "rejected_repeat", "rejected_reason"))
            assert rejected["reward"] == 0
            base_found.add(number)
        else:
            assert ref["kind"] == "concise" and rejected["finish_reason"] == "stop" and rejected["reward"] == 1
            assert groups[row]["group"] == "excluded" and groups[row]["correct"] == 4
            assert chosen["output_tokens"] >= 200
            assert rejected["output_tokens"] >= 3 * chosen["output_tokens"] and rejected["output_tokens"] >= 3000
            distinct = {}
            for sample in sorted(samples[row], key=lambda sample: sample["repeat"]):
                if sample["finish_reason"] == "stop" and sample["reward"] == 1:
                    distinct.setdefault(sample["raw_text"], sample)
            eligible = [sample for sample in distinct.values() if sample["output_tokens"] >= 200]
            expected_chosen = min(eligible, key=lambda sample: (sample["output_tokens"], sample["repeat"]))
            expected_rejected = min(distinct.values(), key=lambda sample: (-sample["output_tokens"], sample["repeat"]))
            assert (chosen["repeat"], rejected["repeat"]) == (expected_chosen["repeat"], expected_rejected["repeat"])
            assert ref["rejected_reason"] == "long_correct"
        for image in item["images"]:
            if image["path"] in images:
                continue
            path = (WORKSPACE / image["path"]).resolve(strict=True)
            assert path.is_relative_to(WORKSPACE) and path.stat().st_size == image["bytes"]
            assert sha(path) == image["sha256"]
            images.add(image["path"])
        chosen_length = len(tokenizer.encode(chosen["raw_text"] + d1.END, add_special_tokens=False))
        rejected_length = len(tokenizer.encode(rejected["raw_text"] + (d1.END if rejected["finish_reason"] == "stop" else ""), add_special_tokens=False))
        category = "wrong" if ref["rejected_reason"] == "fallback_wrong" else ref["rejected_reason"]
        lengths.append({"pair": ordinal, "row": row, "kind": ref["kind"], "category": category,
                        "prompt": item["prompt_tokens"], "chosen": chosen_length, "rejected": rejected_length,
                        "chosen_output": chosen["output_tokens"], "rejected_output": rejected["output_tokens"],
                        "longest": item["prompt_tokens"] + max(chosen_length, rejected_length)})
        by_kind_group_domain[ref["kind"], ref["group"], item["discipline"]] += 1
        reasons[category] += 1
    assert base_found == expected_base
    old_d3_data = read_rows(ROOT / "data/d3_pairs_swift.jsonl")
    old_d3_index = read_rows(ROOT / "data/d3_pairs_index.jsonl")
    prior_base = {ref["d1_pair"]: example for example, ref in zip(old_d3_data, old_d3_index, strict=True) if ref["kind"] == "base"}
    assert set(prior_base) == base_found and all(prior_base[ref["d1_pair"]] == example
        for example, ref in zip(data, index, strict=True) if ref["kind"] == "base")
    concise_ratios = [row["rejected_output"] / row["chosen_output"] for row in lengths if row["kind"] == "concise"]
    result = {"status": "independent_checks_complete", "input_sha256": before,
              "pairs": len(data), "questions": len({ref["row"] for ref in index}), "images_verified": len(images),
              "by_kind": Counter(ref["kind"] for ref in index), "rejected": reasons,
              "by_kind_group_discipline": [{"kind": key[0], "group": key[1], "discipline": key[2], "pairs": count}
                                            for key, count in sorted(by_kind_group_domain.items())],
              "pairs_per_question": Counter(Counter(ref["row"] for ref in index).values()),
              "lengths": {key: d1.stats([row[key] for row in lengths]) for key in ("chosen", "rejected", "chosen_output", "rejected_output")},
              "concise_ratio": {"min": min(concise_ratios), **d1.stats(concise_ratios), "quartiles": statistics.quantiles(concise_ratios, n=4)},
              "longest": max(lengths, key=lambda row: row["longest"]), "over_limit": [row for row in lengths if row["longest"] > LIMIT],
              "steps_per_epoch": math.ceil(len(data) / 16), "steps_two_epochs": math.ceil(len(data) / 16) * 2,
              "concise_rejected_direction_overuse": sum(
                  raw_by_pair[ref["row"], ref["rejected_repeat"]]["marker_count"] >= 21 for ref in index if ref["kind"] == "concise"),
              "base_long_correct_vs_short_wrong": sum(
                  ref["kind"] == "base" and ref["rejected_reason"] in ("wrong", "fallback_wrong")
                  and ref["chosen_output_tokens"] >= 2000
                  and ref["chosen_output_tokens"] >= 2 * ref["rejected_output_tokens"] for ref in index),
              "previous_base_pairs_same": True, "swift_checks": []}
    write_json(RESULT, result)
    print("D3 v2 independent", result["pairs"], result["by_kind"], result["longest"], flush=True)
    if len(data) < 500 or result["by_kind"]["concise"] < 40 or result["over_limit"]:
        result["status"] = "STOP"
        write_json(RESULT, result)
        raise SystemExit("D3 stopping threshold reached")

    selected = {result["longest"]["pair"]}
    selected.update([row["pair"] for row in lengths if row["kind"] == "concise"][:2])
    for category in ("wrong", "truncated", "extract_fail"):
        selected.add(next(row["pair"] for row in lengths if row["kind"] == "base" and row["category"] == category))
    for ordinal in range(len(data)):
        if len(selected) >= 7:
            break
        selected.add(ordinal)
    loaded, _ = load_dataset(str(PAIRS), strict=True, use_hf=True, shuffle=False, remove_unused_columns=False)
    assert len(loaded) == len(data)
    model, swift_processor = get_model_tokenizer(str(d1.PROCESSOR.resolve()), model_type="qwen3_vl", load_model=False, use_hf=True)
    assert model is None and importlib.metadata.version("ms-swift") == "3.12.3"
    template = get_template("qwen3_vl", swift_processor, max_length=LIMIT, truncation_strategy="raise", loss_scale="default")
    template.set_mode("rlhf")
    for ordinal in sorted(selected):
        ref = index[ordinal]
        item = by_row[ref["row"]]
        prepared, prompt, _ = prompt_input(example_for(item, None), WORKSPACE, cfg, processor)
        for image in prepared["multi_modal_data"]["image"]:
            image.close()
        assert len(prompt) == item["prompt_tokens"]
        actual = template.encode(loaded[ordinal])
        observation = {**lengths[ordinal], "image_tokens": prompt.count(processor.image_token_id), "branches": {}}
        for branch in ("chosen", "rejected"):
            raw = raw_by_pair[item["row"], ref[branch + "_repeat"]]
            completion = tokenizer.encode(raw["raw_text"] + (d1.END if raw["finish_reason"] == "stop" else ""), add_special_tokens=False)
            ids, labels = actual[branch + "_input_ids"], actual[branch + "_labels"]
            assert ids == prompt + completion and labels == [-100] * len(prompt) + completion
            observation["branches"][branch] = {"prompt": len(prompt), "completion": len(completion), "ids_match": True, "labels_match": True}
        result["swift_checks"].append(observation)
        write_json(RESULT, result)
        print("D3_V2_SWIFT", ordinal, item["row"], observation["kind"], observation["category"], "PASS", flush=True)
    assert len(result["swift_checks"]) >= 7
    assert verify_inputs() == before
    result["status"] = "PASS"
    write_json(RESULT, result)


if __name__ == "__main__":
    main()
