# 실험 결과와 재현 도구 (baseline 과제 전용)

평가 대상은 [`results/mmmu_team_baseline`](../../results/mmmu_team_baseline/README.md)(실행 당시 이름 `max_new_tokens8192_hakyung`)의 MMMU validation 900문항이며, 채점 결과는 **600/900(66.67%)**다.

```text
experiments/
├── submission/       최신 채점 결과·입력 데이터·실험 근거
├── gap_checks/       격차 분석·소요 시간 보조 계산 (채점 도구는 code/scoring/으로 이동)
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
| [무작위 fallback 기대값](gap_checks/README.md#무작위-fallback-기대값) | Qwen 공개 평가 코드 방식(추출 실패 시 무작위 선택) 적용 시 기대 점수 |
| [분야·과목별 추정 시간](gap_checks/README.md#분야과목별-추정-시간) | 생성 시간을 출력 토큰 비중으로 배분한 추정 |
| [두 8192 실행 비교](gap_checks/README.md#두-8192-실행-비교) | 재추론 시 과목 점수·토큰 비중·생성 시간의 변화 |

## 실행과 검토

| 자료 | 용도 |
|---|---|
| [평가 도구](../../code/scoring/README.md) | 새 raw 채점·결과 비교·기존 입력 검증 기록 |
| [문항 검토 자료](failure_review/README.md) | 원본 이미지·배치 문서·반환 라벨·배포 ZIP 생성 |
| [과거 H1·H2 실험](scoring_lab/README.md) | 899문항 pilot의 파서 검토 근거와 고정 재현 묶음 |

각 분석 폴더의 README에서 결과와 재현 명령을 확인한다. `submission/input/`과 [`results/mmmu_team_baseline/`](../../results/mmmu_team_baseline/README.md)의 원본을 기준으로 나머지 분석을 연결한다.

## 개인 탐색 실험 (참고용)

[hakyung님 개인 작업 공간](../archive/hakyung/experiments/README.md)에 baseline 최종 config 확정 전 탐색한 실험이 있다. 모두 초기 `max_new_tokens=2048`(`max_model_len=9048`) config([`exp0_baseline`](../archive/hakyung/experiments/exp0_baseline), 45.56%/900)를 기준으로 하며, 최종 8192 파이프라인과는 다르다. `assignment/archive/`의 코드는 참조·의존하지 않지만, 아래 결과 문서는 보고서 근거로 인용한다.

| 실험 | 확인할 내용 |
|---|---|
| [파서·Judge 비교](../archive/hakyung/experiments/expA_parser_comparison/outputs/parser_comparison.md) | 자체 규칙 파서와 Qwen 공식 규칙의 900문항 전체 일치(diff 0), Judge 추가 시 45.56%→49.67% |
| [출력 예산 비교](../archive/hakyung/experiments/expB_budget_increase/outputs/comparison.md) | 2048→8192 단일 변수 비교, 230문항 부분집합, 23.91%→38.26%(McNemar p=0.0001) |
| [presence_penalty 비교](../archive/hakyung/experiments/expC_presence_penalty/outputs/comparison.md) | 0/0.5/1.5 비교, 200문항 부분집합, 1.5가 정확도·파싱 실패율 모두 최선 |
| [이미지 배치 비교](../archive/hakyung/experiments/expD_image_layout/outputs/comparison.md) | inline/prefix 비교, 다중 이미지 23문항, 유의한 차이 없음(McNemar p=1, 저검정력) |
| [seed 재현성](../archive/hakyung/experiments/expF_seed_repro/outputs/comparison.md) | seed 3개로 900문항 재생성, macro 정확도 표준편차 0.0038, McNemar 모두 비유의 |
