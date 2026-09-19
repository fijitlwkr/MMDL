#!/usr/bin/env python3
"""Preserve historical TSV question/options/GT; do not replace them with HF data."""
import argparse
import json
import math
from pathlib import Path
import string

import lab


def convert(source):
    ann = source['annotation']
    options = {}
    if ann['question_type'] == 'multiple-choice':
        for label in string.ascii_uppercase:
            value = ann.get(label)
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue  # Missing TSV columns, not the literal option text 'None'.
            options[label] = value
    result = {
        'id': ann['id'], 'question_id': source['question_id'],
        'question': ann['question'], 'question_type': ann['question_type'],
        'options': options, 'answer': ann['answer'],
        'raw_text': lab.first_present(source['result'].get('gen_raw'), source['result'].get('gen')),
        'finish_reason': source['finish_reason'],
        'generated_tokens': source['generated_tokens'],
        'input_tokens': source.get('input_tokens'),
    }
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--predictions', type=Path, required=True)
    p.add_argument('--summary', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--quarantine-invalid', action='store_true',
                   help='Separate invalid historical rows; produce an explicitly incomplete legacy-pilot')
    args = p.parse_args()
    original = lab.read_jsonl(args.predictions)
    rows, rejected = [], []
    for source in original:
        result = convert(source)
        try:
            lab.normalize(result, allow_missing_input_tokens=True)
        except ValueError as error:
            if not args.quarantine_invalid:
                raise
            rejected.append({'row': result, 'error': str(error)})
        else:
            rows.append(result)
    source_kind = 'legacy-pilot' if args.quarantine_invalid else 'legacy-tsv'
    summary = json.loads(args.summary.read_text())
    config = {
        'source_kind': source_kind,
        'original_rows': len(original), 'accepted_rows': len(rows), 'rejected_rows': len(rejected),
        'source_path': str(args.predictions),
        'source_sha256': lab.file_hash(args.predictions),
        'source_summary_sha256': lab.file_hash(args.summary),
        'adapter_sha256': lab.file_hash(Path(__file__)),
        'source_summary': summary,
        'max_new_tokens': summary.get('max_tokens'),
        'sampling_seed': summary.get('sampling', {}).get('seed'),
        'input_tokens_unknown': sum(r['input_tokens'] is None for r in rows),
        'notes': [
            'Original TSV question, options, ground truth, and raw response preserved.',
            'Null/NaN option columns removed; literal string None retained.',
            'HF-shaped IDs identify rows but do not certify HF pinned content.',
            'Unknown input token counts remain null; generation settings are historical.',
        ],
    }
    lab.validate([lab.normalize(r, allow_missing_input_tokens=True) for r in rows], source_kind, config)
    # Reject unexpected non-finite values before creating output files.
    json.dumps(rows, allow_nan=False)
    args.out.mkdir(parents=True, exist_ok=False)
    lab.write_jsonl(args.out/'raw.jsonl', rows)
    lab.write_json(args.out/'config.json', config)
    lab.write_jsonl(args.out/'rejected.jsonl', rejected)
    print(json.dumps({'rows': len(rows), 'input_tokens_unknown': config['input_tokens_unknown'],
                      'sampling_seed': config['sampling_seed'], 'source_kind': source_kind,
                      'rejected': len(rejected)}))


if __name__ == '__main__':
    main()
