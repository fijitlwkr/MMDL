"""Serial fixed development measurements, one disposable merged model at a time."""
import csv,hashlib,json,os,shutil,statistics,subprocess,time
from datetime import datetime,timezone
from pathlib import Path
from classify_answers import ROOT,read_rows,write_json
from d3_prepare import DEV,SOURCE,stratum
from d3_select import validate_raw
from sample_m0 import run_reward

WORK=ROOT.parents[1]
TRAIN=Path('/workspace/train_D1/.venv-train/bin/python')
EVAL=Path('/workspace/train_D1/.venv-eval/bin/python')
BASE=Path('/workspace/hf_cache/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/ebb281ec70b05090aa6165b016eac8ec08e71b17')
CANDIDATES={'D3-e1':('d3_full',39),'D3-e2':('d3_full',78),'SD1-a':('sd1_a',252),'SD1-b':('sd1_b',126),'SD1-c':('sd1_b',252)}
REPORT=ROOT/'reports/d3sd1_dev'

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def stamp():return datetime.now(timezone.utc).isoformat()

def command(argv,folder):
    assert not folder.exists(),folder
    folder.mkdir(parents=True)
    started=time.monotonic();begin=stamp()
    write_json(folder/'command.json',{'argv':[str(x) for x in argv],'cwd':str(WORK),'started_utc':begin})
    with (folder/'gpu_memory.csv').open('x') as memory,(folder/'run.log').open('x') as log:
        memory.write('timestamp,used_mib,total_mib,util_pct\n');memory.flush()
        monitor=subprocess.Popen(['nvidia-smi','--query-gpu=timestamp,memory.used,memory.total,utilization.gpu','--format=csv,noheader,nounits','-l','1'],stdout=memory,stderr=subprocess.DEVNULL)
        try:result=subprocess.run([str(x) for x in argv],cwd=WORK,stdout=log,stderr=subprocess.STDOUT)
        finally:monitor.terminate();monitor.wait()
    receipt={'started_utc':begin,'finished_utc':stamp(),'seconds':time.monotonic()-started,'exit':result.returncode}
    with (folder/'gpu_memory.csv').open() as stream:
        rows=list(csv.DictReader(stream))
    receipt['max_nvidia_smi_mib']=max(float(row['used_mib'].strip()) for row in rows)
    write_json(folder/'execution.json',receipt)
    if result.returncode:raise RuntimeError(f'Command failed ({result.returncode}); retained log: {folder}')
    return receipt

def raw_check(name,out):
    items={row['row']:row for row in read_rows(DEV)}
    groups={row['row']:row for row in json.loads((SOURCE/'groups.json').read_bytes())['groups']}
    layers={row:stratum(groups[row]) for row in items}
    score,identity=run_reward(True)
    stats=validate_raw(out/'raw.jsonl',items,layers,score)
    rows=read_rows(out/'raw.jsonl')
    stats.update(name=name,median_output_tokens=statistics.median(row['output_tokens'] for row in rows),
                 output_tokens_total=sum(row['output_tokens'] for row in rows),input_tokens_total=sum(row['prompt_tokens'] for row in rows),
                 length_count=sum(row['finish_reason']=='length' for row in rows),reward=identity)
    files={p.name:sha(p) for p in out.iterdir() if p.is_file()}
    write_json(out/'SHA256SUMS.json',files)
    write_json(REPORT/f'{name}_measurement.json',{'status':'PASS',**stats,'sha256':files})
    return stats

def sample(name,model,out):
    assert not out.exists(),out
    command([EVAL,'-B','-u',ROOT/'scripts/d3_sample_dev.py','--run','--pool-jsonl',ROOT/'data/r1_pool.jsonl',
             '--questions-jsonl',DEV,'--image-root',WORK,'--repeat-start','4','--k','4','--reward-v2',
             '--model-path',model,'--out',out],REPORT/'execution'/f'{name}_generation')
    raw_check(name,out)

def merge(name,adapter,model):
    assert not model.exists()
    assert not any(p.is_dir() for p in model.parent.iterdir()),'Only one merged model may exist'
    command([TRAIN,'-B','-u',WORK/'sources/e1/merge.py',adapter,model],REPORT/'execution'/f'{name}_merge')
    hashes={p.name:sha(p) for p in model.iterdir() if p.is_file()}
    assert len([n for n in hashes if n.endswith('.safetensors')])==2
    for p in BASE.iterdir():
        if p.suffix in {'.json','.jinja','.txt'} and p.name not in {'config.json','model.safetensors.index.json'}:
            assert hashes[p.name]==sha(p),(name,p.name)
    write_json(REPORT/f'{name}_merge_hashes.json',{'candidate':name,'base_revision':BASE.name,'merge_dtype':'bfloat16',
               'safe_merge':True,'processor_original_bytes':True,'merged_sha256':hashes,
               'adapter_sha256':{p.name:sha(p) for p in adapter.iterdir() if p.is_file()}})
    return hashes

