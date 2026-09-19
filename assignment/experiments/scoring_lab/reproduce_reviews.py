"""Reproduce the frozen H1/H2 review results without API calls or inference."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--evidence', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args()
    evidence = args.evidence.resolve()
    out = args.out.resolve()
    if out.exists():
        raise ValueError('Use a new output directory; frozen evidence is never overwritten')
    if out.is_relative_to(evidence):
        raise ValueError('Output must be outside the frozen evidence directory')

    manifest_path = ROOT / 'bundle_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for name, expected in manifest['files_sha256'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Bundle file changed: {name}')

    out.mkdir(parents=True)
    for phase in ('h1', 'h2'):
        source = evidence / phase
        command = [sys.executable, str(ROOT / f'import_{phase}_review.py'),
                   '--source', str(source / 'source_export.json'),
                   '--labels', str(source / 'returned_review_original.json'),
                   '--out', str(out / phase)]
        if phase == 'h2':
            command += ['--manifest', str(source / 'export_manifest_original.json'),
                        '--template', str(source / 'review_template_original.json'),
                        '--h1-summary', str(evidence / 'h1/summary.json')]
        subprocess.run(command, check=True)
        actual = json.loads((out / phase / 'summary.json').read_text(encoding='utf-8'))
        expected = json.loads((source / 'summary.json').read_text(encoding='utf-8'))
        # File layout/importer hashes changed for publication; statistics did not.
        actual.pop('code_sha256')
        expected.pop('code_sha256')
        if actual != expected:
            raise ValueError(f'{phase}: reproduced summary differs')
        for filename in ('returned_review_original.json', 'human_labels_full.jsonl', 'parser_comparison.jsonl'):
            if (out / phase / filename).read_bytes() != (source / filename).read_bytes():
                raise ValueError(f'{phase}: reproduced {filename} differs')
    print('PASS: H1/H2 statistics and all three evidence/result files per cohort match; no API or inference.')


if __name__ == '__main__':
    main()
