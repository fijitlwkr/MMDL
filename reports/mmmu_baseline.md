# MMMU-val Baseline Evaluation Report — Qwen3-VL-4B-Instruct

- **팀명**: Team4
- **팀원**: 이하경, 채윤석, 트란트룽하우, 홍성준
- **작성일**: 2026.09.27
- **보고서 위치**: [`reports/mmmu_baseline.md`](../reports/mmmu_baseline.md)(과제 가이드), [`assignment/assignment1.md`](../assignment/assignment1.md)(강의 자료) — 두 파일은 같은 내용
- **재현 커맨드**: `HF_HOME=<HF_CACHE_DIR> OPENAI_API_KEY=<KEY> bash code/run_mmmu_eval.sh --install --out <OUTPUT_DIR> --data_root <HF_DATASET_CACHE_DIR>`

---

## 1. 환경 / 재현성

| 항목 | 값 |
|---|---|
| 모델 checkpoint | `Qwen/Qwen3-VL-4B-Instruct` (`ebb281ec70b05090aa6165b016eac8ec08e71b17`, bf16) |
| 추론 백엔드 | `vLLM 0.11.0` (`max_model_len=16384`, `gpu_memory_utilization=0.9`, `max_num_seqs=256`). Qwen이 공식 평가 런타임으로 vLLM을 명시했고, 900문항을 배치로 처리해야 해서 `transformers.generate()` 대신 선택 |
| 사용 GPU | NVIDIA GeForce RTX 4090 × 1, 24564 MiB |
| 실측 peak VRAM | 22297 MiB (nvidia-smi), torch max allocated 19.90 GiB |
| 총 소요 시간 | 57분 50초 (추론 실행 기준, Judge 채점 시간 미포함; 생성 구간 55분 51초, 900문항). 분야별 시간은 아래 추정 참조 |
| 의존성 | 추론 [`code/requirements.txt`](../code/requirements.txt), 채점 [`code/scoring/requirements.txt`](../code/scoring/requirements.txt) |
| 실행 커맨드 | 아래 참조 |

추론부터 채점까지 다음 한 명령으로 실행한다. 모델·데이터 경로는 인자로 받고, 생략하면 `code/config.yaml`의 고정 repo와 revision을 사용한다.

```bash
HF_HOME=<HF_CACHE_DIR> OPENAI_API_KEY=<KEY> bash code/run_mmmu_eval.sh --install \
  --model_path Qwen/Qwen3-VL-4B-Instruct \
    --revision ebb281ec70b05090aa6165b016eac8ec08e71b17 \
      --data_root <HF_DATASET_CACHE_DIR> \
        --out <OUTPUT_DIR>
        ```

        `--data_root`는 `datasets.load_dataset(..., cache_dir=data_root)`에 그대로 전달되는 HF datasets 캐시 경로다. 실행 전에 패키지 버전, GPU, 모델·데이터 revision을 검사하고, 생성 후 900행 raw를 검증한 뒤 채점한다. `OPENAI_API_KEY`가 없으면 Judge 요청 준비까지만 하고 멈추며, 키를 설정한 뒤 `--skip_generate`를 붙여 다시 실행하면 채점을 이어서 끝낸다. 최종 실행은 900문항 모두 `status=ok`(skip 0, error 0)였고, 산출물은 [`results/mmmu_team_baseline/`](../results/mmmu_team_baseline/README.md)에 있다.

        저장된 결과의 점수는 API 없이 다시 계산하고 제출본과 바이트 단위로 대조할 수 있다.

        ```bash
        python assignment/experiments/submission/reproduce.py \
          --evaluator code/scoring/evaluate.py \
            --input results/mmmu_team_baseline/raw.jsonl \
              --metadata results/mmmu_team_baseline/run_metadata.json \
                --judge-cache results/mmmu_team_baseline/judge_cache/gpt-4.1-mini.jsonl \
                  --out <SCORING_OUTPUT_DIR> \
                    --expected results/mmmu_team_baseline/scores
                    ```

### 분야별 소요 시간 (추정)

