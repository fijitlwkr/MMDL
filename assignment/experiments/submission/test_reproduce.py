"""One offline integration check, plus provenance rejection on a real saved receipt."""
import argparse
import copy
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

import reproduce as r


class SubmissionReplayTest(unittest.TestCase):
    def test_offline_scores_and_corrupt_cache_rejection(self):
        root = r.ROOT
        args = argparse.Namespace(evaluator=root.parent / "raw_evaluation/evaluate.py", input=root / "input/raw.jsonl",
                                  metadata=root / "input/run_metadata.json", config=root / "input/scoring_config.yaml",
                                  judge_cache=root / "judge/gpt-4.1-mini.jsonl", comparison_cache=root / "judge/gpt-4o-mini.jsonl",
                                  expected=None)
        with tempfile.TemporaryDirectory(prefix="mmmu-replay-test-") as temporary, \
                patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
                patch("urllib.request.urlopen", side_effect=AssertionError("API forbidden")):
            args.out = Path(temporary) / "results"
            scores = r.reproduce(args)
            self.assertEqual([scores[k]["overall"]["correct"] for k in ("final", "gate_on_4_1", "gate_on_4o", "mmmu_rule")],
                             [600, 594, 567, 452])
            self.assertEqual(scores["gate_ablation"], {"routed_differently": 18, "removal_gains": 8, "removal_losses": 2})
            self.assertEqual(scores["controlled_judge_change_4_1_to_4o"],
                             {"answer_disagreements": 83, "correctness_gains": 5, "correctness_losses": 32,
                              "delta_correct": -27, "delta_percentage_points": -3.0})
            self.assertEqual((scores["automatic_count"], scores["judge_count"], scores["new_api_calls"]), (555, 345, 0))
            e = r.load_evaluator(args.evaluator)
            first = e.read_rows(args.judge_cache)[0]
            row = next(row for row in e.read_rows(args.input) if row["id"] == first["id"])
            parsers = e.load_parsers()
            item = e.derive_item(row, parsers)
            bad_cache = Path(temporary) / "tampered.jsonl"
            for field in ("request_sha256", "model", "total_tokens"):
                with self.subTest(field=field):
                    record = copy.deepcopy(first)
                    if field == "request_sha256":
                        record[field] = "0" * 64
                    elif field == "model":
                        record["response"][field] = r.COMPARISON
                    else:
                        record["response"]["usage"][field] += 1
                    e.write_rows(bad_cache, [record])
                    with self.assertRaises(ValueError):
                        r.validate_cache(e, bad_cache, [row], [item], scores["judge_settings"], parsers)


if __name__ == "__main__":
    unittest.main()
