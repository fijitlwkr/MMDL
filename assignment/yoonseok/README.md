# MMMU Baseline Draft

Qwen3-VL-4B-Instruct의 MMMU validation 평가를 위한 실행 패키지입니다. `baseline_draft/` 폴더를 독립 저장소로 올리거나 기존 저장소에 그대로 추가할 수 있습니다.

> **현재 결과: 기존 900문항 예측을 가져와 CPU에서 재채점한 예비 결과**  
> 새 GPU 추론은 실행하지 않았습니다. 기존 데이터 1문항의 선택지 누락을 발견했고, 해당 문항은 데이터 오류로 기록하여 오답 처리했습니다. 최종 baseline은 지정 revision의 데이터로 다시 실행해야 합니다.

## 디렉터리 구조

```text
baseline_draft/
├── README.md
├── .gitignore
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
├── common.py
├── THIRD_PARTY.md
├── vendor/
│   ├── __init__.py
│   ├── mmmu_eval.py
│   ├── vlmevalkit_matching.py
│   ├── sources.json
│   ├── MMMU-LICENSE
│   └── VLMEvalKit-LICENSE
├── tests/
│   └── test_pipeline.py
└── data/
    ├── baseline_score.json
    ├── baseline_table.md
    └── eval_val.json
```

`common.py`는 중복 없는 입력 검증과 파일 저장을, `vendor/`는 버전을 고정한 공식 parser의 독립 실행을 위한 파일입니다. `vendor/`와 라이선스도 함께 올려야 합니다. 예측·이미지·가상환경·캐시는 `.gitignore`에 따라 제외됩니다.

## 파일 이름과 역할

| 역할 | 파일명 | 사용 시점 |
|---|---|---|
| RunPod 환경 변수 | `env.sh` | 모든 실행 전 `source` |
| Python 의존성 | `requirements.txt` | 최초 환경 설치 |
| 환경 설치/검증 | `setup_env.sh` | 새 Pod에서 최초 1회 |
| Smoke test 전체 실행 | `smoke_test.sh` | 900문항 실행 전 |
| 공통 MMMU 데이터셋 생성 | `build_dataset.py` | 지정 revision의 smoke/full 데이터 생성 |
| 공통 vLLM 추론 | `run_inference.py` | smoke/stress/full 추론 또는 기존 Qwen 결과 가져오기 |
| MC parser 구현/비교 | `mc_parsers.py` | 평가 스크립트에서 import, CPU parser 점검 |
| 최종 baseline 평가 | `evaluate_baseline.py` | MC와 open 전용 로직으로 score 후보 산출 |
| 평가 파이프라인 비교 | `compare_scoring_pipelines.py` | MMMU/VLMEvalKit 규칙 parser 비교 |
| Stress dataset 생성 | `build_stress_dataset.py` | 긴 입력·다중 이미지·open 경로 점검 |
| 공통 입력/저장 | `common.py` | UID·스키마·900문항 구성 검증, 원자적 결과 저장 |

## `data/` 파일 설명

세 결과 파일은 동일한 `data/predictions_val.jsonl`에서 생성했습니다. 현재 서버에는 가져온 예측 파일도 있으나, GitHub용 패키지와 추적 대상에서는 제외합니다. 새 환경에서는 예측 파일을 생성하거나 보존본을 가져와야 합니다. 새로 추론하면 기존 점수를 정확히 재현하는 것은 아닙니다.

| 파일 | 생성 스크립트 | 현재 결과 |
|---|---|---|
| [baseline_score.json](data/baseline_score.json) | `compare_scoring_pipelines.py` | MMMU MC 방식 **50.00% (450/900)**, VLMEvalKit 규칙 방식 **14.89% (134/900)**. 과목별 점수, 실패 UID, random fallback, parser 간 불일치 포함 |
| [baseline_table.md](data/baseline_table.md) | `compare_scoring_pipelines.py` | MMMU MC 방식의 30과목·900문항 표, macro average **50.00%** |
| [eval_val.json](data/eval_val.json) | `evaluate_baseline.py` | MC/open을 구분한 MMMU 방식 **48.89% (440/900)**. 문항별 정오답과 macro/micro 포함 |

JSON의 accuracy는 0~1, Markdown 표는 % 단위입니다. 세 파일에 입력 SHA-256과 parser source commit이 기록되어 있습니다. 예시로 전달된 50.33%·30.11%·49.11%는 이 데이터의 결과로 사용하지 않았습니다.

### 점수가 다른 이유

