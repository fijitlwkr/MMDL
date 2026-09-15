"""Select natural long-input, multi-image, and open-ended MMMU cases without changing gold answers."""
import argparse
import os
from pathlib import Path
from common import ROOT, read_rows, write_rows, write_json, check_output

def select_stress(rows, per_case=2):
    groups = {
        'long_input': sorted(rows, key=lambda r: len(r['question']) + sum(map(len, r['options'].values())), reverse=True),
        'multi_image': sorted([r for r in rows if len(r['images']) >= 2], key=lambda r: len(r['images']), reverse=True),
        'open': [r for r in rows if r['question_type'] == 'open'],
    }
    missing = [name for name, items in groups.items() if not items]
    if missing:
        raise ValueError(f'Missing stress coverage: {missing}. Build the full dataset first.')
    selected = {}
    for name, items in groups.items():
        for row in items[:per_case]:
            selected.setdefault(row['uid'], {**row, 'stress_tags': []})['stress_tags'].append(name)
    return list(selected.values())

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', default=str(ROOT/'data/dataset_val.jsonl'))
    p.add_argument('--output', default=str(ROOT/'data/dataset_stress.jsonl'))
    p.add_argument('--per-case', type=int, default=2)
    p.add_argument('--force', action='store_true')
    args = p.parse_args()
    if args.per_case < 1:
        p.error('--per-case must be positive')
    source, target = Path(args.input).resolve(), Path(args.output).resolve()
    if source == target:
        p.error('Stress output must differ from full dataset input')
    check_output(target, args.force); check_output(target.with_suffix('.meta.json'), args.force)
    rows = select_stress(read_rows(source), args.per_case)
    for row in rows:
        row['images'] = [os.path.relpath((source.parent / x).resolve(), target.parent) for x in row['images']]
    write_rows(target, rows, args.force)
    write_json(target.with_suffix('.meta.json'), {'source': str(source), 'num_examples': len(rows),
               'selection': 'longest question+option characters, most images (>=2), open; natural samples, no synthetic padding',
               'uids': {r['uid']: r['stress_tags'] for r in rows}}, args.force)
    print(f'Saved {len(rows)} stress cases to {target}')

if __name__ == '__main__':
    main()
