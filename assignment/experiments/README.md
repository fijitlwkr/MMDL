# 실험 결과와 재현 도구

최신 평가 대상은 `max_new_tokens8192_hakyung`의 MMMU validation 900문항이며, 채점 결과는 **600/900(66.67%)**다.

```text
experiments/
├── submission/       최신 채점 결과·입력 데이터·실험 근거
├── raw_evaluation/   채점·결과 비교 도구
├── repetition/       반복·미완결 분석
├── failure_review/   문항 검토 자료·실패 유형 분석
│   ├── images/       원본 이미지
│   ├── packets/      검토 문서·라벨 양식
│   └── returned/     반환 라벨·집계 결과
└── scoring_lab/      과거 파서 선택 실험·H1·H2
```

## 결과 읽기

| 자료 | 내용 |
|---|---|
| [과제 제출 보고서](../../reports/mmmu_baseline.md) | 평가 방법·30과목 결과·공식 참조값 비교 |
| [최신 채점 결과·실험 근거](submission/README.md) | 파서 선택·채점 비교·원본 raw·저장 결과 재현 |
| [반복 분석](repetition/README.md) | 900응답의 반복 비율·정답률·생성 토큰 분석 |
| [실패 유형 60문항 분석](failure_review/returned/results/REPORT.md) | 챗 검토 기반 1차 분류·가중 집계·개선 방향 |
| [주관식 Qwen·MMMU 비교](submission/README.md#주관식-qwen-ab와-mmmu-비교) | 동일 53문항의 채점 방식·점수·문항별 판정 비교 |

## 실행과 검토

| 자료 | 용도 |
|---|---|
| [평가 도구](raw_evaluation/README.md) | 새 raw 채점·결과 비교·기존 입력 검증 기록 |
| [문항 검토 자료](failure_review/README.md) | 원본 이미지·배치 문서·반환 라벨·배포 ZIP 생성 |
| [과거 H1·H2 실험](scoring_lab/README.md) | 899문항 pilot의 파서 검토 근거와 고정 재현 묶음 |

각 분석 폴더의 README에서 결과와 재현 명령을 확인한다. `submission/input/`과 `judge/`의 원본을 기준으로 나머지 분석을 연결한다.
