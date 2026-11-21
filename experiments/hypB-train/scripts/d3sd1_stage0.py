"""Five SD1 SFT encodings and strict checks of the separate eight-response GPU smoke."""
import argparse,json,os,math
from pathlib import Path
from classify_answers import ROOT,WORKSPACE,read_rows,write_json
from sample_m0 import CONFIG,MARKERS,example_for,prompt_input,load_processor,request_seed,seed_index,sha
from reward_v2 import reward

BASE=Path('/workspace/hf_cache/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/ebb281ec70b05090aa6165b016eac8ec08e71b17')
OUT=ROOT/'reports/d3sd1_stage0'
def sft():
    import torch,yaml
    from swift.llm import get_model_tokenizer,get_template,load_dataset
    torch.set_num_threads(4);os.chdir(WORKSPACE)
    refs=read_rows(ROOT/'data/sd1_train_index.jsonl');data=read_rows(ROOT/'data/sd1_train_swift.jsonl')
    assert len(refs)==len(data)==2002
    longest=max(range(len(refs)),key=lambda n:refs[n]['prompt_tokens']+refs[n]['output_tokens']+1)
    selected=sorted({longest,*range(4)})
    if len(selected)<5:selected.append(4)
    cfg=yaml.safe_load(CONFIG.read_text())
    independent=load_processor(BASE,cfg)
    model,processor=get_model_tokenizer(str(BASE),model_type='qwen3_vl',load_model=False,use_hf=True)
    assert model is None
    template=get_template('qwen3_vl',processor,max_length=10240,truncation_strategy='raise',loss_scale='default')
    template.set_mode('train')
    loaded,_=load_dataset(str(ROOT/'data/sd1_train_swift.jsonl'),strict=True,use_hf=True,shuffle=False,remove_unused_columns=False)
    pool={r['row']:r for r in read_rows(ROOT/'data/r1_pool.jsonl')};checks=[]
    for n in selected:
        ref=refs[n];item=pool[ref['row']]
        prepared,prompt,_=prompt_input(example_for(item,None),WORKSPACE,cfg,independent)
        for image in prepared['multi_modal_data']['image']:image.close()
        actual=template.encode(loaded[n]);response=data[n]['messages'][-1]['content']
        completion=processor.tokenizer.encode(response+'<|im_end|>\n',add_special_tokens=False)
        assert len(prompt)==ref['prompt_tokens']
        assert actual['input_ids']==prompt+completion
        assert actual['labels']==[-100]*len(prompt)+completion
        assert len(actual['input_ids'])<=10240
        checks.append({'example':n,'row':ref['row'],'prompt_tokens':len(prompt),'response_tokens':len(completion),
                       'total_tokens':len(actual['input_ids']),'longest_included':n==longest,'ids_match':True,'response_only_labels':True})
        print('SD1_SFT_TOKEN_CHECK',n,ref['row'],len(actual['input_ids']),'PASS',flush=True)
    assert len(checks)==5 and max(c['total_tokens'] for c in checks)==9366
    write_json(OUT/'sft_token_checks.json',{'status':'PASS','checks':checks,'model_weights_loaded':False})
def smoke():
    selected=read_rows(ROOT/'data/d3_dev.jsonl')[:2];items={r['row']:r for r in selected}
    folder=ROOT/'data/d3sd1_smoke_M0';raw=read_rows(folder/'raw.jsonl')
    expected={(row,j) for row in items for j in range(4,8)};seen=set()
    for r in raw:
        key=r['row'],r['repeat'];assert key in expected and key not in seen;seen.add(key)
        item=items[r['row']]
        assert r['seed']==request_seed(seed_index(item),r['repeat'])
        assert r['prompt_tokens']==item['prompt_tokens'] and r['finish_reason'] in ('stop','length')
        assert 0<r['output_tokens']<=8192 and (r['finish_reason']!='length' or r['output_tokens']==8192)
        assert (r['reward'],r['reward_reason'])==reward(r['raw_text'],r['finish_reason'],item)
        assert r['marker_count']==len(MARKERS.findall(r['raw_text']))
    assert seen==expected and len(raw)==8
    manifest=json.loads((folder/'manifest.json').read_bytes())
    assert manifest['repeat_start']==4 and manifest['k']==4 and manifest['questions_sha256']==sha(ROOT/'data/d3_dev.jsonl')
    assert manifest['reward_version']=='v2'
    write_json(OUT/'smoke_checks.json',{'status':'PASS','responses':8,'questions':list(items),'repeat_range':[4,7],
               'raw_sha256':sha(folder/'raw.jsonl'),'manifest_sha256':sha(folder/'manifest.json'),'all_seeds_prompt_tokens_rewards_match':True})
    print('DEVELOPMENT_SMOKE_PASS',8,flush=True)
if __name__=='__main__':
    os.environ.update(MIN_PIXELS='1003520',MAX_PIXELS='4014080',IMAGE_MIN_TOKEN_NUM='980',IMAGE_MAX_TOKEN_NUM='3920',SPATIAL_MERGE_SIZE='2')
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['sft','smoke']);args=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    (sft if args.stage=='sft' else smoke)()
