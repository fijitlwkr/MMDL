"""Offline checks: key cleanup on API failure and operational pilot checks."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import judge_runner as runner


class JudgeRunnerTest(unittest.TestCase):
    def test_failure_keeps_pending_and_never_logs_key(self):
        sentinel = 'UNIT_TEST_ONLY_NOT_A_REAL_API_KEY'
        calls = []

        def fake_child(args, **kwargs):
            calls.append(args)
            if 'run' in args:
                self.assertEqual(os.environ['OPENAI_API_KEY'], sentinel)
                return subprocess.CompletedProcess(args, 1)
            self.assertNotIn('OPENAI_API_KEY', os.environ)
            return subprocess.CompletedProcess(args, 0)

        with TemporaryDirectory(dir=runner.ROOT) as directory:
            root = Path(directory)
            self.assertEqual(root.resolve().parent, runner.ROOT.resolve())
            for name in runner.EXPECTED_RAW:
                (root / name).mkdir()
                (root / name / 'summary.json').write_text(json.dumps({
                    'response_count': 0, 'judge_count': 5,
                    'overall': {'pending': 5, 'accuracy': None}}))
            output = io.StringIO()
            with patch.object(runner, 'verify'), patch.object(runner, 'estimate_cost', return_value=0.1), \
                    patch.object(runner.getpass, 'getpass', return_value=sentinel) as key_input, \
                    patch.object(runner.subprocess, 'run', side_effect=fake_child), redirect_stdout(output):
                self.assertEqual(runner.workflow(root), 1)
            key_input.assert_called_once()
            self.assertNotIn('OPENAI_API_KEY', os.environ)
            self.assertNotIn(sentinel, output.getvalue())
            self.assertTrue(all(sentinel not in str(args) for args in calls))
            for file in (root / 'judge_launcher').iterdir():
                self.assertNotIn(sentinel, file.read_text())
            state = runner.read_json(root / 'judge_launcher/status.json')
            self.assertEqual(state['state'], 'failed')
            self.assertEqual(state['pending'], {'E1': 5, 'E2': 5})

    def test_pilot_preserves_completed_v2_failures_but_checks_model(self):
        with TemporaryDirectory(dir=runner.ROOT) as directory:
            folder = Path(directory)
            self.assertEqual(folder.resolve().parent, runner.ROOT.resolve())
            (folder / 'summary.json').write_text(json.dumps({'judge_count': 1, 'response_count': 1}))
            saved = {'response': {'model': runner.SETTINGS['model'], 'choices': [
                {'finish_reason': 'stop', 'message': {'content': 'Z'}}]}}
            path = folder / 'responses.jsonl'
            path.write_text(json.dumps(saved) + '\n')
            runner.pilot_check(folder)
            saved['response']['choices'][0]['finish_reason'] = 'length'
            path.write_text(json.dumps(saved) + '\n')
            runner.pilot_check(folder)
            saved['response']['model'] = 'wrong-snapshot'
            path.write_text(json.dumps(saved) + '\n')
            with self.assertRaises(AssertionError):
                runner.pilot_check(folder)


if __name__ == '__main__':
    unittest.main()
