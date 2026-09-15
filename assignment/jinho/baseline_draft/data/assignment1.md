# MMMU-val Baseline Evaluation Report — Qwen3-VL-4B-Instruct

- **팀명:** 4
- **팀원:** 트란트룽하우
- **작성일:** 2026-09-14
- **재현 커맨드:** `bash scripts/run_mmmu_eval.sh`

---

# 1. 환경 / 재현성

| 항목                | 값                                                                                               |
| ------------------- | ------------------------------------------------------------------------------------------------ |
| 모델 checkpoint     | `Qwen/Qwen3-VL-4B-Instruct`                                                                      |
| Checkpoint revision | `ebb281ec70b05090aa6165b016eac8ec08e71b17`                                                       |
| 추론 백엔드         | vLLM (v0.6.0+)                                                                                   |
| 사용 GPU            | NVIDIA GeForce RTX 4090 24GB (RunPod Cloud Instance)                                             |
| GPU VRAM            | 24GB                                                                                             |
| 실측 peak VRAM      | 약 18.5 GB (vLLM EngineCore 프로세스 점유 기준)                                                  |
| 총 소요 시간        | 569.78초 (약 9분 30초, 900문제 전체 평가)                                                        |
| MMMU dataset        | `MMMU/MMMU` (revision: `98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68`, split: `validation`)          |
| 의존성              | [baseline_draft/requirements.txt](../requirements.txt)                                           |
| 실행 커맨드         | `bash scripts/run_mmmu_eval.sh --model_path "Qwen/Qwen3-VL-4B-Instruct" --data_root "MMMU/MMMU"` |

### 재현 커맨드

```bash
bash scripts/run_mmmu_eval.sh \
  --model_path "Qwen/Qwen3-VL-4B-Instruct" \
  --data_root "MMMU/MMMU"
```

**재현성 요구사항 준수**

- 모델 checkpoint 및 dataset 위치는 hard-coded absolute path를 사용하지 않으며, CLI 인자(`--model_path`, `--data_root`)를 통해 동적으로 설정 가능합니다.

### 환경 정보

```text
OS: Linux (Ubuntu 22.04 LTS / RunPod)
Python: 3.10+ / 3.12+
PyTorch: >=2.4.0
Transformers: >=4.45.0
Datasets: >=3.0.0
Inference Engine: vLLM >= 0.6.0
CUDA: 12.1 / 12.4
GPU: NVIDIA GeForce RTX 4090 (24GB VRAM)
```

---

# 2. 프롬프트

## 2.1 실제 사용한 프롬프트

실제 모델 inference에 전달된 최종 prompt 구조는 다음과 같습니다:

```text
{question}
{options}

Answer with the option's letter from the given choices directly.
```

- `{question}`: MMMU 데이터셋의 문제 텍스트.
- `{options}`: 보기 리스트를 알파벳 순서(`A. ...`, `B. ...`, `C. ...`, `D. ...`)로 줄바꿈 정렬한 텍스트.
- 멀티모달 이미지: 샘플에 포함된 `image_1` ~ `image_7` 이미지가 multi-modal token/input으로 함께 전달됨.

### 출처

- Qwen-VL 공식 벤치마크 평가 방식 및 MMMU 공식 multiple-choice evaluation template을 차용하여 직접 구성.

### 선택 이유

- MMMU의 객관식(Multiple-Choice) 특성에 최적화하여 모델이 긴 CoT나 사족을 붙이지 않고 즉각적으로 정답 알파벳을 생성하도록 유도함.
- 후처리 파싱(Parsing) 단계에서 정답 추출의 모호성을 최소화하고 재현성을 극대화하기 위함.

---

# 3. 생성(Decoding) 설정

## 3.1 Sampling Recipe

`Inference Setup` 공식 권장 설정값을 엄격히 적용함:

| 파라미터             | 값   |
| -------------------- | ---- |
| `do_sample`          | True |
| `temperature`        | 0.7  |
| `top_p`              | 0.8  |
| `top_k`              | 20   |
| `repetition_penalty` | 1.0  |
| `presence_penalty`   | 1.5  |
| `seed`               | 42   |

