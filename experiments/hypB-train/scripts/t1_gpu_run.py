"""Run the fixed T1 smoke and two temperature diagnostics; no training or validation."""
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

BASE = Path('/workspace/train_T1')
ROOT = BASE / 'work/train_RL_20261106'
IMAGES = Path('/workspace/train_D3_SD1')
MODEL = Path('/workspace/hf_cache/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/ebb281ec70b05090aa6165b016eac8ec08e71b17')
REPORT = ROOT / 'reports/t1_diag'
M0_HASHES = {
    'model-00001-of-00002.safetensors': '30a01a0556622645a3cce87b655bbbbbc1f170c196099f1b666c93202c3339a9',
    'model-00002-of-00002.safetensors': '046296a2a387efb43b0c997d5833c789604d168834f6e0d3064bf7bb13d002a6',
}


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2)
        f.write('\n')


def now():
    return datetime.now(timezone.utc).isoformat()


def verify_inputs():
    for name, expected in read(BASE / 't1_input_sha256.json')['files'].items():
        assert sha(ROOT / name) == expected, name


def command(name, argv):
    out = REPORT / 'execution' / name
    out.mkdir(parents=True)
    save(out / 'command.json', {'argv': list(map(str, argv)), 'started_utc': now()})
    started = time.monotonic()
    with (out / 'run.log').open('x') as log, (out / 'vram.csv').open('x') as memory:
        monitor = subprocess.Popen(['nvidia-smi', '--query-gpu=timestamp,memory.used,memory.total,utilization.gpu',
                                    '--format=csv,noheader,nounits', '-l', '1'], stdout=memory)
        try:
            result = subprocess.run(list(map(str, argv)), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        finally:
            monitor.terminate()
            monitor.wait()
    samples = list(csv.reader((out / 'vram.csv').open()))
    save(out / 'execution.json', {'exit': result.returncode, 'seconds': time.monotonic() - started,
                                 'finished_utc': now(),
                                 'max_nvidia_smi_mib': max((float(r[1]) for r in samples if len(r) == 4), default=None)})
    if result.returncode:
        raise RuntimeError(f'{name} failed; stop without changing code or conditions')


def seal(path):
    hashes = {p.name: sha(p) for p in path.iterdir() if p.is_file()}
    save(path / 'SHA256SUMS.json', hashes)
    return hashes


def package():
    entries = {}
    for source, destination in [(ROOT / 'data/t1_diag', 'runs/t1_diag'),
                                (ROOT / 'data/t1_diag_smoke', 'runs/t1_diag_smoke'),
                                (REPORT, 'reports/t1_diag')]:
        for p in sorted(source.rglob('*')):
            if p.is_file():
                assert not p.is_symlink()
                name = str(Path(destination) / p.relative_to(source))
                entries[name] = {'source': str(p), 'bytes': p.stat().st_size, 'sha256': sha(p)}
    index = {'status': 'PASS', 'created_utc': now(), 'files': entries, 'training_started': False,
             'validation_started': False, 'paid_API_calls': 0, 'inputs_unchanged': True,
             'final_nvidia_smi': subprocess.check_output(['nvidia-smi', '--query-gpu=name,memory.used,utilization.gpu',
                                                         '--format=csv,noheader'], text=True).strip()}
    data = (json.dumps(index, indent=2) + '\n').encode()
    archive = BASE / 't1_results.tar'
    with tarfile.open(archive, 'x') as t:
        for name, entry in entries.items():
            t.add(entry['source'], arcname=name, recursive=False)
        member = tarfile.TarInfo('reports/t1_diag/transfer_manifest.json')
        member.size = len(data)
        t.addfile(member, io.BytesIO(data))
    ready = {'status': 'PASS', 'archive_bytes': archive.stat().st_size, 'archive_sha256': sha(archive),
             'manifest_sha256': hashlib.sha256(data).hexdigest(), 'files': len(entries)}
    save(BASE / 't1_ready.json', ready)
    print(json.dumps(ready), flush=True)


def main():
    assert sys.argv[1:] == ['--run']
    assert os.environ.get('HF_HOME') == '/workspace/hf_cache'
    started = time.monotonic()
    progress = REPORT / 'progress'
    progress.mkdir()
    stage = 'preflight'
    save(progress / 'started.json', {'started_utc': now(), 'training_started': False, 'validation_started': False})
    try:
        verify_inputs()
        gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=name,memory.total,memory.used',
                                       '--format=csv,noheader,nounits'], text=True).strip()
        fields = [v.strip() for v in gpu.split(',')]
        assert len(gpu.splitlines()) == 1 and ('A100' in fields[0] or 'H100' in fields[0]) and float(fields[1]) >= 80000
        assert float(fields[2]) == 0, 'Another GPU job is active'
        import importlib.metadata as metadata
        import torch
        versions = {n: metadata.version(n) for n in ['torch', 'transformers', 'tokenizers', 'vllm', 'qwen-vl-utils']}
        assert versions == {'torch': '2.8.0+cu128', 'transformers': '4.57.1', 'tokenizers': '0.22.2',
                            'vllm': '0.11.0', 'qwen-vl-utils': '0.0.14'}
        assert torch.__version__ == '2.8.0+cu128' and torch.version.cuda == '12.8'
        for name, digest in M0_HASHES.items():
            assert sha(MODEL / name) == digest, name
        from sd1_select import DEV, SOURCE, read_rows, run_reward, stratum, validate_raw
        rows = read_rows(ROOT / 'data/r1_pool.jsonl')
        images = {im['path']: im['sha256'] for row in rows for im in row['images']}
        for name, digest in images.items():
            p = (IMAGES / name).resolve(strict=True)
            assert p.is_relative_to(IMAGES) and sha(p) == digest, name
        save(REPORT / 'environment.json', {'status': 'PASS', 'GPU': gpu, 'packages': versions,
                                         'torch_import': torch.__version__, 'CUDA': torch.version.cuda,
                                         'M0_sha256': M0_HASHES, 'images_verified': len(images),
                                         'image_root': str(IMAGES), 'model_path': str(MODEL), 'installation': False})
        physical = ROOT / 'data/t1_diag'
        smoke = ROOT / 'data/t1_diag_smoke'
        assert not physical.exists() and not smoke.exists() and not (ROOT / 'runs/t1_diag').exists()
        physical.mkdir()
        (ROOT / 'runs/t1_diag').symlink_to(physical, target_is_directory=True)
        (ROOT / 'runs/t1_diag_smoke').symlink_to(smoke, target_is_directory=True)
        fixed = [sys.executable, '-B', '-u', ROOT / 'scripts/t1_sample_dev.py', '--run',
                 '--pool-jsonl', ROOT / 'data/r1_pool.jsonl', '--questions-jsonl', DEV,
                 '--repeat-start', '4', '--k', '4', '--reward-v2', '--model-path', MODEL, '--image-root', IMAGES]
        stage = 'smoke'
        (progress / 'stage.txt').write_text(stage + '\n')
        print(now(), stage, flush=True)
        command(stage, [*fixed, '--limit', '2', '--temperature', '0.7', '--out', smoke])
        reference = {(r['row'], r['repeat']): r for r in read_rows(ROOT / 'runs/d3sd1_dev/M0/raw.jsonl')}
        test = read_rows(smoke / 'raw.jsonl')
        subset = [r['row'] for r in read_rows(DEV)[:2]]
        assert len(test) == 8 and {(r['row'], r['repeat']) for r in test} == {(r, k) for r in subset for k in range(4, 8)}
        for r in test:
            base = reference[r['row'], r['repeat']]
            assert (r['seed'], r['prompt_tokens']) == (base['seed'], base['prompt_tokens'])
        assert read(smoke / 'manifest.json')['temperature'] == 0.7
        save(REPORT / 'smoke_check.json', {'status': 'PASS', 'responses': 8, 'rows': subset,
                                         'seed_prompt_equal_M0': True, 'sha256': seal(smoke)})
        items = {r['row']: r for r in read_rows(DEV)}
        groups = {r['row']: r for r in read(SOURCE / 'groups.json')['groups']}
        layers = {row: stratum(groups[row]) for row in items}
        score, identity = run_reward(True)
        for name, temperature in [('T035', '0.35'), ('T010', '0.10')]:
            verify_inputs()
            stage = name
            (progress / 'stage.txt').write_text(stage + '\n')
            print(now(), stage, flush=True)
            out = physical / name
            assert not out.exists()
            command(name, [*fixed, '--temperature', temperature, '--out', out])
            value = validate_raw(out / 'raw.jsonl', items, layers, score)
            current = read_rows(out / 'raw.jsonl')
            for r in current:
                assert (r['seed'], r['prompt_tokens']) == (reference[r['row'], r['repeat']]['seed'],
                                                           reference[r['row'], r['repeat']]['prompt_tokens'])
            manifest = read(out / 'manifest.json')
            assert manifest['temperature'] == float(temperature) and manifest['sampler_sha256'] == sha(ROOT / 'scripts/t1_sample_dev.py')
            save(REPORT / f'{name}_validation.json', {'status': 'PASS', 'metrics': value, 'reward': identity,
                                                   'seed_prompt_equal_M0': True, 'sha256': seal(out)})
        verify_inputs()
        save(progress / 'complete.json', {'status': 'PASS', 'finished_utc': now(),
                                         'seconds': time.monotonic() - started, 'judgment_pending_local': True,
                                         'training_started': False, 'validation_started': False})
        (progress / 'stage.txt').write_text('complete\n')
        package()
        print('T1_GPU_COMPLETE_LOCAL_JUDGMENT_REQUIRED', flush=True)
    except BaseException as error:
        save(progress / 'failure.json', {'status': 'STOP', 'stage': stage, 'error_type': type(error).__name__,
                                        'message': str(error), 'finished_utc': now(), 'settings_changed': False})
        raise


if __name__ == '__main__':
    main()
