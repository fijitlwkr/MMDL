"""Build R1 inputs on CPU or explicitly run a resumable M0 sampling job."""
import argparse
from collections import Counter
import csv
import hashlib
import importlib.metadata
import json
import os
import re
import random
import time
from pathlib import Path

from classify_answers import FORMATS, POOL, ROOT, WORKSPACE, read_rows, write_json
from frozen_generation.inputs import load_processor, prepare_inputs
from frozen_generation.vllm_engine import llm_kwargs, sampling_kwargs
from reward import MC_FORMATS, evaluate, reward

CONFIG = ROOT / "scripts/frozen_generation/config.yaml"
CONFIG_SHA = "3946c9a93cd5ab1cc5a8010fc00473e8a71f1c589e0a5f664edb70a3097234dc"
REWARD_V2_SHA = "ba71a13013bdd3244d972d3d2d45edf4bf22abdccc8eb80163d28f7e64263b82"
POOL_SHA = {
    "E1_train_swift.jsonl": "a8405759de84c93904dab137c16106b657e5b05682a0fd755b955c2f707941ab",
    "image_manifest.csv": "84a5c342294b55d1fc3c915014c7c7b6fd75ce8b12572e112a15e2cbc9067da9",
}
SEED = 3407
STRIDE = 65536
MARKERS = re.compile(r"\b(?:wait|perhaps|alternatively|actually|however|reconsider|re-examine|re-evaluate)\b", re.I)


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def request_seed(index, repeat):
    return SEED + index * STRIDE + repeat


def key(item):
    return str(item["row"])


def seed_index(item):
    return item["seed_index"] if "seed_index" in item else item["swift_index"]


def example_for(item, swift):
    if swift is not None:
        return swift[item["swift_index"]]
    paths = [image["path"] for image in item["images"]]
    return {"images": paths, "messages": [{"role": "user", "content": "<image>" * len(paths) + item["prompt"]}]}


