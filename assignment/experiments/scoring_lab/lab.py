#!/usr/bin/env python3
"""Offline scoring experiments. No network, model inference or paid API calls."""
from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import math
import random
import re
from collections import Counter
from pathlib import Path

from parsers import PARSERS, GATES, analyze, judge_prompt

ROOT = Path(__file__).resolve().parent
MODEL_REV = "ebb281ec70b05090aa6165b016eac8ec08e71b17"
DATA_REV = "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68"
SUBJECTS = set("Accounting Agriculture Architecture_and_Engineering Art Art_Theory Basic_Medical_Science Biology Chemistry Clinical_Medicine Computer_Science Design Diagnostics_and_Laboratory_Medicine Economics Electronics Energy_and_Power Finance Geography History Literature Manage Marketing Materials Math Mechanical_Engineering Music Pharmacy Physics Psychology Public_Health Sociology".split())
POLICIES = [f"{p}__{g}" for p in PARSERS for g in GATES]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def load_run(run):
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    rows = read_jsonl(run / "items.jsonl")
    if digest(rows) != manifest["items_digest"]:
        raise ValueError("Prepared items were modified; prepare a new version instead")
    if digest({k: v for k, v in manifest.items() if k != "analysis_id"}) != manifest["analysis_id"]:
        raise ValueError("Analysis manifest was modified")
    return rows, manifest


def first_present(*values):
    return next((v for v in values if v is not None), None)


def normalize(source, *, allow_missing_input_tokens=False):
    ann = source.get("annotation", source)
    uid = str(first_present(ann.get("id"), source.get("id"), source.get("question_id"), ""))
    match = re.fullmatch(r"validation_(.+)_(\d+)", uid)
    if not match or match.group(1) not in SUBJECTS or not 1 <= int(match.group(2)) <= 30:
        # HF IDs are 1..30 in the pinned validation set. The input contract uses
        # an explicit ID set/count check, never numeric TSV index as identity.
        raise ValueError(f"Expected validation_<subject>_<1..30> HF ID, got {uid!r}")
    qtype = first_present(ann.get("question_type"), source.get("question_type"))
    if qtype not in {"multiple-choice", "open"}:
        raise ValueError(f"{uid}: unknown question_type {qtype!r}")
    raw = first_present(source.get("raw_text"), source.get("raw_response"),
                        source.get("result", {}).get("gen_raw"), source.get("result", {}).get("gen"))
    if not isinstance(raw, str):
        raise ValueError(f"{uid}: missing raw text")
    finish = source.get("finish_reason")
    if finish not in {"stop", "length"}:
        raise ValueError(f"{uid}: finish_reason must be stop/length; do not guess from token counts")
    generated = first_present(source.get("generated_tokens"), source.get("output_tokens"))
    input_tokens = source.get("input_tokens")
    for name, value in (("generated_tokens", generated), ("input_tokens", input_tokens)):
        if name == "input_tokens" and value is None and allow_missing_input_tokens:
            continue  # Legacy logs: unknown, never fabricate a token count.
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{uid}: invalid/missing {name}")
    options = ann.get("options", source.get("options"))
    if isinstance(options, str):
        options = ast.literal_eval(options)
    if isinstance(options, list):
        options = {chr(65 + i): value for i, value in enumerate(options)}
    if options is None:
        options = {k: ann[k] for k in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if k in ann and ann[k] is not None}
    if not isinstance(options, dict):
        raise ValueError(f"{uid}: options must be a dictionary/list")
    if any(not isinstance(k, str) or not re.fullmatch("[A-Z]", k) for k in options):
        raise ValueError(f"{uid}: invalid option key")
    if qtype == "multiple-choice":
        if len(options) < 2 or any(not isinstance(v, str) or not v.strip() for v in options.values()):
            raise ValueError(f"{uid}: missing/empty option; literal 'None' is a valid string")
        options = dict(sorted(options.items()))
    else:
        options = {}
    answer = ann.get("answer", source.get("answer"))
    if qtype == "multiple-choice" and answer not in options:
        raise ValueError(f"{uid}: ground truth is not a valid option")
    if qtype == "open" and (not isinstance(answer, str) or not answer.strip()):
        raise ValueError(f"{uid}: reference answer must be a nonempty string")
    question = ann.get("question", source.get("question"))
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"{uid}: missing question")
    return {"id": uid, "subject": match.group(1), "question_type": qtype,
            "question": question, "options": options, "answer": answer,
            "raw_text": raw, "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "finish_reason": finish, "generated_tokens": generated,
            "input_tokens": input_tokens, "source_question_id": source.get("question_id")}


