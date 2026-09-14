## 파일 이름 기준

파일 이름만 보고도 용도를 구분할 수 있도록 역할 기준으로 통일한다. **코드 로직은 바꾸지 않고 파일명과 import/실행 참조만 정리했다.**

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

### 디렉터리 구조

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
└── compare_scoring_pipelines.py
```

### 파일 흐름

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
                최종 score 후보                    평가 방식 비교/분석

build_stress_dataset.py ─▶ run_inference.py ─▶ predictions_stress.jsonl
```
