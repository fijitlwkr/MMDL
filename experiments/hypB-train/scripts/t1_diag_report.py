"""Apply the frozen T1 diagnostic gate; never train or select an evaluation model."""
import argparse
from collections import Counter
import json
from pathlib import Path

from sd1_select import (DEV, ROOT, SOURCE, SPLIT, STRATUM, metrics, read_rows,
                       run_reward, sha, stratum, validate_raw, write_json)

NAMES = ('M0', 'D3-e1', 'T035', 'T010')
TEMPERATURES = {'T035': 0.35, 'T010': 0.10}
BASELINE_HASHES = {
    'M0': '0d23d51016620d84e56fe834400339fc8dd7e7232f959b1dd4d15a8f77250cd2',
    'D3-e1': '65e0ec75dda1b42fcd2964e2f0c203cb8bded43a3ad3bb30ca81c3a56f10aeb8',
}
ORIGINAL_SAMPLER_SHA = '64b47977fa76b83373261257546119ab7a009f6cb4000de5b0d18d5a204c91fa'


def decide(values):
    assert set(values) == set(TEMPERATURES)
    checks = {}
    for name, value in values.items():
        assert value['responses'] == 1200
        protected = value['by_stratum'][STRATUM]
        assert protected['responses'] == 632
        checks[name] = {'overall_correct': value['correct'],
                        'protected_correct': protected['correct'],
                        'overall_passed': value['correct'] >= 888,
                        'protected_passed': protected['correct'] >= 582}
        checks[name]['passed'] = checks[name]['overall_passed'] and checks[name]['protected_passed']
    passed = [name for name in TEMPERATURES if checks[name]['passed']]
    chosen = None
    if len(passed) == 1:
        chosen = passed[0]
    elif len(passed) == 2:
        difference = abs(values['T035']['correct'] - values['T010']['correct'])
        chosen = 'T035' if difference <= 5 else max(passed, key=lambda n: values[n]['correct'])
    return {'checks': checks, 'passed_conditions': passed, 'condition_for_T1_plan': chosen,
            'temperature_for_T1_plan': TEMPERATURES.get(chosen),
            'decision': 'WRITE_T1_PLAN' if chosen else 'DO_NOT_CONDUCT_T1_CLOSE_WITH_D3_E1',
            'overall_minimum': 888, 'protected_minimum': 582, 'tie_tolerance': 5,
            'auxiliary_metrics_used': False, 'diagnostic_only': True,
            'model_selection_used': False, 'training_started': False, 'validation_started': False}