생성은 과목이 섞인 묶음(첫 16문항, 이후 150문항씩)을 vLLM으로 동시에 디코딩하는 구조다. Qwen 공식 `run_mmmu.py`도 같은 방식으로 900문항을 한 번에 생성하고 전체 시간만 보고한다. 이 구조에서는 여러 과목이 같은 배치 안에서 동시에 생성되므로, 과목·분야별 벽시계 시간은 이 파이프라인에서 애초에 정의되지 않는 값이다.

실측하려면 과목 단위로 배치를 나눠 별도로 추론해야 하는데, 배치 구성이 바뀌면 출력도 달라진다. 실제로 같은 config의 두 8192 전량 실행을 동일 규칙으로 채점했을 때 30과목 중 25과목의 점수가 달랐다. 과목별 재추론은 이번 baseline과는 다른 실행이 되며, 이 보고서의 채점·분석 전체를 다시 요구한다. 같은 config에서도 실행 호스트에 따라 생성 시간이 3,351초와 6,026초로 달라진 사례가 있어, 벽시계 시간은 파이프라인 비교 지표로 쓰기에 안정적이지 않다.

이런 이유로 이번 보고서는 채점에 사용한 실행의 생성 구간(3,351초)을 분야별 출력 토큰 비중으로 배분해 소요 시간으로 보고한다. 출력 토큰은 동시 디코딩에서 각 문항이 실제로 차지한 계산량에 비례하므로, 배치가 섞인 구조에서 시간을 배분하는 합리적인 기준이다. prefill(이미지·텍스트 입력 처리) 시간은 포함하지 않았다. 이 방식의 안정성은 두 8192 실행에서 분야별 토큰 비중이 최대 1.4%p 차이로 거의 같았다는 점으로 확인했다([계산·과목별 추정](../assignment/experiments/gap_checks/README.md)).

| Category | 출력 토큰 | 비중 | 추정 생성 시간 (출력 토큰 비례) |
|---|--:|--:|--:|
| Art & Design | 179,329 | 9.9% | 약 5분 31초 |
| Business | 255,768 | 14.1% | 약 7분 53초 |
| Science | 297,574 | 16.4% | 약 9분 10초 |
| Health & Medicine | 137,503 | 7.6% | 약 4분 14초 |
| Humanities & Social Science | 50,806 | 2.8% | 약 1분 34초 |
| Tech & Engineering | 892,275 | 49.2% | 약 27분 29초 |
| **합계** | **1,813,255** | **100%** | **55분 51초** |

출력 토큰 비중으로 배분한 추정치에서 Tech & Engineering이 약 49.2%로 가장 크다. 이 분야에 길이 상한 종료(128건 중 77건)와 반복 후보(73건 중 32건)가 몰려 있고, 정확도도 59.52%로 가장 낮다([문항별 반복 지표](../assignment/experiments/repetition/results/per_item.jsonl), 5·7절).

---

## 2. 프롬프트

**객관식**

```text
Question: {question}
Options:
A. {option_A}
B. {option_B}
...
Please select the correct answer from the options above.
```

**주관식**

```text
Question: {question}
```

