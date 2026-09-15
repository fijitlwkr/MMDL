"""CPU regression tests for data contracts, scoring, and the inference adapter."""
import copy
import json
import os
import random
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ROOT, SUBJECTS, read_rows, validate, full_validation, write_rows
from evaluate_baseline import evaluate
from compare_scoring_pipelines import compare
from run_inference import import_qwen, prompt_text, generate
from build_stress_dataset import select_stress
from mc_parsers import MMMUParser, parse_vlmevalkit
from vendor import mmmu_eval

def example(uid='validation_Accounting_1', kind='multiple-choice', prediction='(B)'):
    return {'uid': uid, 'subject': 'Accounting', 'split': 'validation', 'question': 'Which color?',
            'question_type': kind, 'options': {'A': 'red', 'B': 'blue'} if kind == 'multiple-choice' else {},
            'answer': 'B' if kind == 'multiple-choice' else '1200', 'images': [], 'prediction': prediction}

class PipelineTests(unittest.TestCase):
    def test_duplicate_and_invalid_gold_rejected(self):
        with self.assertRaises(ValueError):
            validate([example(), example()])
        bad = example(); bad['answer'] = 'D'
        with self.assertRaises(ValueError):
            validate([bad])

    def test_empty_prediction_valid_and_seeded_fallback(self):
        row = example(prediction='')
        validate([row], predictions=True)
        first = evaluate([row], 12)
        self.assertEqual(first, evaluate([row], 12))
        self.assertEqual(first['random_fallback_uids'], [row['uid']])

    def test_full_coverage_requires_every_subject(self):
        rows = []
        for subject in SUBJECTS:
            for n in range(30):
                rows.append({**example(f'validation_{subject}_{n}'), 'subject': subject})
        self.assertTrue(full_validation(rows))
        self.assertFalse(full_validation(rows[:-1]))
        self.assertFalse(full_validation([{**r, 'split': 'test'} for r in rows]))

    def test_official_parser_matches_upstream_including_random(self):
        source = mmmu_eval.parse_multi_choice_response
        reference = types.FunctionType(source.__code__, {**source.__globals__, 'random': random.Random(19)})
        adapter = MMMUParser(19)
        choices = {'A': 'red', 'B': 'blue'}
        for text in ['(A)', 'A or B', 'No answer found', '', 'The described color is clearly blue here.'] * 4:
            self.assertEqual(adapter.parse(text, choices)['parsed'], reference(text, list(choices), choices))

    def test_vlmevalkit_does_not_mutate_choices_or_environment(self):
        choices = {'A': 'Red', 'B': 'Blue'}
        with patch.dict(os.environ, {'VERBOSE': '1'}):
            result = parse_vlmevalkit('(B)', choices)
            self.assertEqual(os.environ['VERBOSE'], '1')
        self.assertEqual(choices['A'], 'Red')
        self.assertEqual(result['parsed'], 'B')

    def test_open_and_mc_comparison_have_different_semantics(self):
        row = example(kind='open', prediction='The answer is 1200.')
        official = evaluate([row])
        comparison = compare([row])
        self.assertEqual(official['correct'], 1)
        self.assertEqual(comparison['pipelines']['vlmevalkit']['correct'], 1)
        # Open numeric aliases are normalized only in the native open pipeline.
        row['answer'] = ['1,200', '1200.00']
        self.assertEqual(evaluate([row])['correct'], 1)
        self.assertEqual(compare([row])['pipelines']['vlmevalkit']['correct'], 0)
        self.assertNotIn('1200.00', prompt_text(row))

    def test_stress_coverage_and_no_duplicate_ids(self):
        rows = [example(), example('validation_Accounting_2', kind='open')]
        rows[0]['images'] = ['one.png', 'two.png']
        result = select_stress(rows, 1)
        self.assertEqual(len({r['uid'] for r in result}), len(result))
        self.assertEqual({tag for r in result for tag in r['stress_tags']}, {'long_input', 'multi_image', 'open'})
        with self.assertRaises(ValueError):
            select_stress([example()], 1)

    def test_import_missing_gold_option_is_flagged_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'old.jsonl'
            p.write_text(json.dumps({'annotation': {'id': 'validation_Accounting_1', 'l2-category': 'Accounting',
                'split': 'validation', 'question': 'Q', 'question_type': 'multiple-choice', 'A': 1, 'B': 2,
                'D': float('nan'), 'answer': 'D'}, 'result': {'gen': '(D)', 'gen_raw': '(D)'}, 'messages': []})+'\n')
            rows = import_qwen(p)
            self.assertNotIn('D', rows[0]['options'])
            self.assertEqual(rows[0]['options']['A'], '1')
            self.assertEqual(rows[0]['data_issue']['missing_labels'], ['D'])
            self.assertEqual(evaluate(rows)['correct'], 0)
            self.assertEqual(compare(rows)['pipelines']['mmmu']['correct'], 0)

    def test_cli_roundtrip_and_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'predictions.jsonl'; out = Path(tmp)/'score.json'; table = Path(tmp)/'table.md'
            write_rows(path, [example(), example('validation_Accounting_2', 'open', '1200')])
            command = [sys.executable, str(ROOT/'evaluate_baseline.py'), '--input', str(path), '--output', str(out)]
            rejected = subprocess.run(command, capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            subprocess.run(command+['--allow-partial'], check=True, capture_output=True)
            original = out.read_bytes()
            self.assertEqual(json.loads(original)['correct'], 2)
            self.assertNotEqual(subprocess.run(command+['--allow-partial'], capture_output=True).returncode, 0)
            self.assertEqual(out.read_bytes(), original)
            subprocess.run([sys.executable, str(ROOT/'compare_scoring_pipelines.py'), '--input', str(path),
                            '--output', str(Path(tmp)/'compare.json'), '--table', str(table), '--allow-partial'],
                           check=True, capture_output=True)
            self.assertIn('Overall (macro)', table.read_text())

    def test_malformed_jsonl_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'bad.jsonl'; path.write_text('{"uid":')
            with self.assertRaises(json.JSONDecodeError):
                read_rows(path)

    def test_vllm_adapter_preserves_metadata_and_excludes_gold(self):
        seen = []
        class Processor:
            image_processor = types.SimpleNamespace(patch_size=16)
            @classmethod
            def from_pretrained(cls, model, **kwargs):
                seen.append(('processor', kwargs)); return cls()
            def apply_chat_template(self, messages, **kwargs):
                self_test.assertNotIn('SECRET_GOLD', str(messages))
                return 'formatted prompt'
        class LLM:
            def __init__(self, **kwargs): seen.append(('llm', kwargs))
            def generate(self, requests, sampling_params):
                return [types.SimpleNamespace(prompt_token_ids=[1,2], outputs=[types.SimpleNamespace(
                    text='<think>x</think> B', finish_reason='stop', stop_reason=None, token_ids=[1,2,3])]) for _ in requests]
        class Monitor:
            peak = {}; samples = 0
            def __enter__(self): return self
            def __exit__(self, *args): pass
        self_test = self
        mocks = {'transformers': types.SimpleNamespace(AutoProcessor=Processor),
                 'qwen_vl_utils': types.SimpleNamespace(process_vision_info=lambda *a, **k: (None,None,{})),
                 'vllm': types.SimpleNamespace(LLM=LLM, SamplingParams=lambda **k: k)}
        args = types.SimpleNamespace(model='Qwen/test', model_revision='fixed-sha', input='/tmp/data.jsonl',
            max_model_len=9048, max_new_tokens=2048, temperature=.7, top_p=.8, top_k=20, repetition_penalty=1.,
            presence_penalty=1.5, seed=42, min_pixels=100, max_pixels=1000, batch_size=1, prompt_style='official',
            dtype='bfloat16', gpu_memory_utilization=.9, tensor_parallel_size=1, max_images=7)
        row = example(kind='open'); row['answer'] = 'SECRET_GOLD'
        with patch.dict(sys.modules, mocks), patch('run_inference.GPUMonitor', Monitor), patch('importlib.metadata.version', return_value='test'):
            rows, meta = generate(args, [row])
        self.assertEqual(rows[0]['prediction'], 'B')
        self.assertEqual(rows[0]['generated_tokens'], 3)
        self.assertEqual(rows[0]['finish_reason'], 'stop')
        self.assertEqual(meta['settings']['revision_applied'], 'fixed-sha')
        self.assertEqual(seen[1][1]['revision'], 'fixed-sha')

if __name__ == '__main__':
    unittest.main()
