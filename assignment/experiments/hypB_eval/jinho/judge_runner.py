"""Enter OpenAI key or use OPENAI_API_KEY env, then run the frozen v2 evaluator for Jinho."""
import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import warnings

from verify_code import ROOT, verify

EVALUATOR = ROOT / 'code/scoring/evaluate.py'
SETTINGS = {'model': 'gpt-4.1-mini-2025-04-14', 'temperature': 0,
            'top_p': 1, 'seed': 3407, 'max_tokens': 8}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def workflow(scoring_root, logs=None, check_only=False):
    verify()
    runs = [d.name for d in scoring_root.iterdir() if d.is_dir() and (d / 'manifest.json').exists()]
    if not runs:
        raise FileNotFoundError(f"No prepared runs found in {scoring_root}. Run evaluate.py prepare first.")

    print(f"Discovered prepared runs in {scoring_root}: {runs}")
    if check_only:
        print('Offline preflight passed; no key entry or API calls.')
        return 0

    logs = logs or scoring_root / 'judge_launcher'
    logs.mkdir(parents=True, exist_ok=True)
    state = {'pid': os.getpid(), 'state': 'starting', 'runs': runs}

    def status(phase, stage):
        state.update(state=phase, stage=stage, updated_at=datetime.now(timezone.utc).isoformat())
        temp = logs / 'status.json.tmp'
        temp.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
        temp.replace(logs / 'status.json')
        with (logs / 'progress.log').open('a', encoding='utf-8') as handle:
            handle.write(f"{state['updated_at']} {phase} {stage}\n")
        print(f'{phase}: {stage}', flush=True)

    def execute(label, command, run, *extra):
        status('running', label)
        args = [sys.executable, '-X', 'utf8', str(EVALUATOR), command,
                '--out', str(scoring_root / run), *extra]
        with (logs / (label + '.log')).open('a', encoding='utf-8') as handle:
            handle.write(f"\n--- {datetime.now(timezone.utc).isoformat()} {label} ---\n")
            handle.flush()
            result = subprocess.run(args, stdout=handle, stderr=subprocess.STDOUT, check=False)
        if result.returncode:
            raise RuntimeError(f'Evaluator {command} on {run} failed; check logs in {logs}')

    failed = False
    secret = os.environ.get('OPENAI_API_KEY', '').strip()
    try:
        if not secret:
            status('waiting_for_key', 'key_entry')
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                secret = getpass.getpass('OpenAI API key (hidden, one entry, never saved): ').strip()
            if not secret:
                raise ValueError('No OpenAI key supplied')
            os.environ['OPENAI_API_KEY'] = secret

        for run in runs:
            execute(f'{run}_full', 'run', run)
    except BaseException as exc:
        failed = True
        state['failure_type'] = type(exc).__name__
        state['failure_stage'] = state.get('stage')
        print(f"Exception encountered: {exc}")
    finally:
        os.environ.pop('OPENAI_API_KEY', None)

    for run in runs:
        try:
            execute(f'{run}_summarize', 'summarize', run)
        except BaseException as exc:
            failed = True
            state['failure_type'] = type(exc).__name__

    summaries = {run: read_json(scoring_root / run / 'summary.json') for run in runs if (scoring_root / run / 'summary.json').exists()}
    state['pending'] = {run: value.get('overall', {}).get('pending', 0) for run, value in summaries.items()}
    if any(state['pending'].values()):
        failed = True

    status('failed' if failed else 'complete', 'finished')
    if failed:
        print('FAILED / PENDING. Review logs before resuming.')
        return 1
    else:
        print('COMPLETE. All runs scored and summarized successfully!')
        return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scoring-root', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    options = parser.parse_args()
    raise SystemExit(workflow(options.scoring_root.resolve(), check_only=options.check_only))

