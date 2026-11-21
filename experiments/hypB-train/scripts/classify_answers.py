"""Classify the frozen MMFR handoff in source order, without using MMMU."""
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
POOL = WORKSPACE / "work/train_data_B_20261023/final_v5_tech_20261025"
SWIFT_FILES = {"train": "E1_train_swift.jsonl", "holdout": "holdout_300_swift.jsonl"}
MC_END = "\nPlease select the correct answer from the options above."
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
WORD = re.compile(r"[A-Za-z]{2,}")
FORMATS = ("mc_letter", "mc_value", "numeric", "short_rule", "excluded")


def read_rows(path):
    with path.open(encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def prompt_choices(text):
    if not text.endswith(MC_END):
        return {}
    _, sep, block = text.removesuffix(MC_END).rpartition("\nOptions:\n")
    labels = list(re.finditer(r"(?m)^([A-Z])\. ", block))
    if not sep or len(labels) < 2 or [m[1] for m in labels] != list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"[:len(labels)]):
        raise ValueError("Malformed E1 choices")
    choices = {m[1]: block[m.end():labels[i+1].start() if i+1 < len(labels) else len(block)].strip()
               for i, m in enumerate(labels)}
    if not all(choices.values()):
        raise ValueError("Empty E1 choice")
    return choices


def classify(gold, choices, content_key):
    if choices:
        explicit = re.fullmatch(r"(?:option\s+)?\(?([A-Z])\)?[.。]?", gold, re.I)
        if explicit and explicit[1].upper() in choices:
            return "mc_letter", explicit[1].upper(), "explicit_label"
        if re.fullmatch(r"[A-Z](?:\s*(?:[,;、]|\band\b)\s*[A-Z])+", gold, re.I):
            return "excluded", None, "multiple_labels"
        prefix = re.fullmatch(r"([A-Z])[.、:：)]\s*(.+)", gold, re.I | re.S)
        value = prefix[2] if prefix else gold
        matches = [key for key, option in choices.items() if content_key(option) == content_key(value)]
        if len(matches) == 1 and (not prefix or prefix[1].upper() == matches[0]):
            return "mc_value", matches[0], "unique_value" if not prefix else "label_and_unique_value"
        if prefix and not matches:
            matches = [key for key, option in choices.items() if content_key(option) == content_key(gold)]
            if len(matches) == 1:
                return "mc_value", matches[0], "unique_full_value"
        return "excluded", None, "non_unique_value" if len(matches) > 1 else "unmapped_or_conflicting_value"
    if NUMBER.fullmatch(gold):
        return "numeric", gold, "single_number_surface"
    if WORD.fullmatch(gold):
        return "short_rule", gold, "single_alphabetic_word"
    return "excluded", None, "complex_or_ambiguous_open"


def main():
    # Use E1's existing presentation-only choice key.
    sys.path.insert(0, str(POOL.parent / "final_v5"))
    from stage47_prepare import content_key

    handoff = read_rows(POOL / "handoff_rows.jsonl")
    swift = {role: read_rows(POOL / name) for role, name in SWIFT_FILES.items()}
    with (POOL / "image_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        images = defaultdict(list)
        for image in csv.DictReader(handle):
            images[image["row"]].append(image)
    counts, failures, rows = Counter(), [], []
    assert len({str(r["row"]) for r in handoff}) == len(handoff) == 3299
    assert len({(r["source"], r["id"]) for r in handoff}) == len(handoff)
    for index, item in enumerate(handoff):
        role, row = item["role"], str(item["row"])
        swift_index = counts[role]
        counts[role] += 1
        example = swift[role][swift_index]
        image_entries = sorted(images[row], key=lambda x: int(x["image_index"]))
        assert all((x["role"], x["source"], x["id"]) == (role, item["source"], str(item["id"])) for x in image_entries)
        assert [x["path"] for x in image_entries] == example["images"] and image_entries
        user, assistant = example["messages"]
        assert (user["role"], assistant["role"]) == ("user", "assistant")
        assert user["content"].startswith("<image>" * len(image_entries) + "Question:")
        choices = prompt_choices(user["content"])
        gold = item["answer"].strip()
        kind, answer, reason = classify(gold, choices, content_key)
        base = {key: item[key] for key in ("row", "source", "id", "role", "discipline", "subject", "pass_rate")}
        if choices:
            _, marker, final = assistant["content"].rpartition("Final Answer:")
            # The historical conversion can leave a closing quotation mark.
            match = re.fullmatch(r"""\s*([A-Z])\s*[.。]?\s*["'”’]?\s*""", final) if marker else None
            final_label = match[1] if match else None
            if answer is None or final_label != answer:
                failures.append({**base, "source_answer": gold, "mapped_answer": answer,
                                 "e1_final_tail": final.strip()[:120] if marker else None,
                                 "reason": reason if answer is None else "e1_final_disagreement"})
                if answer is not None:
                    kind, answer, reason = "excluded", None, "e1_final_disagreement"
        rows.append({**base, "index": index, "swift_index": swift_index, "format": kind,
                     "answer": answer, "reason": reason, "choices": choices})
    assert counts == {"train": 3000, "holdout": 299}
    assert counts == {role: len(values) for role, values in swift.items()}
    write_rows(ROOT / "data/answer_types.jsonl", rows)
    write_json(ROOT / "reports/e1_mc_crosscheck.json", failures)
    for role in SWIFT_FILES:
        print(role, Counter(r["format"] for r in rows if r["role"] == role))
    print("MC exclusions or disagreements:", Counter(r["reason"] for r in failures))


if __name__ == "__main__":
    main()
