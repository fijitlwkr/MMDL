"""가설 B 학습 3,000건(+holdout 300) vs MMMU(dev/val/test)·MMMU-Pro standard(10) 이미지 pHash + 질문 n-gram 대조.

- MMMU·MMMU-Pro는 id·question·options(Pro)·image_1~7 열만 원격 범위 읽기로 가져온다. 정답·해설 열은 읽지 않는다.
- 대조 이미지는 디스크에 저장하지 않고 pHash만 계산한다. 가까운 쌍(해밍 거리 <= SAVE_DIST)만 사람 확인용으로 저장한다.
"""
import csv, io, json, re, sys, time, hashlib, collections
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import numpy as np
import fsspec, pyarrow.parquet as pq
from PIL import Image
from scipy.fft import dct

ROOT = Path(__file__).resolve().parent
FINAL = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / 'final_v5'
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT
MMMU_REV = '98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68'
PRO_REV = '0d7426df4ccb3d8704a992fe6850abee7c262127'
SAVE_DIST = 10
IMG_COLS = [f'image_{i}' for i in range(1, 8)]
fs = fsspec.filesystem('https')
log = open(OUT / 'run.log', 'a', encoding='utf-8')


def say(*a):
    msg = time.strftime('%H:%M:%S ') + ' '.join(str(x) for x in a)
    print(msg, flush=True)
    log.write(msg + '\n'); log.flush()


def phash(img):
    g = img.convert('L').resize((32, 32), Image.LANCZOS)
    a = np.asarray(g, dtype=np.float64)
    d = dct(dct(a, axis=0, norm='ortho'), axis=1, norm='ortho')[:8, :8].flatten()
    med = np.median(d[1:])
    bits = d > med
    return int(np.packbits(bits).view('>u8')[0])


def norm_words(t):
    t = re.sub(r'<image[^>]*>', ' ', (t or '').lower())
    return re.sub(r'[^a-z0-9]+', ' ', t).split()


def grams(w, n):
    return {' '.join(w[i:i + n]) for i in range(len(w) - n + 1)}


def api_tree(repo, rev, path=''):
    url = f'https://huggingface.co/api/datasets/{repo}/tree/{rev}' + (f'/{path}' if path else '')
    return json.loads(fs.cat(url))


def list_files():
    files = []
    for d in api_tree('MMMU/MMMU', MMMU_REV):
        if d['type'] != 'directory':
            continue
        for f in api_tree('MMMU/MMMU', MMMU_REV, d['path']):
            if f['path'].endswith('.parquet'):
                files.append(('MMMU/MMMU', MMMU_REV, f['path']))
    for f in api_tree('MMMU/MMMU_Pro', PRO_REV, 'standard (10 options)'):
        if f['path'].endswith('.parquet'):
            files.append(('MMMU/MMMU_Pro', PRO_REV, f['path']))
    return files


def read_ref(item):
    repo, rev, path = item
    url = f'https://huggingface.co/datasets/{repo}/resolve/{rev}/' + path.replace(' ', '%20')
    for attempt in range(4):
        try:
            with fs.open(url, block_size=2 ** 22) as f:
                pf = pq.ParquetFile(f)
                names = pf.schema_arrow.names
                cols = [c for c in ['id', 'question', 'options'] + IMG_COLS if c in names]
                assert not any(c in cols for c in ('answer', 'explanation'))
                rows = []
                for rg in range(pf.num_row_groups):
                    t = pf.read_row_group(rg, columns=cols).to_pylist()
                    for r in t:
                        imgs = []
                        for c in IMG_COLS:
                            v = r.get(c)
                            if v and v.get('bytes'):
                                try:
                                    im = Image.open(io.BytesIO(v['bytes']))
                                    imgs.append((c, phash(im), v['bytes']))
                                except Exception:
                                    pass
                        rows.append(dict(repo=repo, path=path, id=r.get('id'), question=r.get('question') or '',
                                         options=r.get('options') or '', imgs=imgs))
                return rows
        except Exception as e:
            say('retry', path, attempt, repr(e)[:120])
            time.sleep(3 * (attempt + 1))
    raise RuntimeError('failed ' + path)


