"""대조군: OMR 에서 질문 유형을 가리지 않고 무작위로 뽑는다. 형식 조건과 MMMU 중복 검사는 E1 과 같다.

사용:
  python omr_control.py --cache-dir data_cache --out-dir omr_out --index mmmu_phash.csv --n 1500

조건 (E1 과 같음): 질문 본문 ≤ --max-stem 자, 관찰 문장 추출 성공, 관찰 문장 ≤ --max-perc-words 단어,
  거부 응답 제외, 정답이 보기 안에 있음, MMMU 이미지와 해밍 거리 ≤ 12 제외, 같은 그림(≤ 8)은 하나만.
E1 과 다른 점: 질문 유형(그림 읽기 시그널 단어)으로 고르지 않고, 이미지 없이 풀기 필터와 정답 종류 분류,
  단서 비율 맞추기, 보기 순서 바꾸기를 하지 않는다.
출력: out-dir/final/control_{n}.jsonl (앞 600건이 600건 세트), 이미지는 final/images/
"""
import argparse
import collections
import json
import os
import random
import re

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

from omr_select import PERC_RE, REPO, SEED, TYPE_PATTERNS, classify, split_stem
from phash_utils import load_index, nearest, phash_from_bytes

REFUSAL = re.compile(r"sorry|can.t share|chain-of-thought", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--index", required=True, help="mmmu_phash.csv")
    ap.add_argument("--shards", type=int, default=4)
    ap.add_argument("--n", type=int, default=1500)
    ap.add_argument("--max-stem", type=int, default=300)
    ap.add_argument("--max-perc-words", type=int, default=120)
    ap.add_argument("--mmmu-le", type=int, default=12, help="MMMU 와 이 거리 이하면 제외")
    ap.add_argument("--dup-le", type=int, default=8)
    ap.add_argument("--answer-only", type=float, default=0.2)
    a = ap.parse_args()

    paths = [hf_hub_download(REPO, f"data/train-{s:05d}-of-00031.parquet", repo_type="dataset",
                             cache_dir=a.cache_dir) for s in range(a.shards)]
    elig, stats = [], collections.Counter()
    for s, path in enumerate(paths):
        row = s * 5000
        for batch in pq.ParquetFile(path).iter_batches(batch_size=500, columns=["question", "reasoning", "answer"]):
            d = batch.to_pydict()
            for q, rsn, ans in zip(d["question"], d["reasoning"], d["answer"]):
                rid, row = row, row + 1
                stats["rows"] += 1
                stem, opts = split_stem(q)
                m = PERC_RE.search(rsn)
                perc = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
                letters = re.findall(r"(?m)^\s*([A-J])[.)]", opts)
                if len(stem) > a.max_stem:
                    stats["long_stem"] += 1
                elif not perc or len(perc.split()) > a.max_perc_words:
                    stats["no_or_long_perc"] += 1
                elif REFUSAL.search(perc):
                    stats["refusal"] += 1
                elif ans.strip() not in letters:
                    stats["bad_answer"] += 1
                else:
                    elig.append({"omr_row": rid, "stem": stem, "options": opts, "answer": ans.strip(), "perception": perc})
    stats["eligible"] = len(elig)
    rng = random.Random(SEED + 40)
    rng.shuffle(elig)

    # 무작위 순서대로 이미지 지문을 보고 MMMU 겹침·같은 그림을 빼며 n 건까지 채운다
    want = {r["omr_row"]: r for r in elig[: a.n * 2]}
    imgs = {}
    for s, path in enumerate(paths):
        row = s * 5000
        for batch in pq.ParquetFile(path).iter_batches(batch_size=500, columns=["image"]):
            for img in batch.column("image").to_pylist():
                if row in want:
                    imgs[row] = img["bytes"]
                row += 1
    index = [(i, h) for i, h in load_index(a.index) if not h.startswith("ERROR")]
    chosen, seen = [], []
    for r in elig[: a.n * 2]:
        if len(chosen) >= a.n:
            break
        h = phash_from_bytes(imgs[r["omr_row"]])
        _, dist = nearest(h, index)
        if dist <= a.mmmu_le:
            stats["mmmu_near"] += 1
            continue
        hv = int(h, 16)
        if any(bin(hv ^ x).count("1") <= a.dup_le for x in seen):
            stats["dup_image"] += 1
            continue
        seen.append(hv)
        r["phash"] = h
        chosen.append(r)
    assert len(chosen) == a.n, f"{len(chosen)}건밖에 못 채움"

    fin = os.path.join(a.out_dir, "final")
    os.makedirs(os.path.join(fin, "images"), exist_ok=True)
    rng2 = random.Random(SEED + 50)
    # 600건 세트와 1500건 세트 모두 정답만 비율이 맞도록 앞 600건과 나머지를 따로 뽑는다
    ans_only = set(rng2.sample(range(600), round(600 * a.answer_only))) | \
        {600 + i for i in rng2.sample(range(a.n - 600), round((a.n - 600) * a.answer_only))}
    with open(os.path.join(fin, f"control_{a.n}.jsonl"), "w", encoding="utf-8") as f:
        for i, r in enumerate(chosen):
            fn = f"omr_{r['omr_row']:06d}.jpg"
            with open(os.path.join(fin, "images", fn), "wb") as g:
                g.write(imgs[r["omr_row"]])
            t = classify(r["stem"]) or ""
            kw = re.search(TYPE_PATTERNS[t], r["stem"], re.I).group(0).lower() if t else ""
            tgt = f"Answer: {r['answer']}" if i in ans_only else f"Observation: {r['perception']}\nAnswer: {r['answer']}"
            f.write(json.dumps({"id": f"omr_{r['omr_row']:06d}", "image": f"images/{fn}",
                                "question": f"{r['stem']}\n{r['options']}", "target": tgt, "answer": r["answer"],
                                "answer_only": int(i in ans_only), "type": t, "keyword": kw,
                                "omr_row": r["omr_row"], "phash": r["phash"]}, ensure_ascii=False) + "\n")
    print(dict(stats))
    print("유형(시그널 단어 기준):", dict(collections.Counter(classify(r["stem"]) or "(없음)" for r in chosen)))
    print("정답 글자:", dict(sorted(collections.Counter(r["answer"] for r in chosen).items())))
    print(f"→ {fin}/control_{a.n}.jsonl {len(chosen)}건, 정답만 {len(ans_only)}건")


if __name__ == "__main__":
    main()
