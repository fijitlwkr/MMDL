"""text_only_filter.py 결과에서 최종 학습 문항을 고르고 학습 형식으로 내보낸다.

사용:
  1) python finalize_omr.py --out-dir omr_out --stage label     # 정답 종류 분류가 필요한 문항 → to_label.json
  2) (to_label.json 을 분류해 answer_labels_pool.csv 작성: cand_id, label, labeled_by)
  3) python finalize_omr.py --out-dir omr_out --cache-dir data_cache --stage export --n 600
     python finalize_omr.py --out-dir omr_out --cache-dir data_cache --stage export --n 1500 \
         --include omr_out/final/omr_600.jsonl      # 600건을 그대로 품은 1500건

입력 (out-dir 안): filter_result.csv, selection.csv, candidates_pool.csv, answer_labels_pool.csv
규칙:
  - filter_result 의 drop=1(이미지 없이 3번 중 2번 이상 맞힘)은 뺀다.
  - 정답 종류가 visual/anatomy 인 것만 쓴다. 기존 후보는 answer_labels.csv 라벨, 새 후보 중
    count 는 visual, location 은 기존과 같이 남김(visual 또는 anatomy), findings/marker 는 분류 결과를 쓴다.
  - 유형별로 고르게 뽑되, 모자란 유형의 몫은 다른 유형에 나눈다.
  - 정답 보기가 혼자 제일 긴 문항은 찍기 확률(1/보기 수 평균) 이하로, count 의 정답 값은 한 값이
    1/보기 수 이하가 되도록 제한한다. 지킬 수 없으면 제한을 풀고 비율을 출력한다.
  - 고른 뒤 보기 순서를 바꿔 정답 글자가 A, B, C, D... 에 고르게 가도록 한다(--keep-order 면 안 함).
    4B 가 이미지 없이 C 를 많이 골라 정답이 C 인 문항이 필터에서 더 많이 빠지기 때문이다.
    보기끼리 서로 가리키는 문항("Both A and C" 등)은 순서를 그대로 둔다.
출력 (out-dir/final/): omr_{n}.jsonl, omr_{n}.csv, images/
  target = "Observation: {관찰 문장}\nAnswer: {정답}", --answer-only 비율(기본 0.2)은 "Answer: {정답}" 만.
"""
import argparse
import collections
import csv
import json
import math
import os
import random
import re

