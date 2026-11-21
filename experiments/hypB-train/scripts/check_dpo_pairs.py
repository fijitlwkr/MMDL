"""Check D1 pair rewards, lengths, and CPU ms-swift DPO preprocessing."""

from collections import Counter, defaultdict
import importlib.metadata
import os
import statistics

from build_dpo_pairs import INDEX, SOURCE, SWIFT, ROOT, WORKSPACE, build_pairs, read_rows, verify_inputs
from classify_answers import write_json
from reward_v2 import reward
from sample_m0 import CONFIG, POOL, example_for, load_processor, prompt_input, sha


LIMIT = 12_288
PROCESSOR = POOL.parent / "final_v5/cache/qwen3_vl_4b_ebb281ec"
RESULT = ROOT / "reports/d1_pair_validation.json"
END = "<|im_end|>\n"


def stats(values):
    return {"mean": statistics.mean(values), "median": statistics.median(values), "max": max(values)}


def check():
    os.chdir(WORKSPACE)
    local_cache = ROOT / "data/d1_cpu_cache"
    local_cache.mkdir(exist_ok=True)
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1",
                      MODELSCOPE_OFFLINE="1", MODELSCOPE_CACHE=os.path.relpath(local_cache, WORKSPACE),
                      MIN_PIXELS="1003520", MAX_PIXELS="4014080", IMAGE_MIN_TOKEN_NUM="980",
                      IMAGE_MAX_TOKEN_NUM="3920", SPATIAL_MERGE_SIZE="2")
    import torch
    import yaml
    from swift.llm import get_model_tokenizer, get_template, load_dataset

    torch.set_num_threads(4)
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    processor = load_processor(PROCESSOR.resolve(strict=True), cfg)
    tokenizer = processor.tokenizer
    pairs, data, index = build_pairs(), read_rows(SWIFT), read_rows(INDEX)
    assert len(pairs) == len(data) == len(index)
    lengths = []
    by_group, by_discipline = defaultdict(Counter), defaultdict(Counter)
    for ordinal, ((item, group, chosen, rejected), example, ref) in enumerate(zip(pairs, data, index, strict=True)):
        original = example_for(item, None)
        assert example["messages"][0] == original["messages"][0] and example["images"] == original["images"]
        assert example["messages"][1] == {"role": "assistant", "content": chosen["raw_text"]}
        assert example["rejected_response"] == rejected["raw_text"]
        truncated = rejected["finish_reason"] == "length"
        assert example["rejected_add_eos"] is (False if truncated else None)
        assert (ref["pair"], ref["row"], ref["group"], ref["chosen_repeat"], ref["rejected_repeat"], ref["rejected_reason"]) == (
            ordinal, item["row"], group, chosen["repeat"], rejected["repeat"], rejected["reward_reason"])
        for sample in (chosen, rejected):
            assert reward(sample["raw_text"], sample["finish_reason"], item) == (sample["reward"], sample["reward_reason"])
        assert chosen["reward"] == 1 and rejected["reward"] == 0
        prompt = item["prompt_tokens"]
        chosen_tokens = len(tokenizer.encode(chosen["raw_text"] + END, add_special_tokens=False))
        rejected_tokens = len(tokenizer.encode(rejected["raw_text"] + ("" if truncated else END), add_special_tokens=False))
        category = "wrong" if rejected["reward_reason"] == "fallback_wrong" else rejected["reward_reason"]
        by_group[group][category] += 1
        by_discipline[item["discipline"]][group] += 1
        lengths.append({"pair": ordinal, "row": item["row"], "prompt": prompt, "chosen": chosen_tokens,
                        "rejected": rejected_tokens, "chosen_output": chosen["output_tokens"],
                        "rejected_output": rejected["output_tokens"], "category": category,
                        "longest": prompt + max(chosen_tokens, rejected_tokens)})
    longest = max(lengths, key=lambda row: row["longest"])
    counts = Counter(r["category"] for r in lengths)
    result = {"input_sha256": verify_inputs(), "pairs": len(pairs), "questions": len({r["row"] for r in lengths}),
              "pairs_per_question": Counter(Counter(r["row"] for r in lengths).values()),
              "by_group": by_group, "by_discipline": by_discipline, "rejected": counts,
              "lengths": {key: stats([r[key] for r in lengths]) for key in ("chosen", "rejected", "chosen_output", "rejected_output")},
              "longest": longest, "over_limit": [r for r in lengths if r["longest"] > LIMIT],
              "sha256": {p.name: sha(p) for p in (SWIFT, INDEX)}, "swift_checks": []}
    write_json(RESULT, result)
    print(f"INDEPENDENT_LENGTHS {longest}, over limit: {len(result['over_limit'])}", flush=True)
    if result["over_limit"]:
        raise SystemExit(f"D1 sequence exceeds {LIMIT}; stop before preparing training config")

    sample_rows = {longest["pair"]}
    for category in counts:
        sample_rows.update([r["pair"] for r in lengths if r["category"] == category][:2])
    loaded, _ = load_dataset(str(SWIFT), strict=True, use_hf=True, shuffle=False, remove_unused_columns=False)
    assert len(loaded) == len(pairs)
    model, swift_processor = get_model_tokenizer(str(PROCESSOR.resolve()), model_type="qwen3_vl", load_model=False, use_hf=True)
    assert model is None and importlib.metadata.version("ms-swift") == "3.12.3"
    template = get_template("qwen3_vl", swift_processor, max_length=LIMIT, truncation_strategy="raise", loss_scale="default")
    template.set_mode("rlhf")
    for ordinal in sorted(sample_rows):
        item, _, chosen, rejected = pairs[ordinal]
        expected = lengths[ordinal]
        loaded_row = loaded[ordinal]
        assert loaded_row["rejected_add_eos"] is data[ordinal]["rejected_add_eos"]
        assert loaded_row["rejected_response"] == data[ordinal]["rejected_response"]
        assert [(m["role"], m["content"]) for m in loaded_row["messages"]] == [
            (m["role"], m["content"]) for m in data[ordinal]["messages"]]
        prepared, prompt, _ = prompt_input(example_for(item, None), WORKSPACE, cfg, processor)
        for image in prepared["multi_modal_data"]["image"]:
            image.close()
        encoded = template.encode(loaded_row)
        observation = {**expected, "image_tokens": prompt.count(processor.image_token_id), "branches": {}}
        for branch, sample in (("chosen", chosen), ("rejected", rejected)):
            completion = tokenizer.encode(sample["raw_text"] + (END if sample["finish_reason"] == "stop" else ""),
                                          add_special_tokens=False)
            actual_ids = encoded[branch + "_input_ids"]
            labels = encoded[branch + "_labels"]
            observed = {"prompt": labels.count(-100), "completion": len(labels) - labels.count(-100),
                        "full_ids_match": actual_ids == prompt + completion,
                        "labels_match": labels == [-100] * len(prompt) + completion}
            observation["branches"][branch] = observed
            print("SWIFT", ordinal, item["row"], branch, observed, flush=True)
        result["swift_checks"].append(observation)
        write_json(RESULT, result)
    assert len(result["swift_checks"]) >= 5
    assert all(branch["prompt"] == row["prompt"] and branch["completion"] == row[name]
               and branch["full_ids_match"] and branch["labels_match"]
               for row in result["swift_checks"] for name, branch in row["branches"].items())
    print("D1 CPU CHECK PASS", flush=True)


if __name__ == "__main__":
    check()