### 출처

- `Inference Setup` 가이드라인 및 Qwen3-VL 공식 권장 evaluation recipe.

### 선택 이유

- 과도한 반복 생성을 억제(`presence_penalty = 1.5`)하고, 정답 선택의 다양성과 일관성을 조율(`temperature = 0.7`, `top_p = 0.8`, `top_k = 20`)하여 공식 baseline 재현 환경과 동일한 조건을 유지하기 위함.

---

## 3.2 생성 예산 / 이미지 해상도

| 파라미터           | 값                                                                |
| ------------------ | ----------------------------------------------------------------- |
| `max_model_length` | 9048                                                              |
| `max_new_tokens`   | 2048                                                              |
| `min_pixels`       | 1280 _ 28 _ 28 (1,003,520 pixels)                                 |
| `max_pixels`       | 5120 _ 28 _ 28 (4,014,080 pixels)                                 |
| 이미지 전처리 전략 | Dynamic Aspect Ratio Resizing (Qwen-VL Native Native Patch Token) |

### 선택 근거

- **VRAM vs Visual Resolution Trade-off:** MMMU는 다이어그램, 차트, 복잡한 회로도, 화학 구조식 등 고해상도 시각 정보가 필수적인 벤치마크입니다. `max_pixels = 5120 * 28 * 28` 설정을 통해 고해상도 디테일을 보존하면서도 24GB VRAM 한도 내에서 OOM(Out of Memory) 없이 안정적인 배치가 가능하도록 최적화했습니다.
- **Context Length:** 긴 복합 질문과 최대 7장의 고해상도 이미지를 처리하기 위해 `max_model_length`를 9048로 충분히 확보하였습니다.

---

# 4. 채점(Parsing) 방식

## 4.1 사용한 Parser / Logic

- 자체 구현 정규식 기반 결정론적 파서: [baseline_draft/src/parser.py](../src/parser.py)

## 4.2 동작 방식

1. 모델의 생성 텍스트(`output_text`)를 수신하여 공백 정규화.
2. **Primary Rule**:
   - 단일 알파벳 출력 여부 검사 (`^([A-H])$`).
   - LaTeX boxed 패턴 검사 (`\boxed{([A-H])}`).
   - 명시적 정답 구문 검사 (`The answer is (A)`, `Answer: A`, `Option: A`, `therefore, (A)` 등).
3. **Fallback Rule**:
   - 괄호로 묶인 단일 문자 탐색 (`([A-H])`).
   - 마지막 줄에 등장하는 단독 대문자 옵션(`\b([A-D])\b`) 탐색.
4. **Parsing Failure**:
   - 유효한 옵션 문자를 찾지 못한 경우 빈 문자열(`""`)을 반환하며, `is_correct = False`로 처리.

---

# 5. 결과

## 5.1 Subject-level Results

**전체 평가 규모: 30 subjects × 30 samples = 900 samples**

