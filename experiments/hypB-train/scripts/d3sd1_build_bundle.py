"""Package frozen training/dev inputs without including any validation dataset."""
import csv,hashlib,json,tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORKSPACE=ROOT.parents[1]
def sha(p):
    with p.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()
def main():
    files={}
    def add(p,name=None):
        p=p.resolve(strict=True);name=name or p.relative_to(WORKSPACE).as_posix()
        assert p.is_file() and name not in files
        files[name]=p
    v2=json.loads((ROOT/'reports/d3_artifacts_v2_sha256.json').read_bytes())
    dev=json.loads((ROOT/'reports/d3_dev_pairs_sha256.json').read_bytes())
    for name in ['data/d3_pairs_v2_swift.jsonl','data/d3_pairs_v2_index.jsonl','scripts/d3_config_v2.json']:
        assert sha(ROOT/name)==v2[name]
    for name in ['data/d3_dev_pairs_swift.jsonl','data/d3_dev_pairs_index.jsonl','data/d3_train_probe_index.jsonl','scripts/d3_pair_preference.py']:
        assert sha(ROOT/name)==dev[name]
    for line in (ROOT/'reports/sd1_artifacts_sha256.txt').read_text().splitlines():
        if line.strip():
            digest,name=line.split(' ',1);assert sha(ROOT/name.strip().lstrip('*'))==digest
    for name in ['d3_pairs_v2_swift.jsonl','d3_pairs_v2_index.jsonl','d3_dev.jsonl','d3_split.json','r1_pool.jsonl',
                 'sd1_train_swift.jsonl','sd1_train_index.jsonl','d3_dev_pairs_swift.jsonl','d3_dev_pairs_index.jsonl',
                 'd3_train_probe_index.jsonl','images_B_manifest.csv']:
        add(ROOT/'data'/name)
    for name in ['classify_answers.py','sample_m0.py','reward.py','reward_v2.py','d3_sample_dev.py','d3_pair_preference.py',
                 'd3_select.py','d3_select_v2.py','d3_prepare.py','build_dpo_pairs.py','check_dpo_pairs.py','check_d2p_pairs.py',
                 'build_groups.py','dpo_train.py','dpo_config.json','d3_config_v2.json','sd1_config_a.json','sd1_config_b.json',
                 'd1_pilot.py','d1_full.py','d3sd1_stage_inputs.py','d3sd1_stage0.py','d3sd1_stage0.sh']:
        add(ROOT/'scripts'/name)
    for folder in ['frozen_v2','frozen_generation']:
        for p in sorted((ROOT/'scripts'/folder).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':add(p)
    for name in ['HANDOFF_D3_SD1_gpu.md','PLAN_D3.md','PLAN_SD1.md']:add(ROOT/name)
    for name in ['D3_STAGE1_V2_REPORT.md','D3_DEV_PAIRS_REPORT.md','D3_STAGE1_REVIEW.md','sd1_data_validation.json',
                 'd3_dev_dry_run.json','d3_artifacts_v2_sha256.json','d3_dev_pairs_sha256.json','sd1_artifacts_sha256.txt']:
        add(ROOT/'reports'/name)
    add(ROOT/'runs/full_k4/groups.json')
    add(WORKSPACE/'work/train_data_B_20261023/final_v5_tech_20261025/image_manifest.csv','work/train_RL_20261106/data/A_image_manifest.csv')
    with (ROOT/'data/images_B_manifest.csv').open(encoding='utf-8-sig',newline='') as handle:
        bc=list(csv.DictReader(handle))
    assert len(bc)==140
    for row in bc:
        p=WORKSPACE/row['path'];assert sha(p)==row['sha256'];add(p)
    source=WORKSPACE/'work/hypB-train-git/assignment/experiments/hypB_train/yoonseok'
    for name in ['train.py','train_config.json','merge.py','requirements-train.txt']:
        add(source/name,'sources/e1/'+name)
    folder=ROOT/'reports/d3sd1_upload';folder.mkdir(exist_ok=False)
    hashes={name:sha(p) for name,p in files.items()}
    manifest=folder/'input_files_sha256.json';manifest.write_text(json.dumps(hashes,indent=2)+'\n',encoding='utf-8')
    archive=folder/'inputs.tar.gz'
    with tarfile.open(archive,'w:gz',compresslevel=1) as tar:
        for name,p in files.items():tar.add(p,arcname=name,recursive=False)
        tar.add(manifest,arcname='input_files_sha256.json',recursive=False)
    receipt={'archive_sha256':sha(archive),'archive_bytes':archive.stat().st_size,'files':len(files),
             'manifest_sha256':sha(manifest),'validation_materials_included':False}
    (folder/'upload_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt),flush=True)
if __name__=='__main__':main()
