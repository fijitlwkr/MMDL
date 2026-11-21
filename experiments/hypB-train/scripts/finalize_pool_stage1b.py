"""Screen the received MMFR images against the fixed R1 data requirements."""
from collections import Counter, defaultdict
import csv
import json
import os
import random
import re
import sqlite3
import sys

from PIL import Image
from prepare_pool_stage1b import OUT, POOL, REPORTS, ROOT, SEED, WORKSPACE, identity, read_rows, write_json, write_rows
from sample_m0 import CONFIG, CONFIG_SHA, sha
from frozen_generation.inputs import load_processor, prepare_inputs
from stage47_prepare import IMAGE_CONFIG, _prompt_text, build_messages, split_options

PREVIOUS = POOL.parent / "final_v5_refill18"
REFERENCE = POOL.parent / "tech_expand_20261025/cache/contamination/references.sqlite"
REFERENCE_SHA = "f2284d4e49412458e0507a9353ea7b0bb0e584ff6e948584b0c17536798d76d6"
TOKEN_REFERENCE = WORKSPACE / "work/train_E3_20261101/reports/token_lengths_E3.csv"
TRIM_ORDER = ("Health & Medicine", "Science", "Business")
MARK = re.compile(r"<image(?:\s+(\d+))?>", re.I)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def image_record(relative, row):
    path = WORKSPACE / relative
    if not path.is_file() or path.stat().st_size != int(row["bytes"]) or sha(path) != row["sha256"]:
        raise ValueError(f"Image manifest mismatch: {relative}")
    return {"path": relative, "sha256": row["sha256"], "bytes": int(row["bytes"]),
            "width": int(row["width"]), "height": int(row["height"])}


def formatted(row, image, cfg, processor):
    matches = list(MARK.finditer(row["question"]))
    if len(matches) != 1 or matches[0][1] not in (None, "1"):
        return None, "image_reference_structure"
    question = MARK.sub("<image 1>", row["question"])
    stem, choices, _ = split_options(question)
    # The E1 formatter parses the option block after numbering image markers.
    if stem is None or choices != {k: MARK.sub("<image 1>", v) for k, v in row["choices"].items()}:
        return None, "normalized_choice_disagreement"
    prompt = _prompt_text({"question": stem}, choices)
    path = ROOT / "data" / image["path"]
    messages = build_messages({"image_paths": [str(path)], "prompt": prompt}, IMAGE_CONFIG)
    payload, _ = prepare_inputs(messages, processor)
    images = payload["multi_modal_data"]["image"]
    try:
        ids = processor(text=[payload["prompt"]], images=images, do_resize=False)["input_ids"][0]
    finally:
        for img in images:
            img.close()
    bound = cfg["budget"]["max_model_len"] - cfg["budget"]["max_new_tokens"] - cfg["budget"]["prompt_safety_margin"]
    assert bound == 8064
    if len(ids) > bound:
        return None, "prompt_token_limit"
    result = {key: row[key] for key in ("origin", "split", "source", "id", "discipline", "subject", "pass_rate")}
    result.update(row=str(row["row"]), seed_index=3000 + int(row["row"]), format=row["gold_format"], answer=row["gold"],
                  choices=choices, prompt=prompt, prompt_tokens=len(ids),
                  images=[image_record(path.relative_to(WORKSPACE).as_posix(), image)])
    return result, None


def add_indexes(indexes, who, question, stem, choices, image_hashes, words):
    indexes["source_id"][identity(who)].add(str(who["row"]))
    if q := tuple(words(question)):
        indexes["text"][q].add(str(who["row"]))
    if stem is not None:
        key = (tuple(words(stem)), tuple(tuple(words(v)) for v in choices.values()))
        indexes["prompt"][key].add(str(who["row"]))
    for digest in image_hashes:
        indexes["image_sha256"][digest].add(str(who["row"]))


def duplicates(indexes, who, question, stem, choices, images, words):
    return {label: sorted(indexes[label][value]) for label, value in
            [("source_id", identity(who)), ("text", tuple(words(question))),
             ("prompt", (tuple(words(stem)), tuple(tuple(words(v)) for v in choices.values()))),
             ("image_sha256", images[0]["sha256"])] if value in indexes[label]}


