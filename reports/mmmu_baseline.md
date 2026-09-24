# MMMU-val Baseline Evaluation Report — Qwen3-VL-4B-Instruct

- **팀명**: _(기입)_
- **팀원**: _(기입)_
- **작성일**: _(기입)_
- **재현 커맨드**: `(예: bash scripts/run_mmmu_eval.sh)`

---

## 1. 환경 / 재현성

| 항목 | 값 |
|---|---|
| 모델 checkpoint | `Qwen/Qwen3-VL-4B-Instruct` (ebb281ec70b05090aa6165b016eac8ec08e71b17) |
| 추론 백엔드 | _(예: transformers / vLLM, 버전)_ |
| 사용 GPU | _(모델명, VRAM)_ |
| 실측 peak VRAM | _(GB)_ |
| 총 소요 시간 | _(900문제 기준)_ |
| 의존성 | _(requirements.txt / environment.yml 경로 링크)_ |
| 실행 커맨드 | ```bash\n_(모델 checkpoint 위치와 MMMU 데이터 위치가 인자로 드러나야 함 — 예: --model_path <경로 또는 HF repo id> --data_root <MMMU 데이터 경로>. 하드코딩된 절대경로 대신 인자/환경변수로 받아서, 채점자가 자기 경로만 바꿔 끼우면 그대로 재현되게 작성)_\n``` |

## 2. 프롬프트

**실제 모델에 들어간 프롬프트 전문** (변수 부분은 `{}`로 표시):

```
_(여기에 그대로)_
```

- **출처**: _(직접 설계 / 차용한 도구·저장소명 + 링크)_
- **선택 이유**: _(왜 이 프롬프트를 골랐는지)_

<details>
<summary>작성 형식 예시 (내용은 예시일 뿐입니다. 본인이 실제 찾은/설계한 프롬프트로 교체)</summary>

```
Question: {question}
Choices:
A. {option_A}
B. {option_B}
C. {option_C}
D. {option_D}
Pick the single best choice from the list above.
```

- **출처**: (예시) 오픈소스 평가 툴킷 XYZ의 프롬프트 생성 함수에서 차용, 문구 일부만 수정
- **선택 이유**: (예시) 모델이 장황한 설명 없이 선택지 하나로 바로 답하도록 유도하기 위해 간결한 지시문 사용

</details>

## 3. 생성(Decoding) 설정

### 3.1 Sampling recipe

| 파라미터 | 값 |
|---|---|
| `do_sample` | |
| `temperature` | |
| `top_p` | |
| `top_k` | |
| `repetition_penalty` | |
| `presence_penalty` | |
| `seed` | |

- **출처**: _(모델 제공사의 공식 recipe를 찾았다면 그 출처/링크. 못 찾았거나 다른 값(예: greedy)을 쓰기로
  했다면 그 사실과 이유)_

### 3.2 생성 예산 / 이미지 해상도

| 파라미터 | 값 |
|---|---|
| `max_new_tokens` | |
| 이미지 해상도 처리 (`min_pixels`/`max_pixels` 등) | |

**선택 근거** (본인이 사용한 인프라 제약과 어떻게 연결되는지 — 속도/VRAM/응답 잘림 등 trade-off): _(적절히)_

## 4. 채점(파싱) 방식

채점 정책은 `hybrid100_mc_qwen_ab_open_no_length_gate_v2`다. [평가 실행기](../assignment/experiments/raw_evaluation/evaluate.py)와 [설정](../assignment/src/config.yaml)에 구현했다.