def validate(rows, source_kind, config):
    ids = [r["id"] for r in rows]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Empty input or duplicate HF IDs")
    if source_kind not in {"synthetic-demo", "legacy-pilot"}:
        counts = Counter(r["subject"] for r in rows)
        if len(rows) != 900 or set(counts) != SUBJECTS or set(counts.values()) != {30}:
            raise ValueError("Requires complete 900 rows / all 30 subjects x 30; use synthetic-demo only for fixtures")
    if source_kind == "hf-final":
        expected = {"model_revision": MODEL_REV, "dataset_revision": DATA_REV,
                    "engine_seed": 3407, "sampling_seed": 3407}
        for key, value in expected.items():
            if config.get(key) != value:
                raise ValueError(f"config.{key}: expected {value!r}")
        for key in ("max_model_len", "max_new_tokens"):
            if not isinstance(config.get(key), int) or config[key] <= 0:
                raise ValueError(f"Missing positive config.{key}")
        if any(r["generated_tokens"] > config["max_new_tokens"] for r in rows):
            raise ValueError("Output tokens exceed declared output cap")
        if any(r["input_tokens"] + r["generated_tokens"] > config["max_model_len"] for r in rows):
            raise ValueError("Input plus output tokens exceed declared context window")


def summarize(rows, policy):
    total = len(rows)
    auto = [r for r in rows if r["analysis"]["policies"][policy]["route"] == "auto"]
    correct = sum(r["analysis"]["policies"][policy]["auto_correct"] for r in auto)
    pending = total - len(auto)
    return {"total": total, "auto_accept": len(auto), "judge_pending": pending,
            "auto_correct": correct, "auto_coverage": len(auto) / total if total else None,
            "rule_failure_before_gate": sum(not r["analysis"]["policies"][policy]["rule_success_before_gate"] for r in rows),
            "score_lower_bound_pending_incorrect": correct / total if total else None,
            "final_accuracy": correct / total if total and not pending else None,
            "routes": dict(Counter(r["analysis"]["policies"][policy]["route"] for r in rows))}


def make_summary(rows):
    result = {}
    groups = {"all": rows, **{q: [r for r in rows if r["question_type"] == q] for q in ("multiple-choice", "open")},
              **{f: [r for r in rows if r["finish_reason"] == f] for f in ("stop", "length")}}
    for policy in POLICIES:
        result[policy] = {name: summarize(group, policy) for name, group in groups.items()}
    return result