- 비교 스크립트는 **채점 단계에서만** open 정답을 `A`, `Other Answers`를 `B`로 놓고 두 MC parser에 같은 응답을 입력합니다. 정답은 모델 추론 프롬프트에 넣지 않습니다.
- 최종 평가 스크립트는 open 문항에 MMMU `parse_open_response`와 `eval_open`을 사용합니다. 숫자 및 정답 별칭 처리도 MC 변환과 다릅니다.
- MMMU MC parser는 답을 추출하지 못하면 seed 42의 무작위 선택을 사용하며, 그 결과를 정확도에 포함합니다. `random_fallback_uids`로 따로 기록합니다.
- VLMEvalKit은 고정 commit의 **규칙 parser만** 사용합니다. 추출 실패는 오답 처리하며 GPT judge나 random fallback을 호출하지 않습니다.
- 이 VLMEvalKit 버전에는 응답 길이와 선택지 위치에 관한 규칙이 있습니다. 기존 Qwen 코드에 복사되어 있던 parser와 동일한 구현으로 간주하지 않습니다.
- 과거의 **62.22%**는 GPT judge와 fallback을 포함한 다른 평가 조건의 기록입니다.

### 발견한 데이터 오류

`validation_Geography_15`는 정답이 `D`인데 기존 JSONL과 원본 TSV의 D 선택지 내용이 비어 있습니다. 내용을 임의로 복원하지 않았습니다. 가져오기 시 `data_issue`로 기록하고 두 평가 스크립트 모두 오답 처리하며 분모 900을 유지합니다. 이 예외 때문에 현재 결과는 최종 공식 재현 점수로 취급하지 않습니다.

## 파일 흐름

```text
env.sh + requirements.txt
        │
        ▼
setup_env.sh
        │
        ├──────────────▶ smoke_test.sh
        │                    ├─ build_dataset.py
        │                    ├─ run_inference.py
        │                    ├─ mc_parsers.py
        │                    └─ 두 평가 스크립트 (--allow-partial)
        │
        └─ build_dataset.py ─▶ run_inference.py ─▶ predictions_val.jsonl
                                              │
                           ┌──────────────────┴──────────────────┐
                           ▼                                     ▼
                evaluate_baseline.py              compare_scoring_pipelines.py
                └─ eval_val.json                  ├─ baseline_score.json
                   최종 score 후보                └─ baseline_table.md
                                                     비교/분석

build_stress_dataset.py ─▶ run_inference.py ─▶ predictions_stress.jsonl
```

## 실행 방법

모든 명령은 `baseline_draft/`에서 실행합니다. Python 3.12, Linux, CUDA GPU를 기준으로 합니다. CLI의 `--help`는 vLLM 설치 없이 확인할 수 있습니다.

### 1. 최초 환경 설치

```bash
bash setup_env.sh
source env.sh
```

`.venv/`에 의존성을 설치하고 GPU 접근·import·parser를 검사합니다. 캐시는 기본적으로 패키지의 `.cache/huggingface`에 저장하며 기존 `HF_HOME`이 있으면 유지합니다. 새 환경의 설치와 GPU 동작은 실행 시 검증합니다. API 키는 필요하지 않습니다.

```bash
bash setup_env.sh --check-only
```

### 2. Smoke test

```bash
bash smoke_test.sh
```

Accounting·Physics·Art에서 각 1문항을 가져와 추론하고 두 평가 경로를 검사합니다. 매 실행마다 `data/smoke.XXXXXX/`를 새로 만들어 결과를 보존합니다.

GPU 없이 parser만 확인하려면 NumPy가 설치된 Python에서 다음을 실행합니다.

```bash
bash smoke_test.sh --parsers-only
python -m unittest discover -s tests -v
```

### 3. Full dataset → 추론 → 평가

```bash
source env.sh
"${BASELINE_PYTHON}" build_dataset.py
"${BASELINE_PYTHON}" run_inference.py
"${BASELINE_PYTHON}" evaluate_baseline.py --force
"${BASELINE_PYTHON}" compare_scoring_pipelines.py --force
```

배포된 `data/`에는 기존 점수가 있으므로 평가 예시는 `--force`로 갱신합니다. 다른 출력 경로를 지정해 보존할 수도 있습니다. 모든 스크립트는 기본적으로 기존 출력 파일의 덮어쓰기를 거부합니다.

기본값:

