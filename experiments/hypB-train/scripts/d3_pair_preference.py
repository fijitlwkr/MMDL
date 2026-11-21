"""Score fixed DPO pairs against M0; CPU self-tests never load model weights."""

import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import statistics


def category(ref):
    reason = ref["rejected_reason"]
    return "wrong" if reason == "fallback_wrong" else reason


def preference(ref, m0_chosen, m0_rejected, candidate_chosen, candidate_rejected):
    values = (m0_chosen, m0_rejected, candidate_chosen, candidate_rejected)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Non-finite response log probability")
    delta = (candidate_chosen - m0_chosen) - (candidate_rejected - m0_rejected)
    return {"pair": ref["pair"], "row": ref["row"], "rejected_reason": ref["rejected_reason"],
            "category": category(ref), "m0_chosen_logp": m0_chosen, "m0_rejected_logp": m0_rejected,
            "candidate_chosen_logp": candidate_chosen, "candidate_rejected_logp": candidate_rejected,
            "delta": delta, "preferred": delta > 0}


def summarize(rows):
    if not rows:
        raise ValueError("No complete pair scores")
    def stats(values):
        deltas = [row["delta"] for row in values]
        assert all(math.isfinite(value) for value in deltas)
        return {"pairs": len(values), "positive": sum(value > 0 for value in deltas),
                "zero": sum(value == 0 for value in deltas), "preference_accuracy": sum(value > 0 for value in deltas) / len(values),
                "delta_mean": statistics.mean(deltas), "delta_median": statistics.median(deltas)}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["category"]].append(row)
    return {**stats(rows), "by_rejected_category": {key: stats(values) for key, values in sorted(grouped.items())},
            "definition": "delta=(candidate_chosen-M0_chosen)-(candidate_rejected-M0_rejected); accuracy=mean(delta>0)",
            "logp_reduction": "sum over response labels, no length normalization, no beta scaling",
            "used_for_checkpoint_selection": False}


def response_logps(logits, labels):
    """Causal next-token logp sums with the DPO response-only label mask."""
    import torch
    assert logits.shape[:2] == labels.shape and labels.ndim == 2
    totals, counts = [], []
    for batch in range(labels.shape[0]):
        positions = torch.nonzero(labels[batch, 1:] != -100, as_tuple=True)[0]
        if positions.numel() == 0:
            raise ValueError("Empty response mask")
        total = torch.zeros((), device=logits.device, dtype=torch.float64)
        for chunk in positions.split(128):
            values = logits[batch, chunk].float()
            target = labels[batch, chunk + 1]
            token_logps = values.gather(1, target[:, None]).squeeze(1) - torch.logsumexp(values, dim=-1)
            total += token_logps.double().sum()
        totals.append(total.item())
        counts.append(positions.numel())
    return totals, counts


def make_template(processor):
    from swift.llm import get_template
    template = get_template("qwen3_vl", processor, max_length=10240,
                            truncation_strategy="raise", loss_scale="default")
    template.set_mode("rlhf")
    return template


def encode_pair(template, example):
    encoded = template.encode(example)
    for branch in ("chosen", "rejected"):
        ids, labels = encoded[branch + "_input_ids"], encoded[branch + "_labels"]
        assert len(ids) == len(labels) <= 10240
        start = next(n for n, label in enumerate(labels) if label != -100)
        assert start > 0 and labels == [-100] * start + ids[start:]
    return encoded


def self_test():
    import torch
    records = []
    for number, (reason, delta) in enumerate((("wrong", 2), ("truncated", -1), ("extract_fail", 0), ("long_correct", 3))):
        ref = {"pair": number, "row": str(number), "rejected_reason": reason}
        records.append(preference(ref, -10, -20, -10 + delta, -20))
    summary = summarize(records)
    assert summary["preference_accuracy"] == 0.5 and summary["delta_mean"] == summary["delta_median"] == 1
    assert summary["zero"] == 1 and summary["by_rejected_category"]["truncated"]["delta_mean"] == -1
    assert category({"rejected_reason": "fallback_wrong"}) == "wrong"
    m0 = [preference({"pair": 0, "row": "0", "rejected_reason": "wrong"}, -10, -20, -10, -20)]
    assert summarize(m0)["preference_accuracy"] == 0 and m0[0]["delta"] == 0
    logits = torch.tensor([[[1., 0., 2.], [0., 2., 1.], [3., 1., 0.], [2., 0., 1.], [0., 0., 0.]],
                           [[0., 1., 2.], [1., 3., 0.], [0., 0., 0.], [0., 0., 0.], [0., 0., 0.]]])
    labels = torch.tensor([[-100, -100, 1, 2, -100], [-100, 0, 2, -100, -100]])
    values, counts = response_logps(logits, labels)
    expected = []
    for b in range(2):
        terms = []
        for t in range(1, 5):
            if labels[b, t] != -100:
                numbers = logits[b, t - 1].tolist()
                terms.append(numbers[labels[b, t].item()] - math.log(sum(math.exp(v) for v in numbers)))
        expected.append(sum(terms))
    assert counts == [2, 2] and all(abs(a - b) < 1e-6 for a, b in zip(values, expected))
    for position in ((0, 0), (0, 3), (0, 4), (1, 2), (1, 3), (1, 4)):
        logits[position] = torch.tensor([999., -999., 500.])
    assert response_logps(logits, labels) == (values, counts)
    try:
        preference({"pair": 0, "row": "0", "rejected_reason": "wrong"}, float("nan"), -20, -10, -20)
    except ValueError:
        pass
    else:
        raise AssertionError("Non-finite input was accepted")
    return {"status": "PASS", "synthetic": True, "model_loaded": False, "checks": [
            "four_logps_and_delta", "strict_positive_and_zero_tie", "overall_mean_and_median", "rejected_categories",
            "M0_identity_zero", "causal_shift_and_first_response_token", "prompt_and_padding_mask", "non_finite_rejected"],
            "synthetic_summary": summary, "masked_logp_sums": values, "scored_token_counts": counts}


