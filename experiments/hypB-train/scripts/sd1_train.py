"""E1 SFT launcher adapted only for fixed SD1 config/data and no holdout/reordering."""
import argparse,json,os
from pathlib import Path

def image_env():
    os.environ.update(MIN_PIXELS='1003520',MAX_PIXELS='4014080',IMAGE_MIN_TOKEN_NUM='980',
                      IMAGE_MAX_TOKEN_NUM='3920',SPATIAL_MERGE_SIZE='2')
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('config','data','image_root','output'):parser.add_argument(key,type=Path)
    args=parser.parse_args();config=json.loads(args.config.read_bytes())
    data,image_root,output=args.data.resolve(strict=True),args.image_root.resolve(strict=True),args.output.resolve()
    if output.exists():parser.error('use a new output directory')
    if len(data.read_bytes().splitlines())!=2002:parser.error('expected the fixed 2002 SD1 examples')
    os.chdir(image_root);image_env()
    import torch
    from swift.llm import TrainArguments
    from swift.plugin import extra_callbacks
    from d3sd1_training import TrainingObserver,verify_config,observed_sft_main
    if torch.cuda.device_count()!=1 or int(os.environ.get('WORLD_SIZE','1'))!=1:
        parser.error('expose exactly one GPU for effective batch size 16')
    output.mkdir(parents=True)
    observer=TrainingObserver(config,2002,'sft');extra_callbacks.append(observer)
    train_args=TrainArguments(**config,dataset=[str(data)],max_steps=-1,output_dir=str(output))
    verify_config(train_args,config,output)
    observed_sft_main(train_args)
if __name__=='__main__':main()
