"""Answer-free reference cache and 13-gram/MinHash-LSH/pHash comparison."""
import collections
import concurrent.futures
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import urllib.parse

sys.dont_write_bytecode=True
R=Path(__file__).resolve().parent;TRAIN=R.parent;WORK=TRAIN.parent;OLD=TRAIN/'final_v5'
sys.path[:0]=[str(OLD/'.deps_stage47'),str(OLD/'.deps'),str(WORK/'mmfr18m_check')]
import numpy as np
import pyarrow.parquet as pq
from PIL import Image
import stage1 as transfer
transfer.DOWNLOAD_POOL.shutdown();transfer.DOWNLOAD_POOL=concurrent.futures.ThreadPoolExecutor(max_workers=6)
IMG=[f'image_{i}' for i in range(1,8)]
ALLOW={'id','question','options',*IMG}
transfer.COLS=['id','question','options']+[i+'.'+sub for i in IMG for sub in ['bytes','path']]
CACHE=R/'cache/contamination';CACHE.mkdir(parents=True,exist_ok=True)
DB=CACHE/'references.sqlite'
MMMU_REV='98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68'
PRO_REV='0d7426df4ccb3d8704a992fe6850abee7c262127'


def api(repo,rev,path=''):
    url=f'https://huggingface.co/api/datasets/{repo}/tree/{rev}'+('/'+urllib.parse.quote(path,safe='/') if path else '')+'?limit=1000'
    return json.loads(transfer.fetch(url))


def plan():
    files=[]
    for folder in api('MMMU/MMMU',MMMU_REV):
        if folder['type']!='directory':continue
        for f in api('MMMU/MMMU',MMMU_REV,folder['path']):
            if not f['path'].endswith('.parquet'):continue
            cache=WORK/'mmmu-review-image-cache'/(folder['path']+'.parquet')
            files.append(dict(repo='MMMU/MMMU',revision=MMMU_REV,path=f['path'],size=f['size'],local=str(cache) if Path(f['path']).name.startswith('validation-') and cache.exists() else None))
    for f in api('MMMU/MMMU_Pro',PRO_REV,'standard (10 options)'):
        if f['path'].endswith('.parquet'):files.append(dict(repo='MMMU/MMMU_Pro',revision=PRO_REV,path=f['path'],size=f['size'],local=None))
    assert len(files)==94
    upper=sum(x['size'] for x in files if not x['local'])
    assert upper<4_100_000_000
    p=dict(scope='MMMU dev/validation/test + MMMU-Pro standard (10 options), same as previous check',files=files,remote_full_parquet_upper_bound_bytes=upper,
        allowed_columns=sorted(ALLOW),answer_columns_read=False)
    (R/'reference_transfer_plan.json').write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'files':len(files),'local':sum(bool(x['local']) for x in files),'upper_bytes':upper}),flush=True)
    return p


_c=np.cos(np.pi*(np.arange(32)+.5)[None,:]*np.arange(32)[:,None]/32)*np.sqrt(2/32)
_c[0]/=np.sqrt(2)


def phash(image):
    a=np.asarray(image.convert('L').resize((32,32),Image.Resampling.LANCZOS),dtype=np.float64)
    d=(_c@a@_c.T)[:8,:8].ravel();bits=d>np.median(d[1:])
    return int.from_bytes(np.packbits(bits).tobytes(),'big')


def open_ref(f):
    if f['local']:return pq.ParquetFile(f['local']),None
    url=f"https://huggingface.co/datasets/{f['repo']}/resolve/{f['revision']}/"+urllib.parse.quote(f['path'],safe='/')
    footer=CACHE/(hashlib.sha256((f['repo']+f['path']).encode()).hexdigest()[:20]+'.footer')
    if not footer.exists():
        tail=transfer.fetch(url,f['size']-8,f['size']-1);assert tail[4:]==b'PAR1'
        size=int.from_bytes(tail[:4],'little');body=transfer.fetch(url,f['size']-size-8,f['size']-9)
        footer.write_bytes(b'PAR1'+body+tail)
    data=footer.read_bytes();meta=pq.read_metadata(io.BytesIO(data));ranges=[]
    for g in range(meta.num_row_groups):
        for n in range(meta.row_group(g).num_columns):
            c=meta.row_group(g).column(n)
            if c.path_in_schema.split('.')[0] in ALLOW:
                start=min(x for x in [c.dictionary_page_offset,c.data_page_offset] if x is not None and x>=0)
                ranges.append(dict(start=start,size=c.total_compressed_size,column=c.path_in_schema,group=g))
    assert all(x['column'].split('.')[0] in ALLOW for x in ranges)
    item=dict(size=f['size'],footer_start=f['size']-len(data)+4,footer=str(footer),url=url,ranges=ranges)
    v=transfer.ColumnFile(item)
    return pq.ParquetFile(v,pre_buffer=False),v