SEED = 3407
KEEP = {"visual", "anatomy"}
WORDNUM = {"zero": 0, "none": 0, "one": 1, "single": 1, "two": 2, "three": 3, "four": 4, "five": 5,
           "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def parse_opts(options):
    out = {}
    for line in options.split("\n"):
        m = re.match(r"\s*([A-J])[.)]\s*(.*)", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def unique_longest(r):
    o = parse_opts(r["options"])
    if r["answer"] not in o:
        return False
    lens = [len(v) for v in o.values()]
    return len(o[r["answer"]]) == max(lens) and lens.count(max(lens)) == 1


def count_value(r):
    t = parse_opts(r["options"]).get(r["answer"], "").lower()
    m = re.search(r"\d+", t)
    if m:
        return int(m.group())
    for w in re.findall(r"[a-z]+", t):
        if w in WORDNUM:
            return WORDNUM[w]
    return t


LETTER_REF = re.compile(r"\b(both|all of the above|none of the above|neither)\b|\b[A-J]\s*(and|or|&|,)\s*[A-J]\b", re.I)


def balance_letters(chosen, rng):
    """보기 수가 같은 문항끼리 정답 위치를 고르게 나누고, 정답 보기를 그 자리로 옮긴다."""
    groups = collections.defaultdict(list)
    for r in chosen:
        r["orig_answer"] = r["answer"]
        o = parse_opts(r["options"])
        if r["answer"] in o and not LETTER_REF.search(r["options"]):
            groups[len(o)].append(r)
    for k, rows in groups.items():
        letters = [chr(65 + i) for i in range(k)]
        targets = [letters[i % k] for i in range(len(rows))]
        rng.shuffle(targets)
        for r, tgt in zip(rows, targets):
            o = parse_opts(r["options"])
            others = [v for l, v in o.items() if l != r["answer"]]
            i = letters.index(tgt)
            new = others[:i] + [o[r["answer"]]] + others[i:]
            r["options"] = "\n".join(f"{l}. {v}" for l, v in zip(letters, new))
            r["answer"] = tgt
    return sum(len(v) for v in groups.values())


def load(d, name):
    p = os.path.join(d, name)
    return list(csv.DictReader(open(p, encoding="utf-8"))) if os.path.exists(p) else []


def survivors(d):
    res = {r["cand_id"]: r for r in load(d, "filter_result.csv")}
    old_labels = {r["cand_id"]: r["label"] for r in load(d, "answer_labels.csv")}
    new_labels = {r["cand_id"]: r["label"] for r in load(d, "answer_labels_pool.csv")}
    rows = []
    for src, data in (("selection", load(d, "selection.csv")), ("pool", load(d, "candidates_pool.csv"))):
        for r in data:
            f = res.get(r["cand_id"])
            if f is None or f["drop"] != "0":
                continue
            r = dict(r, source=src, n_correct=f["n_correct"])
            if src == "selection":
                r["label"] = old_labels[r["cand_id"]]
            elif r["type"] == "count":
                r["label"] = "visual"
            elif r["type"] == "location":
                r["label"] = "visual_or_anatomy"
            else:
                r["label"] = new_labels.get(r["cand_id"], "")
            rows.append(r)
    return rows


def strict_pick(cand, q, k, is_count, base=()):
    """base(이미 들어간 문항)와 합쳐 q 건이 되도록 고른다. 정답 제일 긴 보기 ≤ q/k, count 정답 값 하나당 ≤ q/k."""
    ul_cap, val_cap = math.floor(q / k), math.ceil(q / k)
    ul = sum(unique_longest(r) for r in base)
    vals = collections.Counter(count_value(r) for r in base) if is_count else collections.Counter()
    got = []
    for r in cand:
        if len(got) >= q - len(base):
            break
        is_ul = unique_longest(r)
        if (is_ul and ul >= ul_cap) or (is_count and vals[count_value(r)] >= val_cap):
            continue
        got.append(r)
        ul += is_ul
        if is_count:
            vals[count_value(r)] += 1
    return got


def pick(rows, n, rng, fixed=()):
    """fixed(먼저 고정된 문항)를 포함해 n 건이 되도록 새 문항을 고른다. 새로 고른 것만 돌려준다."""
    fixed_ids = {r["cand_id"] for r in fixed}
    by_type, base = collections.defaultdict(list), collections.defaultdict(list)
    for r in rows:
        if r["cand_id"] not in fixed_ids:
            by_type[r["type"]].append(r)
    for r in fixed:
        base[r["type"]].append(r)
    for t in by_type:
        rng.shuffle(by_type[t])
    # 적은 유형부터 고르게 몫을 정하고, 제한 때문에 못 채운 몫은 뒤 유형(후보 많은 쪽)으로 넘긴다
    types = sorted(set(by_type) | set(base), key=lambda t: len(by_type[t]) + len(base[t]))
    chosen, quota, left = [], {}, n
    for i, t in enumerate(types):
        cand, b = by_type[t], base[t]
        k = round(sum(len(parse_opts(r["options"])) for r in cand + b) / len(cand + b)) or 4
        q = max(len(b), min(len(cand) + len(b), left // (len(types) - i)))
        got = []
        while q > len(b):
            got = strict_pick(cand, q, k, t == "count", b)
            if len(got) == q - len(b):
                break
            q -= 1
        if q == len(b):
            got = []
        quota[t], left = q, left - q
        chosen += got
    if left > 0:  # 그래도 모자라면 제한 없이 채움
        ids = {r["cand_id"] for r in chosen} | fixed_ids
        rest = [r for t in types for r in by_type[t] if r["cand_id"] not in ids][:left]
        print(f"제한을 지켜서는 {n - left}건까지만 됨. {len(rest)}건은 제한 없이 채움")
        chosen += rest
    return chosen, quota


def export_images(chosen, d, cache_dir, img_out):
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download
    from omr_select import REPO
    os.makedirs(img_out, exist_ok=True)
    need = {}
    for r in chosen:
        src = os.path.join(d, "images", r["image_file"])
        dst = os.path.join(img_out, r["image_file"])
        if os.path.exists(src):
            with open(src, "rb") as f, open(dst, "wb") as g:
                g.write(f.read())
        else:
            need[int(r["omr_row"])] = dst
    for s in sorted({row // 5000 for row in need}):
        path = hf_hub_download(REPO, f"data/train-{s:05d}-of-00031.parquet", repo_type="dataset", cache_dir=cache_dir)
        row = s * 5000
        for batch in pq.ParquetFile(path).iter_batches(batch_size=500, columns=["image"]):
            for img in batch.column("image").to_pylist():
                if row in need:
                    with open(need[row], "wb") as g:
                        g.write(img["bytes"])
                row += 1
    missing = [p for p in need.values() if not os.path.exists(p)]
    assert not missing, f"이미지 {len(missing)}장 못 꺼냄"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--stage", choices=["label", "export"], required=True)
    ap.add_argument("--cache-dir")
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--answer-only", type=float, default=0.2)
    ap.add_argument("--keep-order", action="store_true", help="보기 순서를 바꾸지 않음")
    ap.add_argument("--include", help="export 단계: 그대로 포함할 이전 결과(jsonl). 예: 600건을 품은 1500건")
    ap.add_argument("--label-max", type=int, default=0, help="label 단계: 유형별 분류할 최대 건수(무작위). 0=전부")
    a = ap.parse_args()
    d = a.out_dir
    rows = survivors(d)
    print("이미지 없이 못 푼 문항:", len(rows), dict(collections.Counter(r["type"] for r in rows)))

    if a.stage == "label":
        todo = [r for r in rows if r["label"] == ""]
        if a.label_max:
            rng = random.Random(SEED + 20)
            rng.shuffle(todo)
            per = collections.Counter()
            todo = [r for r in todo if (per.update([r["type"]]) or per[r["type"]] <= a.label_max)]
        out = [{"cand_id": r["cand_id"], "stem": r["stem"], "options": r["options"], "answer": r["answer"],
                "answer_text": parse_opts(r["options"]).get(r["answer"], "")} for r in todo]
        json.dump(out, open(os.path.join(d, "to_label.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("분류 필요:", len(out), dict(collections.Counter(r["type"] for r in todo)), "→ to_label.json")
        return

    unlabeled = sum(r["label"] == "" for r in rows)
    print(f"정답 종류를 분류하지 않은 findings/marker {unlabeled}건은 제외")
    rows = [r for r in rows if r["label"] in KEEP or r["label"] == "visual_or_anatomy"]
    print("정답 종류 visual/anatomy:", len(rows), dict(collections.Counter(r["type"] for r in rows)))
    fixed_recs = [json.loads(l) for l in open(a.include, encoding="utf-8")] if a.include else []
    fixed_ids = {x["cand_id"] for x in fixed_recs}
    fixed = [r for r in rows if r["cand_id"] in fixed_ids]
    assert len(fixed) == len(fixed_recs), "포함할 문항 중 후보에 없는 것이 있음"
    rng = random.Random(SEED)
    chosen, quota = pick(rows, a.n, rng, fixed)
    allc = fixed + chosen
    print("유형별 몫:", quota, "합계", len(allc), f"(고정 {len(fixed)} + 새로 {len(chosen)})")
    ul = sum(unique_longest(r) for r in allc)
    print(f"정답 보기가 혼자 제일 김: {ul}/{len(allc)} ({ul / len(allc):.0%})")
    cnt = [r for r in allc if r["type"] == "count"]
    if cnt:
        print("count 정답 값:", dict(collections.Counter(count_value(r) for r in cnt).most_common()))
    if not a.keep_order:
        chosen = [dict(r) for r in chosen]
        n_bal = balance_letters(chosen, random.Random(SEED + 30))
        print(f"보기 순서 바꿈 {n_bal}건")

    fin = os.path.join(d, "final")
    export_images(chosen, d, a.cache_dir, os.path.join(fin, "images"))
    rng2 = random.Random(SEED + 10)
    ans_only = set(rng2.sample(range(len(chosen)), round(len(chosen) * a.answer_only)))
    recs = list(fixed_recs)
    for i, r in enumerate(chosen):
        tgt = f"Answer: {r['answer']}" if i in ans_only else f"Observation: {r['perception']}\nAnswer: {r['answer']}"
        recs.append({"id": f"omr_{r['omr_row']:0>6}", "image": f"images/{r['image_file']}",
                     "question": f"{r['stem']}\n{r['options']}", "target": tgt, "answer": r["answer"],
                     "orig_answer": r.get("orig_answer", r["answer"]),
                     "answer_only": int(i in ans_only), "type": r["type"], "label": r["label"],
                     "omr_row": int(r["omr_row"]), "cand_id": r["cand_id"], "source": r["source"],
                     "text_only_correct": int(r["n_correct"])})
    print("정답 글자:", dict(sorted(collections.Counter(x["answer"] for x in recs).items())))
    with open(os.path.join(fin, f"omr_{a.n}.jsonl"), "w", encoding="utf-8") as f:
        for x in recs:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    with open(os.path.join(fin, f"omr_{a.n}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(recs[0].keys()))
        w.writeheader()
        w.writerows(recs)
    print(f"→ {fin}/omr_{a.n}.jsonl {len(recs)}건, 정답만 {sum(x['answer_only'] for x in recs)}건")


if __name__ == "__main__":
    main()
