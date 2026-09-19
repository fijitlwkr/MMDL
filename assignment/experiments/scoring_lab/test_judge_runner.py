"""Network-free tests of billing/cache integrity and the full prepare-to-merge path."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import judge_runner as runner
import lab
from test_lab import row


def response(answer='B', finish='stop'):
    return {'model': runner.MODEL, 'system_fingerprint':'mock',
            'choices':[{'message':{'content':answer}, 'finish_reason':finish}],
            'usage':{'prompt_tokens':100, 'completion_tokens':1, 'prompt_tokens_details':{'cached_tokens':0}}}


class SharedJudgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prepared, self.out = self.root/'prepared', self.root/'judge'
        samples = [row(1, finish='length'), row(2,raw='No conclusion reached.'), row(3,raw='42',finish='length'),
                   row(4,raw='Final Answer: E',finish='length'), row(5)]
        samples[2].update(question_type='open',answer='42',options={})
        samples[3]['options']['E']='purple'
        samples[3]['answer']='E'
        lab.write_jsonl(self.root/'raw.jsonl',samples)
        lab.write_json(self.root/'config.json',{'fixture':True})
        with contextlib.redirect_stdout(io.StringIO()):
            lab.prepare(argparse.Namespace(predictions=self.root/'raw.jsonl',config=self.root/'config.json',
                                            out=self.prepared,source_kind='synthetic-demo'))
        self.args = argparse.Namespace(run=self.prepared,out=self.out,policies=runner.DEFAULT_POLICIES,
                                       budget_usd=1.0,limit=0,execute=False)
        self.payloads = []

    def api(self, payload, key):
        self.assertEqual(key, 'synthetic-key')
        self.payloads.append(payload)
        return response()

    def run_judge(self, execute=False, transport=None, **updates):
        args = argparse.Namespace(**{**vars(self.args),'execute':execute,**updates})
        with patch.dict(os.environ, {'OPENAI_API_KEY':'synthetic-key'}), contextlib.redirect_stdout(io.StringIO()):
            return runner.run(args, transport or self.api)

    def test_dry_run_no_calls_and_no_completed_cache(self):
        report = self.run_judge()
        self.assertFalse(self.payloads)
        self.assertEqual(report['api_calls_this_invocation'],0)
        self.assertEqual(report['pending'],report['judge_union'])
        self.assertEqual(lab.read_jsonl(self.out/'judge_results.jsonl'),[])

    def test_three_parsers_share_union_once_and_resume_without_key(self):
        report = self.run_judge(True)
        self.assertEqual(len(self.payloads),report['judge_union'])
        self.assertLess(report['judge_union'],sum(s['required'] for s in report['policy_costs'].values()))
        with patch.dict(os.environ,{'OPENAI_API_KEY':''}),contextlib.redirect_stdout(io.StringIO()):
            again = runner.run(argparse.Namespace(**{**vars(self.args),'execute':True}),self.api)
        self.assertEqual(again['api_calls_this_invocation'],0)
        self.assertEqual(len(self.payloads),report['judge_union'])
        for p in self.payloads:
            self.assertEqual((p['model'],p['temperature'],p['top_p'],p['seed'],p['max_tokens']),
                             (runner.MODEL,0,1,3407,8))

    def test_limit_then_resume_no_rebilling(self):
        a=self.run_judge(True,limit=1)
        self.assertEqual(a['api_calls_this_invocation'],1)
        self.assertGreater(a['pending'],0)
        b=self.run_judge(True)
        self.assertEqual(len(self.payloads),a['judge_union'])
        self.assertEqual(b['pending'],0)

    def test_adding_policy_reuses_same_settings_cache(self):
        self.run_judge(True)
        before=len(self.payloads)
        r=self.run_judge(True,policies=runner.DEFAULT_POLICIES+['hybrid100__always_judge'])
        self.assertEqual(r['api_calls_this_invocation'],len(self.payloads)-before)
        self.assertEqual(r['pending'],0)

    def test_budget_guard_stops_before_request(self):
        r=self.run_judge(True,budget_usd=1e-8)
        self.assertEqual(r['stop_reason'],'budget')
        self.assertFalse(self.payloads)
        self.assertEqual(r['pending'],r['judge_union'])

    def test_bad_budget_rejected(self):
        for budget in [0,-1,float('nan'),float('inf')]:
            with self.subTest(budget=budget),self.assertRaises(ValueError):
                self.run_judge(True,budget_usd=budget)
        self.assertFalse(self.payloads)

    def test_z_is_terminal_and_never_random_or_retried(self):
        def api(payload,key):
            self.payloads.append(payload)
            return response('Z')
        r=self.run_judge(True,transport=api)
        self.assertEqual(r['extraction_failure'],r['judge_union'])
        self.assertEqual(r['pending'],0)
        self.run_judge(True,transport=api)
        self.assertEqual(len(self.payloads),r['judge_union'])
        self.assertTrue(all(x['parsed'] is None for x in lab.read_jsonl(self.out/'judge_results.jsonl')))

    def test_error_is_pending_halts_and_never_leaks_secret(self):
        def api(payload,key):
            self.payloads.append(payload)
            raise RuntimeError('synthetic-key should never be logged')
        r=self.run_judge(True,transport=api)
        self.assertEqual(len(self.payloads),1)
        self.assertEqual(r['pending'],r['judge_union'])
        self.assertEqual(r['api_error'],1)
        self.assertGreater(r['uncertain_reserved_cost_usd'],0)
        for path in self.out.iterdir():
            self.assertNotIn('synthetic-key',path.read_text())
        with self.assertRaisesRegex(ValueError,'requires review'):
            self.run_judge(True,transport=api)
        self.assertEqual(len(self.payloads),1)

    def test_interrupted_request_is_not_automatically_repeated(self):
        def api(payload,key):
            self.payloads.append(payload)
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_judge(True,transport=api)
        self.assertFalse((self.out/'runner.lock').exists())
        with self.assertRaisesRegex(ValueError,'requires review'):
            self.run_judge(True)
        self.assertEqual(len(self.payloads),1)

    def test_changed_request_or_membership_rejected_before_call(self):
        path=self.prepared/'judge_requests.jsonl'
        req=lab.read_jsonl(path)
        req[0]['needed_by']=[]
        lab.write_jsonl(path,req)
        with self.assertRaisesRegex(ValueError,'membership'):
            self.run_judge(True)
        self.assertFalse(self.payloads)

    def test_other_model_cache_and_changed_cost_rejected(self):
        self.run_judge(True)
        path=self.out/'judge_results.jsonl'
        records=lab.read_jsonl(path)
        records[0]['model']='gpt-3.5-turbo-0125'
        lab.write_jsonl(path,records)
        with self.assertRaisesRegex(ValueError,'different judge model'):
            self.run_judge(True)
        records[0]['model']=runner.MODEL
        records[0]['estimated_cost_usd_uncached']=0
        lab.write_jsonl(path,records)
        with self.assertRaisesRegex(ValueError,'modified'):
            self.run_judge(True)

    def test_lock_prevents_concurrent_request(self):
        self.out.mkdir()
        (self.out/'runner.lock').write_text('other process')
        with self.assertRaisesRegex(ValueError,'lock exists'):
            self.run_judge(True)
        self.assertFalse(self.payloads)

    def test_response_model_usage_and_truncation(self):
        r=runner.parse_response(response(finish='length'),{'A':'a','B':'b'})
        self.assertEqual(r['status'],'extraction_failure')
        self.assertIsNone(r['parsed'])
        for update in [{'model':'different'},{'usage':{}},{'usage':{'prompt_tokens':-1,'completion_tokens':1}}]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                runner.parse_response({**response(),**update},{'A':'a','B':'b'})

    def test_prepare_execute_merge_and_diagnostics(self):
        r=self.run_judge(True)
        self.assertEqual(r['ad_prompt_exposure']['mc_with_options_outside_ad'],1)
        self.assertEqual(r['ad_prompt_exposure']['judge_union_with_options_outside_ad'],1)
        mc=r['length_diagnostics']['multiple-choice']
        self.assertEqual(mc['selected'],2)
        self.assertAlmostEqual(mc['uniform_guess_reference_same_valid_cohort'],(.25+.2)/2)
        self.assertEqual(r['length_diagnostics']['open']['selected'],1)
        with contextlib.redirect_stdout(io.StringIO()):
            lab.merge_judge(argparse.Namespace(run=self.prepared,judge=self.out/'judge_results.jsonl',
                                               model=runner.MODEL,out=self.root/'scores.json'))
        scores=json.loads((self.root/'scores.json').read_text())
        self.assertEqual(scores['source_kind'],'synthetic-demo')
        for name in runner.DEFAULT_POLICIES:
            self.assertTrue(scores['policies'][name]['complete'])
            self.assertIsNotNone(scores['policies'][name]['accuracy'])


if __name__=='__main__':
    unittest.main()
