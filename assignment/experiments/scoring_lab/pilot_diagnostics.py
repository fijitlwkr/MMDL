#!/usr/bin/env python3
"""Descriptive parser diagnostics; no calls or human-faithfulness claims."""
import argparse
import itertools
from pathlib import Path
from collections import Counter

import lab
from parsers import PRIMARY_PARSERS


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    rows, manifest = lab.load_run(args.run)
    stop_mc = [r for r in rows if r['finish_reason'] == 'stop' and r['question_type'] == 'multiple-choice']
    report = {'source_kind': manifest['source_kind'], 'analysis_id': manifest['analysis_id'],
              'total': len(rows), 'question_types': dict(Counter(r['question_type'] for r in rows)),
              'finish_reasons': dict(Counter(r['finish_reason'] for r in rows)),
              'stop_mc': len(stop_mc), 'pairs': [], 'length_rules': {}}
    for a, b in itertools.combinations(PRIMARY_PARSERS, 2):
        both = [r for r in stop_mc if r['analysis'][a] is not None and r['analysis'][b] is not None]
        same = sum(r['analysis'][a] == r['analysis'][b] for r in both)
        report['pairs'].append({
            'a': a, 'b': b, 'joint_success': len(both), 'same': same, 'different': len(both)-same,
            'agreement_among_joint_success': same/len(both) if both else None,
            'a_only_success': sum(r['analysis'][a] is not None and r['analysis'][b] is None for r in stop_mc),
            'b_only_success': sum(r['analysis'][a] is None and r['analysis'][b] is not None for r in stop_mc),
            'both_failed': sum(r['analysis'][a] is None and r['analysis'][b] is None for r in stop_mc),
        })
    for parser in PRIMARY_PARSERS:
        report['length_rules'][parser] = {
            qt: lab.summarize([r for r in rows if r['finish_reason'] == 'length' and r['question_type'] == qt],
                              parser+'__none') for qt in ['multiple-choice', 'open']}
    joint_different = [r for r in stop_mc if r['analysis']['qwen'] is not None
                       and r['analysis']['mmmu_no_random'] is not None
                       and r['analysis']['qwen'] != r['analysis']['mmmu_no_random']]
    report['qwen_mmmu_joint_disagreement_ids'] = [r['id'] for r in joint_different]
    report['note'] = 'No human labels. Parser agreement and GT accuracy do not establish extraction faithfulness.'
    args.out.mkdir(parents=True, exist_ok=False)
    lab.write_json(args.out/'diagnostics.json', report)
    blind = []
    for r in joint_different:
        item = {k: r[k] for k in ['id', 'question', 'options', 'raw_text']}
        item.update(answer_status='', human_answer='', evidence_quote='', notes='')
        blind.append(item)
    lab.write_jsonl(args.out/'h1_joint_disagreements_blind.jsonl', blind)
    print({k: report[k] for k in ['total', 'stop_mc', 'pairs']})


if __name__ == '__main__':
    main()
