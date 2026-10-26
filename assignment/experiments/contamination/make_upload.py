"""finalize_omr.py / omr_control.py 결과를 팀 HF 저장소 형식으로 바꾸고 검증한다.

사용:
  python make_upload.py --final omr_out/final --cand-dir omr_out --tokenizer <tokenizer.json> --out upload_omr

출력 (out 안): omr_e1_600.jsonl, omr_e1_1500.jsonl, omr_control_600.jsonl, omr_control_1500.jsonl, images/, stats.md
한 줄 형식: id(omr_e1_<행번호> / omr_ctl_<행번호>), images, messages(user 는 "<image>\n" 로 시작), image_phash, answer, has_observation,
  response_tokens(Qwen3-VL 토크나이저로 센 응답 토큰 수), keyword(있을 때), source="omr", type
"""
import argparse
import collections
import csv
import json
import os
import re
import shutil
import statistics

from tokenizers import Tokenizer

from omr_select import TYPE_PATTERNS, split_stem

HEX16 = re.compile(r"^[0-9a-f]{16}$")


def convert(recs, phash_of, tok, tag):
    """tag(e1/ctl)를 id 에 붙여, 두 세트에 같이 뽑힌 문항도 id 가 겹치지 않게 한다(내용이 다를 수 있음)."""
    out = []
    for x in recs:
        stem, _ = split_stem(x["question"])
        kw = x.get("keyword")
        if kw is None and x.get("type"):
            m = re.search(TYPE_PATTERNS[x["type"]], stem, re.I)
            kw = m.group(0).lower() if m else ""
        row = {"id": x["id"].replace("omr_", f"omr_{tag}_", 1), "images": [x["image"]],
               "messages": [{"role": "user", "content": "<image>\n" + x["question"]},
                            {"role": "assistant", "content": x["target"]}],
               "image_phash": x.get("phash") or phash_of[x["cand_id"]], "answer": x["answer"],
               "has_observation": x["target"].startswith("Observation:"),
               "response_tokens": len(tok.encode(x["target"]).ids), "source": "omr", "type": x.get("type", "")}
        if kw:
            row["keyword"] = kw
        out.append(row)
    return out


def check(name, rows, n, img_dir):
    assert len(rows) == n, f"{name}: {len(rows)}행 (기대 {n})"
    assert len({r["id"] for r in rows}) == n, f"{name}: id 중복"
    per_img = collections.Counter(r["images"][0] for r in rows)
    per_hash = collections.Counter(r["image_phash"] for r in rows)
    assert max(per_img.values()) <= 2 and max(per_hash.values()) <= 2, f"{name}: 같은 이미지 3번 이상"
    for r in rows:
        c = r["messages"][1]["content"]
        assert r["messages"][0]["content"].startswith("<image>\n")
        assert r["answer"] in "ABCDE" and c.endswith(f"Answer: {r['answer']}"), r["id"]
        assert r["has_observation"] == c.startswith("Observation: "), r["id"]
        assert HEX16.match(r["image_phash"]), r["id"]
        assert os.path.exists(os.path.join(img_dir, os.path.basename(r["images"][0]))), r["id"]


def describe(name, rows):
    tk = [r["response_tokens"] for r in rows]
    obs = sum(r["has_observation"] for r in rows)
    lines = [f"### {name} ({len(rows)}행)", "",
             f"- 유형: {dict(collections.Counter(r['type'] or '(시그널 단어 없음)' for r in rows).most_common())}",
             f"- 정답 글자: {dict(sorted(collections.Counter(r['answer'] for r in rows).items()))}",
             f"- has_observation: true {obs} / false {len(rows) - obs}",
             f"- response_tokens: 평균 {statistics.mean(tk):.1f}, 중앙값 {statistics.median(tk):.0f}, "
             f"최소 {min(tk)}, 최대 {max(tk)}",
             f"- 이미지 {len({r['images'][0] for r in rows})}장 (같은 이미지 최대 "
             f"{max(collections.Counter(r['image_phash'] for r in rows).values())}문항)", ""]
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", required=True)
    ap.add_argument("--cand-dir", required=True, help="selection.csv, candidates_pool.csv 가 있는 폴더")
    ap.add_argument("--tokenizer", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--notes", help="stats.md 앞에 붙일 만든 방법 설명(md)")
    a = ap.parse_args()

    phash_of = {}
    for name in ["selection.csv", "candidates_pool.csv"]:
        for r in csv.DictReader(open(os.path.join(a.cand_dir, name), encoding="utf-8")):
            phash_of[r["cand_id"]] = r["phash"]
    tok = Tokenizer.from_file(a.tokenizer)
    load = lambda name: [json.loads(l) for l in open(os.path.join(a.final, name), encoding="utf-8")]
    e1_600, e1_1500 = load("omr_600.jsonl"), load("omr_1500.jsonl")
    ctl_1500 = load("control_1500.jsonl")
    assert [x["id"] for x in e1_1500[:600]] == [x["id"] for x in e1_600], "E1 1500 앞 600건이 600건 세트와 다름"
    sets = {"omr_e1_600": (e1_600, 600, "e1"), "omr_e1_1500": (e1_1500, 1500, "e1"),
            "omr_control_600": (ctl_1500[:600], 600, "ctl"), "omr_control_1500": (ctl_1500, 1500, "ctl")}

    img_out = os.path.join(a.out, "images")
    os.makedirs(img_out, exist_ok=True)
    stats = []
    if a.notes:
        stats += [open(a.notes, encoding="utf-8").read().rstrip(), ""]
    stats += ["## 파일별 통계", ""]
    converted = {}
    for name, (recs, n, tag) in sets.items():
        rows = convert(recs, phash_of, tok, tag)
        for r in rows:
            fn = os.path.basename(r["images"][0])
            if not os.path.exists(os.path.join(img_out, fn)):
                shutil.copy(os.path.join(a.final, "images", fn), os.path.join(img_out, fn))
        check(name, rows, n, img_out)
        converted[name] = rows
        with open(os.path.join(a.out, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        stats += describe(name, rows)
    for big, small in (("omr_e1_1500", "omr_e1_600"), ("omr_control_1500", "omr_control_600")):
        assert converted[big][:600] == converted[small], f"{big} 앞 600행이 {small} 와 다름"
    e1_ids = {r["id"] for r in converted["omr_e1_1500"]}
    both = sum(r["id"] in e1_ids for r in converted["omr_control_1500"])
    stats += [f"- E1 1500 과 대조군 1500 에 같이 들어간 문항: {both}건 (대조군은 무작위라 겹칠 수 있음)", ""]
    with open(os.path.join(a.out, "stats.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(stats) + "\n")
    print("\n".join(stats))
    print(f"→ {a.out}: jsonl 4개, 이미지 {len(os.listdir(img_out))}장")


if __name__ == "__main__":
    main()
