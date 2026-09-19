"""Tests target scoring integrity, not model benchmark performance."""
import argparse
import copy
import json
import random
import tempfile
import unittest
from pathlib import Path

import lab
from parsers import analyze, marker, mmmu_mc_parse, qwen_parse, vlmeval_parse


def row(index=1, raw="Final Answer: B", finish="stop"):
    return {"id": f"validation_Accounting_{index}", "question_type": "multiple-choice",
            "question": "SYNTHETIC SOFTWARE TEST: choose a color.",
            "options": {"A": "red", "B": "blue", "C": "green", "D": "None"},
            "answer": "B", "raw_text": raw, "finish_reason": finish,
            "input_tokens": 100, "generated_tokens": 20}


class IntegrityTests(unittest.TestCase):
    def test_random_fallback_is_absent_and_rng_unchanged(self):
        state = random.getstate()
        self.assertEqual(mmmu_mc_parse("", row()["options"]), (None, True))
        self.assertEqual(random.getstate(), state)

    def test_mmmu_last_mentioned_vs_qwen_ambiguity(self):
        choices = row()["options"]
        text = "First I tried (A). I now choose (B)."
        self.assertEqual(mmmu_mc_parse(text, choices), ("B", False))
        self.assertIsNone(qwen_parse(text, choices))

    def test_substring_matching_can_misread_model_answer(self):
        # 'considered' contains the option text 'red', a real upstream behavior.
        self.assertEqual(qwen_parse("I considered (A), but I choose (B).", row()["options"]), "A")

    def test_vlmevalkit_is_a_distinct_pinned_parser(self):
        text = "The correct answer is B. I will now explain this statement in detail."
        self.assertEqual(vlmeval_parse(text, row()["options"]), "B")
        # Unlike Qwen, this pinned VLMEvalKit rule checks near-end occurrence.
        text = "B is my response and here follows a long unrelated explanation with words."
        self.assertEqual(qwen_parse(text, row()["options"]), "B")
        self.assertIsNone(vlmeval_parse(text, row()["options"]))

    def test_qwen_input_is_not_mutated(self):
        choices = {"A": "RED", "B": "BLUE"}
        before = copy.deepcopy(choices)
        self.assertEqual(qwen_parse("blue", choices), "B")
        self.assertEqual(choices, before)

    def test_marker_character_boundary_and_conflicting_markers(self):
        options = row()["options"]
        self.assertEqual(marker("Final Answer: B" + "."*100, options)["answer"], "B")
        self.assertIsNone(marker("Final Answer: B" + "."*101, options)["answer"])
        self.assertIsNone(marker("Final Answer: A. Final Answer: B.", options)["answer"])

    def test_legacy_ambiguous_answer_remains_a_documented_risk(self):
        # Preserve this bug in the legacy candidate so it is measured rather
        # than silently fixed before comparing to historical results.
        parsed = analyze(lab.normalize(row(raw="Final Answer: A or B.")))
        self.assertEqual(parsed["hybrid100"], "A")

    def test_length_gate_uses_reason_not_token_count(self):
        stopped = analyze(lab.normalize(row()))
        capped = analyze(lab.normalize(row(finish="length")))
        self.assertEqual(stopped["policies"]["hybrid100__always_judge"]["route"], "auto")
        self.assertEqual(capped["policies"]["hybrid100__always_judge"]["route"], "judge_length")
        self.assertEqual(capped["policies"]["hybrid100__marker_exception"]["route"], "auto")

    def test_open_does_not_use_mc_marker(self):
        sample = row(raw="Final Answer: A. The numerical result is 1200.")
        sample.update(question_type="open", options={}, answer="1200")
        a = analyze(lab.normalize(sample))
        self.assertIsNone(a["marker"]["answer"])
        self.assertTrue(a["policies"]["mmmu_no_random__none"]["auto_correct"])

    def test_literal_none_and_raw_preservation(self):
        original = row(raw="  B\n\n")
        normalized = lab.normalize(original)
        self.assertEqual(normalized["options"]["D"], "None")
        self.assertEqual(normalized["raw_text"], "  B\n\n")

    def test_rejects_unknown_finish_and_duplicate_and_incomplete_final(self):
        with self.assertRaises(ValueError):
            lab.normalize(row(finish="unknown"))
        r = lab.normalize(row())
        with self.assertRaises(ValueError):
            lab.validate([r, r], "synthetic-demo", {})
        with self.assertRaises(ValueError):
            lab.validate([r], "hf-final", {})

    def test_hf900_config_pins_and_cap_bounds(self):
        rows = []
        for subject in sorted(lab.SUBJECTS):
            for i in range(1, 31):
                sample = row(i)
                sample["id"] = f"validation_{subject}_{i}"
                rows.append(lab.normalize(sample))
        config = {"model_revision": lab.MODEL_REV, "dataset_revision": lab.DATA_REV,
                  "engine_seed": 3407, "sampling_seed": 3407,
                  "max_model_len": 16384, "max_new_tokens": 8192}
        lab.validate(rows, "hf-final", config)
        with self.assertRaises(ValueError):
            lab.validate(rows, "hf-final", {**config, "sampling_seed": 42})
        with self.assertRaises(ValueError):
            lab.validate(rows, "hf-final", {**config, "max_new_tokens": 10})


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        samples = [row(), row(2, "I considered (A), but I choose (B)."),
                   row(3, "Final Answer: B", "length"), row(4, ""),
                   row(5, "Final Answer: A or B.")]
        lab.write_jsonl(self.root / "raw.jsonl", samples)
        lab.write_json(self.root / "config.json", {"fixture": True})
        lab.prepare(argparse.Namespace(predictions=self.root / "raw.jsonl", config=self.root / "config.json",
                                       source_kind="synthetic-demo", out=self.run))

    def tearDown(self):
        self.temp.cleanup()

    def test_blinded_reproducible_sampling_and_refuse_overwrite(self):
        for name in ("audit1", "audit2"):
            lab.audit_pack(argparse.Namespace(run=self.run, out=self.root / name, random_n=2, seed=3407))
        a = lab.read_jsonl(self.root / "audit1/rater_1.jsonl")
        self.assertEqual(a, lab.read_jsonl(self.root / "audit2/rater_1.jsonl"))
        for r in a:
            self.assertNotIn("answer", r)
            self.assertNotIn("analysis", r)
            self.assertNotIn("finish_reason", r)
        with self.assertRaises(FileExistsError):
            lab.prepare(argparse.Namespace(predictions=self.root / "raw.jsonl", config=self.root / "config.json",
                                           source_kind="synthetic-demo", out=self.run))

    def test_partial_judge_does_not_report_final_accuracy(self):
        lab.write_jsonl(self.root / "judge.jsonl", [])
        lab.merge_judge(argparse.Namespace(run=self.run, judge=self.root / "judge.jsonl", model="fixture", out=self.root / "score.json"))
        report = json.loads((self.root / "score.json").read_text())
        self.assertIsNone(report["policies"]["hybrid100__always_judge"]["accuracy"])
        self.assertGreater(report["policies"]["hybrid100__always_judge"]["pending"], 0)

    def test_judge_cache_identity_and_random_answers_blocked(self):
        request = lab.read_jsonl(self.run / "judge_requests.jsonl")[0]
        item = {"id": request["id"], "model": "fixture", "request_sha256": request["request_sha256"],
                "judge_settings_sha256": "a"*64,
                "status": "extraction_failure", "parsed": "B", "raw_output": "Z"}
        lab.write_jsonl(self.root / "judge.jsonl", [item])
        with self.assertRaises(ValueError):
            lab.validated_judge_cache(self.run, self.root / "judge.jsonl", "fixture")
        item.update(status="success", parsed="B", raw_output="B", request_sha256="stale")
        lab.write_jsonl(self.root / "judge.jsonl", [item])
        with self.assertRaises(ValueError):
            lab.validated_judge_cache(self.run, self.root / "judge.jsonl", "fixture")

    def test_complete_judge_merge_and_subject_scores(self):
        requests = lab.read_jsonl(self.run / "judge_requests.jsonl")
        cache = [{"id": r["id"], "model": "fixture", "request_sha256": r["request_sha256"],
                  "judge_settings_sha256": "a"*64,
                  "status": "extraction_failure", "parsed": None, "raw_output": "Z"} for r in requests]
        lab.write_jsonl(self.root / "judge.jsonl", cache)
        lab.merge_judge(argparse.Namespace(run=self.run, judge=self.root / "judge.jsonl", model="fixture", out=self.root / "score.json"))
        report = json.loads((self.root / "score.json").read_text())
        self.assertTrue(all(p["complete"] for p in report["policies"].values()))
        self.assertEqual(len(report["paired_score_comparisons"]), 66)
        for result in report["policies"].values():
            self.assertEqual(result["accuracy"], result["macro_accuracy"])

    def test_detect_modified_prepared_response(self):
        rows = lab.read_jsonl(self.run / "items.jsonl")
        rows[0]["raw_text"] = "tampered"
        lab.write_jsonl(self.run / "items.jsonl", rows)
        with self.assertRaises(ValueError):
            lab.load_run(self.run)

    def test_manual_gold_and_fidelity_separate_from_gt(self):
        audit = self.root / "audit"
        lab.audit_pack(argparse.Namespace(run=self.run, out=audit, random_n=5, seed=3407))
        labels = lab.read_jsonl(audit / "rater_1.jsonl")
        for r in labels:
            index = int(r["id"].rsplit("_", 1)[1])
            r.update(answer_status="unique" if index < 4 else ("no_answer" if index == 4 else "ambiguous"),
                     human_answer="B" if index < 4 else "",
                     evidence_quote="(B)" if index == 2 else ("B" if index < 4 else ""),
                     adjudicated=True, reviewed_by="synthetic test fixture")
        lab.write_jsonl(self.root / "gold.jsonl", labels)
        lab.audit_score(argparse.Namespace(run=self.run, sampling=audit / "sampling.json", gold=self.root / "gold.jsonl",
                                          judge=None, model=None, out=self.root / "fidelity.json"))
        report = json.loads((self.root / "fidelity.json").read_text())
        self.assertEqual(report["groups"]["random_primary"]["hybrid100__none"]["misread"], 2)
        self.assertIsNone(report["groups"]["enriched_only"]["hybrid100__none"]["misread_rate_wilson95"])
        lab.label_agreement(argparse.Namespace(run=self.run, rater1=self.root / "gold.jsonl",
                                              rater2=self.root / "gold.jsonl", out=self.root / "agreement.json"))
        self.assertEqual(json.loads((self.root / "agreement.json").read_text())["agreement"], 1)


if __name__ == "__main__":
    unittest.main()