|         No. | Subject                             | Data Num | Correct |   Wrong |   Accuracy |
| ----------: | ----------------------------------- | -------: | ------: | ------: | ---------: |
|           1 | Accounting                          |       30 |      12 |      18 |     40.00% |
|           2 | Agriculture                         |       30 |      16 |      14 |     53.33% |
|           3 | Architecture_and_Engineering        |       30 |      10 |      20 |     33.33% |
|           4 | Art                                 |       30 |      19 |      11 |     63.33% |
|           5 | Art_Theory                          |       30 |      23 |       7 |     76.67% |
|           6 | Basic_Medical_Science               |       30 |      20 |      10 |     66.67% |
|           7 | Biology                             |       30 |      16 |      14 |     53.33% |
|           8 | Chemistry                           |       30 |      11 |      19 |     36.67% |
|           9 | Clinical_Medicine                   |       30 |      17 |      13 |     56.67% |
|          10 | Computer_Science                    |       30 |      15 |      15 |     50.00% |
|          11 | Design                              |       30 |      23 |       7 |     76.67% |
|          12 | Diagnostics_and_Laboratory_Medicine |       30 |      12 |      18 |     40.00% |
|          13 | Economics                           |       30 |      17 |      13 |     56.67% |
|          14 | Electronics                         |       30 |      10 |      20 |     33.33% |
|          15 | Energy_and_Power                    |       30 |      13 |      17 |     43.33% |
|          16 | Finance                             |       30 |      13 |      17 |     43.33% |
|          17 | Geography                           |       30 |      14 |      16 |     46.67% |
|          18 | History                             |       30 |      21 |       9 |     70.00% |
|          19 | Literature                          |       30 |      24 |       6 |     80.00% |
|          20 | Manage                              |       30 |       8 |      22 |     26.67% |
|          21 | Marketing                           |       30 |      19 |      11 |     63.33% |
|          22 | Materials                           |       30 |       6 |      24 |     20.00% |
|          23 | Math                                |       30 |      14 |      16 |     46.67% |
|          24 | Mechanical_Engineering              |       30 |       9 |      21 |     30.00% |
|          25 | Music                               |       30 |      13 |      17 |     43.33% |
|          26 | Pharmacy                            |       30 |      17 |      13 |     56.67% |
|          27 | Physics                             |       30 |      15 |      15 |     50.00% |
|          28 | Psychology                          |       30 |      22 |       8 |     73.33% |
|          29 | Public_Health                       |       30 |      14 |      16 |     46.67% |
|          30 | Sociology                           |       30 |      16 |      14 |     53.33% |
| **Overall** | **Macro Average**                   |  **900** | **459** | **441** | **51.00%** |

---

## 5.2 계산식

### Subject Accuracy

```text
Accuracy = (Correct / Data Num) × 100  (Data Num = 30)
```

예:

```text
Accounting: Correct = 12, Data Num = 30 -> Accuracy = 12 / 30 × 100 = 40.00%
Literature: Correct = 24, Data Num = 30 -> Accuracy = 24 / 30 × 100 = 80.00%
```

### Overall Macro Average

```text
Overall = (Acc_1 + Acc_2 + ... + Acc_30) / 30
        = 1530.0 / 30
        = 51.00%
```

_모든 subject의 sample 수가 30개로 동일하므로 macro average (51.00%)와 전체 900개 기준 micro accuracy (459 / 900 = 51.00%)는 수학적으로 완벽히 일치함._

---

# 6. 공식 수치와의 비교

| 항목                                  |          Overall (MMMU-val) |
| ------------------------------------- | --------------------------: |
| 공식 수치 (Qwen3-VL Technical Report) |                   **67.4%** |
| 우리 재현 결과                        |                   **51.0%** |
| 차이 (Δ)                              | **-16.4 percentage points** |

$$\Delta = 51.0\% - 67.4\% = -16.4\%p$$

### 공식 출처

- Qwen3-VL Technical Report & Official Repository: `https://github.com/QwenLM/Qwen3-VL`

---

# 7. 격차 분석

> **1000자 이내 작성 (실제 실행 후 raw_predictions.jsonl의 오답 샘플을 근거로 작성)**

본 실험의 MMMU-val 재현 결과는 51.00%로 공식 보고 수치(67.40%) 대비 16.40%p 낮게 측정되었다. `raw_predictions.jsonl`의 오답 데이터를 심층 분석한 결과, 주된 격차 원인은 다음과 같다.

1. **디코딩 전략 및 샘플링 영향:**  
   공식 벤치마크 평가는 대개 greedy search(`temperature=0.0`) 또는 log-likelihood 기반 choice ranking을 사용하는 반면, 본 실험은 `Inference Setup` 가이드라인에 따라 stochastic sampling(`temp=0.7`, `top_p=0.8`, `presence_penalty=1.5`)을 적용하였다. 샘플링 노이즈로 인해 복잡한 추론 과정에서 최적이 아닌 선택지를 생성하는 변동성이 발생하였다.

