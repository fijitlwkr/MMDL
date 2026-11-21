"""D1/E1-equivalent parameter, finite-loss, timing and memory observations."""
import json,math,os,re,statistics,time
from pathlib import Path
import torch
from d1_pilot import Observer

def normalized(value):
    if hasattr(value,'value'):value=value.value
    if isinstance(value,torch.dtype):return str(value).removeprefix('torch.')
    return value
def verify_config(args,config,output):
    checks={}
    for key,expected in config.items():
        actual=normalized(getattr(args,key))
        if key=='model' and isinstance(actual,list):same=actual==[expected]
        elif key=='report_to' and expected=='none':same=actual in ('none',[],['none'])
        else:same=actual==expected
        checks[key]={'expected':expected,'actual':actual,'same':same}
        assert same,(key,actual,expected)
    assert args.max_steps==-1 and not args.adapters and args.resume_from_checkpoint is None
    (output/'requested_config.json').write_text(json.dumps(config,indent=2)+'\n')
    (output/'config_check.json').write_text(json.dumps({'status':'PASS','checks':checks,'max_steps':args.max_steps,
        'adapters':args.adapters,'resume_from_checkpoint':args.resume_from_checkpoint},default=str,indent=2)+'\n')

class TrainingObserver(Observer):
    def __init__(self,config,examples,kind,longest_steps=None):
        super().__init__();self.config=config;self.examples=examples;self.kind=kind
        self.steps_per_epoch=math.ceil(examples/config['gradient_accumulation_steps'])
        self.total=self.steps_per_epoch*config['num_train_epochs'];self.expected_longest=longest_steps;self.seen=0
    def on_train_begin(self,args,state,control,model=None,optimizer=None,**kwargs):
        assert state.max_steps==self.total and args.max_steps==-1 and args.num_train_epochs==2
        assert os.environ.get('PYTORCH_CUDA_ALLOC_CONF')=='expandable_segments:True'
        self.log=Path(args.output_dir)/'training_observations.jsonl';self.started=time.monotonic()
        if self.kind=='sft':
            modules={name:module for name,module in model.named_modules() if hasattr(module,'lora_A')}
            allowed={f'{name}.lora_{side}.default.weight' for name in modules for side in ('A','B')}
            trainable={name for name,param in model.named_parameters() if param.requires_grad}
            pattern=r'base_model\.model\.'+self.config['target_regex']
            assert len(modules)==252 and all(re.fullmatch(pattern,name) for name in modules)
            assert trainable==allowed and len(trainable)==504
            for group in optimizer.param_groups:
                assert group['betas']==(0.9,0.999) and group['eps']==1e-8 and group['weight_decay']==0
            self.model_evidence={'language_lora':252,'vision_lora':0,'trainable_tensors':504,'modules':sorted(modules)}
        self.write('model',**self.model_evidence,kind=self.kind,expected_steps=self.total,examples=self.examples,
                   cuda_alloc_conf=os.environ['PYTORCH_CUDA_ALLOC_CONF'])
    def on_log(self,args,state,control,logs=None,**kwargs):
        if not logs or 'loss' not in logs:return
        keys=['loss','grad_norm']
        if self.kind=='dpo':keys+=['rewards/margins','rewards/accuracies','logps/chosen','logps/rejected','nll_loss']
        metrics={key:float(logs[key]) for key in keys}
        metrics['learning_rate']=float(logs['learning_rate'] if 'learning_rate' in logs else kwargs['optimizer'].param_groups[0]['lr'])
        assert all(math.isfinite(v) for v in metrics.values()),(state.global_step,metrics)
        batch=self.config['gradient_accumulation_steps']
        count=(self.examples%batch or batch) if state.global_step%self.steps_per_epoch==0 else batch
        if self.kind=='dpo':
            assert len(self.ref_scores)==count,(state.global_step,len(self.ref_scores),count)
            a,b=zip(*self.ref_scores,strict=True);self.ref_scores.clear()
            metrics.update(ref_chosen_logp=statistics.mean(a),ref_rejected_logp=statistics.mean(b))
        self.seen+=count;record={**self.step_observation,**metrics,'epoch':state.epoch,'examples':count}
        self.metrics.append(record);self.write('step',**record)
        print(f"{self.kind.upper()}_STEP {state.global_step}/{self.total} loss={metrics['loss']:.6f} lr={metrics['learning_rate']:.9g}",flush=True)
    def validate(self):
        assert [r['step'] for r in self.metrics]==list(range(1,self.total+1))
        assert self.seen==self.examples*2 and self.metrics[-1]['epoch']==2
        if self.expected_longest is not None:assert self.longest==self.expected_longest,(self.longest,self.expected_longest)
        self.write('complete',steps=self.total,examples=self.seen,wall_seconds=time.monotonic()-self.started,longest_steps=self.longest)
    def on_train_end(self,args,state,control,**kwargs):
        if self.kind=='sft':self.validate()

def observed_sft_main(args):
    from swift.llm.train.sft import SwiftSft
    class ObservedSFT(SwiftSft):
        def train(self,trainer):
            original=trainer.compute_loss
            def finite_loss(*a,**kw):
                result=original(*a,**kw);loss=result[0] if isinstance(result,tuple) else result
                assert torch.isfinite(loss).all().item(),'Non-finite SFT microbatch loss'
                return result
            trainer.compute_loss=finite_loss
            return super().train(trainer)
    return ObservedSFT(args).main()