def remove_measured_merge(name,model,hashes):
    receipt=REPORT/f'{name}_measurement.json'
    assert json.loads(receipt.read_bytes())['status']=='PASS'
    assert model==WORK/'models'/name and model.resolve()==model and not model.is_symlink()
    assert {p.name:sha(p) for p in model.iterdir() if p.is_file()}==hashes
    assert all(p.is_file() and not p.is_symlink() for p in model.iterdir())
    # User explicitly approved deleting each newly merged model after its development measurement.
    shutil.rmtree(model)
    write_json(REPORT/f'{name}_merge_deleted.json',{'deleted_utc':stamp(),'exact_path':str(model),'sha256_before_delete':hashes,
               'reason':'Development 1200 responses validated; adapter and merge hash receipt preserved'})

def preference_checks():
    first=ROOT/'artifacts/d3_full/checkpoint-39'
    inputs=ROOT/'data/d3sd1_pair_smoke';assert not inputs.exists();inputs.mkdir()
    for source,dest in [('d3_dev_pairs_swift.jsonl','pairs.jsonl'),('d3_dev_pairs_index.jsonl','index.jsonl')]:
        lines=(ROOT/'data'/source).read_bytes().splitlines(keepends=True)
        (inputs/dest).write_bytes(b''.join(lines[:2]))
    smoke=REPORT/'preference/smoke'
    common=[TRAIN,'-B','-u',ROOT/'scripts/d3_pair_preference.py','--run','--base-model',BASE]
    command([*common,'--pairs',inputs/'pairs.jsonl','--index',inputs/'index.jsonl','--adapter',first,'--output',smoke],REPORT/'execution/preference_smoke')
    rows=read_rows(smoke/'pair_logps.jsonl');assert len(rows)==2
    assert all(row['candidate_chosen_logp']!=row['m0_chosen_logp'] or row['candidate_rejected_logp']!=row['m0_rejected_logp'] for row in rows)
    write_json(REPORT/'preference/smoke_verified.json',{'status':'PASS','finite_M0_and_candidate':True,'adapter_on_off_different':True,'pairs':2})
    for name,(run,step) in CANDIDATES.items():
        adapter=ROOT/f'artifacts/{run}/checkpoint-{step}'
        for mode in ['development','train_probe']:
            extra=[]
            if mode=='development':pairs,index=ROOT/'data/d3_dev_pairs_swift.jsonl',ROOT/'data/d3_dev_pairs_index.jsonl'
            else:
                pairs,index=ROOT/'data/d3_pairs_v2_swift.jsonl',ROOT/'data/d3_pairs_v2_index.jsonl'
                extra=['--probe-index',ROOT/'data/d3_train_probe_index.jsonl']
            output=REPORT/'preference'/name/mode
            command([*common,'--pairs',pairs,'--index',index,'--adapter',adapter,'--output',output,*extra],REPORT/'execution'/f'{name}_preference_{mode}')
            assert json.loads((output/'summary.json').read_bytes())['pairs']==146

def main():
    os.chdir(WORK)
    for manifest in ['input_files_sha256.json','training_files_sha256.json']:
        for relative,digest in json.loads((WORK/manifest).read_bytes()).items():assert sha(WORK/relative)==digest,relative
    training=ROOT/'reports/d3sd1_training'
    assert (training/'exit').read_text().strip()=='0' and (training/'stage').read_text().strip()=='complete'
    progress=ROOT/'reports/d3sd1_measurement';assert not progress.exists();progress.mkdir()
    try:
        write_json(progress/'started.json',{'utc':stamp()})
        physical=ROOT/'data/d3sd1_dev';assert not physical.exists();physical.mkdir()
        logical=ROOT/'runs/d3sd1_dev';assert not logical.exists();logical.symlink_to(physical,target_is_directory=True)
        models=WORK/'models';assert not models.exists();models.mkdir()
        (progress/'stage').write_text('M0')
        sample('M0',BASE,logical/'M0')
        for name,(run,step) in CANDIDATES.items():
            (progress/'stage').write_text(name)
            model=models/name;adapter=ROOT/f'artifacts/{run}/checkpoint-{step}'
            hashes=merge(name,adapter,model)
            sample(name,model,logical/name)
            remove_measured_merge(name,model,hashes)
        (progress/'stage').write_text('auxiliary_preference')
        preference_checks()
        (progress/'stage').write_text('joint_selection')
        argv=[TRAIN,'-B','-u',ROOT/'scripts/sd1_select.py','--reference',logical/'M0/raw.jsonl']
        for name in CANDIDATES:argv+=['--candidate',f'{name}={logical/name}/raw.jsonl']
        command([*argv,'--out',REPORT/'joint_selection.json'],REPORT/'execution/joint_selection')
        (progress/'stage').write_text('complete')
        write_json(progress/'finished.json',{'status':'PASS','utc':stamp()})
        (progress/'exit').write_text('0\n')
    except BaseException as error:
        write_json(progress/'failure.json',{'utc':stamp(),'type':type(error).__name__,'message':str(error)})
        (progress/'exit').write_text('1\n')
        raise
if __name__=='__main__':main()