def prepare(args):
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    source_rows = read_jsonl(args.predictions)
    rows = sorted((normalize(r, allow_missing_input_tokens=args.source_kind in {"legacy-tsv", "legacy-pilot"})
                   for r in source_rows), key=lambda r: r["id"])
    validate(rows, args.source_kind, config)
    config_hash = file_hash(args.config)
    for r in source_rows:
        if r.get("config_sha256") is not None and r["config_sha256"] != config_hash:
            raise ValueError("Row config hash does not match the supplied config bytes")
    for row in rows:
        row["analysis"] = analyze(row)
    manifest = {"source_kind": args.source_kind, "count": len(rows), "config": config,
                "predictions_sha256": file_hash(args.predictions), "config_sha256": config_hash,
                "code_sha256": {str(p.relative_to(ROOT)): file_hash(p) for p in
                                [ROOT / "lab.py", ROOT / "parsers.py", *sorted((ROOT / "vendor").glob("*.py"))]},
                "dataset_verification": "ID/count/config checks only; upstream input_validation + image hashes required separately",
                "api_calls": 0, "human_adoption_status": "not_reviewed", "items_digest": digest(rows)}
    manifest["analysis_id"] = digest(manifest)
    requests = []
    for row in rows:
        needed = [name for name, p in row["analysis"]["policies"].items() if p["route"] != "auto"]
        if not needed:
            continue
        is_mc = row["question_type"] == "multiple-choice"
        choices = row["options"] if is_mc else {"A": row["answer"], "B": "Other Answers"}
        request = {"id": row["id"], "analysis_id": manifest["analysis_id"], "raw_sha256": row["raw_sha256"],
                   "valid_options": list(choices), "reference_aware_open": not is_mc,
                   "prompt": judge_prompt(row["question"], choices, row["raw_text"])}
        request["request_sha256"] = digest(request)
        request["needed_by"] = needed
        requests.append(request)
    args.out.mkdir(parents=True, exist_ok=False)
    write_json(args.out / "manifest.json", manifest)
    write_jsonl(args.out / "items.jsonl", rows)
    write_jsonl(args.out / "judge_requests.jsonl", requests)
    summary = make_summary(rows)
    write_json(args.out / "summary.json", summary)
    lines = ["# Offline parser / length policy comparison", "",
             f"Source: **{args.source_kind}**. Rows: {len(rows)}. API calls: 0.", "",
             "Primary comparison: Qwen, MMMU no-random, VLMEvalKit with one shared AI Judge. hybrid100 is supplementary.", "",
             "These are automatic extraction counts and score lower bounds, not completed hybrid scores.", "",
             "| Policy | Auto | Pending Judge | Auto correct | Lower bound (%) |",
             "|---|---:|---:|---:|---:|"]
    for name, groups in summary.items():
        s = groups["all"]
        lines.append(f"| {name} | {s['auto_accept']} | {s['judge_pending']} | {s['auto_correct']} | {100*s['score_lower_bound_pending_incorrect']:.2f} |")
    lines += ["", "MC comparisons isolate parser rules. Open Qwen/VLMEvalKit/hybrid uses reference-aware A/B matching; MMMU uses its open-answer evaluator. Report them separately.",
              "No policy has been adopted by this command. Finish reason, not re-tokenized output length, defines length cases."]
    (args.out / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "rows": len(rows), "union_judge_requests": len(requests), "api_calls": 0}))


def audit_pack(args):
    rows, manifest = load_run(args.run)
    rng = random.Random(args.seed)
    primary = set(r["id"] for r in rng.sample(rows, min(args.random_n, len(rows))))
    reasons = {}
    for row in rows:
        a = row["analysis"]
        tags = []
        if row["id"] in primary:
            tags.append("random_primary")
        if row["question_type"] == "multiple-choice" and len({a[p] for p in PARSERS}) > 1:
            tags.append("parser_disagreement")
        if a["qwen_marker_conflict"] or a["marker"]["conflicting_markers"]:
            tags.append("conflict")
        if row["finish_reason"] == "length" and any(a[p] is not None and a[p] != [] for p in PARSERS):
            tags.append("length_auto_candidate")
        if tags:
            reasons[row["id"]] = tags
    # Additional non-random cases diagnose failure mechanisms. They must NOT be
    # pooled with the representative random sample to estimate population error.
    selected = [r for r in rows if r["id"] in reasons]
    rng.shuffle(selected)
    blinded = [{"id": r["id"], "analysis_id": manifest["analysis_id"], "raw_sha256": r["raw_sha256"],
                "question_type": r["question_type"], "question": r["question"], "options": r["options"],
                "raw_text": r["raw_text"], "answer_status": "", "human_answer": "",
                "evidence_quote": "", "notes": ""} for r in selected]
    args.out.mkdir(parents=True, exist_ok=False)
    for name in ("rater_1.jsonl", "rater_2.jsonl"):
        write_jsonl(args.out / name, blinded)
    write_json(args.out / "sampling.json", {"analysis_id": manifest["analysis_id"], "seed": args.seed,
               "population": len(rows), "random_primary_n": len(primary), "selected_n": len(selected),
               "reasons_private": reasons, "aggregation": "Report random_primary and enriched separately; do not pool"})
    print(json.dumps({"selected": len(selected), "random_primary": len(primary), "blinded_raters": 2}))


