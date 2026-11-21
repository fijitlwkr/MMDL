"""Stage only the fixed external pool images and verify the new GPU input tree."""
from collections import Counter
import csv,json,hashlib,shutil,os
from pathlib import Path

WORKSPACE=Path('/workspace/train_D3_SD1')
ROOT=WORKSPACE/'work/train_RL_20261106'
REV='1833bac3be047aa8bd146492436323bb7c14092a'
BASE_REV='ebb281ec70b05090aa6165b016eac8ec08e71b17'
def sha(p):
    with p.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()
def main():
    os.chdir(WORKSPACE)
    manifest=json.loads((WORKSPACE/'input_files_sha256.json').read_bytes())
    for name,digest in manifest.items():assert sha(WORKSPACE/name)==digest,name
    pool=[json.loads(line) for line in (ROOT/'data/r1_pool.jsonl').read_bytes().splitlines() if line]
    assert len(pool)==1500 and Counter(r['origin'] for r in pool)=={'A':1360,'B':139,'C':1}
    with (ROOT/'data/A_image_manifest.csv').open(encoding='utf-8-sig',newline='') as handle:
        a={r['path']:r for r in csv.DictReader(handle)}
    with (ROOT/'data/images_B_manifest.csv').open(encoding='utf-8-sig',newline='') as handle:
        bc={r['row']:r for r in csv.DictReader(handle)}
    from huggingface_hub import hf_hub_download,try_to_load_from_cache
    from PIL import Image
    sources=Counter();evidence=[]
    for number,item in enumerate(pool,1):
        image,=item['images'];relative=image['path'];target=WORKSPACE/relative
        assert target.resolve().is_relative_to(WORKSPACE)
        source='uploaded_BC'
        if item['origin']=='A':
            prefix='work/train_data_B_20261023/final_v5_tech_20261025/'
            assert relative.startswith(prefix)
            name=relative.removeprefix(prefix);entry=a[name]
            assert entry['row']==item['row'] and entry['sha256']==image['sha256'] and int(entry['bytes'])==image['bytes']
            assert not target.exists()
            staged=Path('/workspace/train_RL_20261106/image_tree')/relative
            if staged.is_file():
                candidate=staged;source='existing_pinned_image_tree'
            else:
                cached=try_to_load_from_cache('MMDL-team4/hypB-train-data',name,repo_type='dataset',revision=REV)
                if not isinstance(cached,str) or not Path(cached).is_file():
                    cached=hf_hub_download('MMDL-team4/hypB-train-data',name,repo_type='dataset',revision=REV)
                    source='pinned_HF_download'
                else:source='pinned_HF_cache'
                candidate=Path(cached)
            assert candidate.stat().st_size==image['bytes'] and sha(candidate)==image['sha256']
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(candidate,target)
        else:
            entry=bc[item['row']]
            assert entry['path']==relative and entry['sha256']==image['sha256']
        assert target.stat().st_size==image['bytes'] and sha(target)==image['sha256'],relative
        with Image.open(target) as im:assert list(im.size)==[image['width'],image['height']]
        sources[source]+=1;evidence.append({'row':item['row'],'origin':item['origin'],'path':relative,'sha256':image['sha256'],'source':source})
        if number%150==0:print('D3SD1_IMAGE_OK',number,flush=True)
    base=Path(os.environ['HF_HOME'])/'hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots'/BASE_REV
    expected={'model-00001-of-00002.safetensors':'30a01a0556622645a3cce87b655bbbbbc1f170c196099f1b666c93202c3339a9',
              'model-00002-of-00002.safetensors':'046296a2a387efb43b0c997d5833c789604d168834f6e0d3064bf7bb13d002a6'}
    for name,digest in expected.items():assert sha(base/name)==digest,name
    out=ROOT/'reports/d3sd1_stage0';out.mkdir(parents=True,exist_ok=True)
    (out/'input_image_verification.json').write_text(json.dumps({'status':'PASS','input_files':len(manifest),'images':evidence,
        'origins':dict(Counter(r['origin'] for r in pool)),'image_sources':dict(sources),'dataset_revision':REV,
        'base_revision':BASE_REV,'base_sha256':expected},indent=2)+'\n')
    print('D3SD1_INPUTS_PASS',len(manifest),dict(sources),flush=True)
if __name__=='__main__':main()
