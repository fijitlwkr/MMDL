"""Build per-member markdown packets for labeling (and one for C's extra checks).

Usage: python make_packets.py --repo . --split results/error_analysis/split.csv \
         --extra results/error_analysis/extra_for_C.csv --out data/error_analysis_packets
Images are linked as ../error_analysis_images/<id>_image_<n>.png (see fetch_images.py).
"""
import argparse, csv, json
from pathlib import Path

IMG_DIR = "../error_analysis_images"


def jl(p):
    return {r["id"]: r for r in (json.loads(l) for l in open(p, encoding="utf-8") if l.strip())}


def block(text):
    fence = "````" if "```" in text else "```"
    return f"{fence}text\n{text}\n{fence}"


def item_md(i, raw, res, label_by=None):
    r, s = raw[i], res[i]
    out = [f"## {i}", ""]
    out.append(f"유형: {r['question_type']} / 종료: {s['finish_reason']} / 출력 토큰: {s['output_tokens']}")
    out.append("")
    out += ["### 프롬프트", "", block(r["prompt"]), ""]
    out += ["### 정답 / 모델이 고른 답", "", f"- 정답(gold): `{s['gold']}`",
            f"- 모델이 고른 답(채점기 추출): `{s['predicted']}`", ""]
    idx = r.get("image_indices") or []
    out.append("### 이미지")
    out.append("")
    if idx:
        for n in idx:
            out.append(f"image {n}:")
            out.append("")
            out.append(f"![{i} image {n}]({IMG_DIR}/{i}_image_{n}.png)")
            out.append("")
    else:
        out += ["(이미지 없음 → `images_checked`는 `na`)", ""]
    out += ["### 모델 응답 전문 (영어 원문)", "", block(r["raw_text"]), ""]
    if label_by:
        out += [f"> 라벨은 `labels_{label_by}.csv`의 `{i}` 줄에 적는다.", ""]
    out += ["---", ""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--split", default="results/error_analysis/split.csv")
    ap.add_argument("--extra", default="results/error_analysis/extra_for_C.csv")
    ap.add_argument("--out", default="data/error_analysis_packets")
    a = ap.parse_args()
    repo, out = Path(a.repo), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    raw = jl(repo / "results/mmmu_team_baseline/raw.jsonl")
    res = jl(repo / "results/mmmu_team_baseline/scores/item_results.jsonl")
    rows = list(csv.DictReader(open(a.split, encoding="utf-8")))
    for m in "ABCD":
        mine = [r["id"] for r in rows if r["member"] == m]
        head = [f"# {m}의 라벨링 자료 ({len(mine)}문항)", "",
                "기준은 가이드의 판단 순서 ①~⑥을 따른다. 영어 응답은 번역기·AI로 이해해도 되지만, 핵심 문장(숫자·단위·부정어·보기 기호·최종 선택)은 영어 원문과 대조한다.", "",
                "---", ""]
        (out / f"packet_{m}.md").write_text("\n".join(head) + "\n" + "\n".join(item_md(i, raw, res, m) for i in mine), encoding="utf-8")
    ex = list(csv.DictReader(open(a.extra, encoding="utf-8")))
    todo = [e for e in ex if e["check"] == "yes"]
    head = [f"# C의 추가 확인 자료 ({len(todo)}문항: 추출 실패 3 + 길이 초과 표본 10)", "",
            "- stop_extraction_failure: 정상 종료인데 답을 못 뽑은 문항. 응답에 최종 선택이 있었는지 확인한다.",
            "- length_ended: 길이 초과 종료 문항. 자동 반복 판정(repetition_flag)이 맞는지 확인한다.", "", "---", ""]
    body = []
    for e in todo:
        body.append(f"<!-- kind={e['kind']} repetition_flag={e['repetition_flag']} -->")
        body.append(item_md(e["id"], raw, res))
    (out / "packet_C_extra.md").write_text("\n".join(head) + "\n" + "\n".join(body), encoding="utf-8")
    print("wrote", sorted(p.name for p in out.iterdir()))


if __name__ == "__main__":
    main()