def validated_labels(path, items, analysis_id):
    rows = read_jsonl(path)
    if len(rows) != len({r["id"] for r in rows}):
        raise ValueError("Duplicate human-label IDs")
    result = {}
    for label in rows:
        uid = label["id"]
        if uid not in items or label.get("analysis_id") != analysis_id or label.get("raw_sha256") != items[uid]["raw_sha256"]:
            raise ValueError(f"{uid}: stale/unknown label")
        status = label.get("answer_status")
        if status not in {"unique", "ambiguous", "no_answer"}:
            raise ValueError(f"{uid}: label must be completed: unique/ambiguous/no_answer")
        answer = label.get("human_answer", "")
        if status == "unique":
            valid = answer in items[uid]["options"] if items[uid]["question_type"] == "multiple-choice" else isinstance(answer, str) and bool(answer.strip())
            if not valid:
                raise ValueError(f"{uid}: invalid human answer")
            quote = label.get("evidence_quote", "")
            if not quote or quote not in items[uid]["raw_text"]:
                raise ValueError(f"{uid}: quote must be an exact nonempty excerpt of raw text")
        elif answer:
            raise ValueError(f"{uid}: non-unique labels must leave human_answer empty")
        result[uid] = label
    return result


def label_agreement(args):
    rows, manifest = load_run(args.run)
    items = {r["id"]: r for r in rows}
    analysis_id = manifest["analysis_id"]
    a, b = [validated_labels(path, items, analysis_id) for path in (args.rater1, args.rater2)]
    if not a or a.keys() != b.keys():
        raise ValueError("Both raters must independently label the same nonempty ID set")
    def code(label):
        return label["answer_status"], label["human_answer"]
    disagree = [uid for uid in sorted(a) if code(a[uid]) != code(b[uid])]
    pa = 1 - len(disagree) / len(a)
    ca, cb = Counter(map(code, a.values())), Counter(map(code, b.values()))
    pe = sum(ca[k] * cb[k] for k in ca.keys() | cb.keys()) / len(a)**2
    report = {"total": len(a), "agreement": pa, "cohen_kappa": (pa-pe)/(1-pe) if pe < 1 else None,
              "disagreement_ids": disagree, "open_answer_agreement": "Exact text only; semantic differences need human adjudication",
              "status": "Human adjudication required; this does not create gold labels"}
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({"total": len(a), "disagreements": len(disagree), "agreement": pa}))


def validated_judge_requests(run):
    rows, manifest = load_run(run)
    items = {r["id"]: r for r in rows}
    request_rows = read_jsonl(run / "judge_requests.jsonl")
    requests = {r["id"]: r for r in request_rows}
    if len(requests) != len(request_rows):
        raise ValueError("Duplicate Judge request IDs")
    expected_ids = {r["id"] for r in rows if any(p["route"] != "auto" for p in r["analysis"]["policies"].values())}
    if set(requests) != expected_ids:
        raise ValueError("Judge request IDs do not match the frozen policy union")
    for uid, request in requests.items():
        row = items[uid]
        choices = row["options"] if row["question_type"] == "multiple-choice" else {"A": row["answer"], "B": "Other Answers"}
        expected = {"id": uid, "analysis_id": manifest["analysis_id"], "raw_sha256": row["raw_sha256"],
                    "valid_options": list(choices), "reference_aware_open": row["question_type"] != "multiple-choice",
                    "prompt": judge_prompt(row["question"], choices, row["raw_text"])}
        if request["request_sha256"] != digest(expected) or any(request.get(k) != v for k, v in expected.items()):
            raise ValueError(f"Judge request changed: {uid}")
        needed = [name for name, entry in row["analysis"]["policies"].items() if entry["route"] != "auto"]
        if request.get("needed_by") != needed:
            raise ValueError(f"Judge policy membership changed: {uid}")
    return rows, manifest, requests


