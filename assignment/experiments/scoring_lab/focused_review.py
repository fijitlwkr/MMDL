#!/usr/bin/env python3
"""Prepare H1/H2 review cohorts. No API calls, automatic gold labels or rule changes."""
import argparse
import random
from pathlib import Path

import lab


def cohorts(rows, sample_n=100, seed=3407):
    stop = sorted((r for r in rows if r['finish_reason'] == 'stop'
                   and r['question_type'] == 'multiple-choice'), key=lambda r: r['id'])
    h1 = [r for r in stop if r['analysis']['qwen'] is not None
          and r['analysis']['mmmu_no_random'] is not None
          and r['analysis']['qwen'] != r['analysis']['mmmu_no_random']]
    h2 = [r for r in stop if r['analysis']['marker']['answer'] is not None
          and r['analysis']['policies']['hybrid100__always_judge']['route'] == 'auto']
    sample = random.Random(seed).sample(h2, min(sample_n, len(h2)))
    return stop, h1, h2, sample


def blind(row, analysis_id):
    result = {k: row[k] for k in ('id', 'raw_sha256', 'question_type', 'question', 'options', 'raw_text')}
    result.update(analysis_id=analysis_id, answer_status='', human_answer='', evidence_quote='', notes='')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--sample-n', type=int, default=100)
    p.add_argument('--seed', type=int, default=3407)
    args = p.parse_args()
    if args.sample_n < 1:
        p.error('--sample-n must be positive')
    rows, manifest = lab.load_run(args.run)
    stop, h1, h2, sample = cohorts(rows, args.sample_n, args.seed)
    ids = lambda group: [r['id'] for r in group]
    selected_ids = set(ids(h1)) | set(ids(sample))
    selected = [r for r in stop if r['id'] in selected_ids]
    random.Random(args.seed).shuffle(selected)
    args.out.mkdir(parents=True, exist_ok=False)
    public = [blind(r, manifest['analysis_id']) for r in selected]
    for name in ('rater_1.jsonl', 'rater_2.jsonl'):
        lab.write_jsonl(args.out / name, public)
    same_qwen = lambda group: sum(r['analysis']['qwen'] is not None for r in group)
    report = {
        'analysis_id': manifest['analysis_id'], 'source_kind': manifest['source_kind'],
        'review_script_sha256': lab.file_hash(Path(__file__)),
        'seed': args.seed, 'sampling': 'Simple random sample without replacement from sorted H2 IDs',
        'population_total': len(rows), 'stop_mc': len(stop),
        'h1_joint_disagreements': len(h1), 'h2_population': len(h2),
        'h2_qwen_already_success': same_qwen(h2), 'h2_qwen_rescued': len(h2)-same_qwen(h2),
        'h2_sample_n': len(sample), 'h2_sample_qwen_rescued': len(sample)-same_qwen(sample),
        'h1_h2_sample_overlap': len(set(ids(h1)) & set(ids(sample))),
        'unique_review_rows': len(selected),
        'h1_ids_private': ids(h1), 'h2_population_ids_private': ids(h2), 'h2_sample_ids_private': ids(sample),
        'qwen_only_success_ids_private': ids([r for r in stop if r['analysis']['qwen'] is not None
                                             and r['analysis']['mmmu_no_random'] is None]),
        'mmmu_only_success_ids_private': ids([r for r in stop if r['analysis']['qwen'] is None
                                             and r['analysis']['mmmu_no_random'] is not None]),
        'qwen_marker_conflict_ids_private': ids([r for r in stop if r['analysis']['qwen_marker_conflict']]),
        'status': 'Blank human labels; exploratory pilot, no extraction-fidelity conclusion',
        'aggregate': 'H1 and H2 separately; do not pool enriched H1 cases into H2 random-sample accuracy',
        'api_calls': 0,
    }
    lab.write_json(args.out / 'selection_private.json', report)
    lab.write_jsonl(args.out / 'h2_tail_screen_private.jsonl', [
        {'id': r['id'], 'raw_sha256': r['raw_sha256'], 'marker': r['analysis']['marker'],
         'qwen': r['analysis']['qwen'], 'tail_300': r['raw_text'][-300:],
         'note': 'Excerpt screen only; full raw required for final human label'} for r in h2])
    instructions = '''# Parser extraction review (H1/H2)

Give each rater only their rater_N.jsonl and these instructions. Keep private files hidden.
The files contain the question, choices and FULL raw response. They omit GT and parser outputs.
Read the whole response and record what the model ultimately answered, even if factually wrong.
Use answer_status: unique / ambiguous / no_answer. For unique, record a valid option letter
and an exact evidence_quote from the response. For the other statuses leave human_answer empty.
Clear final revision overrides an earlier tentative answer; unresolved conflicting conclusions
are ambiguous. Mentioning an option during elimination is not choosing that option.
Do not solve the question yourself, infer an unstated answer, or use GT to repair the response.
Do not use AI-generated labels as human gold. Two raters work independently, then adjudicate.
This pack excludes length and open answers. AI Judge accuracy review is out of scope.
H1 is enriched disagreements, not a representative sample of all extracted answers.
H2 is a random sample of marker-accepted stop MC responses; report separately from H1.
The legacy pilot cannot certify the final pinned-HF baseline or a 99% population guarantee.
Run lab.py label-agreement to compare completed rater files. Do not pass this selection file
to the old audit-score command: its random_primary/enriched schema is a different experiment.
'''
    (args.out / 'LABELING.md').write_text(instructions, encoding='utf-8')
    import json
    print(json.dumps({k: v for k, v in report.items() if not k.endswith('_private')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