def run(args):
    # Weight loading is reachable only through an explicit GPU --run invocation.
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("GPU scoring requires CUDA; CPU preparation must use --self-test")
    from peft import PeftModel
    from swift.llm import get_model_tokenizer, load_dataset, to_device
    from classify_answers import read_rows, write_json
    from sample_m0 import sha

    if args.output.exists():
        raise FileExistsError(args.output)
    refs = read_rows(args.index)
    assert len({ref["pair"] for ref in refs}) == len(refs)
    loaded, _ = load_dataset(str(args.pairs.resolve()), strict=True, use_hf=True,
                             shuffle=False, remove_unused_columns=False)
    assert len(loaded) == len(refs)
    chosen = list(range(len(refs)))
    if args.probe_index:
        probe = read_rows(args.probe_index)
        lookup = {ref["pair"]: n for n, ref in enumerate(refs)}
        chosen = [lookup[ref["pair"]] for ref in probe]
        assert len(set(chosen)) == len(chosen) and all(refs[n] == ref for n, ref in zip(chosen, probe))
    base, processor = get_model_tokenizer(str(args.base_model.resolve()), model_type="qwen3_vl", use_hf=True,
                                          torch_dtype=torch.bfloat16, device_map="cuda:0", attn_impl="sdpa")
    model = PeftModel.from_pretrained(base, str(args.adapter.resolve()), is_trainable=False)
    model.eval()
    template = make_template(processor)
    template.model = model
    scores = []
    for n in chosen:
        encoded = encode_pair(template, loaded[n])
        batch = to_device(template.data_collator([encoded]), model.device)
        labels = batch.pop("labels")
        batch.pop("text_position_ids", None)
        with torch.inference_mode(), template.forward_context(model, batch):
            with model.disable_adapter():
                output = model(**batch, use_cache=False)
                m0, counts = response_logps(output.logits, labels)
                del output
            output = model(**batch, use_cache=False)
            candidate, candidate_counts = response_logps(output.logits, labels)
            del output
        assert counts == candidate_counts
        row = preference(refs[n], m0[0], m0[1], candidate[0], candidate[1])
        row.update(chosen_scored_tokens=counts[0], rejected_scored_tokens=counts[1])
        scores.append(row)
        print(f"scored {len(scores)}/{len(chosen)} pair={refs[n]['pair']}", flush=True)
    args.output.mkdir(parents=True)
    with (args.output / "pair_logps.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        for row in scores:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "summary.json", {"status": "complete", **summarize(scores),
               "pairs_sha256": sha(args.pairs), "index_sha256": sha(args.index),
               "probe_index_sha256": sha(args.probe_index) if args.probe_index else None,
               "base_model": str(args.base_model.resolve()), "adapter": str(args.adapter.resolve())})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run", action="store_true")
    for name in ("pairs", "index", "base-model", "adapter", "output", "probe-index"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.self_test:
        if args.run or any(getattr(args, key) is not None for key in ("pairs", "index", "base_model", "adapter", "output", "probe_index")):
            parser.error("Use --self-test alone")
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return
    if not args.run or not all(getattr(args, key) for key in ("pairs", "index", "base_model", "adapter", "output")):
        parser.error("Scoring requires --run --pairs --index --base-model --adapter --output")
    for path in (args.pairs, args.index, args.base_model, args.adapter):
        if not path.exists():
            parser.error(f"Missing input: {path}")
    os.environ.update(HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1", MODELSCOPE_OFFLINE="1",
                      MIN_PIXELS="1003520", MAX_PIXELS="4014080", IMAGE_MIN_TOKEN_NUM="980",
                      IMAGE_MAX_TOKEN_NUM="3920", SPATIAL_MERGE_SIZE="2")
    run(args)


if __name__ == "__main__":
    main()
