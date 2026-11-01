---
base_model: Qwen/Qwen3-VL-4B-Instruct
library_name: peft
tags:
- lora
- qwen3-vl
---

# hypB-e1-structured-3k

가설 B(구조화된 풀이 SFT) E1 모델의 LoRA adapter입니다. 역할: 정리 풀이 학습 (주 실험).

> **학습 완료** · run-yoonseok 브랜치의 마지막 checkpoint-188 adapter입니다.

## 학습 데이터

`MMDL-team4/hypB-train-data` v1.1 (태그 객체 `e9fe258b9d044e0693441a4c54138054d19130ab` → 실제 커밋 `1833bac3be047aa8bd146492436323bb7c14092a`) `E1_train_swift.jsonl` (3,000문항)

- 응답 형식: 정리 풀이(`</think>` 뒤) + 마지막 줄 `Final Answer: X`
- 병합 모델은 기본으로 올리지 않습니다. 평가 때 원본 모델과 adapter를 병합합니다.

## 원본 모델

`Qwen/Qwen3-VL-4B-Instruct`, revision `ebb281ec70b05090aa6165b016eac8ec08e71b17`, bf16

## 학습 설정

| 항목 | 값 |
|---|---|
| 도구 | ms-swift |
| 학습 범위 | 언어모델 LoRA만. 시각 인코더·merger(DeepStack 포함) 고정 |
| LoRA | r 16, α 32, dropout 0.05, q·k·v·o·gate·up·down (언어모델 36층) |
| 최적화 | AdamW, lr 1e-4, cosine, warmup 3%, weight decay 0, 1 epoch |
| 배치 | 장치당 1 × 누적 16 (약 188 step) |
| 손실 | assistant 응답 토큰만 |
| 이미지 | min_pixels 1,003,520 / max_pixels 4,014,080 (평가와 동일) |
| 최대 길이 | 8,192 토큰 |

E1(`hypB-e1-structured-3k`)과 E2(`hypB-e2-answer-3k`)는 데이터 파일만 다르고 나머지 설정은 같습니다. 둘 다 원본 모델에서 각각 시작합니다.

## 기록

| 항목 | 값 |
|---|---|
| 학습 코드 (Git 커밋) | `b54e00d2ae9e91cc5a93641b4d2da0551cfa93dd` |
| ms-swift / transformers 버전 | 3.12.3 / 4.57.1 |
| GPU | NVIDIA RTX 6000 Ada Generation, 49,140 MiB |
| 학습 시간 · step 수 | 3378.85초 (56.31분), 188 step, 1 epoch |

## 사용 규칙

- 팀 내부용 비공개 저장소입니다.
- 평가에 사용한 버전은 태그(예: `v1.0`)로 고정하고, 고정된 태그의 내용은 수정하지 않습니다.

## run-yoonseok 실행 결과

| 항목 | 값 |
|---|---|
| Epoch 평균 train loss | 0.44173074 |
| 마지막 step train loss | 0.35753852 |
| 마지막 holdout loss (step 188) | 0.38542396 |
| 시작점 | 고정 revision 원본 모델, adapter 없음, resume 없음 |
| Holdout 평가 step | 60, 120, 180 및 ms-swift 기본 최종 평가 188 |
| 평가 로딩 | 마지막 checkpoint-188을 bf16 병합 후 vLLM 0.11.0 로딩 통과 |
| 이미지 | runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404 |
| GPU 최대 사용량 (1초 샘플링) | 45.23 GiB |

학습 설정은 train_config.json과 train_args.json, loss 기록은 training_history.json과 train_log.txt에 보관했습니다. 전체 패키지 목록은 packages_train.txt와 packages_eval.txt에 기록했습니다.