def validated_judge_cache(run, path, model):
    _, _, requests = validated_judge_requests(run)
    cache = read_jsonl(path)
    by_id = {}
    settings_hashes = set()
    for result in cache:
        uid = result["id"]
        request = requests.get(uid)
        if uid in by_id or request is None:
            raise ValueError(f"Duplicate/unrequested judge result: {uid}")
        if result.get("request_sha256") != request["request_sha256"] or result.get("model") != model:
            raise ValueError(f"Stale prompt or different judge model: {uid}")
        settings_hash = result.get("judge_settings_sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", settings_hash):
            raise ValueError(f"Missing SHA-256 of shared Judge settings: {uid}")
        settings_hashes.add(settings_hash)
        status = result.get("status")
        if status not in {"success", "extraction_failure", "api_error"}:
            raise ValueError(f"Invalid judge status: {uid}")
        if status == "success" and result.get("parsed") not in request["valid_options"]:
            raise ValueError(f"Invalid judge answer: {uid}")
        if status != "success" and result.get("parsed") is not None:
            raise ValueError(f"Failed extraction cannot carry an answer (no random fallback): {uid}")
        if status != "api_error" and not isinstance(result.get("raw_output"), str):
            raise ValueError(f"Missing preserved Judge output: {uid}")
        by_id[uid] = result
    if len(settings_hashes) > 1:
        raise ValueError("Different Judge configurations cannot share this experiment cache")
    return by_id


def wilson(successes, total):
    if total == 0:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z*z / total
    center = (p + z*z/(2*total)) / denominator
    margin = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / denominator
    return [max(0.0, center-margin), min(1.0, center+margin)]


def audit_score(args):
    rows, manifest = load_run(args.run)
    items = {r["id"]: r for r in rows}
    analysis_id = manifest["analysis_id"]
    sampling = json.loads(args.sampling.read_text(encoding="utf-8"))
    if sampling["analysis_id"] != analysis_id:
        raise ValueError("Stale audit sampling manifest")
    gold = validated_labels(args.gold, items, analysis_id)
    if set(gold) != set(sampling["reasons_private"]):
        raise ValueError("Gold must cover the entire selected audit set; no cherry-picking completed labels")
    if any(not r.get("adjudicated") or not str(r.get("reviewed_by", "")).strip() for r in gold.values()):
        raise ValueError("Gold requires adjudicated=true and reviewed_by after human review")
    cache = validated_judge_cache(args.run, args.judge, args.model) if args.judge else {}
    report = {"analysis_id": analysis_id, "judge_model": args.model,
              "open_rows_excluded_from_mc_fidelity": sum(items[uid]["question_type"] == "open" for uid in gold),
              "note": "Open reference equivalence requires a separate human audit; no MC fidelity claim extends to open answers.",
              "groups": {}}
    for group in ("random_primary", "enriched_only"):
        selected = [uid for uid in gold if items[uid]["question_type"] == "multiple-choice" and
                    (("random_primary" in sampling["reasons_private"][uid]) == (group == "random_primary"))]
        metrics = {}
        for policy in POLICIES:
            c = Counter(total=len(selected))
            for uid in selected:
                human, entry = gold[uid], items[uid]["analysis"]["policies"][policy]
                answer = entry["parsed"] if entry["route"] == "auto" else None
                judged = cache.get(uid) if args.judge and entry["route"] != "auto" else None
                if judged and judged["status"] == "success":
                    answer = judged["parsed"]
                if entry["route"] != "auto" and args.judge and (not judged or judged["status"] == "api_error"):
                    c["judge_pending"] += 1
                unique = human["answer_status"] == "unique"
                c["human_unique"] += unique
                if answer is not None:
                    faithful = unique and answer == human["human_answer"]
                    c["accepted"] += 1
                    c["faithful"] += faithful
                    c["misread"] += not faithful
                elif unique:
                    c["unextracted_unique"] += 1
            metrics[policy] = {**c, "accepted": c["accepted"], "misread": c["misread"],
                "fidelity_among_accepted": c["faithful"]/c["accepted"] if c["accepted"] else None,
                "misread_rate_wilson95": wilson(c["misread"], c["accepted"]) if group == "random_primary" else None,
                "unique_answer_recall": c["faithful"]/c["human_unique"] if c["human_unique"] else None,
                "judge_pending": c["judge_pending"]}
        report["groups"][group] = metrics
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({"adjudicated_rows": len(gold), "api_calls": 0}))


