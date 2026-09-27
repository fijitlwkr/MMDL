"""
Step 3 - 900문항 채점.

- multiple-choice: options 그대로 사용
- open(-ended): Qwen 공식 run_mmmu.py의 MMMU_preproc() 재현
    A = 정답 텍스트, B = "Other Answers", GT = "A"
    (원본 그대로: dataset_utils.py::MMMU_preproc)
- 파서 2종 모두 적용해서 비교 (이 프로젝트의 핵심 산출물):
    1) MMMU 공식 파서 (parse_multi_choice_response_official) - 채택된 1차 파서
    2) VLMEvalKit 파서 (can_infer_vlmevalkit) - 비교 대상
- 파싱 실패(후보 0개): 오답(0)으로 채점.
  원본 run_mmmu.py/MMMU 공식 레포는 이 경우 random.choice로 임의 정답을 배정하지만,
  이 프로젝트는 재현성(파인튜닝 전후 동일 조건 비교)을 위해 결정론적으로 오답 처리하는
  쪽으로 의도적으로 편차를 둠 (문서화된 변경 - mmmu_env_config.md 참고).
"""
import argparse
import json
from collections import defaultdict

from mc_parsers import can_infer_vlmevalkit, parse_multi_choice_response_official
from build_dataset import SUBJECTS

OFFICIAL_SCORE = 67.4  # Qwen3-VL Technical Report, MMMU val


def build_grading_choices(record):
    """question_type에 따라 채점용 choices/GT 결정 (MMMU_preproc 재현)."""
    if record.get("question_type", "multiple-choice") == "multiple-choice":
        return record["options"], record["answer"]
    # open-ended: A=정답, B=Other Answers, GT=A
    return {"A": str(record["answer"]), "B": "Other Answers"}, "A"


def grade_with_parser(records, parser_fn, parser_name):
    by_subject = defaultdict(lambda: {"n": 0, "hit": 0, "extract_fail": 0})
    fail_uids = []
    pred_by_uid = {}

    for r in records:
        choices, gt = build_grading_choices(r)
        text = r.get("prediction_final", r.get("prediction_raw", ""))

        if parser_name == "mmmu_official":
            pred = parser_fn(text, list(choices.keys()), choices)
        else:  # vlmevalkit
            raw = parser_fn(text, choices)
            pred = raw if raw and raw != "Z" else None

        subj = r["subject"]
        by_subject[subj]["n"] += 1
        pred_by_uid[r["uid"]] = pred

        if pred is None:
            by_subject[subj]["extract_fail"] += 1
            fail_uids.append(r["uid"])
            hit = 0
        else:
            hit = int(pred == gt)
        by_subject[subj]["hit"] += hit

    return by_subject, fail_uids, pred_by_uid


def summarize(by_subject, label):
    print(f"\n{'='*78}")
    print(f"[{label}] 과목별 결과")
    print(f"{'='*78}")
    print(f"{'과목':38s} {'문항수':>6s} {'정답':>6s} {'정확도':>8s} {'파싱실패':>8s}")
    subject_accs = {}
    for subj in SUBJECTS:
        s = by_subject.get(subj, {"n": 0, "hit": 0, "extract_fail": 0})
        acc = s["hit"] / s["n"] if s["n"] else 0.0
        subject_accs[subj] = acc
        print(f"{subj:38s} {s['n']:6d} {s['hit']:6d} {acc:8.1%} {s['extract_fail']:8d}")

    overall = sum(subject_accs.values()) / len(subject_accs) if subject_accs else 0.0
    total_n = sum(s["n"] for s in by_subject.values())
    total_hit = sum(s["hit"] for s in by_subject.values())
    total_fail = sum(s["extract_fail"] for s in by_subject.values())

    print(f"{'-'*78}")
    print(f"Overall (macro avg, {len(subject_accs)}과목): {overall*100:.2f}%")
    print(f"전체 문항 {total_n} / 정답 {total_hit} / 파싱실패(오답처리) {total_fail} ({total_fail/max(total_n,1):.1%})")
    print(f"공식 수치(Qwen3-VL Tech Report) 대비 Δ: {overall*100 - OFFICIAL_SCORE:+.2f}pp")
    return overall, subject_accs, total_n, total_hit, total_fail