- **출처**: Qwen3-VL 공식 저장소 [`evaluation/mmmu/run_mmmu.py`](https://github.com/QwenLM/Qwen3-VL/blob/f8dca99056bb6352cf6ab36d4ea1848a09c54b5b/evaluation/mmmu/run_mmmu.py), commit `f8dca99056bb6352cf6ab36d4ea1848a09c54b5b` (Apache-2.0)
- **선택 이유**: Qwen이 공개한 MMMU 평가 프롬프트와 같은 구조를 써야 공식 수치와 비교할 수 있다. System prompt와 CoT 유도 문구는 추가하지 않았다.

이미지는 문항의 `image_N` 순서대로 텍스트 앞에 배치하고, 본문의 `<image N>` 표시는 그대로 둔다. 원 스크립트의 `Hint:` 줄은 HF 데이터셋에 `hint` 열이 없어 생략했다. 팀의 개인 탐색 실험(초기 2048/9048 config, 다중 이미지 23문항)에서는 이 배치(prefix)와 본문 삽입(inline) 사이에 유의한 차이가 없었다(43.48% vs 39.13%, 정확한 McNemar p=1; 표본이 작아 검정력이 낮다)([근거](../assignment/archive/hakyung/experiments/expD_image_layout/outputs/comparison.md)).

---

## 3. 생성(Decoding) 설정

### 3.1 Sampling recipe

| 파라미터 | 값 |
|---|---|
| `do_sample` | `true` |
| `temperature` | `0.7` |
| `top_p` | `0.8` |
| `top_k` | `20` |
| `repetition_penalty` | `1.0` |
| `presence_penalty` | `1.5` |
| `seed` | `3407` (vLLM engine seed, `SamplingParams.seed` 모두) |

- **출처**: Qwen3-VL [README](https://github.com/QwenLM/Qwen3-VL/blob/f8dca99056bb6352cf6ab36d4ea1848a09c54b5b/README.md)의 `Evaluation Reproduction > Generation Hyperparameters > Instruct models`(`greedy='false'`, `seed=3407`, `top_p=0.8`, `top_k=20`, `temperature=0.7`, `repetition_penalty=1.0`, `presence_penalty=1.5`). 위 `run_mmmu.py`의 기본값도 같다.
- **Seed**: 스크립트는 engine seed를 42로 고정하지만 README의 Instruct 재현 설정인 3407을 따랐다. 요청별 `SamplingParams.seed=3407`은 README에 없는 팀 추가값이다.
- **presence_penalty**: 개인 탐색 실험(초기 2048/9048 config, 200문항 부분집합)에서 `0`/`0.5`/`1.5`를 비교한 결과 `1.5`가 정확도(51.00%)와 파싱 실패율(8.00%) 모두 가장 나았다([근거](../assignment/archive/hakyung/experiments/expC_presence_penalty/outputs/comparison.md)).

### 3.2 생성 예산 / 이미지 해상도

| 파라미터 | 값 |
|---|---|
| `max_new_tokens` | `8192` (`max_model_len=16384`, 입력 안전 여유 128토큰) |
| 이미지 해상도 처리 | `min_pixels=1,003,520` (1280×28×28), `max_pixels=4,014,080` (5120×28×28) |

**선택 근거:** 초기 강의 자료는 RTX 4090 기준 `max_new_tokens=2048`(`max_model_length=9048`)을 참고값으로 제시했다. 과제 가이던스는 생성 예산·해상도를 팀이 인프라 trade-off에 맞춰 정하도록 하고 있어("정답 값은 없음") 이 값에 매이지 않았다. Qwen 공식 출력 예산은 README·스크립트 32768, 고정 revision 모델 카드 16384다. 공식 예산은 RTX 4090 1장에서 한 번 실행할 때 비용 $2 이내라는 팀 목표에 맞지 않아 `max_model_len=16384`로 제한했다. 이 한도에서 `8192`를 출력에 쓰면 입력 한도는 8,064토큰이며, 최종 raw의 최대 입력 5,627토큰을 잘림 없이 수용한다. `max_new_tokens=2048` 사전 실행에서는 234/900이 길이 제한으로 종료됐고 MMMU 규칙 단독 점수는 43.33%였다. 비교 대상 8192 실행(이전 전량 실행)은 108/900, 50.00%였다([8192·2048 비교](../code/scoring/README.md#검증-결과)). 두 수치 모두 Judge를 사용하지 않은 MMMU 규칙 단독 점수이며, 5절의 하이브리드 점수와 채점 조건이 다르다. 다만 2048 실행의 코드 커밋은 현재 저장소 이력에서 확인되지 않아 두 실행의 조건이 완전히 동일했음을 입증할 수 없으므로, 점수 차이를 출력 예산의 효과만으로 해석하지 않는다. 이와 별개로 개인 탐색 단계에서 budget 외 설정을 고정하고(초기 2048/9048 vs 8192/16384) 230문항 부분집합으로 비교한 결과, 정확도가 23.91%에서 38.26%로 유의하게 높아졌다(McNemar p=0.0001)([근거](../assignment/archive/hakyung/experiments/expB_budget_increase/outputs/comparison.md)). 최종 실행에서도 128/900이 상한에 도달했으므로 응답 잘림은 남아 있다(7·8절).

이미지 pixel 범위는 `run_mmmu.py`의 `MIN_PIXELS`/`MAX_PIXELS`와 같은 값이다.

---

## 4. 채점(파싱) 방식

- **사용한 파서/로직**: Qwen3-VL 답 추출 규칙 + 자체 `Final Answer` 보완 규칙 + GPT Judge fallback ([`code/scoring/evaluate.py`](../code/scoring/evaluate.py), 정책명 `hybrid100_mc_qwen_ab_open_no_length_gate_v2`)
  - 기본 파서: Qwen3-VL [`evaluation/mmmu/eval_utils.py`](https://github.com/QwenLM/Qwen3-VL/blob/96588727e44c78b25ba03ea03b8e12f7e64fd0da/evaluation/mmmu/eval_utils.py), commit `96588727e44c78b25ba03ea03b8e12f7e64fd0da` (원문 보관: [`code/scoring/frozen/`](../code/scoring/frozen/THIRD_PARTY.md))
    - Judge: `gpt-4.1-mini-2025-04-14`, `temperature=0`, `top_p=1`, `seed=3407`, `max_tokens=8`
    - **동작 방식 요약**: 아래 규칙을 순서대로 적용한다.

    **객관식**

    1. Qwen의 `can_infer` 규칙으로 선택지를 추출한다.
    2. 별도로 `Final Answer: A` 형태의 명시적 최종 답을 찾는다. 유효한 표기가 모두 같은 답이고 마지막 표기 뒤 텍스트가 100자 이하일 때만 인정한다.
    3. 두 규칙이 모두 답을 냈는데 서로 다르면 어느 쪽도 채택하지 않고 Judge로 보낸다.
    4. 충돌이 없으면 Qwen 답을, Qwen이 실패했으면 Final Answer 답을 채택한다. 둘 다 실패하면 Judge로 보낸다.

    과거 pilot에서 파서 불일치 49건을 사람이 검토했을 때 Qwen 규칙이 47건, MMMU 규칙이 2건 검토 답과 일치해 Qwen 규칙을 기본으로 삼았다. Final Answer 규칙은 별도 100문항 검토에서 100/100 일치해 보조 규칙으로 썼다([파서 선택 근거](../assignment/experiments/submission/README.md#객관식-qwen-기본-파서와-final-answer-보완)). 개인 탐색 단계에서도 자체 구현 규칙 파서와 무작위 fallback을 제외한 Qwen 공식 규칙이 900문항 전체에서 완전히 같은 결과를 냈고(문항별 diff 0/900), 규칙 실패 시 Judge(gpt-3.5-turbo-0125, Qwen 기본값)를 추가하자 정확도가 45.56%에서 49.67%로, 파싱 실패가 9.56%에서 2.89%로 개선됐다([근거](../assignment/archive/hakyung/experiments/expA_parser_comparison/outputs/parser_comparison.md)). 초기 2048/9048 config 기준이며 5절 최종 정책과는 다르다.

    **주관식**

    참조답을 `A`, `Other Answers`를 `B`로 둔 선택지로 바꿔 Qwen의 같은 추출 규칙을 적용한다. 규칙으로 판단할 수 없으면 Judge가 참조답과 모델 응답의 동치 여부를 판단한다. Final Answer 규칙은 쓰지 않는다.

    이 A/B 변환은 Qwen 공식 평가 코드의 `MMMU_preproc`([dataset_utils.py](https://github.com/QwenLM/Qwen3-VL/blob/f8dca99056bb6352cf6ab36d4ea1848a09c54b5b/evaluation/mmmu/dataset_utils.py))와 같은 방식으로, 공식값과 채점 조건을 맞추기 위해 사용했다. 같은 주관식 53문항을 MMMU 규칙으로 채점하면 20/53(37.74%)으로 A/B 방식(40/53)과 크게 다르며, 처리 방식과 문항별 판정은 [Qwen A/B와 MMMU 비교](../assignment/experiments/submission/README.md#주관식-qwen-ab와-mmmu-비교)에 정리했다.

    **Judge와 실패 처리**

    객관식 Judge에는 정답을 주지 않고 질문·선택지·모델 응답만 전달한다. `finish_reason`이 `stop`이든 `length`든 같은 절차를 적용한다. 규칙과 Judge 모두 유효한 답을 얻지 못하면 오답으로 처리하며, 공식 코드의 무작위 선택 fallback은 쓰지 않는다.

    900문항 중 **555건은 규칙으로 자동 확정**, **345건은 Judge로 전달**(규칙 실패 341, 규칙 충돌 4)했다. 최종 답 추출 실패는 **36건**(객관식 24, 주관식 12)이다.

    ---

## 5. 결과

| No. | Subject | Data Num | Acc |
|--:|---|--:|--:|
| 1 | Accounting | 30 | 73.33% |
| 2 | Agriculture | 30 | 46.67% |
| 3 | Architecture_and_Engineering | 30 | 53.33% |
| 4 | Art | 30 | 60.00% |
| 5 | Art_Theory | 30 | 80.00% |
| 6 | Basic_Medical_Science | 30 | 76.67% |
| 7 | Biology | 30 | 50.00% |
| 8 | Chemistry | 30 | 56.67% |
| 9 | Clinical_Medicine | 30 | 80.00% |
| 10 | Computer_Science | 30 | 63.33% |
| 11 | Design | 30 | 83.33% |
| 12 | Diagnostics_and_Laboratory_Medicine | 30 | 33.33% |
| 13 | Economics | 30 | 83.33% |
| 14 | Electronics | 30 | 80.00% |
| 15 | Energy_and_Power | 30 | 63.33% |
| 16 | Finance | 30 | 70.00% |
| 17 | Geography | 30 | 63.33% |
| 18 | History | 30 | 70.00% |
| 19 | Literature | 30 | 80.00% |
| 20 | Manage | 30 | 70.00% |
| 21 | Marketing | 30 | 83.33% |
| 22 | Materials | 30 | 70.00% |
| 23 | Math | 30 | 63.33% |
| 24 | Mechanical_Engineering | 30 | 40.00% |
| 25 | Music | 30 | 23.33% |
| 26 | Pharmacy | 30 | 76.67% |
| 27 | Physics | 30 | 76.67% |
| 28 | Psychology | 30 | 73.33% |
| 29 | Public_Health | 30 | 93.33% |
| 30 | Sociology | 30 | 63.33% |
| | **Overall (macro avg)** | **900** | **66.67%** |

계산식: `Overall = mean(30개 과목 accuracy)`

과목당 30문항으로 같으므로 전체 정답률 `600 / 900 = 66.67%`와 같다. 객관식은 `560/847 (66.12%)`, 주관식은 `40/53 (75.47%)`다. 과목별 정답 수는 [`results/mmmu_team_baseline/scores/subject_scores.md`](../results/mmmu_team_baseline/scores/subject_scores.md)에 있다.

**분야(category)별 결과** (MMMU 공식 분류, 분야 정확도 = 분야 정답 수 / 문항 수)

| Category | Data Num | Correct | Acc |
|---|--:|--:|--:|
| Art & Design | 120 | 74 | 61.67% |
| Business | 150 | 114 | 76.00% |
| Science | 150 | 93 | 62.00% |
| Health & Medicine | 150 | 108 | 72.00% |
| Humanities & Social Science | 120 | 86 | 71.67% |
| Tech & Engineering | 210 | 125 | 59.52% |
| **Overall** | **900** | **600** | **66.67%** |

---

## 6. 공식 수치와의 비교

| | Overall (MMMU val) |
|---|--:|
| 공식 (Qwen3-VL Technical Report) | 67.40% |
| 우리 재현 결과 | 66.67% |
| 차이 (Δ) | **−0.73%p** |

---

## 7. 격차 분석

최종 점수는 66.67%(600/900)로 공식 참조값 67.40%보다 0.73%p 낮다. 생성 config와 GPU 모델이 같은 두 실행은 600/900과 608/900으로 0.89%p 차이를 보였다([근거](../code/scoring/README.md#검증-결과)). 공식값과의 격차 0.73%p는 이 두 실행 사이에서 관측된 차이보다 작았다.

채점 조건도 점수를 이 정도로 움직인다. 동일한 최종 raw와 당시 채점 정책을 고정하고 Judge만 GPT-4.1-mini에서 GPT-4o-mini로 바꾸자 3.00%p 하락했다([근거](../assignment/experiments/submission/README.md#judge-모델-비교)). Qwen 공개 평가 코드는 규칙 및 Judge를 통한 답 추출이 최종적으로 실패하면(Judge를 최대 25회 재시도한 뒤) 선택지와 Z 중 하나를 무작위로 고르지만, 우리는 최종 추출 실패를 오답 처리했다. 우리 파이프라인의 최종 추출 실패 36건에 같은 랜덤 fallback을 가정하면 기대 정답은 21/5 + 3/4 + 12/3 = 8.95건(+0.99%p)이다([계산](../assignment/experiments/gap_checks/README.md)). 이는 공식 evaluator를 쓰면 실제로 이만큼 오른다는 뜻이 아니라, Judge·미추출 처리 차이를 격차의 원인 후보로 보는 근거다.

출력 상한에 도달한 128건의 정확도는 35.94%로 정상 종료의 71.76%보다 낮고, 이 중 67건이 반복 후보였다. 반복 후보 73건의 반복 시작 위치 중앙값은 응답 문자 길이의 23%다([근거](../assignment/experiments/repetition/results/REPORT.md#2-종료-사유를-나눈-비교)). 출력 예산뿐 아니라 생성 중 반복이 답 완결을 막았을 가능성이 있으며, 16384·32768 예산의 효과는 측정하지 않았다.

---

## 8. 기타 특이사항 / 한계

- Seed를 고정해도 vLLM 생성은 bit 단위로 재현되지 않았다. 배치 구성이 달라지면 출력이 바뀐다. 8192 전량 실행 세 번의 `length` 종료 수는 108/114/128건이었다.
- 실행 편차를 0.89%p로 추정한 근거는 전량 실행 두 번뿐이다. 신뢰구간을 내려면 반복 실행이 더 필요하다.
- `max_new_tokens` 16384·32768의 효과는 측정하지 않았다.
- 과목·분야별 소요 시간은 실측이 아닌 출력 토큰 비중 기반 추정이다(1절). 다음 평가부터는 묶음별 경과 시간과 문항 ID를 결과 파일에 기록한다.
- 파인튜닝 방향으로는 length 종료와 반복·미완결 감소를 우선 검토한다(7절).
- Final Answer 규칙의 사람 검증은 이전 899문항 pilot(생성 seed 42)을 대상으로 했으며, 최신 raw 전체를 다시 검증하지는 않았다.
- 주관식은 참조답을 Judge에 주는 동치 판정이라, 정답을 숨기는 객관식 Judge와 평가 구조가 다르다.
- 실행 당시 경로와 실제 실행 명령은 [`run_metadata.supplement.json`](../results/mmmu_team_baseline/run_metadata.supplement.json)에 보완 기록했다.
- 개인 탐색 실험에서 seed 3개(42/3407/1234)로 900문항 전체를 다시 생성해 비교한 결과, macro 정확도 표준편차는 0.0038이고 seed 쌍 간 McNemar 검정은 모두 유의하지 않았다(초기 2048/9048 config)([근거](../assignment/archive/hakyung/experiments/expF_seed_repro/outputs/comparison.md)). 최종 8192 파이프라인에서 다시 측정하지는 않았다.

