"""Reproduce M0 and existing seed-only runs offline, emitting summaries only."""
import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from aggregate import (HERE, MARKERS, M0_SHA, SCORER, compare, paired, raw_rows,
                       require, rule_scores, score_rows, summary, write_json)
from verify_code import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--m0-raw", required=True, type=Path)
    parser.add_argument("--m0-scores", required=True, type=Path)
    parser.add_argument("--seed-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    verify()
    args.out.mkdir(parents=True, exist_ok=False)
    rows, digest = raw_rows(args.m0_raw)
    require(digest == M0_SHA, "M0 raw must have the frozen ef23f0c4 hash")
    baseline_manifest, scored = score_rows(args.m0_scores, rows, digest)
    diagnostic, rules = rule_scores(rows)
    cached = SCORER.read_rows(args.m0_scores / "mmmu_results.jsonl")
    require(all(rules[r["id"]]["final_correct"] == r["final_correct"] for r in cached),
            "recomputed no-Judge scores differ from the existing v2 diagnostic")
    actual = summary(rows, digest, scored, diagnostic)
    ids = sorted(r["id"] for r in rows if r["finish_reason"] == "length")
    require(len(ids) == 128, "M0 length count differs from 128")
    id_file = HERE / "m0_length_ids.txt"
    text = "\n".join(ids) + "\n"
    if id_file.exists():
        require(id_file.read_text(encoding="utf-8") == text, "frozen M0 ID list changed")
    else:
        id_file.write_text(text, encoding="utf-8")
    actual["length_ids_sha256"] = hashlib.sha256(id_file.read_bytes()).hexdigest()
    expected = {"v2_correct": 600, "mc_correct": 560, "mc_total": 847, "open_correct": 40,
                "open_total": 53, "auto": 555, "judge": 345, "extraction_failures": 36,
                "length": 128, "length_correct_v2": 46, "direction_overuse": 217}
    groups = actual["v2"]
    measured = {"v2_correct": groups["overall"]["correct"],
                "mc_correct": groups["by_type"]["multiple-choice"]["correct"],
                "mc_total": groups["by_type"]["multiple-choice"]["total"],
                "open_correct": groups["by_type"]["open"]["correct"],
                "open_total": groups["by_type"]["open"]["total"],
                "auto": actual["processing_routes"].get("auto", 0),
                "judge": sum(v for k, v in actual["processing_routes"].items() if k.startswith("judge_")),
                "extraction_failures": groups["overall"]["extraction_failures"],
                "length": actual["length"]["count"], "length_correct_v2": groups["by_finish"]["length"]["correct"],
                "direction_overuse": actual["direction_overuse"]["count"]}
    actual["reproduction"] = {k: {"expected": v, "measured": measured[k], "match": measured[k] == v}
                              for k, v in expected.items()}
    actual["marker_pattern"] = MARKERS.pattern
    write_json(args.out / "m0_summary.json", actual)

    base = {r["id"]: r for r in rows}
    candidates = []
    expected_gains = {"seed_42": 10, "seed_1234": 8, "seed_2026": 5, "rep_draft": 12, "rep_new_output": 14}
    for arm, expected_gain in expected_gains.items():
        folder = args.seed_root / arm
        source = folder / "item_results.jsonl"
        items = SCORER.read_rows(source)
        SCORER.unique(items, arm)
        by_id = {r["id"]: r for r in items}
        require(set(by_id) == set(scored), "seed score IDs differ")
        for row in items:
            require(type(row["final_correct"]) is bool, "incomplete seed score")
            require(row["subject"] == base[row["id"]]["subject"] and
                    row["question_type"] == base[row["id"]]["question_type"], "seed score identity differs")
        manifest_path = folder / "scoring_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(manifest["policy_id"] == SCORER.POLICY and
                manifest["judge_settings"] == baseline_manifest["judge_settings"], "seed scoring policy differs")
        result = {"arm": arm, "item_results_path": str(source),
                  "item_results_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                  "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                  "scored_raw_sha256": manifest["source_sha256"], "fixed_128_v2": paired(scored, by_id, ids),
                  "expected_net_gain": expected_gain,
                  "matches_expected": paired(scored, by_id, ids)["net_gain"] == expected_gain}
        if not arm.startswith("seed_"):
            result["run_kind"] = "same sampling seed, different host; existing compact v2 results"
            candidates.append(result)
            continue
        seed = int(arm.split("_")[1])
        path = folder / "raw.jsonl.gz"
        other, other_sha = raw_rows(path)
        metadata = json.loads((folder / "run_metadata.json").read_text(encoding="utf-8"))
        diff = json.loads((folder / "config_used.diff.json").read_text(encoding="utf-8"))
        require(metadata["run"]["raw_file"]["sha256"] == other_sha, "seed raw hash mismatch")
        require(diff["changed"] == {"sampling.seed": [3407, seed]}, "seed config changes differ")
        require(metadata["generation"]["seed"] == {"sampling_params_seed": seed, "engine_seed": 3407},
                "seed metadata differs")
        require(metadata["model"]["revision"] == "ebb281ec70b05090aa6165b016eac8ec08e71b17", "model revision differs")
        for r in other:
            for field in ("subject", "question_type", "gold", "options", "image_indices", "prompt", "num_prompt_tokens"):
                require(r[field] == base[r["id"]][field], "seed inputs differ: " + field)
        ds, rs = rule_scores(other)
        require(manifest["source_sha256"] == other_sha, "compact scores refer to another raw")
        result.update({"sampling_seed": seed, "engine_seed": 3407, "raw_path": str(path),
                       "raw_sha256": other_sha, "changed_settings": diff["changed"],
                       "model_revision": metadata["model"]["revision"],
                       "generation_seconds": metadata["run"]["duration_seconds"],
                       "total_no_judge_correct": ds["overall"]["correct"],
                       "reference_128_no_judge": paired(rules, rs, ids)})
        candidates.append(result)
    write_json(args.out / "k0_reproduction.json",
               {"runs": candidates, "k0_finalized": False,
                "all_match_expected": all(c["matches_expected"] for c in candidates),
                "primary_scoring": SCORER.POLICY, "api_calls": 0})
    control = compare(args.m0_raw, args.m0_scores, args.m0_raw, args.m0_scores, id_file, 0)
    require(control["primary_128_v2"]["net_gain"] == 0, "self primary net_gain")
    require(control["reference_128_no_judge"]["net_gain"] == 0, "self reference net_gain")
    require(control["safety_900_v2"]["accuracy_delta_pp"] == 0, "self accuracy delta")
    require(all(x["delta_pp"] == 0 for x in control["mechanism"].values()), "self mechanism delta")
    control["k0_note"] = "0 is an explicit self-check argument only; k0 remains undecided"
    write_json(args.out / "m0_vs_m0.json", control)
    seed42 = args.seed_root / "seed_42"
    comparison = compare(args.m0_raw, args.m0_scores, seed42 / "raw.jsonl.gz", seed42, id_file, 0)
    require(comparison["primary_128_v2"]["net_gain"] == 10, "M0 vs seed42 primary net_gain")
    comparison["k0_note"] = control["k0_note"]
    write_json(args.out / "m0_vs_seed42.json", comparison)
    print("M0", measured, "no-Judge", diagnostic["overall"]["correct"])
    print("v2 net gains", [(x["arm"], x["fixed_128_v2"]["net_gain"]) for x in candidates])
    print("M0 vs M0: primary gain=0, v2 gain=0, accuracy delta=0, mechanism deltas=0")
    print("M0 vs seed42: primary v2 net_gain=+10")


if __name__ == "__main__":
    # This preparation is confined to local reads and fresh summary writes.
    with patch("socket.socket.connect", side_effect=RuntimeError("network disabled during preparation")):
        main()