def to_submission_table_md(subject_accs_by_parser, primary="mmmu_official"):
    """SUBMISSION_TEMPLATE.md '5. 결과' 표 형식으로 markdown 생성 (primary 파서 기준)."""
    lines = ["| No. | Subject | Data Num | Acc |", "|---|---|---|---|"]
    accs = subject_accs_by_parser[primary]
    for i, subj in enumerate(SUBJECTS, 1):
        lines.append(f"| {i} | {subj} | 30 | {accs[subj]*100:.1f} |")
    overall = sum(accs.values()) / len(accs)
    lines.append(f"| | **Overall (macro avg)** | **900** | **{overall*100:.2f}** |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", default="data/predictions_val.jsonl")
    ap.add_argument("--out", default="data/baseline_score.json")
    ap.add_argument("--md-out", default="data/baseline_table.md")
    args = ap.parse_args()

    records = [json.loads(l) for l in open(args.preds, encoding="utf-8")]
    print(f"총 문항 수: {len(records)} (기대값: {len(SUBJECTS)*30}개)")
    if len(records) != len(SUBJECTS) * 30:
        print("!! 경고: 문항 수가 30x30=900과 다릅니다. build_dataset.py --out 실행 결과를 확인하세요.")

    results = {}
    subject_accs_by_parser = {}

    by_subj_mmmu, fail_mmmu, pred_mmmu = grade_with_parser(records, parse_multi_choice_response_official, "mmmu_official")
    overall_mmmu, accs_mmmu, n_mmmu, hit_mmmu, failn_mmmu = summarize(by_subj_mmmu, "MMMU 공식 파서 (1차 채택)")
    subject_accs_by_parser["mmmu_official"] = accs_mmmu

    by_subj_vlm, fail_vlm, pred_vlm = grade_with_parser(records, can_infer_vlmevalkit, "vlmevalkit")
    overall_vlm, accs_vlm, n_vlm, hit_vlm, failn_vlm = summarize(by_subj_vlm, "VLMEvalKit 파서 (비교 대상)")
    subject_accs_by_parser["vlmevalkit"] = accs_vlm

    # 두 파서 모두 추출 성공했지만 답이 다른 문항 (disagreement)
    disagreements = []
    for r in records:
        u = r["uid"]
        a, b = pred_mmmu.get(u), pred_vlm.get(u)
        if a is not None and b is not None and a != b:
            _, gt = build_grading_choices(r)
            disagreements.append({"uid": u, "subject": r["subject"], "mmmu_official": a, "vlmevalkit": b, "gt": gt})

    print(f"\n{'='*78}")
    print(f"[요약] MMMU 공식 {overall_mmmu*100:.2f}%  vs  VLMEvalKit {overall_vlm*100:.2f}%")
    print(f"파싱 실패: MMMU 공식 {failn_mmmu}/{n_mmmu}건, VLMEvalKit {failn_vlm}/{n_vlm}건")
    print(f"둘 다 추출 성공 + 답 불일치: {len(disagreements)}건")
    print(f"{'='*78}")

    result = {
        "official_score": OFFICIAL_SCORE,
        "mmmu_official": {
            "overall_macro_avg": overall_mmmu, "total_n": n_mmmu, "total_hit": hit_mmmu,
            "total_extract_fail": failn_mmmu, "subject_accuracy": accs_mmmu,
            "delta_pp": overall_mmmu * 100 - OFFICIAL_SCORE, "extract_fail_uids": fail_mmmu,
        },
        "vlmevalkit": {
            "overall_macro_avg": overall_vlm, "total_n": n_vlm, "total_hit": hit_vlm,
            "total_extract_fail": failn_vlm, "subject_accuracy": accs_vlm,
            "delta_pp": overall_vlm * 100 - OFFICIAL_SCORE, "extract_fail_uids": fail_vlm,
        },
        "disagreements": disagreements,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n상세 결과 저장 -> {args.out}")

    md = to_submission_table_md(subject_accs_by_parser, primary="mmmu_official")
    with open(args.md_out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"SUBMISSION_TEMPLATE.md용 표 저장 -> {args.md_out} (MMMU 공식 파서 기준)")


if __name__ == "__main__":
    main()
