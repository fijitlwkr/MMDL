"""Apply the A cap, prescreen B/C, then measure image ranges from local footers."""
import argparse
from collections import Counter
import csv
import json
import random
import sqlite3
import sys
from pathlib import Path

from classify_answers import POOL, ROOT, WORKSPACE, classify, read_rows, write_json, write_rows

MMFR = WORKSPACE / "work/mmfr18m_check"
OUT = ROOT / "data/stage1b"
REPORTS = ROOT / "reports"
SEED = 3407
REVISION = "7c93f724791d01246f5425e1182b14ec8d013847"
TECH = ("Mechanical_Engineering", "Electronics", "Architecture_and_Engineering",
        "Materials", "Agriculture", "Energy_and_Power", "Computer_Science")
ART = ("Art", "Art_Theory", "Design", "Music")

sys.path.insert(0, str(POOL.parent / "final_v5"))
from stage47_prepare import content_key, split_options


def identity(row):
    return row["source"], str(row["id"])


def cap_a(rows):
    eligible = [r for r in rows if r["role"] == "train" and r["format"] in ("mc_letter", "mc_value")]
    economics = sorted((r for r in eligible if r["subject"] == "Economics"), key=lambda r: int(r["row"]))
    assert (len(rows), len(eligible), len(economics)) == (3299, 1574, 463)
    kept = {r["row"] for r in random.Random(SEED).sample(economics, 250)}
    capped = [r for r in eligible if r["subject"] != "Economics" or r["row"] in kept]
    assert len(capped) == 1361 and sum(r["discipline"] == "Art & Design" for r in capped) == 60
    return capped, [r["row"] for r in economics if r["row"] not in kept]


def prescreen(label, row, existing):
    if label == "C" and identity(row) in existing:
        return "existing_source_id", None
    if row["pass_rate"] == 0:
        return "pass_rate_zero", None
    if row["consistent"] == 0:
        return "inconsistent", None
    stem, choices, layout = split_options(row["question"])
    if not choices:
        return ("non_mc" if layout == "open_ended" else "ambiguous_layout"), None
    fmt, answer, reason = classify((row["answer"] or "").strip(), choices, content_key)
    if fmt not in ("mc_letter", "mc_value"):
        return "ambiguous_answer:" + reason, None
    return "mc", {**row, "origin": label, "stem": stem, "choices": choices, "gold_format": fmt,
                  "gold": answer, "layout": layout}


def extract():
    types = read_rows(ROOT / "data/answer_types.jsonl")
    capped, removed = cap_a(types)
    write_rows(OUT / "a_capped.jsonl", capped)
    write_json(REPORTS / "stage1b_a_cap.json", {"removed_economics_rows": removed,
                                              "discipline": Counter(r["discipline"] for r in capped),
                                              "subject": Counter(r["subject"] for r in capped)})
    existing = {identity(r) for r in types}
    evidence = []
    uri = (MMFR / "cache/stage1.sqlite").resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        db.row_factory = sqlite3.Row
        for label, split, file, domain, subjects in (
            ("B", "rl", "rl_labels.csv", "Tech & Engineering", TECH),
            ("C", "sft", "labels.csv", "Art & Design", ART),
        ):
            candidates = []
            with (MMFR / file).open(encoding="utf-8-sig", newline="") as handle:
                for entry in csv.DictReader(handle):
                    if entry["split"] != split or entry["discipline"] != domain or entry["subject"] not in subjects:
                        continue
                    matches = db.execute(
                        "SELECT row,split,source,id,discipline,subject,pass_rate,consistent,question,answer "
                        "FROM records WHERE source=? AND id=? AND split=?", (*identity(entry), split)
                    ).fetchall()
                    assert len(matches) == 1, identity(entry)
                    row = dict(matches[0])
                    assert all(str(row[k]) == entry[k] for k in ("source", "id", "discipline", "subject"))
                    assert row["pass_rate"] == float(entry["pass_rate"])
                    status, candidate = prescreen(label, row, existing)
                    evidence.append({k: row[k] for k in ("row", "source", "id", "subject", "consistent", "pass_rate")}
                                    | {"origin": label, "status": status})
                    if candidate is not None:
                        candidates.append(candidate)
            write_rows(OUT / f"{label.lower()}_mc_candidates.jsonl", sorted(candidates, key=lambda r: r["row"]))
    write_rows(REPORTS / "stage1b_prescreen.jsonl", evidence)
    print("A", len(capped), "B slots", 1500 - len(capped))
    for label in ("B", "C"):
        print(label, dict(Counter(r["status"] for r in evidence if r["origin"] == label)))