def contamination(candidates, words, grams, phash):
    assert sha(REFERENCE) == REFERENCE_SHA
    own13, own5 = defaultdict(set), defaultdict(set)
    sizes, hashes = {}, {}
    for row, raw in candidates:
        key = row["row"]
        tokens = words(raw["question"])
        five = grams(tokens, 5)
        sizes[key] = len(five)
        for g in grams(tokens, 13):
            own13[g].add(key)
        for g in five:
            own5[g].add(key)
        with Image.open(WORKSPACE / row["images"][0]["path"]) as image:
            hashes[key] = phash(image)
    pairs, counts, max_jaccard = [], Counter(), 0.0
    db = sqlite3.connect(REFERENCE.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        query = "SELECT repo,path,id,question,images FROM refs ORDER BY key"
        for repo, path, ident, question, images in db.execute(query):
            counts[repo] += 1
            tokens = words(question)
            overlap13 = Counter(row for g in grams(tokens, 13) for row in own13.get(g, ()))
            ref = {"repo": repo, "path": path, "id": ident}
            pairs.extend({"row": row, "reference": ref, "method": "13gram", "shared": n}
                         for row, n in sorted(overlap13.items()))
            five = grams(tokens, 5)
            overlap5 = Counter(row for g in five for row in own5.get(g, ()))
            for row, n in sorted(overlap5.items()):
                score = n / (len(five) + sizes[row] - n)
                max_jaccard = max(score, max_jaccard)
                if score >= 0.5:
                    pairs.append({"row": row, "reference": ref, "method": "5gram_jaccard", "score": score})
            for image in json.loads(images):
                ref_hash = int(image["phash"])
                for row, own in hashes.items():
                    distance = (ref_hash ^ own).bit_count()
                    if distance <= 10:
                        pairs.append({"row": row, "reference": ref, "method": "phash",
                                      "reference_image": image["col"], "distance": distance})
    finally:
        db.close()
    assert counts == {"MMMU/MMMU": 11550, "MMMU/MMMU_Pro": 1730}
    write_json(REPORTS / "stage1b_contamination_pairs.json", pairs)
    return {p["row"] for p in pairs}, {"references": counts, "pairs": len(pairs),
                                      "methods": Counter(p["method"] for p in pairs), "max_5gram_jaccard": max_jaccard}


def choose(b, c, a):
    noncs = [r for r in b if r["subject"] != "Computer_Science"]
    cs = [r for r in b if r["subject"] == "Computer_Science"]
    b_count = 1500 - len(a)
    assert b_count == 139
    if len(noncs) > b_count:
        b_selected = random.Random(SEED).sample(noncs, b_count)
    else:
        b_selected = noncs + random.Random(SEED).sample(cs, min(len(cs), b_count - len(noncs)))
    if len(b_selected) < b_count:
        raise ValueError(f"B has only {len(b_selected)} of {b_count} required candidates")
    c_cap = 200 - sum(r["discipline"] == "Art & Design" for r in a)
    assert c_cap == 140
    c_selected = random.Random(SEED).sample(c, c_cap) if len(c) > c_cap else c
    ties = sorted((r for r in a if r["discipline"] in TRIM_ORDER), key=lambda r: int(r["row"]))
    random.Random(SEED).shuffle(ties)
    ties.sort(key=lambda r: float(r["pass_rate"]) != 1.0)
    counts = Counter(r["discipline"] for r in a)
    removed = []
    for _ in c_selected:
        domain = max(TRIM_ORDER, key=counts.__getitem__)
        index = next(i for i, row in enumerate(ties) if row["discipline"] == domain)
        removed.append(ties.pop(index))
        counts[domain] -= 1
    drop = {r["row"] for r in removed}
    return [r for r in a if r["row"] not in drop], b_selected, c_selected, removed


def main():
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1")
    import torch
    import yaml
    torch.set_num_threads(4)
    assert sha(CONFIG) == CONFIG_SHA
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    proc = load_processor(POOL.parent / "final_v5/cache/qwen3_vl_4b_ebb281ec", cfg)
    # The legacy pHash helper prepends its vendored dependencies at import.
    paths = sys.path[:]
    try:
        sys.path.insert(0, str(PREVIOUS))
        from check_contamination import grams, phash, words
    finally:
        sys.path[:] = paths
    source_rows = read_rows(POOL / "handoff_rows.jsonl")
    swift = read_rows(POOL / "E1_train_swift.jsonl")
    manifest = defaultdict(list)
    for image in read_csv(POOL / "image_manifest.csv"):
        manifest[str(image["row"])].append(image)
    indexes = defaultdict(lambda: defaultdict(set))
    for row in source_rows:
        stem, choices, _ = split_options(row["question"])
        add_indexes(indexes, row, row["question"], stem, choices,
                    (im["sha256"] for im in manifest[str(row["row"])]), words)
    assert len(source_rows) == len(manifest) == 3299
    receipt = json.loads((REPORTS / "stage1b_image_receipt.json").read_text(encoding="utf-8"))
    assert receipt["range_bytes_received"] == 1_102_724_846
    received = {r["row"]: r for r in receipt["rows"]}
    inputs = read_rows(OUT / "image_candidates.jsonl")
    assert len(received) == len(inputs) == 388 and received.keys() == {r["row"] for r in inputs}
    screened, log = [], {}
    for number, raw in enumerate(inputs, 1):
        image = received[raw["row"]]
        row_key = str(raw["row"])
        event = log[row_key] = {"row": row_key, "origin": raw["origin"], "subject": raw["subject"],
                                "source": raw["source"], "id": raw["id"]}
        if image["status"] != "image_ok":
            event["status"] = image["status"]
            continue
        row, reason = formatted(raw, image, cfg, proc)
        if reason:
            event["status"] = reason
            continue
        event["prompt_tokens"] = row["prompt_tokens"]
        if hits := duplicates(indexes, row, raw["question"], raw["stem"], raw["choices"], row["images"], words):
            event.update(status="existing_duplicate", matches=hits)
            continue
        event["status"] = "pre_contamination_pass"
        screened.append((row, raw))
        if number % 40 == 0:
            print(f"CPU image/format/length {number}/{len(inputs)}", flush=True)
    print(f"Contamination comparison for {len(screened)} candidates", flush=True)
    flags, stats = contamination(screened, words, grams, phash)
    filtered, seen = {"B": [], "C": []}, defaultdict(lambda: defaultdict(set))
    # Keep a clean representative, giving eligible non-CS B rows priority.
    screened.sort(key=lambda pair: (pair[0]["origin"], pair[0]["subject"] == "Computer_Science", int(pair[0]["row"])))
    for row, raw in screened:
        event = log[row["row"]]
        if row["row"] in flags:
            event["status"] = "contamination_near_match"
            continue
        if hits := duplicates(seen, row, raw["question"], raw["stem"], raw["choices"], row["images"], words):
            event.update(status="bc_duplicate", matches=hits)
            continue
        add_indexes(seen, row, raw["question"], raw["stem"], raw["choices"],
                    (im["sha256"] for im in row["images"]), words)
        event["status"] = "pass"
        filtered[row["origin"]].append(row)
    for group in filtered.values():
        group.sort(key=lambda row: int(row["row"]))
    write_rows(REPORTS / "stage1b_checks.jsonl", log.values())
    write_json(REPORTS / "stage1b_check_summary.json", stats)

    old_tokens = {int(r["row"]): int(r["prompt_tokens"]) for r in read_csv(TOKEN_REFERENCE) if r["role"] == "train"}
    a = []
    for row in read_rows(OUT / "a_capped.jsonl"):
        record = swift[row["swift_index"]]
        imgs = sorted(manifest[str(row["row"])], key=lambda im: int(im["image_index"]))
        assert record["images"] == [im["path"] for im in imgs]
        prompt = record["messages"][0]["content"]
        prefix = "<image>" * len(imgs)
        assert prompt.startswith(prefix + "Question:")
        fields = ("source", "id", "discipline", "subject", "pass_rate", "format", "answer", "choices", "swift_index")
        a.append({**{k: row[k] for k in fields}, "origin": "A", "split": "sft", "row": str(row["row"]),
                  "seed_index": row["swift_index"], "prompt": prompt[len(prefix):],
                  "prompt_tokens": old_tokens[row["swift_index"]],
                  "images": [image_record((POOL / im["path"]).relative_to(WORKSPACE).as_posix(), im) for im in imgs]})
    a, b, c, removed = choose(filtered["B"], filtered["C"], a)
    final = a + b + c
    assert len(final) == len({r["row"] for r in final}) == len({identity(r) for r in final}) == 1500
    assert len({r["seed_index"] for r in final}) == len(final)
    assert not {r["row"] for r in final} & flags
    assert all(r["answer"] in r["choices"] and r["prompt_tokens"] <= 8064 for r in final)
    write_rows(ROOT / "data/r1_pool.jsonl", final)
    by_row = {r["row"]: r for r in b+c}
    with (ROOT / "data/images_B_manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ("origin", "split", "row", "source", "id", "path", "sha256", "bytes", "width", "height")
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in by_row.values():
            writer.writerow({k: (row | row["images"][0])[k] for k in fields})
    write_json(REPORTS / "stage1b_selection.json",
               {"removed_a": [{k: r[k] for k in ("row", "discipline", "subject", "pass_rate")} for r in removed],
                "b_selected": [r["row"] for r in b], "c_selected": [r["row"] for r in c],
                "verified": len(final), "candidates_checked": len(inputs)})
    print("Final pool", Counter(r["origin"] for r in final), flush=True)


if __name__ == "__main__":
    main()
