"""Check completed fixed runs and summarize original step records without selecting checkpoints."""
import argparse,csv,json,math,statistics,hashlib
from pathlib import Path
from classify_answers import ROOT,write_json

def sha(p):
    with p.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('run',choices=['d3_full','sd1_a','sd1_b']);args=p.parse_args()
    name=args.run;artifact=ROOT/'artifacts'/name;logs=ROOT/'reports'/name
    records=[json.loads(line) for line in (artifact/'training_observations.jsonl').read_bytes().splitlines()]
    model,=[r for r in records if r['event']=='model'];complete,=[r for r in records if r['event']=='complete']
    steps=[r for r in records if r['event']=='step'];expected=78 if name=='d3_full' else 252
    checkpoints=[39,78] if name=='d3_full' else [252] if name=='sd1_a' else [126,252]
    assert model['language_lora']==252 and model['vision_lora']==0 and model['trainable_tensors']==504
    assert complete['steps']==expected and [r['step'] for r in steps]==list(range(1,expected+1))
    assert complete['examples']==(611 if name=='d3_full' else 2002)*2
    assert sorted(int(d.name.removeprefix('checkpoint-')) for d in artifact.glob('checkpoint-*') if d.is_dir())==checkpoints
    checkpoint_hashes={}
    for step in checkpoints:
        folder=artifact/f'checkpoint-{step}';state=json.loads((folder/'trainer_state.json').read_bytes())
        assert state['global_step']==step
        checkpoint_hashes[str(step)]={f.name:sha(f) for f in folder.iterdir() if f.is_file()}
    native=json.loads((artifact/'args.json').read_bytes())
    assert native['max_steps']==-1 and native['num_train_epochs']==2 and not native['adapters'] and native['resume_from_checkpoint'] is None
    assert native['eval_strategy']=='no' and not native['val_dataset']
    result={'status':'PASS','run':name,'steps':expected,'examples':complete['examples'],'checkpoints':checkpoints,
            'training_seconds':complete['wall_seconds'],'step_seconds_mean':statistics.mean(r['seconds'] for r in steps),
            'step_seconds_median':statistics.median(r['seconds'] for r in steps),
            'max_allocated_gib':max(r['allocated_bytes'] for r in steps)/2**30,
            'max_reserved_gib':max(r['reserved_bytes'] for r in steps)/2**30,
            'first_step':steps[0],'last_step':steps[-1],'checkpoint_sha256':checkpoint_hashes,'actual_args_sha256':sha(artifact/'args.json')}
    fields=list(dict.fromkeys(key for row in steps for key in row if key!='event'))
    with (logs/'step_metrics.csv').open('x',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(steps)
    write_json(logs/'training_summary.json',result)
    print(json.dumps(result),flush=True)
if __name__=='__main__':main()
