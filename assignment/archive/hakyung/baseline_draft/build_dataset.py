"""
Step 2 - 1단계: HF MMMU/MMMU (revision 고정) 30개 subject config를 각각 로드해서
build_mmmu_prompt()가 기대하는 flat 스키마(A/B/C.. options, 이미지 경로 리스트)로 변환 후 저장.

reference: assignment_guidance.md 1.2절 (dataset revision, 30 subject config, validation split, 900문항)
"""
import argparse
import ast
import json
import os
import re
import string

from datasets import load_dataset

DATASET_NAME = "MMMU/MMMU"
DATASET_REVISION = "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68"

SUBJECTS = [
    "Accounting", "Agriculture", "Architecture_and_Engineering", "Art", "Art_Theory",
    "Basic_Medical_Science", "Biology", "Chemistry", "Clinical_Medicine", "Computer_Science",
    "Design", "Diagnostics_and_Laboratory_Medicine", "Economics", "Electronics",
    "Energy_and_Power", "Finance", "Geography", "History", "Literature", "Manage",
    "Marketing", "Materials", "Math", "Mechanical_Engineering", "Music", "Pharmacy",
    "Physics", "Psychology", "Public_Health", "Sociology",
]

IMAGE_PLACEHOLDER_RE = re.compile(r"<image\s*\d+>")


def parse_options(raw):
    """HF 'options' 컬럼은 "['a', 'b', 'c', 'd']" 형태의 리스트 리터럴 문자열."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = ast.literal_eval(raw)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, SyntaxError):
        return []


def strip_image_placeholders(text):
    """본문 안의 <image 1>, <image 2> 같은 inline 플레이스홀더 제거.
    (알려진 단순화: 원래 위치 정보는 버리고, 이미지는 등장 순서대로 텍스트 앞에 배치)"""
    return IMAGE_PLACEHOLDER_RE.sub("", text).strip()


def build_record(row, subject, img_dir):
    options_list = parse_options(row.get("options"))
    letters = list(string.ascii_uppercase)
    options = {letters[i]: str(opt) for i, opt in enumerate(options_list)}

    uid = f"{subject}__{row.get('id', row.get('index', 'noid'))}"
    safe_uid = uid.replace("/", "_").replace(" ", "_")

    image_paths = []
    for i in range(1, 8):
        img = row.get(f"image_{i}")
        if img is not None:
            path = os.path.join(img_dir, f"{safe_uid}_{i}.png")
            img.save(path)
            image_paths.append(path)

    question = strip_image_placeholders(row.get("question", ""))

    return {
        "uid": uid,
        "subject": subject,
        "question": question,
        "options": options,
        "answer": row.get("answer"),
        "question_type": row.get("question_type", "multiple-choice"),
        "image_paths": image_paths,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-per-subject", type=int, default=None,
                     help="과목당 문항 수 제한 (라이트 테스트용, 지정 안 하면 전체 30개씩=900개)")
    ap.add_argument("--out", type=str, default="data/mmmu_val.jsonl")
    ap.add_argument("--img-dir", type=str, default="data/images")
    ap.add_argument("--mc-only", action="store_true",
                     help="multiple-choice 문항만 포함 (open-ended 문항은 별도 채점 로직 필요, 파서 비교 실험은 이 옵션 권장)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    os.makedirs(args.img_dir, exist_ok=True)

    total = 0
    per_subject_count = {}
    skipped_open = 0

    with open(args.out, "w", encoding="utf-8") as f:
        for subject in SUBJECTS:
            ds = load_dataset(DATASET_NAME, subject, split="validation", revision=DATASET_REVISION)

            if args.mc_only:
                before = len(ds)
                ds = ds.filter(lambda x: x.get("question_type") == "multiple-choice")
                skipped_open += before - len(ds)

            # 필터를 먼저 적용한 뒤 limit을 걸어야 "MC N개 x 30과목"이 실제로 보장됨
            if args.limit_per_subject:
                ds = ds.select(range(min(args.limit_per_subject, len(ds))))

            count = 0
            for row in ds:
                rec = build_record(row, subject, args.img_dir)
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                count += 1
                total += 1

            per_subject_count[subject] = count
            print(f"[{subject}] {count}개 로드 (누적 {total})")

    print("\n==================== 요약 ====================")
    print(f"총 문항 수      : {total}")
    print(f"과목 수         : {len(SUBJECTS)}")
    print(f"open-ended 제외 : {skipped_open}" if args.mc_only else "open-ended 포함됨 (--mc-only 미지정)")
    if args.limit_per_subject is None and not args.mc_only:
        expected = len(SUBJECTS) * 30
        status = "OK" if total == expected else "!! 불일치 확인 필요 !!"
        print(f"기대값(30x30={expected}) 대비: {status}")
    print("===============================================")

    if args.limit_per_subject == 1 and args.mc_only:
        assert total == len(SUBJECTS), (
            f"MC 1개 x {len(SUBJECTS)}과목을 기대했으나 {total}개만 수집됨 "
            f"(과목별 카운트: {per_subject_count}) — MC 문항이 0개인 과목이 있는지 확인 필요"
        )


if __name__ == "__main__":
    main()
