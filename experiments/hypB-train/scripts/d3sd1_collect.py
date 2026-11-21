"""Package completed local-only D3/SD1 artifacts with a per-file SHA-256 receipt."""
import hashlib,json,tarfile
from pathlib import Path
from classify_answers import ROOT,write_json

def sha(p):
    with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    assert (ROOT/'reports/d3sd1_measurement/exit').read_text().strip()=='0'
    files={}
    def add_tree(source,destination):
        for p in sorted(source.rglob('*')):
            if p.is_file():
                assert not p.is_symlink()
                name=str(Path(destination)/p.relative_to(source)).replace('\\','/')
                assert name not in files
                files[name]=p
    for name,run,step in [('d3_e1','d3_full',39),('d3_e2','d3_full',78),('sd1_a','sd1_a',252),('sd1_b','sd1_b',126),('sd1_c','sd1_b',252)]:
        add_tree(ROOT/f'artifacts/{run}/checkpoint-{step}',f'adapter/{name}')
    for run in ['d3_full','sd1_a','sd1_b']:
        add_tree(ROOT/'reports'/run,f'reports/{run}')
        for p in (ROOT/'artifacts'/run).iterdir():
            if p.is_file():files[f'reports/{run}/artifact_root/{p.name}']=p
    for folder in ['d3sd1_stage0','d3sd1_training','d3sd1_measurement','d3sd1_dev']:
        add_tree(ROOT/'reports'/folder,f'reports/{folder}')
    # Follow the known data directory explicitly; runs/ is a compatibility symlink.
    add_tree(ROOT/'data/d3sd1_dev','runs/d3sd1_dev')
    hashes={name:sha(p) for name,p in files.items()}
    receipt=ROOT/'recovery_sha256.json';assert not receipt.exists()
    write_json(receipt,hashes)
    archive=ROOT.parents[1]/'d3sd1_completed.tar.gz';assert not archive.exists()
    with tarfile.open(archive,'w:gz',compresslevel=1) as tar:
        for name,p in files.items():tar.add(p,arcname=name,recursive=False)
        tar.add(receipt,arcname='reports/d3sd1_dev/recovery_sha256.json',recursive=False)
    result={'archive':str(archive),'sha256':sha(archive),'bytes':archive.stat().st_size,'files':len(files)}
    write_json(ROOT/'recovery_archive.json',result)
    print(json.dumps(result),flush=True)
if __name__=='__main__':main()