def main():
    rows = [json.loads(l) for l in open(FINAL / 'handoff_rows.jsonl', encoding='utf-8')]
    say('train/holdout rows', len(rows), collections.Counter(r.get('role') for r in rows))
    man = list(csv.DictReader(open(FINAL / 'image_manifest.csv', encoding='utf-8')))
    mine = []
    for m in man:
        im = Image.open(FINAL / m['path'])
        mine.append(dict(role=m['role'], row=m['row'], source=m['source'], id=m['id'], path=m['path'], h=phash(im)))
    H = np.array([m['h'] for m in mine], dtype=np.uint64)
    say('own phash', len(mine))
    qtext = {(r['source'], str(r['id'])): r.get('question', '') for r in rows}
    files = list_files()
    say('reference files', len(files), collections.Counter(f[0] for f in files),
        collections.Counter(f[2].split('/')[-1].split('-')[0] for f in files if f[0] == 'MMMU/MMMU'))
    ref_text = []
    near = []
    (OUT / 'ref_images').mkdir(exist_ok=True)
    nimg = 0
    with ThreadPoolExecutor(6) as ex:
        futs = {ex.submit(read_ref, f): f for f in files}
        for k, fu in enumerate(as_completed(futs), 1):
            for r in fu.result():
                ref_text.append((r['repo'], r['path'], r['id'], r['question'] + ' ' + str(r['options'])))
                for col, h, b in r['imgs']:
                    nimg += 1
                    d = np.bitwise_count(H ^ np.uint64(h))
                    for i in np.nonzero(d <= SAVE_DIST)[0]:
                        name = hashlib.sha1(f"{r['repo']}|{r['id']}|{col}".encode()).hexdigest()[:16] + '.png'
                        p = OUT / 'ref_images' / name
                        if not p.exists():
                            Image.open(io.BytesIO(b)).convert('RGB').save(p)
                        near.append(dict(dist=int(d[i]), own_role=mine[i]['role'], own_row=mine[i]['row'],
                                         own_source=mine[i]['source'], own_id=mine[i]['id'], own_image=mine[i]['path'],
                                         ref_repo=r['repo'], ref_file=r['path'], ref_id=r['id'], ref_col=col,
                                         ref_image='ref_images/' + name,
                                         own_question=qtext.get((mine[i]['source'], mine[i]['id']), '')[:300],
                                         ref_question=r['question'][:300]))
            if k % 25 == 0:
                say('files', k, '/', len(files), 'ref images', nimg, 'near', len(near))
    say('done download; ref items', len(ref_text), 'ref images', nimg, 'near pairs', len(near))
    # 텍스트: 8-gram 포함률 (대조 문항 기준) + 13-gram 정확 일치
    idx8 = collections.defaultdict(set)
    ref_g8 = []
    for j, (_, _, _, t) in enumerate(ref_text):
        g = grams(norm_words(t), 8)
        ref_g8.append(len(g))
        for x in g:
            idx8[x].add(j)
    text_hits = []
    for r in rows:
        w = norm_words(r.get('question', ''))
        g8 = grams(w, 8)
        c = collections.Counter()
        for x in g8:
            for j in idx8.get(x, ()):
                c[j] += 1
        best = None
        for j, n in c.most_common(3):
            cont = n / max(ref_g8[j], 1)
            if best is None or cont > best[0]:
                best = (cont, n, j)
        if best:
            cont, n, j = best
            text_hits.append(dict(role=r.get('role'), source=r['source'], id=r['id'], shared_8gram=n,
                                  containment=round(cont, 3), ref_repo=ref_text[j][0], ref_file=ref_text[j][1],
                                  ref_id=ref_text[j][2], own_question=r.get('question', '')[:300],
                                  ref_question=ref_text[j][3][:300]))
    text_hits.sort(key=lambda x: -x['containment'])
    near.sort(key=lambda x: x['dist'])
    with open(OUT / 'image_near_pairs.csv', 'w', encoding='utf-8-sig', newline='') as f:
        if near:
            w = csv.DictWriter(f, fieldnames=list(near[0]))
            w.writeheader(); w.writerows(near)
    with open(OUT / 'text_top_matches.csv', 'w', encoding='utf-8-sig', newline='') as f:
        if text_hits:
            w = csv.DictWriter(f, fieldnames=list(text_hits[0]))
            w.writeheader(); w.writerows(text_hits[:200])
    dist_hist = collections.Counter(x['dist'] for x in near)
    stats = dict(own_images=len(mine), ref_files=len(files), ref_items=len(ref_text), ref_images=nimg,
                 near_pairs=len(near), near_dist_hist=dict(sorted(dist_hist.items())),
                 near_pairs_train=sum(x['own_role'] == 'train' for x in near),
                 text_items_any_8gram=len(text_hits),
                 text_containment_ge_0_5=sum(x['containment'] >= 0.5 for x in text_hits),
                 text_top10=[(x['containment'], x['shared_8gram'], x['source'], x['id'], x['ref_id']) for x in text_hits[:10]])
    (OUT / 'stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    say('stats', json.dumps(stats, ensure_ascii=False))


if __name__ == '__main__':
    main()