2. **파서 추출 실패(Empty Prediction, 84건 발생):**  
   전체 900개 샘플 중 84개(9.33%)에서 정답 알파벳을 추출하지 못해 오답 처리되었다. 실제 오답 출력을 확인한 결과, 회계(Accounting), 기계공학(Mechanical Engineering) 등 계산 문제에서 모델이 장문의 Chain-of-Thought 풀이 과정만 서술하고 최종 알파벳(`A~D`)을 명시하지 않거나, 보기 문자 대신 수식 결과값(예: `$51,180`, `$5.00`)만 서술한 사례가 다수 확인되었다.

3. **도메인별 시각 복잡도 편차:**  
   인문/예술/이론 계열(Literature 80.0%, Art_Theory 76.7%, Design 76.7%)에서는 높은 정확도를 보인 반면, 복합 도면과 미세 회로도가 포함된 재료(Materials 20.0%), 경영(Manage 26.7%), 전자(Electronics 33.3%)에서는 정확도가 저조하였다. `max_pixels` 해상도 제한 환경에서 미세 다이어그램 심볼 인식 손실이 발생한 것으로 분석된다.

향후 공식 수치 재현을 위해서는 greedy decoding 적용 및 최종 정답 옵션 출력을 강제하는 후처리 프롬프트 보강이 유효할 것이다.

---

# 8. 기타 특이사항 / 한계 (Optional)

### 특이사항

- `Inference Setup`의 권장 하이퍼파라미터(max_model_len=9048, max_new_tokens=2048, pixels limits, sampling params)를 엄격히 준수하여 900개 샘플 전체에 대해 569.78초(약 9.5분)라는 매우 빠른 속도로 평가를 완주함.
- vLLM multi-modal engine을 성공적으로 연동하여 24GB VRAM 환경에서 단 한 번의 OOM(Out of Memory) 없이 안정적인 배치 추론을 달성함.

### 한계

- 단일 패스 direct generation 방식을 취하여, 장문 추론을 수행하다가 옵션 알파벳을 생략하는 84건의 파싱 실패 샘플을 구제하지 못함.
- 향후 fine-tuned 체크포인트 평가 시 동일한 프롬프트 및 파이프라인을 그대로 적용하여 일관된 베이스라인 비교 기준으로 활용할 수 있음.

---

# 최종 검증 Checklist

- [x] Model checkpoint가 실제 사용한 checkpoint와 일치한다.
- [x] Checkpoint revision이 실제 실행한 revision(`ebb281ec70b05090aa6165b016eac8ec08e71b17`)과 일치한다.
- [x] MMMU dataset과 split이 명확하게 기록되어 있다 (`MMMU/MMMU`, `validation`, revision: `98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68`).
- [x] 총 평가 sample 수가 `900`인지 확인했다.
- [x] Subject 수가 `30`인지 확인했다.
- [x] 각 subject의 sample 수가 `30`인지 확인했다.
- [x] 모든 subject의 `Correct + Wrong = 30`인지 확인했다.
- [x] Accuracy 계산이 `Correct / 30 × 100`과 일치한다.
- [x] Overall 계산이 30개 subject의 macro average와 일치한다 (51.00%).
- [x] Prompt가 실제 inference code와 일치한다.
- [x] Decoding 설정이 실제 실행값과 일치한다.
- [x] Parser가 실제 evaluation code와 일치한다.
- [x] GPU 및 peak VRAM은 실제 측정값이다 (RTX 4090, ~18.5GB).
- [x] 실행 시간은 실제 900 samples evaluation 결과이다 (569.78초).
- [x] Hard-coded absolute path가 재현 커맨드에 포함되어 있지 않다.
- [x] 공식 67.4%의 출처가 명시되어 있다.
- [x] 공식 결과와 재현 결과의 차이 `Δ`가 정확하게 계산되었다 (-16.4%p).
- [x] Gap analysis가 1000자 이내이다 (공백 포함 약 820자).
- [x] 확인할 수 없는 값을 임의로 생성하지 않았다.
