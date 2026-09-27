"""Score MC and open responses using the pinned official MMMU functions."""
import argparse
import json
from common import ROOT, read_rows, full_validation, input_metadata, aggregate, write_json
from mc_parsers import MMMUParser, parse_open, score_open, score_mc

def evaluate(rows, seed=42):
    parser = MMMUParser(seed)
    details = []
    for row in rows:
        if row.get('data_issue'):
            result = {'parsed': None, 'parse_success': False, 'random_fallback': False, 'data_issue': row['data_issue']}
            correct = False
        elif row['question_type'] == 'multiple-choice':
            result = parser.parse(row['prediction'], row['options'])
            correct = score_mc(row['answer'], result['parsed'])
        else:
            parsed = parse_open(row['prediction'])
            result = {'parsed': parsed, 'parse_success': bool(row['prediction'].strip()), 'random_fallback': False}
            correct = score_open(row['answer'], parsed)
        details.append({'uid': row['uid'], 'subject': row['subject'], 'question_type': row['question_type'],
                        'answer': row['answer'], **result, 'correct': correct})
    return {**aggregate(details), 'parsing_failure_uids': [r['uid'] for r in details if not r['parse_success']],
            'random_fallback_uids': [r['uid'] for r in details if r['random_fallback']], 'details': details}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', default=str(ROOT/'data/predictions_val.jsonl'))
    p.add_argument('--output', default=str(ROOT/'data/eval_val.json'))
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--allow-partial', action='store_true', help='Permit smoke/stress inputs; mark them partial')
    p.add_argument('--force', action='store_true')
    args = p.parse_args()
    rows = read_rows(args.input, predictions=True)
    if not args.allow_partial and not full_validation(rows):
        p.error('Expected 30 subjects x 30 validation items; use --allow-partial for smoke/stress only')
    result = {'schema_version': 1, 'status': 'completed', 'pipeline': 'mmmu_official_mc_and_open',
              'seed': args.seed, 'input': input_metadata(args.input, rows),
              'parser_sources': json.loads((ROOT/'vendor/sources.json').read_text()),
              'policy': {'mc_no_match': 'seeded random choice; counted in accuracy', 'open': 'official parse_open_response/eval_open',
                         'judge_api': False, 'prediction_text': 'prediction field, no extra answer extraction', 'invalid_imported_options': 'count incorrect and flag; provisional score'},
              **evaluate(rows, args.seed)}
    write_json(args.output, result, args.force)
    print(f"MMMU MC+open: macro={result['macro_accuracy']:.4%}, micro={result['micro_accuracy']:.4%}; {args.output}")

if __name__ == '__main__':
    main()
