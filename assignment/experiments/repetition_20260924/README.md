# 반복·미완결 분석 — 2026-09-24

최신 900개 응답의 반복 패턴을 고정 v2 채점 결과와 연결한 분석이다. 20% 기준 반복 후보는 **73/900(8.11%)**이며, 이 집단의 정책 정답률은 **24/73(32.88%)**, 기준 미만 집단은 **576/827(69.65%)**다. 추가 API 호출·재추론은 없다.

- [요약 보고서](../../../reports/repetition_analysis_20260924.md): 결과와 발표용 해석.
- [상세 보고서](results/REPORT.md): 계산 정의, 종료 사유별 비교, 10%·20%·30% 민감도, 사례.
- [900문항별 지표](results/per_item.jsonl): 원문 해시, 반복 위치·근거, 정오·종료·추출 상태.
- [집계·설정·입력 해시](results/summary.json): 과목별·유형별 결과와 출처 확인.
- [분석 코드](analyze.py): Python 3.10 이상 표준 라이브러리만 사용.

## 입력과 출처

[제출 묶음](../submission_20260923/README.md)의 [raw.jsonl](../submission_20260923/input/raw.jsonl), [run_metadata.json](../submission_20260923/input/run_metadata.json), [scores.json](../submission_20260923/results/scores.json), [item_results.jsonl](../submission_20260923/results/item_results.jsonl)을 읽는다. 입력 해시·900개 ID·문항 메타데이터·집계가 일치해야 실행된다.

원본 SHA-256: `ef23f0c49d9b1ae6c62b9625fbd52cce474a0c035c1a644cfa737e0967daa313`.
채점 정책은 `hybrid100_mc_qwen_ab_open_no_length_gate_v2`, Judge는 `gpt-4.1-mini-2025-04-14`다. 원본 응답과 기존 점수 600/900을 변경하지 않는다.

## 재현

저장소 루트에서 새 빈 출력 경로를 지정한다.

```bash
python assignment/experiments/repetition_20260924/analyze.py --self-test
python assignment/experiments/repetition_20260924/analyze.py --out assignment/experiments/raw_evaluation/outputs/repetition_check
```

`REPORT.md`, `per_item.jsonl`, `summary.json` 3개가 생성된다. 다른 입력 묶음은 `--source`로 지정하되 동일한 900문항 구조가 필요하다. 저장된 결과는 `.gitattributes`로 원래 바이트를 보존한다. 스크립트 해시는 줄바꿈을 LF로 정규화한 값(`script_sha256_lf`)이며, 다른 운영체제에서 재생성한 파일을 비교할 때도 줄바꿈 차이를 정규화한다.

자동 반복 후보는 사람 검토로 확정한 오류가 아니다. 반복과 낮은 정답률의 연관을 관찰한 분석이며 반복 제거의 성능 향상 효과를 측정한 실험은 아니다.