def self_test(out):
    layers = {str(i): STRATUM if i < 158 else 'other' for i in range(300)}
    def fake(total, protected):
        assert 0 <= total - protected <= 568
        rows = [{'row': str(i // 4), 'reward': int(i < protected if i < 632 else i - 632 < total - protected),
                 'finish_reason': 'stop', 'output_tokens': 10, 'marker_count': 0} for i in range(1200)]
        return metrics(rows, layers)
    cases = [
        ('exact_boundaries_pass', (888, 582), (887, 582), 'T035'),
        ('overall_below', (887, 600), (880, 600), None),
        ('protected_below', (900, 581), (899, 581), None),
        ('both_pass_within_five', (890, 590), (895, 590), 'T035'),
        ('both_pass_difference_six', (890, 590), (896, 590), 'T010'),
        ('only_T010_passes', (887, 600), (888, 582), 'T010'),
        ('equal_counts_prefer_T035', (888, 582), (888, 582), 'T035'),
        ('higher_count_guard_failure', (888, 582), (950, 581), 'T035'),
    ]
    tests = []
    for name, a, b, expected in cases:
        result = decide({'T035': fake(*a), 'T010': fake(*b)})
        assert result['condition_for_T1_plan'] == expected, (name, result)
        tests.append({'case': name, 'counts': {'T035': a, 'T010': b},
                      'expected': expected, 'actual': result, 'passed': True})
    write_json(out, {'status': 'PASS', 'synthetic': True, 'real_T1_raws_read': False, 'tests': tests})
    print('T1_DIAGNOSTIC_SYNTHETIC_PASS', len(tests), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--m0', type=Path)
    parser.add_argument('--d3', type=Path)
    parser.add_argument('--t035', type=Path)
    parser.add_argument('--t010', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    paths = dict(zip(NAMES, (args.m0, args.d3, args.t035, args.t010)))
    if args.self_test:
        assert not any(paths.values())
        self_test(args.out)
        return
    if not all(paths.values()):
        parser.error('Provide M0, D3-e1, T035, T010 raws')
    proof = ROOT / 'reports/t1_diag/self_test.json'
    assert json.loads(proof.read_bytes())['status'] == 'PASS'
    assert sha(ROOT / 'scripts/d3_sample_dev.py') == ORIGINAL_SAMPLER_SHA
    items = {r['row']: r for r in read_rows(DEV)}
    assert len(items) == 300 and set(items) == set(json.loads(SPLIT.read_bytes())['development_rows'])
    groups = {r['row']: r for r in json.loads((SOURCE / 'groups.json').read_bytes())['groups']}
    layers = {row: stratum(groups[row]) for row in items}
    assert sum(v == STRATUM for v in layers.values()) == 158
    score, reward_identity = run_reward(True)
    values, records, common_manifest = {}, {}, None
    new_sampler_sha = sha(ROOT / 'scripts/t1_sample_dev.py')
    for name, path in paths.items():
        if name in BASELINE_HASHES:
            assert sha(path) == BASELINE_HASHES[name], name
        manifest = json.loads((path.parent / 'manifest.json').read_bytes())
        assert manifest['k'] == 4 and manifest['repeat_start'] == 4
        assert manifest['questions_sha256'] == sha(DEV)
        assert manifest['reward_sha256'] == reward_identity['reward_sha256']
        if name in TEMPERATURES:
            assert manifest['temperature'] == TEMPERATURES[name]
            assert manifest['sampler_sha256'] == new_sampler_sha
        else:
            assert 'temperature' not in manifest
            assert manifest['sampler_sha256'] == ORIGINAL_SAMPLER_SHA
        common = {k: v for k, v in manifest.items() if k not in ('model_path', 'sampler_sha256', 'temperature')}
        if common_manifest is None:
            common_manifest = common
        else:
            assert common == common_manifest, (name, 'Non-temperature conditions differ')
        if name in TEMPERATURES:
            original_manifest = json.loads((paths['M0'].parent / 'manifest.json').read_bytes())
            assert manifest['model_path'] == original_manifest['model_path'], (name, 'Not the M0 path')
        value = validate_raw(path, items, layers, score)
        rows = read_rows(path)
        records[name] = {(r['row'], r['repeat']): r for r in rows}
        counts = Counter()
        for row in rows:
            counts[row['row']] += row['reward']
        value['question_outcomes'] = {'all_correct': sum(n == 4 for n in counts.values()),
                                      'mixed': sum(1 <= n <= 3 for n in counts.values()),
                                      'all_wrong': sum(n == 0 for n in counts.values())}
        assert sum(value['question_outcomes'].values()) == 300
        value['length_count'] = sum(r['finish_reason'] == 'length' for r in rows)
        value['direction_overuse_count'] = sum(r['marker_count'] >= 21 for r in rows)
        value['output_tokens_total'] = sum(r['output_tokens'] for r in rows)
        values[name] = value
    assert values['M0']['correct'] == 861 and values['D3-e1']['correct'] == 882
    assert values['M0']['by_stratum'][STRATUM]['correct'] == 594
    reference = records['M0']
    for name in NAMES:
        current = records[name]
        assert set(current) == set(reference)
        for pair, row in current.items():
            assert row['seed'] == reference[pair]['seed']
            assert row['prompt_tokens'] == reference[pair]['prompt_tokens']
        gained = sum(reference[p]['reward'] == 0 and current[p]['reward'] == 1 for p in reference)
        lost = sum(reference[p]['reward'] == 1 and current[p]['reward'] == 0 for p in reference)
        assert gained - lost == values[name]['correct'] - 861
        values[name]['versus_M0'] = {'gained': gained, 'lost': lost, 'net': gained - lost}
    result = {'measurements': values, 'judgment': decide({n: values[n] for n in TEMPERATURES}),
              'temperatures': {'M0': 0.7, 'D3-e1': 0.7, **TEMPERATURES},
              'reward': reward_identity, 'development_sha256': sha(DEV),
              'raw_sha256': {name: sha(path) for name, path in paths.items()},
              'M0_seed_and_prompt_tokens_equal': True, 'baselines_reused': True,
              'training_started': False, 'validation_started': False, 'paid_API_calls': 0}
    write_json(args.out, result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
