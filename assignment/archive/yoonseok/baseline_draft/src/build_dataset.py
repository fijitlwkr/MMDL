"""Build a pinned Hugging Face MMMU validation manifest and portable image files."""
import argparse
import ast
import json
import string
from pathlib import Path
from common import ROOT, SUBJECTS, DATA_REVISION, read_rows, validate, write_rows, write_json, check_output

def options_dict(value):
    if isinstance(value, str):
        value = ast.literal_eval(value)
    if isinstance(value, list):
        if len(value) > 26:
            raise ValueError('More than 26 options')
        return dict(zip(string.ascii_uppercase, value))
    if isinstance(value, dict):
        return value
    raise ValueError(f'Unsupported options type: {type(value)}')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', default=str(ROOT/'data/dataset_val.jsonl'))
    p.add_argument('--revision', default=DATA_REVISION)
    p.add_argument('--subjects', nargs='+', choices=SUBJECTS, default=SUBJECTS)
    p.add_argument('--per-subject', type=int, default=30)
    p.add_argument('--force', action='store_true')
    args = p.parse_args()
    if not 1 <= args.per_subject <= 30 or len(set(args.subjects)) != len(args.subjects):
        p.error('Use 1..30 examples per subject and unique subjects')
    output = Path(args.output).resolve()
    check_output(output, args.force)
    check_output(output.with_suffix('.meta.json'), args.force)
    from datasets import load_dataset
    from PIL import Image
    from io import BytesIO
    image_dir = output.parent / (output.stem + '_images')
    image_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for subject in args.subjects:
        dataset = load_dataset('MMMU/MMMU', subject, split='validation', revision=args.revision)
        if len(dataset) != 30:
            raise ValueError(f'{subject}: expected 30 validation examples, got {len(dataset)}')
        for source in dataset.select(range(args.per_subject)):
            uid = source['id']
            if not uid.startswith(f'validation_{subject}_') or Path(uid).name != uid:
                raise ValueError(f'Unexpected UID {uid}')
            images = []
            for index in range(1, 8):
                image = source.get(f'image_{index}')
                if image is None:
                    continue
                if isinstance(image, dict):
                    image = Image.open(BytesIO(image['bytes'])) if image.get('bytes') else Image.open(image['path'])
                destination = image_dir / f'{uid}_{index}.png'
                image.convert('RGB').save(destination)
                images.append(str(destination.relative_to(output.parent)))
            kind = source['question_type']
            row = {'uid': uid, 'subject': subject, 'split': 'validation', 'question_type': kind,
                   'question': source['question'], 'options': options_dict(source['options']) if kind == 'multiple-choice' else {},
                   'answer': source['answer'], 'images': images,
                   'provenance': {'dataset': 'MMMU/MMMU', 'revision': args.revision, 'config': subject, 'source': 'huggingface'}}
            rows.append(row)
        print(f'{subject}: {args.per_subject} examples')
    validate(rows)
    write_rows(output, rows, args.force)
    write_json(output.with_suffix('.meta.json'), {'dataset': 'MMMU/MMMU', 'revision': args.revision,
               'split': 'validation', 'subjects': args.subjects, 'per_subject': args.per_subject, 'num_examples': len(rows)}, args.force)
    print(f'Saved {len(rows)} examples to {output}')

if __name__ == '__main__':
    main()
