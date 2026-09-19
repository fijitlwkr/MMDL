"""Legacy metadata may be unknown without weakening final HF input checks."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest

import lab
from legacy_adapter import convert
from test_lab import row


class LegacyInputTests(unittest.TestCase):
    def test_incomplete_pilot_is_never_a_full_legacy_or_hf_run(self):
        r = lab.normalize(row())
        lab.validate([r], 'legacy-pilot', {})
        for kind in ['legacy-tsv', 'hf-final']:
            with self.assertRaises(ValueError):
                lab.validate([r], kind, {})
        bad = row()
        bad['answer'] = 'E'
        with self.assertRaises(ValueError):
            lab.normalize(bad, allow_missing_input_tokens=True)

    def test_adapter_preserves_legacy_content_and_literal_none(self):
        source = {'annotation': {'id': 'validation_Accounting_1',
                  'question_type': 'multiple-choice', 'question': 'Original TSV question',
                  'A': 'None', 'B': 'blue', 'C': float('nan'), 'D': None, 'answer': 'A'},
                  'question_id': 733, 'result': {'gen': 'A', 'gen_raw': '  Final Answer: A\n'},
                  'finish_reason': 'length', 'generated_tokens': 9048}
        r = convert(source)
        self.assertEqual(r['options'], {'A': 'None', 'B': 'blue'})
        self.assertEqual(r['answer'], 'A')
        self.assertEqual(r['question'], 'Original TSV question')
        self.assertEqual(r['raw_text'], source['result']['gen_raw'])
        self.assertEqual(r['finish_reason'], 'length')
        self.assertIsNone(r['input_tokens'])

    def test_missing_is_distinct_from_invalid_or_invented(self):
        sample = row()
        del sample['input_tokens']
        with self.assertRaises(ValueError):
            lab.normalize(sample)
        self.assertIsNone(lab.normalize(sample, allow_missing_input_tokens=True)['input_tokens'])
        sample['input_tokens'] = -1
        with self.assertRaises(ValueError):
            lab.normalize(sample, allow_missing_input_tokens=True)
        sample['input_tokens'] = None
        del sample['generated_tokens']
        with self.assertRaises(ValueError):
            lab.normalize(sample, allow_missing_input_tokens=True)

    def test_prepare_legacy900_preserves_unknown_but_hf_rejects_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for subject in sorted(lab.SUBJECTS):
                for index in range(1, 31):
                    sample = row(index)
                    sample['id'] = f'validation_{subject}_{index}'
                    del sample['input_tokens']
                    rows.append(sample)
            lab.write_jsonl(root/'raw.jsonl', rows)
            lab.write_json(root/'config.json', {})
            args = argparse.Namespace(predictions=root/'raw.jsonl', config=root/'config.json',
                                      source_kind='legacy-tsv', out=root/'legacy')
            lab.prepare(args)
            prepared, manifest = lab.load_run(args.out)
            self.assertEqual(manifest['source_kind'], 'legacy-tsv')
            self.assertEqual(len(prepared), 900)
            self.assertTrue(all(r['input_tokens'] is None for r in prepared))
            args.source_kind, args.out = 'hf-final', root/'final'
            with self.assertRaises(ValueError):
                lab.prepare(args)


if __name__ == '__main__':
    unittest.main()
