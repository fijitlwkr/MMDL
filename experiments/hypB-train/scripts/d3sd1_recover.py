"""Verify and recover the completed archive without overwriting local files."""
import hashlib,json,shutil,tarfile
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPECTED='c11e831073f6c23bf631fe82d0f362bbe172f0032a2b25ce773512a5e546db89'
def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def main():
    archive=ROOT/'reports/d3sd1_upload/d3sd1_completed.tar.gz'
    assert archive.stat().st_size==625684909 and sha(archive)==EXPECTED
    receipt_name='reports/d3sd1_dev/recovery_sha256.json'
    written=existing=0
    with tarfile.open(archive) as tar:
        members=tar.getmembers();assert len({m.name for m in members})==len(members)
        hashes=json.load(tar.extractfile(receipt_name))
        assert len(hashes)==264 and set(hashes)=={m.name for m in members if m.name!=receipt_name}
        for m in members:
            path=(ROOT/m.name).resolve()
            assert m.isfile() and path.is_relative_to(ROOT.resolve()) and not path.is_symlink(),m.name
            if path.exists():
                with tar.extractfile(m) as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
                assert path.is_file() and sha(path)==digest,('existing local file differs',m.name)
        for m in members:
            path=(ROOT/m.name).resolve()
            if path.exists():existing+=1;continue
            path.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(m) as source,path.open('xb') as dest:shutil.copyfileobj(source,dest)
            written+=1
    for relative,digest in hashes.items():assert sha(ROOT/relative)==digest,relative
    result={'status':'PASS','verified_utc':datetime.now(timezone.utc).isoformat(),'files_verified':len(hashes),
            'archive_sha256':EXPECTED,'archive_bytes':archive.stat().st_size,'new_files_written':written,
            'existing_identical_files_preserved':existing,'remote_and_local_archive_sha256_equal':True,
            'remote_and_local_file_sha256_equal':True}
    path=ROOT/'reports/d3sd1_dev/recovery_verified.json'
    with path.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps(result),flush=True)
if __name__=='__main__':main()
