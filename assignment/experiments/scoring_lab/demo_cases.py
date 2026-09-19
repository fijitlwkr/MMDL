"""Reproduce parser differences on authored examples, never benchmark scores."""
import argparse
import json
from pathlib import Path

from parsers import analyze, PARSERS

CASES = [
    ("S1", "Final Answer: B", "stop", "unique B"),
    ("S2", "First I tried (A). I now choose (B).", "stop", "unique B"),
    ("S3", "I considered (A), but I choose (B).", "stop", "unique B"),
    ("S4", "Final Answer: A or B.", "stop", "ambiguous"),
    ("S5", "The answer is C. Actually, the final answer is B.", "stop", "unique B"),
    ("S6", "B is my response and here follows a long unrelated explanation with words.", "stop", "unique B"),
    ("S7", "I cannot reach a conclusion.", "stop", "no answer"),
    ("S8", "Final Answer: B", "length", "unique B in a length-ended response"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for case_id, text, finish, intended in CASES:
        row = {"question_type": "multiple-choice", "options": {"A": "red", "B": "blue", "C": "green", "D": "None"},
               "answer": "B", "raw_text": text, "finish_reason": finish}
        results.append({"case_id": case_id, "raw_text": text, "finish_reason": finish,
                        "authored_interpretation": intended, "analysis": analyze(row)})
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "synthetic_cases.json").write_text(json.dumps(results, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    lines = ["# 파서 차이 예비 확인 — 합성 사례", "",
             "**직접 작성한 문장 8개다. MMMU 모델 응답의 실측 정확도나 오류 빈도가 아니다.**", "",
             "선택지: A=red, B=blue, C=green, D=None. 같은 텍스트를 고정 소스 함수에 전달했다.", "",
             "| 사례 | 작성 의도 | Qwen | MMMU(no random) | VLMEvalKit | hybrid100(보조) |",
             "|---|---|---|---|---|---|"]
    for r in results:
        answers = [str(r["analysis"][p]) if r["analysis"][p] is not None else "실패" for p in PARSERS]
        lines.append("| " + " | ".join([r["case_id"], r["authored_interpretation"], *answers]) + " |")
    lines += ["", "## 문장 원문", ""]
    for r in results:
        lines += [f"### {r['case_id']} ({r['finish_reason']})", "", r["raw_text"], ""]
    lines += ["## 이 단계에서 얻은 검증 항목", "",
              "- S3: Qwen은 considered 안의 red를 선택지 본문으로 매칭할 수 있다.",
              "- S4: 유효 선택지를 반환해도 모델 답이 하나로 정해진 것은 아니다. MMMU/hybrid의 낮은 실패율만으로 우수함을 판단하면 안 된다.",
              "- S5: 고정 VLMEvalKit의 answer-is 정규식은 먼저 나온 C를 잡을 수 있다. 답 번복 여부를 육안 기준에 포함한다.",
              "- S6: 파서별 장문 처리 조건 차이로 명확한 답도 실패할 수 있다.",
              "- S8: 원문에 답이 있어도 length 항상 Judge 정책이면 모두 Judge 대상이 된다. 이 정책의 이득/손해는 실제 응답과 동일 Judge 캐시로 확인한다.",
              "", "실제 실패 빈도와 최종 채택은 최종 HF raw 및 독립 육안 라벨링을 받은 뒤 판단한다."]
    (args.out / "casebook.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps({"kind": "synthetic_examples_only", "cases": len(results), "api_calls": 0, "out": str(args.out)}))


if __name__ == "__main__":
    main()
