import unittest

from focused_review import blind, cohorts


def row(uid, q='A', m='B', marker='A', finish='stop', kind='multiple-choice', route='auto'):
    return dict(id=uid, finish_reason=finish, question_type=kind, question='Example?',
                options={'A': 'one', 'B': 'two'}, raw_text='Final Answer: A', raw_sha256='hash', answer='B',
                analysis={'qwen': q, 'mmmu_no_random': m, 'marker': {'answer': marker},
                          'policies': {'hybrid100__always_judge': {'route': route}}})


class FocusedReviewTests(unittest.TestCase):
    def test_excludes_wrong_denominators(self):
        rows = [row('disagree'), row('both_failed', q=None, m=None, marker=None, route='judge_rule_failure'),
                row('qwen_only', m=None, marker=None), row('rescued', q=None),
                row('length', finish='length'), row('open', kind='open'),
                row('conflict', route='judge_conflict')]
        _, h1, h2, sample = cohorts(rows)
        self.assertEqual({r['id'] for r in h1}, {'disagree', 'conflict'})
        self.assertEqual({r['id'] for r in h2}, {'disagree', 'rescued'})
        self.assertEqual(len(sample), 2)

    def test_sampling_is_order_invariant_and_without_replacement(self):
        rows = [row(str(i)) for i in range(150)]
        a = cohorts(rows)[-1]
        b = cohorts(list(reversed(rows)))[-1]
        self.assertEqual([r['id'] for r in a], [r['id'] for r in b])
        self.assertEqual(len({r['id'] for r in a}), 100)

    def test_blind_sheet_has_no_gt_parser_or_completed_labels(self):
        r = blind(row('one'), 'analysis_hash')
        self.assertNotIn('answer', r)
        self.assertNotIn('analysis', r)
        self.assertEqual(r['human_answer'], '')
        self.assertEqual(r['answer_status'], '')
        self.assertEqual(r['raw_text'], 'Final Answer: A')
        self.assertEqual(r['analysis_id'], 'analysis_hash')


if __name__ == '__main__':
    unittest.main()
