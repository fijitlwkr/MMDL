"""Offline decline diagnostics; item text is written only outside the Git checkout."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics

from aggregate import CATEGORIES, HERE, ROOT, raw_rows, require, score_rows, write_json
from verify_code import verify


def distribution(values):
    return {'count': len(values), 'total': sum(values),
            'mean': statistics.mean(values) if values else None,
            'median': statistics.median(values) if values else None,
            'min': min(values) if values else None, 'max': max(values) if values else None}


def lengths(ids, left, right):
    a = [left[i]['output_tokens'] for i in ids]
    b = [right[i]['output_tokens'] for i in ids]
    return {'left': distribution(a), 'right': distribution(b),
            'shorter': sum(y < x for x, y in zip(a, b)),
            'equal': sum(y == x for x, y in zip(a, b)),
            'longer': sum(y > x for x, y in zip(a, b)),
            'left_length_ended': sum(left[i]['finish_reason'] == 'length' for i in ids),
            'right_length_ended': sum(right[i]['finish_reason'] == 'length' for i in ids)}


def transitions(ids, ls, rs):
    gains = [i for i in ids if not ls[i]['final_correct'] and rs[i]['final_correct']]
    losses = [i for i in ids if ls[i]['final_correct'] and not rs[i]['final_correct']]
    retained = sum(ls[i]['final_correct'] and rs[i]['final_correct'] for i in ids)
    return {'total': len(ids), 'gains': len(gains), 'losses': len(losses),
            'net_gain': len(gains) - len(losses), 'retained_correct': retained,
            'left_correct': retained + len(losses), 'right_correct': retained + len(gains)}, gains, losses


def analyze_pair(name, left, right, ls, rs):
    ids = sorted(left)
    stats, gains, losses = transitions(ids, ls, rs)
    axes = {}
    for axis in ('category', 'subject', 'question_type'):
        label = lambda i: CATEGORIES[left[i]['subject']] if axis == 'category' else left[i][axis]
        groups = {}
        for value in sorted({label(i) for i in ids}):
            group = [i for i in ids if label(i) == value]
            row, _, lost = transitions(group, ls, rs)
            row['loss_share'] = len(lost) / len(losses) if losses else 0
            row['loss_rate_among_left_correct'] = len(lost) / row['left_correct'] if row['left_correct'] else None
            groups[value] = row
        require(sum(v['losses'] for v in groups.values()) == len(losses), axis + ' losses')
        require(sum(v['gains'] for v in groups.values()) == len(gains), axis + ' gains')
        axes[axis] = groups
    route = lambda subset: dict(sorted(Counter(ls[i]['route'] + ' -> ' + rs[i]['route'] for i in subset).items()))
    statuses = lambda subset: dict(Counter(rs[i]['final_status'] for i in subset))
    result = {'comparison': name, 'v2': stats, 'by': axes,
              'loss_lengths': lengths(losses, left, right), 'gain_lengths': lengths(gains, left, right),
              'all_lengths': lengths(ids, left, right),
              'loss_route_transitions': route(losses), 'gain_route_transitions': route(gains),
              'loss_right_status': statuses(losses)}
    for qtype in ('multiple-choice', 'open'):
        subset = [i for i in ids if left[i]['question_type'] == qtype]
        row, g, l = transitions(subset, ls, rs)
        result[qtype] = {'v2': row, 'loss_lengths': lengths(l, left, right),
                         'loss_route_transitions': route(l), 'loss_right_status': statuses(l)}
    return result, losses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace-root', type=Path, default=ROOT.parents[1])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--private-out', type=Path, required=True)
    args = parser.parse_args()
    verify()
    workspace = args.workspace_root.resolve()
    private = args.private_out.resolve()
    require(not private.is_relative_to(ROOT), 'Private item audits must stay outside the Git checkout')
    require(not private.exists() and not args.out.exists(), 'Use fresh diagnostic output paths')
    sources = {
        'M0': ('assignment/experiments/received_20260922/results/input/raw.jsonl',
               'work/team-evaluator-no-length/assignment/experiments/raw_evaluation/outputs/release-v2-latest'),
        'E1': ('work/eval_B_20261101/runs/E1/generation/raw.jsonl', 'work/eval_B_20261101/scoring/E1'),
        'E2': ('work/eval_B_20261101/runs/E2/generation/raw.jsonl', 'work/eval_B_20261101/scoring/E2'),
    }
    raw, scored, hashes = {}, {}, {}
    for model, (raw_path, score_path) in sources.items():
        rows, digest = raw_rows(workspace / raw_path)
        _, results = score_rows(workspace / score_path, rows, digest)
        require(all(type(r['final_correct']) is bool for r in results.values()), 'Scores must be complete')
        raw[model], scored[model], hashes[model] = {r['id']: r for r in rows}, results, digest
    private.mkdir(parents=True, exist_ok=False)
    summary = {'raw_sha256': hashes, 'comparisons': {}, 'api_calls': 0, 'grading_changed': False}
    audits = []
    for left_name, right_name in (('M0', 'E1'), ('M0', 'E2'), ('E1', 'E2')):
        name = left_name + '_vs_' + right_name
        result, lost = analyze_pair(name, raw[left_name], raw[right_name], scored[left_name], scored[right_name])
        frozen = json.loads((HERE / 'aggregation_20261101' / (name + '.json')).read_text(encoding='utf-8'))
        for field in ('gains', 'losses', 'net_gain'):
            require(result['v2'][field] == frozen['safety_900_v2'][field], 'Frozen aggregate reconciliation: ' + name)
        summary['comparisons'][name] = result
        if left_name != 'M0':
            continue
        for i in lost:
            audits.append({'id': i, 'model': right_name, 'category': CATEGORIES[raw['M0'][i]['subject']],
                           'M0': raw['M0'][i], 'target': raw[right_name][i],
                           'M0_score': scored['M0'][i], 'target_score': scored[right_name][i]})
    open_ids = [i for i in raw['M0'] if raw['M0'][i]['question_type'] == 'open']
    s, _, _ = transitions(open_ids, scored['M0'], scored['E2'])
    require(s['left_correct'] == 40 and s['right_correct'] == 17 and s['net_gain'] == -23, 'Open-score reconciliation')
    with (private / 'decline_items.jsonl').open('w', encoding='utf-8', newline='\n') as handle:
        for row in audits:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    open_audit = [r for r in audits if r['model'] == 'E2' and r['M0']['question_type'] == 'open']
    with (private / 'E2_open_losses.jsonl').open('w', encoding='utf-8', newline='\n') as handle:
        for row in open_audit:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    write_json(args.out, summary)
    print('Frozen aggregate reconciliation passed for all three comparisons.')
    print('E2 open transitions:', s)
    print('Private review items:', len(audits), '; public output contains aggregate counters only.')


if __name__ == '__main__':
    main()