**출처와 선택 근거:** 기본 규칙과 Judge 프롬프트는 [Qwen3-VL `eval_utils.py`](https://github.com/QwenLM/Qwen3-VL/blob/96588727e44c78b25ba03ea03b8e12f7e64fd0da/evaluation/mmmu/eval_utils.py)의 `can_infer_option`, `can_infer_text`, `can_infer`, `build_prompt`를 사용한다(commit `96588727e44c78b25ba03ea03b8e12f7e64fd0da`). 선택지 문자 추출 뒤 선택지 텍스트 매칭을 시도한다. H1 파서 불일치 49건에서 Qwen은 검토 답과 47건 일치했고, H2의 Final Answer 보완 표본은 100/100건 일치해 이 조합을 채택했다. 표본 조건은 8절, 고정 함수와 라이선스는 [출처 목록](../assignment/experiments/raw_evaluation/frozen/THIRD_PARTY.md)에 정리했다.

1. **객관식:** Qwen 규칙과 사용자 정의 Final Answer 규칙을 적용한다. Final Answer 정규식의 유효 답 표기들이 모두 같고 마지막 매치의 답 문자 끝부터 응답 끝까지 **100자 이하**일 때 보완 후보를 인정한다. 이는 생성 길이 제한이 아니다. 두 규칙이 충돌하면 Judge, 충돌이 없으면 Qwen 답을 우선 사용하고 Qwen 미추출일 때 보완 답을 사용한다.
2. **주관식:** 참조답 원형을 `A`, `Other Answers`를 `B`로 두고 같은 Qwen 규칙을 적용한다. Final Answer 문자 보완은 적용하지 않는다. 이 방식은 참조답을 사용하는 동치 판정이다.
3. **Judge 전송:** 추론 종료 사유에 관계없이 규칙 추출 성공은 자동 처리하며, 미추출·규칙 충돌만 Judge로 보낸다. 객관식 Judge에는 질문·선택지·응답을 전달하고 gold는 별도로 보여주지 않는다. 주관식 Judge에는 A에 참조답이 들어간다. 고정 프롬프트는 응답과 가장 비슷한 선택지를 찾도록 한다.
4. **Judge 설정:** `gpt-4.1-mini-2025-04-14`, `temperature=0`, `top_p=1`, `seed=3407`, `max_tokens=8`. Judge 응답이 `stop`일 때 고정 Qwen 규칙으로 유효 선택지를 읽는다. `Z`·유효 답 없음·Judge 자체의 비정상 종료는 추출 실패로 오답 처리한다. API 오류·미응답은 `pending`으로 분리하며 모든 요청 완료 후 정확도를 집계한다. 랜덤 답과 완료된 Z 재호출은 사용하지 않는다.

규칙 단독 비교에는 [MMMU `eval_utils.py`](https://github.com/MMMU-Benchmark/MMMU/blob/51ce7f3e829c16bb44bc5445782686b4c3508794/eval/eval_utils.py)(commit `51ce7f3e829c16bb44bc5445782686b4c3508794`)를 사용했다. 랜덤 폴백을 제거하고 파싱 실패를 오답 처리했다. 주관식의 문자열로 저장된 복수 허용 답 3건은 목록으로 변환했다.

재현·근거: [채점 결과·선택 근거](../assignment/experiments/submission_20260923/README.md), [오프라인 재현 스크립트](../assignment/experiments/submission_20260923/reproduce.py), [원본 raw](../assignment/experiments/submission_20260923/input/raw.jsonl), [실행 메타데이터](../assignment/experiments/submission_20260923/input/run_metadata.json), [집계](../assignment/experiments/submission_20260923/results/scores.json), [동일 입력 비교](../assignment/experiments/submission_20260923/results/comparisons.json).

## 5. 결과

최신 raw의 900개 고유 ID를 모두 평가했다. 원본 SHA-256은 `ef23f0c49d9b1ae6c62b9625fbd52cce474a0c035c1a644cfa737e0967daa313`이며, 아래 표는 **v2 + GPT-4.1-mini** 결과다.

| No. | Subject | Data Num | Correct | Wrong | Accuracy |
|---:|---|---:|---:|---:|---:|
| 1 | Accounting | 30 | 22 | 8 | 73.33% |
| 2 | Agriculture | 30 | 14 | 16 | 46.67% |
| 3 | Architecture_and_Engineering | 30 | 16 | 14 | 53.33% |
| 4 | Art | 30 | 18 | 12 | 60.00% |
| 5 | Art_Theory | 30 | 24 | 6 | 80.00% |
| 6 | Basic_Medical_Science | 30 | 23 | 7 | 76.67% |
| 7 | Biology | 30 | 15 | 15 | 50.00% |
| 8 | Chemistry | 30 | 17 | 13 | 56.67% |
| 9 | Clinical_Medicine | 30 | 24 | 6 | 80.00% |
| 10 | Computer_Science | 30 | 19 | 11 | 63.33% |
| 11 | Design | 30 | 25 | 5 | 83.33% |
| 12 | Diagnostics_and_Laboratory_Medicine | 30 | 10 | 20 | 33.33% |
| 13 | Economics | 30 | 25 | 5 | 83.33% |
| 14 | Electronics | 30 | 24 | 6 | 80.00% |
| 15 | Energy_and_Power | 30 | 19 | 11 | 63.33% |
| 16 | Finance | 30 | 21 | 9 | 70.00% |
| 17 | Geography | 30 | 19 | 11 | 63.33% |
| 18 | History | 30 | 21 | 9 | 70.00% |
| 19 | Literature | 30 | 24 | 6 | 80.00% |
| 20 | Manage | 30 | 21 | 9 | 70.00% |
| 21 | Marketing | 30 | 25 | 5 | 83.33% |
| 22 | Materials | 30 | 21 | 9 | 70.00% |
| 23 | Math | 30 | 19 | 11 | 63.33% |
| 24 | Mechanical_Engineering | 30 | 12 | 18 | 40.00% |
| 25 | Music | 30 | 7 | 23 | 23.33% |
| 26 | Pharmacy | 30 | 23 | 7 | 76.67% |
| 27 | Physics | 30 | 23 | 7 | 76.67% |
| 28 | Psychology | 30 | 22 | 8 | 73.33% |
| 29 | Public_Health | 30 | 28 | 2 | 93.33% |
| 30 | Sociology | 30 | 19 | 11 | 63.33% |
| | **Overall (macro avg)** | **900** | **600** | **300** | **66.67%** |

`Subject accuracy = Correct / 30 × 100`, `Overall = mean(30개 과목 accuracy)`로 계산했다. 과목별 값을 반올림하기 전에 평균을 구했으며, 과목당 30문항이므로 `600 / 900 × 100 = 66.666…%`와 일치한다. 표시는 소수 둘째 자리로 반올림했다.

객관식 **560/847(66.12%)**, 주관식 **40/53(75.47%)**다. 자동 처리 555건·Judge 처리 345건이며 미완료는 0건이다. 오답 300건에는 추출 실패 36건이 포함된다. [과목별 결과 파일](../assignment/experiments/submission_20260923/results/subject_scores.md)과 [900문항별 정오·처리 경로](../assignment/experiments/submission_20260923/results/item_results.jsonl)에서 근거를 확인할 수 있다.

## 6. 공식 수치와의 비교

| 구분 | Overall (MMMU validation) |
|---|---:|
| 과제에서 제시한 공식 참조값(Qwen3-VL Technical Report 기준) | 67.40% |
| 우리 결과: 최신 raw·v2·GPT-4.1-mini | 66.67% |
| 차이: 우리 결과 − 공식 참조값 | **−0.73%p** |

차이는 반올림 전 값으로 `600 / 900 × 100 − 67.4 = −0.7333…%p`다. 공식 참조값은 과제 지시문의 67.4%를 사용했다.

## 7. 격차 분석

재현 점수는 66.67%(600/900)로 공식 참조값 67.40%보다 0.73%p 낮았다. **응답의 반복·중단과 채점 방식에 따른 점수 차이**를 분석했다.

**응답의 반복·중단:** 생성 상한 8,192토큰에 도달한 128건의 정확도는 35.94%로 정상 종료 772건의 71.76%보다 낮았다. 상한 도달 응답은 전체의 14.22%지만, 전체 오답의 27.33%(82/300)와 답 추출 실패의 69.44%(25/36)를 차지했다. 실제 `validation_Accounting_5`는 같은 해석을 85회 반복하다 문장 중간에서 종료됐고, 답 추출도 실패했다.

**채점 방식:** 동일 응답·자동 처리 537건·Judge 대상 363건을 고정하고 Judge만 GPT-4.1-mini에서 GPT-4o-mini로 바꾸자 66.00%→63.00%로 낮아졌다. 답은 83건에서 달랐고 정답 증가 5건·감소 32건으로 **27문항·3.00%p** 차이가 발생했다. 동일 응답의 채점 모델 비교에서 공식 참조값과의 격차 0.73%p보다 큰 점수 차이가 관찰됐다. [집계·비교 결과](../assignment/experiments/submission_20260923/results/comparisons.json)

## 8. 기타 특이사항 / 한계 (Optional)

- 파서 검토 [H1](../assignment/experiments/scoring_lab/legacy_pilot/h1/REPORT.md)·[H2](../assignment/experiments/scoring_lab/legacy_pilot/h2/REPORT.md)는 과거 899문항 pilot(생성 seed 42, cap 9048)에서 선정한 고유 139문항을 검토자 1명이 확인한 결과다.