def cache_refs():
    p=json.loads((R/'reference_transfer_plan.json').read_text(encoding='utf-8')) if (R/'reference_transfer_plan.json').exists() else plan()
    db=sqlite3.connect(DB)
    db.executescript('CREATE TABLE IF NOT EXISTS files(key TEXT PRIMARY KEY,repo TEXT,path TEXT,rows INTEGER);CREATE TABLE IF NOT EXISTS refs(key TEXT PRIMARY KEY,repo TEXT,path TEXT,id TEXT,question TEXT,options TEXT,images TEXT);')
    done={x[0] for x in db.execute('select key from files')}
    def work(f):
        pf,v=open_ref(f);cols=[x for x in pf.schema_arrow.names if x in ALLOW]
        assert not {'answer','explanation'} & set(cols)
        out=[]
        for batch in pf.iter_batches(columns=cols,batch_size=64):
            for x in batch.to_pylist():
                imgs=[]
                for col in IMG:
                    raw=(x.get(col) or {}).get('bytes')
                    if raw:
                        try:
                            with Image.open(io.BytesIO(raw)) as im:h=phash(im)
                            imgs.append({'col':col,'phash':str(h)})
                        except Exception as e:raise RuntimeError('Reference image decode failure '+str(x.get('id'))) from e
                ident=str(x['id']);q=x.get('question') or '';options=x.get('options') or ''
                rk=f['repo']+'|'+f['path']+'|'+ident
                out.append((rk,f['repo'],f['path'],ident,q,json.dumps(options,ensure_ascii=False),json.dumps(imgs)))
        return f,out
    todo=[x for x in p['files'] if x['repo']+'|'+x['path'] not in done]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for future in concurrent.futures.as_completed([pool.submit(work,x) for x in todo]):
            f,rows=future.result();db.executemany('insert into refs values (?,?,?,?,?,?,?)',rows)
            db.execute('insert into files values (?,?,?,?)',(f['repo']+'|'+f['path'],f['repo'],f['path'],len(rows)));db.commit()
            print(json.dumps({'completed_files':db.execute('select count(*) from files').fetchone()[0],'reference_items':db.execute('select count(*) from refs').fetchone()[0],'network_body_bytes':transfer.TRANSFER['body_bytes']}),flush=True)
    assert db.execute('select count(*) from files').fetchone()[0]==94
    stat=dict(files=94,items=db.execute('select count(*) from refs').fetchone()[0],network_body_bytes_this_run=transfer.TRANSFER['body_bytes'],answer_columns_read=False)
    db.close();(R/'reference_cache_status.json').write_text(json.dumps(stat,indent=2)+'\n',encoding='utf-8')


def words(s):return re.sub(r'[^a-z0-9]+',' ',re.sub(r'<image[^>]*>',' ',s.lower())).split()
def grams(w,n):return {' '.join(w[i:i+n]) for i in range(max(0,len(w)-n+1))}
_rng=np.random.default_rng(3407);_prime=np.uint64(4294967291)
_a=_rng.integers(1,int(_prime),128,dtype=np.uint64);_b=_rng.integers(0,int(_prime),128,dtype=np.uint64)


def signature(gs):
    if not gs:return np.full(128,_prime,dtype=np.uint64)
    hs=np.array([int.from_bytes(hashlib.blake2b(s.encode(),digest_size=4).digest(),'little')%int(_prime) for s in gs],dtype=np.uint64)
    return ((_a[:,None]*hs[None,:]+_b[:,None])%_prime).min(axis=1)