| 항목 | 값 |
|---|---|
| 모델 | `Qwen/Qwen3-VL-4B-Instruct` |
| 모델 revision | `ebb281ec70b05090aa6165b016eac8ec08e71b17` |
| 데이터 / revision | `MMMU/MMMU` / `98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68` |
| split / 구성 | validation, 30과목 × 30문항 |
| dtype | bfloat16 |
| 입력 prompt | 기존 Qwen MMMU 형식, 추가 CoT 없음 |
| 생성 한도 / context | 2,048 / 9,048 |
| temperature / top-p / top-k | 0.7 / 0.8 / 20 |
| repetition / presence penalty | 1.0 / 1.5 |
| seed / batch size | 42 / 32 |
| min / max pixels | 1,003,520 / 4,014,080 |

Revision 값은 이전 과제 안내 정리에 근거합니다. 모델을 로컬 경로로 지정하면 그 경로가 지정 revision의 snapshot인지 사용자가 확인해야 하며, 메타데이터의 `revision_applied`는 `null`로 기록합니다. 기존 사전 점검 실행과 새 실행의 batch 구성·환경이 같다고 가정하지 않습니다.

### 4. Stress test

```bash
"${BASELINE_PYTHON}" build_stress_dataset.py
"${BASELINE_PYTHON}" run_inference.py \
  --input data/dataset_stress.jsonl \
  --output data/predictions_stress.jsonl
"${BASELINE_PYTHON}" evaluate_baseline.py \
  --input data/predictions_stress.jsonl \
  --output data/eval_stress.json --allow-partial
```

Full manifest에서 질문·선택지 문자 수가 긴 문항, 이미지 2개 이상인 문항, open 문항을 각각 최대 2개 고릅니다. 중복 UID는 합칩니다. 실제 문항을 그대로 사용하며 텍스트를 인위적으로 늘리지 않습니다. 세 경로 중 하나라도 없으면 오류로 알려줍니다.

### 5. 기존 Qwen 예측 재사용

현재 포함된 결과를 생성한 경로입니다. 이 모드에서는 GPU나 judge API를 호출하지 않습니다.

```bash
"${BASELINE_PYTHON}" run_inference.py \
  --import-qwen-jsonl /workspace/mmdl/results/mmmu_validation900.jsonl
"${BASELINE_PYTHON}" evaluate_baseline.py --force
"${BASELINE_PYTHON}" compare_scoring_pipelines.py --force
```

기존 `result.gen`을 그대로 `prediction`에 복사하고 `gen_raw`도 보존합니다. 과거 실행의 model/data revision, finish reason, token 수를 새 기본값으로 소급해 채우지 않습니다. 이미 예측 파일이 있으면 다른 `--output`을 지정하거나 `--force`를 명시합니다.

## 공통 데이터 형식

Dataset과 predictions는 JSONL이며, 한 줄이 한 문항입니다.

```json
{"uid":"validation_Accounting_1","subject":"Accounting","split":"validation","question_type":"multiple-choice","question":"...","options":{"A":"...","B":"..."},"answer":"B","images":["dataset_val_images/validation_Accounting_1_1.png"],"provenance":{"dataset":"MMMU/MMMU","revision":"..."}}
```

- MC는 `question_type="multiple-choice"`, open은 `"open"`과 빈 `options`를 사용합니다.
- 이미지 경로는 manifest 파일 위치를 기준으로 해석합니다.
- Predictions에는 `prediction`, `prediction_raw`, `finish_reason`, `generated_tokens` 등이 추가됩니다.
- 새 추론은 batch별 시간, 생성 token 수, 종료 사유, 설정, 환경 버전과 device-wide GPU 메모리 표본 최댓값을 저장합니다. 1초 간격 메모리 관측은 프로세스별 정확한 peak 측정과 다릅니다.
- UID 중복, 정답 누락, 잘못된 유형, 추론 오류가 있는 입력은 거부합니다. 최종 평가는 30×30 validation 구성을 확인하며 smoke/stress에는 `--allow-partial`이 필요합니다.

## 검증 범위

- CPU parser self-test 및 pipeline 회귀 테스트 통과.
- 기존 900문항 가져오기와 두 평가 스크립트의 실제 실행 완료.
- Shell 문법 검사와 CLI 도움말 검사 완료.
- 새 환경 의존성 설치, Hugging Face 다운로드, 실제 GPU smoke/full 추론은 아직 실행하지 않음. vLLM 연결부는 mock 기반 CPU 테스트로 검증했습니다.

공식 parser의 출처·고정 commit·라이선스는 [THIRD_PARTY.md](THIRD_PARTY.md)와 [vendor/sources.json](vendor/sources.json)에 있습니다.
