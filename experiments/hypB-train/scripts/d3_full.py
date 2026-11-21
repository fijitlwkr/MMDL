"""Train the fixed D3 order with the unchanged D1 DPO trainer and objective."""
import argparse,json,os,math
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('config','data','image_root','output'):p.add_argument(name,type=Path)
    args=p.parse_args();config=json.loads(args.config.read_bytes())
    data,image_root,output=args.data.resolve(strict=True),args.image_root.resolve(strict=True),args.output.resolve()
    if output.exists():p.error('use a new output directory')
    assert len(data.read_bytes().splitlines())==611
    os.chdir(image_root)
    from dpo_train import arguments,image_env
    image_env()
    import torch
    from swift.plugin import extra_callbacks
    from d1_pilot import ObservedDPO
    from d3sd1_training import TrainingObserver,verify_config
    if torch.cuda.device_count()!=1 or int(os.environ.get('WORLD_SIZE','1'))!=1:p.error('one GPU is required')
    refs=[json.loads(line) for line in data.with_name('d3_pairs_v2_index.jsonl').read_bytes().splitlines()]
    pool={r['row']:r for r in [json.loads(line) for line in data.with_name('r1_pool.jsonl').read_bytes().splitlines()]}
    longest=max(refs,key=lambda r:pool[r['row']]['prompt_tokens']+max(r['chosen_output_tokens']+1,r['rejected_output_tokens']+(0 if r['rejected_reason']=='truncated' else 1)))
    first=longest['pair']//config['gradient_accumulation_steps']+1
    observer=TrainingObserver(config,611,'dpo',[first,first+math.ceil(611/16)])
    extra_callbacks.append(observer);output.mkdir(parents=True)
    train_args=arguments(**config,dataset=[str(data)],max_steps=-1,output_dir=str(output))
    verify_config(train_args,config,output)
    assert train_args.ref_model is None and not train_args.ref_adapters
    ObservedDPO(train_args).main()
if __name__=='__main__':main()
