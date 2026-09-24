# 실험 결과와 재현 도구

최신 평가 대상은 `max_new_tokens8192_hakyung`의 MMMU validation 900문항이며, 채점 결과는 **600/900(66.67%)**다.

## 결과 읽기

| 자료 | 내용 |
|---|---|
| [과제 제출 보고서](../../reports/mmmu_baseline.md) | 평가 방법·30과목 결과·공식 참조값 비교 |
| [최신 채점 결과·실험 근거](submission_20260923/README.md) | 파서 선택·채점 비교·원본 raw·저장 결과 재현 |
| [반복 분석](repetition_20260924/README.md) | 900응답의 반복 비율·정답률·생성 토큰 분석 |
| [실패 유형 60문항 분석](failure_review_20260924/returned_20260924/results/REPORT.md) | 챗 검토 기반 1차 분류·가중 집계·개선 방향 |

## 실행과 검토

| 자료 | 용도 |
|---|---|
| [평가 도구](raw_evaluation/README.md) | 새 raw 채점·결과 비교·기존 입력 검증 기록 |
| [문항 검토 자료](failure_review_20260924/README.md) | 원본 이미지·배치 문서·반환 라벨·배포 ZIP 생성 |
| [과거 H1·H2 실험](scoring_lab/README.md) | 899문항 pilot의 파서 검토 근거와 고정 재현 묶음 |

각 분석 폴더의 README에서 결과와 재현 명령을 확인한다. `submission_20260923/input/`과 `judge/`의 원본을 기준으로 나머지 분석을 연결한다.
