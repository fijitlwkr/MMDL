# MMMU-val Baseline Evaluation Report — Qwen3-VL-4B-Instruct

<!-- 1~3절 기준 최종 8192 전량 실행 폴더: assignment/runs/max_new_tokens8192_hakyung -->

- **팀명**: Team4
- **팀원**: 이하경, 채윤석, 트란트룽하우, 홍성준
- **작성일**: 2026.09.25
- **재현 커맨드**: `최종 파이프라인 완성 시 작성`

---

## 1. 환경 / 재현성

| 항목 | 값 |
|---|---|
| 모델 checkpoint | `Qwen/Qwen3-VL-4B-Instruct` (ebb281ec70b05090aa6165b016eac8ec08e71b17) |
| 추론 백엔드 | `vllm==0.11.0`; `gpu_memory_utilization=0.9`, `max_model_len=16384`, `max_num_batched_tokens=8192`, `max_num_seqs=256`, `limit_mm_per_prompt={image: 10, video: 0}`, `trust_remote_code=true` (근거: `assignment/src/requirements.txt`, `assignment/src/config.yaml`, `assignment/runs/max_new_tokens8192_hakyung/run_metadata.json`) |
| 사용 GPU | NVIDIA GeForce RTX 4090, 24564 MiB (근거: `assignment/runs/max_new_tokens8192_hakyung/env_check.json`의 `gpu` 섹션; driver 580.159.04, CUDA header 13.0) |
| 실측 peak VRAM | nvidia-smi 최대 사용량 **22297 MiB** (env.json sampler); torch `max_allocated_gib` **19.8962 GiB**, `max_reserved_gib` **20.5977 GiB** (env.json) |
| 총 소요 시간 | 총 57분 50초 (3469.539초), 생성 구간 55분 51초 (3351.217초), 900문항 (근거: assignment/runs/max_new_tokens8192_hakyung/env.json) |
| 의존성 | [`assignment/src/requirements.txt`](../assignment/src/requirements.txt); 저장소에는 `assignment/sungjun/requirements.lock.txt`가 있으나 이 실행에서 사용했다는 근거는 문서에 없음 |
| 실행 커맨드 | `최종 파이프라인 완성 시 작성` |

## 2. 프롬프트

**실제 모델에 들어간 프롬프트 전문** (변수 부분은 `{}`로 표시):

```
Question: {question}
Options:
{options}
Please select the correct answer from the options above.
```

open 문항:

```
Question: {question}
```
- **출처**: `https://github.com/QwenLM/Qwen3-VL`, `evaluation/mmmu/run_mmmu.py`, commit `f8dca99056bb6352cf6ab36d4ea1848a09c54b5b`, Apache-2.0 (근거: `assignment/src/common.py` 헤더 주석)
- **선택 이유**: HF validation schema를 사용하고 선택지 문자를 목록 위치에서 생성하며, hint가 없는 데이터에 맞춰 optional hint를 생략하고 image marker를 보존한다. CoT는 비활성화한다 (근거: `assignment/src/common.py` 헤더 주석).

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
| `seed` | `3407` |

- **출처**: `sampling.seed=3407`은 README에 없는 팀 추가값이다. `engine_seed=3407`은 GitHub README의 `Evaluation Reproduction > Generation Hyperparameters > Instruct models` 값을 따른다. `temperature=0.7`, `top_p=0.8`, `top_k=20`, `presence_penalty=1.5`, `repetition_penalty=1.0`, `do_sample=true`, `stop_token_ids=[]`의 기준은 `assignment/src/config.yaml` 주석과 실행 설정이다.

### 3.2 생성 예산 / 이미지 해상도

| 파라미터 | 값 |
|---|---|
| `max_new_tokens` | `8192` |
| 이미지 해상도 처리 (`min_pixels`/`max_pixels` 등) | `min_pixels = 1280*28*28 = 1,003,520`, `max_pixels = 5120*28*28 = 4,014,080` |

**선택 근거**: `max_new_tokens=8192`는 RunPod RTX 4090 1회 실행 비용을 2달러 이하로 맞추려는 팀 결정이다 (근거: `assignment/src/config.yaml` 주석). 8192 대 2048의 정확도·95% CI·비용 비교 수치는 정확도-비용 비교 실험(별첨/부록 참조)에서 확인한다; 구체 수치는 이 절에서 비워 둔다.

## 4. 채점(파싱) 방식

- 사용한 파서/로직: _(자체 구현 / 차용 도구명 + 링크)_
- 동작 방식 요약: _(예: 어떤 순서로 규칙을 적용하는지, 실패 시 fallback은 무엇인지)_

## 5. 결과

| No. | Subject | Data Num | Acc |
|---|---|---|---|
| 1 | Accounting | 30 | |
| 2 | Agriculture | 30 | |
| 3 | Architecture_and_Engineering | 30 | |
| 4 | Art | 30 | |
| 5 | Art_Theory | 30 | |
| 6 | Basic_Medical_Science | 30 | |
| 7 | Biology | 30 | |
| 8 | Chemistry | 30 | |
| 9 | Clinical_Medicine | 30 | |
| 10 | Computer_Science | 30 | |
| 11 | Design | 30 | |
| 12 | Diagnostics_and_Laboratory_Medicine | 30 | |
| 13 | Economics | 30 | |
| 14 | Electronics | 30 | |
| 15 | Energy_and_Power | 30 | |
| 16 | Finance | 30 | |
| 17 | Geography | 30 | |
| 18 | History | 30 | |
| 19 | Literature | 30 | |
| 20 | Manage | 30 | |
| 21 | Marketing | 30 | |
| 22 | Materials | 30 | |
| 23 | Math | 30 | |
| 24 | Mechanical_Engineering | 30 | |
| 25 | Music | 30 | |
| 26 | Pharmacy | 30 | |
| 27 | Physics | 30 | |
| 28 | Psychology | 30 | |
| 29 | Public_Health | 30 | |
| 30 | Sociology | 30 | |
| | **Overall (macro avg)** | **900** | |

계산식: `Overall = mean(30개 과목 accuracy)` _(다른 방식을 썼다면 명시)_

## 6. 공식 수치와의 비교

| | Overall (MMMU val) |
|---|---|
| 공식 (Qwen3-VL Technical Report) | 67.4 |
| 우리 재현 결과 | |
| 차이 (Δ) | |

## 7. 격차 분석

_(1000 char 이내로 작성 - Official 성능과 차이가 발생하는지, 그렇다면 그 이유를 서술. 길게 쓴다고 credit이 느는 게
아니라, 근거의 질이 핵심입니다. 레포트는 짧을수록 좋습니다.)_


## 8. 기타 특이사항 / 한계 (Optional)

_(재현 중 겪은 문제, 시간 관계상 못 해본 것, 다음에 시도해보고 싶은 것 등. 자유롭게)_
