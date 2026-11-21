"""Build C1 from frozen R1 rollouts, without model loads or evaluation data."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
SEED = 3407


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def read_rows(path):
    with Path(path).open(encoding='utf-8-sig') as f:
        return [json.loads(line) for line in f if line.strip()]


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def serialize(rows):
    return ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n'
                   for r in rows).encode('utf-8')


def inputs():
    source = ROOT / 'runs/full_k4'
    expected = json.loads((source / 'SHA256SUMS.json').read_bytes())
    manifest = json.loads((source / 'manifest.json').read_bytes())
    split = json.loads((ROOT / 'data/d3_split.json').read_bytes())
    hashes = {f'runs/full_k4/{n}': expected[n] for n in ('raw.jsonl', 'groups.json', 'manifest.json', 'r1_train.jsonl')}
    hashes.update(split['input_sha256'])
    assert hashes['data/r1_pool.jsonl'] == manifest['pool_sha256']
    assert manifest['reward_version'] == 'v2'
    assert manifest['reward_sha256'] == hashes['scripts/reward_v2.py']
    for name, wanted in hashes.items():
        assert sha(ROOT / name) == wanted, name
    for name in ('data/d3_split.json', 'data/d3_dev.jsonl', 'adapter/d3_e1/adapter_config.json',
                 'scripts/d3_pair_preference.py', 'scripts/d3_sample_dev.py', 'scripts/sd1_prepare.py',
                 'PLAN_C1.md', 'HANDOFF_C1_impl.md', 'scripts/c1_prepare.py'):
        hashes[name] = sha(ROOT / name)
    pool = read_rows(ROOT / 'data/r1_pool.jsonl')
    raw = read_rows(source / 'raw.jsonl')
    assert len(pool) == 1500 and len(raw) == 6000
    dev = set(split['development_rows'])
    assert len(dev) == 300 and dev == {r['row'] for r in read_rows(ROOT / 'data/d3_dev.jsonl')}
    assert len(set(split['training_rows'])) == 1200
    assert set(split['training_rows']).isdisjoint(dev)
    assert set(split['training_rows']) | dev == {r['row'] for r in pool}
    by = defaultdict(list)
    for r in raw:
        by[r['row']].append(r)
    assert set(by) == {r['row'] for r in pool}
    for item in pool:
        samples = by[item['row']]
        assert sorted(r['repeat'] for r in samples) == [0, 1, 2, 3]
        assert all(r['prompt_tokens'] == item['prompt_tokens'] for r in samples)
        assert all(r['seed'] == SEED + item['seed_index'] * 65536 + r['repeat'] for r in samples)
    return pool, by, dev, hashes


def build(pool, by, dev):
    rng = random.Random(SEED)
    anchors, train, distribution = [], [], Counter()
    for item in sorted(pool, key=lambda x: int(x['row'])):
        if item['row'] in dev:
            continue
        samples = sorted(by[item['row']], key=lambda r: r['repeat'])
        candidates = [r for r in samples if r['finish_reason'] == 'stop' and r['reward'] == 1 and r['output_tokens'] <= 4096]
        if not candidates:
            continue
        anchor = rng.choice(candidates)
        anchors.append({'row': item['row'], 'anchor_repeat': anchor['repeat'], 'raw_text': anchor['raw_text'],
                        'output_tokens': anchor['output_tokens']})
        distribution[sum(r['reward'] for r in samples)] += 1
        for sample in samples:
            entry = {k: sample[k] for k in ('row', 'repeat', 'raw_text', 'finish_reason', 'reward', 'prompt_tokens', 'output_tokens')}
            entry.update(images=item['images'], prompt=item['prompt'], anchor_repeat=anchor['repeat'],
                         origin=item['origin'], discipline=item['discipline'], subject=item['subject'])
            assert entry['raw_text'].encode('utf-8') == sample['raw_text'].encode('utf-8')
            assert entry['prompt'].encode('utf-8') == item['prompt'].encode('utf-8')
            assert 'answer' not in entry and 'choices' not in entry
            train.append(entry)
    random.Random(SEED).shuffle(train)
    assert len(anchors) == 1036 and len(train) == 4144
    assert dict(distribution) == {4: 631, 3: 194, 2: 115, 1: 96}, distribution
    assert sum(r['reward'] for r in train) == 3432
    assert sum(r['finish_reason'] == 'length' for r in train) == 155
    assert sum(r['output_tokens'] > 4608 for r in train) == 300
    assert not ({r['row'] for r in train} & dev)
    assert len({(r['row'], r['repeat']) for r in train}) == len(train)
    return train, anchors, distribution


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output-dir', type=Path, default=ROOT / 'data')
    ap.add_argument('--report', type=Path, default=ROOT / 'reports/c1_data_validation.json')
    args = ap.parse_args()
    assert args.output_dir.resolve().is_relative_to((ROOT / 'data').resolve())
    assert args.report.resolve().is_relative_to((ROOT / 'reports').resolve())
    targets = [args.output_dir / 'c1_train.jsonl', args.output_dir / 'c1_anchors.jsonl', args.report]
    assert not any(p.exists() for p in targets), 'Refuse to overwrite outputs'
    pool, by, dev, hashes = inputs()
    train, anchors, distribution = build(pool, by, dev)
    image_hashes = {}
    for entry in train:
        for im in entry['images']:
            if im['path'] not in image_hashes:
                path = (WORKSPACE / im['path']).resolve(strict=True)
                assert path.is_relative_to(WORKSPACE) and sha(path) == im['sha256'], im['path']
                image_hashes[im['path']] = im['sha256']
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for path, data in zip(targets[:2], (train, anchors)):
        with path.open('xb') as f:
            f.write(serialize(data))
    result = {'status': 'PASS', 'questions': len(anchors), 'responses': len(train), 'correct_responses': 3432,
              'truncated_responses': 155, 'responses_over_4608': 300, 'correct_of_4': dict(distribution),
              'development_overlap': 0, 'anchor_stop_reward1_le4096': True, 'source_text_utf8_unchanged': True,
              'training_order': 'numeric row, repeat ascending; independent Random(3407).shuffle',
              'anchor_selection': 'numeric row; repeat-sorted eligible candidates; one shared Random(3407).choice',
              'images_verified': len(image_hashes), 'image_sha256': image_hashes, 'input_sha256': hashes,
              'output_sha256': {p.name: sha(p) for p in targets[:2]}}
    write_json(args.report, result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('image_sha256', 'input_sha256')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
