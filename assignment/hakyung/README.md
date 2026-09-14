## 디렉터리 구조

```text
baseline_draft/
├── env.sh
├── requirements.txt
├── setup_env.sh
├── smoke_test.sh
├── build_dataset.py
├── build_stress_dataset.py
├── run_inference.py
├── mc_parsers.py
├── evaluate_baseline.py
├── compare_scoring_pipelines.py
└── data/
    ├── baseline_score.json
    ├── baseline_table.md
    └── eval_val.json
```

### 파일 이름

| 역할 | 새 파일명 | 사용 시점 |
|---|---|---|
| RunPod 환경 변수 | `env.sh` | 모든 실행 전 |
| Python 의존성 | `requirements.txt` | 최초 환경 설치 |
| 환경 설치/검증 | `setup_env.sh` | 새 Pod에서 최초 1회 |
| Smoke test 전체 실행 | `smoke_test.sh` | 900문항 실행 전 빠른 검증 |
| 공통 MMMU 데이터셋 생성 | `build_dataset.py` | smoke/full dataset 생성 |
| 공통 vLLM 추론 | `run_inference.py` | smoke/stress/full inference |
| MC parser 구현/비교 | `mc_parsers.py` | smoke parser test 및 비교 평가에서 import |
| 최종 baseline 평가 | `evaluate_baseline.py` | 900문항 최종 score 후보 산출 |
| 평가 파이프라인 비교 | `compare_scoring_pipelines.py` | MMMU/VLMEvalKit 방식 비교 |
| Stress dataset 생성 | `build_stress_dataset.py` | 긴 입력·다중 이미지·open 경로 점검 |

### `data/` 파일 설명

세 파일 모두 `data/predictions_val.jsonl`을 입력으로 채점한 결과다. 현재
저장소에는 이 입력 파일이 없으므로, 결과를 다시 생성하려면 먼저
`run_inference.py`로 예측 파일을 만들어야 한다.

| 파일 | 생성 스크립트 | 설명 |
|---|---|---|
| `baseline_score.json` | `compare_scoring_pipelines.py` | MMMU 공식 선택지 파서와 VLMEvalKit 파서의 과목별 정확도, macro average, 파싱 실패 UID, 두 파서 간 불일치 문항을 담은 상세 비교 결과다. 현재 MMMU 방식은 50.33%, VLMEvalKit 방식은 30.11%다. |
| `baseline_table.md` | `compare_scoring_pipelines.py` | `baseline_score.json` 중 1차 채택 방식인 MMMU 공식 파서 결과를 제출용 표 형태로 요약한 파일이다. 30개 과목, 900문항의 overall macro average는 50.33%다. |
| `eval_val.json` | `evaluate_baseline.py` | MMMU 공식 평가 로직에 따라 multiple-choice와 open-ended 문항을 각각 채점한 상세 결과다. 문항별 파싱 결과와 정오답, 과목별 정확도, macro/micro accuracy를 포함하며 현재 결과는 49.11%다. |

`baseline_score.json`/`baseline_table.md`와 `eval_val.json`의 점수가 다른 이유는
open-ended 문항 처리 방식이 다르기 때문이다. 비교 스크립트는 open-ended
정답을 `A`, `Other Answers`를 `B`로 둔 선택지 문제로 변환해 두 MC 파서를
비교하고, 최종 평가 스크립트는 MMMU의 open-ended 전용 parser/evaluator를
사용한다.

## 파일 흐름

```text
env.sh + requirements.txt
        │
        ▼
setup_env.sh
        │
        ├──────────────▶ smoke_test.sh
        │                    │
        │                    ├─ build_dataset.py
        │                    ├─ run_inference.py
        │                    └─ mc_parsers.py
        │
        └─ build_dataset.py ─▶ run_inference.py ─▶ predictions_val.jsonl
                                              │
                           ┌──────────────────┴──────────────────┐
                           ▼                                     ▼
                evaluate_baseline.py              compare_scoring_pipelines.py
                │                                  ├─ baseline_score.json
                └─ eval_val.json                  └─ baseline_table.md
                최종 score 후보                    평가 방식 비교/분석

build_stress_dataset.py ─▶ run_inference.py ─▶ predictions_stress.jsonl
```