def stratified_trial(rows, size=100):
    totals = Counter(row["discipline"] for row in rows)
    quotas = {domain: n * size // len(rows) for domain, n in totals.items()}
    order = sorted(totals, key=lambda domain: (-(totals[domain] * size % len(rows)), domain))
    for domain in order[:size - sum(quotas.values())]:
        quotas[domain] += 1
    rng = random.Random(SEED)
    trial = []
    for domain in sorted(totals):
        domain_rows = sorted((row for row in rows if row["discipline"] == domain), key=lambda r: int(r["row"]))
        trial.extend(rng.sample(domain_rows, quotas[domain]))
    rng.shuffle(trial)
    assert len(trial) == len({key(row) for row in trial}) == size
    return trial


def freeze_trial(rows, pool_path, *, create):
    path = ROOT / "data/trial_100.jsonl"
    picked = stratified_trial(rows)
    pool_digest = sha(pool_path)
    frozen = [{**{k: row[k] for k in ("row", "id", "source", "origin", "discipline", "subject", "seed_index")},
               "pool_sha256": pool_digest, "request_seeds": [request_seed(seed_index(row), j) for j in range(4)]}
              for row in picked]
    if path.exists():
        if read_rows(path) != frozen:
            raise ValueError("The deterministic trial does not match the fixed trial file")
    elif create:
        evaluate.write_rows(path, frozen)
    else:
        raise ValueError("Freeze the 100-row trial with --dry-run before generating")
    return picked


def build_messages(swift, pool, cfg):
    paths = swift["images"]
    prefix = "<image>" * len(paths)
    user = swift["messages"][0]
    if user["role"] != "user" or not user["content"].startswith(prefix + "Question:"):
        raise ValueError("Malformed E1 Swift prompt")
    images = [(pool / name).resolve() for name in paths]
    if not images or not all(path.is_relative_to(pool) and path.is_file() for path in images):
        raise ValueError("Missing or unsafe E1 image path")
    content = [{"type": "image", "image": str(path), "min_pixels": cfg["image"]["min_pixels"],
                "max_pixels": cfg["image"]["max_pixels"]} for path in images]
    return [{"role": "user", "content": content + [{"type": "text", "text": user["content"][len(prefix):]}]}]


def prompt_input(swift, pool, cfg, processor):
    messages = build_messages(swift, pool, cfg)
    prepared, sizes = prepare_inputs(messages, processor)
    encoded = processor(text=[prepared["prompt"]], images=prepared["multi_modal_data"]["image"], do_resize=False)
    ids = encoded["input_ids"][0]
    bound = cfg["budget"]["max_model_len"] - cfg["budget"]["max_new_tokens"] - cfg["budget"]["prompt_safety_margin"]
    if len(ids) > bound:
        raise ValueError(f"Prompt requires {len(ids)} tokens, above the evaluation bound {bound}")
    return prepared, ids, sizes


def dry_run(args, cfg, selected, swift):
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1")
    import torch
    torch.set_num_threads(4)
    processor = load_processor(args.processor.resolve(strict=True), cfg)
    original = read_rows(args.pool / "E1_train.jsonl")
    e3 = read_rows(WORKSPACE / "work/train_E3_20261101/data/E3_train_swift.jsonl")
    reference = WORKSPACE / "work/train_E3_20261101/reports/token_lengths_E3.csv"
    with reference.open(encoding="utf-8-sig", newline="") as handle:
        e1_prompt_counts = {int(r["row"]): int(r["prompt_tokens"]) for r in csv.DictReader(handle) if r["role"] == "train"}
    evidence = []
    for item in selected:
        i = item["swift_index"]
        example = swift[i]
        assert e3[i]["messages"][0] == example["messages"][0] and e3[i]["images"] == example["images"]
        prepared, ids, sizes = prompt_input(example, args.pool, cfg, processor)
        independent = original[i]["messages"][0]
        reference_content = []
        for part in independent["content"]:
            if part["type"] == "text":
                reference_content.append(part)
            else:
                reference_content.append({**part, "image": str(args.pool / part["image"])})
        reference_messages = [{"role": independent["role"], "content": reference_content}]
        assert reference_messages == build_messages(example, args.pool, cfg)
        assert prepared["prompt"] == processor.apply_chat_template(reference_messages, tokenize=False, add_generation_prompt=True)
        assert len(ids) == e1_prompt_counts[i], (i, len(ids), e1_prompt_counts[i])
        evidence.append({"row": key(item), "swift_index": i, "format": item["format"],
                         "prompt_tokens": len(ids), "e1_reference_tokens": e1_prompt_counts[i],
                         "resized_image_sizes": sizes, "request_seeds": [request_seed(i, j) for j in range(args.k)]})
    write_json(ROOT / "reports/sampling_dry_run.json",
               {"config_sha256": sha(CONFIG), "swift_reference_sha256": sha(reference),
                "k_example": args.k, "model_loaded": False, "rows": evidence})
    print(f"Dry-run: {len(evidence)} prompts match original E1 messages and frozen Swift prompt token counts")


def dry_run_combined(args, cfg, selected):
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1")
    import torch
    torch.set_num_threads(4)
    processor = load_processor(args.processor.resolve(strict=True), cfg)
    e1 = read_rows(args.pool / "E1_train_swift.jsonl")
    evidence = []
    for row in selected:
        example = example_for(row, None)
        for image in row["images"]:
            if sha(args.image_root / image["path"]) != image["sha256"]:
                raise ValueError(f"Image hash mismatch for {key(row)}")
        prepared, ids, sizes = prompt_input(example, args.image_root, cfg, processor)
        try:
            assert len(ids) == row["prompt_tokens"], (row["row"], len(ids), row["prompt_tokens"])
            if row["origin"] == "A":
                original = e1[row["swift_index"]]
                assert original["messages"][0] == example["messages"][0]
                assert [(args.pool / path).resolve() for path in original["images"]] == [
                    (args.image_root / im["path"]).resolve() for im in row["images"]]
                method = "E1 Swift user/images and frozen token reference"
            else:
                images = prepared["multi_modal_data"]["image"]
                grids = processor.image_processor(images, do_resize=False)["image_grid_thw"]
                base = processor.tokenizer.encode(prepared["prompt"], add_special_tokens=False)
                image_id = processor.image_token_id
                assert base.count(image_id) == len(grids)
                counts = iter([int(grid.prod()) // processor.image_processor.merge_size**2 for grid in grids])
                independent = []
                for token in base:
                    independent.extend([token] * (next(counts) if token == image_id else 1))
                assert ids == independent, row["row"]
                method = "independent tokenizer IDs and vision grid expansion"
            evidence.append({"row": row["row"], "origin": row["origin"], "discipline": row["discipline"],
                             "prompt_tokens": len(ids), "resized_image_sizes": sizes, "method": method})
        finally:
            for image in prepared["multi_modal_data"]["image"]:
                image.close()
    write_json(ROOT / "reports/stage1b_sampling_dry_run.json",
               {"config_sha256": sha(CONFIG), "pool_sha256": sha(args.pool_jsonl),
                "model_loaded": False, "rows": evidence})
    print(f"Combined-pool dry-run: {len(evidence)} checked, " + str(dict(Counter(r["origin"] for r in evidence))))


def append_bytes(path, data):
    with path.open("ab") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def append_record(path, record):
    append_bytes(path, json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n")


def read_raw(path, repair=False):
    """Seal a torn terminal line by appending its digest, preserving every byte."""
    if not path.exists():
        return []
    rows, invalid = [], None
    with path.open("rb") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                if invalid is not None:
                    raise ValueError("Multiple consecutive corrupt raw lines")
                invalid = hashlib.sha256(line.removesuffix(b"\n")).hexdigest()
                continue
            if invalid is not None:
                if record != {"partial_line_sha256": invalid}:
                    raise ValueError("Unsealed interior corrupt raw line")
                invalid = None
            else:
                rows.append(record)
    with path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        if size:
            handle.seek(-1, os.SEEK_END)
        needs_newline = bool(size and handle.read(1) != b"\n")
    if invalid is not None or needs_newline:
        if not repair:
            raise ValueError("Raw has an interrupted tail. Resume the sampler before grouping.")
        suffix = b"\n" if needs_newline else b""
        if invalid is not None:
            suffix += json.dumps({"partial_line_sha256": invalid}).encode("ascii") + b"\n"
        append_bytes(path, suffix)
    return rows


def run_reward(use_v2):
    legacy_sha = sha(ROOT / "scripts/reward.py")
    if not use_v2:
        return reward, {"reward_sha256": legacy_sha}
    digest = sha(ROOT / "scripts/reward_v2.py")
    if digest != REWARD_V2_SHA:
        raise ValueError("Frozen reward_v2 hash mismatch")
    from reward_v2 import reward as reward_v2

    return reward_v2, {"reward_version": "v2", "reward_sha256": digest, "legacy_reward_sha256": legacy_sha}


def run(args, cfg, selected, swift):
    if not args.out or (swift is not None and not args.formats):
        raise ValueError("--run requires --out, and legacy mode also requires --formats")
    if any(item["format"] not in MC_FORMATS for item in selected):
        raise ValueError("Numeric and short-answer policies are pending approval. Open v2 is diagnostic only.")
    out = args.out.resolve()
    if not out.is_relative_to(ROOT.resolve() / "data") or out == ROOT.resolve() / "data":
        raise ValueError("--out must be a new or resumable run directory inside R1 data/")
    score, reward_manifest = run_reward(args.reward_v2)
    if importlib.metadata.version("vllm") != cfg["environment"]["expected_packages"]["vllm"]:
        raise ValueError("vLLM version differs from evaluation config")
    os.environ.update(cfg["environment"]["env_vars"])
    from huggingface_hub import snapshot_download
    from vllm import LLM, SamplingParams

    model = Path(snapshot_download(cfg["model"]["repo_id"], revision=cfg["model"]["revision"], local_files_only=True))
    image_root = args.pool if swift is not None else args.image_root
    if swift is not None:
        with (args.pool / "image_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
            image_hashes = {entry["path"]: entry["sha256"] for entry in csv.DictReader(handle)}
    for item in selected:
        example = example_for(item, swift)
        build_messages(example, image_root, cfg)
        expected = image_hashes if swift is not None else {im["path"]: im["sha256"] for im in item["images"]}
        for name in example["images"]:
            if sha(image_root / name) != expected[name]:
                raise ValueError(f"Image hash mismatch: {name}")
    manifest = {"config_sha256": sha(CONFIG),
                "sampler_sha256": sha(Path(__file__)), **reward_manifest,
                "code_sha256": evaluate.code_hashes(), "model": cfg["model"], "k": args.k,
                "rows": [key(item) for item in selected]}
    if swift is not None:
        manifest.update(swift_sha256=sha(args.pool / "E1_train_swift.jsonl"),
                        image_manifest_sha256=sha(args.pool / "image_manifest.csv"),
                        answer_types_sha256=sha(ROOT / "data/answer_types.jsonl"))
    else:
        manifest["pool_sha256"] = sha(args.pool_jsonl)
        if args.stratified_trial:
            manifest["trial_sha256"] = sha(ROOT / "data/trial_100.jsonl")
    out.mkdir(parents=True, exist_ok=True)
    with evaluate.execution_lock(out):
        manifest_path, raw = out / "manifest.json", out / "raw.jsonl"
        if manifest_path.exists():
            if evaluate.read_json(manifest_path) != manifest:
                raise ValueError("Resume input or parameters differ from the run manifest")
        elif raw.exists():
            raise ValueError("Raw exists without a manifest")
        else:
            evaluate.write_json(manifest_path, manifest)
        requests = {(key(item), j): item for item in selected for j in range(args.k)}
        done = set()
        for record in read_raw(raw, repair=True):
            pair = (record["row"], record["repeat"])
            if pair not in requests or pair in done or record["seed"] != request_seed(seed_index(requests[pair]), pair[1]):
                raise ValueError(f"Invalid or duplicate raw request {pair}")
            done.add(pair)
        pending = [pair for pair in requests if pair not in done]
        if not pending:
            print(f"Already complete: {len(done)} responses")
            return
        processor = load_processor(model, cfg)
        engine = LLM(**llm_kwargs(cfg, model))
        started = time.monotonic()
        cursor = 0
        while cursor < len(pending):
            size = cfg["run"]["first_chunk_size"] if not cursor and not done else cfg["run"]["chunk_size"]
            batch = pending[cursor:cursor + size]
            prepared, params, counts, cached = [], [], [], {}
            for row, repeat in batch:
                item = requests[row, repeat]
                index = seed_index(item)
                if row not in cached:
                    cached[row] = prompt_input(example_for(item, swift), image_root, cfg, processor)
                prompt, ids, _ = cached[row]
                prepared.append(prompt)
                counts.append(len(ids))
                params.append(SamplingParams(**{**sampling_kwargs(cfg), "seed": request_seed(index, repeat)}))
            outputs = engine.generate(prepared, params, use_tqdm=False)
            for pair, count, output in zip(batch, counts, outputs, strict=True):
                row, repeat = pair
                completion, = output.outputs
                if len(output.prompt_token_ids) != count:
                    raise ValueError(f"Prompt token mismatch for {pair}")
                if completion.finish_reason not in ("stop", "length"):
                    raise ValueError(f"Unexpected finish reason for {pair}")
                value, reason = score(completion.text, completion.finish_reason, requests[pair])
                append_record(raw, {"row": row, "repeat": repeat, "seed": request_seed(seed_index(requests[pair]), repeat),
                                    "raw_text": completion.text, "finish_reason": completion.finish_reason,
                                    "prompt_tokens": count, "output_tokens": len(completion.token_ids),
                                    "reward": value, "reward_reason": reason,
                                    "marker_count": len(MARKERS.findall(completion.text))})
            cursor += len(batch)
            print(f"Completed {len(done) + cursor}/{len(requests)} responses ({time.monotonic() - started:.1f}s)", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--k", type=int, default=4, help="Draft trial default, pending decision")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--formats", nargs="+", choices=FORMATS[:-1])
    parser.add_argument("--pool", type=Path, default=POOL)
    parser.add_argument("--pool-jsonl", type=Path, help="Combined R1 pool")
    parser.add_argument("--image-root", type=Path, default=WORKSPACE)
    parser.add_argument("--stratified-trial", action="store_true", help="Use the fixed stratified trial of 100 rows at K=4")
    parser.add_argument("--reward-v2", action="store_true", help="Use the validated terminal fallback during --run")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--processor", type=Path, default=POOL.parent / "final_v5/cache/qwen3_vl_4b_ebb281ec")
    args = parser.parse_args()
    if args.reward_v2 and not args.run:
        parser.error("--reward-v2 requires --run")
    if not 0 < args.k < STRIDE or (args.limit is not None and args.limit <= 0):
        parser.error("K and limit must be positive; K must be below 65536")
    if sha(CONFIG) != CONFIG_SHA:
        raise ValueError("Evaluation config hash mismatch")
    import yaml
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    if args.stratified_trial and (not args.pool_jsonl or args.k != 4 or args.limit not in (None, 100) or args.formats):
        parser.error("--stratified-trial requires --pool-jsonl, K=4, and the full format mix")
    if args.pool_jsonl:
        args.pool_jsonl = args.pool_jsonl.resolve(strict=True)
        args.image_root = args.image_root.resolve(strict=True)
        rows = read_rows(args.pool_jsonl)
        if (len(rows) != 1500 or len({key(r) for r in rows}) != len(rows)
                or len({seed_index(r) for r in rows}) != len(rows)
                or any(r["format"] not in MC_FORMATS or r["answer"] not in r["choices"] for r in rows)):
            raise ValueError("Expected a validated 1,500-question MC pool with unique row and seed keys")
        if args.stratified_trial:
            selected = freeze_trial(rows, args.pool_jsonl, create=args.dry_run)
        else:
            selected = [r for r in rows if not args.formats or r["format"] in args.formats][:args.limit]
        if not selected:
            raise ValueError("No eligible combined-pool questions")
        if args.dry_run:
            dry_run_combined(args, cfg, selected)
        else:
            run(args, cfg, selected, None)
        return
    args.pool = args.pool.resolve(strict=True)
    for name, digest in POOL_SHA.items():
        if sha(args.pool / name) != digest:
            raise ValueError(f"Frozen pool hash mismatch: {name}")
    items = read_rows(ROOT / "data/answer_types.jsonl")
    swift = read_rows(args.pool / "E1_train_swift.jsonl")
    train = [item for item in items if item["role"] == "train"]
    if [item["swift_index"] for item in train] != list(range(len(swift))) or len(train) != 3000:
        raise ValueError("Train pool and E1 Swift rows do not align")
    selected = [item for item in train if item["format"] in (args.formats or FORMATS[:-1])][:args.limit]
    if not selected:
        raise ValueError("No eligible questions")
    if args.dry_run:
        dry_run(args, cfg, selected, swift)
    else:
        run(args, cfg, selected, swift)


if __name__ == "__main__":
    main()