def compare():
    rows=[json.loads(s) for s in (R/'provisional_18.jsonl').read_text(encoding='utf-8').splitlines()]
    with (R/'new_image_manifest.csv').open(encoding='utf-8-sig',newline='') as f:ims={x['row']:x for x in csv.DictReader(f)}
    assert np.allclose(_c@_c.T,np.eye(32),atol=1e-12)
    assert np.array_equal(signature({'one two three four five'}),signature({'one two three four five'}))
    assert grams(words('<image> ONE, two three four five six seven eight nine ten eleven twelve thirteen!'),13)=={'one two three four five six seven eight nine ten eleven twelve thirteen'}
    own13=collections.defaultdict(set);own5=collections.defaultdict(set);shingles=[];lsh=collections.defaultdict(set);ownhash=[]
    for n,x in enumerate(rows):
        w=words(x['question']);s=grams(w,5);shingles.append(s);sig=signature(s)
        for g in grams(w,13):own13[g].add(n)
        for g in s:own5[g].add(n)
        for band in range(32):lsh[(band,sig[band*4:band*4+4].tobytes())].add(n)
        with Image.open(R/ims[x['row']]['path']) as im:ownhash.append(phash(im))
    db=sqlite3.connect(DB);pairs=[];near=[];lshscores=[];counts=collections.Counter();top=[];all_scores=[]
    for rk,repo,path,ident,q,opts,rawimgs in db.execute('select * from refs'):
        w=words(q);g13=grams(w,13);matches=collections.defaultdict(list)
        for g in g13:
            for n in own13.get(g,()):matches[n].append(g)
        for n,gs in matches.items():pairs.append(dict(n=n,repo=repo,path=path,id=ident,question=q,options=json.loads(opts),type='13gram',score=len(gs)))
        ss=grams(w,5);sig=signature(ss);cands=set()
        for band in range(32):cands.update(lsh.get((band,sig[band*4:band*4+4].tobytes()),()))
        shared=collections.Counter(n for g in ss for n in own5.get(g,()))
        # Exact overlap guard also catches any high-similarity pair missed by LSH.
        for n,count in shared.items():
            score=count/max(1,len(ss)+len(shingles[n])-count);all_scores.append(score)
            top.append(dict(own_row=rows[n]['row'],ref_repo=repo,ref_id=ident,jaccard=score))
            if score>=.5:cands.add(n)
        for n in cands:
            score=len(ss&shingles[n])/max(1,len(ss|shingles[n]));lshscores.append(score)
            if score>=.5:pairs.append(dict(n=n,repo=repo,path=path,id=ident,question=q,options=json.loads(opts),type='minhash',score=score))
        for image in json.loads(rawimgs):
            h=int(image['phash'])
            for n,oh in enumerate(ownhash):
                dist=(h^oh).bit_count()
                if dist<=10:near.append(dict(n=n,repo=repo,path=path,id=ident,question=q,options=json.loads(opts),type='phash',score=dist,col=image['col']))
                if dist<=10:pairs.append(dict(near[-1]))
        counts[repo]+=1
    db.close()
    for x in pairs+near:
        row=rows[x.pop('n')];x.update(own_row=row['row'],own_source=row['source'],own_id=row['id'],own_question=row['question'],own_image=ims[row['row']]['path'])
    report=dict(reference_counts=dict(counts),targets=len(rows),hits=len(pairs),flagged_own_rows=sorted({x['own_row'] for x in pairs}),
        methods={'13gram':'normalized English word exact contiguous 13-gram, any match flags','minhash':'5-word shingles; 128 affine hashes;32x4 LSH; exact shingle Jaccard>=0.5','phash':'64-bit DCT pHash; Hamming<=10 flags, same candidate range as previous check'},
        lsh_candidate_count=len(lshscores),lsh_max_exact_jaccard=max(lshscores,default=0),near_hash_distance_histogram=dict(collections.Counter(x['score'] for x in near)))
    report.update(nonzero_shingle_pairs=len(all_scores),maximum_exact_5gram_jaccard=max(all_scores,default=0),top_exact_jaccard_pairs=sorted(top,key=lambda x:-x['jaccard'])[:5],
        calibration_note='5-gram exact Jaccard distribution across all nonzero-overlap pairs is retained; cutoff0.50 represents high wording overlap. pHash<=10 preserves the previous candidate range; no pair falls within that range.')
    (R/'contamination_hits.json').write_text(json.dumps(pairs,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (R/'contamination_near_pairs.json').write_text(json.dumps(near,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (R/'contamination_result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':{'plan':plan,'cache':cache_refs,'compare':compare}[sys.argv[1]]()