def merge_judge(args):
    rows, manifest = load_run(args.run)
    by_id = validated_judge_cache(args.run, args.judge, args.model)
    report = {"model": args.model, "source_kind": manifest["source_kind"], "analysis_id": manifest["analysis_id"],
              "judge_settings_sha256": next(iter(by_id.values()))["judge_settings_sha256"] if by_id else None,
              "policies": {}, "paired_score_comparisons": []}
    correctness = {}
    for policy in POLICIES:
        counter = Counter(total=len(rows))
        hits = {}
        subjects = {s: Counter() for s in sorted({r["subject"] for r in rows})}
        for row in rows:
            entry = row["analysis"]["policies"][policy]
            result = by_id.get(row["id"])
            hit = entry["auto_correct"] if entry["route"] == "auto" else False
            if entry["route"] != "auto":
                if result is None or result["status"] == "api_error":
                    counter["pending"] += 1
                elif result["status"] == "extraction_failure":
                    counter["extraction_failure"] += 1
                else:
                    counter["judge_success"] += 1
                    hit = result["parsed"] == (row["answer"] if row["question_type"] == "multiple-choice" else "A")
            else:
                counter["auto"] += 1
            counter["correct"] += bool(hit)
            hits[row["id"]] = bool(hit)
            subjects[row["subject"]]["total"] += 1
            subjects[row["subject"]]["correct"] += bool(hit)
        complete = counter["pending"] == 0
        report["policies"][policy] = {**counter, "pending": counter["pending"], "complete": complete,
            "score_lower_bound_pending_incorrect": counter["correct"] / len(rows),
            "accuracy": counter["correct"] / len(rows) if complete else None,
            "macro_accuracy": sum(s["correct"]/s["total"] for s in subjects.values())/len(subjects) if complete else None,
            "subjects": subjects}
        if complete:
            correctness[policy] = hits
    for a, b in itertools.combinations(correctness, 2):
        ab = sum(correctness[a][uid] and not correctness[b][uid] for uid in correctness[a])
        ba = sum(correctness[b][uid] and not correctness[a][uid] for uid in correctness[a])
        n = ab + ba
        p = min(1.0, 2 * sum(math.comb(n, k) for k in range(min(ab, ba)+1)) / 2**n) if n else 1.0
        report["paired_score_comparisons"].append({"a": a, "b": b, "a_only_correct": ab,
            "b_only_correct": ba, "mcnemar_exact_p_unadjusted": p,
            "interpretation": "Exploratory; multiple comparisons unadjusted, GT score is not extraction fidelity"})
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({"policies": len(POLICIES), "cached_judge_rows": len(by_id), "api_calls": 0}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--predictions", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--source-kind", choices=["hf-final", "legacy-tsv", "legacy-pilot", "synthetic-demo"], required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=prepare)
    p = sub.add_parser("audit-pack")
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--random-n", type=int, default=120)
    p.add_argument("--seed", type=int, default=3407)
    p.set_defaults(func=audit_pack)
    p = sub.add_parser("label-agreement")
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--rater1", type=Path, required=True)
    p.add_argument("--rater2", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=label_agreement)
    p = sub.add_parser("audit-score")
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--sampling", type=Path, required=True)
    p.add_argument("--gold", type=Path, required=True)
    p.add_argument("--judge", type=Path)
    p.add_argument("--model")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=audit_score)
    p = sub.add_parser("merge-judge")
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--judge", type=Path, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=merge_judge)
    args = parser.parse_args()
    if hasattr(args, "random_n") and args.random_n <= 0:
        parser.error("--random-n must be positive")
    if args.command == "audit-score" and bool(args.judge) != bool(args.model):
        parser.error("--judge and --model must be provided together")
    args.func(args)


if __name__ == "__main__":
    main()
