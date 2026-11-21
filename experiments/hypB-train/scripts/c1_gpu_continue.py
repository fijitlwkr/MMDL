"""Continue only a passed <=8h C1 smoke: fresh full training, serial dev, selection."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time

from c1_select import DEV, SOURCE, STRATUM, read_rows, run_reward, stratum, validate_raw

BASE = Path('/workspace/train_C1')
ROOT = BASE / 'work/train_RL_20261106'
TRAIN = Path('/workspace/train_D1/.venv-train/bin/python')
EVAL = Path('/workspace/train_D1/.venv-eval/bin/python')
M0 = Path('/workspace/hf_cache/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/ebb281ec70b05090aa6165b016eac8ec08e71b17')
MERGE = Path('/workspace/train_D3_SD1/sources/e1/merge.py')
IMAGES = Path('/workspace/train_D3_SD1')
REPORT = ROOT / 'reports/c1_dev'
PROGRESS = ROOT / 'reports/c1_gpu_pipeline'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2)
        f.write('\n')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def command(name, argv):
    folder = ROOT / 'reports/c1_gpu_execution' / name
    folder.mkdir(parents=True)
    save(folder / 'c1_command.json', {'argv':list(map(str,argv)), 'started_utc':stamp(), 'cwd':str(ROOT)})
    started = time.monotonic()
    with (folder/'c1_gpu_memory.csv').open('x') as memory, (folder/'c1_run.log').open('x') as log:
        monitor = subprocess.Popen(['nvidia-smi','--query-gpu=timestamp,memory.used,memory.total,utilization.gpu',
                                    '--format=csv,noheader,nounits','-l','1'], stdout=memory, stderr=subprocess.DEVNULL)
        try:
            result = subprocess.run(list(map(str,argv)), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        finally:
            monitor.terminate()
            monitor.wait()
    samples = list(csv.reader((folder/'c1_gpu_memory.csv').open()))
    receipt = {'exit':result.returncode, 'seconds':time.monotonic()-started, 'finished_utc':stamp(),
               'max_nvidia_smi_mib':max(float(r[1]) for r in samples if len(r)==4)}
    save(folder/'c1_execution.json',receipt)
    if result.returncode:
        raise RuntimeError(f'{name} failed; preserve logs and stop without changes')
    return receipt


def stage(name):
    (PROGRESS/'c1_stage.txt').write_text(name+'\n')
    print(stamp(),name,flush=True)


def merged_receipt(name, model, adapter):
    from safetensors import safe_open
    assert model.is_dir() and not model.is_symlink()
    hashes = {p.name:sha(p) for p in sorted(model.iterdir()) if p.is_file()}
    weights = {n:v for n,v in hashes.items() if n.endswith('.safetensors')}
    assert len(weights)==2
    tensor_count = 0
    for n in weights:
        with safe_open(model/n,framework='pt',device='cpu') as f:
            for key in f.keys():
                assert f.get_slice(key).get_dtype()=='BF16'
                tensor_count+=1
    for p in M0.iterdir():
        if p.suffix in ('.json','.jinja','.txt') and p.name not in ('config.json','model.safetensors.index.json'):
            assert hashes[p.name]==sha(p),p.name
    result = {'status':'PASS','candidate':name,'safe_merge':True,'dtype':'BF16','tensor_count':tensor_count,
              'processor_original_bytes':True,'merged_sha256':hashes,
              'adapter_sha256':{p.name:sha(p) for p in sorted(adapter.iterdir()) if p.is_file()}}
    save(REPORT/f'c1_{name}_merge_hashes.json',result)
    return hashes


def delete_merge(name, model, hashes, validated):
    allowed = {'smoke':ROOT/'artifacts/c1_smoke/c1_merged','h':BASE/'models/C1-h','f':BASE/'models/C1-f'}
    assert validated and model==allowed[name] and model.resolve()==model and model.is_relative_to(BASE)
    assert not model.is_symlink() and all(p.is_file() and not p.is_symlink() for p in model.iterdir())
    assert {p.name:sha(p) for p in model.iterdir()}==hashes
    save(REPORT/f'c1_{name}_merge_delete_intent.json',{'exact_path':str(model),'sha256':hashes,'utc':stamp()})
    shutil.rmtree(model)
    save(REPORT/f'c1_{name}_merge_deleted.json',{'exact_path':str(model),'sha256_before_delete':hashes,'deleted_utc':stamp()})


def validate_development(name, out):
    items = {r['row']:r for r in read_rows(DEV)}
    groups = {r['row']:r for r in read(SOURCE/'groups.json')['groups']}
    layers = {row:stratum(groups[row]) for row in items}
    score, reward_identity = run_reward(True)
    stats = validate_raw(out/'raw.jsonl',items,layers,score)
    reference = {(r['row'],r['repeat']):r for r in read_rows(ROOT/'runs/d3sd1_dev/M0/raw.jsonl')}
    rows = read_rows(out/'raw.jsonl')
    assert len(rows)==1200
    for row in rows:
        old = reference[row['row'],row['repeat']]
        assert row['seed']==old['seed'] and row['prompt_tokens']==old['prompt_tokens']
    hashes = {p.name:sha(p) for p in out.iterdir() if p.is_file()}
    save(out/'SHA256SUMS.json',hashes)
    save(REPORT/f'c1_{name}_measurement.json',{'status':'PASS','metrics':stats,'reward':reward_identity,
                                           'M0_seed_and_prompt_tokens_equal':True,'sha256':hashes})
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run',action='store_true')
    args = ap.parse_args()
    if not args.run:
        ap.error('Explicit --run requires passed smoke/time gate and user GPU authorization')
    assert os.environ.get('HF_HOME')=='/workspace/hf_cache'
    assert os.environ.get('PYTORCH_CUDA_ALLOC_CONF')=='expandable_segments:True'
    assert not PROGRESS.exists()
    for name, expected in read(BASE/'c1_input_sha256.json').items():
        assert sha(BASE/name)==expected,name
    smoke = ROOT/'artifacts/c1_smoke'
    summary = read(smoke/'c1_smoke_summary.json')
    assert (ROOT/'reports/c1_gpu_smoke_execution/c1_exit.txt').read_text().strip()=='0'
    assert summary['status']=='PASS' and summary['training']['steps']==20
    assert summary['training']['estimated_full_259_step_seconds']<=28800
    assert not summary['estimated_full_training_over_8h']
    assert read(REPORT/'c1_selection_self_test.json')['status']=='PASS'
    PROGRESS.mkdir(parents=True)
    started = time.monotonic()
    save(PROGRESS/'c1_start.json',{'started_utc':stamp(),'time_gate_seconds':summary['training']['estimated_full_259_step_seconds'],
                                'full_starts_from':'M0 + fresh LoRA; no smoke adapter/resume','validation_authorized':False})
    try:
        stage('smoke_merge_cleanup')
        smoke_adapter=smoke/'c1_training/checkpoint-20'
        assert sha(smoke_adapter/'adapter_model.safetensors')==summary['adapter_sha256']
        hashes=merged_receipt('smoke',smoke/'c1_merged',smoke_adapter)
        assert {n:v for n,v in hashes.items() if n.endswith('.safetensors')}==summary['merged_sha256']
        delete_merge('smoke',smoke/'c1_merged',hashes,read(smoke/'c1_vllm_load.json')['status']=='PASS')
        stage('full_training')
        full=ROOT/'artifacts/c1_full'
        assert not full.exists()
        command('c1_full',[TRAIN,'-B','-u',ROOT/'scripts/c1_train.py','--run','--model-path',M0,
                          '--image-root',IMAGES,'--output',full])
        train=read(full/'c1_training_summary.json');run=read(full/'c1_run.json');steps=read_rows(full/'c1_steps.jsonl')
        assert train['status']=='PASS' and train['steps']==len(steps)==259 and train['examples']==4144
        assert not train['partial_run'] and run['config_sha256']==sha(ROOT/'scripts/c1_config.json')
        assert run['lora']['lora_modules']==252 and run['lora']['trainable_tensors']==504 and run['lora']['visual_trainable_tensors']==0
        assert [r['step'] for r in steps]==list(range(1,260))
        assert all(r['examples']==r['step']*16 and r['learning_rate']==1e-5 for r in steps)
        assert all(math.isfinite(r[k]) for r in steps for k in ('js_loss','grad_norm','student_mean_logp','teacher_mean_logp'))
        assert sorted(p.name for p in full.glob('checkpoint-*'))==['checkpoint-130','checkpoint-259']
        models=BASE/'models';models.mkdir()
        physical=ROOT/'data/c1_dev';physical.mkdir()
        logical=ROOT/'runs/c1_dev';assert not logical.exists();logical.symlink_to(physical,target_is_directory=True)
        for name,short,step in [('C1-h','h',130),('C1-f','f',259)]:
            stage(name+'_merge')
            adapter=full/f'checkpoint-{step}';model=models/name
            assert not any(models.iterdir()) and not model.exists()
            command('c1_'+short+'_merge',[TRAIN,'-B',MERGE,adapter,model])
            hashes=merged_receipt(short,model,adapter)
            stage(name+'_vllm_loading')
            command('c1_'+short+'_load',[EVAL,'-B',ROOT/'scripts/c1_smoke.py','vllm-load','--run','--model-path',model,
                                        '--output',REPORT/f'c1_{short}_vllm_load.json'])
            stage(name+'_development')
            out=logical/name;assert not out.exists()
            command('c1_'+short+'_development',[EVAL,'-B','-u',ROOT/'scripts/d3_sample_dev.py','--run',
                      '--pool-jsonl',ROOT/'data/r1_pool.jsonl','--questions-jsonl',DEV,'--repeat-start','4','--k','4',
                      '--reward-v2','--model-path',model,'--image-root',IMAGES,'--out',out])
            validate_development(short,out)
            delete_merge(short,model,hashes,True)
        stage('selection')
        command('c1_selection',[TRAIN,'-B',ROOT/'scripts/c1_select.py',
                 '--m0',ROOT/'runs/d3sd1_dev/M0/raw.jsonl','--d3',ROOT/'runs/d3sd1_dev/D3-e1/raw.jsonl',
                 '--half',logical/'C1-h/raw.jsonl','--full',logical/'C1-f/raw.jsonl','--out',REPORT/'c1_selection.json'])
        result={'status':'PASS','seconds':time.monotonic()-started,'finished_utc':stamp(),
                'selection':read(REPORT/'c1_selection.json')['selection'],'validation_started':False}
        save(PROGRESS/'c1_finished.json',result)
        stage('complete')
        (PROGRESS/'c1_exit.txt').write_text('0\n')
    except BaseException as exc:
        save(PROGRESS/'c1_failure.json',{'status':'STOP','stage':(PROGRESS/'c1_stage.txt').read_text().strip(),
                                       'error_type':type(exc).__name__,'message':str(exc),'finished_utc':stamp(),
                                       'settings_or_frozen_code_changed':False,'validation_started':False})
        (PROGRESS/'c1_exit.txt').write_text('1\n')
        raise


if __name__=='__main__':
    main()