def plan():
    sys.path.insert(0, str(POOL.parent))
    from inspect_stage0 import footer, image_chunks

    b = read_rows(OUT / "b_mc_candidates.jsonl")
    c = read_rows(OUT / "c_mc_candidates.jsonl")
    review = json.loads((REPORTS / "stage1b_c_content_review.json").read_text(encoding="utf-8"))
    decisions = {item["row"]: item for item in review}
    assert len(review) == len(decisions) == len(c) and decisions.keys() == {r["row"] for r in c}
    assert all(d["decision"] in ("art", "exclude") and d["reason"] for d in review)
    selected = b + [r for r in c if decisions[r["row"]]["decision"] == "art"]
    valid = []
    structural = []
    for r in selected:
        choices = r["choices"]
        keys = [content_key(v) for v in choices.values()]
        reason = ("invalid_choice_structure" if len(choices) < 2 or r["gold"] not in choices or not all(keys)
                  else "duplicate_choices" if len(set(keys)) != len(keys) else None)
        if reason is None:
            valid.append(r)
        else:
            structural.append({"row": r["row"], "origin": r["origin"], "subject": r["subject"], "reason": reason})
    write_rows(OUT / "image_candidates.jsonl", valid)
    write_json(REPORTS / "stage1b_structure_exclusions.json", structural)

    source = json.loads((MMFR / "download_plan.json").read_text(encoding="utf-8"))
    assert source["revision"] == REVISION
    found, files, offset = set(), [], 0
    for file in source["files"]:
        candidates = [r for r in valid if offset <= r["row"] < offset + file["rows"]]
        if candidates:
            local_footer = MMFR / "cache" / (Path(file["path"]).name + ".footer")
            groups = []
            for group in image_chunks(footer(local_footer)):
                start = offset + group["row_start"]
                rows = [r for r in candidates if start <= r["row"] < start + group["rows"]]
                if not rows:
                    continue
                assert all(r["split"] == Path(file["path"]).name.split("-")[0] for r in rows)
                found.update(r["row"] for r in rows)
                groups.append({**group, "targets": [{"row": r["row"], "origin": r["origin"],
                                                     "row_group_offset": r["row"] - start} for r in rows]})
            files.append({"path": file["path"], "global_row_start": offset, "groups": groups})
        offset += file["rows"]
    assert offset == source["rows"] and len(found) == len(valid) and found == {r["row"] for r in valid}
    all_groups = [g for f in files for g in f["groups"]]
    counts = {origin: {"rows": sum(r["origin"] == origin for r in valid),
                       "row_groups": sum(any(r["origin"] == origin for r in g["targets"]) for g in all_groups),
                       "bytes": sum(g["bytes"] for g in all_groups if any(r["origin"] == origin for r in g["targets"]))}
              for origin in ("B", "C")}
    size = sum(g["bytes"] for g in all_groups)
    assert sum(v["bytes"] for v in counts.values()) == size
    result = {"revision": REVISION, "range_bytes": size, "threshold_bytes": 1_000_000_000,
              "approval_required": size > 1_000_000_000, "network_bytes_received": 0,
              "by_origin": counts, "files": files}
    write_json(REPORTS / "stage1b_image_transfer_plan.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("extract", "plan"))
    {"extract": extract, "plan": plan}[parser.parse_args().step]()
